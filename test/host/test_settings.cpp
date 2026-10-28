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

#include "../../EspaperClient/configportal.h"

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

void run_settings_tests() {
  UnitySetTestFile(__FILE__);  // so failures name this file, not the one that owns main()
  RUN_TEST(test_stored_server_url_overrides_the_compiled_default);
  RUN_TEST(test_absent_stored_url_falls_back_to_the_compiled_default);
  RUN_TEST(test_an_empty_stored_url_falls_back_to_the_compiled_default);
  RUN_TEST(test_a_url_saved_from_the_form_survives_a_reload);
  RUN_TEST(test_saving_the_default_does_not_pin_it_as_a_stored_value);
  RUN_TEST(test_the_portal_form_offers_the_server_url_field);
}
