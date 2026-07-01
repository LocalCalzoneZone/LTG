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


def test_starting_mana_length_must_match_archetype():
    # Fighter starts with 2; a 1-colour starting mana is invalid.
    with pytest.raises(ValidationError):
        Loadout.model_validate(
            {
                "character": {
                    "name": "X", "archetype": "Fighter",
                    "colors": ["W"], "starting_mana": ["W"],
                },
                "cards": [],
            }
        )
    # Caster starts with 3; a 2-colour starting mana is invalid.
    with pytest.raises(ValidationError):
        Loadout.model_validate(
            {
                "character": {
                    "name": "X", "archetype": "Caster",
                    "colors": ["U", "B"], "starting_mana": ["U", "B"],
                },
                "cards": [],
            }
        )


def test_archetype_required_and_stats_derive():
    from ltg_core.schema import Character, archetype_stats
    with pytest.raises(ValidationError):
        Character.model_validate({"name": "X", "colors": ["U"], "starting_mana": ["U", "U"]})
    caster = Character.model_validate({
        "name": "Ys", "archetype": "Caster", "colors": ["U", "B"],
        "starting_mana": ["U", "U", "B"],
    })
    assert caster.level == 1
    # Stats now also carry the attack profile (R-3): a Caster defaults to ranged/2.
    assert caster.stats == {"starting_hp": 10, "starting_hand": 3, "starting_mana": 3,
                            "power": 2, "attack_mode": "ranged"}
    assert archetype_stats("Fighter") == {"starting_hp": 25, "starting_hand": 2, "starting_mana": 2}
