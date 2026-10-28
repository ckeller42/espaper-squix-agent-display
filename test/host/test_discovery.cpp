// Task 3 (Review Focus 3): a stored server URL is trusted only if the screen fetch it already does
// returns 200 with exactly PAYLOAD_SIZE bytes. Real EspaperParser against (a) the live Python server
// and (b) a canned-response socket server that plays "the printer that inherited yesterday's DHCP lease".
#include <Arduino.h>
#include <MiniGrafx.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <unity.h>

#include <atomic>
#include <thread>

#include <ESP8266mDNS.h>  // the host shim: a scripted answer list, see shims/ESP8266mDNS.h

#include "../../EspaperClient/EspaperParser.h"
#include "../../EspaperClient/discovery.h"
#include "../../EspaperClient/serverTrust.h"

static MiniGrafx gfx2;
static std::string liveUrl;

// ---- an impostor on a reused address ----------------------------------------------------------
class Impostor {
 public:
  explicit Impostor(std::string canned) : canned_(std::move(canned)) {
    fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    ::bind(fd_, (sockaddr *)&a, sizeof a);
    ::listen(fd_, 4);
    socklen_t n = sizeof a;
    ::getsockname(fd_, (sockaddr *)&a, &n);
    port_ = ntohs(a.sin_port);
    th_ = std::thread([this] {
      for (;;) {
        int c = ::accept(fd_, nullptr, nullptr);
        if (c < 0 || stop_) { if (c >= 0) ::close(c); return; }
        char buf[2048];
        ::recv(c, buf, sizeof buf, 0);  // the request; contents are irrelevant to a printer
        ::send(c, canned_.data(), canned_.size(), 0);
        ::close(c);
      }
    });
  }
  ~Impostor() {
    stop_ = true;
    int c = ::socket(AF_INET, SOCK_STREAM, 0);  // wake accept()
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = htons(port_);
    ::connect(c, (sockaddr *)&a, sizeof a);
    ::close(c);
    th_.join();
    ::close(fd_);
    ::close(c);
  }
  String url() const { return String("http://127.0.0.1:") + String((long)port_); }

 private:
  std::string canned_;
  int fd_;
  uint16_t port_;
  std::atomic<bool> stop_{false};
  std::thread th_;
};

static std::string httpResponse(const char *status, size_t bodyBytes) {
  return std::string("HTTP/1.1 ") + status + "\r\nContent-Length: " + std::to_string(bodyBytes) +
         "\r\nConnection: close\r\n\r\n" + std::string(bodyBytes, 'x');
}

// What setup() does with a stored URL: fetch the screen once, judge that same fetch. The discovery
// hook is the REAL discoverServer() over the (empty unless a test fills it) mDNS shim.
struct Attempt {
  ScreenFetch result;
  int rejections;  // times the discovery hook ran
  int connects;
  int mdnsQueries;  // mDNS is UDP: WiFiClient::connectCount cannot see it, so it is counted at the shim
};

static Attempt fetchScreenFrom(const String &baseUrl, const String &deviceId, const String &secret,
                               bool urlIsManual = false) {
  Attempt a{};
  DEVICE_FS.files.clear();
  gfx2.calls.clear();
  EspaperParser p(&gfx2, "", baseUrl, secret, "host-1");
  int before = WiFiClient::connectCount;
  int queriesBefore = MDNS.queryCount;
  a.result = fetchScreenOrDiscover(
      [&] { return p.getAndDrawScreen("/public/devices/" + deviceId + "/screen", "", [] {}); },
      urlIsManual,
      [&] { a.rejections++; return discoverServer(); },
      [&](const String &url) { p.setBaseUrl(url); },
      [&](const String &) { return true; });
  a.connects = WiFiClient::connectCount - before;
  a.mdnsQueries = MDNS.queryCount - queriesBefore;
  return a;
}

