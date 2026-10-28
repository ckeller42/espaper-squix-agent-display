# ESPaper Display Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A display server on odelly that renders an approved recipe into the exact byte format the ESPaper expects, serves it over the device protocol, and shows the same render on a preview web page.

**Architecture:** A deterministic pipeline — recipe plus freshly fetched data goes to a renderer that produces a 1-bit 296×128 image; one packer turns that image into the 4742-byte MiniGrafx payload; the HTTP layer serves those bytes to the device and the identical render as a PNG to the browser. No model runs in this path. Data providers sit behind one small interface so an unofficial source can be swapped without touching the renderer.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, Pillow (1-bit rendering), httpx (data fetching), pytest. Dependencies managed with `uv`.

**Spec:** `docs/superpowers/specs/2026-10-28-espaper-agent-display-design.md`

## Global Constraints

Copied verbatim from the spec. Every task's requirements include these.

- The screen payload is **exactly 4742 bytes**: `6 + (128 × 37)`.
- Header: `offset 0` version (uint8), `offset 1` bitsPerPixel **must be 1**, `offset 2` width **big-endian uint16 = 296**, `offset 4` height **big-endian uint16 = 128**.
- **Palette index 0 is BLACK, 1 is WHITE.** Inverted from the usual "1 = ink". An all-white screen is all bits set (`0xFF` bytes).
- Pixel data is row-major, **MSB-first within each byte**, and **each row restarts on a fresh byte** (37 bytes per row at width 296).
- The server **must never send `X-ESPAPER-COMMAND: UPDATE`** in this plan. OTA belongs to the firmware plan.
- Sleep is controlled by response headers `X-ESPAPER-SLEEP-SECONDS` and `X-ESPAPER-SLEEP-UNTIL`; cadence must be a configuration value, not hard-coded.
- Registration returns identity in **HTTP headers** `X-ESPAPER-DEVICE-ID` and `X-ESPAPER-SECRET`, not in the body.
- Every figure carries its unit or currency: `$216.61`, `7 °C`. NVDA stays in **USD**; no FX conversion.
- Timestamps render in the **timezone of the host preparing the data**, and display the zone abbreviation (`19:02 CET`).
- Rendering is **deterministic**: the same recipe and the same data produce byte-identical output.
- No secrets in the repo.
- Python **3.12** (odelly has 3.12.3).
- Open-Meteo requires attribution: "Weather data by Open-Meteo.com" (CC BY 4.0).

## Review Focus

Failure modes the spec implies that no single task's happy path exercises. Each has a test pinned to the task that owns the code.

1. **A data source is unreachable or times out** — the screen must still render, showing the last known value with its real age, never a blank panel or a crash. (Task 3)
2. **A quote is stale because the market is closed** — the displayed age must come from the quote's own timestamp, not from render time, or a 15-hour-old price appears fresh. (Task 2, Task 3)
3. **The device asks for a screen before any recipe is approved** — first boot does this immediately after registering; a fallback screen must be served, not a 404. (Task 5)
4. **An unknown device id or a wrong secret** — must return **410**, which is the status the firmware handles by clearing its stored identity and re-registering. Any other error leaves it stuck. (Task 5)
5. **A render overflows its region** — the payload must be exactly 4742 bytes regardless of input text length, or the device silently keeps the previous image. (Task 1, Task 4)

---

## Testing layers

Modelled on `open-california`'s `docs/simulation-and-testing.md`. Each layer is
closer to the real device than the one below and runs less often. **Nothing is
flashed until every layer here is green** — the device is the last tier, not
the first.

| Layer | Runs against | Proves | Task |
|---|---|---|---|
| Unit | pure functions | packing, render determinism, source parsing | 1–4 |
| **Payload parity** | the firmware's *own* decode loop, ported to the test | the server's 4742 bytes decode back to exactly the image the renderer drew — this is what catches the inverted palette and row alignment | 7 |
| **Fake device** | a Python client speaking the device protocol | registration, the 410 re-register path, sleep headers, telemetry, first-boot fallback | 8 |
| **Firmware host build** | the real `EspaperParser` compiled for the `native` platform, against a live local server | the firmware's actual HTTP, header-parsing and discovery code — no Arduino hardware | 9 |
| Hardware | the real ESPaper | the radio, the panel, the flash layout | *firmware plan, after all of the above* |

