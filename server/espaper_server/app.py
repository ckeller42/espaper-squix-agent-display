"""The device protocol. The server serves bytes; it never draws while a device waits."""

import asyncio
import contextlib
import html
import io
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from espaper_server.advertise import Advertiser, advertiser_from_env
from espaper_server.packer import pack_screen, unpack_screen
from espaper_server.recipe import Panel, Recipe
from espaper_server.render import render, render_ascii
from espaper_server.sources import Reading
from espaper_server.store import Store

log = logging.getLogger(__name__)

DEFAULT_REFRESH_SECONDS = 300.0


def refresh_seconds_from_env() -> float | None:
    """How often to replay the approved recipe. ESPAPER_REFRESH_SECONDS=0 turns the timer off;
    an unreadable value falls back to the default rather than stopping the server from booting,
    because a stale screen is a far smaller failure than no server."""
    raw = os.environ.get("ESPAPER_REFRESH_SECONDS")
    if raw is None:
        return DEFAULT_REFRESH_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        log.error("ESPAPER_REFRESH_SECONDS=%r is not a number; using %s", raw, DEFAULT_REFRESH_SECONDS)
        return DEFAULT_REFRESH_SECONDS
    if seconds <= 0:
        return None
    return seconds


async def refresh_loop(store, seconds: float) -> None:
    """Redraw the approved screen every `seconds`, forever.

    It sleeps first: approve() has just drawn, so there is nothing to redo at startup. Each
    redraw runs in a thread because fetching sources and rendering are blocking work, and the
    server must stay able to answer a device mid-draw. One failed cycle is logged and skipped --
    a source being down must not end every later refresh.
    """
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(store.refresh)
        except Exception:  # noqa: BLE001 -- a refresh may fail any way a network can
            log.exception("refresh failed; the panel keeps the screen it has")


_WAITING_RECIPE = Recipe(
    timezone="UTC",
    panels=[Panel(source={}, weight=1.0, title="{label}", primary="{value}", lines=["{extra[hint]}"], max_primary=28)],
)


def build_waiting_payload(now) -> bytes:
    """Rendered once at startup, before any request. Devices register and ask for a screen
    before any recipe exists; this is what they get until one is approved."""
    reading = Reading(
        value="Warte auf Inhalt",
        observed_at=now,
        label="ESPaper",
        extra={"hint": "Rezept freigeben, dann geht es los"},
    )
    return pack_screen(render(_WAITING_RECIPE, [reading], now))


class Registration(BaseModel):
    macAddress: str
    deviceType: str
    timeZone: str = Field(min_length=1)


def create_app(
    store: Store, advertiser: Advertiser | None = None, refresh_seconds: float | None = -1.0
) -> FastAPI:
    """refresh_seconds defaults to the sentinel -1, meaning "ask the environment"; pass None to
    run without the timer (the tests do) or a number to pin it."""

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # Advertising is optional and never fatal: Advertiser logs its own failures. It runs in a
        # thread because registering probes the network for a second or more.
        adv = advertiser or advertiser_from_env()
        if adv is not None:
            await asyncio.to_thread(adv.start)
        every = refresh_seconds_from_env() if refresh_seconds == -1.0 else refresh_seconds
        refresher = asyncio.create_task(refresh_loop(store, every)) if every else None
        try:
            yield
        finally:
            if refresher is not None:
                refresher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresher
            if adv is not None:
                await asyncio.to_thread(adv.stop)

    app = FastAPI(lifespan=lifespan)
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

    def served_screen():
        """The image the panel would show, unpacked from the very bytes devices are sent."""
        return unpack_screen(store.current_payload() or waiting)

    @app.get("/preview.png")
    def preview_png() -> Response:
        buffer = io.BytesIO()
        served_screen().save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png")

    @app.get("/preview.txt")
    def preview_txt() -> PlainTextResponse:
        return PlainTextResponse(render_ascii(served_screen()) + "\n")

    @app.get("/preview")
    def preview() -> HTMLResponse:
        recipe, rendered_at = store.pending_recipe(), store.rendered_at()
        if recipe is None:
            state = "No recipe proposed yet. Devices are shown the waiting screen."
        elif store.is_approved():
            state = "Recipe approved: devices show this screen."
        else:
            state = "Recipe awaiting approval: devices still show the screen below, not the proposal."
        if rendered_at is None:
            when = "Nothing rendered yet."
        else:
            local = rendered_at.astimezone(ZoneInfo(recipe.timezone if recipe else "UTC"))
            when = f"Rendered {local:%Y-%m-%d %H:%M %Z}."
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><title>ESPaper preview</title>"
            "<style>img{image-rendering:pixelated;display:block;margin:.5em 0;border:1px solid #888}</style>"
            f"<h1>ESPaper preview</h1><p>{html.escape(state)} {html.escape(when)}</p>"
            '<img src="/preview.png" width=296 height=128 alt="screen at panel size">'
            '<img src="/preview.png" width=888 height=384 alt="screen enlarged">'
            '<p><a href="/preview.txt">Text version</a></p>'
        )

    return app


app = create_app(Store(Path(os.environ.get("ESPAPER_DATA_DIR", "data"))))
