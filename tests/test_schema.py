"""Schema validates the fixtures, round-trips losslessly, and rejects junk."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ltg_core.schema import Card, Loadout

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
FIXTURES = ["giant_growth", "counterspell", "feed_the_swarm", "trample_anthem", "anthem"]


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_validates(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    card = Card.model_validate(data)
    assert card.source_name


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_round_trips_losslessly(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    card = Card.model_validate(data)
    again = Card.model_validate(card.model_dump())
    assert again == card
    # And dumping is stable: dump -> load -> dump is a fixed point.
    assert again.model_dump() == card.model_dump()


def test_corrected_shared_target_fixture_round_trips():
    data = json.loads((EXAMPLES / "sign_in_blood_corrected.json").read_text())
    card = Card.model_validate(data)
    assert card.targets["T1"].mode.value == "chosen"
    assert card.targets["T1"].side.value == "ally"
    assert all(e.target == "$T1" for e in card.effects)
    assert Card.model_validate(card.model_dump()) == card


def test_sample_loadout_validates_and_round_trips():
    data = json.loads((EXAMPLES / "sample_loadout.json").read_text())
    loadout = Loadout.model_validate(data)
    assert Loadout.model_validate(loadout.model_dump()) == loadout


def test_malformed_card_rejected_unknown_effect_kind():
    data = json.loads((EXAMPLES / "giant_growth.json").read_text())
    data["effects"] = [{"kind": "frobnicate", "target": "an_enemy"}]
    with pytest.raises(ValidationError):
        Card.model_validate(data)


def test_malformed_card_rejected_bad_target():
    data = json.loads((EXAMPLES / "giant_growth.json").read_text())
    data["effects"][0]["target"] = "the_moon"
    with pytest.raises(ValidationError):
        Card.model_validate(data)


def test_malformed_card_rejected_missing_required_field():
    data = json.loads((EXAMPLES / "giant_growth.json").read_text())
    del data["rarity"]
    with pytest.raises(ValidationError):
        Card.model_validate(data)


def test_character_colors_count_enforced():
    with pytest.raises(ValidationError):
        Loadout.model_validate(
            {
                "character": {
                    "name": "X",
                    "archetype": "Fighter",
                    "colors": ["W", "U", "B", "R"],  # 4 > 3
                    "starting_mana": ["W", "U"],
                },
                "cards": [],
            }
        )


def test_character_portrait_round_trips():
    data = {
        "character": {
            "name": "Ys",
            "portrait": "data:image/png;base64,AAAA",
            "archetype": "Fighter",
            "colors": ["U"],
            "starting_mana": ["U", "U"],
        },
        "cards": [],
    }
    loadout = Loadout.model_validate(data)
    assert loadout.character.portrait == "data:image/png;base64,AAAA"
    assert Loadout.model_validate(loadout.model_dump()) == loadout


def test_starting_mana_allows_two_of_same_colour():
    loadout = Loadout.model_validate(
        {
            "character": {
                "name": "Mono",
                "archetype": "Fighter",
                "colors": ["U"],
                "starting_mana": ["U", "U"],
            },
            "cards": [],
        }
    )
    assert loadout.character.starting_mana == ["U", "U"]


def test_over_budget_build_is_advisory():
    """Update 17 §D17-2.2: over-spending is flagged, never rejected — a loadout
    saved under the old flat table must still load, and its overage shows in
    the picker like deck status."""
    from ltg_core.schema import Character
    # 8 mana slots = +7 capacity = 15+15+20+25+30+35+40 = 180 points on the
    # T-79 curve, far over the 70 budget.
    c = Character.model_validate({
        "name": "X", "colors": ["U"], "starting_mana": ["U"] * 8,
    })
    assert c.points_spent == 180 and c.points_over == 110
    assert c.points_remaining == -110


def test_price_curve_and_level_thresholds():
    """T-79 escalating prices and T-78 derived levels."""
    from ltg_core.schema import (stat_price, stat_cost, price_list, creation_points,
                                 level_for_points, points_to_next_level, LEVEL_THRESHOLDS)
    assert price_list("mana", 7) == [15, 15, 20, 25, 30, 35, 40]
    assert price_list("card", 6) == [15, 15, 20, 25, 30, 35]
    assert price_list("power", 6) == [10, 10, 15, 20, 25, 30]
    assert price_list("hp_step", 10) == [5, 5, 5, 5, 6, 6, 7, 7, 8, 8]
    assert stat_price("hp_step", 11) == 9
    assert stat_cost("hp_step", 6) == 32
    # Creation is the first steps of the same curve: 12 HP / 2 mana / 2 cards / +1 Power
    assert creation_points(12, 2, 2, 1, None) == 10 + 15 + 15 + 10
    # Level derives from cumulative earned points.
    assert level_for_points(0) == 1
    assert level_for_points(29) == 1
    assert level_for_points(30) == 2
    assert level_for_points(60) == 3
    assert level_for_points(120) == 4   # T-78 table: L5 needs 150 (the doc prose says 120 — the register wins)
    assert level_for_points(150) == 5
    assert level_for_points(180) == 5
    assert level_for_points(210) == 6
    assert level_for_points(300) == 7
    assert level_for_points(2010) == 20
    assert level_for_points(99999) == 20
    assert points_to_next_level(0) == 30
    assert points_to_next_level(180) == 30
    assert points_to_next_level(2010) is None
    assert LEVEL_THRESHOLDS[10] == 570


def test_legacy_archetype_loads_and_stats_derive():
    from ltg_core.schema import Character, Archetype
    # A bare build defaults to the free baseline (8 HP / 1 mana / 1 card / melee 2).
    base = Character.model_validate({"name": "X", "colors": ["U"], "starting_mana": ["U"]})
    assert base.stat_block == {
        "hp": 8, "mana_capacity": 1, "starting_cards": 1,
        "attack_profile": {"mode": "melee", "power": 2}, "keywords": [],
    }
    assert base.points_spent == 0
    # A pre-Update-05 archetype character still loads (migration): legacy HP (10 for
    # Caster), preset hand/mana/Power, flagged legacy and exempt from the guardrails.
    caster = Character.model_validate({
        "name": "Ys", "archetype": "Caster", "colors": ["U", "B"],
        "starting_mana": ["U", "U", "B"],
    })
    assert caster.level == 1 and caster.preset == "Caster" and caster.legacy
    assert caster.stats == {"starting_hp": 10, "starting_hand": 3, "starting_mana": 3,
                            "power": 2, "attack_mode": "ranged", "keywords": []}
    assert caster.points_over == 0  # legacy builds are never counted over
    # The presets themselves are gone (Update 17 §D17-2.2): nothing in the
    # schema materialises one — only the retired names survive for migration.
    import ltg_core.schema as schema
    assert not hasattr(schema, "PRESETS") and not hasattr(schema, "preset_character")
    assert Archetype.Caster.value == "Caster"
