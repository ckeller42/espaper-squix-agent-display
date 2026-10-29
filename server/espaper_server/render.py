"""Turn a Recipe plus fresh Readings into the 296x128 one-bit screen.

The renderer is a weighted layout engine: panels split the width by weight, a one-pixel rule
separates neighbours, and each panel's text comes from templates in the recipe. It knows
nothing about weather or stocks. Every panel is drawn on its own canvas and pasted in, so no
text can reach outside its panel box whatever the readings contain.
"""

import io
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from espaper_server.packer import SCREEN_HEIGHT, SCREEN_WIDTH
from espaper_server.recipe import Panel, Recipe
from espaper_server.sources import Reading, age_of

FONT_DIR = Path(__file__).parent / "fonts"
INK, PAPER = 0, 1
NO_DATA = "—"
PAD_X, PAD_TOP = 6, 4
GUTTER = 2  # paper kept free at a panel's right edge, so clipped text never touches the rule
RULE_INSET = 4  # the rule stops this far from the top and bottom edges
TITLE_SIZE, LINE_SIZE, ATTRIBUTION_SIZE = 12, 12, 9
PRIMARY_MIN, SMALL_MIN = 12, 8


@lru_cache(maxsize=None)
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSansCondensed.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


class _Fields(dict):
    """Template namespace that notes when a template asked for something it does not have."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.missing = False

    def __missing__(self, key):
        self.missing = True
        return ""


def _percent(change: str, base: str) -> str | None:
    """Signed percentage of two formatted figures, currency-agnostic ("-$0.76" over "$216.61")."""
    numbers = [re.search(r"\d+(?:\.\d+)?", s) for s in (change, base)]
    if not all(numbers) or float(numbers[1].group()) == 0:
        return None
    ratio = float(numbers[0].group()) / float(numbers[1].group()) * 100
    sign = "-" if "-" in change else "+"
    return f"{sign}{ratio:.2f} %"


def _age_text(age: timedelta) -> str:
    """German, like everything else the panel shows. Abbreviated because this sits beside a
    clock time on a 150-pixel-wide panel: "vor 3 Min." fits where "vor 3 Minuten" does not."""
    minutes = max(int(age.total_seconds() // 60), 0)
    if minutes < 60:
        return f"vor {minutes} Min."
    if minutes < 48 * 60:
        return f"vor {minutes // 60} Std."
    return f"vor {minutes // (24 * 60)} Tg."


def _fields(panel: Panel, reading: Reading, tz: ZoneInfo, now: datetime, stale: bool) -> _Fields:
    fields = _Fields(label=reading.label, value=reading.value)
    extra = _Fields(
        (k, panel.translate.get(k, {}).get(v, v)) for k, v in reading.extra.items()
    )
    fields["extra"] = extra
    if reading.value == NO_DATA:
        # The placeholder's observed_at is the epoch: no time and no age may be derived from it.
        return fields
    shown = f"{reading.observed_at.astimezone(tz):%H:%M %Z}"
    fields["time"] = f"{shown} · {_age_text(age_of(reading, now))}" if stale else shown
    for name, spec in panel.derive.items():
        top, bottom = spec["percent_of"]
        derived = _percent(reading.extra.get(top, ""), reading.extra.get(bottom, ""))
        if derived:
            fields[name] = derived
    return fields


def _expand(template: str, fields: _Fields) -> str | None:
    """The filled-in template, or None if it needed a field the reading lacks."""
    fields.missing = False
    fields["extra"].missing = False
    try:
        text = template.format_map(fields)
    except (ValueError, IndexError, AttributeError):
        return None
    if fields.missing or fields["extra"].missing:
        return None
    return text.strip() or None


def _fit_size(text: str, draw: ImageDraw.ImageDraw, width: int, bold: bool, largest: int, smallest: int) -> int:
    """Largest size that fits the width; if none does, the smallest (the panel canvas clips)."""
    for size in range(largest, smallest - 1, -1):
        if draw.textlength(text, font=_font(bold, size)) <= width:
            return size
    return smallest


def _draw_panel(
    panel: Panel, reading: Reading, width: int, tz: ZoneInfo, now: datetime, stale: bool
) -> Image.Image:
    canvas = Image.new("1", (width - GUTTER, SCREEN_HEIGHT), PAPER)  # drawing past its edge is a no-op
    draw = ImageDraw.Draw(canvas)
    draw.fontmode = "1"  # no anti-aliasing: pure ink or paper

    def put(y: int, text: str, bold: bool, size: int) -> int:
        draw.text((PAD_X, y), text, font=_font(bold, size), fill=INK)
        return y + _font(bold, size).getbbox("Hg")[3] + 2

    fields = _fields(panel, reading, tz, now, stale)
    inner = canvas.width - PAD_X
    y = PAD_TOP
    bottom = SCREEN_HEIGHT
    if panel.attribution:
        bottom -= _font(False, ATTRIBUTION_SIZE).getbbox("Hg")[3] + 4
        put(bottom, panel.attribution, False, ATTRIBUTION_SIZE)

    title = _expand(panel.title, fields) if panel.title else None
    if title:
        y = put(y, title, True, _fit_size(title, draw, inner, True, TITLE_SIZE, SMALL_MIN))
    primary = _expand(panel.primary, fields)
    if primary:
        y = put(y, primary, True, _fit_size(primary, draw, inner, True, panel.max_primary, PRIMARY_MIN))
    for template in panel.lines:
        line = _expand(template, fields)
        size = _fit_size(line or "", draw, inner, False, LINE_SIZE, SMALL_MIN)
        if line and y + _font(False, size).getbbox("Hg")[3] <= bottom:
            y = put(y, line, False, size)
    return canvas


def _panel_boxes(recipe: Recipe) -> list[tuple[int, int]]:
    """(start, end) columns of each panel, split by weight; a one-pixel rule sits at each
    interior end, and the next panel starts just after it. The last panel ends at the edge."""
    rules = len(recipe.panels) - 1
    total = sum(p.weight for p in recipe.panels)
    boxes, start, share = [], 0, 0.0
    for i, panel in enumerate(recipe.panels):
        share += panel.weight / total
        end = SCREEN_WIDTH if i == rules else round((SCREEN_WIDTH - rules) * share)
        boxes.append((start, end))
        start = end + 1
    return boxes


def render(
    recipe: Recipe,
    readings: Sequence[Reading],
    now: datetime,
    stale: Sequence[bool] = (),
) -> Image.Image:
    """Draw the screen. readings[i] feeds recipe.panels[i]; stale[i] (from fetch_with_fallback)
    says whether that reading is a fallback and so should show its age. Readings are read-only."""
    if len(readings) != len(recipe.panels):
        raise ValueError(f"{len(recipe.panels)} panels need as many readings, got {len(readings)}")
    stale_flags = list(stale) + [False] * (len(readings) - len(stale))
    tz = ZoneInfo(recipe.timezone)
    boxes = _panel_boxes(recipe)
    screen = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), PAPER)
    for i, (panel, reading, (x, edge)) in enumerate(zip(recipe.panels, readings, boxes)):
        screen.paste(_draw_panel(panel, reading, edge - x, tz, now, stale_flags[i]), (x, 0))
        if i < len(boxes) - 1:
            ImageDraw.Draw(screen).line(
                [(edge, RULE_INSET), (edge, SCREEN_HEIGHT - 1 - RULE_INSET)], fill=INK
            )
    return screen


def render_png(
    recipe: Recipe, readings: Sequence[Reading], now: datetime, stale: Sequence[bool] = ()
) -> bytes:
    buffer = io.BytesIO()
    render(recipe, readings, now, stale).save(buffer, format="PNG")
    return buffer.getvalue()


ASCII_RAMP = " .:-=+*#%@"  # blank paper to solid ink


def render_ascii(image: Image.Image, cols: int = 74) -> str:
    """The screen as text for a terminal. Each character covers a block of pixels (twice as tall as
    wide, as terminal cells are) and shows how much ink the block holds; paper is blank."""
    block_width = image.width / cols
    rows = round(image.height / (2 * block_width))
    # BOX averages each block; ink is bit 0, so ink share = 1 - brightness.
    brightness = image.convert("L").resize((cols, rows), Image.Resampling.BOX)
    top = len(ASCII_RAMP) - 1
    return "\n".join(
        "".join(ASCII_RAMP[round((255 - brightness.getpixel((x, y))) / 255 * top)] for x in range(cols))
        for y in range(rows)
    )
