"""Movement and Mitigate under LIVE movement (Design Update 15, superseding
Update 02 §M-B): the single-position model, stack-action Moves, the melee lunge,
and the Mitigate reaction (self + ally interception). The §L-3 redirect /
interposition rules themselves are pinned in test_design_update_15.py."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", power=2, hp=30, attack_mode="melee", keywords=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 1,
            "identity": ["U"], "row": row, "attack_mode": attack_mode,
            "keywords": keywords or [],
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
    """Pass every remaining priority in the open window so the top item resolves."""
    while state.stack:
        p = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if p is None:
            break
        state = apply_action(state, p)[0]
    return state


# --- live movement (§L-1 / §L-2) ---------------------------------------------- #
def test_voluntary_move_resolves_live():
    st = _state([_char("p", row="front")], [_enemy("e", "p")])
    st = _do(st, kind="move", target_id="rear")
    p = st.party[0]
    assert st.stack and st.stack[-1].kind == "move"           # a stack action (§L-2.2)
    assert p.row == "front"                                   # not yet resolved
    assert p.acted_mode == "move" and p.used_move             # action spent, once per turn
    st = _pass_all(st)
    assert st.party[0].row == "rear"                          # the body relocated LIVE
    assert all(a.kind != "move" for a in legal_actions(st))   # no second move this turn


def test_melee_attack_lunges_to_front_at_declaration():
    st = _state([_char("p", row="rear")], [_enemy("e", "p", hp=20)])
    st = _do(st, kind="attack", target_id="e")                # melee swing
    assert st.stack                                           # the swing is still pending
    assert st.party[0].row == "front"                         # §L-2.1: the body lunged NOW


def test_move_cannot_dodge_a_ranged_intent():
    # Ranged intents never redirect and never miss a mover (§L-3.2): the volley
    # stays locked on its declared target wherever it stands.
    st = _state([_char("p", row="rear", hp=20)], [_enemy("e", "p", amount=3, mode="ranged")])
    st = _do(st, kind="move", target_id="front")              # try to slip away
    st = _pass_all(st)
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="pass")                                 # take the hit
    assert st.party[0].hp == 17                               # 3 landed — no dodge


def test_move_without_interposer_is_followed():
    # A melee intent follows its target when nobody covers them (§L-3.1): with no
    # body left in front, the front-most row IS wherever the target now stands.
    st = _state([_char("p", row="front", hp=20)], [_enemy("e", "p", amount=3)])
    st = _do(st, kind="move", target_id="rear")               # running, not dodging
    st = _pass_all(st)
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="pass")
    assert st.party[0].hp == 17                               # the swing followed


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


def test_mitigate_ally_redirects_and_dashes_live():
    st = _two_char_state(tank_row="mid")                      # mid is adjacent to rear
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", actor_id="tank", target_id="mage")
    assert st.character("tank").row == "rear"                 # §L-2.1: the dash is live
    st = _pass_all(st)                                        # mage passes too → the attack resolves
    assert st.character("mage").hp == 10                      # the hit was redirected away
    assert st.character("tank").hp == 30 - (5 - 2)            # tank took 5 − X(2) = 3


def test_mitigate_ally_blocked_by_adjacency():
    st = _two_char_state(tank_row="front")                    # front is NOT adjacent to rear
    st = _drive_to_enemy_window(st)
    acts = legal_actions(st)
    assert all(not (a.kind == "mitigate" and a.target_id == "mage") for a in acts)


# --- Haste -------------------------------------------------------------------- #
def test_haste_allows_act_and_free_live_move():
    st = _state([_char("p", row="front", power=2, hp=30)], [_enemy("e", "p")])
    st.party[0].keywords["haste"] = "encounter"
    st = _do(st, kind="attack", target_id="e")               # spend the proactive action
    st = _pass_all(st)                                        # resolve the attack → main phase
    assert st.party[0].acted_mode == "attack"
    move = next((a for a in legal_actions(st) if a.kind == "move"), None)
    assert move is not None                                   # haste still offers a free move
    st = apply_action(st, next(a for a in legal_actions(st)
                               if a.kind == "move" and a.target_id == "rear"))[0]
    assert st.party[0].acted_mode == "attack"                # the free move did NOT cost the action
    st = _pass_all(st)
    assert st.party[0].row == "rear"                          # resolved LIVE, before the enemy step


def test_no_move_while_own_action_is_unresolved():
    # §L-2.2: with the attack still on the stack, even a hasted character cannot
    # take the free move — the window offers reactions, never a Move.
    st = _state([_char("p", row="front", power=2, hp=30)], [_enemy("e", "p")])
    st.party[0].keywords["haste"] = "encounter"
    st = _do(st, kind="attack", target_id="e")
    assert st.stack
    assert all(a.kind != "move" for a in legal_actions(st))
