"""Enchantments / channeled effects: while_channeled, upkeep trigger, rendering."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.mappings import build_card, render_effects
from backend.schema import Card

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def chan_card(effects, targets=None):
    return Card.model_validate({
        "id": "x", "name": "x", "source_name": "x", "rarity": "rare", "level": 2,
        "type": "Enchantment", "timing": "channeled",
        "targets": targets or {}, "effects": effects,
    })


def render(card):
    return render_effects(card.effects, card.targets, channeled=True)


# --- the four worked examples render exactly --------------------------------- #
def test_anthem_render():
    c = chan_card([{"kind": "pump", "power": 1, "toughness": 1,
                    "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"}])
    assert render(c) == "While channeled: all allies gain +1 attack and +1 temp HP."


def test_pacifism_render():
    c = chan_card(
        [{"kind": "disable", "intent_type": "attack", "target": "$T1", "duration": "while_channeled"}],
        {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}},
    )
    assert render(c) == "While channeled: the chosen enemy can't attack."


def test_bitterblossom_render():
    c = chan_card([
        {"kind": "create_token", "token_id": "faerie", "count": 1, "trigger": "upkeep"},
        {"kind": "lose_life", "amount": 1, "target": {"mode": "self"}, "trigger": "upkeep"},
    ])
    assert render(c) == ("At the start of each of your turns while channeled: "
                         "create a Faerie ally and lose 1 HP.")


def test_mixed_continuous_and_upkeep_render_and_lint():
    # Regression: targetless effects (create_token) must not crash lints/render.
    from backend.mappings import lint_card
    c = chan_card(
        [
            {"kind": "disable", "intent_type": "attack", "target": "$T1", "duration": "while_channeled"},
            {"kind": "create_token", "token_id": "faerie", "count": 1, "trigger": "upkeep"},
        ],
        {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}},
    )
    assert lint_card(c) == []
    text = render(c)
    assert "While channeled: the chosen enemy can't attack." in text
    assert "create a Faerie ally" in text


def test_enemy_debuff_render():
    c = chan_card([{"kind": "wound", "power": 1, "toughness": 1,
                    "target": {"mode": "all", "side": "enemy"}, "duration": "while_channeled"}])
    assert render(c) == "While channeled: all enemies have -1 attack and -1 HP."


# --- validation -------------------------------------------------------------- #
def test_while_channeled_rejected_on_non_channeled():
    with pytest.raises(ValidationError):
        Card.model_validate({
            "id": "x", "name": "x", "source_name": "x", "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant",
            "effects": [{"kind": "pump", "power": 1, "toughness": 1,
                         "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"}],
        })


def test_upkeep_rejected_on_non_channeled():
    with pytest.raises(ValidationError):
        Card.model_validate({
            "id": "x", "name": "x", "source_name": "x", "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery",
            "effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}, "trigger": "upkeep"}],
        })


def test_continuous_and_recurring_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        chan_card([{"kind": "pump", "power": 1, "toughness": 1,
                    "target": {"mode": "all", "side": "ally"},
                    "duration": "while_channeled", "trigger": "upkeep"}])


# --- type detection + auto-build -------------------------------------------- #
def test_enchantment_builds_as_channeled_continuous():
    card = build_card({
        "name": "Glorious Anthem", "cmc": 3.0, "type_line": "Enchantment", "rarity": "rare",
        "oracle_text": "Creatures you control get +1/+1.",
    })
    assert card.timing.value == "channeled"
    assert card.effects[0].duration.value == "while_channeled"
    assert card.translated_text.startswith("While channeled:")


# --- fixtures validate & round-trip ----------------------------------------- #
@pytest.mark.parametrize("name", ["anthem", "pacifism", "bitterblossom"])
def test_channeled_fixture_round_trips(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    card = Card.model_validate(data)
    assert card.timing.value == "channeled"
    assert Card.model_validate(card.model_dump()) == card
