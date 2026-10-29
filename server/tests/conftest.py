"""A real server on a real socket, with the data sources stubbed to the recorded readings."""

import socket
import threading
import time

import pytest
import uvicorn

from espaper_server.app import create_app
from espaper_server.store import Store
from tests.recipes import FIXED_NOW, READINGS


class LiveServer(str):
    """The base URL, which also carries the Store the running app uses."""

    store: Store


class _Readings:
    def __init__(self, reading):
        self._reading = reading

    def fetch(self):
        return self._reading


@pytest.fixture
def live_server(tmp_path):
    # Sources are stubbed, so no test reaches an external API: panel i gets READINGS[i].
    store = Store(
        tmp_path,
        source_factory=lambda panel, tz: _Readings(READINGS[0 if panel.source["type"] == "weather" else 1]),
        clock=lambda: FIXED_NOW,
    )
    # Bind port 0 ourselves and hand the open socket to uvicorn, so the port is known
    # before the server starts and cannot be taken by someone else in between.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(store), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("test server did not start")
            time.sleep(0.01)
        url = LiveServer(f"http://127.0.0.1:{port}")
        url.store = store
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
