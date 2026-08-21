"""§M-A.7 — Combat Abilities: an ability-class action that DEALS DAMAGE is a swing
by another name. Derived from the verbs, never authored, it puts the hit in the
COMBAT-damage lane, trips on-attack triggers, and — when the damage is aimed at one
named victim — lets Mitigate answer it. Its non-damage RIDERS follow the residual
damage: blunted to nothing, they never land; taken by a guard, they land on the guard.

Non-damaging abilities, spell-classed components, and AoE/splash payloads are all
deliberately untouched.
"""

from __future__ import annotations

from ltg_combat.engine import (_is_combat_ability, _mitigable, apply_action,
                               legal_actions)
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import StackItem


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", power=2, hp=30, attack_mode="melee", keywords=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 1,
            "identity": ["U"], "row": row, "attack_mode": attack_mode,
            "keywords": keywords or [],
            "library": [_filler(cid + "_a"), _filler(cid + "_b")]}


def _chosen(side="ally"):
    return {"mode": "chosen", "side": side, "targeted": True}


def _rammer(eid="ram", verbs=None, action_type=None, amount=5, hp=30):
    """The complaint case: "Battering Ram — deal 5" authored as a plain ability,
    with no `action_type` opting it into anything."""
    comp = {"id": "ram", "timing": "proactive", "priority": 10,
            "target_rule": "valuation", "telegraph": "Battering Ram",
            "verbs": verbs if verbs is not None
            else [{"kind": "deal_damage", "amount": amount, "target": _chosen()}]}
    if action_type is not None:
        comp["action_type"] = action_type
    return {"id": eid, "name": eid, "hp": hp, "level": 2, "power": 2,
            "attack_mode": "melee", "components": [comp]}


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


def _do(state, **kw):
    a = next(a for a in legal_actions(state)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(state, a)[0]


def _has(state, **kw):
    return any(all(getattr(a, k) == v for k, v in kw.items())
               for a in legal_actions(state))


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


# --------------------------------------------------------------------------- #
# The derivation itself
# --------------------------------------------------------------------------- #
def test_a_damaging_ability_is_derived_as_a_combat_ability():
    """The complaint case, end to end: nothing in the authoring opts in — the
    engine reads the verbs and classifies the swing itself."""
    st = _state([_char("p")], [_rammer(amount=5)])
    st = _drive_to_enemy_window(st)
    top = st.stack[-1]
    assert top.kind == "ability" and top.combat_ability


def test_a_non_damaging_ability_is_left_alone():
    stun = [{"kind": "stun", "target": _chosen()}]
    st = _state([_char("p")], [_rammer(verbs=stun)])
    st = _drive_to_enemy_window(st)
    assert not st.stack[-1].combat_ability


def test_a_spell_classed_component_stays_a_spell():
    """Authoring something as arcane is a deliberate choice — Negate is its answer,
    not a raised shield. The derivation never overrides it."""
    st = _state([_char("p")], [_rammer(action_type="spell")])
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].kind == "spell"
    assert not st.stack[-1].combat_ability


def test_damage_wrapped_in_a_conditional_still_counts():
    """Laundering the hit through a container verb must not dodge the rule."""
    wrapped = [{"kind": "conditional",
                "condition": {"kind": "self_hp", "op": ">", "value": 0},
                "effects": [{"kind": "deal_damage", "amount": 4,
                             "target": _chosen()}]}]
    assert _is_combat_ability("ability", _state(
        [_char("p")], [_rammer(verbs=wrapped)]).enemies[0].components[0].verbs)


# --------------------------------------------------------------------------- #
# Mitigate answers it
# --------------------------------------------------------------------------- #
def test_a_damaging_ability_can_be_mitigated():
    st = _state([_char("p", power=2, hp=20)], [_rammer(amount=5)])   # X = 1
    st = _drive_to_enemy_window(st)
    assert _mitigable(st.stack[-1])
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    assert st.character("p").hp == 16                                # 5 − 1 = 4


def test_a_non_damaging_ability_offers_no_mitigate():
    stun = [{"kind": "stun", "target": _chosen()}]
    st = _state([_char("p", power=2, hp=20)], [_rammer(verbs=stun)])
    st = _drive_to_enemy_window(st)
    assert not _mitigable(st.stack[-1])
    assert not _has(st, kind="mitigate")


