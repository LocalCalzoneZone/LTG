"""§F-7.4 pile-on rule (beta playtest, 2026-08): a trigger episode is answered
by ONE instance of a given reaction, however many bodies carry it.

Before: five enemies with the same hidden "punish the caster" reaction all
discharged into the first spell, one per window, while the spell sat on the
stack — a 5x burst that then left casting FREE for the rest of the fight (every
punisher spent, every cooldown ticking together). Now the first body answers,
the rest stay ARMED (no cooldown spent), and the next trigger meets the next
punisher: the deterrent persists instead of detonating. Distinct reactions
still all fire — they are different threats, not echoes."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import DealDamage, Wound, t_chosen


def _char(cid, power=3, hp=30):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": "front", "attack_mode": "melee",
            "library": []}


def _enemy(eid, hp=20):
    return {"id": eid, "name": eid, "hp": hp, "level": 3,
            "intent": {"name": "Hit", "amount": 2, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _riposte(dmg=2):
    """The pile-on shape from the playtest: "a hero swings — punish them",
    carried by many bodies. `on_attack` (like `on_spell_cast`) matches the
    stack top whoever it aims at, so every carrier is eligible at once."""
    return Component(id="riposte", archetype="Punish", timing="reactive",
                     trigger="on_attack", cooldown=2, priority=25,
                     verbs=[DealDamage(amount=dmg,
                                       target=t_chosen("ally", targeted=True))],
                     target_rule="trigger_source", telegraph="Riposte")


def _hexlash():
    """Same trigger, DIFFERENT payload shape — a distinct threat."""
    return Component(id="hexlash", archetype="Debilitate", timing="reactive",
                     trigger="on_attack", cooldown=2, priority=30,
                     verbs=[Wound(power=1, toughness=1,
                                  target=t_chosen("ally", targeted=True))],
                     target_rule="trigger_source", telegraph="Hex-Lash")


def _state(party, enemies, comps):
    st = state_from_dict({"party": party, "enemies": enemies})
    for e, comp in zip(st.enemies, comps):
        if comp is not None:
            e.components.append(comp)
    return st


def _attack(st, target_id):
    a = next(a for a in legal_actions(st)
             if a.kind == "attack" and a.target_id == target_id)
    return apply_action(st, a)[0]


def _pass_all(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def test_identical_reactions_answer_one_episode_once():
    """Three bodies, one shared riposte, one attack: 2 damage comes back — not 6."""
    st = _state([_char("p")], [_enemy(f"e{i}") for i in range(3)],
                [_riposte(), _riposte(), _riposte()])
    st = _pass_all(_attack(st, "e0"))
    assert st.character("p").hp == 30 - 2


def test_the_unfired_bodies_stay_armed_for_the_next_episode():
    """The deterrent persists: a SECOND attack (a fresh episode) is punished
    again by a body whose reaction never spent."""
    st = _state([_char("p"), _char("q")], [_enemy(f"e{i}") for i in range(3)],
                [_riposte(), _riposte(), _riposte()])
    st = _pass_all(_attack(st, "e0"))
    assert st.character("p").hp == 30 - 2
    # Step to q's main phase: q's attack is a new stack item — a new episode —
    # and an armed clone answers it (the firing clone's cooldown is irrelevant).
    for _ in range(20):
        a = next((a for a in legal_actions(st)
                  if a.kind == "attack" and a.actor_id == "q"
                  and a.target_id == "e1"), None)
        if a is not None:
            st = _pass_all(apply_action(st, a)[0])
            break
        step = next((x for x in legal_actions(st) if x.kind == "pass"), None) \
            or next((x for x in legal_actions(st) if x.kind == "end_turn"), None)
        assert step is not None, "no path to q's attack"
        st = apply_action(st, step)[0]
    assert st.character("q").hp == 30 - 2


def test_distinct_reactions_on_one_trigger_both_fire():
    """A riposte and a hex are different threats, not echoes — the episode rule
    only silences REPEATS of one signature."""
    st = _state([_char("p")], [_enemy("e0"), _enemy("e1")],
                [_riposte(), _hexlash()])
    st = _pass_all(_attack(st, "e0"))
    hero = st.character("p")
    assert hero.hp == 30 - 2                        # the riposte landed once
    assert hero.current_power < 3                   # and the hex landed too


def test_reaction_amounts_do_not_split_the_signature():
    """"Deal 2" and "deal 4" off the same trigger and shape are one threat in
    two costumes — still one answer per episode (the first in order)."""
    st = _state([_char("p")], [_enemy("e0"), _enemy("e1")],
                [_riposte(2), _riposte(4)])
    st = _pass_all(_attack(st, "e0"))
    assert st.character("p").hp == 30 - 2


def test_episodes_reset_at_turn_start():
    from ltg_combat.engine import _begin_turn
    st = _state([_char("p")], [_enemy("e0")], [_riposte()])
    st = _pass_all(_attack(st, "e0"))
    assert st.reacted_episode                       # the answered episode is recorded
    _begin_turn(st)
    assert st.reacted_episode == []                 # history at turn start
