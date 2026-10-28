import json
import httpx2
import pytest

from espaper_server.packer import PAYLOAD_SIZE, pack_screen
from espaper_server.recipe import Recipe
from espaper_server.render import render
from espaper_server.store import DEFAULT_SLEEP_SECONDS, Store
from tests.recipes import FIXED_NOW, READINGS, RECIPE


class FakeSource:
    def __init__(self, reading=None):
        self.reading = reading

    def fetch(self):
        if self.reading is None:
            raise httpx2.ConnectError("offline")
        return self.reading


def factory_for(*readings):
    """A source_factory serving readings[i] to panel i (None means the source is down)."""
    sources = iter(FakeSource(r) for r in readings)
    return lambda panel, tz: next(sources)


def make_store(tmp_path, *readings):
    return Store(tmp_path, source_factory=factory_for(*(readings or READINGS)), clock=lambda: FIXED_NOW)


def test_register_then_authenticate(tmp_path):
    store = Store(tmp_path)
    device_id, secret = store.register_device("AA:BB", "Espaper29Bw", "Europe/Berlin")
    assert store.authenticate(device_id, secret)
    assert not store.authenticate(device_id, "wrong")
    assert not store.authenticate("nope", secret)


def test_secrets_are_unique_and_not_stored_in_clear(tmp_path):
    store = Store(tmp_path)
    a = store.register_device("AA:BB", "Espaper29Bw", "Europe/Berlin")
    b = store.register_device("AA:BB", "Espaper29Bw", "Europe/Berlin")
    assert a[0] != b[0] and a[1] != b[1]
    assert a[1] not in "".join(p.read_text() for p in tmp_path.rglob("*.json"))


def test_authentication_survives_a_restart(tmp_path):
    device_id, secret = Store(tmp_path).register_device("AA:BB", "Espaper29Bw", "UTC")
    assert Store(tmp_path).authenticate(device_id, secret)


def test_forget_makes_authentication_fail(tmp_path):
    store = Store(tmp_path)
    device_id, secret = store.register_device("AA:BB", "Espaper29Bw", "UTC")
    store.forget(device_id)
    assert not store.authenticate(device_id, secret)
    store.forget(device_id)  # forgetting twice is harmless


@pytest.mark.parametrize("bad_id", ["../etc/passwd", "a/b", "", "..", "a.json"])
def test_hostile_device_ids_are_simply_unknown(tmp_path, bad_id):
    assert not Store(tmp_path).authenticate(bad_id, "x")


def test_payload_roundtrip_and_empty_default(tmp_path):
    store = Store(tmp_path)
    assert store.current_payload() is None
    store.put_payload(b"\x01" * PAYLOAD_SIZE)
    assert Store(tmp_path).current_payload() == b"\x01" * PAYLOAD_SIZE


def test_nothing_is_approved_at_first(tmp_path):
    store = Store(tmp_path)
    assert store.pending_recipe() is None and not store.is_approved()


def test_proposed_recipe_is_pending_and_leaves_the_screen_alone(tmp_path):
    store = make_store(tmp_path)
    store.put_payload(b"\x02" * PAYLOAD_SIZE)
    store.propose(RECIPE)
    assert store.pending_recipe() == RECIPE and not store.is_approved()
    assert store.current_payload() == b"\x02" * PAYLOAD_SIZE


def test_approve_renders_and_stores_the_payload(tmp_path):
    store = make_store(tmp_path)
    store.approve(RECIPE)
    expected = pack_screen(render(RECIPE, READINGS, FIXED_NOW, stale=[False, False]))
    assert store.current_payload() == expected and len(expected) == PAYLOAD_SIZE
    assert store.is_approved() and store.pending_recipe() == RECIPE
    reopened = Store(tmp_path)
    assert reopened.is_approved() and reopened.pending_recipe() == RECIPE


def test_a_new_proposal_after_approval_is_unapproved_again(tmp_path):
    store = make_store(tmp_path)
    store.approve(RECIPE)
    store.propose(RECIPE)
    assert not store.is_approved()


def test_approve_passes_stale_flags_to_the_renderer(tmp_path):
    make_store(tmp_path).approve(RECIPE)  # first approval remembers both good readings
    store = make_store(tmp_path, None, READINGS[1])  # now the weather source is down
    store.approve(RECIPE)
    flagged = pack_screen(render(RECIPE, READINGS, FIXED_NOW, stale=[True, False]))
    unflagged = pack_screen(render(RECIPE, READINGS, FIXED_NOW, stale=[False, False]))
    assert flagged != unflagged  # the flag is visible, so the next assertion means something
    assert store.current_payload() == flagged


