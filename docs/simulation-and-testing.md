# Simulation and testing

The device is the slowest, least observable place to find a bug, so the project
climbs a ladder. Each rung runs against something more real than the one below
and is slower and harder to automate. **Do not flash until the rungs above the
hardware are green.**

| Layer | Runs against | Proves | Where | CI job |
|---|---|---|---|---|
| Unit | pure functions | packing, render determinism, source parsing | `server/tests/test_{packer,render,sources,recipe}.py` | `Server tests` |
| Payload parity | the **firmware's own decode loop**, transcribed from `lib/MiniGrafx/src/MiniGrafx.cpp` | the server's 4742 bytes decode back to the image drawn | `server/tests/firmware_decode.py`, `test_payload_parity.py` | `Server tests` |
| Fake device | a Python model of the firmware's protocol sequence | registration, the 410 re-register path, sleep headers, telemetry, first-boot fallback | `server/tests/fake_device.py`, `test_protocol_e2e.py` | `Server tests` |
| Firmware host build | the **real** `EspaperParser` compiled native, against a live server | the firmware's actual HTTP, `dissectUrl` and header parsing | `test/host/` | `Firmware host tests` |
| Hardware | the real ESPaper | the radio, the panel, the flash layout | manual, last | none |

Locally, `./scripts/gate.sh` runs the same steps in the same order as CI:
server suite, native firmware tests, containerised firmware build, warning
gate. It skips a step with a message when its tool (`uv`, `pio`, `docker`) is
missing, so a green gate on a bare machine proves less than a green gate on a
full one. Read the output for "skipping".

## The rule for fakes

**A fake encodes only behaviour that has already been verified against the
firmware source or the device.** It is a regression harness and executable
documentation, not an oracle. When a fake and the firmware disagree, the
firmware wins and the fake is fixed. If a behaviour has not been checked, the
fake must not guess; leave it out, or mark it as unverified.

## What each layer does not prove

- **Unit.** Says nothing about what the firmware does with the bytes. A packer
  can be self-consistent and still be wrong for the device.
- **Payload parity.** Proves the bytes decode correctly through a *transcription*
  of the firmware loop. It does not prove the transcription is faithful beyond
  what was read from source, nor that the panel shows it correctly. Nothing
  about HTTP.
- **Fake device.** Proves the server answers the sequence the model sends. The
  model is a hand-written copy of the firmware's behaviour, so it is only as
  right as the last time someone checked it against the source (see finding 2).
- **Firmware host build.** Runs real firmware code, but against host *shims* for
  `WiFiClient`, `String` and friends. It proves nothing about the ESP8266 TCP
  stack, timing, memory limits, or anything behind `#ifdef` that the shims
  replace. A shim can itself be wrong (finding 3).
- **Hardware.** The only layer that proves the radio, the e-paper panel, the
  LittleFS layout and power behaviour. It is manual and last.

## Findings this ladder produced

These justify having the layers, and each is now pinned by a test.

1. **Truncation invisibility.** The parity round-trip first compared pixel lists
   only. The firmware's decoder reuses the last byte on short input and the
   render has white margins, so truncations of 1, 10, 37 and 148 bytes all
   decoded pixel-identical. Fixed by asserting the payload length and decoded
   size with literals. Lesson: a round-trip that cannot fail on truncation
   proves nothing about length.
2. **Post-registration sleep.** The firmware's `registerDevice` discards the
   screen response, so a freshly registered device sleeps **60 s**, not the
   server's schedule. The fake had it wrong, and the tests discarded the sleep
   value, so nothing caught it. Lesson: a fake that is wrong in a way no
   assertion reads is invisible.
3. **A false belief, corrected.** The design spec claimed `dissectUrl` yields an
   empty host for a path-less URL. It does not: Arduino's `substring` is
   unsigned, so host and port parse and only the path is empty. The empty host
   was an artifact of a **test shim**. A test double created a false belief
   that was then written into a spec as fact; the host tier caught it
   (commit `c2d88a9`). Lesson: shims need the same verification as fakes.

## Known firmware defects found by the host build

Not fixed here: `EspaperClient/` is out of scope for the server plan. They are
routed to the firmware plan.

- `EspaperParser.cpp:118` and `:334`: `if (!client->available() == 0)`, an
  inverted check (`!x == 0` is `x != 0`, written as if it meant `x == 0`).
- `EspaperParser.cpp:378`: `printf` with `%d` given a `long` (`downloadedBytes`). Harmless on the 32-bit ESP8266, where `long` is `int`, but a format mismatch on a 64-bit host.
- `EspaperParser.cpp:427`: an **enum passed to `%s`**, in the `default:` arm of
  the OTA switch. On the device this dereferences a small integer as a
  pointer. It only fires on an unexpected OTA return value, which is why it has
  not shown up in use.

## Running the layers

```bash
cd server && uv run pytest              # unit + parity + fake device
uv sync --project server                # once, provisions server/.venv
pio test -e native                      # firmware host build (9 tests)
./scripts/gate.sh                       # everything, in CI order
```

**Always pass `-e native` to `pio test`.** `platformio.ini` sets
`default_envs = Espaper29Bw-PROD`, so a bare `pio run` builds the firmware. The
`native` env has no `main()` (it exists for `pio test` only), and PlatformIO
cannot exclude a root test suite per environment, so a bare `pio test` or
`pio test -e <device env>` fails by design. `scripts/dev.sh` and CI pass `-e`
explicitly. The native test binary starts the Python server itself from
`server/.venv/bin/python` (override with `ESPAPER_TEST_PYTHON`), so the venv
must exist before `pio test`.
