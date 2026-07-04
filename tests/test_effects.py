"""Targeting-model increment: target descriptors, slots, derived text, lints."""

import pytest
from pydantic import ValidationError

from ltg_core.lints import lint_card
from ltg_core.translation import render_effects
from ltg_core.schema import Card, effect_specs

BASE = {
    "id": "sign_in_blood",
    "name": "Sign in Blood",
    "source_name": "Sign in Blood",
    "rarity": "common",
    "level": 2,
    "type": "Sorcery",
    "timing": "sorcery",
    "original_text": "Target player draws two cards and loses 2 life.",
}

# Descriptor shorthands
CHOSEN_ALLY_T = {"mode": "chosen", "side": "ally", "targeted": True}
CHOSEN_ANY_T = {"mode": "chosen", "side": "any", "targeted": True}
CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}
SELF = {"mode": "self"}
ALL_ALLY = {"mode": "all", "side": "ally"}


def card(**over):
    return Card.model_validate({**BASE, **over})


# --- descriptor structure / validation ------------------------------------ #
def test_targeted_only_on_chosen():
    with pytest.raises(ValidationError):
        card(effects=[{"kind": "draw", "amount": 1, "target": {"mode": "self", "targeted": True}}])
    with pytest.raises(ValidationError):
        card(effects=[{"kind": "pump", "power": 1, "toughness": 1,
                       "target": {"mode": "all", "side": "ally", "targeted": True}}])


def test_side_required_unless_self():
    with pytest.raises(ValidationError):
        card(effects=[{"kind": "destroy", "target": {"mode": "chosen"}}])


def test_bad_target_string_rejected():
    with pytest.raises(ValidationError):
        card(effects=[{"kind": "draw", "amount": 2, "target": "the_moon"}])


# --- shared slots use descriptors ----------------------------------------- #
def test_shared_slot_must_be_chosen():
    with pytest.raises(ValidationError):
        card(targets={"T1": ALL_ALLY}, effects=[{"kind": "draw", "amount": 1, "target": "$T1"}])


def test_undeclared_slot_ref_rejected():
    with pytest.raises(ValidationError):
        card(effects=[{"kind": "draw", "amount": 2, "target": "$T9"}])


def test_sign_in_blood_corrected_matches_brief_json():
    c = card(
        targets={"T1": CHOSEN_ALLY_T},
        effects=[
            {"kind": "draw", "amount": 2, "target": "$T1"},
            {"kind": "lose_life", "amount": 2, "target": "$T1"},
        ],
    )
    dump = c.model_dump(mode="json")
    assert dump["targets"]["T1"] == {"mode": "chosen", "side": "ally", "exclude_self": False, "targeted": True}
    assert [e["target"] for e in dump["effects"]] == ["$T1", "$T1"]
    assert Card.model_validate(c.model_dump()) == c


# --- text derives from effects -------------------------------------------- #
def test_render_shared_target_wording():
    c = card(
        targets={"T1": CHOSEN_ALLY_T},
        effects=[
            {"kind": "draw", "amount": 2, "target": "$T1"},
            {"kind": "lose_life", "amount": 2, "target": "$T1"},
        ],
    )
    assert render_effects(c.effects, c.targets) == "Choose an ally: they draw 2, then lose 2 HP."


def test_render_direct_descriptors():
    c = card(effects=[{"kind": "deal_damage", "amount": 3, "target": CHOSEN_ENEMY_T}])
    assert render_effects(c.effects, c.targets) == "Deal 3 damage to an enemy."
    a = card(type="Enchantment", timing="channeled",
             effects=[{"kind": "pump", "power": 1, "toughness": 1, "target": ALL_ALLY}])
    assert "all allies" in render_effects(a.effects, a.targets).lower()


# --- worked examples round-trip ------------------------------------------- #
def test_worked_examples_round_trip():
    giant = card(effects=[{"kind": "pump", "power": 3, "toughness": 3, "target": CHOSEN_ANY_T}])
    assert giant.effects[0].target.targeted is True
    assert Card.model_validate(giant.model_dump()) == giant


# --- draw/scry cannot target enemies -------------------------------------- #
def test_draw_enemy_rejected():
    with pytest.raises(ValidationError):
        card(effects=[{"kind": "draw", "amount": 2, "target": CHOSEN_ENEMY_T}])
    with pytest.raises(ValidationError):
        card(targets={"T1": CHOSEN_ENEMY_T}, effects=[{"kind": "scry", "amount": 1, "target": "$T1"}])


