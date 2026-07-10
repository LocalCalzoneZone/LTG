"""Enemy COUNTERSPELLS: a reactive Counter component answers the party's stack.

The component's `counter` verb takes no target — `_fire_reaction` aims it at the
stack action that tripped the trigger (the "#uid" handle a player's counter uses).
It fires pre-resolution (on_spell_cast / on_attack), sits ON the stack itself
(so the party could answer it in turn), and `_r_counter` now cancels across
either side — you can never counter your own side's action.
"""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _card(cid, name, effects, timing="instant", cost=None):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": 1, "type": "Instant" if timing == "instant" else "Sorcery",
            "timing": timing, "cost": cost or {"generic": 0, "colors": {"U": 1}},
            "effects": effects, "validated": True}


_ZAP = _card("zap", "Zap", [{"kind": "deal_damage", "amount": 2,
                             "target": {"mode": "chosen", "side": "enemy",
                                        "targeted": True}}],
             cost={"generic": 0, "colors": {}})  # free: two casts a turn in tests


def _counter_comp(trigger="on_spell_cast", filt="spell", cd=3):
    return {"id": "hush", "archetype": "Counter", "timing": "reactive",
            "trigger": trigger, "cooldown": cd, "priority": 15,
            "action_type": "spell", "target_rule": "trigger_source",
            "telegraph": "Hushing Mist — counter",
            "verbs": [{"kind": "counter", "filter": filt}]}


def _state(components, hand=None):
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 3,
                   "hand_size": len(hand or []), "identity": ["U"], "row": "front",
                   "attack_mode": "melee", "library": hand or []}],
        "enemies": [{"id": "mage", "name": "Mage", "hp": 12, "level": 3,
                     "intent": {"name": "Bash", "amount": 0, "action_type": "ability",
                                "intent_type": "attack",
                                "targeting": "lowest_hp_party", "mode": "melee"},
                     "components": components}],
    })


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


def test_enemy_counters_a_player_spell():
    st = _state([_counter_comp()], hand=[dict(_ZAP)])
    st, _ = _act(st, kind="cast", card_id="zap", target_id="mage")
    st, log = _act(st, kind="pass")               # all pass -> the sentinel answers
    assert [i.label for i in st.stack][0] == "Zap"
    assert st.stack[-1].source_side == "enemy"    # the counter sits on top
    assert st.stack[-1].target_id == f"#{st.stack[0].uid}"
    st = _pass_all(st)
    assert st.enemies[0].hp == 12                 # Zap never resolved
    assert any(ev.type == "countered" for ev in st.log)


def test_counter_spell_filter_ignores_attacks():
    st = _state([_counter_comp()])                # on_spell_cast never sees an attack
    st, _ = _act(st, kind="attack", target_id="mage")
    st = _pass_all(st)
    assert st.enemies[0].hp == 12 - 3             # the swing landed, uncountered


def test_enemy_parries_an_attack_with_on_attack_counter():
    st = _state([_counter_comp(trigger="on_attack", filt="attack")])
    st, _ = _act(st, kind="attack", target_id="mage")
    st = _pass_all(st)
    assert st.enemies[0].hp == 12                 # the parry cancelled the swing
    assert any(ev.type == "countered" for ev in st.log)


def test_counter_consumes_cooldown_and_window_slot():
    st = _state([_counter_comp()], hand=[dict(_ZAP), dict(_ZAP)])
    st, _ = _act(st, kind="cast", card_id="zap", target_id="mage")
    st = _pass_all(st)
    assert st.enemies[0].hp == 12                 # first cast countered
    # The same turn, the second copy resolves — the sentinel is on cooldown.
    dup = next(a for a in legal_actions(st) if a.kind == "cast")
    st = apply_action(st, dup)[0]
    st = _pass_all(st)
    assert st.enemies[0].hp == 10                 # Zap #2 landed
