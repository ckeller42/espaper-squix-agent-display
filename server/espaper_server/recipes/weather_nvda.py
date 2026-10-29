"""The shipped screen: Stuttgart weather on the left, the NVDA quote on the right.

Both panels are deliberately built the same way -- equal width, the same largest type size, a
title, a figure, three small lines and a credit -- so the two halves read as one screen rather
than a big panel beside a small one. Every string a person reads is German.
"""

from espaper_server.recipe import Panel, Recipe

# WMO weather interpretation codes, as Open-Meteo reports them. Kept short: these are drawn on
# a panel about 140 pixels wide, and the renderer shrinks a long line rather than wrapping it.
WMO_CODES = {
    "0": "Klarer Himmel", "1": "Überwiegend klar", "2": "Teils wolkig", "3": "Bedeckt",
    "45": "Nebel", "48": "Reifnebel",
    "51": "Leichter Niesel", "53": "Nieselregen", "55": "Starker Niesel",
    "56": "Gefrierender Niesel", "57": "Starker gefr. Niesel",
    "61": "Leichter Regen", "63": "Regen", "65": "Starker Regen",
    "66": "Gefrierender Regen", "67": "Starker gefr. Regen",
    "71": "Leichter Schnee", "73": "Schneefall", "75": "Starker Schnee", "77": "Schneegriesel",
    "85": "Schneeschauer", "86": "Starke Schneeschauer",
    "80": "Leichte Schauer", "81": "Schauer", "82": "Starke Schauer",
    "95": "Gewitter", "96": "Gewitter mit Hagel", "99": "Schweres Gewitter m. Hagel",
}  # fmt: skip

# "Stand" is the reading's own timestamp from the provider, not the time we drew the screen, so
# a stale panel says when its data was measured instead of implying it is current.
AS_OF = "Stand {time}"

RECIPE = Recipe(
    timezone="Europe/Berlin",
    panels=[
        Panel(
            source={"type": "weather", "latitude": 48.77, "longitude": 9.18},
            weight=0.5,
            # Three small lines is all a panel holds once it carries a title, a figure and a
            # credit -- a fourth is silently dropped, which is how the update time went missing
            # in the first place. The rain chance rides on the title instead, which also gives
            # both panels the same "A - B" heading shape.
            title="Stuttgart · Regen {extra[precipitation]}",
            primary="{value}",
            lines=["{extra[weather_code]}", "Max {extra[high]}  Min {extra[low]}", AS_OF],
            translate={"weather_code": WMO_CODES},
            attribution="Wetterdaten von Open-Meteo.com",
            max_primary=30,
        ),
        Panel(
            source={"type": "quote", "symbol": "NVDA"},
            weight=0.5,
            title="{label} · {extra[exchange]}",
            primary="{value}",
            lines=["{extra[change]} ({change_pct})", "Vortag {extra[previous_close]}", AS_OF],
            derive={"change_pct": {"percent_of": ["change", "previous_close"]}},
            attribution="Kurse von Yahoo Finance",
            max_primary=30,
        ),
    ],
)
