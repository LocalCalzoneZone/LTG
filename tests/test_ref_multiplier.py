"""A reference value may carry an integer multiplier — {"ref": …, "mult": 2} is
"twice …" — resolved by the engine, worded by the translator, and omitted from
JSON when 1 so existing cards serialize unchanged."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ltg_combat.engine import _value
from ltg_core.schema import Card, DealDamage, Ref, t_chosen
from ltg_core.translation import render_effects


class _Obj:
    power = 2
    power_bonus = 3
    max_hp = 20
    hp = 7

    @property
    def current_power(self):
        return self.power + self.power_bonus

    @property
    def effective_hp(self):
        return self.hp


def test_engine_scales_the_resolved_reference():
    ctx = {"caster_obj": _Obj(), "target_obj": _Obj(), "x": 3, "capacity": 4}
    assert _value(Ref(ref="caster_base_power", mult=2), ctx) == 4
    assert _value(Ref(ref="caster_power", mult=3), ctx) == 15
    assert _value(Ref(ref="x", mult=2), ctx) == 6
    assert _value(Ref(ref="mana_capacity", mult=2), ctx) == 8
    assert _value(Ref(ref="caster_base_power"), ctx) == 2  # default: unscaled


def test_multiplier_must_be_at_least_one():
    with pytest.raises(ValidationError):
        Ref(ref="x", mult=0)


def test_unit_multiplier_is_omitted_from_json():
    assert Ref(ref="x").model_dump() == {"ref": "x"}
    assert Ref(ref="x", mult=2).model_dump() == {"ref": "x", "mult": 2}
    # Round-trips through a card.
    c = Card.model_validate({
        "id": "c", "name": "c", "source_name": "c", "rarity": "common", "level": 1,
        "type": "Instant", "timing": "instant",
        "effects": [{"kind": "deal_damage", "amount": {"ref": "caster_base_power", "mult": 2},
                     "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]})
    dumped = json.loads(c.model_dump_json())
    assert dumped["effects"][0]["amount"] == {"ref": "caster_base_power", "mult": 2}


def test_card_text_words_the_multiplier():
    tgt = t_chosen("enemy", targeted=True)
    assert render_effects([DealDamage(amount=Ref(ref="caster_base_power", mult=2), target=tgt)]) \
        == "Deal damage equal to twice your base Power to an enemy."
    assert render_effects([DealDamage(amount=Ref(ref="target_hp", mult=3), target=tgt)]) \
        == "Deal damage equal to three times its current HP to an enemy."
    assert "2X damage" in render_effects([DealDamage(amount=Ref(ref="x", mult=2), target=tgt)])
    # A scaled capacity ref is no longer the "1 per point" phrasing.
    assert "twice your mana capacity" in render_effects(
        [DealDamage(amount=Ref(ref="mana_capacity", mult=2), target=tgt)])


# --- set_reference: stored values ------------------------------------------- #
def _state_two_enemies(card):
    from ltg_combat.scenario import state_from_dict
    intent = {"name": "Bite", "amount": 1, "action_type": "ability",
              "intent_type": "attack", "targeting": "lowest_hp_party", "mode": "melee"}
    return state_from_dict({
        "party": [{"id": "ys", "name": "Ys", "hp": 10, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [dict(card)]}],
        "enemies": [{"id": "e1", "name": "Rat", "hp": 5, "level": 1,
                     "attack_mode": "melee", "intent": dict(intent)},
                    {"id": "e2", "name": "Bat", "hp": 7, "level": 1,
                     "attack_mode": "melee", "intent": dict(intent)}],
    })


def test_set_reference_survives_the_destroy_it_precedes():
    """'Remember the target's max HP, destroy it, deal that much to another
    enemy' — the snapshot is taken before the body is gone."""
    from ltg_combat.engine import apply_action, legal_actions
    card = {"id": "c", "name": "C", "source_name": "C", "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
            "validated": True,
            "targets": {"T1": {"mode": "chosen", "side": "enemy", "targeted": True},
                        "T2": {"mode": "chosen", "side": "enemy", "exclude_self": True,
                               "targeted": True}},
            "effects": [
                {"kind": "set_reference", "name": "R1",
                 "value": {"ref": "target_base_hp"}, "target": "$T1"},
                {"kind": "destroy", "target": "$T1"},
                {"kind": "deal_damage", "amount": {"ref": "$R1"}, "target": "$T2"},
            ]}
    st = _state_two_enemies(card)
    while True:
        acts = legal_actions(st)
        cast = next((a for a in acts if a.kind == "cast" and a.card_id == "c"
                     and tuple(a.targets) == ("e1", "e2")), None)
        if cast is not None:
            break
        nxt = next((a for a in acts if a.kind in ("pass", "end_turn")), acts[0])
        st = apply_action(st, nxt)[0]
    st = apply_action(st, cast)[0]
    # Let the cast resolve (pass priority until the stack empties).
    for _ in range(10):
        if not st.stack:
            break
        acts = legal_actions(st)
        st = apply_action(st, next(a for a in acts if a.kind == "pass"))[0]
    assert st.enemy("e1") is None or not st.enemy("e1").alive   # destroyed
    bat = st.enemy("e2")
    assert bat is not None and bat.hp == 2                      # 7 − R1 (5)
    assert any(getattr(ev, "kind", None) == "set_reference" and ev.data.get("value") == 5
               for ev in st.log) or any("remembers 5 as R1" in str(ev) for ev in st.log)


def test_stored_ref_must_be_declared_on_the_card():
    with pytest.raises(ValidationError):
        Card.model_validate({
            "id": "c", "name": "c", "source_name": "c", "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant",
            "effects": [{"kind": "heal", "amount": {"ref": "$R1"}, "target": {"mode": "self"}}]})


def test_set_reference_card_text():
    c = Card.model_validate({
        "id": "c", "name": "c", "source_name": "c", "rarity": "common", "level": 1,
        "type": "Sorcery", "timing": "sorcery",
        "targets": {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}},
        "effects": [
            {"kind": "set_reference", "name": "R1", "value": {"ref": "target_base_hp"},
             "target": "$T1"},
            {"kind": "destroy", "target": "$T1"},
            {"kind": "heal", "amount": {"ref": "$R1"},
             "target": {"mode": "chosen", "side": "ally", "targeted": True}}]})
    assert render_effects(c.effects, c.targets) == (
        "Choose an enemy: they have their maximum HP noted as R1, then are destroyed. "
        "Restore HP equal to R1 to an ally.")
