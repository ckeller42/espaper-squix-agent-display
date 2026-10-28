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

#include <ESP8266mDNS.h>  // host shim: scripted answers

#include "../../EspaperClient/configportal.h"
#include "../../EspaperClient/discovery.h"

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
}