The rule `open-california` states and this inherits: **a fake encodes only
behaviour already verified against the real thing.** Every protocol fact in
these layers was read out of `EspaperClient/` — it is a regression harness and
executable documentation, not an oracle.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/pyproject.toml` | Package metadata, dependencies, pytest config |
| `server/espaper_server/packer.py` | 1-bit image → MiniGrafx payload bytes |
| `server/espaper_server/sources.py` | Data provider interface + Open-Meteo and Yahoo implementations |
| `server/espaper_server/recipe.py` | Recipe model and (de)serialisation |
| `server/espaper_server/render.py` | Recipe + data → 1-bit image, and the PNG preview |
| `server/espaper_server/store.py` | Persistence: recipe, rendered payload, device records, telemetry |
| `server/espaper_server/app.py` | FastAPI app: device endpoints + preview page |
| `server/tests/` | One test module per source module above |

---

### Task 1: Screen payload packer

The byte format is the one thing the device cannot forgive, so it is built and
pinned first, independently of any rendering.

**Files:**
- Create: `server/pyproject.toml`, `server/espaper_server/__init__.py`, `server/espaper_server/packer.py`
- Test: `server/tests/test_packer.py`

**Interfaces:**
- Produces: `pack_screen(image: PIL.Image.Image) -> bytes`, and the constants `SCREEN_WIDTH = 296`, `SCREEN_HEIGHT = 128`, `PAYLOAD_SIZE = 4742`.

- [ ] **Step 1: Scaffold the package**

Create `server/pyproject.toml` with `requires-python = ">=3.12"`, dependencies `fastapi`, `uvicorn`, `pillow`, `httpx`, dev dependency `pytest`, and a `[tool.pytest.ini_options]` block with `testpaths = ["tests"]`.

- [ ] **Step 2: Write the failing tests**

```python
def test_payload_is_exactly_4742_bytes():
    assert len(pack_screen(blank_white_image())) == PAYLOAD_SIZE

def test_header_encodes_bit_depth_and_dimensions_big_endian():
    header = pack_screen(blank_white_image())[:6]
    assert header[1] == 1                      # bitsPerPixel
    assert header[2:4] == (296).to_bytes(2, "big")
    assert header[4:6] == (128).to_bytes(2, "big")

def test_white_is_bit_one_black_is_bit_zero():
    # Palette index 0 is BLACK, 1 is WHITE -- inverted from "1 = ink".
    assert pack_screen(blank_white_image())[6:] == b"\xff" * (128 * 37)
    assert pack_screen(blank_black_image())[6:] == b"\x00" * (128 * 37)

def test_each_row_starts_on_a_fresh_byte():
    # One black pixel at (0, 1) must clear the MSB of row 1's first byte,
    # which is byte 37 of the pixel data -- not a continuation of row 0.
    img = blank_white_image(); img.putpixel((0, 1), 0)
    data = pack_screen(img)[6:]
    assert data[37] == 0x7F
    assert data[36] == 0xFF

def test_rejects_wrong_dimensions():
    with pytest.raises(ValueError):
        pack_screen(Image.new("1", (200, 100), 1))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_packer.py -v`
Expected: FAIL — `packer` has no attribute `pack_screen`

- [ ] **Step 4: Implement `pack_screen(image) -> bytes` in `server/espaper_server/packer.py`**

Raise `ValueError` unless the image is mode `"1"` and exactly 296×128. Emit the 6-byte header, then pack each row MSB-first, starting a new byte at every row.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_packer.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add server/pyproject.toml server/espaper_server/ server/tests/test_packer.py
git commit -m "feat(server): pack 1-bit images into the MiniGrafx screen payload"
```

---

### Task 2: Data sources behind one interface

