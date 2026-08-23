"""The combat-damage reach qualifier (`combat_kind`: all | melee | ranged) on
prevent / protection / amplify, and `protection` as a typed one-shot CHARGE
(parameter: all_damage | combat_damage | spell_damage) distinct from a
duration-bound `prevent` shield."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ltg_combat.engine import _prevent_match, apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component, ProtectionTag
from ltg_core.schema import (Card, DealDamage, Heal, Prevent, Protection, Amplify,
                             effect_specs, t_chosen, t_self)
from ltg_core.translation import render_effects


def _shield_card(kind="prevent", **extra):
    eff = {"kind": kind, "target": {"mode": "all", "side": "ally"}, **extra}
    if kind == "prevent":
        eff.setdefault("uses", "all")
        eff.setdefault("duration", "this_turn")
    return {"id": "shield", "name": "Shield", "source_name": "Shield",
            "rarity": "common", "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "effects": [eff], "validated": True}


def _state(card, mode="melee", components=None):
    st = state_from_dict({
        "party": [{"id": "ys", "name": "Ys", "hp": 10, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [dict(card)]}],
        "enemies": [{"id": "sov", "name": "Sovereign", "hp": 20, "level": 4,
                     "attack_mode": mode,
                     "intent": {"name": "Swipe", "amount": 3,
                                "action_type": "ability", "intent_type": "attack",
                                "targeting": "lowest_hp_party", "mode": mode}}],
    })
    st.enemies[0].components.extend(components or [])
    return st


def _run_until_turn(st, turn=2):
    while not (st.turn >= turn and st.phase == "player" and not st.stack):
        acts = legal_actions(st)
        if not acts or st.result is not None:
            break
        a = (next((x for x in acts if x.kind == "cast" and x.card_id == "shield"), None)
             or next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    return st


# --- schema -------------------------------------------------------------------
def test_combat_kind_defaults_to_all_on_every_lane_verb():
    """Existing cards never wrote the qualifier: they load as 'all'."""
    assert Prevent(parameter="combat_damage", target=t_self()).combat_kind == "all"
    assert Protection(target=t_self()).combat_kind == "all"
    assert Protection(target=t_self()).parameter == "all_damage"
    assert Amplify(event="combat_damage").combat_kind == "all"
    with pytest.raises(ValidationError):
        Prevent(parameter="combat_damage", combat_kind="thrown", target=t_self())


def test_legacy_protection_scope_still_loads():
    p = Protection.model_validate({"kind": "protection", "target": {"mode": "self"},
                                   "scope": "next_spell_or_attack"})
    assert p.parameter == "all_damage" and not hasattr(p, "scope")


def test_editor_spec_gates_combat_kind_on_the_lane():
    specs = effect_specs()
    for kind, lane in (("prevent", "parameter"), ("protection", "parameter"),
                       ("amplify", "event")):
        ck = next(p for p in specs[kind]["params"] if p["name"] == "combat_kind")
        assert ck["control"] == "enum" and ck["options"] == ["all", "melee", "ranged"]
        assert ck["default"] == "all"
        assert ck["show_when"] == {"field": lane, "values": ["combat_damage"]}
    prot = {p["name"]: p for p in specs["protection"]["params"]}
    assert prot["parameter"]["options"] == ["all_damage", "combat_damage", "spell_damage"]
    assert "scope" not in prot


# --- matching --------------------------------------------------------------------
class _Src:
    def __init__(self, mode): self.attack_mode = mode


def test_prevent_match_honours_reach():
    assert _prevent_match("combat_damage", "attack", "melee", None, "melee")
    assert not _prevent_match("combat_damage", "attack", "melee", None, "ranged")
    assert _prevent_match("combat_damage", "attack", "all", None, "ranged")
    # An ability wears its owner's reach; a fight is always melee.
    assert _prevent_match("combat_damage", "ability", "ranged", _Src("ranged"), None)
    assert not _prevent_match("combat_damage", "ability", "melee", _Src("ranged"), None)
    assert _prevent_match("combat_damage", "fight", "melee", _Src("ranged"), None)
    # Spell damage never carries a reach.
    assert not _prevent_match("combat_damage", "spell", "all", None, "melee")
    assert _prevent_match("all_damage", "spell", "melee", None, None)


# --- engine ------------------------------------------------------------------------
def test_melee_prevent_stops_the_melee_swing():
    st = _run_until_turn(_state(_shield_card(parameter="combat_damage", combat_kind="melee")))
    assert st.character("ys").hp == 10
    ev = next(e for e in st.log if e.type == "prevented")
    assert ev.data.get("combat_kind") == "melee"


def test_melee_prevent_lets_the_ranged_volley_through_and_says_why():
    st = _run_until_turn(_state(_shield_card(parameter="combat_damage", combat_kind="melee"),
                                mode="ranged"))
    assert st.character("ys").hp == 7
    note = next(e for e in st.log if e.type == "not_prevented")
    assert "ranged" in note.msg and "melee combat damage" in note.msg


def test_ranged_prevent_stops_the_ranged_volley():
    st = _run_until_turn(_state(_shield_card(parameter="combat_damage", combat_kind="ranged"),
                                mode="ranged"))
    assert st.character("ys").hp == 10


def test_protection_charge_is_typed_and_persists_across_turns():
    """A spell_damage protection ignores the attack (which lands) and is still
    standing next turn — a charge has no clock, unlike a prevent shield."""
    st = _run_until_turn(_state(_shield_card("protection", parameter="spell_damage")), turn=3)
    ys = st.character("ys")
    assert ys.hp == 4                      # two melee swings landed
    assert [t.parameter for t in ys.protection_tags] == ["spell_damage"]


def test_all_damage_protection_negates_one_hit_then_is_spent():
    st = _run_until_turn(_state(_shield_card("protection")), turn=3)
    ys = st.character("ys")
    assert ys.hp == 7                      # turn-1 swing negated, turn-2 swing landed
    assert ys.protection_tags == []
    assert any(e.type == "protected" for e in st.log)


def test_melee_protection_ignores_ranged():
    st = _run_until_turn(_state(_shield_card("protection", parameter="combat_damage",
                                             combat_kind="melee"), mode="ranged"))
    ys = st.character("ys")
    assert ys.hp == 7 and len(ys.protection_tags) == 1


# --- card text -----------------------------------------------------------------------
def test_card_text_names_the_reach_and_the_charge():
    txt = render_effects([Prevent(parameter="combat_damage", combat_kind="ranged",
                                  target={"mode": "all", "side": "ally"})])
    assert "ranged combat damage" in txt
    txt = render_effects([Protection(target=t_chosen("ally", targeted=True))])
    assert "protection" in txt and "next damaging spell, attack or ability" in txt
    txt = render_effects([Protection(parameter="combat_damage", combat_kind="melee",
                                     target=t_chosen("ally", targeted=True))])
    assert "next melee combat damage" in txt
