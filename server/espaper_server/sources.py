"""Data sources behind one interface. Each fetch returns a formatted Reading."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

TIMEOUT = httpx.Timeout(10.0)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


@dataclass(frozen=True)
class Reading:
    value: str  # already formatted, unit or currency included
    observed_at: datetime  # timezone-aware, the provider's own timestamp
    label: str
    extra: dict[str, str] = field(default_factory=dict)


class Source(Protocol):
    def fetch(self) -> Reading: ...


def _money(amount: float, currency: str) -> str:
    sign = "-" if amount < 0 else ""
    prefix = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    return f"{sign}{prefix}{abs(amount):.2f}"


class WeatherSource:
    URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, latitude: float, longitude: float, timezone: str):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone

    def fetch(self) -> Reading:
        response = httpx.get(
            self.URL,
            params={
                "latitude": self.latitude,
                "longitude": self.longitude,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": self.timezone,
                "forecast_days": 1,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return self._parse(response.json())

    def _parse(self, payload: dict[str, Any]) -> Reading:
        current = payload["current"]
        units = payload["current_units"]
        daily = payload["daily"]
        daily_units = payload["daily_units"]
        # current.time is local to the requested timezone with no offset suffix.
        offset = timezone(timedelta(seconds=payload["utc_offset_seconds"]))
        observed_at = datetime.fromisoformat(current["time"]).replace(tzinfo=offset)
        return Reading(
            value=f"{current['temperature_2m']} {units['temperature_2m']}",
            observed_at=observed_at,
            label="Weather",
            extra={
                "high": f"{daily['temperature_2m_max'][0]} {daily_units['temperature_2m_max']}",
                "low": f"{daily['temperature_2m_min'][0]} {daily_units['temperature_2m_min']}",
                "precipitation": f"{daily['precipitation_probability_max'][0]} "
                f"{daily_units['precipitation_probability_max']}",
                "weather_code": str(current["weather_code"]),
            },
        )


class QuoteSource:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def __init__(self, symbol: str):
        self.symbol = symbol

    def fetch(self) -> Reading:
        response = httpx.get(
            self.URL.format(symbol=self.symbol),
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": BROWSER_UA},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return self._parse(response.json())

    def _parse(self, payload: dict[str, Any]) -> Reading:
        meta = payload["chart"]["result"][0]["meta"]
        currency = meta["currency"]
        price = meta["regularMarketPrice"]
        extra: dict[str, str] = {}
        previous = meta.get("chartPreviousClose")
        if previous is not None:
            extra["previous_close"] = _money(previous, currency)
            extra["change"] = _money(round(price - previous, 2), currency)
        if meta.get("fullExchangeName"):
            extra["exchange"] = meta["fullExchangeName"]
        return Reading(
            value=_money(price, currency),
            observed_at=datetime.fromtimestamp(meta["regularMarketTime"], tz=timezone.utc),
            label=meta.get("symbol", self.symbol),
            extra=extra,
        )
