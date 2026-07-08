"""The new event-reactive triggers: on_self_below_N (a minion-grade enrage
moment), on_hero_downed (the pack surges), and on_hero_healed (punish the
medic)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _char(cid, power=3, hp=30, hand=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power,
            "hand_size": len(hand or []), "identity": ["U"], "row": "front",
            "attack_mode": "melee", "library": hand or []}


def _enemy(eid, components=None, hp=10, amount=2, targeting="lowest_hp_party"):
    return {"id": eid, "name": eid, "hp": hp, "level": 3,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": targeting,
                       "mode": "melee"},
            "components": components or []}


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


def _run_turn(st):
    """End the player's turn and pass every window until the next turn starts."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        a = next((x for x in acts if x.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, a)[0]
    return st


_SURGE = {"kind": "counters", "power": 2, "toughness": 0, "target": {"mode": "self"}}


def _bloodied(pct=50):
    return {"id": "bloodied", "archetype": "Escalate", "timing": "reactive",
            "trigger": f"on_self_below_{pct}", "once_per_encounter": True,
            "priority": 12, "target_rule": "self",
            "telegraph": "Bloodied Roar", "verbs": [dict(_SURGE)]}


def test_on_self_below_fires_on_the_crossing_hit():
    st = state_from_dict({"party": [_char("p", power=6)],
                          "enemies": [_enemy("boar", [_bloodied(50)], hp=10)]})
    st, _ = _act(st, kind="attack", target_id="boar")   # 10 -> 4: below 50%
    st = _pass_all(st)
    boar = st.enemy("boar")
    assert boar.power == 2 + 2 and boar.counters == 2   # the roar landed
    assert any(ev.type == "enemy_react" for ev in st.log)


def test_on_self_below_does_not_fire_above_threshold():
    st = state_from_dict({"party": [_char("p", power=2)],
                          "enemies": [_enemy("boar", [_bloodied(50)], hp=10)]})
    st, _ = _act(st, kind="attack", target_id="boar")   # 10 -> 8: still healthy
    st = _pass_all(st)
    assert st.enemy("boar").counters == 0


def test_on_hero_downed_surge():
    # The enemy's own swing downs the weak hero; the packmate surges in the
    # post-resolution window of the ENEMY step.
    surger = {"id": "surge", "archetype": "Escalate", "timing": "reactive",
              "trigger": "on_hero_downed", "once_per_encounter": True,
              "priority": 12, "target_rule": "self",
              "telegraph": "Blood Frenzy", "verbs": [dict(_SURGE)]}
    st = state_from_dict({"party": [_char("a", hp=30), _char("b", hp=2, power=1)],
                          "enemies": [_enemy("wolf", amount=3),
                                      _enemy("packmate", [surger], amount=0)]})
    st = _run_turn(st)                                   # the wolf downs b
    assert not st.character("b").alive
    assert st.enemy("packmate").counters == 2            # the pack surged


def test_on_hero_healed_punishes_the_medic():
    mend = {"id": "mend", "name": "Mend", "source_name": "Mend",
            "rarity": "common", "level": 1, "type": "Instant",
            "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "heal", "amount": 3,
                         "target": {"mode": "chosen", "side": "ally",
                                    "targeted": True}}],
            "validated": True}
    spite = {"id": "spite", "archetype": "Punish", "timing": "reactive",
             "trigger": "on_hero_healed", "cooldown": 2, "priority": 20,
             "target_rule": "trigger_source", "telegraph": "Spiteful Lash",
             "verbs": [{"kind": "deal_damage", "amount": 2,
                        "target": {"mode": "chosen", "side": "ally",
                                   "targeted": True}}]}
    st = state_from_dict({"party": [_char("p", hand=[mend])],
                          "enemies": [_enemy("witch", [spite], amount=0)]})
    st.party[0].hp = 10                                  # wounded: the heal is real
    st, _ = _act(st, kind="cast", card_id="mend", target_id="p")
    st = _pass_all(st)
    assert st.party[0].hp == 10 + 3 - 2                  # healed, then lashed
    assert any(ev.type == "enemy_react" for ev in st.log)