**Files:**
- Create: `server/espaper_server/sources.py`
- Test: `server/tests/test_sources.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Reading` with fields `value: str` (already formatted, unit or currency included), `observed_at: datetime` (timezone-aware, the source's own timestamp), `label: str`, `extra: dict[str, str]`.
- Produces: `class Source(Protocol): def fetch(self) -> Reading: ...`
- Produces: `WeatherSource(latitude: float, longitude: float, timezone: str)` and `QuoteSource(symbol: str)`.

Note for the implementer: `observed_at` must come from the **provider's** timestamp — Open-Meteo's `current.time`, Yahoo's `meta.regularMarketTime` — never from `datetime.now()`. Review Focus 2 depends on this.

- [ ] **Step 1: Write the failing tests**

Tests use recorded JSON fixtures, not live calls.

```python
def test_weather_formats_value_with_unit():
    assert WeatherSource(48.77, 9.18, "Europe/Berlin")._parse(WEATHER_FIXTURE).value == "9.7 °C"

def test_quote_formats_value_with_currency_symbol():
    assert QuoteSource("NVDA")._parse(QUOTE_FIXTURE).value == "$216.61"

def test_observed_at_comes_from_the_provider_not_now():
    r = QuoteSource("NVDA")._parse(QUOTE_FIXTURE)
    assert r.observed_at == datetime.fromtimestamp(1793211545, tz=timezone.utc)

def test_observed_at_is_timezone_aware():
    assert WeatherSource(48.77, 9.18, "Europe/Berlin")._parse(WEATHER_FIXTURE).observed_at.tzinfo is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_sources.py -v`

- [ ] **Step 3: Implement `sources.py`**

`WeatherSource.fetch()` calls `https://api.open-meteo.com/v1/forecast` (no key) requesting `current=temperature_2m,weather_code` and the daily min/max and precipitation probability. `QuoteSource.fetch()` calls `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}` with a browser `User-Agent`, reading `chart.result[0].meta`. Split parsing into `_parse(payload)` so the tests above need no network. Both use `httpx` with an explicit timeout.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_sources.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/espaper_server/sources.py server/tests/test_sources.py
git commit -m "feat(server): fetch weather and quotes behind one source interface"
```

---

### Task 3: Resilient fetching with honest ages

Owns Review Focus 1 and 2.

**Files:**
- Modify: `server/espaper_server/sources.py`
- Test: `server/tests/test_sources.py`

**Interfaces:**
- Produces: `fetch_with_fallback(source: Source, previous: Reading | None) -> tuple[Reading, bool]` — the reading to display and whether it is a fallback to the previous value.

- [ ] **Step 1: Write the failing tests**

```python
def test_timeout_falls_back_to_previous_reading():
    reading, is_stale = fetch_with_fallback(FailingSource(), previous=OLD_READING)
    assert reading == OLD_READING and is_stale is True

def test_timeout_without_a_previous_reading_does_not_raise():
    reading, is_stale = fetch_with_fallback(FailingSource(), previous=None)
    assert is_stale is True and reading.value == "—"

def test_age_is_measured_from_the_providers_timestamp():
    assert age_of(OLD_READING, now=FIXED_NOW) == timedelta(hours=15)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_sources.py -v`

- [ ] **Step 3: Implement `fetch_with_fallback` and `age_of(reading, now) -> timedelta`**

Catch transport and parse errors only — never a bare `except`. With no previous reading, return a `Reading` whose `value` is an em dash so the renderer always has something to draw.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_sources.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/espaper_server/sources.py server/tests/test_sources.py
git commit -m "feat(server): fall back to the previous reading and report its true age"
```

---

### Task 4: Recipe and renderer

**Files:**
- Create: `server/espaper_server/recipe.py`, `server/espaper_server/render.py`
- Test: `server/tests/test_recipe.py`, `server/tests/test_render.py`

**Interfaces:**
- Produces: `Recipe` with `panels: list[Panel]`, `timezone: str`, and `to_json()` / `from_json(str)`. `Panel` carries a source specification and its display weight.
- Produces: `render(recipe: Recipe, readings: list[Reading], now: datetime) -> PIL.Image.Image` (mode `"1"`, 296×128).
- Produces: `render_png(recipe, readings, now) -> bytes`.

Layout is the spec's layout C: the first panel takes roughly 60% of the width with a large value; the second is a narrower rail separated by a one-pixel vertical rule. Times render in `recipe.timezone` with the zone abbreviation appended.

- [ ] **Step 1: Write the failing tests**

```python
def test_recipe_round_trips_through_json():
    assert Recipe.from_json(RECIPE.to_json()) == RECIPE

def test_render_is_the_right_mode_and_size():
    img = render(RECIPE, READINGS, FIXED_NOW)
    assert img.mode == "1" and img.size == (296, 128)

def test_render_is_deterministic():
    assert pack_screen(render(RECIPE, READINGS, FIXED_NOW)) == pack_screen(render(RECIPE, READINGS, FIXED_NOW))

def test_overlong_text_still_packs_to_the_exact_payload_size():
    readings = [replace(READINGS[0], value="9.7 °C " + "x" * 400), READINGS[1]]
    assert len(pack_screen(render(RECIPE, readings, FIXED_NOW))) == PAYLOAD_SIZE

def test_time_is_rendered_in_the_recipe_timezone_with_the_zone_shown():
    assert "CET" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))

def test_attribution_is_present_when_a_weather_source_is_used():
    assert "Open-Meteo" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))
```

`text_drawn` is a test helper that records strings passed to the drawing calls; implement it in the test module.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_recipe.py tests/test_render.py -v`

- [ ] **Step 3: Implement `recipe.py` and `render.py`**

Draw onto a `PIL.Image.new("1", (296, 128), 1)` (white). Clip every text draw to its panel's box so no input can overflow the canvas. Use a bundled bitmap or TrueType font checked into `server/espaper_server/fonts/` — do **not** rely on a system font, or renders differ between machines and break determinism.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_recipe.py tests/test_render.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/espaper_server/recipe.py server/espaper_server/render.py server/espaper_server/fonts/ server/tests/test_recipe.py server/tests/test_render.py
git commit -m "feat(server): render a recipe into a deterministic 1-bit screen"
```

---

### Task 5: Store and device endpoints

Owns Review Focus 3 and 4.

**Files:**
- Create: `server/espaper_server/store.py`, `server/espaper_server/app.py`
- Test: `server/tests/test_store.py`, `server/tests/test_app.py`

**Interfaces:**
- Produces: `Store(root: Path)` with:
  - `register_device(mac, device_type, timezone) -> tuple[str, str]` — returns `(device_id, secret)`
  - `authenticate(device_id, secret) -> bool`
  - `forget(device_id) -> None` — drops the record, so the next request gets 410
  - `current_payload() -> bytes | None` / `put_payload(data: bytes) -> None`
  - `approve(recipe: Recipe) -> None` — marks a recipe current; renders and stores its payload
  - `pending_recipe() -> Recipe | None` / `is_approved() -> bool` — what the preview page reports
  - `record_telemetry(device_id, headers: Mapping[str, str]) -> None`
  - `last_telemetry(device_id) -> dict` — parsed, so `["battery"]` is an `int`
  - `sleep_seconds() -> int` — from config, never hard-coded
- Produces: FastAPI `app` with `POST /public/devices`, `GET /public/devices/{device_id}/screen`.

- [ ] **Step 1: Write the failing tests**

```python
def test_registration_returns_identity_in_headers_not_the_body():
    r = client.post("/public/devices", json={"macAddress": "AA:BB", "deviceType": "Espaper29Bw", "timeZone": "Europe/Berlin"})
    assert r.status_code == 200
    assert r.headers["X-ESPAPER-DEVICE-ID"] and r.headers["X-ESPAPER-SECRET"]

def test_screen_returns_the_exact_payload_and_sleep_headers():
    r = client.get(f"/public/devices/{dev}/screen", headers=auth)
    assert len(r.content) == PAYLOAD_SIZE
    assert int(r.headers["X-ESPAPER-SLEEP-SECONDS"]) > 0

def test_unknown_device_returns_410_so_the_firmware_reregisters():
    assert client.get("/public/devices/nope/screen", headers={"X-ESPAPER-SECRET": "x"}).status_code == 410

def test_wrong_secret_returns_410():
    assert client.get(f"/public/devices/{dev}/screen", headers={"X-ESPAPER-SECRET": "wrong"}).status_code == 410  # pragma: allowlist secret

def test_screen_before_any_recipe_serves_the_fallback_not_404():
    r = client.get(f"/public/devices/{fresh}/screen", headers=auth)
    assert r.status_code == 200 and len(r.content) == PAYLOAD_SIZE

def test_update_command_header_is_never_sent():
    assert "X-ESPAPER-COMMAND" not in client.get(f"/public/devices/{dev}/screen", headers=auth).headers

def test_telemetry_headers_are_recorded():
    client.get(f"/public/devices/{dev}/screen", headers={**auth, "X-ESPAPER-BATTERY": "812"})
    assert store.last_telemetry(dev)["battery"] == 812
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_store.py tests/test_app.py -v`

- [ ] **Step 3: Implement `store.py` and `app.py`**

The store is a directory: JSON for device records and the recipe, the payload as a file, telemetry appended as JSON lines. The fallback payload is generated at startup by rendering a fixed "waiting for a screen" recipe, so the server still never draws pixels of its own at request time. `sleep_seconds()` reads a config value.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_store.py tests/test_app.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/espaper_server/store.py server/espaper_server/app.py server/tests/test_store.py server/tests/test_app.py
git commit -m "feat(server): serve the device protocol with registration and telemetry"
```

---

### Task 6: Preview page

**Files:**
- Modify: `server/espaper_server/app.py`
- Test: `server/tests/test_app.py`

**Interfaces:**
- Produces: `GET /preview` (HTML) and `GET /preview.png` (image/png).

- [ ] **Step 1: Write the failing tests**

```python
def test_preview_png_is_a_png_of_the_panel_size():
    r = client.get("/preview.png")
    assert r.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(r.content)).size == (296, 128)

