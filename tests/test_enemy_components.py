"""Design Update 04 §F-3/§F-7 — the enemy "mind": components merged into one
priority list, evaluated first-match-wins with condition and cooldown gates.

No loader ingest yet (that's §F-8/§F-1 build), so these attach `Component`s to a
runtime enemy directly and drive through the engine's two-function contract."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import DealDamage, Heal, t_chosen, t_self


def _char(cid, power=3, hp=30):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": "front", "attack_mode": "melee", "library": []}


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


def _declared_intent_name(st):
    """The enemy's intent as the engine would present it at the first decision point."""
    return settle(st).enemies[0].intent.name


def _fortify(cd=2, prio=10):
    return Component(id="fortify", archetype="Fortify", priority=prio, cooldown=cd,
                     condition={"kind": "self_hp_pct", "op": "<", "value": 50},
                     verbs=[Heal(amount=5, target=t_self())], target_rule="self",
                     telegraph="Blood Ritual")


def _drain(cd=2, prio=30):
    return Component(id="drain", archetype="Drain", priority=prio, cooldown=cd,
                     verbs=[DealDamage(amount=3, target=t_chosen("ally", targeted=True)),
                            Heal(amount=3, target=t_self())],
                     target_rule="valuation", telegraph="Life Drain")


def _drive(st, kinds=("end_turn", "pass")):
    """Take the lowest-commitment action available (end a turn, else pass, else the
    first offered) until the turn advances or the game ends."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        act = next((a for a in acts if a.kind in kinds), acts[0])
        st = apply_action(st, act)[0]
    return st


# --- condition gate ---------------------------------------------------------- #
def test_condition_false_falls_through_to_default_attack():
    # Healthy: self_hp < 50% is false, so Fortify is skipped and the terminal Attack
    # (priority 90) declares instead.
    st = _state([_char("p")], [_enemy("e", hp=10)],
                tweak=lambda s: s.enemies[0].components.append(_fortify()))
    assert _declared_intent_name(st) == "Hit"


def test_condition_true_wins_over_default_attack():
    # Bloodied (4/10 = 40%): Fortify's condition flips true and, at priority 10, it
    # outranks the default attack — the condition *is* the arbitration (§F-8 Ironhide).
    def bloody(s):
        s.enemies[0].hp = 4
        s.enemies[0].components.append(_fortify())
    st = _state([_char("p")], [_enemy("e", hp=10)], tweak=bloody)
    assert _declared_intent_name(st) == "Blood Ritual"


# --- multi-verb resolution (Drain: damage a player + heal self) -------------- #
def test_drain_component_damages_player_and_heals_self():
    def setup(s):
        s.enemies[0].hp = 5                       # room to heal
        s.enemies[0].components.append(_drain())
    st = _state([_char("p", hp=20)], [_enemy("e", hp=10)], tweak=setup)
    assert _declared_intent_name(st) == "Life Drain"
    st = _drive(st)                               # play the turn out; Drain resolves
    assert st.party[0].hp == 20 - 3               # the player took the drain
    assert st.enemies[0].hp == 5 + 3              # the enemy healed itself


# --- cooldown --------------------------------------------------------------- #
def test_cooldown_blocks_refire_then_recovers():
    def setup(s):
        s.enemies[0].hp = 5
        s.enemies[0].components.append(_drain(cd=2))
    st = _state([_char("p", hp=40)], [_enemy("e", hp=10)], tweak=setup)

    assert _declared_intent_name(st) == "Life Drain"      # turn 1: fires
    st = _drive(st)                                        # -> executes, cooldown set to turn 3
    assert st.turn == 2
    assert _declared_intent_name(st) == "Hit"             # turn 2: on cooldown -> default attack
    st = _drive(st)
    assert st.turn == 3
    assert _declared_intent_name(st) == "Life Drain"      # turn 3: available again


# --- movement (§F-7.3): an Evasive rule declares a Move, resolved at End step -- #
def _evasive(prio=20):
    return Component(id="evasive", archetype="Evasive", priority=prio,
                     move_home=True, target_rule="self", telegraph="Reposition")


def test_evasive_repositions_to_home_row_at_end_step():
    def setup(s):
        e = s.enemies[0]
        e.row = e.committed = "front"     # shoved up front
        e.home_row = "mid"                # wants to be at mid
        e.components.append(_evasive())
    st = _state([_char("p")], [_enemy("e")], tweak=setup)
    assert _declared_intent_name(st) == "Reposition"   # the Move outranks the attack
    st = _drive(st)                                     # execute + play to End step
    assert st.enemies[0].row == "mid"                  # the body caught up to the queued Move


def test_evasive_skips_when_already_home():
    # Already at home: the repositioning rule produces no Move, so it is skipped and the
    # default attack declares instead (first-match-wins keeps scanning).
    def setup(s):
        e = s.enemies[0]
        e.row = e.committed = e.home_row = "mid"
        e.components.append(_evasive())
    st = _state([_char("p")], [_enemy("e")], tweak=setup)
    assert _declared_intent_name(st) == "Hit"
