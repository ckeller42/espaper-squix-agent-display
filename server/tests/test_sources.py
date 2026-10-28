import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
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
    httpx.ReadTimeout("timed out"),
    httpx.ConnectError("unreachable"),
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


def test_a_type_error_is_a_bug_and_is_not_swallowed():
    with pytest.raises(TypeError):
        fetch_with_fallback(FailingSource(TypeError("bug")), previous=OLD_READING)


def test_timeout_falls_back_to_previous_reading():
    reading, is_stale = fetch_with_fallback(
        FailingSource(httpx.ReadTimeout("timed out")), previous=OLD_READING
    )
    assert reading == OLD_READING and is_stale is True


def test_timeout_without_a_previous_reading_does_not_raise():
    reading, is_stale = fetch_with_fallback(
        FailingSource(httpx.ReadTimeout("timed out")), previous=None
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
