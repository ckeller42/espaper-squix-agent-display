import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from espaper_server.sources import QuoteSource, Reading, WeatherSource

FIXTURES = Path(__file__).parent / "fixtures"
# Weather: real Open-Meteo capture. Quote: hand-written from the verified
# field list (Yahoo rate-limited the capture attempt); same shape as the API.
WEATHER_FIXTURE = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
QUOTE_FIXTURE = json.loads((FIXTURES / "yahoo_chart_nvda.json").read_text())


def weather() -> WeatherSource:
    return WeatherSource(48.77, 9.18, "Europe/Berlin")


def test_weather_formats_value_with_unit():
    assert weather()._parse(WEATHER_FIXTURE).value == "9.2 °C"


def test_quote_formats_value_with_currency_symbol():
    assert QuoteSource("NVDA")._parse(QUOTE_FIXTURE).value == "$216.61"


def test_observed_at_comes_from_the_provider_not_now():
    r = QuoteSource("NVDA")._parse(QUOTE_FIXTURE)
    assert r.observed_at == datetime.fromtimestamp(1793211545, tz=timezone.utc)


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
    assert r.extra["change"] == "-$1.33"
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
