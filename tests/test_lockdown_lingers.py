"""Roadmap M1.25 (ruled 2026-09-25): enemies act after the party, so an
enemy's "this turn" lockdown on a hero used to lapse at the End Step before
the hero ever acted under it. Now it holds THROUGH THE HERO'S NEXT TURN:
Silence / Pacify, wounds, sap, hostile action modifiers and a taunt. And a
hero's Pacify / Silence on an enemy cuts short the intent it declared."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict

CHOSEN_HERO = {"mode": "chosen", "side": "ally", "targeted": True}


def _bolt(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "deal_damage", "amount": 1,
                         "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]}


def _hero(hid="p", hp=40, power=4):
    return {"id": hid, "name": hid, "hp": hp, "power": power, "hand_size": 3,
            "identity": ["U"], "row": "front", "attack_mode": "melee",
            "library": [_bolt(f"{hid}{i}") for i in range(8)]}


def _locker(verbs, eid="hexer"):
    return {"id": eid, "name": eid, "hp": 60, "level": 3, "power": 1,
            "attack_mode": "melee",
            "components": [{"id": "lock", "archetype": "Debilitate", "timing": "proactive",
                            "priority": 10, "once_per_encounter": True,
                            "target_rule": "valuation", "telegraph": "Hex",
                            "verbs": verbs}]}


def _to_round(st, n):
    """Run turns (ending them) until round `n`'s player phase is open."""
    for _ in range(400):
        acts = legal_actions(st)
        if st.turn >= n and any(a.kind == "end_turn" for a in acts) and not st.stack:
            return st
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    raise AssertionError("never reached")


def _end_turn(st, hid="p"):
    return apply_action(st, next(a for a in legal_actions(st)
                                 if a.kind == "end_turn" and a.actor_id == hid))[0]


def test_an_enemy_silence_holds_through_the_heros_next_turn():
    st = state_from_dict({"party": [_hero()], "enemies": [_locker([
        {"kind": "prevent", "parameter": "cast", "target": CHOSEN_HERO}])]})
    st = _to_round(st, 2)                           # the Hex landed in round 1
    assert not [a for a in legal_actions(st) if a.kind == "cast"]   # still silenced
    st = _end_turn(st)
    assert not any(t.parameter == "cast" for t in st.character("p").prevent_tags)
    assert any(ev.type == "lockdown_lapses" for ev in st.log)


def test_an_enemy_wound_and_sap_hold_through_the_heros_next_turn():
    st = state_from_dict({"party": [_hero(power=4)], "enemies": [_locker([
        {"kind": "wound", "power": 2, "toughness": 0, "target": CHOSEN_HERO},
        {"kind": "sap", "amount": 1, "target": CHOSEN_HERO}])]})
    st = _to_round(st, 2)
    p = st.character("p")
    assert p.current_power == 2 and p.capacity_mod == -1   # both still bite
    st = _end_turn(st)
    p = st.character("p")
    assert p.current_power == 4 and p.capacity_mod == 0


def test_an_enemy_taunt_holds_through_the_heros_next_turn():
    st = state_from_dict({"party": [_hero()], "enemies": [
        _locker([{"kind": "taunt", "target": CHOSEN_HERO}]),
        {"id": "other", "name": "other", "hp": 60, "level": 1, "power": 1}]})
    st = _to_round(st, 2)
    assert st.character("p").taunted_to == "hexer"
    swings = {a.target_id for a in legal_actions(st) if a.kind == "attack"}
    assert swings == {"hexer"}
    st = _end_turn(st)
    assert st.character("p").taunted_to is None


def test_a_heros_pacify_cancels_the_enemys_declared_attack():
    pacify = {"id": "calm", "name": "calm", "source_name": "calm", "rarity": "common",
              "level": 1, "type": "Instant", "timing": "instant",
              "cost": {"generic": 0, "colors": {}},
              "effects": [{"kind": "prevent", "parameter": "attack", "uses": "next",
                           "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]}
    hero = _hero()
    hero["library"] = [pacify] + hero["library"]
    brute = {"id": "brute", "name": "brute", "hp": 30, "level": 2, "power": 2,
             "attack_mode": "melee",
             "intent": {"name": "Smash", "amount": 3, "action_type": "attack",
                        "intent_type": "attack", "targeting": "lowest_hp_party",
                        "mode": "melee"}}
    st = state_from_dict({"party": [hero], "enemies": [brute]})
    st = settle(_to_round(st, 1))
    assert st.enemy("brute").intent is not None
    st = apply_action(st, next(a for a in legal_actions(st)
                               if a.kind == "cast" and a.card_id == "calm"))[0]
    while st.stack:
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    assert st.enemy("brute").intent is None               # the swing is cut short
    assert not st.enemy("brute").prevent_tags             # the one-shot was spent on it
