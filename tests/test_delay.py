"""Delay: at the start of its turn a character may move to the END of the party
turn order — for the rest of the encounter — handing the main phase to the next
character in line and coming back round last."""

from __future__ import annotations

from ltg_combat.engine import apply_action, auto_pass_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict

_FILLER = {"id": "f", "name": "f", "source_name": "f", "rarity": "common",
           "level": 1, "type": "Instant", "timing": "instant",
           "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "draw", "amount": 0}]}


def _pc(cid):
    return {"id": cid, "name": cid.title(), "hp": 20, "power": 2, "hand_size": 1,
            "identity": ["U"], "row": "front", "library": [dict(_FILLER)]}


def _state():
    st = state_from_dict({
        "party": [_pc("alpha"), _pc("beta"), _pc("gamma")],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 60, "level": 1,
                     "intent": {"name": "Hurl", "amount": 1, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "ranged"}}],
    })
    st.party_order = ["alpha", "beta", "gamma"]
    return st


def _main_phase_open(st):
    """legal_actions advances the turn structure: a main phase is open when the
    legal set carries an `end_turn` (and no stack window is pending)."""
    return not st.stack and any(a.kind == "end_turn" for a in legal_actions(st))


def _to_player_phase(st, turn=1):
    while not (_main_phase_open(st) and st.turn >= turn):
        acts = legal_actions(st)
        nxt = next((a for a in acts if a.kind in ("pass", "end_turn", "choose_mana")), acts[0])
        st = apply_action(st, nxt)[0]
    return settle(st)  # priority lands on the main-phase holder


def _act(st, kind):
    a = next(a for a in legal_actions(st) if a.kind == kind)
    return apply_action(st, a)[0]


def test_delay_hands_turn_to_next_and_comes_back_last():
    st = _to_player_phase(_state())
    assert st.priority == "alpha"
    assert any(a.kind == "delay" for a in legal_actions(st))
    st = settle(_act(st, "delay"))
    # Beta goes now; alpha's turn is NOT ended.
    assert st.priority == "beta"
    assert st.character("alpha").turn_ended is False
    assert st.party_order == ["beta", "gamma", "alpha"]
    st = settle(_act(st, "end_turn"))
    assert st.priority == "gamma"
    st = settle(_act(st, "end_turn"))
    assert st.priority == "alpha"  # round comes back to the delayer, last
    # Once per turn: no second delay, and nobody else is left to hand off to.
    assert not any(a.kind == "delay" for a in legal_actions(st))


def test_delay_persists_into_later_turns():
    st = _to_player_phase(_state())
    st = _act(st, "delay")
    # Finish the round: beta, gamma, then alpha end their turns.
    for _ in range(3):
        st = _act(st, "end_turn")
    # Run through the enemy step into turn 2's player phase.
    st = _to_player_phase(st, turn=2)
    assert st.party_order == ["beta", "gamma", "alpha"]
    assert st.priority == "beta"  # the new order holds next round
    assert st.character("alpha").delayed is False  # the once-per-turn gate reset
    assert any(a.kind == "delay" for a in legal_actions(st))


def test_delay_only_at_start_of_turn():
    st = _to_player_phase(_state())
    st = _act(st, "attack")
    # Resolve the attack's window.
    while st.stack:
        st = _act(st, "pass")
    st = settle(st)
    assert st.priority == "alpha"
    assert not any(a.kind == "delay" for a in legal_actions(st))


def test_delay_not_offered_to_the_last_character_in_the_round():
    st = _to_player_phase(_state())
    st = _act(st, "end_turn")
    st = settle(_act(st, "end_turn"))
    assert st.priority == "gamma"
    assert not any(a.kind == "delay" for a in legal_actions(st))


def test_bare_end_turn_plus_delay_still_auto_ends():
    st = _to_player_phase(_state())
    kinds = {a.kind for a in legal_actions(st)}
    assert "delay" in kinds and "end_turn" in kinds
    # With a real option (attack) on the table, nothing auto-fires.
    assert auto_pass_action(st) is None
    # Strip every real option: the lone end_turn(+delay) set auto-ends.
    st = settle(st)
    alpha = st.character("alpha")
    alpha.used_attack = alpha.used_defend = alpha.used_move = True
    alpha.hand = []
    kinds = {a.kind for a in legal_actions(st)}
    assert kinds == {"end_turn", "delay"}
    assert auto_pass_action(st).kind == "end_turn"