void test_a_valid_stored_url_is_used_without_discovery() {
  EspaperParser reg(&gfx2, "", String(liveUrl.c_str()), "", "host-1");
  auto id = reg.registerDevice("/public/devices",
      "{\"macAddress\":\"AA:BB:CC:DD:EE:FF\",\"deviceType\":\"Espaper29Bw\",\"timeZone\":\"Europe/Berlin\"}");

  Attempt a = fetchScreenFrom(String(liveUrl.c_str()), id.deviceId, id.deviceSecret);

  TEST_ASSERT_TRUE(a.result.trusted);
  TEST_ASSERT_EQUAL(200, a.result.response.httpCode);
  TEST_ASSERT_EQUAL_INT(0, a.rejections);  // discovery never ran
  // Discovery is UDP, so the connect count below cannot see it. Without this line an unconditional
  // discovery query would leave this test green: the guard has to watch the mDNS shim too.
  TEST_ASSERT_EQUAL_INT(0, a.mdnsQueries);
  // The steady state is free: exactly one connection, the screen fetch itself. An added validation
  // probe (HEAD, /health, a second GET) would make this 2 and fail here.
  TEST_ASSERT_EQUAL_INT(1, a.connects);
}

void test_a_stored_url_serving_a_non_espaper_response_is_rejected() {
  {  // a 200 of the wrong size: an unrelated web page on a reused address
    Impostor printer(httpResponse("200 OK", 1500));
    Attempt a = fetchScreenFrom(printer.url(), "x", "");
    TEST_ASSERT_FALSE(a.result.trusted);
    TEST_ASSERT_EQUAL_INT(1, a.rejections);
    TEST_ASSERT_FALSE_MESSAGE(gfx2.calls.size() && gfx2.calls[0] == "drawPalettedBitmapFromFile:/screen",
                              "must not draw another device's bytes as a screen");
  }
  {  // a 200 one byte short and one byte long: "exactly", not "about"
    Impostor shortOne(httpResponse("200 OK", ESPAPER_PAYLOAD_SIZE - 1));
    TEST_ASSERT_FALSE(fetchScreenFrom(shortOne.url(), "x", "").result.trusted);
    Impostor longOne(httpResponse("200 OK", ESPAPER_PAYLOAD_SIZE + 1));
    TEST_ASSERT_FALSE(fetchScreenFrom(longOne.url(), "x", "").result.trusted);
  }
  {  // a 404
    Impostor nginx(httpResponse("404 Not Found", 162));
    Attempt a = fetchScreenFrom(nginx.url(), "x", "");
    TEST_ASSERT_FALSE(a.result.trusted);
    TEST_ASSERT_EQUAL_INT(1, a.rejections);
  }
  {  // a connection refusal (nothing listens on port 1)
    Attempt a = fetchScreenFrom("http://127.0.0.1:1", "x", "");
    TEST_ASSERT_FALSE(a.result.trusted);
    TEST_ASSERT_EQUAL_INT(1, a.rejections);
  }
  {  // sanity: a 200 of exactly the right size IS trusted, whoever serves it
    Impostor exact(httpResponse("200 OK", ESPAPER_PAYLOAD_SIZE));
    TEST_ASSERT_TRUE(fetchScreenFrom(exact.url(), "x", "").result.trusted);
  }
}

// ---- Task 4: discovery ---------------------------------------------------------------------------

static const IPAddress IP_9(192, 168, 1, 9), IP_50(192, 168, 1, 50), IP_8(10, 0, 0, 8);

void test_discovery_returns_empty_when_nothing_answers() {
  MDNS.reset();
  TEST_ASSERT_EQUAL_STRING("", discoverServer().c_str());
  TEST_ASSERT_EQUAL_INT_MESSAGE(1, MDNS.queryCount, "it must actually have asked");
  TEST_ASSERT_FALSE_MESSAGE(MDNS.responderRunning, "the responder's socket and buffers must be released");
}

void test_discovery_returns_the_one_server_that_answers() {
  MDNS.reset();
  MDNS.answers = {{IP_9, 8411}};
  TEST_ASSERT_EQUAL_STRING("http://192.168.1.9:8411", discoverServer().c_str());
}

