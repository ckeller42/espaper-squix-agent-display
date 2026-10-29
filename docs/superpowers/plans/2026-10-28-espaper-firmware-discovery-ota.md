# ESPaper Firmware: Discovery and OTA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The device finds its own server and keeps its own firmware current, so neither a DHCP lease nor a code change requires walking over to the board with a programmer.

**Architecture:** Three independent pieces. The server URL becomes a stored setting rather than a compile-time constant, seeded by the config portal. mDNS discovery runs **only when the stored URL fails**, so the steady state costs no radio time. OTA follows the `open-california` two-track release pattern, with the server deciding when to offer an update.

**Tech Stack:** ESP8266 Arduino core 3.1.2 (PlatformIO `espressif8266@4.2.1`), `ESP8266mDNS` from the core, LittleFS, the existing Python display server, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-28-espaper-agent-display-design.md` — decisions 10 (OTA) and 13 (discovery).

## Global Constraints

- **Every change to `EspaperClient/` must stay reviewable against upstream.** This is a fork of `ThingPulse/espaper-client` with `upstream` still wired. Keep local changes small, commented at the call site, and separable.
- The device has **~45.9 KB free heap after init**, and the framebuffer allocation is already the tight moment in the cycle — `getAndDrawScreen` deliberately returns *before* allocating it on the OTA path to avoid fragmenting memory. **Measure heap before and after** any addition.
- Flash is 2 MB with a 512 KB filesystem (`eagle.flash.2m512.ld`); the firmware is ~525 KB. **Confirm an OTA image fits before enabling OTA.**
- `CLIENT_VERSION` in `platformio.ini` (`V031` today) is what triggers an update. The release tag and that constant **must agree** or devices update in a loop or never.
- **Warnings are fixed at the source, never suppressed.** The containerised build is gated on being warning-free.
- Flashing requires the manual **S0 → RST** sequence. Every reflash is a trip to the bench, which is the whole reason this plan exists.
- Tests make no external network calls.

## Review Focus

Failure modes the spec implies that no task's happy path exercises.

1. **Discovery finds more than one server.** Two servers answering `_espaper._tcp` must not produce a coin flip. (Task 4)
2. **Discovery finds none, and the stored URL is also dead.** Failing to a blank panel is worse than failing to a message you can read across the room. (Task 4)
3. **A stored URL that resolves but serves something else.** DHCP reuse means yesterday's address can belong to a different device today. (Task 3)
4. **An OTA image that is valid but wrong** — right size, right hash, wrong build. `CLIENT_VERSION` disagreeing with the release tag is the live case. (Task 6)
5. **A 410 loop with no sleep.** `ESP.restart()` on 410 means a device repeatedly getting 410 reboots continuously rather than sleeping, flattening a 600 mAh cell in hours. (Task 7)

---

## File Structure

| File | Responsibility |
|---|---|
| `EspaperClient/EspaperParser.cpp` | Three defect fixes (Task 1) |
| `EspaperClient/configportal.h` | `SERVER_URL` as a stored setting (Task 2) |
| `EspaperClient/discovery.h/.cpp` | mDNS lookup, isolated so it can be tested and excluded |
| `EspaperClient/EspaperClient.ino` | Wiring: stored URL → fetch → discovery on failure |
| `test/host/test_discovery.cpp` | Host-tier tests for the above |
| `server/espaper_server/app.py` | `/firmware` route, version compare (Task 6) |
| `.github/workflows/esp-release.yml` | `esp-stable` / `esp-latest` tracks |

---

### Task 1: Fix the three firmware defects

Smallest task, and the one worth offering upstream. Found by the native host build in the server plan's Task 9.

**Files:** Modify `EspaperClient/EspaperParser.cpp`

- [ ] **Step 1: Fix the inverted check at `:118` and `:334`**

`if (!client->available() == 0)` reads backwards — it fires when data *is* available, so the "disconnected" message is wrong. It gates a log line only, so behaviour is unchanged; the fix is for the reader and to clear two host-build warnings.

- [ ] **Step 2: Fix `:378` — `%d` with a `long`**

`Serial.printf("... size %d", downloadedBytes)`. Correct on the 32-bit device, a width mismatch anywhere else. Use the right specifier.

- [ ] **Step 3: Fix `:427` — an enum passed to `%s`**

```c
Serial.printf_P(PSTR("%s is an unexpected return value..."), ret);
```

`ret` is an enum. On the device this dereferences a small integer as a pointer. It sits in the `default:` arm of the OTA switch, so it fires only on an *unexpected* update return — during a firmware update, in the path you rely on to say what went wrong. Print the integer.

- [ ] **Step 4: Verify the host build is warning-free**

Run: `pio test -e native`
Expected: 9 tests pass, and the two `EspaperParser.cpp` warnings are gone.

- [ ] **Step 5: Commit, and open an upstream PR**

These are upstream's bugs, not ours. Offer them back.

---

### Task 2: `SERVER_URL` becomes a stored setting

**Files:** Modify `EspaperClient/configportal.h`, `EspaperClient/settings.h`
**Test:** `test/host/test_settings.cpp`

**Interfaces:**
- Produces: `SERVER_URL` loaded from `/espaper.txt` like `WIFI_SSID`, with the compiled-in value as the default.

The portal already persists arbitrary key/value pairs and has a `getFormField()` helper, so this is roughly four lines plus the form field.

- [ ] **Step 1: Write the failing host test**

```cpp
void test_stored_server_url_overrides_the_compiled_default();
void test_absent_stored_url_falls_back_to_the_compiled_default();
```

- [ ] **Step 2: Run to verify it fails** — `pio test -e native`

- [ ] **Step 3: Add `SERVER_URL` to the portal's save/load and form**

Mirror `UPDATE_INTERVAL_MINS` exactly — it is the closest existing analogue. Remove the PROVISIONAL comment from `settings.h` once the stored value wins.

- [ ] **Step 4: Run to verify it passes**

- [ ] **Step 5: Commit**

---

### Task 3: Validate a stored URL before trusting it

Owns Review Focus 3.

**Files:** Modify `EspaperClient/EspaperClient.ino`
**Test:** `test/host/test_discovery.cpp`

- [ ] **Step 1: Write the failing test**

```cpp
void test_a_stored_url_serving_a_non_espaper_response_is_rejected();
void test_a_valid_stored_url_is_used_without_discovery();   // no mDNS query at all
```

The second matters most: it pins the steady state as **free**. Discovery must not run when the stored URL works.

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement**

A stored URL is trusted only if the screen request returns 200 with a payload of exactly `PAYLOAD_SIZE`. Anything else — including a 200 of the wrong size from an unrelated device on a reused address — falls through to discovery.

- [ ] **Step 4: Run to verify it passes**

- [ ] **Step 5: Commit**

---

### Task 4: mDNS discovery as the exception path

Owns Review Focus 1 and 2.

**Files:** Create `EspaperClient/discovery.h`, `EspaperClient/discovery.cpp`
**Test:** `test/host/test_discovery.cpp`

**Interfaces:**
- Produces: `String discoverServer()` — returns a URL, or `""` when nothing is found.

- [ ] **Step 1: Write the failing tests**

```cpp
void test_discovery_returns_empty_when_nothing_answers();
void test_discovery_picks_deterministically_when_two_servers_answer();
void test_a_discovered_url_is_persisted_for_next_wake();
void test_the_config_portal_value_is_never_overwritten_by_discovery();
```

The last is a decision, not a detail: a hand-entered URL must win permanently, or the feature becomes unpredictable exactly when someone is trying to control it.

**Amendment, found while implementing Task 2.** A discovered URL and a hand-entered
one are currently stored *identically* in `/espaper.txt`, so nothing can tell them
apart and "hand-entered wins" is unimplementable as written. This task must add a
second key — `SERVER_URL_SOURCE` with values like `manual` / `discovered` — and
discovery must refuse to overwrite a `manual` entry. Without it the rule above is
a comment, not a behaviour.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement `discoverServer()`**

Query `_espaper._tcp`. On multiple answers, pick by a stated rule (lowest IP is fine — the requirement is *deterministic*, not *clever*) and say so in a comment. On zero answers, return `""`.

- [ ] **Step 4: Measure the heap cost**

Run: capture `ESP.getFreeHeap()` before and after the mDNS query on-device.
Expected: record the number in the report. The budget is ~45.9 KB and the framebuffer is the tight moment.

- [ ] **Step 5: Draw a readable failure**

When both the stored URL and discovery fail, draw a message naming what was tried. A blank panel is indistinguishable from a flat battery across a room.

- [ ] **Step 6: Run to verify they pass, then commit**

---

### Task 5: Server advertises the service

**Files:** Modify `server/espaper_server/` (a small Avahi/zeroconf publisher), `server/README.md`
**Test:** `server/tests/test_discovery_advert.py`

- [ ] **Step 1: Write the failing test** — the service is advertised with the expected name, port and TXT record.
- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_discovery_advert.py -v`
- [ ] **Step 3: Implement.** On odelly (Pop!\_OS) Avahi is the obvious route. Keep it optional — the server must still run when zeroconf is unavailable.
- [ ] **Step 4: Run to verify it passes**
- [ ] **Step 5: Document it in `server/README.md`, then commit**

