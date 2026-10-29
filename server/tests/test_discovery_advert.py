"""The server advertises _espaper._tcp so the firmware's discovery finds it.

Nothing here touches the network: zeroconf is replaced by a fake that records what it was asked
to register. These tests prove WHAT would be advertised, not that a real mDNS stack carries it.
"""

import sys

from fastapi.testclient import TestClient

from espaper_server.advertise import SERVICE_TYPE, Advertiser, advertiser_from_env
from espaper_server.app import create_app
from espaper_server.store import Store
from tests.recipes import FIXED_NOW


class FakeZeroconf:
    def __init__(self):
        self.registered = []
        self.unregistered = []
        self.closed = False

    def register_service(self, info):
        self.registered.append(info)

    def unregister_service(self, info):
        self.unregistered.append(info)

    def close(self):
        self.closed = True


def test_the_service_is_advertised_with_the_expected_name_and_port():
    fake = FakeZeroconf()
    adv = Advertiser(port=8411, address="192.168.178.43", zeroconf_factory=lambda: fake)

    assert adv.start() is True

    (info,) = fake.registered
    # EspaperClient/discovery.cpp: MDNS.queryService("espaper", "tcp") -> _espaper._tcp.local.
    assert SERVICE_TYPE == "_espaper._tcp.local."
    assert info.type == "_espaper._tcp.local."
    assert info.name == "ESPaper display server._espaper._tcp.local."
    # discovery.cpp reads MDNS.IP(i) and MDNS.port(i): an IPv4 address and the SRV port.
    assert info.port == 8411
    assert info.parsed_addresses() == ["192.168.178.43"]

    adv.stop()
    assert fake.unregistered == [info] and fake.closed


def test_the_server_starts_when_zeroconf_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("ESPAPER_ADVERTISE_PORT", "8411")
    monkeypatch.setenv("ESPAPER_ADVERTISE_ADDRESS", "192.168.178.43")
    monkeypatch.setitem(sys.modules, "zeroconf", None)  # `import zeroconf` raises ImportError
    app = create_app(Store(tmp_path, clock=lambda: FIXED_NOW))

    with TestClient(app) as client:  # runs startup and shutdown
        assert client.get("/preview.png").status_code == 200


def test_the_server_starts_when_registering_fails(tmp_path):
    def broken():
        raise OSError("no multicast interface")

    adv = Advertiser(port=8411, address="192.168.178.43", zeroconf_factory=broken)
    app = create_app(Store(tmp_path, clock=lambda: FIXED_NOW), advertiser=adv)

    with TestClient(app) as client:
        assert client.get("/preview.png").status_code == 200
    assert adv.start() is False


def test_nothing_is_advertised_unless_enabled(monkeypatch):
    monkeypatch.delenv("ESPAPER_ADVERTISE_PORT", raising=False)
    assert advertiser_from_env() is None


def test_a_bad_port_setting_disables_advertising_instead_of_raising(monkeypatch):
    monkeypatch.setenv("ESPAPER_ADVERTISE_PORT", "not-a-port")
    assert advertiser_from_env() is None
