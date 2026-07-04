"""Design Update 04 capstone — a framework-DEFINED enemy (chassis + keywords +
components, no legacy `intent`) loaded from JSON and driven through the engine.

Builds the §F-8 worked statblock "Ironhide Warleader" (a tanky fighter that heals
when hurt and punishes melee) and exercises its whole mind: the synthesized default
attack, the condition-gated Fortify, and the reactive on_hit Punish."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict

TARGET_ALLY = {"mode": "chosen", "side": "ally", "targeted": True}
SELF = {"mode": "self"}

IRONHIDE = {
    "name": "Ironhide Warleader", "hp": 10, "power": 3, "level": 5,
    "row": "front", "attack_mode": "melee", "keywords": ["trample"],
    "components": [
        {"id": "fortify", "archetype": "Fortify", "timing": "proactive",
         "priority": 10, "cooldown": 2, "target_rule": "self", "telegraph": "Second Wind",
         "condition": {"kind": "self_hp_pct", "op": "<", "value": 50},
         "verbs": [{"kind": "heal", "amount": 7, "target": SELF}]},
        {"id": "punish", "archetype": "Punish", "timing": "reactive",
         "trigger": "on_hit", "priority": 25, "cooldown": 2,
         "target_rule": "trigger_source", "telegraph": "Retaliate",
         "verbs": [{"kind": "deal_damage", "amount": 2, "target": TARGET_ALLY}]},
    ],
}


def _hero(power=6, hp=40):
    return {"id": "hero", "name": "Hero", "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": "front", "attack_mode": "melee", "library": []}


def _state():
    return state_from_dict({"party": [_hero()], "enemies": [IRONHIDE]})


def _act(st, **kw):
    a = next(a for a in legal_actions(st)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(st, a)


def _pass_all(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def _end_turn(st):
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    return st


# --- the framework object deserializes into a runnable enemy ----------------- #
def test_framework_enemy_loads():
    e = _state().enemies[0]
    assert e.max_hp == 10 and e.power == 3 and e.level == 5
    assert "trample" in e.keywords and e.is_boss is False
    assert {c.id for c in e.components} == {"fortify", "punish"}
    assert e.home_row == "front"
    # No legacy intent: the default attack was synthesized, targeted by valuation.
    assert e.intent_template["targeting"] == "valuation"
    assert e.intent_template["amount"] == 3


# --- healthy: it swings; the Fortify condition is false ---------------------- #
def test_healthy_declares_its_attack():
    assert settle(_state()).enemies[0].intent.name == "Ironhide Warleader Attack"


# --- reactive on_hit Punish + condition-gated Fortify when bloodied ---------- #
def test_punish_on_hit_then_fortify_when_bloodied():
    st = _state()
    eid = st.enemies[0].id
    st, _ = _act(st, kind="attack", target_id=eid)
    st = _pass_all(st)
    assert st.enemies[0].hp == 10 - 6              # the attack landed (10 -> 4)
    assert st.party[0].hp == 40 - 2               # Punish retaliated post-resolution

    st = _end_turn(st)                            # the enemy takes its turn; turn advances
    # Turn 2: at 4/10 (< 50%) the Fortify condition flips true and, at priority 10,
    # outranks the attack — the condition is the arbitration (§F-8).
    assert settle(st).enemies[0].intent.name == "Second Wind"