def test_preview_page_shows_when_it_was_rendered_and_the_approval_state():
    body = client.get("/preview").text
    assert "CET" in body and ("approved" in body or "awaiting approval" in body)

def test_preview_png_matches_the_payload_served_to_the_device():
    png = Image.open(BytesIO(client.get("/preview.png").content)).convert("1")
    assert pack_screen(png) == client.get(f"/public/devices/{dev}/screen", headers=auth).content
```

The third test is the one that matters: it is what stops the preview from ever drifting from the panel.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_app.py -v`

- [ ] **Step 3: Implement the two routes**

Serve the PNG from the same rendered image the payload was packed from, not a re-render. The page shows the image at 296×128 and scaled, plus the render time with its zone and the approval state.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_app.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/espaper_server/app.py server/tests/test_app.py
git commit -m "feat(server): preview page served from the same render as the panel"
```

---

### Task 7: Payload parity — decode with the firmware's own algorithm

The server is the only writer of this format and the device the only reader, so
nothing yet proves they agree. This task ports the firmware's decode loop into
the test suite and round-trips against it. It is the cheapest layer that would
have caught an inverted palette.

**Files:**
- Create: `server/tests/firmware_decode.py`, `server/tests/test_payload_parity.py`

**Interfaces:**
- Produces: `decode_payload(data: bytes) -> PIL.Image.Image` — a transcription of
  `MiniGrafx::drawPalettedBitmapFromFile` (`lib/MiniGrafx/src/MiniGrafx.cpp`),
  written from the C, not from `packer.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_decode_rejects_a_bit_depth_the_device_would_refuse():
    # The device logs and returns WITHOUT drawing, leaving the old image up.
    bad = bytes([1, 4]) + (296).to_bytes(2,"big") + (128).to_bytes(2,"big") + b"\x00"*4736
    with pytest.raises(ValueError):
        decode_payload(bad)

