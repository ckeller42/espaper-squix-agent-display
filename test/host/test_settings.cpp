// The config portal's real save/load code (configportal.h, compiled unmodified for the host) against
// the in-memory DEVICE_FS. Only the web server is stood in for (shims/ESP8266WebServer.h): it records
// what the portal sends and returns the form fields a test "posts". Nothing here proves the HTML
// renders in a browser or that LittleFS behaves -- only that the firmware's own save/load logic
// round-trips SERVER_URL and falls back to the compiled default.
#define ESPAPER29BW  // pick a device so settings.h defines the screen type artwork.h needs
#include <Arduino.h>
#include <MiniGrafx.h>
#include <MiniGrafxFonts.h>
#include <unity.h>

#include <cstring>  // strstr in the assertions below

#include <ESP8266mDNS.h>  // host shim: scripted answers

#include "../../EspaperClient/configportal.h"
#include "../../EspaperClient/discovery.h"
#include "../../EspaperClient/goneGuard.h"

// board_stubs.h (the other translation unit) defines the rest of BoardClass; the portal's info page
// also asks for the chip id.
String BoardClass::getChipId() { return "host-chip"; }

// Captured during static initialisation, before any test can change SERVER_URL.
static const String COMPILED_DEFAULT = SERVER_URL;

// A minimal valid config -- loadConfig() reports false without SSID, password and time zone.
static const char *BASE_CONFIG =
    "WIFI_SSID=net\r\nWIFI_PASS=pw\r\nTIMEZONE=Europe/Berlin CET-1CEST\r\n";

static void storeConfig(const std::string &extraLines) {
  DEVICE_FS.files["/espaper.txt"] = std::string(BASE_CONFIG) + extraLines;
}

static void resetPortalState() {
  resetUserSettings();
  server.posted.clear();
  server.sent.clear();
}

void test_stored_server_url_overrides_the_compiled_default() {
  resetPortalState();
  storeConfig("SERVER_URL=http://odelly.local:8411\r\n");

  TEST_ASSERT_TRUE(loadConfig());

  TEST_ASSERT_EQUAL_STRING("http://odelly.local:8411", SERVER_URL.c_str());
}

void test_absent_stored_url_falls_back_to_the_compiled_default() {
  resetPortalState();
  storeConfig("");  // an un-provisioned device, or one saved by a build before this setting existed

  TEST_ASSERT_TRUE(loadConfig());

  TEST_ASSERT_EQUAL_STRING(COMPILED_DEFAULT.c_str(), SERVER_URL.c_str());
}

void test_an_empty_stored_url_falls_back_to_the_compiled_default() {
  resetPortalState();
  storeConfig("SERVER_URL=\r\n");  // a blanked field must not leave the device with no server

  TEST_ASSERT_TRUE(loadConfig());

  TEST_ASSERT_EQUAL_STRING(COMPILED_DEFAULT.c_str(), SERVER_URL.c_str());
}

void test_a_url_saved_from_the_form_survives_a_reload() {
  resetPortalState();
  server.posted = {{"ssid", "net"}, {"password", "pw"}, {"updateIntervalMins", "20"},
                   {"timeZone", "Europe/Berlin CET-1CEST"}, {"ntpServers", "pool.ntp.org"},
                   {"serverUrl", "http://odelly.local:8411"}};

  handleSave();
  resetUserSettings();  // as after a reboot: RAM is back to the compiled defaults
  TEST_ASSERT_TRUE(loadConfig());

  TEST_ASSERT_EQUAL_STRING("http://odelly.local:8411", SERVER_URL.c_str());
}

