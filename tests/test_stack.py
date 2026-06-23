"""Stack classification: counter (filtered), action targets, intent tools, speed."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ltg_core.translation import render_effects
from ltg_core.schema import (
    AbilityKind,
    Card,
    Speed,
    ability_speed,
    spell_speed,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
ACTION = {"class": "action", "side": "enemy"}


def card(effects, **kw):
    base = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant"}
    base.update(kw)
    return Card.model_validate({**base, "effects": effects})


# --- counter rendering (worked examples) ------------------------------------ #
@pytest.mark.parametrize("filt,text", [
    ("action", "Cancel an enemy action (spell or ability)."),
    ("spell", "Cancel an enemy spell."),
    ("ability", "Cancel an enemy ability (including attacks)."),
    ("triggered", "Cancel an enemy triggered ability."),
])
def test_counter_render(filt, text):
    c = card([{"kind": "counter", "filter": filt, "target": ACTION}])
    assert render_effects(c.effects) == text


def test_intent_tools_render():
    chosen_enemy = {"mode": "chosen", "side": "enemy", "targeted": True}
    assert render_effects(card([{"kind": "strip_intent", "target": chosen_enemy}]).effects) \
        == "Remove the chosen enemy's telegraphed intent."
    assert render_effects(card([{"kind": "stun", "target": chosen_enemy}]).effects) \
        == "The chosen enemy skips its next intent."


# --- action target serialization + round-trip ------------------------------- #
def test_action_target_uses_class_key_and_round_trips():
    c = card([{"kind": "counter", "filter": "spell", "target": ACTION}])
    dump = c.model_dump(mode="json")
    assert dump["effects"][0]["target"] == {"class": "action", "side": "enemy"}
    assert Card.model_validate(c.model_dump()) == c


# --- validation ------------------------------------------------------------- #
def test_counter_rejects_creature_target():
    with pytest.raises(ValidationError):
        card([{"kind": "counter", "filter": "action",
               "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])


def test_non_counter_rejects_action_target():
    with pytest.raises(ValidationError):
        card([{"kind": "deal_damage", "amount": 2, "target": ACTION}])


def test_bad_filter_rejected():
    with pytest.raises(ValidationError):
        card([{"kind": "counter", "filter": "creature", "target": ACTION}])


def test_counter_on_sorcery_flagged():
    from ltg_core.lints import lint_card
    c = card([{"kind": "counter", "filter": "action", "target": ACTION}],
             type="Sorcery", timing="sorcery")
    assert any("respond" in m for m in lint_card(c))


# --- type / speed vocabulary ------------------------------------------------ #
def test_card_is_spell_and_speed_derives():
    assert card([]).action_type.value == "spell"
    assert card([], timing="instant").speed == Speed.reactive
    assert card([], type="Sorcery", timing="sorcery").speed == Speed.active
    assert card([], type="Enchantment", timing="channeled").speed == Speed.sustained


def test_ability_speed_derivation():
    assert ability_speed(AbilityKind.attack) == Speed.active
    assert ability_speed(AbilityKind.activated) == Speed.active
    assert ability_speed(AbilityKind.triggered) == Speed.reactive
    assert ability_speed(AbilityKind.reaction) == Speed.reactive
    assert spell_speed("instant") == Speed.reactive


# --- fixtures --------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["counterspell", "negate", "stifle"])
def test_counter_fixtures_round_trip(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    c = Card.model_validate(data)
    assert c.effects[0].kind == "counter"
    assert Card.model_validate(c.model_dump()) == c
