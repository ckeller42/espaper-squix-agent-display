# ESPaper display server

Serves a 296x128 1-bit screen (a 4742-byte payload) to the ESPaper device over
plain HTTP. The device wakes, fetches the screen, draws it and sleeps. The
server never draws while a device waits: it serves bytes that were composed
earlier, when a recipe was approved.

## Run

```bash
cd server
uv sync --frozen
ESPAPER_DATA_DIR=/var/lib/espaper uv run uvicorn espaper_server.app:app --host 192.168.178.43 --port 8411
```

- **Interface.** Bind the LAN address the device can reach (the firmware's
  `SERVER_URL` in `EspaperClient/settings.h` must match it), not `0.0.0.0`
  unless you mean it. There is no authentication on registration or on the
  `/preview*` pages, and the transport is plain HTTP, so keep it off untrusted
  networks.
- **Port.** The firmware setting uses 8411; uvicorn's default is 8000.
- **Data directory.** `ESPAPER_DATA_DIR`, default `data` relative to the
  working directory. It is created on first write.
- Until a recipe is approved, devices get a "Waiting for a screen" payload.
- The screen changes only when a recipe is approved. Nothing re-fetches data on
  a schedule, so a deployed screen ages until someone approves again.

## Look at it

- `/preview` HTML page showing the screen, with the recipe state
- `/preview.png`, `/preview.txt` the exact stored bytes, unpacked

These show what a device would be sent, including before approval of a pending
recipe (which devices do not see yet).

## Data directory

```
config.json                optional, {"sleep_seconds": N}
devices/<id>.json          one record per registered device (secret stored hashed)
telemetry/<id>.jsonl       one JSON line per screen request (X-ESPAPER-* headers except the secret)
recipe.json                the recipe being previewed or shown
approved                   marker file: present when recipe.json is approved
readings.json              last good reading per source, the fallback when a source is down
screen.bin                 the payload served to devices
rendered_at                when screen.bin was stored
```

`screen.bin` is validated on every read (length 4742 and the 6-byte header). If
it is not valid the server logs an error and serves the waiting screen.

## Refresh cadence

`config.json` sets how long the device sleeps between fetches. It is read on
every request, so no restart is needed:

```json
{"sleep_seconds": 900}
```

Without the file the default is 3600. The value must be a positive integer; an
invalid file makes the screen route fail with a server error, so fix it rather
than leave it. This controls how often the device asks, not how often data is
re-fetched (see above).

## Proposing and approving a recipe

There is no CLI and no HTTP route for this. The only interface today is Python
against `Store`, pointed at the same data directory as the running server (the
server reads the files on each request, so a separate process works):

```python
from pathlib import Path
from espaper_server.recipes.weather_nvda import RECIPE   # or build a Recipe
from espaper_server.store import Store

store = Store(Path("/var/lib/espaper"))
store.propose(RECIPE)   # parks it; devices still get the old screen
# open /preview to check, then:
store.approve(RECIPE)   # fetches each source once, renders, stores the payload
```

`propose` clears the approved marker and leaves `screen.bin` alone. `approve`
fetches every panel's source (network access needed); a source that is down
falls back to its last good reading, shown with its age. A recipe is a
`Recipe(timezone=..., panels=[Panel(...)])`; see `espaper_server/recipe.py` and
the shipped `espaper_server/recipes/weather_nvda.py` (Stuttgart weather and
the NVDA quote). Source types: `weather` (latitude, longitude) and `quote`
(symbol).

An agent may also write a pre-rendered payload with `store.put_payload(bytes)`;
it must be exactly 4742 bytes with a valid header or it is refused.

## Tests

```bash
uv run --frozen pytest -q
```
