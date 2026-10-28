"""A recipe says what to show; it carries no data and no drawing code.

A Panel describes one region of the screen as text templates over a Reading's fields, so the
renderer never needs to know whether a panel is weather, a stock quote or something new.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Panel:
    """One region. Templates use str.format fields: {label} {value} {time} {change_pct}
    and {extra[key]}. A line that references a field the reading lacks is dropped."""

    source: dict[str, Any]  # opaque to the renderer; the caller turns it into a Source
    weight: float  # share of the screen width, relative to the other panels
    title: str = ""  # small heading, a template
    primary: str = "{value}"  # the big figure, a template
    lines: tuple[str, ...] | list[str] = ()  # supporting lines, templates, top to bottom
    translate: dict[str, dict[str, str]] = field(default_factory=dict)  # extra key -> raw -> text
    attribution: str = ""  # small credit pinned to the panel's bottom edge
    max_primary: int = 40  # largest pixel size the primary figure may use

    def __post_init__(self):
        if self.weight <= 0:
            raise ValueError(f"panel weight must be positive, got {self.weight}")
        object.__setattr__(self, "lines", tuple(self.lines))


@dataclass(frozen=True)
class Recipe:
    panels: list[Panel]
    timezone: str  # IANA name; every time on the screen renders in it, zone abbreviation shown

    def __post_init__(self):
        if not self.panels:
            raise ValueError("a recipe needs at least one panel")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {self.timezone!r}") from exc

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Recipe":
        data = json.loads(text)
        return cls(panels=[Panel(**p) for p in data["panels"]], timezone=data["timezone"])
