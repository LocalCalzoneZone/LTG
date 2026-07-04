"""Modal ('Choose one') + conditional ('If …') effects: schema, render, validate."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ltg_core.translation import render_effects
from ltg_deckbuilder.ingest import build_card, parse_modal
from ltg_core.schema import Card, effect_specs

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
ENEMY = {"mode": "chosen", "side": "enemy", "targeted": True}


def card(effects, **kw):
    base = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant"}
    base.update(kw)
    return Card.model_validate({**base, "effects": effects})


# --- modal ------------------------------------------------------------------ #
def test_modal_render():
    c = card([{"kind": "modal", "modes": [
        {"effects": [{"kind": "deal_damage", "amount": 3, "target": ENEMY}]},
        {"effects": [{"kind": "draw", "amount": 2, "target": {"mode": "self"}}]},
    ]}])
    assert render_effects(c.effects) == \
        "Choose one — • Deal 3 damage to an enemy. • Draw 2 card(s)."


def test_modal_choose_count_render():
    modes = [
        {"effects": [{"kind": "deal_damage", "amount": 3, "target": ENEMY}]},
        {"effects": [{"kind": "draw", "amount": 2, "target": {"mode": "self"}}]},
        {"effects": [{"kind": "scry", "amount": 1, "target": {"mode": "self"}}]},
    ]
    assert render_effects(card([{"kind": "modal", "choose": 2, "modes": modes}]).effects) \
        .startswith("Choose two — ")
    assert render_effects(card([{"kind": "modal", "choose": 1, "or_more": True,
                                 "modes": modes}]).effects).startswith("Choose one or more — ")


def test_modal_choose_cannot_exceed_modes():
    with pytest.raises(ValidationError):
        card([{"kind": "modal", "choose": 3, "modes": [
            {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]},
            {"effects": [{"kind": "scry", "amount": 1, "target": {"mode": "self"}}]},
        ]}])


def test_strip_intent_shared_slot_render():
    """Recoil-style: strip_intent in a shared slot reads grammatically and never
    leaks the raw '$slot' reference (regression for the reported bug)."""
    c = card([{"kind": "bounce", "target": "$T1"},
              {"kind": "strip_intent", "target": "$T2"}],
             targets={"T1": {"mode": "chosen", "side": "any"},
                      "T2": {"mode": "chosen", "side": "any", "exclude_self": True}})
    out = render_effects(c.effects, c.targets)
    assert out == ("Choose a target: they are returned to hand. "
                   "Choose another target: they lose their telegraphed intent.")
    assert "$" not in out


def test_modal_requires_two_modes():
    with pytest.raises(ValidationError):
        card([{"kind": "modal", "modes": [
            {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]}]}])


def test_modal_mode_needs_effects():
    with pytest.raises(ValidationError):
        card([{"kind": "modal", "modes": [
            {"effects": []},
            {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]}]}])


def test_modal_auto_build():
    c = build_card({"name": "Charm", "cmc": 2.0, "type_line": "Instant", "rarity": "uncommon",
                    "oracle_text": "Choose one —\n• Counter target spell.\n• Draw two cards."})
    assert c.effects[0].kind == "modal"
    assert len(c.effects[0].modes) == 2
    assert c.translated_text.startswith("Choose one —")


def test_modal_mode_resolves_shared_slot():
    """Healing Salve shape: slot refs inside modal modes must resolve to their
    slot description, not leak the raw '$T1'/'$T2' (regression for reported bug)."""
    c = card(
        [{"kind": "modal", "modes": [
            {"effects": [{"kind": "heal", "amount": 3, "target": "$T1"}]},
            {"effects": [{"kind": "prevent", "parameter": "combat_damage",
                          "uses": "next", "target": "$T2", "duration": "this_turn"}]},
        ]}],
        targets={"T1": {"mode": "chosen", "side": "ally"},
                 "T2": {"mode": "chosen", "side": "any"}},
    )
    out = render_effects(c.effects, c.targets)
    assert "$" not in out
    assert out == ("Choose one — • Choose an ally: they heal 3. "
                   "• Choose a target: they have the next combat damage prevented.")


def test_parse_modal_skips_non_modal():
    assert parse_modal("Draw a card.") is None


# --- conditional ------------------------------------------------------------ #
def test_conditional_cast_mode_render():
    c = card([
        {"kind": "deal_damage", "amount": 2, "target": ENEMY},
        {"kind": "conditional", "condition": {"kind": "cast_mode", "mode": "reaction"},
         "effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]},
    ])
    assert render_effects(c.effects) == \
        "Deal 2 damage to an enemy. If cast as a reaction, draw 1 card(s)."


def test_conditional_target_property_render():
    c = card([{"kind": "conditional",
               "condition": {"kind": "target_property", "property": "has_keyword", "keyword": "flying"},
               "effects": [{"kind": "deal_damage", "amount": 2, "target": ENEMY}]}])
    assert render_effects(c.effects) == "Deal 2 damage to an enemy with flying."


def test_conditional_side_render():
    c = card([{"kind": "conditional",
               "condition": {"kind": "target_property", "property": "side", "side": "enemy"},
               "effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]}])
    assert "If the target is an enemy" in render_effects(c.effects)


def test_has_keyword_requires_known_keyword():
    with pytest.raises(ValidationError):
        card([{"kind": "conditional",
               "condition": {"kind": "target_property", "property": "has_keyword", "keyword": "bogus"},
               "effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]}])


def test_modal_mode_may_hold_a_conditional():
    # modal > conditional > effect: the condition applies to the mode's effect.
    c = card([{"kind": "modal", "modes": [
        {"effects": [{"kind": "deal_damage", "amount": 2, "target": ENEMY}]},
        {"effects": [{"kind": "conditional",
                      "condition": {"kind": "target_property", "property": "level", "level": 4, "compare": "or_more"},
                      "effects": [{"kind": "destroy", "target": ENEMY}]}]},
    ]}])
    assert c.effects[0].modes[1].effects[0].kind == "conditional"
    assert render_effects(c.effects) == \
        "Choose one — • Deal 2 damage to an enemy. • Destroy an enemy with level 4 or more."
    assert Card.model_validate(c.model_dump()) == c  # round-trips


def test_modal_mode_rejects_nested_modal():
    # No modal-in-modal — a mode may hold a conditional, but not another modal.
    with pytest.raises(ValidationError):
        card([{"kind": "modal", "modes": [
            {"effects": [{"kind": "modal", "modes": [
                {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]},
                {"effects": [{"kind": "scry", "amount": 1, "target": {"mode": "self"}}]}]}]},
            {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]}]}])


def test_nested_draw_enemy_rejected_in_mode():
    # iter_effects descends into modes, so the illegal nested draw is caught.
    with pytest.raises(ValidationError):
        card([{"kind": "modal", "modes": [
            {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "chosen", "side": "enemy"}}]},
            {"effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}]}]}])


# --- editor metadata + fixtures --------------------------------------------- #
def test_effect_specs_nested_controls():
    specs = effect_specs()
    modal_modes = next(p for p in specs["modal"]["params"] if p["name"] == "modes")
    assert modal_modes["control"] == "nested"
    cond_fields = {p["name"]: p["control"] for p in specs["conditional"]["params"]}
    assert cond_fields["condition"] == "nested" and cond_fields["effects"] == "nested"


@pytest.mark.parametrize("name", ["modal_charm", "conditional_strike"])
def test_fixtures_round_trip(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    c = Card.model_validate(data)
    assert Card.model_validate(c.model_dump()) == c
