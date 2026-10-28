"""A stand-in for the ESPaper, following the sequence in EspaperClient.ino and EspaperParser.cpp.

One call to wake() is one boot-to-sleep cycle of the real device:

  * identity (id and secret) lives in `device_id` / `secret`, standing in for the flash settings;
  * with no stored id AND secret it registers, then asks for its screen (registerDevice());
  * with both stored it goes straight to GET .../screen (isDeviceRegistered());
  * 410 is the one status that clears the stored identity and restarts; the next boot has no
    identity, so it registers and fetches. Every other failure sleeps 60 s and keeps its identity;
  * the screen is decoded by the firmware's own algorithm, not by the server's unpacker.
"""

import time

import httpx2
from PIL import Image

from tests.firmware_decode import decode_payload

CLIENT_VERSION = "fake-1"
DEVICE_TYPE = "Espaper29Bw"
TIMEZONE = "Europe/Berlin"
RETRY_SECONDS = 60  # EspaperClient.ino: the sleep after any failure
DEFAULT_SLEEP_SECONDS = 20 * 60  # UPDATE_INTERVAL_MINS stand-in, used when the server gives no deadline
MAX_SLEEP_DISAGREEMENT = 600  # startDeviceSleep(): beyond this the clock is distrusted


class RegistrationFailed(Exception):
    pass


class FakeDevice:
    def __init__(self, base_url: str, mac: str = "AA:BB:CC:DD:EE:FF", battery: int = 700):
        self.base_url = str(base_url)
        self.mac = mac
        self.battery = battery
        self.device_id = ""
        self.secret = ""
        self.last_status = 0
        self._started = time.monotonic()

    @property
    def is_registered(self) -> bool:
        return bool(self.device_id) and bool(self.secret)

    def register(self) -> None:
        """POST /public/devices. The identity comes back in response headers, not the body."""
        response = httpx2.post(
            f"{self.base_url}/public/devices",
            json={"macAddress": self.mac, "deviceType": DEVICE_TYPE, "timeZone": TIMEZONE},
            headers={
                "X-ESPAPER-CLIENT-VERSION": CLIENT_VERSION,
                "X-ESPAPER-BATTERY": str(self.battery),
                "X-ESPAPER-WIFI-RSSI": "-60",
            },
        )
        device_id = response.headers.get("X-ESPAPER-DEVICE-ID")
        secret = response.headers.get("X-ESPAPER-SECRET")
        if not device_id or not secret:
            raise RegistrationFailed(f"HTTP {response.status_code} without an identity: {response.text}")
        self.device_id, self.secret = device_id, secret

    def _fetch_screen(self) -> httpx2.Response:
        # The header set of getAndDrawScreen(), in the firmware's alphabetical order.
        headers = {
            "X-ESPAPER-BATTERY": str(self.battery),
            "X-ESPAPER-CLIENT-VERSION": CLIENT_VERSION,
            "X-ESPAPER-FREE-HEAP": "30000",
            "X-ESPAPER-MILLIS": str(int((time.monotonic() - self._started) * 1000)),
            "X-ESPAPER-SECRET": self.secret,
            "X-ESPAPER-SPIFFS-FREE": "1000000",
            "X-ESPAPER-SPIFFS-TOTAL": "1500000",
            "X-ESPAPER-WIFI-RSSI": "-60",
        }
        response = httpx2.get(f"{self.base_url}/public/devices/{self.device_id}/screen", headers=headers)
        self.last_status = response.status_code
        return response

    def _boot(self) -> tuple[Image.Image | None, int, bool]:
        """One boot. Returns (image, sleep seconds, restarted)."""
        if not self.is_registered:
            try:
                self.register()
            except (RegistrationFailed, httpx2.TransportError):
                return None, RETRY_SECONDS, False
        try:
            response = self._fetch_screen()
        except httpx2.TransportError:
            return None, RETRY_SECONDS, False
        if response.status_code == 410:
            self.device_id = self.secret = ""  # saveDeviceRegistration("", ""); ESP.restart()
            return None, RETRY_SECONDS, True
        if response.status_code != 200:
            return None, RETRY_SECONDS, False
        return decode_payload(response.content), self._sleep_seconds(response.headers), False

    @staticmethod
    def _sleep_seconds(headers) -> int:
        """startDeviceSleep(): sleep until the server's deadline, unless that disagrees with the
        server's own duration by more than 10 minutes (the device clock is then not trusted)."""
        seconds = int(headers.get("X-ESPAPER-SLEEP-SECONDS", 0))
        until = int(headers.get("X-ESPAPER-SLEEP-UNTIL", 0))
        if until == 0:
            return DEFAULT_SLEEP_SECONDS
        effective = until - int(time.time())
        return seconds if abs(seconds - effective) > MAX_SLEEP_DISAGREEMENT else effective

    def wake(self) -> tuple[Image.Image | None, int]:
        """Boot, fetch the screen, and report (image, seconds to sleep). A restart caused by 410
        is a second boot within the same call; a second 410 in a row is left to the next wake."""
        image, sleep_s, restarted = self._boot()
        if restarted:
            image, sleep_s, _ = self._boot()
        return image, sleep_s
