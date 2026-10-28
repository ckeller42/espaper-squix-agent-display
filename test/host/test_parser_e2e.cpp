// The firmware's own EspaperParser, compiled for the host, talking to the real Python server.
// Only the Arduino/socket/graphics edges are shimmed (test/host/shims); every line of
// EspaperParser.cpp that parses a URL, builds a request or reads a response runs unmodified.
#include <Arduino.h>
#include <MiniGrafx.h>
#include <sys/wait.h>
#include <unity.h>

#include <csignal>

// dissectUrl() and the Url struct are private; the test needs to call them directly.
#define private public
#include "../../EspaperClient/EspaperParser.h"
#undef private

#include "board_stubs.h"

static const size_t PAYLOAD_BYTES = 4742;

// ---- the live server, started and stopped by this harness -----------------------------------

static pid_t serverPid = -1;
static int serverStdin = -1;
static int serverPort = 0;
static long serverSleepSeconds = 0;
static long serverSleepUntil = 0;

static void startServer() {
  int out[2], in[2];
  if (pipe(out) != 0 || pipe(in) != 0) { perror("pipe"); exit(1); }
  serverPid = fork();
  if (serverPid == 0) {
    dup2(out[1], STDOUT_FILENO);
    dup2(in[0], STDIN_FILENO);
    close(out[0]); close(out[1]); close(in[0]); close(in[1]);
    const char *py = getenv("ESPAPER_TEST_PYTHON");
    execl(py ? py : "server/.venv/bin/python", "python", "test/host/live_server.py", (char *)nullptr);
    perror("exec server");
    _exit(127);
  }
  close(out[1]); close(in[0]);
  serverStdin = in[1];
  FILE *f = fdopen(out[0], "r");
  if (!f || fscanf(f, "%d %ld %ld", &serverPort, &serverSleepSeconds, &serverSleepUntil) != 3) {
    fprintf(stderr, "live server did not report a port\n");
    exit(1);
  }
}

static void stopServer() {
  if (serverStdin >= 0) close(serverStdin);  // EOF on its stdin is the shutdown signal
  if (serverPid > 0) {
    int status;
    waitpid(serverPid, &status, 0);
  }
}

// ---- helpers --------------------------------------------------------------------------------

static MiniGrafx gfx;

static String serverUrl() { return String("http://127.0.0.1:") + String(serverPort); }

static EspaperParser makeParser(const String &secret = "") {
  return EspaperParser(&gfx, "", serverUrl(), secret, "host-1");
}

static EspaperParser::DeviceIdAndSecret registerOnServer(EspaperParser &p) {
  return p.registerDevice("/public/devices",
                          "{\"macAddress\":\"AA:BB:CC:DD:EE:FF\",\"deviceType\":\"Espaper29Bw\",\"timeZone\":\"Europe/Berlin\"}");
}

static bool drew(const std::string &call) {
  for (auto &c : gfx.calls) if (c == call) return true;
  return false;
}

void setUp() {
  gfx.calls.clear();
  DEVICE_FS.files.clear();
}
void tearDown() {}

// ---- dissectUrl (pure firmware code) ----------------------------------------------------------

void test_dissect_url_accepts_a_hostname() {  // spec decision 13: the device discovers its server by name
  EspaperParser p = makeParser();
  auto u = p.dissectUrl("http://odelly.fritz.box:8080/public/devices");
  TEST_ASSERT_EQUAL_STRING("http", u.protocol.c_str());
  TEST_ASSERT_EQUAL_STRING("odelly.fritz.box", u.host.c_str());
  TEST_ASSERT_EQUAL(8080, u.port);
  TEST_ASSERT_EQUAL_STRING("/public/devices", u.path.c_str());
}

void test_dissect_url_defaults_the_port_for_http() {
  EspaperParser p = makeParser();
  auto u = p.dissectUrl("http://odelly.fritz.box/public/devices");
  TEST_ASSERT_EQUAL_STRING("odelly.fritz.box", u.host.c_str());
  TEST_ASSERT_EQUAL(80, u.port);
}

// The Arduino core's substring() takes UNSIGNED arguments, so a failed indexOf (-1) means "to the end".
// The firmware relies on that at EspaperParser.cpp:97, :101 and :190; the shim must agree with the device.
void test_substring_with_a_failed_index_runs_to_the_end() {
  String s("abc\r");
  TEST_ASSERT_EQUAL_STRING("abc\r", s.substring(0, -1).c_str());
  TEST_ASSERT_EQUAL_STRING("c\r", s.substring(2, -1).c_str());
  TEST_ASSERT_EQUAL_STRING("bc", s.substring(1, 3).c_str());
  TEST_ASSERT_EQUAL_STRING("bc", s.substring(3, 1).c_str());  // swapped, as on the device
  TEST_ASSERT_EQUAL_STRING("", s.substring(9, 12).c_str());
}

