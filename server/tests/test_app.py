import pytest
from fastapi.testclient import TestClient

import espaper_server.app as app_module
from espaper_server.app import create_app
from espaper_server.packer import PAYLOAD_SIZE
from espaper_server.store import Store
from tests.recipes import FIXED_NOW

REGISTER = {"macAddress": "AA:BB", "deviceType": "Espaper29Bw", "timeZone": "Europe/Berlin"}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path, clock=lambda: FIXED_NOW)


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


@pytest.fixture
def device(client):
    r = client.post("/public/devices", json=REGISTER)
    return r.headers["X-ESPAPER-DEVICE-ID"], {"X-ESPAPER-SECRET": r.headers["X-ESPAPER-SECRET"]}


def test_registration_returns_identity_in_headers_not_the_body(client):
    r = client.post("/public/devices", json=REGISTER)
    assert r.status_code == 200
    assert r.headers["X-ESPAPER-DEVICE-ID"] and r.headers["X-ESPAPER-SECRET"]
    assert r.headers["X-ESPAPER-DEVICE-ID"] not in r.text
    assert r.headers["X-ESPAPER-SECRET"] not in r.text


def test_registration_rejects_a_malformed_body(client):
    assert client.post("/public/devices", json={"macAddress": "AA"}).status_code == 422


def test_screen_returns_the_exact_payload_and_sleep_headers(client, store, device):
    dev, auth = device
    store.put_payload(b"\x07" * PAYLOAD_SIZE)
    r = client.get(f"/public/devices/{dev}/screen", headers=auth)
    assert r.status_code == 200 and r.content == b"\x07" * PAYLOAD_SIZE
    assert r.headers["Content-Type"] == "application/octet-stream"
    seconds = int(r.headers["X-ESPAPER-SLEEP-SECONDS"])
    assert seconds == store.sleep_seconds() > 0
    assert int(r.headers["X-ESPAPER-SLEEP-UNTIL"]) == int(FIXED_NOW.timestamp()) + seconds


def test_sleep_cadence_comes_from_config(client, store, device, tmp_path):
    dev, auth = device
    (tmp_path / "config.json").write_text('{"sleep_seconds": 77}')
    r = client.get(f"/public/devices/{dev}/screen", headers=auth)
    assert r.headers["X-ESPAPER-SLEEP-SECONDS"] == "77"


def test_unknown_device_returns_410_so_the_firmware_reregisters(client):
    assert client.get("/public/devices/nope/screen", headers={"X-ESPAPER-SECRET": "x"}).status_code == 410


def test_wrong_secret_returns_410(client, device):
    dev, _ = device
    r = client.get(f"/public/devices/{dev}/screen", headers={"X-ESPAPER-SECRET": "wrong"})  # pragma: allowlist secret
    assert r.status_code == 410


def test_missing_secret_returns_410(client, device):
    dev, _ = device
    assert client.get(f"/public/devices/{dev}/screen").status_code == 410


def test_a_forgotten_device_gets_410(client, store, device):
    dev, auth = device
    store.forget(dev)
    assert client.get(f"/public/devices/{dev}/screen", headers=auth).status_code == 410


def test_screen_before_any_recipe_serves_the_fallback_not_404(client, device):
    dev, auth = device
    r = client.get(f"/public/devices/{dev}/screen", headers=auth)
    assert r.status_code == 200 and len(r.content) == PAYLOAD_SIZE
    assert r.content[1] == 1  # bitsPerPixel: the firmware refuses anything else
    assert len(set(r.content[6:])) > 1  # something is drawn, not a blank page


def test_fallback_is_made_at_startup_and_identical_on_every_request(store, monkeypatch):
    client = TestClient(create_app(store))
    r = client.post("/public/devices", json=REGISTER)
    dev, auth = r.headers["X-ESPAPER-DEVICE-ID"], {"X-ESPAPER-SECRET": r.headers["X-ESPAPER-SECRET"]}
    first = client.get(f"/public/devices/{dev}/screen", headers=auth).content

    def no_drawing_at_request_time(*args, **kwargs):
        raise AssertionError("rendered while serving a request")

    monkeypatch.setattr(app_module, "render", no_drawing_at_request_time)
    assert client.get(f"/public/devices/{dev}/screen", headers=auth).content == first


def test_an_approved_payload_replaces_the_fallback(client, store, device):
    dev, auth = device
    store.put_payload(b"\x09" * PAYLOAD_SIZE)
    assert client.get(f"/public/devices/{dev}/screen", headers=auth).content == b"\x09" * PAYLOAD_SIZE


def test_update_command_header_is_never_sent(client, store, device):
    dev, auth = device
    for payload in (None, b"\x00" * PAYLOAD_SIZE):
        if payload:
            store.put_payload(payload)
        r = client.get(f"/public/devices/{dev}/screen", headers={**auth, "X-ESPAPER-CLIENT-VERSION": "V001"})
        assert "X-ESPAPER-COMMAND" not in r.headers


def test_telemetry_headers_are_recorded(client, store, device):
    dev, auth = device
    client.get(f"/public/devices/{dev}/screen", headers={**auth, "X-ESPAPER-BATTERY": "812"})
    assert store.last_telemetry(dev)["battery"] == 812


def test_rejected_requests_record_no_telemetry(client, store, device):
    dev, _ = device
    client.get(f"/public/devices/{dev}/screen", headers={"X-ESPAPER-SECRET": "bad", "X-ESPAPER-BATTERY": "1"})  # pragma: allowlist secret
    assert store.last_telemetry(dev) == {}
