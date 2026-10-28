from dataclasses import replace
from datetime import datetime, timezone

import pytest
from PIL import Image, ImageDraw

from espaper_server.packer import PAYLOAD_SIZE, SCREEN_HEIGHT, SCREEN_WIDTH, pack_screen
from espaper_server.recipe import Recipe
from espaper_server.render import render, render_png
from espaper_server.sources import Reading

from tests.recipes import FIXED_NOW, READINGS, RECIPE


@pytest.fixture
def drawn(monkeypatch):
    """Render and return the text that landed legibly on the panel.

    Wraps ImageDraw.text to record each string, but only if it fits inside the canvas it is
    drawn on: a line that overruns is clipped on the panel, so it must not count as shown."""
    seen: list[str] = []
    original = ImageDraw.ImageDraw.text

    def recording(self, xy, text, *args, font=None, **kwargs):
        if xy[0] + self.textlength(text, font=font) <= self.im.size[0]:
            seen.append(text)
        return original(self, xy, text, *args, font=font, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording)

    def render_and_read(*args, **kwargs) -> str:
        seen.clear()
        render(*args, **kwargs)
        return "\n".join(seen)

    return render_and_read


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


def test_time_is_rendered_in_the_recipe_timezone_with_the_zone_shown(drawn):
    assert "CET" in drawn(RECIPE, READINGS, FIXED_NOW)
    assert "19:02 CET" in drawn(RECIPE, READINGS, FIXED_NOW)


def test_a_different_recipe_timezone_changes_the_rendered_time(drawn):
    tokyo = replace(RECIPE, timezone="Asia/Tokyo")
    assert "03:02 JST" in drawn(tokyo, READINGS, FIXED_NOW)


def test_attribution_is_present_when_a_weather_source_is_used(drawn):
    assert "Open-Meteo" in drawn(RECIPE, READINGS, FIXED_NOW)


def test_every_figure_carries_its_unit_or_currency(drawn):
    drawn = drawn(RECIPE, READINGS, FIXED_NOW)
    for figure in ("9.7 °C", "$215.85", "-$0.76", "11.2 °C"):
        assert figure in drawn


def test_translate_table_turns_raw_codes_into_words(drawn):
    assert "Overcast" in drawn(RECIPE, READINGS, FIXED_NOW)


def test_change_is_shown_in_dollars_and_percent(drawn):
    # -0.76 / 216.61 = -0.35 %
    assert "-$0.76 (-0.35 %)" in drawn(RECIPE, READINGS, FIXED_NOW)


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


def test_no_data_placeholder_renders_without_an_age(drawn):
    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
    nothing = Reading(value="—", observed_at=epoch, label="")
    text = drawn(RECIPE, [nothing, READINGS[1]], FIXED_NOW, stale=[True, False])
    assert "—" in text
    assert "ago" not in text and "1970" not in text and "56" not in text


def test_stale_reading_shows_its_age_from_the_providers_timestamp(drawn):
    assert "19:02 CET · 3m ago" in drawn(RECIPE, READINGS, FIXED_NOW, stale=[False, True])


def test_fresh_reading_shows_no_age(drawn):
    assert "ago" not in drawn(RECIPE, READINGS, FIXED_NOW)


def test_missing_extra_key_drops_the_line_instead_of_printing_blanks(drawn):
    bare = replace(READINGS[0], extra={})
    drawn = drawn(RECIPE, [bare, READINGS[1]], FIXED_NOW)
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


def test_a_line_wider_than_its_panel_is_not_counted_as_shown(drawn):
    long = replace(READINGS[1], extra={**READINGS[1].extra, "exchange": "Q" * 200})
    text = drawn(RECIPE, [READINGS[0], long], FIXED_NOW)
    assert "Q" * 200 not in text and "NVDA · " + "Q" * 200 not in text
    assert "$215.85" in text  # the neighbouring, legible lines still count


def test_overlong_primary_value_is_not_counted_as_shown(drawn):
    readings = [replace(READINGS[0], value="9.7 °C " + "x" * 400), READINGS[1]]
    assert "x" * 400 not in drawn(RECIPE, readings, FIXED_NOW)


def test_derive_percent_works_on_arbitrary_key_names(drawn):
    panel = replace(
        RECIPE.panels[1],
        lines=["{extra[delta]} ({pct})"],
        derive={"pct": {"percent_of": ["delta", "base"]}},
    )
    recipe = replace(RECIPE, panels=[RECIPE.panels[0], panel])
    reading = replace(READINGS[1], extra={"delta": "+5 pts", "base": "50 pts"})
    assert "+5 pts (+10.00 %)" in drawn(recipe, [READINGS[0], reading], FIXED_NOW)


def test_without_derive_there_is_no_derived_field(drawn):
    panel = replace(RECIPE.panels[1], derive={})  # lines still ask for {change_pct}
    recipe = replace(RECIPE, panels=[RECIPE.panels[0], panel])
    text = drawn(recipe, READINGS, FIXED_NOW)
    assert "%" not in text and "-$0.76" not in text  # the whole line is dropped


def test_panel_boxes_split_the_width_by_weight_with_one_pixel_rules():
    from espaper_server.render import _panel_boxes

    boxes = _panel_boxes(RECIPE)
    assert boxes[0][0] == 0 and boxes[-1][1] == SCREEN_WIDTH
    assert boxes[1][0] == boxes[0][1] + 1
    assert boxes[0][1] == round((SCREEN_WIDTH - 1) * 0.63)


def test_ascii_of_an_all_white_screen_is_blank_not_solid():
    from espaper_server.render import render_ascii

    art = render_ascii(Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 1))
    assert art.strip() == ""


def test_ascii_of_an_all_black_screen_is_solid():
    from espaper_server.render import render_ascii

    art = render_ascii(Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 0))
    assert set(art.replace("\n", "")) == {"@"}


def test_ascii_has_exact_width_and_sixteen_rows():
    from espaper_server.render import render_ascii

    lines = render_ascii(render(RECIPE, READINGS, FIXED_NOW)).split("\n")
    assert len(lines) == 16
    assert {len(line) for line in lines} == {74}


def test_ascii_width_follows_cols():
    from espaper_server.render import render_ascii

    lines = render_ascii(render(RECIPE, READINGS, FIXED_NOW), cols=37).split("\n")
    assert {len(line) for line in lines} == {37}


def test_ascii_puts_ink_where_the_ink_is():
    from espaper_server.render import render_ascii

    image = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 1)
    ImageDraw.Draw(image).rectangle([0, 0, 3, 7], fill=0)  # exactly the top-left character cell
    lines = render_ascii(image).split("\n")
    assert lines[0][0] == "@"
    assert lines[0][1:].strip() == "" and all(not line.strip() for line in lines[1:])
