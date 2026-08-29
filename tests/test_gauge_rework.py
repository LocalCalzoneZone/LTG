"""Gauge rework (2026-08-29): Mitigate credit, control denial credits, and the
level-scaled charge cost.

Three amendments to §D8-3.3, agreed in playtest review:

* Mitigate pays the guard +1 gauge per point of damage actually turned (capped
  at the blow), on top of the victim's usual +1/HP-lost — the hero who steps in
  is credited for the blow's full weight.
* Control is paid in the enemy's own numbers: a counter banks the damage the
  cancelled action would have dealt (source level when it dealt none); a stun
  pays as each intent is skipped; a strip pays the stripped intent's damage;
  destroy/exile/bounce/deathtouch and soft control (taunt, channel break) pay
  the target's level.
* The charge cost scales with level (100 + 20 per level past 1). Magnitude
  payouts stay raw points; tempo payouts (+2 action, +5 Skill, +25 ally down,
  authored charge/drain verbs) are percent of the cost. Clients see a 0-100
  percentage.
"""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.serialize import _character_dict
from ltg_core.schema import Card

CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}
CHOSEN_ALLY_T = {"mode": "chosen", "side": "ally", "targeted": True}


def _card(cid, effects, timing="sorcery", cost=None):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Spell", "timing": timing,
            "cost": cost or {"generic": 0, "colors": {}},
            "effects": effects, "validated": True}


def _char(cid, power=3, hp=30, level=1, row="front", library=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "level": level,
            "hand_size": len(library or []), "identity": ["U"], "row": row,
            "attack_mode": "melee", "library": library or []}


def _enemy(eid="e", hp=30, amount=2, level=3, power=None, components=None):
    e = {"id": eid, "name": eid, "hp": hp, "level": level,
         "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                    "intent_type": "attack", "targeting": "lowest_hp_party",
                    "mode": "melee"}}
    if power is not None:
        e["power"] = power
    if components is not None:
        e["components"] = components
    return e


def _state(party, enemies, tweak=None):
    st = state_from_dict({"party": party, "enemies": enemies})
    if tweak:
        tweak(st)
    return st


def _do(state, **kw):
    a = next(a for a in legal_actions(state)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(state, a)[0]


def _pass_all(state):
    while state.stack:
        p = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if p is None:
            break
        state = apply_action(state, p)[0]
    return state


def _drive_to_enemy_window(state):
    """Run to the first open reaction window in the enemy step."""
    while True:
        acts = legal_actions(state)
        if state.stack and any(a.kind == "pass" for a in acts):
            return state
        et = next((a for a in acts if a.kind == "end_turn"), None)
        state = apply_action(state, et if et is not None else acts[0])[0]


def _drive_until_logged(state, event_type, cap=200):
    """End turns / pass until `event_type` appears in the log."""
    for _ in range(cap):
        if any(ev.type == event_type for ev in state.log):
            return state
        acts = legal_actions(state)
        if not acts or state.result is not None:
            break
        a = next((x for x in acts if x.kind in ("end_turn", "pass")), acts[0])
        state = apply_action(state, a)[0]
    return state


def _rammer(amount=5, hp=30, eid="ram", level=2):
    comp = {"id": "ram", "timing": "proactive", "priority": 10,
            "target_rule": "valuation", "telegraph": "Battering Ram",
            "verbs": [{"kind": "deal_damage", "amount": amount,
                       "target": CHOSEN_ALLY_T}]}
    return {"id": eid, "name": eid, "hp": hp, "level": level, "power": 2,
            "attack_mode": "melee", "components": [comp]}


# --------------------------------------------------------------------------- #
# Mitigate: (mitigated) + (taken)
# --------------------------------------------------------------------------- #
def test_mitigate_credits_the_guard_for_damage_turned():
    # Power 6 → X = 3 against a 5-damage hit: +3 mitigated, +2 for the HP lost.
    st = _state([_char("p", power=6)], [_rammer(amount=5)])
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    p = st.character("p")
    assert p.hp == 28
    assert p.ultimate_gauge == 3 + 2


def test_mitigate_credit_is_capped_at_the_blow():
    # X = 3 raised against a 2-damage chip hit turns 2, never 3.
    st = _state([_char("p", power=6)], [_rammer(amount=2)])
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    p = st.character("p")
    assert p.hp == 30                       # fully absorbed
    assert p.ultimate_gauge == 2            # only what was actually turned


def test_ally_mitigate_credits_the_guard_not_the_protected():
    # The tank steps in front of the mage: mitigated share + the residual they
    # wear both pay the tank; the untouched mage earns nothing.
    st = _state([_char("tank", power=6, hp=30), _char("mage", power=1, hp=10)],
                [_rammer(amount=5, hp=4)])   # low HP → valuation picks the mage
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].target_id == "mage"
    st = _do(st, kind="mitigate", actor_id="tank", target_id="mage")
    st = _pass_all(st)
    tank, mage = st.character("tank"), st.character("mage")
    assert mage.hp == 10 and mage.ultimate_gauge == 0
    assert tank.hp == 28
    assert tank.ultimate_gauge == 3 + 2     # mitigated 3, wore the leaked 2


