import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
import pytest

from espaper_server.sources import (
    QuoteSource,
    Reading,
    WeatherSource,
    age_of,
    fetch_with_fallback,
)

FIXTURES = Path(__file__).parent / "fixtures"
# Both fixtures are real captured API responses (Open-Meteo and Yahoo chart, 2026-10-28);
# the minimal-meta quote test below is deliberately synthetic.
WEATHER_FIXTURE = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
QUOTE_FIXTURE = json.loads((FIXTURES / "yahoo_chart_nvda.json").read_text())


def weather() -> WeatherSource:
    return WeatherSource(48.77, 9.18, "Europe/Berlin")


def test_weather_formats_value_with_unit():
    assert weather()._parse(WEATHER_FIXTURE).value == "9.2 °C"


def test_quote_formats_value_with_currency_symbol():
    assert QuoteSource("NVDA")._parse(QUOTE_FIXTURE).value == "$215.85"


def test_observed_at_comes_from_the_provider_not_now():
    r = QuoteSource("NVDA")._parse(QUOTE_FIXTURE)
    assert r.observed_at == datetime.fromtimestamp(1793213773, tz=timezone.utc)


def test_observed_at_is_timezone_aware():
    assert weather()._parse(WEATHER_FIXTURE).observed_at.tzinfo is not None


def test_weather_observed_at_applies_provider_utc_offset():
    r = weather()._parse(WEATHER_FIXTURE)
    assert r.observed_at == datetime(2026, 10, 28, 18, 45, tzinfo=timezone.utc)
    assert r.observed_at.utcoffset() == timedelta(seconds=3600)


def test_weather_extra_carries_units():
    r = weather()._parse(WEATHER_FIXTURE)
    assert r.extra["high"] == "13.7 °C"
    assert r.extra["low"] == "8.5 °C"
    assert r.extra["precipitation"] == "65 %"
    assert r.extra["weather_code"] == "1"


def test_quote_extra_has_previous_close_and_change():
    r = QuoteSource("NVDA")._parse(QUOTE_FIXTURE)
    assert r.label == "NVDA"
    assert r.extra["previous_close"] == "$217.94"
    assert r.extra["change"] == "-$2.09"
    assert r.extra["exchange"] == "NasdaqGS"


def test_quote_tolerates_missing_optional_meta():
    payload = {"chart": {"result": [{"meta": {
        "regularMarketPrice": 10.0, "currency": "USD", "regularMarketTime": 1793211545}}]}}
    r = QuoteSource("X")._parse(payload)
    assert r.value == "$10.00"
    assert "previous_close" not in r.extra


def test_reading_is_frozen():
    r = QuoteSource("NVDA")._parse(QUOTE_FIXTURE)
    assert isinstance(r, Reading)
    try:
        r.value = "x"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Reading should be frozen")


FIXED_NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
OLD_READING = Reading(
    value="$215.85",
    observed_at=FIXED_NOW - timedelta(hours=15),
    label="NVDA",
    extra={"change": "$1.20"},
)


class FailingSource:
    def __init__(self, error: Exception):
        self.error = error

    def fetch(self) -> Reading:
        raise self.error


class WorkingSource:
    def fetch(self) -> Reading:
        return OLD_READING


TRANSPORT_AND_PARSE_ERRORS = [
    httpx2.ReadTimeout("timed out"),
    httpx2.ConnectError("unreachable"),
    KeyError("chart"),
]


# Deliberately synthetic: Yahoo's documented error shape, hand-written (not captured).
YAHOO_ERROR_FIXTURE = {
    "chart": {
        "result": None,
        "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"},
    }
}


def test_quote_parse_raises_value_error_on_yahoo_error_shape():
    with pytest.raises(ValueError, match="Not Found.*delisted"):
        QuoteSource("NVDA")._parse(YAHOO_ERROR_FIXTURE)


def test_quote_parse_raises_value_error_on_missing_or_empty_result():
    for chart in ({}, {"result": []}, {"result": None, "error": None}):
        with pytest.raises(ValueError):
            QuoteSource("NVDA")._parse({"chart": chart})


def test_yahoo_error_shape_falls_back_to_previous_reading():
    class ErrorShapeQuote(QuoteSource):
        def fetch(self) -> Reading:
            return self._parse(YAHOO_ERROR_FIXTURE)

    reading, is_stale = fetch_with_fallback(ErrorShapeQuote("NVDA"), previous=OLD_READING)
    assert reading == OLD_READING and is_stale is True


def test_placeholder_extra_cannot_be_corrupted_across_calls():
    first, _ = fetch_with_fallback(FailingSource(KeyError("x")), previous=None)
    first.extra["corrupted"] = "1"
    second, _ = fetch_with_fallback(FailingSource(KeyError("x")), previous=None)
    assert second.extra == {}


