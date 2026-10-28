"""The device protocol. The server serves bytes; it never draws while a device waits."""

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from espaper_server.packer import pack_screen
from espaper_server.recipe import Panel, Recipe
from espaper_server.render import render
from espaper_server.sources import Reading
from espaper_server.store import Store

_WAITING_RECIPE = Recipe(
    timezone="UTC",
    panels=[Panel(source={}, weight=1.0, title="{label}", primary="{value}", lines=["{extra[hint]}"], max_primary=28)],
)


def build_waiting_payload(now) -> bytes:
    """Rendered once at startup, before any request. Devices register and ask for a screen
    before any recipe exists; this is what they get until one is approved."""
    reading = Reading(
        value="Waiting for a screen",
        observed_at=now,
        label="ESPaper",
        extra={"hint": "approve a recipe to begin"},
    )
    return pack_screen(render(_WAITING_RECIPE, [reading], now))


class Registration(BaseModel):
    macAddress: str
    deviceType: str
    timeZone: str = Field(min_length=1)


def create_app(store: Store) -> FastAPI:
    app = FastAPI()
    app.state.store = store
    waiting = build_waiting_payload(store._clock())

    @app.post("/public/devices")
    def register(body: Registration) -> Response:
        device_id, secret = store.register_device(body.macAddress, body.deviceType, body.timeZone)
        # The firmware reads identity from these headers; a JSON body would not be parsed.
        return Response(headers={"X-ESPAPER-DEVICE-ID": device_id, "X-ESPAPER-SECRET": secret})

    @app.get("/public/devices/{device_id}/screen")
    def screen(
        device_id: str, request: Request, x_espaper_secret: str = Header(default="")
    ) -> Response:
        if not store.authenticate(device_id, x_espaper_secret):
            # 410 is the one status that makes the firmware drop its identity and re-register.
            raise HTTPException(status_code=410, detail="unknown device")
        store.record_telemetry(device_id, request.headers)
        seconds = store.sleep_seconds()
        return Response(
            content=store.current_payload() or waiting,
            media_type="application/octet-stream",
            headers={
                "X-ESPAPER-SLEEP-SECONDS": str(seconds),
                "X-ESPAPER-SLEEP-UNTIL": str(int(store._clock().timestamp()) + seconds),
            },
        )

    return app


app = create_app(Store(Path(os.environ.get("ESPAPER_DATA_DIR", "data"))))
