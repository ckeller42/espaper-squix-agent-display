// Host stand-in for the Arduino core, covering exactly what EspaperParser.cpp, Board.h and
// settings.h touch. String and Serial follow the Arduino core's behaviour (incl. unsigned substring arguments); WiFiClient is a REAL POSIX
// TCP socket, so the firmware's HTTP code talks to a real server. The ESP8266-only parts
// (OTA updater, WiFi radio, heap) are inert stubs.
#ifndef HOST_ARDUINO_H
#define HOST_ARDUINO_H

#include <arpa/inet.h>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>  // EspaperParser.h uses std::function without including it
#include <map>
#include <string>

#define PROGMEM
#define PSTR(s) (s)
#define FPSTR(s) (String(s))
#define pgm_read_byte(p) (*(const uint8_t *)(p))
#define INPUT 0
inline void pinMode(int, int) {}
inline void yield() {}
#define F(s) (s)
typedef bool boolean;

inline unsigned long millis() {
  using namespace std::chrono;
  return (unsigned long)duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

// ---- String ------------------------------------------------------------------------------

class String {
 public:
  String() {}
  String(const char *s) : s_(s ? s : "") {}
  String(const std::string &s) : s_(s) {}
  String(char c) : s_(1, c) {}
  String(int v) : s_(std::to_string(v)) {}
  String(unsigned int v) : s_(std::to_string(v)) {}
  String(long v) : s_(std::to_string(v)) {}
  String(unsigned long v) : s_(std::to_string(v)) {}

  const char *c_str() const { return s_.c_str(); }
  unsigned int length() const { return (unsigned int)s_.size(); }

  int indexOf(char c, unsigned int from = 0) const {
    size_t p = s_.find(c, from);
    return p == std::string::npos ? -1 : (int)p;
  }
  // Unsigned arguments, exactly as in the Arduino core: a failed indexOf() (-1) becomes UINT_MAX and
  // clamps to the end of the string. The firmware relies on this (EspaperParser.cpp:97, :101, :190).
  String substring(unsigned int left, unsigned int right) const {
    if (left > right) std::swap(left, right);
    if (left >= s_.size()) return String();
    if (right > s_.size()) right = (unsigned int)s_.size();
    return String(s_.substr(left, right - left));
  }
  String substring(unsigned int left) const { return substring(left, (unsigned int)s_.size()); }
  void remove(unsigned int index) { if (index < s_.size()) s_.erase(index); }
  void remove(unsigned int index, unsigned int count) { if (index < s_.size()) s_.erase(index, count); }
  long toInt() const { return atol(s_.c_str()); }
  void toUpperCase() { for (auto &c : s_) c = (char)toupper((unsigned char)c); }
  bool startsWith(const String &p) const { return s_.compare(0, p.s_.size(), p.s_) == 0; }
  bool equals(const String &o) const { return s_ == o.s_; }
  // Used by configportal.h (the config portal is compiled on the host, see test_settings.cpp).
  String(double v) : s_(std::to_string(v)) {}
  char charAt(unsigned int i) const { return i < s_.size() ? s_[i] : 0; }
  int indexOf(const String &t, unsigned int from = 0) const {
    size_t p = s_.find(t.s_, from);
    return p == std::string::npos ? -1 : (int)p;
  }
  void replace(const String &from, const String &to) {
    if (from.s_.empty()) return;
    for (size_t p = 0; (p = s_.find(from.s_, p)) != std::string::npos; p += to.s_.size()) s_.replace(p, from.s_.size(), to.s_);
  }

  String &operator+=(const String &o) { s_ += o.s_; return *this; }
  friend String operator+(const String &a, const String &b) { return String(a.s_ + b.s_); }
  friend String operator+(const String &a, const char *b) { return String(a.s_ + b); }
  friend String operator+(const char *a, const String &b) { return String(std::string(a) + b.s_); }
  friend String operator+(const String &a, unsigned int b) { return a + String(b); }
  friend bool operator==(const String &a, const String &b) { return a.s_ == b.s_; }
  friend bool operator==(const String &a, const char *b) { return a.s_ == b; }
  friend bool operator!=(const String &a, const char *b) { return a.s_ != b; }

 private:
  std::string s_;
};

// ---- Serial ------------------------------------------------------------------------------

struct HostSerial {
  void print(const char *s) { fputs(s, stdout); }
  void print(const String &s) { fputs(s.c_str(), stdout); }
  void println() { fputc('\n', stdout); }
  void println(const char *s) { fprintf(stdout, "%s\n", s); }
  void println(const String &s) { fprintf(stdout, "%s\n", s.c_str()); }
  void println(int v) { fprintf(stdout, "%d\n", v); }
  // Deliberately NOT format-checked: the firmware targets 32-bit ints AND longs, so its "%d" with a
  // long is correct on the device and only mismatches on this 64-bit host. printf_P is the
  // flash-string twin of printf (PSTR is a plain pointer here).
  // COST: turning format checking off also hides GENUINE mismatches, not just the long/int width one
  // -- e.g. an enum passed to "%s" (EspaperParser.cpp:427) compiles silently here. Do not read a
  // clean host build as proof the firmware's printf calls are right.
  void printf(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stdout, fmt, ap);
    va_end(ap);
  }
  void printf_P(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stdout, fmt, ap);
    va_end(ap);
  }
};
inline HostSerial Serial;

// ---- ESP8266 odds and ends the parser calls ------------------------------------------------

struct HostEsp {
  uint32_t getFreeHeap() { return 30000; }
  uint32_t getFreeSketchSpace() { return 1000000; }
  uint32_t getFlashChipSize() { return 4 * 1024 * 1024; }
  void restart() {}
};
inline HostEsp ESP;

