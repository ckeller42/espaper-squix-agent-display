// FORK ADDITION (Task 4): see discovery.h.
#include "discovery.h"

#include <ESP8266mDNS.h>

// Query window. LEAmDNS' default is 1000 ms; slightly longer so a server that answers on the second
// of the two queries the library sends is not missed. This is the wake-time cost of a failed lookup.
#define DISCOVERY_QUERY_MS 1500

// Is a "better" than b under the tie-break rule?
//
// TIE-BREAK RULE (deterministic, not clever): when several servers answer, the one with the LOWEST
// IPv4 ADDRESS wins, compared octet by octet as a number (so 192.168.1.9 beats 192.168.1.50, which a
// text comparison would get backwards). If the same address is advertised on two ports, the lower
// port wins. The result therefore depends only on the SET of answers, never on the order in which
// they arrived, so two servers never make the device flip between them from wake to wake.
static bool isPreferred(const IPAddress &ipA, uint16_t portA, const IPAddress &ipB, uint16_t portB) {
  for (int i = 0; i < 4; i++) {
    if (ipA[i] != ipB[i]) return ipA[i] < ipB[i];
  }
  return portA < portB;
}

String discoverServer() {
  // LEAmDNS answers queries only while its responder is running (queryService() returns 0 without begin()).
  if (!MDNS.begin("espaper-client")) {
    Serial.println(F("mDNS responder failed to start; no discovery"));
    return "";
  }
  uint32_t count = MDNS.queryService("espaper", "tcp", DISCOVERY_QUERY_MS);
  Serial.printf_P(PSTR("mDNS: %u answer(s) for _espaper._tcp\n"), (unsigned) count);

  bool found = false;
  IPAddress bestIp;
  uint16_t bestPort = 0;
  for (uint32_t i = 0; i < count; i++) {
    IPAddress ip = MDNS.IP(i);
    uint16_t port = MDNS.port(i);
    if ((uint32_t) ip == 0 || port == 0) continue;  // an answer whose address record never arrived
    if (!found || isPreferred(ip, port, bestIp, bestPort)) {
      bestIp = ip;
      bestPort = port;
      found = true;
    }
  }

  // Release the query's answers and the responder's UDP socket and buffers before the screen
  // framebuffer is allocated: free heap is tight at that moment.
  MDNS.removeQuery();
  MDNS.close();

  if (!found) return "";
  return String(F("http://")) + bestIp.toString() + String(F(":")) + String((unsigned int) bestPort);
}
