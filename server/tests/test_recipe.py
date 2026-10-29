import json

import pytest

from espaper_server.recipe import Panel, Recipe

from tests.recipes import RECIPE


def test_recipe_round_trips_through_json():
    assert Recipe.from_json(RECIPE.to_json()) == RECIPE


def test_json_is_plain_data_an_agent_can_write():
    data = json.loads(RECIPE.to_json())
    assert data["timezone"] == "Europe/Berlin"
    assert [p["weight"] for p in data["panels"]] == [0.63, 0.37]


def test_optional_panel_fields_default_when_absent_from_json():
    minimal = '{"timezone": "UTC", "panels": [{"source": {"type": "x"}, "weight": 1}]}'
    panel = Recipe.from_json(minimal).panels[0]
    assert panel.primary == "{value}" and panel.lines == () and panel.attribution == ""


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        Recipe(panels=[Panel(source={}, weight=1)], timezone="Mars/Olympus")


def test_non_positive_weight_is_rejected():
    with pytest.raises(ValueError, match="weight"):
        Recipe(panels=[Panel(source={}, weight=0)], timezone="UTC")


def test_a_recipe_needs_at_least_one_panel():
    with pytest.raises(ValueError, match="panel"):
        Recipe(panels=[], timezone="UTC")