void test_discovery_picks_deterministically_when_two_servers_answer() {
  // The rule (discovery.cpp): lowest IPv4 address, octet-wise numeric; then lowest port.
  // .9 vs .50 is chosen because text order ("...50" < "...9") would pick the wrong one.
  MDNS.reset();
  MDNS.answers = {{IP_50, 8411}, {IP_9, 8411}};
  TEST_ASSERT_EQUAL_STRING("http://192.168.1.9:8411", discoverServer().c_str());
  MDNS.answers = {{IP_9, 8411}, {IP_50, 8411}};  // same set, other arrival order
  TEST_ASSERT_EQUAL_STRING("http://192.168.1.9:8411", discoverServer().c_str());

  MDNS.answers = {{IP_9, 8411}, {IP_8, 9000}, {IP_50, 80}};  // lowest address wins whatever the port
  TEST_ASSERT_EQUAL_STRING("http://10.0.0.8:9000", discoverServer().c_str());

  MDNS.answers = {{IP_9, 9000}, {IP_9, 8411}};  // one address on two ports: lower port
  TEST_ASSERT_EQUAL_STRING("http://192.168.1.9:8411", discoverServer().c_str());
}

void test_discovery_ignores_an_answer_without_an_address() {
  MDNS.reset();
  MDNS.answers = {{IPAddress(), 8411}, {IP_50, 8411}};
  TEST_ASSERT_EQUAL_STRING("http://192.168.1.50:8411", discoverServer().c_str());
  MDNS.answers = {{IPAddress(), 8411}};
  TEST_ASSERT_EQUAL_STRING("", discoverServer().c_str());
}

// A rejected stored URL (a 404 from "nginx on a reused address") with a live server elsewhere.
void test_a_rejected_stored_url_is_replaced_by_the_discovered_server_and_adopted_once_it_works() {
  EspaperParser reg(&gfx2, "", String(liveUrl.c_str()), "", "host-1");
  auto id = reg.registerDevice("/public/devices",
      "{\"macAddress\":\"AA:BB:CC:DD:EE:FF\",\"deviceType\":\"Espaper29Bw\",\"timeZone\":\"Europe/Berlin\"}");
  Impostor nginx(httpResponse("404 Not Found", 162));

  DEVICE_FS.files.clear();
  EspaperParser p(&gfx2, "", nginx.url(), id.deviceSecret, "host-1");
  std::vector<std::string> adopted;
  DiscoveryOutcome outcome;
  ScreenFetch r = fetchScreenOrDiscover(
      [&] { return p.getAndDrawScreen("/public/devices/" + id.deviceId + "/screen", "", [] {}); },
      false, [&] { return String(liveUrl.c_str()); },
      [&](const String &url) { p.setBaseUrl(url); },
      [&](const String &url) { adopted.push_back(url.c_str()); return true; }, &outcome);

  TEST_ASSERT_TRUE(r.trusted);
  TEST_ASSERT_EQUAL(200, r.response.httpCode);
  TEST_ASSERT_TRUE(outcome.discoveryRan);
  TEST_ASSERT_EQUAL_UINT(1, adopted.size());
  TEST_ASSERT_EQUAL_STRING(liveUrl.c_str(), adopted[0].c_str());
}

void test_a_discovered_server_that_does_not_serve_a_screen_is_not_adopted() {
  Impostor nginx(httpResponse("404 Not Found", 162));
  Impostor otherPrinter(httpResponse("200 OK", 1500));
  int adoptions = 0;
  DiscoveryOutcome outcome;
  EspaperParser p(&gfx2, "", nginx.url(), "", "host-1");
  ScreenFetch r = fetchScreenOrDiscover(
      [&] { return p.getAndDrawScreen("/public/devices/x/screen", "", [] {}); },
      false, [&] { return otherPrinter.url(); },
      [&](const String &url) { p.setBaseUrl(url); },
      [&](const String &) { adoptions++; return true; }, &outcome);

  TEST_ASSERT_FALSE(r.trusted);
  TEST_ASSERT_EQUAL_INT_MESSAGE(0, adoptions, "a wrong answer must not be persisted for the next wake");
  TEST_ASSERT_TRUE(outcome.discoveryRan);
  TEST_ASSERT_EQUAL_STRING(otherPrinter.url().c_str(), outcome.found.c_str());
}

void test_a_manual_stored_url_is_never_replaced_and_discovery_does_not_even_run() {
  MDNS.reset();
  MDNS.answers = {{IP_9, 8411}};  // a server IS available; it must still be left alone
  Impostor nginx(httpResponse("404 Not Found", 162));
  Attempt a = fetchScreenFrom(nginx.url(), "x", "", /*urlIsManual=*/true);
  TEST_ASSERT_FALSE(a.result.trusted);
  TEST_ASSERT_EQUAL_INT(0, a.rejections);
  TEST_ASSERT_EQUAL_INT(0, a.mdnsQueries);
  MDNS.reset();
}

