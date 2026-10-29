# espaper-squix-agent-display

ESP8266 firmware for the Squix / ThingPulse 2.9" ESPaper Plus Kit. Fork of
`ThingPulse/espaper-client`, kept buildable with current tooling. Goal: the
device renders screens pushed by an agent via a server on the LAN.

## Workflow
- **PR-only.** `main` is protected (admins too, conversation resolution required).
  Branch → commit → `gh pr create`. Direct push fails.
- Commit prefixes: `feat:` `fix:` `docs:` `test:` `ci:` `chore:`.
- CodeRabbit reviews every PR. Unresolved threads block merge: fix, then resolve
  via the PR UI or GraphQL `resolveReviewThread`.
- `upstream` remote points at ThingPulse. Keep local changes small and commented
  at the call site so `git pull upstream master` stays reviewable.

## Build / flash
- `./scripts/gate.sh` = secret scan + server suite + native firmware tests +
  containerised build + warning gate (mirrors CI; skips steps whose tool is
  missing, with a message). **The device is the last tier — do not flash until
  those are green.** Layers: `docs/simulation-and-testing.md`.
- Always pass `-e` to `pio test` (`pio test -e native`); `default_envs` is the
  firmware env, so a bare `pio run` builds firmware but a bare `pio test` (or
  `pio test -e <device env>`) fails by design.
- `./scripts/dev.sh build|clean|size|shell` — build only. `SQUIX_ENV` picks the
  PlatformIO env (default `Espaper29Bw-PROD`).
- `./scripts/flash.sh` — flashes from the **host**. `SQUIX_PORT` overrides port
  detection; otherwise it asks when several adapters are present and refuses to
  guess when there is no terminal.
- `pre-commit install` once per clone — hooks are inert otherwise.
- **Configure the device over serial**, not only through the setup AP: in config-portal
  mode the firmware reads commands on the USB line at 115200 (`set ssid <v>`,
  `set password <v>`, `set timezone <v>`, `set ntp <v>`, `set server <url>`,
  `set interval <n>`, `show`, `save`, `restart`, `help`). Values run to end of
  line, so spaces and `=` are kept; `show` never prints the password. The AP
  path still works and both channels share one URL rule
  (`setServerUrlFromInput`).

## Hardware facts (verified on the device, not assumed)
- Board: ESP8266 WROOM-02, 296×128 Waveshare panel. Programmer is a **CP2102**
  (`10C4:EA60`); macOS has the driver built in and names it
  `/dev/cu.usbserial-0001`, **not** `cu.SLAB_USBtoUART` as upstream hardcodes.
- **DTR/RTS are NOT wired to GPIO0/RST.** Flash mode is manual: hold S0 → tap RST
  → release RST → release S0. Upstream's `upload_resetmethod = nodemcu` does not
  match this kit. Beware a false positive: esptool connecting with
  `--before default-reset` only proves the chip was *already* in the bootloader.
  The decisive test is flashing a device that is running the application.
- The e-paper **keeps its image when powered off**, so a populated screen does
  not mean the device is on. "No serial data received" is usually the power
  switch or a reversed programmer, not a missing driver.
- Flash chip reports **4MB** (`a1`/`4016`) though the kit is documented as 2MB.
  We stay on `eagle.flash.2m512.ld`; `--flash-size` in `flash.sh` must match the
  ldscript, not the physical chip, or the filesystem lands at the wrong offset.
- Free heap after init: ~45.9 KB. That is the real budget for new features.

## Gotchas
- **`gh` resolves to `upstream` on this repo.** With the ThingPulse remote present,
  `gh workflow run` / `gh run list` target *their* repo and fail confusingly
  (`404: workflow ci.yml not found on the default branch`). `gh repo set-default
  ckeller42/espaper-squix-agent-display` is already set in this clone; re-run it
  in a fresh clone.
- **Warnings are fixed, not tolerated** — CI fails the build if any appear.
  `-Werror` is deliberately not used (it would also fail on framework headers);
  the gate greps the build output we own.
- **LittleFS, not SPIFFS.** `DEVICE_FS` in `EspaperClient/settings.h` selects it.
  The formats are incompatible: a half-migration means the app writes files the
  renderer cannot find. `lib/MiniGrafx` is vendored *solely* to carry the same
  fix — see `lib/MiniGrafx/VENDORED.md`; candidate to upstream.
- A device provisioned by an older SPIFFS build loses its config once and falls
  back to the `ESPaperConfig` setup AP. Expected, not a bug.
- `platformio.ini` upstream had `build_unflags` **twice** in `[esp8266]`;
  PlatformIO 6 rejects the whole file for that. Do not re-add it.
- MiniGrafx is **not** in the PlatformIO registry. `Mini Grafx@1.2.2` resolves to
  nothing and fails later as a missing header, not a missing dependency.
- `pio/hooks.py` uses `PROJECT_BUILD_DIR`; `PROJECTBUILD_DIR` is PlatformIO ≤3.
- The xtensa-lx106 toolchain is **x86_64-only** — no arm64 build exists anywhere.
  That is why the build is containerised; it is not a preference.
- `scripts/dev.sh` guards `-it` on a TTY and uses `${arr[@]+...}` because macOS
  ships bash 3.2, where `"${empty[@]}"` trips `set -u`.
- detect-secrets only sees **git-tracked** files, and filters documented example
  keys such as `AKIAIOSFODNN7EXAMPLE`.  <!-- pragma: allowlist secret -->
  Verify the hook with a random, real-shaped
  token on a `git add`-ed file, or you will "verify" a hook that does nothing.
- Secrets never belong in source here: WiFi credentials are entered on-device via
  the config portal (S1 + RST) and stored in the device filesystem.