def test_lint_draw_any_side_flagged():
    c = card(effects=[{"kind": "draw", "amount": 2, "target": CHOSEN_ANY_T}])
    assert any("either side" in m for m in lint_card(c))


def test_lint_exclude_self_on_enemy():
    c = card(effects=[{"kind": "deal_damage", "amount": 2,
                       "target": {"mode": "chosen", "side": "enemy", "exclude_self": True, "targeted": True}}])
    assert any("no-op" in m for m in lint_card(c))


def test_lint_counter_on_non_instant():
    # BASE is a Sorcery; a counter on a non-instant is flagged (can't respond).
    c = card(effects=[{"kind": "counter", "filter": "action",
                       "target": {"class": "action", "side": "enemy"}}])
    assert any("respond" in m for m in lint_card(c))


def test_lint_zero_amount_and_unused_slot():
    c = card(
        targets={"T1": CHOSEN_ALLY_T, "T2": CHOSEN_ALLY_T},
        effects=[{"kind": "draw", "amount": 0, "target": "$T1"}],
    )
    lints = lint_card(c)
    assert any("amount is 0" in m for m in lints)
    assert any("T2" in m and "never used" in m for m in lints)


def test_lint_slots_referenced_inside_modal_are_used():
    # Healing Salve shape: "Choose one — heal $T1 / prevent damage to $T2". The
    # slot refs live inside modal modes; the slot lint must descend into them.
    c = card(
        targets={"T1": CHOSEN_ALLY_T, "T2": CHOSEN_ANY_T},
        effects=[{
            "kind": "modal",
            "choose": 1,
            "modes": [
                {"effects": [{"kind": "heal", "amount": 3, "target": "$T1"}]},
                {"effects": [{"kind": "prevent", "parameter": "combat_damage",
                              "uses": "next", "target": "$T2",
                              "duration": "this_turn"}]},
            ],
        }],
    )
    assert not any("never used" in m for m in lint_card(c))


def test_duration_end_of_turn_is_legacy_alias_of_this_turn():
    from ltg_core.schema import Duration
    # `end_of_turn` was merged into `this_turn`; it is no longer a member but old
    # data still loads and normalises so nothing breaks on import.
    assert "end_of_turn" not in {d.value for d in Duration}
    c = card(effects=[{"kind": "pump", "power": 1, "toughness": 1,
                       "target": CHOSEN_ALLY_T, "duration": "end_of_turn"}])
    assert c.effects[0].duration is Duration.this_turn
    assert c.model_dump(mode="json")["effects"][0]["duration"] == "this_turn"


def test_lint_flags_multiple_independent_inline_targets():
    # A "+2/+2 and gains lifelink" spell authored with two inline chosen targets
    # resolves to TWO independent targets — the lint nudges toward a shared slot.
    c = card(effects=[
        {"kind": "pump", "power": 2, "toughness": 2, "target": CHOSEN_ANY_T},
        {"kind": "grant_keyword", "keywords": ["lifelink"], "target": CHOSEN_ANY_T},
    ])
    assert any("independently" in m and "shared slot" in m for m in lint_card(c))


def test_shared_slot_two_effects_is_not_flagged():
    # The same spell, but both effects share $T1 → one target, no warning.
    c = card(
        targets={"T1": CHOSEN_ANY_T},
        effects=[
            {"kind": "pump", "power": 2, "toughness": 2, "target": "$T1"},
            {"kind": "grant_keyword", "keywords": ["lifelink"], "target": "$T1"},
        ],
    )
    assert not any("independently" in m for m in lint_card(c))


def test_distinct_slots_are_not_flagged():
    # Agony-Warp shape: two effects on two distinct slots is deliberate, not a warning.
    c = card(
        targets={"T1": CHOSEN_ANY_T, "T2": CHOSEN_ANY_T},
        effects=[
            {"kind": "wound", "power": 3, "toughness": 0, "target": "$T1"},
            {"kind": "wound", "power": 0, "toughness": 3, "target": "$T2"},
        ],
    )
    assert not any("independently" in m for m in lint_card(c))


# --- editor metadata ------------------------------------------------------- #
def test_effect_specs_cover_all_kinds():
    specs = effect_specs()
    assert "draw" in specs and "pump" in specs
    draw_params = {p["name"]: p for p in specs["draw"]["params"]}
    assert draw_params["target"]["control"] == "target"
    pump_params = {p["name"]: p for p in specs["pump"]["params"]}
    assert pump_params["duration"]["control"] == "enum"