void test_the_failure_message_names_what_was_tried() {
  DiscoveryOutcome none;
  none.discoveryRan = true;
  String m = describeServerFailure("http://192.168.1.5:8411", false, none);
  TEST_ASSERT_NOT_EQUAL(-1, m.indexOf('8'));
  TEST_ASSERT_TRUE(std::string(m.c_str()).find("http://192.168.1.5:8411") != std::string::npos);
  TEST_ASSERT_TRUE(std::string(m.c_str()).find("_espaper._tcp") != std::string::npos);
  TEST_ASSERT_TRUE(std::string(m.c_str()).find("nothing") != std::string::npos);

  DiscoveryOutcome skipped;
  String manual = describeServerFailure("http://10.9.9.9:8411", true, skipped);
  TEST_ASSERT_TRUE(std::string(manual.c_str()).find("hand") != std::string::npos);
  TEST_ASSERT_TRUE(std::string(manual.c_str()).find("Not searching") != std::string::npos);

  DiscoveryOutcome wrong;
  wrong.discoveryRan = true;
  wrong.found = "http://192.168.1.9:8411";
  String w = describeServerFailure("http://192.168.1.5:8411", false, wrong);
  TEST_ASSERT_TRUE(std::string(w.c_str()).find("http://192.168.1.9:8411") != std::string::npos);
}

// ---- double refresh: a failed wake draws ONE screen ----------------------------------------------
// The e-ink refresh is the device's biggest power cost and the panel has finite cycles, so the
// refresh count is asserted at the MiniGrafx shim: every commit() is one physical refresh.

static int commitsIn(const MiniGrafx &g) {
  int n = 0;
  for (auto &c : g.calls) if (c == "commit") n++;
  return n;
}

struct Wake {
  ScreenFetch result;
  int failureScreens;
};

// setup()'s fetchAndDrawScreen(): the real parser, the real wrapper; showFailure is the sketch's
// showMessageSmall (init, draw, commit) as far as the shim can see it.
static Wake wakeAgainst(const String &baseUrl, const String &deviceId, const String &secret,
                        bool urlIsManual = false, String discovered = "") {
  Wake w{};
  DEVICE_FS.files.clear();
  gfx2.calls.clear();
  EspaperParser p(&gfx2, "", baseUrl, secret, "host-1");
  w.result = fetchScreenOrDiscoverOrReport(
      &p, [&] { return p.getAndDrawScreen("/public/devices/" + deviceId + "/screen", "", [] {}); },
      urlIsManual, [&] { return discovered; },
      [&](const String &url) { p.setBaseUrl(url); },
      [&](const String &) { return true; }, baseUrl,
      [&](const String &message) {
        w.failureScreens++;
        gfx2.init();
        gfx2.drawStringMaxWidth(4, 4, 288, message);
        gfx2.commit();
      });
  return w;
}

void test_a_down_server_draws_exactly_one_screen() {
  Wake w = wakeAgainst("http://127.0.0.1:1", "x", "");  // connection refused: httpCode -2
  TEST_ASSERT_FALSE(w.result.trusted);
  TEST_ASSERT_EQUAL_INT_MESSAGE(1, commitsIn(gfx2), "one e-ink refresh per failed wake");
  TEST_ASSERT_EQUAL_INT(1, w.failureScreens);
  TEST_ASSERT_EQUAL_UINT32_MESSAGE(60, w.result.response.sleepSeconds, "retry in 1 min still set");
  TEST_ASSERT_EQUAL_UINT32(60, w.result.response.sleepUntilEpoch);
}

void test_every_rejection_kind_draws_exactly_one_screen_and_never_zero() {
  Impostor nginx(httpResponse("404 Not Found", 162));
  Impostor broken(httpResponse("500 Internal Server Error", 10));
  Impostor printer(httpResponse("200 OK", 1500));  // wrong-size 200: parser already drew nothing
  Impostor otherPrinter(httpResponse("200 OK", 1500));
  struct Kind { const char *name; String url; bool manual; String discovered; };
  Kind kinds[] = {
      {"404", nginx.url(), false, ""},
      {"500", broken.url(), false, ""},
      {"wrong-size 200", printer.url(), false, ""},
      {"manual URL", nginx.url(), true, ""},
      {"discovery found a non-server", nginx.url(), false, otherPrinter.url()},
  };
  for (auto &k : kinds) {
    wakeAgainst(k.url, "x", "", k.manual, k.discovered);  // clears the shim, so each count is its own
    TEST_ASSERT_EQUAL_INT_MESSAGE(1, commitsIn(gfx2), k.name);
  }
}

