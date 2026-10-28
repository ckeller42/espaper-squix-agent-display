#pragma once
// BoardClass is declared by the firmware's real Board.h but implemented in Board.cpp, which
// drives the radio and flash and is not built on the host. These are the values the parser
// reports in its request headers.
#include "../../EspaperClient/Board.h"

BoardClass Board;
BoardClass::BoardClass() {}
uint32_t BoardClass::getBattery() { return 700; }
uint32_t BoardClass::getFreeSPIFFSBytes() { return 1000000; }
uint32_t BoardClass::getTotalSPIFFSBytes() { return 1500000; }
