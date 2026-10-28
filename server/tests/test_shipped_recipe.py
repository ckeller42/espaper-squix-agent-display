from PIL import ImageDraw

from espaper_server.recipe import Recipe
from espaper_server.recipes.weather_nvda import RECIPE as SHIPPED
from espaper_server.render import render
from espaper_server.store import source_for
from tests.recipes import FIXED_NOW, READINGS


def test_shipped_recipe_is_weather_left_and_nvda_right_in_berlin():
    weather, quote = SHIPPED.panels
    assert SHIPPED.timezone == "Europe/Berlin"
    assert weather.source["type"] == "weather" and quote.source == {"type": "quote", "symbol": "NVDA"}
    assert 0.55 <= weather.weight / (weather.weight + quote.weight) <= 0.65
    assert weather.attribution == "Weather data by Open-Meteo.com"


def test_shipped_recipe_round_trips_and_builds_sources():
    assert Recipe.from_json(SHIPPED.to_json()) == SHIPPED
    for panel in SHIPPED.panels:
        source_for(panel, SHIPPED.timezone)


def test_shipped_recipe_translates_every_wmo_code_open_meteo_can_send():
    codes = SHIPPED.panels[0].translate["weather_code"]
    wmo = {0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
           80, 81, 82, 85, 86, 95, 96, 99}
    assert wmo <= {int(c) for c in codes}


def test_shipped_recipe_shows_units_currency_zone_and_credit(monkeypatch):
    drawn = []
    real = ImageDraw.ImageDraw.text
    monkeypatch.setattr(
        ImageDraw.ImageDraw, "text", lambda self, xy, text, *a, **k: (drawn.append(text), real(self, xy, text, *a, **k))[1]
    )
    render(SHIPPED, READINGS, FIXED_NOW)
    shown = " | ".join(drawn)
    for expected in ("9.7 °C", "H 11.2 °C", "Overcast", "19:02 CET", "$215.85", "-$0.76", "NVDA", "Weather data by Open-Meteo.com"):
        assert expected in shown