---

### Task 6: OTA — release track and server side

Owns Review Focus 4.

**Files:** Create `.github/workflows/esp-release.yml`; modify `server/espaper_server/app.py`, `store.py`
**Test:** `server/tests/test_ota.py`

Follow `open-california`: two tracks, `esp-stable` (latest) and `esp-latest` (pre-release), each carrying the firmware binary and a `manifest.json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_matching_client_version_is_not_offered_an_update():
    assert "X-ESPAPER-COMMAND" not in headers_for(client_version="V031")

def test_a_newer_release_offers_exactly_one_update_command():
    assert headers_for(client_version="V030")["X-ESPAPER-COMMAND"] == "UPDATE"

def test_the_firmware_route_serves_the_release_binary_byte_for_byte():
def test_a_manifest_version_disagreeing_with_client_version_is_refused():
```

The last one is Review Focus 4: a mismatch must fail loudly at release time, not put devices in an update loop.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_ota.py -v`

- [ ] **Step 3: Implement the `/firmware` route and the version comparison**

Until this task, the server must **never** send `X-ESPAPER-COMMAND: UPDATE` — that constraint from the server plan is lifted only here, and only behind a real version comparison.

- [ ] **Step 4: Add the release workflow**

SHA-pin every action with a version comment. Verify `CLIENT_VERSION` and the release tag agree, and fail the workflow if not.

- [ ] **Step 5: Confirm an OTA image fits**

Run: check free space against `eagle.flash.2m512.ld` with a ~525 KB image.
Expected: a written answer, not an assumption. If it does not fit, stop — the layout must change first.

- [ ] **Step 6: Run to verify they pass, then commit**

---

### Task 7: Stop the 410 reboot loop

Owns Review Focus 5.

**Files:** Modify `EspaperClient/EspaperClient.ino`
**Test:** `server/tests/test_protocol_e2e.py` (the fake device already models the restart)

- [ ] **Step 1: Write the failing test**

```python
def test_repeated_410_does_not_reboot_continuously():
    # Three 410s in a row must produce at least one sleep, not three instant restarts.
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement**

`ESP.restart()` on 410 currently has no sleep. Today's server terminates the loop because registration writes the record before responding — but any future path that answers 410 to a just-registered device flattens a 600 mAh cell in hours. Sleep before restarting after a repeated 410.

- [ ] **Step 4: Run to verify it passes, then commit**

---

### Task 8: Bench verification

**This task needs the hardware** and cannot be completed from software. It is written down so the device work is not "done" until it is checked.

- [ ] **Step 1: Flash and confirm the boot log**
- [ ] **Step 2: Confirm the panel shows the server's screen** — and specifically **that it is not inverted**. The palette direction (`palette[] = {MINI_BLACK, MINI_WHITE}`) is the one property no software tier can prove; every tier passes if that reading is backwards and the panel shows a perfect negative.
- [ ] **Step 3: Move the server and confirm discovery re-points the device without a reflash**
- [ ] **Step 4: Bump `CLIENT_VERSION`, release, and confirm the device updates itself**
- [ ] **Step 5: Record the measured heap and the real battery drain at the chosen cadence**

---

## Not in this plan

- Composing screens, the pi-squix agent session, or odelly provisioning — spec decisions 1–3, a separate plan.
- TLS on the device. The spec rules it out: the ESP8266 cannot afford it alongside the framebuffer.