def test_round_trip_is_pixel_identical(sample_image):
    assert list(decode_payload(pack_screen(sample_image)).getdata()) == list(sample_image.getdata())

def test_round_trip_holds_for_a_real_render():
    img = render(RECIPE, READINGS, FIXED_NOW)
    assert list(decode_payload(pack_screen(img)).getdata()) == list(img.getdata())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_payload_parity.py -v`

- [ ] **Step 3: Transcribe the decoder in `server/tests/firmware_decode.py`**

Read `drawPalettedBitmapFromFile` and transcribe its loop: 6-byte header, reject
a `bitsPerPixel` mismatch, then `shift = 8 - (bitCounter + 1) * bitsPerPixel`,
`paletteIndex = (data >> shift) & bitMask`, with `bitCounter` reset at the end of
each row. Keep it a literal transcription with the C line numbers in comments —
its value is being an *independent* reading of the format.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_payload_parity.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/tests/firmware_decode.py server/tests/test_payload_parity.py
git commit -m "test(server): round-trip payloads through the firmware's own decode loop"
```

---

### Task 8: Fake device — the protocol end to end

**Files:**
- Create: `server/tests/fake_device.py`, `server/tests/test_protocol_e2e.py`

**Interfaces:**
- Produces: `FakeDevice(base_url, mac="AA:BB:CC:DD:EE:FF")` with `register()`,
  `wake()` → `(image, sleep_seconds)`, and a `battery` attribute it reports.