def test_an_aoe_ability_stays_unmitigable():
    """A party-wide blast is deliberately beyond one raised guard (design call:
    that level of splash is not something one character steps in front of)."""
    blast = [{"kind": "deal_damage", "amount": 4,
              "target": {"mode": "all", "side": "ally"}}]
    st = _state([_char("p", power=2, hp=20), _char("q", power=2, hp=20)],
                [_rammer(verbs=blast)])
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].combat_ability          # still combat damage…
    assert not _mitigable(st.stack[-1])         # …but no one guard covers it
    assert not _has(st, kind="mitigate")


def test_an_ally_can_step_in_front_of_a_damaging_ability():
    st = _state([_char("tank", row="front", power=2, hp=30),
                 _char("mage", row="front", power=1, hp=10)],
                [_rammer(amount=5, hp=4)])      # low HP → valuation picks the mage
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].target_id == "mage"     # valuation picks the squishy one
    st = _do(st, kind="mitigate", actor_id="tank", target_id="mage")
    st = _pass_all(st)
    assert st.character("mage").hp == 10         # the mage is untouched…
    assert st.character("tank").hp == 26         # …the tank wears 5 − 1 = 4


# --------------------------------------------------------------------------- #
# Riders follow the residual damage (§M-A.7)
# --------------------------------------------------------------------------- #
def _stunner(amount=5):
    return _rammer(verbs=[{"kind": "deal_damage", "amount": amount, "target": _chosen()},
                          {"kind": "stun", "target": _chosen()}])


def test_a_rider_lands_when_damage_leaks_through():
    st = _state([_char("p", power=2, hp=20)], [_stunner(amount=5)])   # X = 1
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    assert st.character("p").hp == 16
    assert st.character("p").stunned > 0                             # 4 leaked → stun lands


def test_a_rider_is_blocked_when_the_guard_eats_the_hit_whole():
    """Mitigate X (⌈Power/2⌉) at or above the damage zeroes it — and the rider
    goes with it. Guarding fully is now worth more than a partial refund."""
    st = _state([_char("p", power=6, hp=20)], [_stunner(amount=3)])   # X = 3 ≥ 3
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    assert st.character("p").hp == 20
    assert st.character("p").stunned == 0
    assert any(ev.type == "rider_blocked" for ev in st.log)


def test_a_rider_follows_the_damage_onto_the_guard():
    """The tactically rich case: step in front of "deal 5 and stun" for an ally and
    you eat the leftover damage AND the stun. Interposing is a real decision."""
    st = _state([_char("tank", row="front", power=2, hp=30),
                 _char("mage", row="front", power=1, hp=10)],
                [_stunner(amount=5)])
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].target_id == "mage"
    st = _do(st, kind="mitigate", actor_id="tank", target_id="mage")
    st = _pass_all(st)
    assert st.character("mage").hp == 10
    assert st.character("mage").stunned == 0     # the mage is clean…
    assert st.character("tank").hp == 26
    assert st.character("tank").stunned > 0      # …the tank wears damage AND stun
    assert any(ev.type == "rider_follows" for ev in st.log)


def test_the_mitigation_outcome_survives_a_mid_resolution_pause():
    """The rider rule reads a record that must outlive an interactive pause: "deal 5
    and discard a card" stops for the player's pick, and the resume rebuilds the
    resolution context from scratch. The record rides the STACK ITEM for exactly
    this reason — on the context it would be lost, and the rider would snap back
    onto the character the guard stepped in front of."""
    discarder = _rammer(verbs=[{"kind": "deal_damage", "amount": 3,
                                "target": _chosen()},
                               {"kind": "move_card", "count": 1, "source": "hand",
                                "destination": "graveyard", "target": _chosen()}])
    st = _state([_char("p", power=6, hp=20)], [discarder])       # X = 3 ≥ 3
    st = _drive_to_enemy_window(st)
    before = len(st.character("p").hand)
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    assert st.character("p").hp == 20                            # swallowed whole…
    assert st.pending_choice is None                             # …so no pick was raised
    assert len(st.character("p").hand) == before                 # …and no card was lost


def test_a_card_logistics_rider_follows_the_guard_across_the_pause():
    """The same rider, but leaking damage and guarded by an ally: the discard must
    land on the GUARD. move_card resolves through its own interactive path, so this
    pins that the rule lives at a chokepoint both paths share."""
    discarder = _rammer(verbs=[{"kind": "deal_damage", "amount": 5,
                                "target": _chosen()},
                               {"kind": "move_card", "count": 1, "source": "hand",
                                "destination": "graveyard", "target": _chosen()}])
    st = _state([_char("tank", row="front", power=2, hp=30),
                 _char("mage", row="front", power=1, hp=10)], [discarder])
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].target_id == "mage"
    st = _do(st, kind="mitigate", actor_id="tank", target_id="mage")
    st = _pass_all(st)
    assert st.character("tank").hp == 26                          # 5 − 1 leaked onto them
    pc = st.pending_choice
    assert pc is not None and pc.chooser_id == "tank"             # the guard discards


