"""The shipped screen: Stuttgart weather on the left (about 60 %), the NVDA quote on the right."""

from espaper_server.recipe import Panel, Recipe

# WMO weather interpretation codes, as Open-Meteo reports them.
WMO_CODES = {
    "0": "Clear sky", "1": "Mainly clear", "2": "Partly cloudy", "3": "Overcast",
    "45": "Fog", "48": "Rime fog",
    "51": "Light drizzle", "53": "Drizzle", "55": "Heavy drizzle",
    "56": "Freezing drizzle", "57": "Heavy frz. drizzle",
    "61": "Light rain", "63": "Rain", "65": "Heavy rain",
    "66": "Freezing rain", "67": "Heavy frz. rain",
    "71": "Light snow", "73": "Snow", "75": "Heavy snow", "77": "Snow grains",
    "80": "Light showers", "81": "Showers", "82": "Heavy showers",
    "85": "Snow showers", "86": "Heavy snow showers",
    "95": "Thunderstorm", "96": "Thunderstorm, hail", "99": "Heavy thunderstorm, hail",
}  # fmt: skip

RECIPE = Recipe(
    timezone="Europe/Berlin",
    panels=[
        Panel(
            source={"type": "weather", "latitude": 48.77, "longitude": 9.18},
            weight=0.6,
            title="Stuttgart",
            primary="{value}",
            lines=["{extra[weather_code]}", "H {extra[high]}  L {extra[low]}", "Rain {extra[precipitation]}", "{time}"],
            translate={"weather_code": WMO_CODES},
            attribution="Weather data by Open-Meteo.com",
            max_primary=34,
        ),
        Panel(
            source={"type": "quote", "symbol": "NVDA"},
            weight=0.4,
            title="{label} · {extra[exchange]}",
            primary="{value}",
            lines=["{extra[change]} ({change_pct})", "{time}"],
            derive={"change_pct": {"percent_of": ["change", "previous_close"]}},
            max_primary=28,
        ),
    ],
)