# --------------------------------------------------------------------------- #
# Control: paid in the enemy's own numbers
# --------------------------------------------------------------------------- #
_NEGATE = _card("negate", [{"kind": "counter", "filter": "spell",
                            "target": {"class": "action", "side": "enemy"}}],
                timing="instant")


def _spell_comp(verbs, telegraph):
    return {"id": "comp", "timing": "proactive", "priority": 10,
            "target_rule": "valuation", "action_type": "spell",
            "telegraph": telegraph, "verbs": verbs}


def test_counter_banks_the_denied_damage():
    fireball = _spell_comp([{"kind": "deal_damage", "amount": 4,
                             "target": CHOSEN_ALLY_T}], "Fireball — deal 4")
    st = _state([_char("p", library=[_NEGATE])],
                [_enemy(components=[fireball], level=3)])
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="cast", card_id="negate")
    st = _pass_all(st)
    assert any(ev.type == "countered" for ev in st.log)
    p = st.character("p")
    assert p.hp == 30                       # the Fireball never landed
    assert p.ultimate_gauge == 4            # reactive cast, 0 mana — denial only


def test_countering_a_non_damage_action_pays_the_source_level():
    curse = _spell_comp([{"kind": "wound", "power": 1, "toughness": 1,
                          "target": CHOSEN_ALLY_T}], "Curse — wound")
    st = _state([_char("p", library=[_NEGATE])],
                [_enemy(components=[curse], level=3)])
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="cast", card_id="negate")
    st = _pass_all(st)
    assert any(ev.type == "countered" for ev in st.log)
    assert st.character("p").ultimate_gauge == 3   # the enemy's level


def test_stun_pays_the_denied_turn_as_it_is_skipped():
    stun = _card("stunner", [{"kind": "stun", "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", hp=40, library=[stun])],
                [_enemy(amount=2, level=3, power=4)])
    st = _do(st, kind="cast", card_id="stunner")
    st = _pass_all(st)
    p = st.character("p")
    assert p.ultimate_gauge == 2            # the proactive action; no payout yet
    st = _drive_until_logged(st, "stunned")
    assert any(ev.type == "stunned" for ev in st.log)
    # +2 action, +2 for this round's hit taken, +4 (enemy Power) at the skip.
    assert st.character("p").ultimate_gauge == 2 + 2 + 4
    assert st.enemy("e").stunned_by is None  # spent with the last stack


def test_destroy_and_bounce_pay_the_removed_level():
    zap = _card("zap", [{"kind": "destroy", "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", library=[zap])], [_enemy(level=3, hp=30)])
    st = _do(st, kind="cast", card_id="zap")
    st = _pass_all(st)
    assert st.character("p").ultimate_gauge == 2 + 3   # action + level

    ebb = _card("ebb", [{"kind": "bounce", "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", library=[ebb])], [_enemy(level=4, hp=30)])
    st = _do(st, kind="cast", card_id="ebb")
    st = _pass_all(st)
    assert st.enemy("e").in_hand
    assert st.character("p").ultimate_gauge == 2 + 4


