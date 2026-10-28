from io import BytesIO

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

import espaper_server.app as app_module
from espaper_server.app import create_app
from espaper_server.packer import PAYLOAD_SIZE, pack_screen
from espaper_server.store import Store
from tests.recipes import FIXED_NOW, READINGS, RECIPE, filled_payload
from tests.test_store import factory_for

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
    store.put_payload(filled_payload(7))
    r = client.get(f"/public/devices/{dev}/screen", headers=auth)
    assert r.status_code == 200 and r.content == filled_payload(7)
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
    store.put_payload(filled_payload(9))
    assert client.get(f"/public/devices/{dev}/screen", headers=auth).content == filled_payload(9)


def test_update_command_header_is_never_sent(client, store, device):
    dev, auth = device
    for payload in (None, filled_payload(0)):
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


def test_a_corrupt_device_record_gets_410_so_the_device_reregisters(client, tmp_path, device):
    dev, auth = device
    (tmp_path / "devices" / f"{dev}.json").write_text("{truncated")
    assert client.get(f"/public/devices/{dev}/screen", headers=auth).status_code == 410


@pytest.fixture
def approved(tmp_path):
    store = Store(tmp_path, source_factory=factory_for(*READINGS), clock=lambda: FIXED_NOW)
    store.approve(RECIPE)
    return store


def test_preview_png_is_a_png_of_the_panel_size(client):
    r = client.get("/preview.png")
    assert r.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(r.content)).size == (296, 128)


def test_preview_page_shows_when_it_was_rendered_and_the_approval_state(approved):
    body = TestClient(create_app(approved)).get("/preview").text
    assert "18:05 UTC" not in body and "19:05 CET" in body
    assert "approved" in body and "awaiting approval" not in body


def test_preview_page_says_awaiting_approval_for_a_proposed_recipe(approved):
    approved.propose(RECIPE)
    body = TestClient(create_app(approved)).get("/preview").text
    assert "awaiting approval" in body


def test_preview_page_before_any_recipe_says_so(client):
    body = client.get("/preview").text
    assert "no recipe" in body.lower()
    assert client.get("/preview.png").status_code == 200


def test_preview_page_embeds_the_image_and_links_the_text_view(approved):
    body = TestClient(create_app(approved)).get("/preview").text
    assert 'src="/preview.png"' in body and "/preview.txt" in body


def _hand_drawn_screen() -> Image.Image:
    """An image no renderer would produce: a diagonal cross and a lone pixel. If /preview.png
    re-rendered anything instead of unpacking stored bytes, it could not come back as this."""
    image = Image.new("1", (296, 128), 1)
    draw = ImageDraw.Draw(image)
    draw.line([(0, 0), (295, 127)], fill=0, width=3)
    draw.line([(0, 127), (295, 0)], fill=0)
    draw.point((147, 5), fill=0)
    return image


def _assert_preview_is_the_stored_screen(client, dev, auth, drawn):
    payload = pack_screen(drawn)
    png = Image.open(BytesIO(client.get("/preview.png").content)).convert("1")
    assert png.tobytes() == drawn.tobytes()
    assert pack_screen(png) == payload == client.get(f"/public/devices/{dev}/screen", headers=auth).content


def test_preview_png_matches_the_payload_served_to_the_device(approved):
    client = TestClient(create_app(approved))
    r = client.post("/public/devices", json=REGISTER)
    dev, auth = r.headers["X-ESPAPER-DEVICE-ID"], {"X-ESPAPER-SECRET": r.headers["X-ESPAPER-SECRET"]}
    drawn = _hand_drawn_screen()
    approved.put_payload(pack_screen(drawn))  # replaces the approved render with bytes no renderer made
    _assert_preview_is_the_stored_screen(client, dev, auth, drawn)


def test_preview_before_approval_shows_what_the_device_would_get(client, store, device):
    dev, auth = device
    drawn = _hand_drawn_screen()
    store.put_payload(pack_screen(drawn))  # nothing approved: the shelf holds only these bytes
    assert not store.is_approved()
    _assert_preview_is_the_stored_screen(client, dev, auth, drawn)


def test_preview_with_nothing_stored_shows_the_waiting_screen_the_device_gets(client, device):
    dev, auth = device
    png = Image.open(BytesIO(client.get("/preview.png").content)).convert("1")
    assert pack_screen(png) == client.get(f"/public/devices/{dev}/screen", headers=auth).content


def test_preview_txt_is_plain_text_art_of_the_served_screen(approved):
    r = TestClient(create_app(approved)).get("/preview.txt")
    assert r.headers["content-type"].startswith("text/plain")
    lines = r.text.rstrip("\n").split("\n")
    assert len(lines) == 16 and {len(line) for line in lines} == {74}
    assert r.text.strip()  # the weather and quote panels leave ink


# A screen.bin that did not come through put_payload (an agent dropping a pre-rendered file on the
# shelf, a half-written copy) must never reach the device, which has no error channel.
def _corrupt_screen_bin(tmp_path, kind):
    good = filled_payload(5)
    (tmp_path / "screen.bin").write_bytes(
        {
            "truncated": good[:100],
            "empty": b"",
            "oversized": good + b"\x00",
            "bad-header": b"\x02" + good[1:],
        }[kind]
    )


CORRUPTIONS = ["truncated", "empty", "oversized", "bad-header"]


@pytest.mark.parametrize("kind", CORRUPTIONS)
def test_device_gets_the_waiting_screen_not_a_malformed_payload(client, device, tmp_path, caplog, kind):
    dev, auth = device
    waiting = client.get(f"/public/devices/{dev}/screen", headers=auth).content  # nothing stored yet
    _corrupt_screen_bin(tmp_path, kind)
    with caplog.at_level("ERROR"):
        r = client.get(f"/public/devices/{dev}/screen", headers=auth)
    assert r.status_code == 200 and r.content == waiting and len(r.content) == PAYLOAD_SIZE
    assert "not a valid screen payload" in caplog.text


@pytest.mark.parametrize("kind", CORRUPTIONS)
def test_preview_survives_a_malformed_stored_payload(client, tmp_path, kind):
    _corrupt_screen_bin(tmp_path, kind)
    assert client.get("/preview.png").status_code == 200
    assert client.get("/preview.txt").status_code == 200
