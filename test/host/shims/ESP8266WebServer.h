#pragma once
// Stands in for the web server so configportal.h compiles on the host. It is a RECORDER, not a
// behavioural model: arg() returns what a test posted, sendContent() accumulates what the firmware
// emitted. No routing, no sockets -- the portal's handlers are called directly by the tests.
#include <Arduino.h>

#include <map>

#define CONTENT_LENGTH_UNKNOWN (-1)
enum HttpMethod { HTTP_GET, HTTP_POST };

class ESP8266WebServer {
 public:
  explicit ESP8266WebServer(int) {}
  std::map<std::string, std::string> posted;  // form fields a test submits
  std::string sent;                           // everything handed to sendContent()

  String arg(const char *name) { auto it = posted.find(name); return it == posted.end() ? String() : String(it->second); }
  String arg(int i) { auto it = posted.begin(); std::advance(it, i); return String(it->second); }
  void sendContent(const String &s) { sent += s.c_str(); }
  void sendHeader(const char *, const char *) {}
  void setContentLength(int) {}
  void send(int, const char *, const String &) {}
  struct Client { void stop() {} };
  Client client() { return Client(); }
  void on(const char *, std::function<void()>) {}
  void onNotFound(std::function<void()>) {}
  void begin() {}
  void handleClient() {}
  String uri() { return ""; }
  HttpMethod method() { return HTTP_GET; }
  int args() { return 0; }
  String argName(int) { return ""; }
};
