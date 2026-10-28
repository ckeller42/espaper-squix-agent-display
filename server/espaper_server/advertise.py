"""Optional mDNS advertisement of the display server as _espaper._tcp.

The firmware's discovery (EspaperClient/discovery.cpp) calls MDNS.queryService("espaper", "tcp") and
reads, per answer, MDNS.IP(i) and MDNS.port(i): the SRV port and an IPv4 address. It reads no TXT
record, so none is published.

Everything here is best effort. A missing zeroconf, no multicast interface, a name clash: each is
logged and start() returns False. The display never depends on this module.
"""

import logging
import os
import socket

log = logging.getLogger(__name__)

SERVICE_TYPE = "_espaper._tcp.local."
INSTANCE_NAME = f"ESPaper display server.{SERVICE_TYPE}"
HOST_NAME = "espaper-server.local."


def _lan_address() -> str:
    # Connecting a UDP socket sends nothing; it only makes the OS pick the outgoing interface.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
        return s.getsockname()[0]


def _real_zeroconf():
    from zeroconf import Zeroconf  # imported late: a missing package must not break the server

    return Zeroconf()


class Advertiser:
    def __init__(self, port: int, address: str | None = None, zeroconf_factory=_real_zeroconf):
        self.port = port
        self.address = address
        self._factory = zeroconf_factory
        self._zc = None
        self._info = None

    def start(self) -> bool:
        try:
            from zeroconf import ServiceInfo

            address = self.address or _lan_address()
            info = ServiceInfo(
                SERVICE_TYPE,
                INSTANCE_NAME,
                port=self.port,
                server=HOST_NAME,
                parsed_addresses=[address],
            )
            zc = self._factory()
            try:
                zc.register_service(info)
            except BaseException:
                zc.close()
                raise
        except Exception:
            log.exception("mDNS advertisement not started; the display is unaffected")
            return False
        self._zc, self._info = zc, info
        log.info("advertising %s on %s:%d", SERVICE_TYPE, address, self.port)
        return True

    def stop(self) -> None:
        zc, info, self._zc, self._info = self._zc, self._info, None, None
        if zc is None:
            return
        try:
            zc.unregister_service(info)
            zc.close()
        except Exception:
            log.exception("mDNS advertisement did not stop cleanly")


def advertiser_from_env() -> Advertiser | None:
    """ESPAPER_ADVERTISE_PORT turns advertising on (it must be the port uvicorn listens on);
    ESPAPER_ADVERTISE_ADDRESS optionally pins the IPv4 address instead of auto-detecting it."""
    raw = os.environ.get("ESPAPER_ADVERTISE_PORT")
    if not raw:
        return None
    try:
        port = int(raw)
        if not 0 < port < 65536:
            raise ValueError(raw)
    except ValueError:
        log.error("ESPAPER_ADVERTISE_PORT=%r is not a port; not advertising", raw)
        return None
    return Advertiser(port, os.environ.get("ESPAPER_ADVERTISE_ADDRESS") or None)
