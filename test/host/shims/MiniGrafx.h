#pragma once
// A no-op MiniGrafx that records the calls the parser makes. Drawing is proven elsewhere (packer,
// render and payload-parity tests); here we only need to see WHAT the parser asked to draw.
#include <Arduino.h>

#include <vector>

enum TEXT_ALIGNMENT { TEXT_ALIGN_LEFT, TEXT_ALIGN_RIGHT, TEXT_ALIGN_CENTER };

class MiniGrafx {
 public:
  std::vector<std::string> calls;  // e.g. "drawPalettedBitmapFromFile:/screen", "drawStringMaxWidth:<msg>"

  void init() { calls.push_back("init"); }
  void fillBuffer(uint16_t) {}
  uint16_t getWidth() { return 296; }
  void setColor(uint16_t) {}
  void setTextAlignment(TEXT_ALIGNMENT) {}
  void setFont(const uint8_t *) {}
  void drawPalettedBitmapFromFile(int, int, const char *file) {
    calls.push_back(std::string("drawPalettedBitmapFromFile:") + file);
  }
  void drawStringMaxWidth(int, int, int, const String &msg) {
    calls.push_back(std::string("drawStringMaxWidth:") + msg.c_str());
  }
  void drawPalettedBitmapFromPgm(int, int, const char *) {}
  void drawString(int, int, const String &) {}
  void commit() { calls.push_back("commit"); }
  void freeBuffer() {}
};
