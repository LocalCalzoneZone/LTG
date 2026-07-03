"""Design Update 04 §F-4 — Swarm: an enemy create_token spawns enemy-side tokens
(full enemies that attack the party and must be defeated), capped at 2 alive per
creator (T-27)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import CreateToken


def _char(cid, hp=40, power=2):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": "front", "attack_mode": "melee", "library": []}


def _swarmer(eid="e", cd=1):
    return {"id": eid, "name": eid, "hp": 30, "level": 3,
            "intent": {"name": "Bite", "amount": 1, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _swarm_component(cd=1, count=2):
    return Component(id="swarm", archetype="Swarm", priority=20, cooldown=cd,
                     verbs=[CreateToken(token_id="bat", count=count, hp=2, power=1)],
                     target_rule="self", telegraph="Call Swarm")


def _state(cd=1, count=2):
    st = state_from_dict({"party": [_char("p")], "enemies": [_swarmer()]})
    st.enemies[0].components.append(_swarm_component(cd=cd, count=count))
    return st


def _end_turn(st):
    """Advance one full turn: the player ends, the enemy step + end step run."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    return st


def test_swarm_spawns_enemy_side_tokens():
    st = _state(count=2)
    st = _end_turn(st)                             # turn 1: the swarmer calls its swarm
    tokens = [e for e in st.enemies if e.created_by == "e"]
    assert len(tokens) == 2                        # two enemy tokens joined the enemy side
    assert all(t.intent_template.get("intent_type") == "attack" for t in tokens)
    assert all(t.max_hp == 2 and t.power == 1 for t in tokens)


def test_swarm_respects_per_creator_cap_and_attacks_when_full():
    st = _state(cd=1, count=2)
    st = _end_turn(st)                             # turn 1: spawns 2 (now at cap)
    assert len([e for e in st.enemies if e.created_by == "e"]) == 2
    hp_before = st.party[0].hp
    st = _end_turn(st)                             # turn 2: at cap -> skip swarm, attack instead
    assert len([e for e in st.enemies if e.created_by == "e"]) == 2   # no third token
    assert st.party[0].hp < hp_before             # the creator (and tokens) attacked instead


def test_spawned_token_counts_for_victory():
    # A spawned enemy token keeps the encounter live — it must be defeated too.
    st = _state(count=1)
    st = _end_turn(st)
    assert any(e.created_by == "e" for e in st.enemies)
    assert st.result is None
