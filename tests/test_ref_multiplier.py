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
