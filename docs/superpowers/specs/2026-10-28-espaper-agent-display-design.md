# ESPaper agent display — design

**Date:** 2026-10-28
**Status:** design, awaiting approval — not yet planned or built
**Hardware:** Squix / ThingPulse 2.9" ESPaper Plus Kit (ESP8266 WROOM-02, 296×128 1-bit e-paper)

---

## Intent

Christoph asks an agent to show him something, and it appears on the e-paper on
his desk instead of scrolling past in a terminal. The example he gave:

> "show me the weather for today on the left and on the right the nvidia stock price"

The screen stays current — weather shifts, NVDA moves — refreshing every few
minutes without him asking again.

### Why this shape

Three facts drove every decision below.

1. **The ESP8266 cannot join a tailnet.** Every Tailscale port for
   microcontrollers targets ESP32-class silicon; the ESP8266 has ~50 KB of
   usable heap in station mode and this firmware already uses ~35 KB of it.
   So the *server* joins the tailnet and the device talks plain HTTP on the LAN.
2. **A deep-sleeping device cannot be pushed to.** It polls. Everything is
   therefore "leave it on the shelf and the device finds it next time".
3. **The agent does the work, not the server.** The server never understands
   content; it holds bytes.

---

## Goals

- Say what you want in a Claude Code session; see it rendered; it appears.
- The approved screen keeps itself current without further conversation.
- Arbitrary content — this is not a weather station with a stock widget bolted on.
- Nothing on the device needs reflashing to show something new.
- The device keeps itself on the latest firmware over the air.

## Non-goals

- Tailscale, WireGuard or TLS *on the device*.
- A web UI for *composing* screens. The agent is the interface; the web page
  is for looking, not authoring.
- Multi-device support. One ESPaper. The protocol allows more; nothing should
  prevent it, but it is not being built or tested.
- Any content understanding in the server.

## Anti-goals

Things that would mean failure even if it technically worked:

- **A fixed widget template.** Christoph picked the hand-tuned layout over the
  generic two-slot one. If the builder ends up with `renderWeather()` and
  `renderStock()`, the design has been missed.
- **A screen that is silently stale.** A wrong price shown confidently is worse
  than no price. Every figure must be able to say how old it is.
- **A layout that reflows between refreshes.** On a static e-paper panel a
  shifting layout reads as a fault, not as freshness.
- **The device needing the internet.** It talks to one host on the LAN.
- **Secrets in the firmware repo.** WiFi credentials are entered on-device
  through the config portal.

---

## Decisions Christoph made

These are his. Do not revisit them without asking.

1. **Server and agent both on odelly**, user `ckeller`.
2. **This Claude Code session is for conversation only.** It does not fetch,
   compose, render or send. It tells the pi agent what to prepare.
3. **A `pi-squix` agent session on odelly, running under agent-deck**, prepares
   the data, renders the screen, sends it to the device, and owns refreshing
   from then on.
4. **Refresh is deterministic, not a model every time.** The model composes
   once, at approval, and emits a **recipe**. A small deterministic renderer
   replays that recipe every few minutes. The model is invoked again only when
   Christoph asks for something different. This is what keeps the layout
   identical between refreshes and the cost bounded.
5. **Preview is a web page served from odelly.** The agent hands over a URL;
   Christoph looks at the rendered screen in a browser.
6. **Layout C — hand-tuned, weighted.** Weather leads at roughly 60% of the
   width with a large glyph; the second panel is a narrower rail. Explicitly
   chosen over a generic two-slot template, accepting that each new pair of
   things needs its own composition.
7. **Units and currency always shown**: `$216.61` not `216.61`, `7 °C` not
   `7°`. NVDA stays in **USD** — no FX conversion.
8. **Timestamps use the timezone of the host that prepared the data**, and
   display the zone (`19:02 CET`).
9. **The ESPaper joins the WiFi network `Insel`.** The password may be
   requested interactively via `zenity`.
10. **OTA is in scope.** The repo always publishes a latest firmware release
    and the device flashes it when available, following the pattern already
    used in `open-california`.
11. **Server and agent code live in this repo**, through PR flows.
12. **Approval is needed only for a new screen.** When Christoph asks for
    something different, the agent composes it and he approves it at the
    preview URL. Every subsequent refresh of that approved recipe goes up
    without asking — a refresh proposes nothing new, it only replaces numbers.
