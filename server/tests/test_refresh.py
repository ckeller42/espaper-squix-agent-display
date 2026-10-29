"""The approved recipe is replayed on a timer, so the numbers on the panel stay current.

Without this the server renders once, at approval, and every later device fetch receives the
same bytes forever -- the panel showed a 50-minute-old temperature while dutifully waking
every 12 minutes.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from espaper_server.app import refresh_loop, refresh_seconds_from_env
from espaper_server.store import Store
from tests.recipes import RECIPE


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, minutes):
        self.now += timedelta(minutes=minutes)


def _store(tmp_path, clock, readings):
    store = Store(tmp_path, clock=clock)
    store._source_factory = lambda panel, tz: _Source(readings, panel, clock)
    return store


class _Source:
    """Returns a reading stamped with whatever the clock says at fetch time."""

    def __init__(self, readings, panel, clock):
        self.reading, self.clock = readings[panel.source["type"]], clock

    def fetch(self):
        from dataclasses import replace

        return replace(self.reading, observed_at=self.clock())


@pytest.fixture
def readings():
    from tests.recipes import READINGS

    return {"weather": READINGS[0], "quote": READINGS[1]}


def test_refresh_redraws_an_approved_recipe_with_new_readings(tmp_path, readings):
    clock = _Clock()
    store = _store(tmp_path, clock, readings)
    store.approve(RECIPE)
    first, first_at = store.current_payload(), store.rendered_at()

    clock.advance(30)
    assert store.refresh() is True
    assert store.rendered_at() > first_at
    assert store.current_payload() != first, "a 30-minute-older timestamp must change the pixels"


def test_refresh_does_nothing_when_no_recipe_is_approved(tmp_path, readings):
    clock = _Clock()
    store = _store(tmp_path, clock, readings)
    store.propose(RECIPE)  # proposed, deliberately not approved
    assert store.refresh() is False
    assert store.current_payload() is None
    assert store.rendered_at() is None


def test_refresh_keeps_the_recipe_approved(tmp_path, readings):
    clock = _Clock()
    store = _store(tmp_path, clock, readings)
    store.approve(RECIPE)
    store.refresh()
    assert store.is_approved(), "a refresh replaces numbers; it must not require re-approval"
    assert store.pending_recipe() == RECIPE


def _run_loop_briefly(store, seconds=0.01, for_seconds=0.08) -> None:
    """Run refresh_loop as a task, then cancel it. Written with asyncio.run rather than
    pytest-asyncio so the suite keeps its single test dependency."""

    async def drive():
        task = asyncio.create_task(refresh_loop(store, seconds))
        await asyncio.sleep(for_seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(drive())


def test_the_loop_refreshes_repeatedly_until_cancelled():
    calls = []

    class FakeStore:
        def refresh(self):
            calls.append(1)
            return True

    _run_loop_briefly(FakeStore())
    assert len(calls) >= 2, f"expected repeated refreshes, got {len(calls)}"


def test_a_failing_refresh_does_not_kill_the_loop():
    calls = []

    class BrokenStore:
        def refresh(self):
            calls.append(1)
            raise RuntimeError("source is down")

    _run_loop_briefly(BrokenStore())
    assert len(calls) >= 2, "one failed fetch must not stop every later refresh"


def test_refresh_interval_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("ESPAPER_REFRESH_SECONDS", raising=False)
    assert refresh_seconds_from_env() == 300
    monkeypatch.setenv("ESPAPER_REFRESH_SECONDS", "60")
    assert refresh_seconds_from_env() == 60
    monkeypatch.setenv("ESPAPER_REFRESH_SECONDS", "0")
    assert refresh_seconds_from_env() is None, "0 turns the timer off"
    monkeypatch.setenv("ESPAPER_REFRESH_SECONDS", "nonsense")
    assert refresh_seconds_from_env() == 300, "a bad value falls back, it does not crash boot"
