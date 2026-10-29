#pragma once
// TLS is not exercised on the host: the live server speaks plain HTTP on loopback.
#include <Arduino.h>
class WiFiClientSecure : public WiFiClient {};
