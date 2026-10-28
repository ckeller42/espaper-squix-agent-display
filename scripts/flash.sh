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

# Pick the serial port to flash.
#
# Policy, and why:
#   $SQUIX_PORT always wins          -- keeps the script scriptable and lets
#                                       CI/agents run without a terminal.
#   0 candidates -> fail with a hint -- the usual causes are a device that is
#                                       switched off or a programmer plugged
#                                       in the wrong way round, not a missing
#                                       driver (macOS has CP210x built in).
#   1 candidate  -> take it, say so  -- the common case, no friction.
#   2+ candidates-> menu, or refuse  -- the dangerous case. Auto-picking the
#                                       first match can flash a DIFFERENT
#                                       board (router, Pi, another ESP), so
#                                       require a human to choose. With no
#                                       terminal there is nobody to ask, so
#                                       refuse rather than guess.
#
# Echoes one device path on stdout; all chatter goes to stderr so that
# `port="$(select_port)"` captures only the path.
select_port() {
    local ports=()
    local p
    while IFS= read -r p; do
        [[ -n "$p" ]] && ports+=("$p")
    done < <(list_candidate_ports)

    case "${#ports[@]}" in
        0)
            cat >&2 <<'NOPORT'
No USB serial adapter found.

Checks, in the order they usually fail:
  1. Is the ESPaper switched ON? The programmer only powers it if it is.
     (The e-paper keeps its image when off, so the screen tells you nothing.)
  2. Is the programmer the right way round? Its +5V pin must line up with
     the 5V pin on the ESPaper, components facing down/back. Plugged in
     reversed the adapter still enumerates on USB but the UART goes nowhere.
  3. Is the ESPaper's own USB port also plugged in? Do not power it from
     both at once.
NOPORT
            return 1
            ;;
        1)
            echo "==> using ${ports[0]}" >&2
            echo "${ports[0]}"
            return 0
            ;;
        *)
            if [[ ! -t 0 ]]; then
                {
                    echo "Found ${#ports[@]} serial adapters and there is no terminal to ask."
                    echo "Refusing to guess -- flashing the wrong board is not recoverable"
                    echo "by this script. Re-run with the one you want:"
                    echo
                    for p in "${ports[@]}"; do echo "    SQUIX_PORT=$p $0 $*"; done
                } >&2
                return 1
            fi

            echo "Several serial adapters are connected:" >&2
            local i=1
            for p in "${ports[@]}"; do
                printf '  %d) %s\n' "$i" "$p" >&2
                i=$((i + 1))
            done

            local choice
            read -r -p "Which one is the ESPaper? [1-${#ports[@]}] " choice
            if ! [[ "$choice" =~ ^[0-9]+$ ]] \
               || (( choice < 1 || choice > ${#ports[@]} )); then
                echo "Not a valid choice: '$choice'" >&2
                return 1
            fi
            echo "${ports[$((choice - 1))]}"
            return 0
            ;;
    esac
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
    echo "==> Put the ESPaper into flash mode:"
    echo "      hold S0  ->  tap RST  ->  release RST  ->  release S0"
    # Only block when a human is present; otherwise the read hits EOF under
    # `set -e` and kills the script. The ESP stays in the bootloader until the
    # next reset, so a non-interactive run is fine if the buttons were pressed
    # beforehand.
    if [[ -t 0 ]]; then
        read -r -p "    press Enter when done "
    else
        echo "    (non-interactive: assuming the device is already in flash mode)"
    fi

    # DTR/RTS are NOT wired to GPIO0/RST on this programmer, so the bootloader
    # must be entered by hand -- as the ThingPulse guide says.
    #
    # Do not be fooled by a successful connect with --before default-reset:
    # that only proves the chip was ALREADY in the bootloader (e.g. you had
    # just pressed the buttons). The decisive test is flashing a device that
    # is running the application -- with auto-reset that works, and here it
    # fails with "No serial data received". Upstream's
    # "upload_resetmethod = nodemcu" does not reflect this kit's wiring.
    #
    # --after no-reset for the same reason: tap RST yourself to run the new
    # firmware.
    #
    # flash-size 2MB matches board_build.ldscript (eagle.flash.2m512.ld), NOT
    # the chip's physical size -- this unit reports 4MB. The header and the
    # linker script must agree or the filesystem lands at the wrong offset.
    #
    # dout (not qio) matches board_build.flash_mode in platformio.ini.
    esptool --chip esp8266 --port "$port" --baud "$BAUD" \
        --before no-reset --after no-reset \
        write-flash --flash-mode dout --flash-size 2MB 0x0 "$FIRMWARE"

    if [[ $do_monitor -eq 1 ]]; then
        echo "==> opening console at ${MONITOR_BAUD} (ctrl-] to quit)"
        python3 -m serial.tools.miniterm "$port" "$MONITOR_BAUD"
    fi
}

main "$@"
