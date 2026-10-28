#!/usr/bin/env bash
# Flash the ESPaper from the HOST.
#
# This cannot run inside the build container: Docker Desktop, Colima and
# OrbStack all run Linux in a VM, and none of them forward a macOS USB serial
# device into it. So: compile in Docker (scripts/dev.sh), flash from here.
#
#   ./scripts/flash.sh            build, then flash
#   ./scripts/flash.sh --no-build flash the existing firmware.bin
#   ./scripts/flash.sh --monitor  flash, then open the serial console
#
# The ESPaper has no auto-reset circuit, so entering flash mode is MANUAL:
#   1. hold S0        2. tap RST        3. release RST        4. release S0
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIRMWARE="$PROJECT_ROOT/.pio/build/${SQUIX_ENV:-Espaper29Bw-PROD}/firmware.bin"
BAUD="${SQUIX_BAUD:-921600}"
MONITOR_BAUD=115200

# The programmer in the Squix kit is a CP210x or CH340 depending on batch;
# both enumerate under one of these glob patterns on macOS.
list_candidate_ports() {
    ls /dev/cu.usbserial-* /dev/cu.SLAB_USBtoUART* /dev/cu.wchusbserial* 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# TODO(you): implement select_port()
#
# Contract: echo exactly one device path on stdout and return 0, or write a
# message to stderr and return 1. $SQUIX_PORT, if set, must always win so the
# script stays scriptable/CI-friendly.
#
# Input to work with:
#   local -a ports=( $(list_candidate_ports) )   # may be 0, 1 or many entries
#
# The three cases and what is actually at stake:
#
#   0 ports  -> Right now this is YOUR situation: nothing enumerates. Do you
#              fail immediately with a hint about the CP210x/CH340 driver, or
#              poll for a few seconds so you can plug in after starting the
#              script? Polling is friendlier at the desk but hangs CI.
#
#   1 port   -> Obvious: use it. The only question is whether to say so.
#
#   2+ ports -> The interesting one. You own a GL-iNet router, a WalkingPad
#              and assorted Pi gear, so a second adapter being plugged in is
#              realistic. Auto-picking the first match can flash the WRONG
#              device -- recoverable on a dev board, annoying on something
#              mid-deployment. Prompt with a numbered menu? Refuse and demand
#              $SQUIX_PORT? Prefer the most recently appeared device?
#
# My suggestion if you want one: fail fast on 0 with the driver hint, take the
# single match silently on 1, and on 2+ print a numbered menu when stdin is a
# TTY ([[ -t 0 ]]) but hard-fail otherwise -- that keeps it safe interactively
# and deterministic in automation. But the 2+ policy is a real judgement call
# about how much you trust an auto-pick, so it should be yours.
# ---------------------------------------------------------------------------
select_port() {
    echo "select_port() is not implemented yet -- see scripts/flash.sh" >&2
    return 1
}

require_esptool() {
    if ! command -v esptool >/dev/null 2>&1; then
        echo "esptool.py not found. Install it with:  uv tool install esptool" >&2
        exit 1
    fi
}

main() {
    local do_build=1 do_monitor=0
    for arg in "$@"; do
        case "$arg" in
            --no-build) do_build=0 ;;
            --monitor)  do_monitor=1 ;;
            *) echo "unknown option: $arg" >&2; exit 2 ;;
        esac
    done

    require_esptool
    [[ $do_build -eq 1 ]] && "$PROJECT_ROOT/scripts/dev.sh" build

    [[ -f "$FIRMWARE" ]] || { echo "no firmware at $FIRMWARE" >&2; exit 1; }

    local port
    port="${SQUIX_PORT:-$(select_port)}"

    echo
    echo "==> Put the ESPaper into flash mode now:"
    echo "      hold S0  ->  tap RST  ->  release RST  ->  release S0"
    read -r -p "    press Enter when done "

    # no_reset on both ends: the ESPaper's programmer header carries power and
    # the two UART lines only -- DTR/RTS are not wired to GPIO0/RST, which is
    # exactly why flash mode is the manual S0+RST dance above. Letting esptool
    # attempt an auto-reset just adds a confusing failure mode.
    #
    # dout (not qio) matches board_build.flash_mode in platformio.ini.
    esptool --chip esp8266 --port "$port" --baud "$BAUD" \
        --before no_reset --after no_reset \
        write_flash --flash_mode dout --flash_size 2MB 0x0 "$FIRMWARE"

    if [[ $do_monitor -eq 1 ]]; then
        echo "==> opening console at ${MONITOR_BAUD} (ctrl-] to quit)"
        python3 -m serial.tools.miniterm "$port" "$MONITOR_BAUD"
    fi
}

main "$@"