def test_strip_pays_the_stripped_intents_damage():
    unravel = _card("unravel", [{"kind": "strip_intent",
                                 "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", library=[unravel])], [_enemy(amount=4, level=2)])
    st = _do(st, kind="cast", card_id="unravel")
    st = _pass_all(st)
    assert st.enemy("e").round_intent_status == "stripped"
    assert st.character("p").ultimate_gauge == 2 + 4   # action + denied hit


def test_taunt_pays_the_targets_level():
    jeer = _card("jeer", [{"kind": "taunt", "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", library=[jeer])], [_enemy(level=3)])
    st = _do(st, kind="cast", card_id="jeer")
    st = _pass_all(st)
    assert st.enemy("e").taunted_by == "p"
    assert st.character("p").ultimate_gauge == 2 + 3


# --------------------------------------------------------------------------- #
# Level scaling: the cost grows, tempo payouts stay percent
# --------------------------------------------------------------------------- #
def test_charge_cost_and_pct_scale_with_level():
    st = _state([_char("a", level=1), _char("b", level=4)], [_enemy()])
    a, b = st.character("a"), st.character("b")
    assert a.ultimate_charge_cost == 100
    assert b.ultimate_charge_cost == 160
    b.ultimate_gauge = 80
    assert b.ultimate_gauge_pct == 50


def test_tempo_payouts_are_percent_of_the_cost():
    # Level 3 → cost 140. Defend: +2% action (round(2.8) = 3) + Power temp HP
    # (raw points — magnitude payouts deliberately dilute with level).
    st = _state([_char("p", power=3, level=3)], [_enemy()])
    st = _do(st, kind="defend")
    assert st.character("p").ultimate_gauge == 3 + 3


def test_ultimate_gates_on_the_scaled_cost():
    ult = _card("doom", [{"kind": "deal_damage", "amount": 9,
                          "target": CHOSEN_ENEMY_T}])

    def wire(gauge):
        def fn(s):
            p = s.character("p")
            p.ultimate = Card.model_validate(ult)
            p.ultimate_gauge = gauge
        return fn

    st = _state([_char("p", level=2)], [_enemy()], tweak=wire(119))
    assert not any(a.kind == "use_ultimate" for a in legal_actions(st))
    st = _state([_char("p", level=2)], [_enemy()], tweak=wire(120))
    assert any(a.kind == "use_ultimate" for a in legal_actions(st))
    st = _do(st, kind="use_ultimate")
    assert st.character("p").ultimate_gauge == 0


def test_serializer_reports_the_gauge_as_a_percentage():
    st = _state([_char("p", level=2)], [_enemy()])
    st.character("p").ultimate_gauge = 60           # of a 120-point cost
    assert _character_dict(st, st.character("p"))["ultimate_gauge"] == 50


def test_charge_and_drain_verbs_are_percent_denominated():
    surge = _card("surge", [{"kind": "modify_action", "action": "ultimate",
                             "modifier": "charge_ultimate", "amount": 30,
                             "target": {"mode": "self"}}], timing="instant")
    st = _state([_char("p", level=3, library=[surge])], [_enemy()])
    st = _do(st, kind="cast", card_id="surge")
    st = _pass_all(st)
    # 30% of a 140-point bar → 42 raw points (instant: no proactive credit).
    assert st.character("p").ultimate_gauge == 42

    sap = _card("sap_ult", [{"kind": "modify_action", "action": "ultimate",
                             "modifier": "drain_ultimate", "amount": 50,
                             "target": {"mode": "self"}}], timing="instant")
    st = _state([_char("p", level=3, library=[sap])], [_enemy()])
    st.character("p").ultimate_gauge = 140
    st = _do(st, kind="cast", card_id="sap_ult")
    st = _pass_all(st)
    assert st.character("p").ultimate_gauge == 140 - 70   # 50% of the bar
