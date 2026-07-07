"""Enchantments / channeled effects: while_channeled, upkeep trigger, rendering."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ltg_core.translation import render_effects
from ltg_deckbuilder.ingest import build_card
from ltg_core.schema import Card

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
    # Pacifism keeps its target from attacking (`prevent attack`, R-11) — distinct
    # from a wound aura, which only shaves attack power.
    c = chan_card(
        [{"kind": "prevent", "parameter": "attack", "target": "$T1", "duration": "while_channeled"}],
        {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}},
    )
    assert render(c) == "While channeled: the chosen enemy can't attack."


def test_wound_aura_render():
    # A −2/−0 wound aura (e.g. Still the Blade) only blunts the enemy's attack power.
    c = chan_card(
        [{"kind": "wound", "power": 2, "toughness": 0, "target": "$T1", "duration": "while_channeled"}],
        {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}},
    )
    assert render(c) == "While channeled: the chosen enemy has -2 attack and -0 HP."


def test_bitterblossom_render():
    c = chan_card([
        {"kind": "create_token", "token_id": "faerie", "count": 1, "trigger": "upkeep"},
        {"kind": "lose_life", "amount": 1, "target": {"mode": "self"}, "trigger": "upkeep"},
    ])
    assert render(c) == ("At the start of every turn while channeled: "
                         "create a Faerie ally and lose 1 HP.")


def test_mixed_continuous_and_upkeep_render_and_lint():
    # Regression: targetless effects (create_token) must not crash lints/render.
    from ltg_core.lints import lint_card
    c = chan_card(
        [
            {"kind": "wound", "power": 2, "toughness": 0, "target": "$T1", "duration": "while_channeled"},
            {"kind": "create_token", "token_id": "faerie", "count": 1, "trigger": "upkeep"},
        ],
        {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}},
    )
    assert lint_card(c) == []
    text = render(c)
    assert "While channeled: the chosen enemy has -2 attack and -0 HP." in text
    assert "create a Faerie ally" in text


def test_enemy_debuff_render():
    c = chan_card([{"kind": "wound", "power": 1, "toughness": 1,
                    "target": {"mode": "all", "side": "enemy"}, "duration": "while_channeled"}])
    assert render(c) == "While channeled: all enemies have -1 attack and -1 HP."


# --- validation -------------------------------------------------------------- #
def test_channeled_exile_render():
    c = chan_card([{"kind": "exile", "target": "$T1", "duration": "while_channeled"}],
                  {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}})
    assert render(c) == "While channeled: exile the chosen enemy."


def test_exile_duration_must_be_while_channeled():
    # Exile is permanent (no duration) or reversible (while_channeled) — the
    # turn-scoped durations are meaningless and rejected.
    with pytest.raises(ValidationError):
        chan_card([{"kind": "exile", "target": "$T1", "duration": "this_turn"}],
                  {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}})


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
@pytest.mark.parametrize("name", ["anthem", "pacifism", "bitterblossom", "banishing_light"])
def test_channeled_fixture_round_trips(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    card = Card.model_validate(data)
    assert card.timing.value == "channeled"
    assert Card.model_validate(card.model_dump()) == card


# --- channel_break trigger (goes on the stack when the channel ends) --------- #
def test_channel_break_render():
    from ltg_core.translation import channel_break_clause
    c = chan_card([
        {"kind": "pump", "power": 1, "toughness": 1,
         "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"},
        {"kind": "deal_damage", "amount": 3,
         "target": {"mode": "all", "side": "enemy"}, "trigger": "channel_break"},
    ])
    text = render(c)
    assert "While channeled: all allies gain +1 attack and +1 temp HP." in text
    assert "When this channel ends (dropped or broken): deal 3 damage to all enemies." in text
    # The clause alone (no lead-in) — what the combat UI's channel note shows.
    assert channel_break_clause(c.effects, c.targets) == "deal 3 damage to all enemies"
    # A card without the trigger yields no note.
    plain = chan_card([{"kind": "pump", "power": 1, "toughness": 1,
                        "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"}])
    assert channel_break_clause(plain.effects, plain.targets) == ""


def test_channel_break_rejected_on_non_channeled():
    with pytest.raises(ValidationError):
        Card.model_validate({
            "id": "x", "name": "x", "source_name": "x", "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant",
            "effects": [{"kind": "deal_damage", "amount": 2, "trigger": "channel_break",
                         "target": {"mode": "all", "side": "enemy"}}],
        })


def test_channel_break_and_while_channeled_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        chan_card([{"kind": "pump", "power": 1, "toughness": 1,
                    "target": {"mode": "all", "side": "ally"},
                    "duration": "while_channeled", "trigger": "channel_break"}])


def test_leaves_the_battlefield_builds_as_channel_break():
    # MTG "when ~ leaves the battlefield" wording on an enchantment imports as a
    # channel_break trigger (the sacrifice/leave-play analogue, GDD §8).
    card = build_card({
        "name": "Seal of Fire", "cmc": 1.0, "type_line": "Enchantment", "rarity": "common",
        "oracle_text": "When Seal of Fire leaves the battlefield, Seal of Fire deals 2 damage to any target.",
    })
    assert card.timing.value == "channeled"
    assert card.effects and all(e.trigger == "channel_break" for e in card.effects)
    assert "When this channel ends" in card.translated_text
