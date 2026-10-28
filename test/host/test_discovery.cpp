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

#include "../../EspaperClient/EspaperParser.h"
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

// What setup() does with a stored URL: fetch the screen once, judge that same fetch.
struct Attempt {
  ScreenFetch result;
  int rejections;
  int connects;
};

static Attempt fetchScreenFrom(const String &baseUrl, const String &deviceId, const String &secret) {
  Attempt a{};
  DEVICE_FS.files.clear();
  gfx2.calls.clear();
  EspaperParser p(&gfx2, "", baseUrl, secret, "host-1");
  int before = WiFiClient::connectCount;
  a.result = fetchScreenJudged(
      [&] { return p.getAndDrawScreen("/public/devices/" + deviceId + "/screen", "", [] {}); },
      [&] { a.rejections++; });  // the seam Task 4 fills with discovery
  a.connects = WiFiClient::connectCount - before;
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

void run_discovery_tests(const std::string &liveServerUrl) {
  UnitySetTestFile(__FILE__);
  liveUrl = liveServerUrl;
  RUN_TEST(test_a_valid_stored_url_is_used_without_discovery);
  RUN_TEST(test_a_stored_url_serving_a_non_espaper_response_is_rejected);
}