void test_saving_the_default_does_not_pin_it_as_a_stored_value() {
  resetPortalState();
  server.posted = {{"ssid", "net"}, {"password", "pw"}, {"updateIntervalMins", "20"},
                   {"timeZone", "Europe/Berlin CET-1CEST"}, {"ntpServers", "pool.ntp.org"},
                   {"serverUrl", COMPILED_DEFAULT.c_str()}};

  handleSave();

  // Otherwise saving any other setting would freeze today's default into flash, and a later
  // firmware with a new default (or a discovered URL, Task 4) could not tell it from a hand-entered one.
  TEST_ASSERT_EQUAL(std::string::npos, DEVICE_FS.files["/espaper.txt"].find("SERVER_URL"));
}

void test_the_portal_form_offers_the_server_url_field() {
  resetPortalState();
  SERVER_URL = "http://odelly.local:8411";

  handleRoot();

  TEST_ASSERT_NOT_EQUAL(std::string::npos, server.sent.find("name='serverUrl'"));
  TEST_ASSERT_NOT_EQUAL(std::string::npos, server.sent.find("value='http://odelly.local:8411'"));
}

// ---- Task 4: what discovery does to the stored setting. These live here, not in test_discovery.cpp,
// because only this translation unit may include configportal.h (its functions are not inline).

void test_a_discovered_url_is_persisted_for_next_wake() {
  resetPortalState();
  storeConfig("");  // a device with no stored server: it runs on the compiled default
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("", SERVER_URL_SOURCE.c_str());  // absent source key == compiled default

  MDNS.reset();
  MDNS.answers = {{IPAddress(192, 168, 1, 9), 8411}};
  String found = discoverServer();
  TEST_ASSERT_TRUE(saveDiscoveredServerUrl(found));

  resetUserSettings();  // next wake: RAM is back to the compiled defaults
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("http://192.168.1.9:8411", SERVER_URL.c_str());
  TEST_ASSERT_EQUAL_STRING("discovered", SERVER_URL_SOURCE.c_str());
  MDNS.reset();
}

void test_a_discovered_url_may_be_replaced_by_a_later_discovery() {
  resetPortalState();
  storeConfig("SERVER_URL=http://192.168.1.9:8411\r\nSERVER_URL_SOURCE=discovered\r\n");
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_TRUE(saveDiscoveredServerUrl("http://10.0.0.8:8411"));
  resetUserSettings();
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("http://10.0.0.8:8411", SERVER_URL.c_str());
}

void test_the_config_portal_value_is_never_overwritten_by_discovery() {
  resetPortalState();
  server.posted = {{"ssid", "net"}, {"password", "pw"}, {"updateIntervalMins", "20"},
                   {"timeZone", "Europe/Berlin CET-1CEST"}, {"ntpServers", "pool.ntp.org"},
                   {"serverUrl", "http://odelly.local:8411"}};
  handleSave();  // someone types an address into the portal

  MDNS.reset();
  MDNS.answers = {{IPAddress(192, 168, 1, 9), 8411}};
  TEST_ASSERT_FALSE(saveDiscoveredServerUrl(discoverServer()));

  // Not only in RAM -- "permanently": across wakes, and across later unrelated saves.
  for (int wake = 0; wake < 3; wake++) {
    resetUserSettings();
    TEST_ASSERT_TRUE(loadConfig());
    TEST_ASSERT_EQUAL_STRING("http://odelly.local:8411", SERVER_URL.c_str());
    TEST_ASSERT_EQUAL_STRING("manual", SERVER_URL_SOURCE.c_str());
    TEST_ASSERT_FALSE(saveDiscoveredServerUrl("http://192.168.1.9:8411"));
    saveDeviceRegistration("id", "secret");  // an unrelated saveConfig() must not demote it either
  }
  MDNS.reset();
}

void test_a_url_stored_before_the_source_key_existed_counts_as_manual() {
  resetPortalState();
  storeConfig("SERVER_URL=http://odelly.local:8411\r\n");  // written by Task 2's portal: only a person did that
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("manual", SERVER_URL_SOURCE.c_str());
  TEST_ASSERT_FALSE(saveDiscoveredServerUrl("http://192.168.1.9:8411"));
}

