"""The three extended conditional properties (Deckbuilder/engine update):
`self_hp` (caster HP as a % of max), `enemy_count` (living enemies vs party
size), and `spells_cast` (spells the caster has cast this turn, counting the
one resolving). Driven through the engine's legal_actions/apply_action contract."""

from __future__ import annotations

import pytest

from ltg_core.schema import Card
from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _conditional_card(cid, condition):
    """A 0-cost sorcery: 'If <condition>, deal 5 damage to target enemy.'"""
    return {
        "id": cid, "name": cid, "source_name": cid, "rarity": "common",
        "level": 1, "type": "Sorcery", "timing": "sorcery",
        "cost": {"generic": 0, "colors": {}},
        "effects": [{"kind": "conditional", "condition": condition,
                     "effects": [{"kind": "deal_damage", "amount": 5,
                                  "target": {"mode": "chosen", "side": "enemy",
                                             "targeted": True}}]}],
        "validated": True,
    }


def _free_draw(cid="cantrip"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Sorcery", "timing": "sorcery",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "scry", "amount": 0}], "validated": True}


def _state(cards, hp=20, extra_enemies=0):
    enemies = [{"id": f"ogre{i}", "name": f"Ogre{i}", "hp": 30, "level": 1,
                "intent": {"name": "Bash", "amount": 0, "action_type": "ability",
                           "intent_type": "attack", "targeting": "lowest_hp_party",
                           "mode": "melee"}}
               for i in range(1 + extra_enemies)]
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": hp, "power": 2,
                   "hand_size": len(cards), "identity": ["U"], "row": "front",
                   "attack_mode": "melee", "library": cards}],
        "enemies": enemies,
    })


def _cast(state, card_id, target_id=None):
    """Advance to the player phase, cast `card_id`, and let the stack settle."""
    for _ in range(200):
        acts = legal_actions(state)
        cast = next((a for a in acts if a.kind == "cast" and a.card_id == card_id), None)
        if cast is not None:
            if cast.target_id is None and target_id is not None:
                cast.target_id = target_id
            state = apply_action(state, cast)[0]
            break
        nxt = (next((a for a in acts if a.kind == "pass"), None)
               or next((a for a in acts if a.kind == "end_turn"), None) or acts[0])
        state = apply_action(state, nxt)[0]
    while state.stack:
        p = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if p is None:
            break
        state = apply_action(state, p)[0]
    return state


def _enemy_hp(state, eid="ogre0"):
    return state.enemy(eid).hp


# --- self_hp ---------------------------------------------------------------- #
def test_self_hp_or_less_fires_when_wounded():
    cond = {"kind": "self_hp", "percent": 50, "compare": "or_less"}
    st = _state([_conditional_card("execute", cond)], hp=20)
    st.character("p").hp = 10  # exactly 50% — "or less" includes the boundary
    st = _cast(st, "execute", target_id="ogre0")
    assert _enemy_hp(st) == 25


def test_self_hp_or_less_skips_at_full_health():
    cond = {"kind": "self_hp", "percent": 50, "compare": "or_less"}
    st = _state([_conditional_card("execute", cond)], hp=20)
    st = _cast(st, "execute", target_id="ogre0")
    assert _enemy_hp(st) == 30
    assert any(e.type == "condition_false" for e in st.log)


def test_self_hp_or_more_fires_at_full_health():
    cond = {"kind": "self_hp", "percent": 80, "compare": "or_more"}
    st = _state([_conditional_card("bold", cond)], hp=20)
    st = _cast(st, "bold", target_id="ogre0")
    assert _enemy_hp(st) == 25


# --- enemy_count -------------------------------------------------------------- #
def test_enemy_count_more_fires_when_outnumbered():
    cond = {"kind": "enemy_count", "compare": "more"}
    st = _state([_conditional_card("stand", cond)], extra_enemies=1)  # 2 enemies vs 1 hero
    st = _cast(st, "stand", target_id="ogre0")
    assert _enemy_hp(st) == 25


def test_enemy_count_more_skips_when_even():
    cond = {"kind": "enemy_count", "compare": "more"}
    st = _state([_conditional_card("stand", cond)])  # 1 enemy vs 1 hero
    st = _cast(st, "stand", target_id="ogre0")
    assert _enemy_hp(st) == 30


def test_enemy_count_equal_fires_when_even():
    cond = {"kind": "enemy_count", "compare": "equal"}
    st = _state([_conditional_card("parity", cond)])
    st = _cast(st, "parity", target_id="ogre0")
    assert _enemy_hp(st) == 25


# --- spells_cast -------------------------------------------------------------- #
def test_spells_cast_counts_this_cast_and_resets():
    cond = {"kind": "spells_cast", "count": 2, "compare": "or_more"}
    # All three start in hand (opening hand = top hand_size of the library).
    st = _state([_conditional_card("surge", cond), _free_draw("c1"),
                 _conditional_card("surge2", cond)], hp=20)

    st = _cast(st, "surge", target_id="ogre0")  # the only spell so far this turn → 1 < 2, skipped
    assert _enemy_hp(st) == 30
    st = _cast(st, "c1")     # second cast this turn
    st = _cast(st, "surge2", target_id="ogre0")  # third cast → fires (sorceries stack on a Cast turn)
    assert _enemy_hp(st) == 25


def test_spells_cast_condition_validates_in_schema():
    card = Card.model_validate(_conditional_card(
        "x", {"kind": "spells_cast", "count": 1, "compare": "exactly"}))
    assert card.effects[0].condition.kind == "spells_cast"


def test_bad_percent_rejected():
    with pytest.raises(Exception):
        Card.model_validate(_conditional_card(
            "x", {"kind": "self_hp", "percent": 150, "compare": "or_less"}))
