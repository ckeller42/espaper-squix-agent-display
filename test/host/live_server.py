"""Boots the real FastAPI server on an ephemeral loopback port for the native firmware tests.

Prints one line, "<port> <sleep_seconds> <sleep_until>", once it is serving, then runs until
stdin reaches EOF (the C++ harness exiting, however it exits, ends the server). Sources are
stubbed exactly as in server/tests/conftest.py, so nothing reaches an external network.
"""

import json
import socket
import sys
import tempfile
import threading
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "server"
sys.path.insert(0, str(SERVER))

import uvicorn  # noqa: E402

from espaper_server.app import create_app  # noqa: E402
from espaper_server.store import Store  # noqa: E402
from tests.recipes import FIXED_NOW, READINGS  # noqa: E402

SLEEP_SECONDS = 1234  # distinctive, so the test cannot pass on a default


class _Readings:
    def __init__(self, reading):
        self._reading = reading

    def fetch(self):
        return self._reading


with tempfile.TemporaryDirectory() as root:
    (Path(root) / "config.json").write_text(json.dumps({"sleep_seconds": SLEEP_SECONDS}))
    store = Store(
        Path(root),
        source_factory=lambda panel, tz: _Readings(READINGS[0 if panel.source["type"] == "weather" else 1]),
        clock=lambda: FIXED_NOW,
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(store), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    while not server.started:
        if not thread.is_alive():
            sys.exit("test server did not start")
        thread.join(0.01)
    print(sock.getsockname()[1], SLEEP_SECONDS, int(FIXED_NOW.timestamp()) + SLEEP_SECONDS, flush=True)
    sys.stdin.read()  # blocks until the harness closes its end
    server.should_exit = True
    thread.join(timeout=10)