void test_resaving_the_portal_does_not_turn_a_discovered_url_into_a_manual_one() {
  resetPortalState();
  storeConfig("SERVER_URL=http://192.168.1.9:8411\r\nSERVER_URL_SOURCE=discovered\r\n");
  TEST_ASSERT_TRUE(loadConfig());
  // the form is pre-filled with the discovered URL; changing only the WiFi password re-posts it unchanged
  server.posted = {{"ssid", "net"}, {"password", "other"}, {"updateIntervalMins", "20"},
                   {"timeZone", "Europe/Berlin CET-1CEST"}, {"ntpServers", "pool.ntp.org"},
                   {"serverUrl", "http://192.168.1.9:8411"}};
  handleSave();
  resetUserSettings();
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("discovered", SERVER_URL_SOURCE.c_str());
}

void test_blanking_the_portal_field_returns_to_the_default_and_to_discoverable() {
  resetPortalState();
  storeConfig("SERVER_URL=http://odelly.local:8411\r\nSERVER_URL_SOURCE=manual\r\n");
  TEST_ASSERT_TRUE(loadConfig());
  server.posted = {{"ssid", "net"}, {"password", "pw"}, {"updateIntervalMins", "20"},
                   {"timeZone", "Europe/Berlin CET-1CEST"}, {"ntpServers", "pool.ntp.org"},
                   {"serverUrl", ""}};
  handleSave();
  resetUserSettings();
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("", SERVER_URL_SOURCE.c_str());
  TEST_ASSERT_TRUE(saveDiscoveredServerUrl("http://192.168.1.9:8411"));  // the owner gave up control
}

// ---- Task 7: a repeated 410 sleeps instead of restarting -------------------------------------------

static DeviceData freshDeviceData() {
  DEVICE_FS.files.erase("/device-data.txt");
  DeviceData d;
  loadDeviceData(&d);  // no file: the struct is initialised
  return d;
}

void test_the_first_410_restarts_and_a_repeat_sleeps() {
  DeviceData d = freshDeviceData();
  TEST_ASSERT_FALSE(recordGoneShouldSleep(&d));  // the healthy case stays fast
  TEST_ASSERT_TRUE(recordGoneShouldSleep(&d));
  TEST_ASSERT_TRUE(recordGoneShouldSleep(&d));  // and keeps sleeping while the 410s continue
}

void test_a_screen_resets_the_410_count() {
  DeviceData d = freshDeviceData();
  recordGoneShouldSleep(&d);
  clearGoneCount(&d);
  TEST_ASSERT_FALSE(recordGoneShouldSleep(&d));
}

void test_the_410_count_survives_the_restart_it_precedes() {
  DeviceData d = freshDeviceData();
  recordGoneShouldSleep(&d);
  saveDeviceData(&d);  // what the 410 path does before ESP.restart()
  DeviceData reborn;
  loadDeviceData(&reborn);
  TEST_ASSERT_TRUE(recordGoneShouldSleep(&reborn));
}

void test_the_410_count_saturates_instead_of_wrapping_to_zero() {
  DeviceData d = freshDeviceData();
  for (int i = 0; i < 600; i++) recordGoneShouldSleep(&d);
  TEST_ASSERT_TRUE(recordGoneShouldSleep(&d));
}