struct HostIp { String toString() const { return "192.168.4.1"; } };
enum { WIFI_AP = 2 };
struct HostWiFi {
  int RSSI() { return -60; }
  String macAddress() { return "AA:BB:CC:DD:EE:FF"; }
  void mode(int) {}
  void softAP(const char *) {}
  HostIp softAPIP() { return HostIp(); }
};
inline HostWiFi WiFi;

// ---- Filesystem: DEVICE_FS keeps written files in memory so a test can inspect them ---------

class File {
 public:
  File() : files_(nullptr) {}
  // Like the real FS, only a "w"/"a" open creates or truncates; "r" on a missing file fails.
  File(std::map<std::string, std::string> *files, const std::string &name, const char *mode)
      : files_(files), name_(name) {
    if (mode[0] == 'w') (*files_)[name_].clear();
    else if (files_->find(name_) == files_->end()) files_ = nullptr;
  }
  explicit operator bool() const { return files_ != nullptr; }
  size_t write(const uint8_t *buf, size_t n) {
    (*files_)[name_].append((const char *)buf, n);
    return n;
  }
  void close() {}
  // Used by configportal.h's saveConfig()/loadConfig().
  void print(const String &v) { write((const uint8_t *)v.c_str(), v.length()); }
  void println(const String &v) { print(v); print("\r\n"); }  // the ESP8266 core's println ends lines with CRLF
  void println(int v) { println(String(v)); }
  bool available() { return files_ && pos_ < (*files_)[name_].size(); }
  int read() { return available() ? (unsigned char)(*files_)[name_][pos_++] : -1; }
  String readStringUntil(char term) {
    std::string out;
    while (available()) {
      char c = (*files_)[name_][pos_++];
      if (c == term) break;
      out += c;
    }
    return String(out);
  }

 private:
  std::map<std::string, std::string> *files_;
  std::string name_;
  size_t pos_ = 0;
};

struct HostFs {
  std::map<std::string, std::string> files;
  File open(const String &name, const char *mode) { return File(&files, name.c_str(), mode); }
  bool remove(const String &name) { return files.erase(name.c_str()) > 0; }
};
inline HostFs DEVICE_FS;

// ---- WiFiClient: a real, blocking-with-timeout TCP socket ------------------------------------

class WiFiClient {
 public:
  virtual ~WiFiClient() { stop(); }

  // Test instrumentation, not Arduino API: counts connection attempts so a test can prove how many
  // requests a code path makes.
  static inline int connectCount = 0;

  int connect(const char *host, uint16_t port) {
    connectCount++;
    stop();
    struct addrinfo hints = {}, *res = nullptr;
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, std::to_string(port).c_str(), &hints, &res) != 0) return 0;
    for (auto *p = res; p; p = p->ai_next) {
      fd_ = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
      if (fd_ < 0) continue;
      if (::connect(fd_, p->ai_addr, p->ai_addrlen) == 0) break;
      ::close(fd_);
      fd_ = -1;
    }
    freeaddrinfo(res);
    eof_ = false;
    buf_.clear();
    return fd_ >= 0;
  }
  uint8_t connected() {
    fill(0);
    return fd_ >= 0 && !(eof_ && buf_.empty());
  }
  size_t print(const String &s) {
    size_t sent = 0;
    while (sent < s.length()) {
      ssize_t n = ::send(fd_, s.c_str() + sent, s.length() - sent, 0);
      if (n <= 0) break;
      sent += (size_t)n;
    }
    return sent;
  }
  int available() {
    fill(1);
    return (int)buf_.size();
  }
  String readStringUntil(char term) {
    unsigned long start = millis();
    for (;;) {
      size_t nl = buf_.find(term);
      if (nl != std::string::npos) {
        String line(buf_.substr(0, nl));
        buf_.erase(0, nl + 1);
        return line;
      }
      if ((eof_ && buf_.empty()) || millis() - start > 1000) break;  // Stream's 1 s timeout
      fill(10);
      if (eof_ && buf_.find(term) == std::string::npos) break;
    }
    String rest(buf_);
    buf_.clear();
    return rest;
  }
  size_t readBytes(uint8_t *out, size_t n) {
    n = n < buf_.size() ? n : buf_.size();
    memcpy(out, buf_.data(), n);
    buf_.erase(0, n);
    return n;
  }
  void stop() {
    if (fd_ >= 0) ::close(fd_);
    fd_ = -1;
  }

 private:
  // Pull whatever the peer has sent into buf_, waiting at most waitMs for the first byte.
  void fill(int waitMs) {
    if (fd_ < 0 || eof_) return;
    struct pollfd pfd = {fd_, POLLIN, 0};
    if (::poll(&pfd, 1, waitMs) <= 0) return;
    char tmp[1024];
    ssize_t n = ::recv(fd_, tmp, sizeof tmp, 0);
    if (n > 0) buf_.append(tmp, (size_t)n);
    else eof_ = true;
  }
  int fd_ = -1;
  bool eof_ = false;
  std::string buf_;
};

// ---- OTA updater: never exercised on the host ------------------------------------------------

enum t_httpUpdate_return { HTTP_UPDATE_FAILED, HTTP_UPDATE_NO_UPDATES, HTTP_UPDATE_OK };
struct HostUpdater {
  void rebootOnUpdate(bool) {}
  t_httpUpdate_return update(WiFiClient &, const String &) { return HTTP_UPDATE_FAILED; }
  int getLastError() { return 0; }
  String getLastErrorString() { return "not available on the host"; }
};
inline HostUpdater HTTP_UPDATER_INSTANCE;
#define HTTP_UPDATER HTTP_UPDATER_INSTANCE

#endif
