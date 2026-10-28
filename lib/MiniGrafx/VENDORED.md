# Vendored: ThingPulse MiniGrafx

Source: https://github.com/ThingPulse/minigrafx tag `1.2.2`
(the version espaper-client pins), vendored because it needed a local fix.

## Why vendored rather than pulled from GitHub

MiniGrafx opens font and bitmap files from `SPIFFS`. This project migrated to
`LittleFS` (SPIFFS is deprecated in Arduino core 3.x and warns on every call).
Those are **incompatible on-flash formats**, so leaving the library on SPIFFS
was not merely noisy -- it was a real bug: `EspaperParser` downloads fonts and
bitmaps and writes them to LittleFS, and MiniGrafx would then look for them in
a SPIFFS volume that holds nothing.

## Local changes

`src/MiniGrafx.cpp` only: the three `SPIFFS.open(...)` calls now go through a
`MINIGRAFX_FS` alias that binds to LittleFS on ESP8266 and SPIFFS on ESP32.
Nothing else is modified; diff against upstream `1.2.2` to verify.

This is a candidate to upstream as a pull request.
