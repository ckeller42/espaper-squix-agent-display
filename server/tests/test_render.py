from dataclasses import replace
from datetime import datetime, timezone

from PIL import Image

from espaper_server.packer import PAYLOAD_SIZE, SCREEN_HEIGHT, SCREEN_WIDTH, pack_screen
from espaper_server.recipe import Recipe
from espaper_server.render import render, render_png
from espaper_server.sources import Reading

from tests.recipes import FIXED_NOW, READINGS, RECIPE


def text_drawn(image: Image.Image) -> str:
    """Every string the renderer drew, joined; render records them in image.info["text"]."""
    return "\n".join(image.info["text"])


def test_render_is_the_right_mode_and_size():
    img = render(RECIPE, READINGS, FIXED_NOW)
    assert img.mode == "1" and img.size == (296, 128)


def test_render_is_deterministic():
    assert pack_screen(render(RECIPE, READINGS, FIXED_NOW)) == pack_screen(
        render(RECIPE, READINGS, FIXED_NOW)
    )


def test_overlong_text_still_packs_to_the_exact_payload_size():
    readings = [replace(READINGS[0], value="9.7 °C " + "x" * 400), READINGS[1]]
    assert len(pack_screen(render(RECIPE, readings, FIXED_NOW))) == PAYLOAD_SIZE


def test_overlong_text_in_every_field_stays_inside_its_panel():
    long = "W" * 400
    readings = [
        replace(READINGS[0], value=long, extra={k: long for k in READINGS[0].extra}),
        replace(READINGS[1], value=long, label=long, extra={k: long for k in READINGS[1].extra}),
    ]
    img = render(RECIPE, readings, FIXED_NOW)
    assert len(pack_screen(img)) == PAYLOAD_SIZE
    # the gutters beside the rule hold no ink, so neither panel's text spilled across it
    rule_x = round((SCREEN_WIDTH - 1) * 0.63)
    for x in (rule_x - 2, rule_x - 1, rule_x + 1, rule_x + 2):
        assert [img.getpixel((x, y)) for y in range(SCREEN_HEIGHT)].count(0) == 0


def test_time_is_rendered_in_the_recipe_timezone_with_the_zone_shown():
    assert "CET" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))
    assert "19:02 CET" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))


def test_a_different_recipe_timezone_changes_the_rendered_time():
    tokyo = replace(RECIPE, timezone="Asia/Tokyo")
    assert "03:02 JST" in text_drawn(render(tokyo, READINGS, FIXED_NOW))


def test_attribution_is_present_when_a_weather_source_is_used():
    assert "Open-Meteo" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))


def test_every_figure_carries_its_unit_or_currency():
    drawn = text_drawn(render(RECIPE, READINGS, FIXED_NOW))
    for figure in ("9.7 °C", "$215.85", "-$0.76", "11.2 °C"):
        assert figure in drawn


def test_translate_table_turns_raw_codes_into_words():
    assert "Overcast" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))


def test_change_is_shown_in_dollars_and_percent():
    # -0.76 / 216.61 = -0.35 %
    assert "-$0.76 (-0.35 %)" in text_drawn(render(RECIPE, READINGS, FIXED_NOW))


def test_panel_widths_follow_the_weights_and_a_one_pixel_rule_separates_them():
    img = render(RECIPE, READINGS, FIXED_NOW)
    rule_x = round((SCREEN_WIDTH - 1) * 0.63)
    column = [img.getpixel((rule_x, y)) for y in range(SCREEN_HEIGHT)]
    assert column.count(0) == SCREEN_HEIGHT - 2 * 4  # inset from top and bottom
    assert column[4] == 0 and column[SCREEN_HEIGHT - 5] == 0


def test_background_is_white_and_ink_is_black():
    img = render(RECIPE, READINGS, FIXED_NOW)
    assert img.getpixel((0, 0)) == 1
    assert img.histogram()[0] > 0


def test_no_data_placeholder_renders_without_an_age():
    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
    nothing = Reading(value="—", observed_at=epoch, label="")
    img = render(RECIPE, [nothing, READINGS[1]], FIXED_NOW, stale=[True, False])
    drawn = text_drawn(img)
    assert "—" in drawn
    assert "ago" not in drawn and "1970" not in drawn and "56" not in drawn


def test_stale_reading_shows_its_age_from_the_providers_timestamp():
    img = render(RECIPE, READINGS, FIXED_NOW, stale=[False, True])
    assert "19:02 CET · 3m ago" in text_drawn(img)


def test_fresh_reading_shows_no_age():
    assert "ago" not in text_drawn(render(RECIPE, READINGS, FIXED_NOW))


def test_missing_extra_key_drops_the_line_instead_of_printing_blanks():
    bare = replace(READINGS[0], extra={})
    drawn = text_drawn(render(RECIPE, [bare, READINGS[1]], FIXED_NOW))
    assert "H  L" not in drawn


def test_readings_are_not_mutated():
    before = [(r.value, dict(r.extra)) for r in READINGS]
    render(RECIPE, READINGS, FIXED_NOW, stale=[True, True])
    assert [(r.value, dict(r.extra)) for r in READINGS] == before


def test_reading_count_must_match_panel_count():
    import pytest

    with pytest.raises(ValueError, match="readings"):
        render(RECIPE, READINGS[:1], FIXED_NOW)


def test_a_recipe_with_one_panel_fills_the_width():
    single = Recipe(panels=[RECIPE.panels[0]], timezone="UTC")
    img = render(single, READINGS[:1], FIXED_NOW)
    assert img.size == (296, 128)


def test_render_png_is_a_decodable_png_of_the_same_screen():
    import io

    png = render_png(RECIPE, READINGS, FIXED_NOW)
    assert png.startswith(b"\x89PNG")
    decoded = Image.open(io.BytesIO(png)).convert("1")
    assert pack_screen(decoded) == pack_screen(render(RECIPE, READINGS, FIXED_NOW))
