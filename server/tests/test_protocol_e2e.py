"""The whole device protocol against a real running server, with no hardware."""

from espaper_server.render import render
from tests.fake_device import FakeDevice
from tests.recipes import FIXED_NOW, READINGS, RECIPE


def registered_device_count(live_server) -> int:
    return len(list((live_server.store.root / "devices").glob("*.json")))


def test_a_fresh_device_registers_then_gets_a_screen(live_server):
    d = FakeDevice(live_server)
    d.register()
    img, sleep_s = d.wake()
    assert img.size == (296, 128) and sleep_s > 0


def test_first_wake_before_any_recipe_shows_the_fallback(live_server):
    d = FakeDevice(live_server)
    d.register()
    assert d.wake()[0] is not None  # a screen, not an error


def test_a_device_with_stored_identity_does_not_register_again(live_server):
    d = FakeDevice(live_server)
    d.register()
    d.wake()
    d.wake()
    assert registered_device_count(live_server) == 1


def test_a_device_with_no_identity_registers_on_its_first_wake(live_server):
    d = FakeDevice(live_server)
    img, sleep_s = d.wake()
    assert img is not None and d.device_id and d.secret
    # registerDevice() discards the screen response, so setup() sleeps its initial 60 s
    assert sleep_s == 60
    assert registered_device_count(live_server) == 1


def test_410_makes_the_device_reregister(live_server):
    d = FakeDevice(live_server)
    d.register()
    old_id = d.device_id
    live_server.store.forget(old_id)
    img, sleep_s = d.wake()
    assert img is not None
    assert sleep_s == 60  # the screen was fetched inside registerDevice(), so the schedule is dropped
    assert d.device_id and d.device_id != old_id
    assert live_server.store.authenticate(d.device_id, d.secret)


def test_an_approved_recipe_reaches_the_device(live_server):
    live_server.store.approve(RECIPE)
    d = FakeDevice(live_server)
    d.register()
    shown, expected = d.wake()[0], render(RECIPE, READINGS, FIXED_NOW)
    assert list(shown.get_flattened_data()) == list(expected.get_flattened_data())


def test_battery_telemetry_arrives_at_the_server(live_server):
    d = FakeDevice(live_server)
    d.register()
    d.battery = 812
    d.wake()
    assert live_server.store.last_telemetry(d.device_id)["battery"] == 812


def test_every_screen_request_carries_the_firmwares_header_set(live_server):
    d = FakeDevice(live_server)
    d.register()
    d.wake()
    seen = live_server.store.last_telemetry(d.device_id)
    firmware_sends = {
        "battery", "client_version", "free_heap", "millis",
        "spiffs_free", "spiffs_total", "wifi_rssi",
        # buildOptionalHeaderFields(), appended to every screen request
        "total_device_starts", "successful_device_starts", "last_ntp_sync_time",
        "starts_without_ntp_sync", "last_cycle_duration",
    }  # the secret is sent too, but the server never logs it
    assert firmware_sends <= seen.keys()
    assert "secret" not in seen
