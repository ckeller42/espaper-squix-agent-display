"""Everything the server remembers, in one directory.

    root/config.json            optional {"sleep_seconds": N}; read on every call
    root/devices/<id>.json      one record per device (secret kept only as a hash)
    root/telemetry/<id>.jsonl   one JSON line per screen request
    root/recipe.json            the recipe being previewed or shown
    root/approved               marker file: present when recipe.json is approved
    root/readings.json          last good reading per source spec, the fallback when a source is down
    root/screen.bin             the payload served to devices
    root/rendered_at            when screen.bin was stored (ISO time)

The store holds bytes. approve() is the only place that composes a screen, and it runs when a
person approves a recipe, never while a device is waiting for a response.
"""

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from espaper_server.packer import PAYLOAD_SIZE, pack_screen
from espaper_server.recipe import Panel, Recipe
from espaper_server.render import render
from espaper_server.sources import QuoteSource, Reading, Source, WeatherSource, fetch_with_fallback

DEFAULT_SLEEP_SECONDS = 3600  # used only when config.json does not say otherwise
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
_TELEMETRY_PREFIX = "X-ESPAPER-"
_NEVER_LOGGED = {"SECRET"}


def source_for(panel: Panel, timezone_name: str) -> Source:
    """Turn a panel's opaque source spec into a Source."""
    spec = panel.source
    match spec.get("type"):
        case "weather":
            return WeatherSource(spec["latitude"], spec["longitude"], timezone_name)
        case "quote":
            return QuoteSource(spec["symbol"])
    raise ValueError(f"unknown source type {spec.get('type')!r}")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _parse_value(text: str) -> int | str:
    try:
        return int(text)
    except ValueError:
        return text


class Store:
    def __init__(
        self,
        root: Path,
        source_factory: Callable[[Panel, str], Source] = source_for,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.root = Path(root)
        self._source_factory = source_factory
        self._clock = clock

    # -- files ------------------------------------------------------------------------------

    def _write(self, relative: str, data: bytes | str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        (tmp.write_bytes if isinstance(data, bytes) else tmp.write_text)(data)
        tmp.replace(path)  # a reader never sees half a file

    def _device_path(self, device_id: str) -> Path | None:
        # The id comes straight from the URL; only plain tokens may touch the filesystem.
        if not _SAFE_ID.fullmatch(device_id):
            return None
        return self.root / "devices" / f"{device_id}.json"

    # -- devices ----------------------------------------------------------------------------

    def register_device(self, mac: str, device_type: str, timezone: str) -> tuple[str, str]:
        device_id, secret = secrets.token_urlsafe(9), secrets.token_urlsafe(32)
        record = {
            "mac": mac,
            "device_type": device_type,
            "timezone": timezone,
            "registered_at": self._clock().isoformat(),
            "secret_sha256": _hash(secret),
        }
        self._write(f"devices/{device_id}.json", json.dumps(record))
        return device_id, secret

    def authenticate(self, device_id: str, secret: str) -> bool:
        path = self._device_path(device_id)
        if path is None or not path.exists():
            return False
        try:
            stored = json.loads(path.read_text())["secret_sha256"]
            return hmac.compare_digest(stored, _hash(secret))
        except (OSError, ValueError, KeyError, TypeError):
            # A damaged record counts as unknown: the caller answers 410 and the device
            # re-registers. Raising here would answer 500 and strand it, never clearing identity.
            return False

    def forget(self, device_id: str) -> None:
        path = self._device_path(device_id)
        if path is not None:
            path.unlink(missing_ok=True)

    # -- the screen -------------------------------------------------------------------------

    def current_payload(self) -> bytes | None:
        path = self.root / "screen.bin"
        return path.read_bytes() if path.exists() else None

    def put_payload(self, data: bytes) -> None:
        if len(data) != PAYLOAD_SIZE:
            raise ValueError(f"a screen payload is exactly {PAYLOAD_SIZE} bytes, got {len(data)}")
        self._write("screen.bin", data)
        self._write("rendered_at", self._clock().isoformat())

    def rendered_at(self) -> datetime | None:
        path = self.root / "rendered_at"
        return datetime.fromisoformat(path.read_text()) if path.exists() else None

    def propose(self, recipe: Recipe) -> None:
        """Park a recipe for preview. The screen devices see does not change until approve()."""
        self._write("recipe.json", recipe.to_json())
        (self.root / "approved").unlink(missing_ok=True)

    def approve(self, recipe: Recipe) -> None:
        """Fetch each panel's source once, render, and store the payload. A source that is down
        falls back to its last good reading, shown with its age, rather than failing the approval."""
        remembered = self._load_readings()
        readings, stale = [], []
        for panel in recipe.panels:
            key = json.dumps(panel.source, sort_keys=True)
            reading, is_stale = fetch_with_fallback(
                self._source_factory(panel, recipe.timezone), remembered.get(key)
            )
            readings.append(reading)
            stale.append(is_stale)
            if not is_stale:
                remembered[key] = reading
        payload = pack_screen(render(recipe, readings, self._clock(), stale=stale))
        self._save_readings(remembered)
        self.put_payload(payload)
        self._write("recipe.json", recipe.to_json())
        self._write("approved", "")

    def _load_readings(self) -> dict[str, Reading]:
        path = self.root / "readings.json"
        if not path.exists():
            return {}
        return {
            key: Reading(**{**r, "observed_at": datetime.fromisoformat(r["observed_at"])})
            for key, r in json.loads(path.read_text()).items()
        }

    def _save_readings(self, readings: dict[str, Reading]) -> None:
        data = {k: {**asdict(r), "observed_at": r.observed_at.isoformat()} for k, r in readings.items()}
        self._write("readings.json", json.dumps(data))

    def pending_recipe(self) -> Recipe | None:
        path = self.root / "recipe.json"
        return Recipe.from_json(path.read_text()) if path.exists() else None

    def is_approved(self) -> bool:
        return (self.root / "approved").exists()

    # -- telemetry --------------------------------------------------------------------------

    def record_telemetry(self, device_id: str, headers: Mapping[str, str]) -> None:
        fields: dict[str, Any] = {}
        for name, value in headers.items():
            upper = name.upper()
            key = upper.removeprefix(_TELEMETRY_PREFIX)
            if upper.startswith(_TELEMETRY_PREFIX) and key not in _NEVER_LOGGED:
                fields[key.lower().replace("-", "_")] = _parse_value(value)
        if not fields or not _SAFE_ID.fullmatch(device_id):
            return
        fields["recorded_at"] = self._clock().isoformat()
        path = self.root / "telemetry" / f"{device_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(fields) + "\n")

    def last_telemetry(self, device_id: str) -> dict[str, Any]:
        if not _SAFE_ID.fullmatch(device_id):
            return {}
        path = self.root / "telemetry" / f"{device_id}.jsonl"
        if not path.exists():
            return {}
        for line in reversed(path.read_text().splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut short by a power failure
        return {}

    # -- config -----------------------------------------------------------------------------

    def sleep_seconds(self) -> int:
        path = self.root / "config.json"
        if not path.exists():
            return DEFAULT_SLEEP_SECONDS
        try:
            seconds = json.loads(path.read_text())["sleep_seconds"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}: expected {{'sleep_seconds': <positive int>}}") from exc
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError(f"{path}: sleep_seconds must be a positive integer, got {seconds!r}")
        return seconds
