// FORK ADDITION (Task 4): find an ESPaper server on the local network by mDNS.
//
// This is the EXCEPTION path. The stored SERVER_URL is used first; discovery runs only when the
// stored URL has been rejected (serverTrust.h). Nothing here is called in the steady state.
//
// All use of the ESP8266mDNS library is confined to discovery.cpp, so it can be excluded or swapped.
#ifndef DISCOVERY_H
#define DISCOVERY_H

#include <Arduino.h>

// Queries _espaper._tcp and returns "http://<ip>:<port>" of the chosen server, or "" when nothing
// answers. WiFi must be up. Blocks for the query window (about 1.5 s).
String discoverServer();

#endif // DISCOVERY_H