# Deliberately synthetic degenerate payloads (hand-written, not captured): each is a shape
# Yahoo could plausibly return that used to escape as AttributeError/TypeError/OverflowError.
def _quote_with_meta(**overrides):
    payload = json.loads(json.dumps(QUOTE_FIXTURE))
    payload["chart"]["result"][0]["meta"].update(overrides)
    return payload


def _quote_with_result(result):
    return {"chart": {"result": result, "error": None}}


@pytest.mark.parametrize(
    "payload",
    [
        _quote_with_result([None]),
        _quote_with_result(["not-a-dict"]),
        _quote_with_result([{"meta": None}]),
        _quote_with_result([{"meta": "not-a-dict"}]),
        _quote_with_meta(chartPreviousClose="n/a"),
        _quote_with_result(5),
        _quote_with_result(True),
    ],
    ids=[
        "result0-null",
        "result0-str",
        "meta-null",
        "meta-str",
        "previous-close-non-numeric",
        "result-numeric",
        "result-bool",
    ],
)
def test_quote_parse_raises_value_error_on_malformed_structure(payload):
    with pytest.raises(ValueError):
        QuoteSource("NVDA")._parse(payload)


def test_quote_parse_still_accepts_an_absent_or_null_previous_close():
    for value in (None, "absent"):
        payload = _quote_with_meta()
        meta = payload["chart"]["result"][0]["meta"]
        if value is None:
            meta["chartPreviousClose"] = None
        else:
            del meta["chartPreviousClose"]
        reading = QuoteSource("NVDA")._parse(payload)
        assert reading.value == "$215.85" and "change" not in reading.extra


@pytest.mark.parametrize(
    "payload",
    [
        {"chart": None},
        _quote_with_meta(regularMarketPrice=None),
        _quote_with_meta(regularMarketTime=None),
        _quote_with_meta(regularMarketTime=10**20),
        _quote_with_meta(currency=None),
    ],
    ids=["chart-null", "price-null", "time-null", "time-out-of-range", "currency-null"],
)
def test_quote_parse_raises_value_error_on_null_or_invalid_fields(payload):
    with pytest.raises(ValueError):
        QuoteSource("NVDA")._parse(payload)


def test_a_type_error_is_a_bug_and_is_not_swallowed():
    with pytest.raises(TypeError):
        fetch_with_fallback(FailingSource(TypeError("bug")), previous=OLD_READING)


def test_timeout_falls_back_to_previous_reading():
    reading, is_stale = fetch_with_fallback(
        FailingSource(httpx2.ReadTimeout("timed out")), previous=OLD_READING
    )
    assert reading == OLD_READING and is_stale is True


def test_timeout_without_a_previous_reading_does_not_raise():
    reading, is_stale = fetch_with_fallback(
        FailingSource(httpx2.ReadTimeout("timed out")), previous=None
    )
    assert is_stale is True and reading.value == "—"


def test_every_transport_and_parse_error_falls_back():
    for error in TRANSPORT_AND_PARSE_ERRORS:
        reading, is_stale = fetch_with_fallback(FailingSource(error), previous=OLD_READING)
        assert reading == OLD_READING and is_stale is True, error


def test_unrelated_errors_are_not_swallowed():
    for error in (KeyboardInterrupt(), RuntimeError("bug")):
        try:
            fetch_with_fallback(FailingSource(error), previous=OLD_READING)
        except type(error):
            continue
        raise AssertionError(f"{error!r} was swallowed")


def test_successful_fetch_is_returned_fresh():
    reading, is_stale = fetch_with_fallback(WorkingSource(), previous=None)
    assert reading == OLD_READING and is_stale is False


def test_placeholder_age_is_never_mistaken_for_fresh():
    reading, _ = fetch_with_fallback(FailingSource(KeyError("x")), previous=None)
    assert reading.observed_at.tzinfo is not None
    assert age_of(reading, now=FIXED_NOW) > timedelta(days=365)


def test_age_is_measured_from_the_providers_timestamp():
    assert age_of(OLD_READING, now=FIXED_NOW) == timedelta(hours=15)


def test_real_httpx2_failures_are_covered_by_fetch_errors():
    """Guards the tuple itself: a restructured exception hierarchy would stop matching silently."""
    import socket

    from espaper_server.sources import FETCH_ERRORS

    with socket.socket() as s:  # a local port nothing listens on: refused, no network involved
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(FETCH_ERRORS):
        httpx2.get(f"http://127.0.0.1:{port}/", timeout=2)
    response = httpx2.Response(503, request=httpx2.Request("GET", "http://example.invalid/"))
    with pytest.raises(FETCH_ERRORS):
        response.raise_for_status()