def test_riders_resolve_after_damage_even_when_authored_first():
    """The rider rule reads what the damage did, so a "stun, then deal 5" list is
    resolved damage-first under a declared Mitigate. Authored order is otherwise
    untouched."""
    swapped = _rammer(verbs=[{"kind": "stun", "target": _chosen()},
                             {"kind": "deal_damage", "amount": 3,
                              "target": _chosen()}])
    st = _state([_char("p", power=6, hp=20)], [swapped])             # X = 3 ≥ 3
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    st = _pass_all(st)
    assert st.character("p").hp == 20
    assert st.character("p").stunned == 0        # the swallowed hit took the stun with it


# --------------------------------------------------------------------------- #
# The combat-damage lane
# --------------------------------------------------------------------------- #
def _shield_card(cid="fog", parameter="combat_damage"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "prevent", "parameter": parameter, "uses": "next",
                         "target": {"mode": "self"}}]}


def _punisher(eid="thorn", amount=4):
    """A reactive punish — "Flare-Snap: deal 4 to the attacker". It stacks as a
    TRIGGERED ability, which used to put its damage in the SPELL lane."""
    return {"id": eid, "name": eid, "hp": 30, "level": 2, "power": 1,
            "attack_mode": "melee",
            "components": [{"id": "snap", "timing": "reactive", "trigger": "on_hit",
                            "priority": 10, "target_rule": "trigger_source",
                            "telegraph": "Flare-Snap",
                            "verbs": [{"kind": "deal_damage", "amount": amount,
                                       "target": _chosen()}]}]}


def test_a_reactive_punish_lands_in_the_combat_damage_lane():
    """A triggered damage component is physical, not arcane: a combat_damage
    shield must cover it. Before §M-A.7 it slipped through into the spell lane."""
    party = [_char("p", power=3, hp=20)]
    party[0]["library"] = [_shield_card("fog"), _filler("p_b")]
    party[0]["hand_size"] = 2
    st = _state(party, [_punisher(amount=4)])
    st = _do(st, kind="cast", card_id="fog")     # raise the shield
    st = _pass_all(st)
    st = _do(st, kind="attack", target_id="thorn")
    st = _pass_all(st)
    assert st.character("p").hp == 20            # the punish is covered
    assert any(ev.type == "prevented" for ev in st.log)


def test_a_damaging_ability_still_reads_as_combat_damage():
    party = [_char("p", power=2, hp=20)]
    party[0]["library"] = [_shield_card("fog"), _filler("p_b")]
    party[0]["hand_size"] = 2
    st = _state(party, [_rammer(amount=5)])
    st = _do(st, kind="cast", card_id="fog")
    st = _pass_all(st)
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("p").hp == 20


# --------------------------------------------------------------------------- #
# On-attack triggers
# --------------------------------------------------------------------------- #
def test_a_heros_damaging_ability_opens_an_on_attack_punish_window():
    """Symmetry: if a damaging ability can be answered like a swing, it can be
    punished like one. A hero's damaging consumable trips `on_attack`."""
    bomb = {"id": "bomb", "name": "bomb", "source_name": "bomb", "rarity": "common",
            "level": 1, "type": "Item", "timing": "instant", "consumable_id": "bomb",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "deal_damage", "amount": 2,
                         "target": _chosen("enemy")}]}
    party = [_char("p", power=2, hp=20)]
    party[0]["library"] = [bomb, _filler("p_b")]
    party[0]["hand_size"] = 2
    duellist = {"id": "duel", "name": "duel", "hp": 30, "level": 2, "power": 2,
                "attack_mode": "melee",
                "components": [{"id": "riposte", "timing": "reactive",
                                "trigger": "on_attack", "priority": 10,
                                "target_rule": "trigger_source",
                                "telegraph": "Riposte",
                                "verbs": [{"kind": "deal_damage", "amount": 3,
                                           "target": _chosen()}]}]}
    st = _state(party, [duellist])
    st = _do(st, kind="cast", card_id="bomb", target_id="duel")
    st = _do(st, kind="pass")            # the party passes → the enemy side answers
    assert any(ev.type == "enemy_react" for ev in st.log)