13. **The device discovers its server**, in this build rather than later. The
    hybrid described below: use the stored URL on wake, fall back to mDNS only
    when that fails, seeded by a config-portal field that can always override
    by hand.

---

## Constraints

### Device protocol — verified by reading the firmware, not assumed

**Base URL** comes from `SERVER_URL` in `EspaperClient/settings.h`. The
`DEV_ENV` branch already does plain HTTP to a LAN address and sets
`USE_SECURE_WIFI_CLIENT 0`, so the build is `Espaper29Bw-DEV` with that
constant pointed at odelly. One-line firmware change plus a reflash.

**Endpoints** (`SERVER_API_DEVICES_PATH` = `/public/devices`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/public/devices` | Register a new device |
| `GET`  | `/public/devices/{deviceId}/screen` | Fetch the current screen |
| `GET`  | `/public/devices/{deviceId}/firmware` | OTA image |

**Registration.** Body is JSON:
`{"macAddress": "...", "deviceType": "Espaper29Bw", "timeZone": "..."}`.
The response returns identity **in HTTP headers, not the body**:
`X-ESPAPER-DEVICE-ID` and `X-ESPAPER-SECRET`.

**Every screen request** carries telemetry the server should log — it is the
only channel the device has:

```
X-ESPAPER-SECRET, X-ESPAPER-BATTERY (raw analogRead(A0), 0..1023),
X-ESPAPER-FREE-HEAP, X-ESPAPER-WIFI-RSSI, X-ESPAPER-CLIENT-VERSION,
X-ESPAPER-MILLIS, X-ESPAPER-SPIFFS-FREE, X-ESPAPER-SPIFFS-TOTAL
```

**The server controls the sleep interval** via response headers — which is why
cadence never requires a reflash:

```
X-ESPAPER-SLEEP-SECONDS: <n>
X-ESPAPER-SLEEP-UNTIL:   <unix epoch>
```

If `SLEEP-UNTIL` is 0 the device uses its compiled-in interval. The sketch
sanity-checks the two and prefers `SLEEP-SECONDS` if they disagree by more than
600 s. Non-200 responses make the device draw an error and retry in 60 s.

### Image format — the part that is easy to get wrong

The device does **not** accept PNG or BMP. The response body is written
verbatim to `/screen` on LittleFS and read by
`MiniGrafx::drawPalettedBitmapFromFile`:

```
offset 0   uint8   version          (only logged, not validated)
offset 1   uint8   bitsPerPixel     MUST be 1, or the device refuses to draw
offset 2   uint16  width   big-endian   = 296
offset 4   uint16  height  big-endian   = 128
offset 6   packed pixel data, row-major, MSB-first within each byte
```

- **Palette index 0 is BLACK, 1 is WHITE** (`palette[] = {MINI_BLACK,
  MINI_WHITE}`). Inverted from the usual "1 = ink" convention. Getting it
  backwards yields a valid, fully inverted screen.
- **Each row restarts on a fresh byte.** 296 / 8 = 37 exactly, so no padding at
  this width, but a renderer assuming a continuous bitstream breaks elsewhere.
- Total payload: `6 + (128 × 37)` = **4742 bytes**.
- A `bitsPerPixel` mismatch logs and returns without drawing — the previous
  image stays up. A silent-looking failure.

### OTA

The firmware implements this already. The device sends
`X-ESPAPER-CLIENT-VERSION` on every screen request; if the server replies
`X-ESPAPER-COMMAND: UPDATE`, the device fetches
`/public/devices/{id}/firmware` and self-updates via `ESP8266httpUpdate`.

Follow the `open-california` pattern: two tracks, `esp-stable` (latest release)
and `esp-latest` (pre-release), each carrying the firmware binary and a
`manifest.json`, published by a dedicated workflow. CI here already builds and
uploads `firmware.bin` plus the versioned `target/Espaper29Bw-*-V0NN.bin`.

Safety notes the builder must respect:

- The version string is `CLIENT_VERSION` in `platformio.ini` (`V031` today).
  Bumping it is what triggers an update; the release and that constant must
  agree or devices will update in a loop or never.
- Flash is 2 MB with a 512 KB filesystem (`eagle.flash.2m512.ld`) and the
  firmware is ~527 KB. Confirm the free space actually accommodates an OTA
  image before enabling it, and verify a rollback path — the device is
  recoverable by manual flash, but that means hands on the hardware.
- The device must never receive `X-ESPAPER-COMMAND: UPDATE` unless a genuinely
  newer, verified image is being served.

### Server discovery (decision 13)

Three facts, all verified against the firmware rather than assumed:

- **`EspaperParser::dissectUrl` already accepts hostnames**, not only IPs. It
  splits host and port and hands the host to the WiFi client, which resolves it
  by DNS. A hostname URL therefore needs no parser work.

  **Correction (verified 2026-10-28 by the native host build, Task 9).** An
  earlier draft of this document claimed a URL with no path yields an *empty
  host*. That was wrong, and the error was mine. Arduino's `String::substring`
  takes **unsigned** arguments, so `substring(0, -1)` from a failed `indexOf`
  wraps, clamps, and means "to the end" — host and port parse correctly. Only
  the **path** comes out empty. The empty-host behaviour was an artifact of a
  test shim that clamped negatives to zero, not of the firmware. `SERVER_URL`
  should still always be concatenated with a path before dissection, because an
  empty path produces a malformed request line — but the failure mode is an
  empty path, not an empty host.
- **`ESP8266mDNS` ships in the Arduino core**, so DNS-SD is available without a
  hand-rolled UDP protocol.
- **The config portal already persists arbitrary key/value pairs** to
  `/espaper.txt` and has a `getFormField()` helper. `SERVER_URL` becomes
  another stored setting alongside `WIFI_SSID` and `UPDATE_INTERVAL_MINS`.

The required behaviour, in order:

1. On wake, use the **stored** server URL. No discovery, no extra radio time —
   this is the steady state and must stay free.
2. **Only if that fails**, run an mDNS query for the service the server
   advertises, and persist whatever it finds for next time.
3. A value entered in the config portal always wins and is never silently
   overwritten by discovery.

Why the order matters: a discovery query on every wake would lengthen the awake
window, and the awake window is the single largest battery cost on this device.
Discovery must be the exception path, not the hot path. mDNS across the two
meshed `Insel` access points may also be unreliable, which is a further reason
not to depend on it routinely.

This is genuine firmware work — discovery, persistence and a fallback path —
not the one-line `SERVER_URL` edit the rest of the design would otherwise need.
It is also the part that cannot be fixed without physical access to the device
(DTR/RTS are not wired, so reflashing means the manual S0/RST sequence), which
raises the bar for testing it before it ships.

### Network

`Insel` **is** the Fritz!Box network — odelly is already on it at
`192.168.178.85/24`. So the device lands on the same subnet as the server and
plain HTTP works with no routing. Two access points broadcast it (signal 90 and
55); the device picks one.

### Host

**odelly** holds the server, the renderer and the pi agent.

| | |
|---|---|
| Hardware | x86_64, 16 cores, 31 GB RAM, 729 GB free |
| OS | Pop!\_OS 24.04 LTS, Python 3.12.3, git 2.43 |
| LAN / tailnet | `192.168.178.85` / `100.65.26.115` |
| Sleep | `sleep.target` and `suspend.target` both **masked** |
| Installed | **nothing else**: no node, npm, docker, uv, claude, pi, agent-deck, chezmoi |

masterpi was considered and rejected: `armv7l` 32-bit (Node ≤ 22, the last line
with official armv7l builds) and a live home-automation hub running FHEM,
Grafana, InfluxDB, Mosquitto, Homebridge and nginx with 55 days uptime.

---

## How it fits together

```
  Christoph ⇄ this Claude Code session (bar)        ← conversation only
                     │  "weather left, NVDA right"
                     ▼
  ┌──────────────────────────────────────────────────────────┐
  │ odelly  192.168.178.85                                   │
  │                                                          │
  │  pi-squix agent session (agent-deck)                     │
  │    composes ONCE → emits recipe                          │
  │                                                          │
  │  deterministic renderer (every few minutes)              │
  │    recipe + fresh data → 4742-byte screen                │
  │                                                          │
  │  display server         preview web page (a URL)         │
  └──────────────────────────────────────────────────────────┘
                              ▲
                              │ plain HTTP, LAN (Insel)
                   ESPaper (deep sleep → wake → GET → draw → sleep)
```

### The recipe

Decision 4 makes the recipe the centre of the system. It must carry enough for
a non-model renderer to reproduce the screen with fresh numbers: which data to
fetch, and how to lay it out. The server stores it next to the rendered image
and treats it as **opaque** — it never parses or acts on it. Only agents and the
renderer read it.

---

## Calls I made (not Christoph's — check these)

- **Data sources.** He said "just guess what works". Both verified live today:
  - **Weather: Open-Meteo.** No API key at all. Returns units and
    `Europe/Berlin` directly. Live check returned 9.7 °C for Stuttgart.
    CC BY 4.0 — attribution ("Weather data by Open-Meteo.com") is required
    wherever its data is shown, which on a 296×128 panel needs a decision about
    where that fits.
  - **Quote: Yahoo's public chart endpoint**
    (`query1.finance.yahoo.com/v8/finance/chart/NVDA`). No key. Live check
    returned 216.61 USD, NasdaqGS, with the quote's own timestamp. It is
    **unofficial** and can break or start blocking; isolate it behind a small
    interface so swapping costs little. Documented fallback: **Finnhub** with a
    free key. Third-party sources disagree on Finnhub's free-tier limits and
    whether its US quotes are real-time, and its pricing page does not say —
    verify before relying on it.
  - The quote carries its own timestamp. **Display it.** That is what turns a
    delayed quote from a silent lie into an honest one, and it is the direct
    answer to the staleness anti-goal.
  - **Cadence should be market-aware.** NVDA does not move outside US market
    hours (roughly 15:30–22:00 CET). Refreshing the quote every few minutes
    overnight burns API calls and battery for nothing.
- **Fallback screens are pre-rendered by the agent, not drawn by the server.**
  The device registers and *immediately* GETs `/screen` before any recipe
  exists. Rather than give the server a renderer and a font — which would break
  "the server holds bytes" — the agent pre-renders a small set of fallback
  screens that the server serves verbatim.
- ~~odelly gets a DHCP reservation~~ — **withdrawn.** This existed only because
  a compiled-in IP could be stranded by a new DHCP lease. Decision 13 removes
  the cause: the device discovers and re-persists the server address. A
  reservation is still worth having for everything else on odelly, but it is no
  longer load-bearing for this system.
- **Testing runs on USB**, not battery. A multi-day 3-minute cadence is
  harmless on USB and punishing on a 600 mAh cell.
- **No ThingPulse registration to lose.** This device has never been registered
  with their service; it is ours outright.

---

## Left to the builder

- Server language and framework. Python 3.12 is already on odelly.
- How the server and renderer run (systemd units, containers) and survive reboot,
  including what keeps the agent-deck session alive.
- Storage layout for image, recipe, device state and telemetry. Nothing here
  needs a database.
- The recipe's concrete format — the server does not care; it must be
  replayable by a non-model renderer.
- The rendering path to the 4742-byte payload, and the preview page, which
  should come from the same renderer so the preview cannot drift from the panel.
- How this session talks to the pi-squix session (agent-deck `session send`,
  an HTTP call, or a file). This crosses a host boundary, `bar` → odelly.
- Whether registration auto-accepts the first device or is explicit.
- The mDNS service name and how the server advertises it on odelly (Avahi is
  the obvious route on Pop!\_OS). Also what the device does when discovery
  finds **more than one** server, and what it shows when it finds none —
  failing to a blank panel would be worse than failing to a message.
- How much heap the mDNS path costs. There is ~45.9 KB free after init, and
  the framebuffer allocation is already the tight moment in the cycle
  (`getAndDrawScreen` deliberately returns before allocating it on the OTA
  path to avoid fragmenting memory). Measure before and after.
- Provisioning odelly: Claude Code, pi, agent-deck and credentials on a
  headless box as `ckeller`. Headless auth is the sharp edge — if only
  interactive OAuth is possible, decision 3 needs rethinking rather than
  silently degrading to a cron job. The `setting-up-a-machine` skill covers
  this ground.
- How a recipe is marked approved, and what the device shows between a new
  screen being composed and Christoph approving it — decision 12 sets the rule,
  not the mechanism.

---

## Open question deliberately deferred

**Refresh cadence versus battery life.** Each wake costs a WiFi association and
a full e-paper refresh. The device reports `X-ESPAPER-BATTERY` on every
request, so the real drain can be observed and the interval tuned from data.
The builder should not hard-code a cadence that is awkward to change.
