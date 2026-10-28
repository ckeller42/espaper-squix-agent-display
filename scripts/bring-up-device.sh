#!/usr/bin/env bash
# One-shot: take a responsive ESPaper from nothing to showing the server's screen.
#
# Run this the moment the device answers again. It is idempotent — safe to re-run.
#
#   ./scripts/bring-up-device.sh
#
# Preconditions it checks for you: the programmer enumerated, the chip answering,
# and the display server reachable on the LAN.
set -euo pipefail

PORT="${SQUIX_PORT:-/dev/cu.usbserial-0001}"
SERVER="${SQUIX_SERVER:-http://192.168.178.43:8411}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FW="$ROOT/.pio/build/Espaper29Bw-DEV/firmware.bin"

say() { printf '\n==> %s\n' "$1"; }

say "1/5  programmer present?"
[ -e "$PORT" ] || { echo "   $PORT missing — replug the programmer's USB" >&2; exit 1; }
echo "   $PORT"

say "2/5  chip answering?"
if ! esptool --chip esp8266 --port "$PORT" --before default-reset --after no-reset flash-id 2>&1 | grep -q Manufacturer; then
    cat >&2 <<'HINT'
   The chip is not answering. The ROM bootloader replies regardless of what is
   flashed, so this is power or wiring, not the image:
     - the programmer's +5V pin must align with the board's 5V pin, components down/back
     - unplug and replug the programmer's USB to re-enumerate the adapter
     - check the ESPaper's own power switch
HINT
    exit 1
fi

say "3/5  server reachable?"
curl -sf -o /dev/null "$SERVER/preview" || { echo "   $SERVER not reachable" >&2; exit 1; }
echo "   $SERVER"

say "4/5  flashing the DEV build"
[ -f "$FW" ] || SQUIX_ENV=Espaper29Bw-DEV "$ROOT/scripts/dev.sh" build
esptool --chip esp8266 --port "$PORT" --baud 921600 \
    --before default-reset --after hard-reset \
    write-flash --flash-mode dout --flash-size 2MB 0x0 "$FW"

say "5/5  waiting for the device to register (120s)"
# The firmware has no stored WiFi credentials on a fresh flash, so it will raise
# its ESPaperConfig access point instead. Join that from a phone, enter the
# Insel credentials at http://192.168.4.1, and registration follows.
for i in $(seq 1 24); do
    if curl -sf "$SERVER/preview" >/dev/null && \
       [ "$(find "${SQUIX_STORE:-/tmp/espaper-store}/devices" -type f 2>/dev/null | wc -l)" -gt 0 ]; then
        echo "   device registered"; exit 0
    fi
    sleep 5
done
cat <<'NEXT'
   Not registered yet — expected on a fresh flash.
   The device is raising its ESPaperConfig access point. From a phone:
     1. join WiFi "ESPaperConfig"
     2. open http://192.168.4.1
     3. enter the Insel credentials
   It registers and pulls the screen on the next wake.
NEXT
