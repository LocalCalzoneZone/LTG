"""Party turn order & priority (Update 06 rulings):

1. Turn order is a fixed initiative — randomized once at setup when the scenario
   is seeded (else the authored order) — and NEVER reshuffles when characters
   reposition mid-fight.
2. Window priority starts with the CASTER of the action on top (they hit Pass
   first), then moves through the other players in turn order. Enemy-sourced
   tops seed at the top of the turn order.
"""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _card(cid, effects):
    return {"id": cid, "name": cid.title(), "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "effects": effects,
            "validated": True}


_ZAP = _card("zap", [{"kind": "deal_damage", "amount": 1,
                      "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])
_JOLT = _card("jolt", [{"kind": "deal_damage", "amount": 1,
                        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])


def _char(cid, row="front", hand=None):
    return {"id": cid, "name": cid.title(), "hp": 20, "power": 2,
            "hand_size": len(hand or []), "identity": ["U"], "row": row,
            "attack_mode": "melee", "library": hand or []}


def _spec(party):
    return {"party": party,
            "enemies": [{"id": "orc", "name": "Orc", "hp": 30, "level": 1,
                         "intent": {"name": "Hit", "amount": 0,
                                    "action_type": "ability", "intent_type": "attack",
                                    "targeting": "lowest_hp_party", "mode": "melee"}}]}


def _pick(st, **kw):
    return next(a for a in legal_actions(st)
                if all(getattr(a, k) == v for k, v in kw.items()))


# --------------------------------------------------------------------------- #
# 1. Fixed initiative
# --------------------------------------------------------------------------- #
def test_seeded_setup_randomizes_the_turn_order():
    party = [_char("a"), _char("b"), _char("c")]
    orders = {tuple(state_from_dict(_spec(party), seed=s).party_order)
              for s in range(12)}
    assert all(sorted(o) == ["a", "b", "c"] for o in orders)  # a permutation
    assert len(orders) > 1                                    # and actually varies


def test_unseeded_setup_keeps_the_authored_order():
    st = state_from_dict(_spec([_char("b"), _char("a")]))
    assert st.party_order == ["b", "a"]


def test_turn_order_survives_repositioning():
    # "a" opens (authored order) even from the rear; moving rows never reshuffles.
    st = state_from_dict(_spec([_char("a", row="rear"), _char("b", row="front")]))
    assert _pick(st, kind="end_turn").actor_id == "a"     # a's main phase first
    st, _ = apply_action(st, _pick(st, kind="move", actor_id="a", target_id="front"))
    while st.stack:  # the Move is a stack action now (§L-2.2): pass it through
        st, _ = apply_action(st, _pick(st, kind="pass"))
    st, _ = apply_action(st, _pick(st, kind="end_turn", actor_id="a"))
    assert _pick(st, kind="end_turn").actor_id == "b"     # then b, as rolled
    # Turn 2: same order again, despite a's new row.
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        a = next((x for x in acts if x.kind in ("end_turn", "pass")), acts[0])
        st, _ = apply_action(st, a)
    assert _pick(st, kind="end_turn").actor_id == "a"


def test_turn_order_is_announced_in_the_log():
    st = state_from_dict(_spec([_char("a"), _char("b")]))
    st, _ = apply_action(st, _pick(st, kind="end_turn", actor_id="a"))
    ev = next(e for e in st.log if e.type == "turn_order")
    assert ev.data["order"] == ["a", "b"]


# --------------------------------------------------------------------------- #
# 2. Caster-first priority
# --------------------------------------------------------------------------- #
def test_caster_gets_priority_first_then_turn_order():
    st = state_from_dict(_spec([_char("a"), _char("b", hand=[dict(_ZAP)])]))
    # a ends; b's main phase: b casts — and b, the caster, holds priority first.
    st, _ = apply_action(st, _pick(st, kind="end_turn", actor_id="a"))
    st, _ = apply_action(st, _pick(st, kind="cast", actor_id="b", card_id="zap",
                                   target_id="orc"))
    assert _pick(st, kind="pass").actor_id == "b"
    st, _ = apply_action(st, _pick(st, kind="pass", actor_id="b"))
    assert _pick(st, kind="pass").actor_id == "a"         # then turn order
    st, _ = apply_action(st, _pick(st, kind="pass", actor_id="a"))
    assert st.enemy("orc").hp == 29                       # all passed -> resolved


def test_responder_takes_priority_then_it_returns_to_the_pending_caster():
    st = state_from_dict(_spec([_char("a", hand=[dict(_JOLT)]),
                                _char("b", hand=[dict(_ZAP)])]))
    # a casts Jolt: a first. a passes; b responds with Zap: B (the new caster)
    # speaks first on the new top.
    st, _ = apply_action(st, _pick(st, kind="cast", actor_id="a", card_id="jolt",
                                   target_id="orc"))
    assert _pick(st, kind="pass").actor_id == "a"
    st, _ = apply_action(st, _pick(st, kind="pass", actor_id="a"))
    st, _ = apply_action(st, _pick(st, kind="cast", actor_id="b", card_id="zap",
                                   target_id="orc"))
    assert _pick(st, kind="pass").actor_id == "b"
    # Everyone passes -> Zap resolves; the reopened window (Jolt on top) starts
    # with JOLT's caster again: a.
    st, _ = apply_action(st, _pick(st, kind="pass", actor_id="b"))
    st, _ = apply_action(st, _pick(st, kind="pass", actor_id="a"))
    assert st.enemy("orc").hp == 29                       # Zap landed
    assert [i.label for i in st.stack] == ["Jolt"]
    assert _pick(st, kind="pass").actor_id == "a"


def test_enemy_action_window_starts_at_the_top_of_turn_order():
    st = state_from_dict(_spec([_char("b"), _char("a")]))  # authored: b first
    while st.result is None and not (st.stack and st.stack[-1].source_id == "orc"):
        acts = legal_actions(st)
        a = next((x for x in acts if x.kind in ("end_turn", "pass")), acts[0])
        st, _ = apply_action(st, a)
    assert _pick(st, kind="pass").actor_id == "b"          # top of the fixed order