// Characterisation of the known dissectUrl latent bug, with the DEVICE's substring semantics:
// no path means indexOf('/') == -1, which reads as "to the end", so the host survives and the path is empty.
void test_dissect_url_without_a_path_keeps_the_host_and_has_an_empty_path() {
  EspaperParser p = makeParser();
  auto u = p.dissectUrl("http://odelly.fritz.box:8080");
  TEST_ASSERT_EQUAL_STRING("odelly.fritz.box", u.host.c_str());
  TEST_ASSERT_EQUAL(8080, u.port);
  TEST_ASSERT_EQUAL_STRING("", u.path.c_str());
}

// ---- against the live server ---------------------------------------------------------------------

void test_registration_parses_identity_from_headers() {
  EspaperParser p = makeParser();
  auto id = registerOnServer(p);
  TEST_ASSERT_FALSE(String("-1").equals(id.deviceId));  // -1 / -2 are the firmware's error markers
  TEST_ASSERT_FALSE(String("-2").equals(id.deviceSecret));
  TEST_ASSERT_GREATER_THAN_UINT(0, id.deviceId.length());
  TEST_ASSERT_GREATER_THAN_UINT(0, id.deviceSecret.length());
}

static EspaperParser::ResourceResponse fetchScreen(EspaperParser &p, const String &deviceId) {
  return p.getAndDrawScreen("/public/devices/" + deviceId + "/screen", "", [] {});
}

void test_screen_download_yields_the_exact_payload_size() {
  EspaperParser p = makeParser();
  auto id = registerOnServer(p);
  auto r = fetchScreen(p, id.deviceId);
  TEST_ASSERT_EQUAL(200, r.httpCode);
  TEST_ASSERT_EQUAL_UINT(PAYLOAD_BYTES, DEVICE_FS.files["/screen"].size());
  TEST_ASSERT_TRUE(drew("drawPalettedBitmapFromFile:/screen"));
}

void test_sleep_headers_are_parsed() {
  EspaperParser p = makeParser();
  auto id = registerOnServer(p);
  auto r = fetchScreen(p, id.deviceId);
  TEST_ASSERT_EQUAL_UINT32(serverSleepSeconds, r.sleepSeconds);  // X-ESPAPER-SLEEP-SECONDS
  TEST_ASSERT_EQUAL_UINT32(serverSleepUntil, r.sleepUntilEpoch);  // X-ESPAPER-SLEEP-UNTIL
}

void test_unknown_device_gets_410_and_an_error_screen_not_a_payload() {
  EspaperParser p = makeParser("not-a-secret");
  auto r = fetchScreen(p, "nobody");
  TEST_ASSERT_EQUAL(410, r.httpCode);
  TEST_ASSERT_EQUAL_UINT(0, DEVICE_FS.files["/screen"].size());
  TEST_ASSERT_FALSE(drew("drawPalettedBitmapFromFile:/screen"));
}

void test_unreachable_server_is_reported_as_minus_two() {
  EspaperParser p(&gfx, "", "http://127.0.0.1:1", "", "host-1");
  auto r = p.getAndDrawScreen("/public/devices/x/screen", "", [] {});
  TEST_ASSERT_EQUAL(-2, r.httpCode);
  TEST_ASSERT_EQUAL_UINT32(60, r.sleepSeconds);
}

void run_settings_tests();  // test_settings.cpp

int main() {
  startServer();
  UNITY_BEGIN();
  RUN_TEST(test_dissect_url_accepts_a_hostname);
  RUN_TEST(test_dissect_url_defaults_the_port_for_http);
  RUN_TEST(test_substring_with_a_failed_index_runs_to_the_end);
  RUN_TEST(test_dissect_url_without_a_path_keeps_the_host_and_has_an_empty_path);
  RUN_TEST(test_registration_parses_identity_from_headers);
  RUN_TEST(test_screen_download_yields_the_exact_payload_size);
  RUN_TEST(test_sleep_headers_are_parsed);
  RUN_TEST(test_unknown_device_gets_410_and_an_error_screen_not_a_payload);
  RUN_TEST(test_unreachable_server_is_reported_as_minus_two);
  run_settings_tests();
  int failed = UNITY_END();
  stopServer();
  return failed;
}
