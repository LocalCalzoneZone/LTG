"""`exclude_self` ("another …") on a CHOSEN target: the pick offers neither the
caster nor a creature one of the card's other target sites already names."""

from __future__ import annotations

from ltg_combat.engine import legal_actions
from ltg_combat.scenario import state_from_dict


def _state(card):
    return state_from_dict({
        "party": [{"id": "ys", "name": "Ys", "hp": 10, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [dict(card)]},
                  {"id": "bo", "name": "Bo", "hp": 10, "power": 2, "hand_size": 0,
                   "identity": ["W"], "row": "mid", "attack_mode": "melee",
                   "library": []}],
        "enemies": [{"id": "e1", "name": "Rat", "hp": 5, "level": 1, "attack_mode": "melee",
                     "intent": {"name": "Bite", "amount": 1, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}},
                    {"id": "e2", "name": "Bat", "hp": 5, "level": 1, "attack_mode": "melee",
                     "intent": {"name": "Bite", "amount": 1, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })


def _card(effects, targets=None):
    return {"id": "c", "name": "C", "source_name": "C", "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
            "validated": True, "effects": effects, "targets": targets or {}}


def _casts(st):
    return [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "c"]


def test_another_ally_never_offers_the_caster():
    st = _state(_card([{"kind": "heal", "amount": 2,
                        "target": {"mode": "chosen", "side": "ally",
                                   "exclude_self": True, "targeted": True}}]))
    assert {a.target_id for a in _casts(st)} == {"bo"}


def test_another_pick_differs_from_the_cards_other_pick():
    st = _state(_card(
        [{"kind": "deal_damage", "amount": 2, "target": "$T1"},
         {"kind": "deal_damage", "amount": 1, "target": "$T2"}],
        targets={"T1": {"mode": "chosen", "side": "enemy", "targeted": True},
                 "T2": {"mode": "chosen", "side": "enemy", "exclude_self": True,
                        "targeted": True}}))
    combos = {tuple(a.targets) for a in _casts(st)}
    assert combos == {("e1", "e2"), ("e2", "e1")}


def test_another_side_any_excludes_caster_and_other_pick():
    st = _state(_card(
        [{"kind": "deal_damage", "amount": 2, "target": "$T1"},
         {"kind": "deal_damage", "amount": 1, "target": "$T2"}],
        targets={"T1": {"mode": "chosen", "side": "any", "targeted": True},
                 "T2": {"mode": "chosen", "side": "any", "exclude_self": True,
                        "targeted": True}}))
    combos = {tuple(a.targets) for a in _casts(st)}
    assert combos, "the card must still be castable"
    for first, second in combos:
        assert second != "ys" and second != first


def test_two_plain_picks_may_still_coincide():
    st = _state(_card(
        [{"kind": "deal_damage", "amount": 2, "target": "$T1"},
         {"kind": "deal_damage", "amount": 1, "target": "$T2"}],
        targets={"T1": {"mode": "chosen", "side": "enemy", "targeted": True},
                 "T2": {"mode": "chosen", "side": "enemy", "targeted": True}}))
    assert ("e1", "e1") in {tuple(a.targets) for a in _casts(st)}