def test_approve_with_a_source_down_and_no_history_still_succeeds(tmp_path):
    store = make_store(tmp_path, None, None)
    store.approve(RECIPE)
    assert len(store.current_payload()) == PAYLOAD_SIZE and store.is_approved()


def test_approve_builds_real_sources_from_panel_specs(tmp_path):
    from espaper_server.sources import QuoteSource, WeatherSource
    from espaper_server.store import source_for

    weather, quote = RECIPE.panels
    assert isinstance(source_for(weather, "Europe/Berlin"), WeatherSource)
    assert isinstance(source_for(quote, "Europe/Berlin"), QuoteSource)
    from dataclasses import replace

    with pytest.raises(ValueError, match="unknown source"):
        source_for(replace(weather, source={"type": "tarot"}), "UTC")


def test_telemetry_is_parsed(tmp_path):
    store = Store(tmp_path)
    device_id, _ = store.register_device("AA:BB", "Espaper29Bw", "UTC")
    store.record_telemetry(
        device_id,
        {
            "x-espaper-secret": "hunter2",  # pragma: allowlist secret
            "X-ESPAPER-BATTERY": "812",
            "X-ESPAPER-FREE-HEAP": "30000",
            "X-ESPAPER-WIFI-RSSI": "-61",
            "X-ESPAPER-CLIENT-VERSION": "V031",
            "Accept": "*/*",
        },
    )
    got = store.last_telemetry(device_id)
    assert got["battery"] == 812 and got["free_heap"] == 30000 and got["wifi_rssi"] == -61
    assert got["client_version"] == "V031"
    assert "secret" not in got and "accept" not in got
    assert "hunter2" not in "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())


def test_last_telemetry_is_the_latest_and_empty_when_none(tmp_path):
    store = Store(tmp_path)
    device_id, _ = store.register_device("AA:BB", "Espaper29Bw", "UTC")
    assert store.last_telemetry(device_id) == {}
    store.record_telemetry(device_id, {"X-ESPAPER-BATTERY": "800"})
    store.record_telemetry(device_id, {"X-ESPAPER-BATTERY": "790"})
    assert store.last_telemetry(device_id)["battery"] == 790
    assert len((tmp_path / "telemetry" / f"{device_id}.jsonl").read_text().splitlines()) == 2


def test_telemetry_ignores_a_garbled_trailing_line(tmp_path):
    store = Store(tmp_path)
    device_id, _ = store.register_device("AA:BB", "Espaper29Bw", "UTC")
    store.record_telemetry(device_id, {"X-ESPAPER-BATTERY": "800"})
    with open(tmp_path / "telemetry" / f"{device_id}.jsonl", "a") as f:
        f.write('{"battery": 7')  # power cut mid-write
    assert store.last_telemetry(device_id)["battery"] == 800


def test_sleep_seconds_defaults_and_reads_config(tmp_path):
    store = Store(tmp_path)
    assert store.sleep_seconds() == DEFAULT_SLEEP_SECONDS > 0
    (tmp_path / "config.json").write_text(json.dumps({"sleep_seconds": 120}))
    assert store.sleep_seconds() == 120  # picked up without a restart


@pytest.mark.parametrize("bad", ['{"sleep_seconds": 0}', '{"sleep_seconds": "x"}', "not json"])
def test_bad_sleep_config_is_an_error_not_a_silent_default(tmp_path, bad):
    (tmp_path / "config.json").write_text(bad)
    with pytest.raises(ValueError):
        Store(tmp_path).sleep_seconds()


def test_put_payload_rejects_a_wrong_sized_payload(tmp_path):
    store = Store(tmp_path)
    for bad in (b"", b"\x00" * 10, b"\x00" * (PAYLOAD_SIZE + 1)):
        with pytest.raises(ValueError, match="4742"):
            store.put_payload(bad)
    assert store.current_payload() is None


@pytest.mark.parametrize("damage", ["", "{not json", "[]", '{"mac": "AA"}'])
def test_a_corrupt_device_record_is_unknown_not_an_error(tmp_path, damage):
    store = Store(tmp_path)
    device_id, secret = store.register_device("AA:BB", "Espaper29Bw", "UTC")
    (tmp_path / "devices" / f"{device_id}.json").write_text(damage)
    assert not store.authenticate(device_id, secret)