void test_a_failure_still_draws_something() {  // never zero: a blank panel looks like a flat battery
  Wake w = wakeAgainst("http://127.0.0.1:1", "x", "");
  TEST_ASSERT_GREATER_OR_EQUAL_INT(1, commitsIn(gfx2));
  TEST_ASSERT_EQUAL_INT(1, w.failureScreens);
  bool saidWhy = false;
  for (auto &c : gfx2.calls) if (c.find("Cannot reach the ESPaper server") != std::string::npos) saidWhy = true;
  TEST_ASSERT_TRUE_MESSAGE(saidWhy, "the one screen is the specific one");
}

void test_a_410_still_draws_its_own_screen_because_the_sketch_restarts_before_any_other() {
  EspaperParser p(&gfx2, "", String(liveUrl.c_str()), "not-a-secret", "host-1");
  DEVICE_FS.files.clear();
  gfx2.calls.clear();
  p.setDeferFailureScreen(true);
  auto r = p.getAndDrawScreen("/public/devices/nobody/screen", "", [] {});
  TEST_ASSERT_EQUAL(410, r.httpCode);
  TEST_ASSERT_EQUAL_INT(1, commitsIn(gfx2));
}

void test_a_rescued_wake_draws_only_the_real_screen() {  // the first rejected fetch drew a wasted one
  EspaperParser reg(&gfx2, "", String(liveUrl.c_str()), "", "host-1");
  auto id = reg.registerDevice("/public/devices",
      "{\"macAddress\":\"AA:BB:CC:DD:EE:FF\",\"deviceType\":\"Espaper29Bw\",\"timeZone\":\"Europe/Berlin\"}");
  Impostor nginx(httpResponse("404 Not Found", 162));
  Wake w = wakeAgainst(nginx.url(), id.deviceId, id.deviceSecret, false, String(liveUrl.c_str()));
  TEST_ASSERT_TRUE(w.result.trusted);
  TEST_ASSERT_EQUAL_INT(0, w.failureScreens);
  TEST_ASSERT_EQUAL_INT(1, commitsIn(gfx2));
  TEST_ASSERT_EQUAL_STRING("drawPalettedBitmapFromFile:/screen", gfx2.calls[1].c_str());
}

void run_discovery_tests(const std::string &liveServerUrl) {
  UnitySetTestFile(__FILE__);
  liveUrl = liveServerUrl;
  MDNS.reset();
  RUN_TEST(test_a_valid_stored_url_is_used_without_discovery);
  RUN_TEST(test_a_stored_url_serving_a_non_espaper_response_is_rejected);
  RUN_TEST(test_discovery_returns_empty_when_nothing_answers);
  RUN_TEST(test_discovery_returns_the_one_server_that_answers);
  RUN_TEST(test_discovery_picks_deterministically_when_two_servers_answer);
  RUN_TEST(test_discovery_ignores_an_answer_without_an_address);
  RUN_TEST(test_a_rejected_stored_url_is_replaced_by_the_discovered_server_and_adopted_once_it_works);
  RUN_TEST(test_a_discovered_server_that_does_not_serve_a_screen_is_not_adopted);
  RUN_TEST(test_a_manual_stored_url_is_never_replaced_and_discovery_does_not_even_run);
  RUN_TEST(test_the_failure_message_names_what_was_tried);
  RUN_TEST(test_a_down_server_draws_exactly_one_screen);
  RUN_TEST(test_every_rejection_kind_draws_exactly_one_screen_and_never_zero);
  RUN_TEST(test_a_failure_still_draws_something);
  RUN_TEST(test_a_410_still_draws_its_own_screen_because_the_sketch_restarts_before_any_other);
  RUN_TEST(test_a_rescued_wake_draws_only_the_real_screen);
}
