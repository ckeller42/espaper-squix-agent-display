// Host stand-in for the ESP8266 core's mDNS responder (libraries/ESP8266mDNS, the LEAmDNS API),
// covering exactly what EspaperClient/discovery.cpp calls.
//
// WHAT THIS IS: a scripted answer list. A test puts "services on the network" into MDNS.answers and
// the real discovery.cpp runs its real selection logic over them.
// WHAT THIS IS NOT: mDNS. No packet is sent, nothing times out, no record can arrive late, be
// malformed, or lack its A record. It encodes only the three API facts discovery.cpp depends on and
// that we read in the core's source (LEAmDNS.cpp): queryService() returns 0 unless begin() ran first
// (m_pUDPContext is null), it matches the service/protocol it was asked for, and the answer count is
// what IP(i)/port(i) are then indexed by. Whether the real library behaves that way on the radio is
// proven only on a device.
#ifndef HOST_ESP8266MDNS_H
#define HOST_ESP8266MDNS_H

#include <Arduino.h>

#include <vector>

// The subset of IPAddress that discovery.cpp uses; the real one stores the octets the same way.
class IPAddress {
 public:
  IPAddress() {}
  IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d) : o_{a, b, c, d} {}
  uint8_t operator[](int i) const { return o_[i]; }
  operator uint32_t() const { return (uint32_t)o_[0] | (uint32_t)o_[1] << 8 | (uint32_t)o_[2] << 16 | (uint32_t)o_[3] << 24; }
  String toString() const {
    return String((int)o_[0]) + "." + String((int)o_[1]) + "." + String((int)o_[2]) + "." + String((int)o_[3]);
  }

 private:
  uint8_t o_[4] = {0, 0, 0, 0};
};

struct HostMdns {
  struct Answer {
    IPAddress ip;
    uint16_t port;
  };
  std::vector<Answer> answers;  // what the "network" will answer with
  bool responderRunning = false;
  int queryCount = 0;  // test instrumentation: how many queries went out (UDP, invisible to WiFiClient::connectCount)

  void reset() { answers.clear(); responderRunning = false; queryCount = 0; }

  bool begin(const char *) { responderRunning = true; return true; }
  bool close() { responderRunning = false; return true; }
  uint32_t queryService(const char *service, const char *protocol, uint16_t = 1000) {
    queryCount++;
    if (!responderRunning) return 0;  // as LEAmDNS: "safeguard against misuse"
    if (std::string(service) != "espaper" || std::string(protocol) != "tcp") return 0;
    return (uint32_t)answers.size();
  }
  bool removeQuery() { return true; }
  IPAddress IP(uint32_t i) { return answers[i].ip; }
  uint16_t port(uint32_t i) { return answers[i].port; }
};
inline HostMdns MDNS;

#endif