`FakeDevice` must follow the firmware's real sequence (`EspaperClient.ino`):
register only when it has no stored id and secret; send the full
`X-ESPAPER-*` header set on every screen request; on **410**, clear its stored
identity and re-register.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_fresh_device_registers_then_gets_a_screen(live_server):
    d = FakeDevice(live_server); d.register()
    img, sleep_s = d.wake()
    assert img.size == (296, 128) and sleep_s > 0

def test_first_wake_before_any_recipe_shows_the_fallback(live_server):
    d = FakeDevice(live_server); d.register()
    assert d.wake()[0] is not None          # a screen, not an error

def test_410_makes_the_device_reregister(live_server):
    d = FakeDevice(live_server); d.register()
    live_server.store.forget(d.device_id)
    d.wake()
    assert d.device_id and d.device_id != OLD_ID

def test_an_approved_recipe_reaches_the_device(live_server):
    live_server.store.approve(RECIPE)
    assert list(d.wake()[0].getdata()) == list(render(RECIPE, READINGS, FIXED_NOW).getdata())

def test_battery_telemetry_arrives_at_the_server(live_server):
    d = FakeDevice(live_server); d.register(); d.battery = 812; d.wake()
    assert live_server.store.last_telemetry(d.device_id)["battery"] == 812
```

`live_server` is a pytest fixture running the real app with uvicorn on an
ephemeral port, with the data sources stubbed to the recorded fixtures.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_protocol_e2e.py -v`

- [ ] **Step 3: Implement `fake_device.py` and the `live_server` fixture**

The fake decodes screens with `decode_payload` from Task 7, so a format
regression fails here too.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_protocol_e2e.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/tests/fake_device.py server/tests/test_protocol_e2e.py
git commit -m "test(server): drive the protocol end to end with a fake device"
```

---

### Task 9: Firmware host build — the real parser against a live server

The headline requirement: the **firmware's own code** talks to the **real
server** before anything is flashed. `EspaperParser` is plain C++ over a socket
and a string API, so it compiles for PlatformIO's `native` platform behind thin
host shims.

**Files:**
- Create: `test/host/shims/` (Arduino `String`, `Serial`, `WiFiClient` over a
  real POSIX socket), `test/host/test_parser_e2e.cpp`
- Modify: `platformio.ini` (add an `[env:native]`)

**Interfaces:**
- Consumes: the live server from Task 5, started by the test harness.
- Produces: a `native` PlatformIO environment runnable as `pio test -e native`.

- [ ] **Step 1: Add the `native` environment to `platformio.ini`**

```ini
[env:native]
platform = native
test_framework = unity
build_flags = -std=gnu++17 -I test/host/shims -DESPAPER_HOST_TEST
```

Note it must **not** inherit `${esp8266.build_flags}` — those carry the Xtensa
linker script.

- [ ] **Step 2: Write the failing tests**

```cpp
void test_dissect_url_accepts_a_hostname() {           // spec decision 13
    auto u = parser.dissectUrl("http://odelly.fritz.box:8080/public/devices");
    TEST_ASSERT_EQUAL_STRING("odelly.fritz.box", u.host.c_str());
    TEST_ASSERT_EQUAL(8080, u.port);
}
void test_dissect_url_defaults_the_port_for_http() { /* port == 80 */ }
void test_registration_parses_identity_from_headers() { /* against live server */ }
void test_screen_download_yields_the_exact_payload_size() { /* 4742 */ }
void test_sleep_headers_are_parsed() { /* X-ESPAPER-SLEEP-SECONDS */ }
```

- [ ] **Step 3: Run to verify they fail**

Run: `pio test -e native -v`

- [ ] **Step 4: Implement the shims and wire the harness**

Shims provide only what `EspaperParser.cpp` touches. `WiFiClient` becomes a real
TCP socket so the test speaks to the live server rather than a mock. Start the
server from the harness script and pass its port via an environment variable.

- [ ] **Step 5: Run to verify they pass**

Run: `pio test -e native -v`
Expected: all tests PASS against the live server

- [ ] **Step 6: Commit**

```bash
git add platformio.ini test/host/
git commit -m "test(firmware): run EspaperParser natively against the live server"
```

---

### Task 10: Document the layers

**Files:**
- Create: `docs/simulation-and-testing.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Write `docs/simulation-and-testing.md`**

