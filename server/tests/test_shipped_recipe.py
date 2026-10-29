from PIL import ImageDraw

from espaper_server.recipe import Recipe
from espaper_server.recipes.weather_nvda import RECIPE as SHIPPED
from espaper_server.render import render
from espaper_server.store import source_for
from tests.recipes import FIXED_NOW, READINGS


def test_shipped_recipe_is_weather_left_and_nvda_right_in_stuttgart():
    weather, quote = SHIPPED.panels
    assert SHIPPED.timezone == "Europe/Berlin"  # Stuttgart's timezone
    assert weather.title.startswith("Stuttgart")
    assert (weather.source["latitude"], weather.source["longitude"]) == (48.77, 9.18)
    assert weather.source["type"] == "weather" and quote.source == {"type": "quote", "symbol": "NVDA"}
    assert weather.attribution == "Wetterdaten von Open-Meteo.com"


def test_both_panels_are_built_alike_so_the_halves_look_like_one_screen():
    weather, quote = SHIPPED.panels
    assert weather.weight == quote.weight
    assert weather.max_primary == quote.max_primary
    assert len(weather.lines) == len(quote.lines)
    assert weather.attribution and quote.attribution


def test_every_panel_says_when_its_reading_was_taken():
    # A panel may carry only three small lines; a fourth is dropped without a word, which is
    # exactly how the weather panel lost its timestamp. Assert the text is actually DRAWN.
    assert all("{time}" in " ".join(panel.lines) for panel in SHIPPED.panels)


def test_the_update_time_survives_the_layout_on_every_panel(monkeypatch):
    drawn = []
    real = ImageDraw.ImageDraw.text
    monkeypatch.setattr(
        ImageDraw.ImageDraw, "text",
        lambda self, xy, text, *a, **k: (drawn.append(text), real(self, xy, text, *a, **k))[1],
    )
    render(SHIPPED, READINGS, FIXED_NOW)
    stands = [text for text in drawn if text.startswith("Stand ")]
    assert len(stands) == len(SHIPPED.panels), f"a panel dropped its timestamp: {drawn}"


def test_shipped_recipe_round_trips_and_builds_sources():
    assert Recipe.from_json(SHIPPED.to_json()) == SHIPPED
    for panel in SHIPPED.panels:
        source_for(panel, SHIPPED.timezone)


def test_shipped_recipe_translates_every_wmo_code_open_meteo_can_send():
    codes = SHIPPED.panels[0].translate["weather_code"]
    wmo = {0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
           80, 81, 82, 85, 86, 95, 96, 99}
    assert wmo <= {int(c) for c in codes}


def test_shipped_recipe_shows_german_copy_units_currency_zone_and_credit(monkeypatch):
    drawn = []
    real = ImageDraw.ImageDraw.text
    monkeypatch.setattr(
        ImageDraw.ImageDraw, "text", lambda self, xy, text, *a, **k: (drawn.append(text), real(self, xy, text, *a, **k))[1]
    )
    render(SHIPPED, READINGS, FIXED_NOW)
    shown = " | ".join(drawn)
    for expected in ("9.7 °C", "Max 11.2 °C", "Bedeckt", "Stand 19:00 CET", "Stand 19:02 CET",
                     "Regen 40 %", "$215.85", "-$0.76", "Vortag $216.61", "NVDA",
                     "Wetterdaten von Open-Meteo.com", "Kurse von Yahoo Finance"):
        assert expected in shown, f"missing {expected!r} in {shown}"
