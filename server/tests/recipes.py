"""Shared fixtures for the recipe and render tests."""

from datetime import datetime, timezone

from espaper_server.recipe import Panel, Recipe
from espaper_server.sources import Reading

WMO = {"3": "Overcast", "61": "Light rain"}

RECIPE = Recipe(
    timezone="Europe/Berlin",
    panels=[
        Panel(
            source={"type": "weather", "latitude": 52.52, "longitude": 13.41},
            weight=0.63,
            title="Berlin",
            primary="{value}",
            lines=["{extra[weather_code]}", "H {extra[high]}  L {extra[low]}", "{time}"],
            translate={"weather_code": WMO},
            attribution="Weather data by Open-Meteo.com",
            max_primary=34,
        ),
        Panel(
            source={"type": "quote", "symbol": "NVDA"},
            weight=0.37,
            title="{label} · {extra[exchange]}",
            primary="{value}",
            lines=["{extra[change]} ({change_pct})", "{time}"],
            derive={"change_pct": {"percent_of": ["change", "previous_close"]}},
            max_primary=28,
        ),
    ],
)

FIXED_NOW = datetime(2026, 10, 28, 18, 5, tzinfo=timezone.utc)

READINGS = [
    Reading(
        value="9.7 °C",
        observed_at=datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc),
        label="Weather",
        extra={"high": "11.2 °C", "low": "6.1 °C", "precipitation": "40 %", "weather_code": "3"},
    ),
    Reading(
        value="$215.85",
        observed_at=datetime(2026, 10, 28, 18, 2, tzinfo=timezone.utc),
        label="NVDA",
        extra={"previous_close": "$216.61", "change": "-$0.76", "exchange": "NasdaqGS"},
    ),
]