The layer table from this plan, what each layer proves, what it does *not*
prove, and which CI job runs it. State the inherited rule explicitly: a fake
encodes only behaviour verified against the firmware source or the device.

- [ ] **Step 2: Add a line to `AGENTS.md`**

Under Build / flash: `./scripts/gate.sh` now also runs the server suite and the
native firmware tests, and **the device is the last tier — do not flash until
those are green.**

- [ ] **Step 3: Commit**

```bash
git add docs/simulation-and-testing.md AGENTS.md
git commit -m "docs: describe the testing layers and the no-flash-before-green rule"
```

---

### Task 11: CI gate for the server

**Files:**
- Modify: `.github/workflows/ci.yml`, `scripts/gate.sh`

- [ ] **Step 1: Add two jobs to `.github/workflows/ci.yml`**

`Server tests` (unit + parity + protocol e2e) and `Firmware host tests`
(`pio test -e native` against a server the job starts). Both on `ubuntu-24.04`,
keeping the top-level `permissions: {contents: read}`. Give each a
`timeout-minutes` so a hang cannot burn six hours — `open-california` sets this
on its e2e job for exactly that reason.

Pin every action **by commit SHA with the version in a trailing comment**
(`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`), which is
what `open-california` does and what a tag does not give you. This repo
currently pins tags only; convert the existing ones in the same change.

- [ ] **Step 2: Extend `scripts/gate.sh` to mirror CI**

Order matters: server suite, then native firmware tests, then the firmware
build and warning gate. Follow `open-california`'s `tools/ci.sh` convention of
**skipping cleanly with a message** when an optional tool is missing, rather
than failing — the gate must stay runnable on a machine without `uv` or
PlatformIO.

Run: `./scripts/gate.sh`
Expected: `*** GATE PASSED ***`

- [ ] **Step 3: Commit and open a PR**

```bash
git add .github/workflows/ci.yml scripts/gate.sh
git commit -m "ci: run the server test suite in CI and the local gate"
gh pr create --title "feat: ESPaper display server" --fill
```

- [ ] **Step 4: Confirm CI is green**

Run: `gh pr checks --watch`
Expected: `Build firmware` pass, `Server tests` pass. Note `gh repo set-default` is required in a fresh clone — this repo has an `upstream` remote and `gh` otherwise targets ThingPulse.

---

## Not in this plan

- **Firmware server discovery** (spec decision 13) and the **OTA release track** (decision 10) — separate plan. Task 9 builds the host harness they will be tested in, so discovery arrives with an e2e tier already waiting for it.
- **odelly provisioning and the pi-squix agent session** (decisions 1–3) — separate plan.
- The server here reads a recipe it is given. Nothing composes one yet; the fallback screen covers the gap.
- **Flashing.** Explicitly out of scope. The device is the last tier and is not touched until Tasks 7–9 are green.

## Deferred from the spec, deliberately

- **Market-aware cadence** (my call in the spec): `sleep_seconds()` is a config value in Task 5, so the hook exists, but the market-hours logic belongs with the composing agent, not the server.
- **Open-Meteo attribution placement**: Task 4 asserts the string is drawn; where it sits in layout C is a rendering detail for the implementer, constrained only by it being present.
