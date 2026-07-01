"""Independent per-effect targeting (multi-target spells like Agony Warp).

Driven through the engine's two-function contract (legal_actions / apply_action),
exactly as the clients use it."""

from __future__ import annotations

import json
from pathlib import Path

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

_ATTACK = {"name": "Hit", "amount": 1, "action_type": "ability",
           "intent_type": "attack", "targeting": "lowest_hp_party", "mode": "melee"}
# A free filler instant so the library/hand has spare cards to draw.
_FILLER = {"id": "filler", "name": "Filler", "source_name": "Filler", "rarity": "common",
           "level": 1, "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "draw", "amount": 1}]}


def _wound(power, toughness, side="enemy"):
    return {"kind": "wound", "power": power, "toughness": toughness,
            "target": {"mode": "chosen", "side": side, "targeted": True},
            "duration": "end_of_turn"}


# Agony Warp: two independent top-level wounds.
_AGONY = {"id": "agony_warp", "name": "Agony Warp", "source_name": "Agony Warp",
          "rarity": "uncommon", "level": 1, "type": "Instant", "timing": "instant",
          "cost": {"generic": 0, "colors": {}},
          "effects": [_wound(3, 0), _wound(0, 3)]}


def _state(card, extra_enemy_keywords=None):
    spec = {
        "party": [{"id": "p", "name": "Caster", "hp": 30, "power": 2, "hand_size": 1,
                   "identity": ["U"], "library": [card, _FILLER, _FILLER]}],
        "enemies": [
            {"id": "ea", "name": "EnemyA", "hp": 12, "level": 1, "intent": dict(_ATTACK)},
            {"id": "eb", "name": "EnemyB", "hp": 12, "level": 1, "intent": dict(_ATTACK)},
        ],
    }
    st = state_from_dict(spec)
    if extra_enemy_keywords:
        for e in st.enemies:
            e.keywords.update(extra_enemy_keywords)
    return st


def _do(state, **kw):
    a = next(a for a in legal_actions(state)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(state, a)[0]


def test_agony_warp_enumerates_target_combinations():
    st = _state(_AGONY)
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "agony_warp"]
    combos = sorted(a.targets for a in casts)
    # 2 sites × 2 enemies = 4 combinations, including same-target on each enemy.
    assert combos == [("ea", "ea"), ("ea", "eb"), ("eb", "ea"), ("eb", "eb")]


def test_agony_warp_two_different_targets():
    st = _state(_AGONY)
    st = _do(st, kind="cast", card_id="agony_warp", targets=("ea", "eb"))
    st = _do(st, kind="pass")  # let the instant resolve out of the reaction window
    ea = st.enemy("ea")
    eb = st.enemy("eb")
    # wound #1 (-3/-0) hit EnemyA; wound #2 (-0/-3) hit EnemyB — independently.
    assert (ea.power_bonus, ea.temp_mod) == (-3, 0)
    assert (eb.power_bonus, eb.temp_mod) == (0, -3)


def test_agony_warp_same_target_twice():
    st = _state(_AGONY)
    st = _do(st, kind="cast", card_id="agony_warp", targets=("ea", "ea"))
    st = _do(st, kind="pass")
    ea = st.enemy("ea")
    eb = st.enemy("eb")
    # both wounds stack on EnemyA; EnemyB untouched.
    assert (ea.power_bonus, ea.temp_mod) == (-3, -3)
    assert (eb.power_bonus, eb.temp_mod) == (0, 0)


def test_single_target_card_unchanged():
    # A one-site card enumerates one cast per target with no `targets` tuple.
    one = {"id": "zap", "name": "Zap", "source_name": "Zap", "rarity": "common",
           "level": 1, "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "deal_damage", "amount": 2,
                        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]}
    st = _state(one)
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "zap"]
    assert {a.target_id for a in casts} == {"ea", "eb"}
    assert all(a.targets == () for a in casts)
    st2 = _do(st, kind="cast", card_id="zap", target_id="ea")
    st2 = _do(st2, kind="pass")
    assert st2.enemy("ea").hp == 10 and st2.enemy("eb").hp == 12


def test_conditional_strike_shares_one_target():
    """Opportune Strike: the conditional's inner damage must hit the SAME target the
    base damage hit (the condition reads it) — one shared target, not two."""
    card = json.loads((EXAMPLES / "conditional_strike.json").read_text())
    card["cost"] = {"generic": 0, "colors": {}}  # free so the test caster can cast it
    # Give the enemies flying so the conditional branch fires on the chosen target.
    st = _state(card, extra_enemy_keywords={"flying": ""})
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == card["id"]]
    # Single site → one cast per enemy, no combinations, no targets tuple.
    assert {a.target_id for a in casts} == {"ea", "eb"}
    assert all(a.targets == () for a in casts)
    st = _do(st, kind="cast", card_id=card["id"], target_id="ea")
    st = _do(st, kind="pass")
    # base 2 + conditional 2, both on EnemyA; EnemyB untouched.
    assert st.enemy("ea").hp == 12 - 4
    assert st.enemy("eb").hp == 12