void run_settings_tests() {
  UnitySetTestFile(__FILE__);  // so failures name this file, not the one that owns main()
  RUN_TEST(test_stored_server_url_overrides_the_compiled_default);
  RUN_TEST(test_absent_stored_url_falls_back_to_the_compiled_default);
  RUN_TEST(test_an_empty_stored_url_falls_back_to_the_compiled_default);
  RUN_TEST(test_a_url_saved_from_the_form_survives_a_reload);
  RUN_TEST(test_saving_the_default_does_not_pin_it_as_a_stored_value);
  RUN_TEST(test_the_portal_form_offers_the_server_url_field);
  RUN_TEST(test_a_discovered_url_is_persisted_for_next_wake);
  RUN_TEST(test_a_discovered_url_may_be_replaced_by_a_later_discovery);
  RUN_TEST(test_the_config_portal_value_is_never_overwritten_by_discovery);
  RUN_TEST(test_a_url_stored_before_the_source_key_existed_counts_as_manual);
  RUN_TEST(test_resaving_the_portal_does_not_turn_a_discovered_url_into_a_manual_one);
  RUN_TEST(test_blanking_the_portal_field_returns_to_the_default_and_to_discoverable);
  RUN_TEST(test_the_first_410_restarts_and_a_repeat_sleeps);
  RUN_TEST(test_a_screen_resets_the_410_count);
  RUN_TEST(test_the_410_count_survives_the_restart_it_precedes);
  RUN_TEST(test_the_410_count_saturates_instead_of_wrapping_to_zero);
}

// --- serial configuration ----------------------------------------------------------------------
// The USB serial line is the only configuration channel that still works when the device's setup
// access point cannot be reached -- a host that drops the AP association mid-POST, a host with one
// radio that must stay on the LAN, an AP out of range. Nothing here proves bytes arrive over UART
// (the host shim has no inbound serial); it proves the command grammar, that "show" masks the
// password, and that "save" writes a config the firmware's own loadConfig() reads back.

// settings.h declares its globals as file-static, so a second translation unit including
// configportal.h would get its own copies (and duplicate every non-inline function). These tests
// therefore live beside test_settings.cpp's, in the one TU that owns the config portal.
static void resetSerialConfig() {
  resetUserSettings();
  DEVICE_FS.files.clear();
}

static SerialConfigOutcome run(const char *line) { return applySerialConfigCommand(String(line)); }

void test_set_ssid_stores_the_value() {
  resetSerialConfig();
  SerialConfigOutcome out = run("set ssid Insel");
  TEST_ASSERT_EQUAL_STRING("Insel", WIFI_SSID.c_str());
  TEST_ASSERT_FALSE(out.restart);
}

void test_a_value_may_contain_spaces() {
  resetSerialConfig();
  run("set timezone Europe/Berlin CET-1CEST,M3.5.0,M10.5.0/3");
  TEST_ASSERT_EQUAL_STRING("Europe/Berlin CET-1CEST,M3.5.0,M10.5.0/3", TIMEZONE.c_str());
}

void test_a_password_is_taken_verbatim_including_spaces_and_equals() {
  resetSerialConfig();
  run("set password a b=c ");
  TEST_ASSERT_EQUAL_STRING("a b=c ", WIFI_PASS.c_str());
}

void test_show_never_prints_the_password() {
  resetSerialConfig();
  run("set ssid Insel");
  run("set password hunter2hunter2");
  String reply = run("show").reply;
  TEST_ASSERT_NULL(strstr(reply.c_str(), "hunter2hunter2"));
  TEST_ASSERT_NOT_NULL(strstr(reply.c_str(), "Insel"));
  TEST_ASSERT_NOT_NULL(strstr(reply.c_str(), "password=(set)"));
}

void test_show_says_when_no_password_is_set() {
  resetSerialConfig();
  TEST_ASSERT_NOT_NULL(strstr(run("show").reply.c_str(), "password=(unset)"));
}

void test_save_writes_a_config_the_firmware_reads_back() {
  resetSerialConfig();
  run("set ssid Insel");
  run("set password pw");
  run("set timezone Europe/Berlin CET-1CEST,M3.5.0,M10.5.0/3");
  TEST_ASSERT_TRUE(run("save").saved);
  resetUserSettings();
  TEST_ASSERT_TRUE(loadConfig());
  TEST_ASSERT_EQUAL_STRING("Insel", WIFI_SSID.c_str());
  TEST_ASSERT_EQUAL_STRING("pw", WIFI_PASS.c_str());
}

