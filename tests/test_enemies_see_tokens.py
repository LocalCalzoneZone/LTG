"""Roadmap M1.27 (ruled 2026-09-25):
(a) regen ticks pay the placer's gauge, and mana paid for the Skill earns +1
    gauge per point;
(d) enemies may aim at the party's ordinary tokens, and grounded tokens form
    the melee wall (tokens used to be invisible to enemy aim)."""

from __future__ import annotations

from ltg_combat.engine import _tick_afflictions_one, settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import TokenState


def _hero(hid, row="front", hp=20):
    return {"id": hid, "name": hid, "hp": hp, "power": 2, "hand_size": 0,
            "identity": ["U"], "row": row, "attack_mode": "melee", "library": []}


def _brute():
    return {"id": "brute", "name": "brute", "hp": 20, "level": 2, "power": 2,
            "attack_mode": "melee",
            "intent": {"name": "Smash", "amount": 3, "action_type": "attack",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def test_a_grounded_token_walls_a_melee_enemy_off_the_heroes():
    st = state_from_dict({"party": [_hero("mage", row="mid")], "enemies": [_brute()]})
    st.tokens.append(TokenState(id="wolf", name="Wolf", hp=4, max_hp=4, power=1, row="front"))
    st = settle(st)
    assert st.enemy("brute").intent.target_id == "wolf"   # the wolf is the wall


def test_regen_ticks_pay_whoever_placed_them():
    st = state_from_dict({"party": [_hero("medic"), _hero("hurt", hp=20)],
                          "enemies": [_brute()]})
    hurt = st.character("hurt")
    hurt.hp = 10
    hurt.regen_counters, hurt.regen_source = 3, "medic"
    before = st.character("medic").ultimate_gauge
    _tick_afflictions_one(st, hurt)
    assert hurt.hp == 13
    assert st.character("medic").ultimate_gauge == before + 3
