"""Design Update 02 — Movement (current/committed/pending_voluntary), the Mitigate
reaction (self + ally interception), and the Haste keyword. Driven through the
engine's legal_actions / apply_action contract."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", power=2, hp=30, attack_mode="melee"):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 1,
            "identity": ["U"], "row": row, "attack_mode": attack_mode,
            "library": [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid, target, amount=3, mode="melee", hp=20):
    return {"id": eid, "name": eid, "hp": hp, "level": 1,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": target, "mode": mode}}


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


def _do(state, **kw):
    a = next(a for a in legal_actions(state)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(state, a)[0]


def _drive_to_enemy_window(state):
    """End every character's turn so the enemy step executes its attack and opens a
    reaction window."""
    while True:
        acts = legal_actions(state)
        if any(a.kind in ("mitigate", "pass") for a in acts) and state.stack:
            return state                      # reaction window on an enemy attack
        et = next((a for a in acts if a.kind == "end_turn"), None)
        if et is None:                        # e.g. a capacity colour choice — auto-pick
            state = apply_action(state, acts[0])[0]
        else:
            state = apply_action(state, et)[0]


def _pass_all(state):
    """Pass every remaining priority in the open window so the top attack resolves."""
    while state.stack:
        p = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if p is None:
            break
        state = apply_action(state, p)[0]
    return state


# --- movement sync points ----------------------------------------------------- #
def test_voluntary_move_resolves_at_end_step():
    st = _state([_char("p", row="front")], [_enemy("e", "p")])
    st = _do(st, kind="move", target_id="rear")
    p = st.party[0]
    assert p.pending_voluntary == "rear" and p.row == "front"  # body has NOT moved yet
    assert p.acted_mode == "move"                              # the proactive action is spent
    # play out the turn; at End step the body catches up to the queued destination.
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="pass")                                  # let the enemy hit resolve → End step
    assert st.party[0].row == "rear"                           # current ← pending_voluntary
    assert st.party[0].pending_voluntary is None and st.party[0].committed == "rear"


def test_melee_attack_forces_committed_front():
    st = _state([_char("p", row="rear")], [_enemy("e", "p", hp=20)])
    st = _do(st, kind="attack", target_id="e")                # melee swing
    assert st.party[0].committed == "front"                   # §M-B.3 forced move
    assert st.party[0].row == "rear"                          # body still where it stood


def test_move_does_not_dodge_a_locked_intent():
    # The enemy's intent locks onto the rear character at declaration; queueing a
    # move afterward cannot break it (it still lands this turn).
    st = _state([_char("p", row="rear", hp=20)], [_enemy("e", "p", amount=3, mode="ranged")])
    st = _do(st, kind="move", target_id="front")              # try to slip away
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="pass")                                 # take the hit
    assert st.party[0].hp == 17                               # 3 landed — no dodge


# --- Mitigate (self) ---------------------------------------------------------- #
def test_mitigate_self_reduces_by_ceil_half_power():
    st = _state([_char("p", power=3, hp=20)], [_enemy("e", "p", amount=4)])  # X = ceil(3/2)=2
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    assert st.party[0].hp == 18                               # 4 − 2 = 2 landed


def test_mitigate_self_fully_negates_small_hit():
    st = _state([_char("p", power=4, hp=20)], [_enemy("e", "p", amount=2)])  # X = 2, hit 2
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")
    assert st.party[0].hp == 20                               # max(0, 2−2) = 0


def test_mitigate_is_once_per_turn():
    # Two enemies attack the same character in one enemy step; the single use is
    # spent on the first, so the second window offers no Mitigate.
    st = _state([_char("p", power=2, hp=30)],
                [_enemy("e1", "p", amount=2), _enemy("e2", "p", amount=2)])
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")             # resolves; e2's attack follows
    assert st.stack and all(a.kind != "mitigate" for a in legal_actions(st))


# --- Mitigate (ally interception) --------------------------------------------- #
def _two_char_state(tank_row):
    # Tank (Power 4 → X=2) plus a fragile Mage in the rear; a ranged enemy targets
    # the Mage so the wall can't stop it — only interception can.
    party = [_char("tank", row=tank_row, power=4, hp=30),
             _char("mage", row="rear", power=1, hp=10)]
    return _state(party, [_enemy("e", "mage", amount=5, mode="ranged")])


def test_mitigate_ally_redirects_and_forces_move():
    st = _two_char_state(tank_row="mid")                      # mid is adjacent to rear
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", actor_id="tank", target_id="mage")
    assert st.character("tank").committed == "rear"           # §M-A.6 forced move (at declaration)
    st = _pass_all(st)                                        # mage passes too → the attack resolves
    assert st.character("mage").hp == 10                      # the hit was redirected away
    assert st.character("tank").hp == 30 - (5 - 2)            # tank took 5 − X(2) = 3


def test_mitigate_ally_blocked_by_adjacency():
    st = _two_char_state(tank_row="front")                    # front is NOT adjacent to rear
    st = _drive_to_enemy_window(st)
    acts = legal_actions(st)
    assert all(not (a.kind == "mitigate" and a.target_id == "mage") for a in acts)


# --- Haste -------------------------------------------------------------------- #
def test_haste_allows_act_and_free_move():
    st = _state([_char("p", row="front", power=2, hp=30)], [_enemy("e", "p")])
    st.party[0].keywords["haste"] = "encounter"
    st = _do(st, kind="attack", target_id="e")               # spend the proactive action
    st = _pass_all(st)                                        # resolve the attack → back to main phase
    assert st.party[0].acted_mode == "attack"
    move = next((a for a in legal_actions(st) if a.kind == "move"), None)
    assert move is not None                                   # haste still offers a free move
    st = apply_action(st, next(a for a in legal_actions(st)
                               if a.kind == "move" and a.target_id == "rear"))[0]
    assert st.party[0].acted_mode == "attack"                # the free move did NOT cost the action
    assert st.party[0].pending_voluntary == "rear"
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="pass")
    assert st.party[0].row == "rear"                          # resolved at End step
