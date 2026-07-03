"""Design Update 04 §F-3.2 / §F-7.4 — enemy reactions as reactive components:
trigger-typed, one per enemy per window, cross-turn reuse gated by cooldowns.

Reactions fire both BEFORE the stack top resolves (on_targeted / on_spell_cast /
on_incoming_lethal) and AFTER a resolution (on_hit / on_ally_hit / on_ally_death).
Driven through the two-function contract; components attached to a runtime enemy."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import DealDamage, Heal, Wound, t_chosen, t_self


def _char(cid, power=3, hp=30, hand=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power,
            "hand_size": len(hand or []), "identity": ["U"], "row": "front",
            "attack_mode": "melee", "library": hand or []}


def _enemy(eid, hp=10, amount=2):
    return {"id": eid, "name": eid, "hp": hp, "level": 3,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _state(party, enemies, tweak=None):
    st = state_from_dict({"party": party, "enemies": enemies})
    if tweak:
        tweak(st)
    return st


def _act(st, **kw):
    a = next(a for a in legal_actions(st)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(st, a)


def _pass_all(st):
    """Pass every reaction window until the stack empties (player back to main phase),
    resolving whatever the enemy stacks in between."""
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def _punish_on_hit(cd=2, dmg=2):
    return Component(id="punish", archetype="Punish", timing="reactive",
                     trigger="on_hit", cooldown=cd, priority=25,
                     verbs=[DealDamage(amount=dmg, target=t_chosen("ally", targeted=True))],
                     target_rule="trigger_source", telegraph="Retaliate")


def _retaliate_on_targeted(dmg=2):
    return Component(id="riposte", archetype="Punish", timing="reactive",
                     trigger="on_targeted", cooldown=2, priority=25,
                     verbs=[DealDamage(amount=dmg, target=t_chosen("ally", targeted=True))],
                     target_rule="trigger_source", telegraph="Riposte")


def _fortify_on_lethal(heal=5):
    return Component(id="guard", archetype="Fortify", timing="reactive",
                     trigger="on_incoming_lethal", cooldown=3, priority=10,
                     verbs=[Heal(amount=heal, target=t_self())],
                     target_rule="self", telegraph="Last Ward")


def _react_events(log):
    return [ev for ev in log if ev.type == "enemy_react"]


# --- no reactive component -> no reaction ------------------------------------ #
def test_no_reactive_component_never_reacts():
    st = _state([_char("p")], [_enemy("e")])
    st, _ = _act(st, kind="attack", target_id="e")
    st = _pass_all(st)
    assert st.enemies and st.enemies[0].hp == 10 - 3   # the attack simply resolved


# --- on_targeted (pre-resolution) -------------------------------------------- #
def test_on_targeted_reaction_stacks_above_and_reopens():
    st = _state([_char("p", hp=30)], [_enemy("e", hp=20)],
                tweak=lambda s: s.enemies[0].components.append(_retaliate_on_targeted(2)))
    st, log = _act(st, kind="attack", target_id="e")   # player attack opens the window
    st, log = _act(st, kind="pass")                    # all pass -> enemy ripostes pre-resolution
    assert [i.label for i in st.stack] == ["Basic Attack", "Riposte"]
    assert st.stack[-1].source_side == "enemy"
    assert _react_events(log)                          # the enemy answered
    st = _pass_all(st)
    assert st.party[0].hp == 30 - 2                    # riposte hit the attacker
    assert st.enemies[0].hp == 20 - 3                  # the attack still resolved


# --- on_hit (post-resolution) ------------------------------------------------ #
def test_on_hit_reaction_fires_after_the_hit_resolves():
    st = _state([_char("p", hp=30)], [_enemy("e", hp=20)],
                tweak=lambda s: s.enemies[0].components.append(_punish_on_hit(dmg=2)))
    st, _ = _act(st, kind="attack", target_id="e")
    st = _pass_all(st)
    assert st.enemies[0].hp == 20 - 3                  # the attack landed
    assert st.party[0].hp == 30 - 2                    # then Punish answered post-resolution


# --- on_incoming_lethal (pre-resolution save) -------------------------------- #
def test_on_incoming_lethal_fortify_saves_the_enemy():
    # The enemy is wounded to 3 of a 20 max, so its heal has headroom to matter.
    def setup(s):
        s.enemies[0].hp = 3
        s.enemies[0].components.append(_fortify_on_lethal(5))
    st = _state([_char("p", power=3)], [_enemy("e", hp=20)], tweak=setup)
    st, _ = _act(st, kind="attack", target_id="e")     # 3 damage into 3 effective HP = lethal
    st = _pass_all(st)
    assert st.enemies and st.enemies[0].alive          # the heal resolved first (LIFO)
    assert st.enemies[0].hp == 3 + 5 - 3               # +5 heal, then -3 attack


# --- cooldown gates cross-turn reuse ----------------------------------------- #
def test_reaction_cooldown_blocks_next_turn_then_recovers():
    # The enemy's own attack deals 0, so only Punish moves the player's HP.
    st = _state([_char("p", hp=40)], [_enemy("e", hp=40, amount=0)],
                tweak=lambda s: s.enemies[0].components.append(_punish_on_hit(cd=2, dmg=2)))

    def player_attacks_and_ends(state):
        state, _ = _act(state, kind="attack", target_id="e")
        state = _pass_all(state)
        # end everyone's turn so the enemy step + end step run and the turn advances
        turn = state.turn
        while state.result is None and state.turn == turn:
            acts = legal_actions(state)
            act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
            state = apply_action(state, act)[0]
        return state

    hp0 = st.party[0].hp
    st = player_attacks_and_ends(st)                   # turn 1: Punish fires (player -2)
    assert st.party[0].hp == hp0 - 2 and st.turn == 2
    st = player_attacks_and_ends(st)                   # turn 2: on cooldown -> no Punish
    assert st.party[0].hp == hp0 - 2 and st.turn == 3
    st = player_attacks_and_ends(st)                   # turn 3: available again -> player -2
    assert st.party[0].hp == hp0 - 4