void test_save_refuses_an_incomplete_config() {
  resetSerialConfig();
  run("set ssid Insel");  // no password, no time zone
  SerialConfigOutcome out = run("save");
  TEST_ASSERT_FALSE(out.saved);
  TEST_ASSERT_NOT_NULL(strstr(out.reply.c_str(), "ERR"));
}

void test_setting_a_server_url_marks_it_as_entered_by_hand() {
  resetSerialConfig();
  run("set server http://192.168.178.43:8411");
  TEST_ASSERT_EQUAL_STRING("http://192.168.178.43:8411", SERVER_URL.c_str());
  TEST_ASSERT_EQUAL_STRING(SERVER_URL_SOURCE_MANUAL, SERVER_URL_SOURCE.c_str());
}

void test_blanking_the_server_url_returns_to_the_default_and_to_discoverable() {
  resetSerialConfig();
  run("set server http://elsewhere:9000");
  run("set server");
  TEST_ASSERT_EQUAL_STRING(SERVER_URL_DEFAULT.c_str(), SERVER_URL.c_str());
  TEST_ASSERT_EQUAL_STRING("", SERVER_URL_SOURCE.c_str());
}

void test_interval_is_read_as_a_number() {
  resetSerialConfig();
  run("set interval 30");
  TEST_ASSERT_EQUAL_INT(30, UPDATE_INTERVAL_MINS);
}

void test_restart_is_reported_to_the_caller() {
  resetSerialConfig();
  TEST_ASSERT_TRUE(run("restart").restart);
}

void test_an_unknown_command_is_refused_and_changes_nothing() {
  resetSerialConfig();
  run("set ssid Insel");
  SerialConfigOutcome out = run("set nonsense x");
  TEST_ASSERT_NOT_NULL(strstr(out.reply.c_str(), "ERR"));
  TEST_ASSERT_EQUAL_STRING("Insel", WIFI_SSID.c_str());
}

void test_surrounding_whitespace_and_cr_are_ignored() {
  resetSerialConfig();
  run("  set ssid Insel\r");
  TEST_ASSERT_EQUAL_STRING("Insel", WIFI_SSID.c_str());
}

void test_an_empty_line_is_ignored_without_an_error() {
  resetSerialConfig();
  SerialConfigOutcome out = run("   ");
  TEST_ASSERT_EQUAL_STRING("", out.reply.c_str());
  TEST_ASSERT_FALSE(out.saved);
  TEST_ASSERT_FALSE(out.restart);
}

void test_help_lists_every_command() {
  resetSerialConfig();
  String reply = run("help").reply;
  for (const char *name : {"ssid", "password", "timezone", "ntp", "server", "interval", "show",
                           "save", "restart"}) {
    TEST_ASSERT_NOT_NULL(strstr(reply.c_str(), name));
  }
}

void run_serial_config_tests() {
  UnitySetTestFile(__FILE__);
  RUN_TEST(test_set_ssid_stores_the_value);
  RUN_TEST(test_a_value_may_contain_spaces);
  RUN_TEST(test_a_password_is_taken_verbatim_including_spaces_and_equals);
  RUN_TEST(test_show_never_prints_the_password);
  RUN_TEST(test_show_says_when_no_password_is_set);
  RUN_TEST(test_save_writes_a_config_the_firmware_reads_back);
  RUN_TEST(test_save_refuses_an_incomplete_config);
  RUN_TEST(test_setting_a_server_url_marks_it_as_entered_by_hand);
  RUN_TEST(test_blanking_the_server_url_returns_to_the_default_and_to_discoverable);
  RUN_TEST(test_interval_is_read_as_a_number);
  RUN_TEST(test_restart_is_reported_to_the_caller);
  RUN_TEST(test_an_unknown_command_is_refused_and_changes_nothing);
  RUN_TEST(test_surrounding_whitespace_and_cr_are_ignored);
  RUN_TEST(test_an_empty_line_is_ignored_without_an_error);
  RUN_TEST(test_help_lists_every_command);
}
