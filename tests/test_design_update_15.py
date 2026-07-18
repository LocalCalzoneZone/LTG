"""Design Update 15 — Live Movement: the §L-3 interposition redirect, flyer wall
transparency (§L-4), positional row-targeted intents (§L-5), `relentless`
(§L-6.2), live enemy movement (§L-2.3), and the uncounterable Move. The base
live-movement mechanics (stack Move, lunge, dash, haste) are pinned in
test_movement_mitigate.py."""

from __future__ import annotations

from ltg_combat.engine import _filter_matches, apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import StackItem


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


def _cleaver(eid="gore", row="front", amount=4):
    """An enemy with a positional Cleave (§L-5): an attack-type swipe aimed at a
    ROW, its verbs row-scoped so resolution reads occupancy live."""
    return {"id": eid, "name": eid, "hp": 30, "level": 2, "power": 2,
            "attack_mode": "melee",
            "components": [{
                "id": "cleave", "timing": "proactive", "priority": 10,
                "target_row": row, "action_type": "attack", "telegraph": "Cleave",
                "verbs": [{"kind": "deal_damage", "amount": amount,
                           "target": {"mode": "all", "side": "ally",
                                      "rows": [row]}}]}]}


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


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
    while True:
        acts = legal_actions(state)
        if state.stack and any(a.kind == "pass" for a in acts):
            return state
        et = next((a for a in acts if a.kind == "end_turn"), None)
        if et is None:
            state = apply_action(state, acts[0])[0]
        else:
            state = apply_action(state, et)[0]


def _finish_turn(state):
    """End every turn and pass every window until the next turn's player phase."""
    turn = state.turn
    while state.result is None and state.turn == turn:
        acts = legal_actions(state)
        a = next((x for x in acts if x.kind in ("pass", "end_turn")), acts[0])
        state = apply_action(state, a)[0]
    return state


# --- §L-3: dodging is interposition ------------------------------------------- #
def test_stepping_behind_an_interposer_redirects_the_swing():
    st = _state([_char("tank", row="front", hp=30), _char("mage", row="front", hp=10)],
                [_enemy("e", "mage", amount=3)])
    st = _do(st, kind="end_turn", actor_id="tank")
    st = _do(st, kind="move", actor_id="mage", target_id="rear")  # step behind the tank
    st = _pass_all(st)
    e = st.enemies[0]
    assert e.intent.target_id == "tank"                       # covered → redirected
    assert any(ev.type == "intent_redirect" for ev in st.log)
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("mage").hp == 10                      # the dodge worked…
    assert st.character("tank").hp == 27                      # …because the tank ate it


def test_stepping_in_front_is_a_voluntary_bodyguard():
    # The positive twin: a tank walks INTO the pending swing by taking the front.
    st = _state([_char("tank", row="mid", hp=30), _char("mage", row="mid", hp=10)],
                [_enemy("e", "mage", amount=3)])
    st = _do(st, kind="move", actor_id="tank", target_id="front")
    st = _pass_all(st)
    assert st.enemies[0].intent.target_id == "tank"           # the swing re-aims at the wall


def test_melee_lunge_can_pull_the_intent_onto_the_attacker():
    # Update 15, Example 4: with the front row EMPTY, a melee attacker's lunge
    # makes it the wall — and the pending swing on its mid-row ally re-aims.
    st = _state([_char("tank", row="mid", hp=30), _char("mage", row="mid", hp=10)],
                [_enemy("e", "mage", amount=3, hp=20)])
    st = _do(st, kind="attack", actor_id="tank", target_id="e")   # lunges to front
    assert st.party[0].row == "front"
    assert st.enemies[0].intent.target_id == "tank"           # attacking is interposing
    st = _pass_all(st)


# --- §L-4: flyers and the wall ------------------------------------------------- #
def test_flyer_does_not_form_the_wall():
    # Regression for the old exploit: a flying frontliner used to be an
    # unhittable wall (it set the front-most row, then filtered itself out).
    # Now ground melee looks straight past it to the first grounded body.
    st = _state([_char("bird", row="front", keywords=["flying"]),
                 _char("mage", row="rear", hp=20)],
                [_enemy("e", "mage", amount=3)])
    st = _do(st, kind="end_turn", actor_id="bird")            # advance into the turn
    assert st.enemies[0].round_intent is not None
    assert st.enemies[0].round_intent.target_id == "mage"     # reached THROUGH the flyer


def test_flyer_cannot_interpose():
    st = _state([_char("p", row="front", hp=20), _char("bird", row="front", keywords=["flying"])],
                [_enemy("e", "p", amount=3)])
    st = _do(st, kind="move", actor_id="p", target_id="rear")  # "cover me, bird!"
    st = _pass_all(st)
    assert st.enemies[0].intent.target_id == "p"              # no — the swing follows p
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("p").hp == 17


# --- §L-5: positional intents -------------------------------------------------- #
def test_positional_intent_hits_the_occupied_row():
    st = _state([_char("p", row="front", power=2, hp=20)], [_cleaver()])
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].target_row == "front"
    st = _pass_all(st)
    assert st.character("p").hp == 16                         # 4 to everyone standing there


def test_positional_intent_whiffs_on_a_vacated_row():
    st = _state([_char("p", row="front", power=2, hp=20)], [_cleaver()])
    st = _do(st, kind="move", target_id="mid")                # don't be standing there
    st = _pass_all(st)
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("p").hp == 20                         # clean whiff
    assert any(ev.type == "whiff" for ev in st.log)


def test_positional_intent_can_be_mitigated_by_a_struck_character():
    st = _state([_char("p", row="front", power=2, hp=20)], [_cleaver()])  # X = 1
    st = _drive_to_enemy_window(st)
    st = _do(st, kind="mitigate", target_id="p")              # brave: stand and blunt it
    assert st.character("p").hp == 17                         # 4 − 1 = 3 landed


# --- §L-6.2: relentless -------------------------------------------------------- #
def test_relentless_pursues_through_the_wall():
    st = _state([_char("tank", row="front", hp=30), _char("mage", row="front", hp=10)],
                [_enemy("e", "mage", amount=3)])
    st.enemies[0].keywords["relentless"] = "encounter"
    st = _do(st, kind="end_turn", actor_id="tank")
    st = _do(st, kind="move", actor_id="mage", target_id="rear")
    st = _pass_all(st)
    assert st.enemies[0].intent.target_id == "mage"           # no redirect — it pursues
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("mage").hp == 7                       # caught behind the wall


# --- §L-2.3: enemy movement is live -------------------------------------------- #
def test_enemy_move_intent_relocates_at_execution():
    # A stranded ground-melee enemy (the whole party flies) advances toward reach;
    # the body relocates AS THE INTENT EXECUTES, not at End step.
    st = _state([_char("bird", row="rear", keywords=["flying"])],
                [_enemy("e", "bird", amount=2)])
    st = _finish_turn(st)
    ev = next(e for e in st.log if e.type == "enemy_move")
    assert "End step" not in ev.msg                           # the old deferred wording
    assert st.enemies[0].row == "rear"


# --- §L-5 schema surface: row-aimed attacks in both enemy forms ----------------- #
def test_legacy_intent_template_can_target_a_row():
    # The chassis basic attack aimed at ground: an `intent` template with
    # `target_row` — no components needed.
    volley = {"id": "bal", "name": "bal", "hp": 20, "level": 2,
              "intent": {"name": "Ballista Rake", "amount": 3, "target_row": "rear",
                         "intent_type": "attack", "mode": "ranged"}}
    st = _state([_char("mage", row="rear", hp=20)], [volley])
    st = _drive_to_enemy_window(st)
    assert st.stack[-1].label == "Ballista Rake" and st.stack[-1].target_row == "rear"
    st = _pass_all(st)
    assert st.character("mage").hp == 17                      # it raked the back line


def test_legacy_template_positional_whiffs_when_dodged():
    volley = {"id": "bal", "name": "bal", "hp": 20, "level": 2,
              "intent": {"name": "Ballista Rake", "amount": 3, "target_row": "rear",
                         "intent_type": "attack", "mode": "ranged"}}
    st = _state([_char("mage", row="rear", hp=20)], [volley])
    st = _do(st, kind="move", target_id="mid")                # the casters step up
    st = _pass_all(st)
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("mage").hp == 20                      # nothing back there
    assert any(ev.type == "whiff" for ev in st.log)


def test_positional_component_verbs_are_auto_scoped():
    # The author writes a PLAIN damage verb (no hand-written row footprint);
    # the engine normalises it onto the row — everyone standing there is hit.
    swipe = {"id": "gore", "name": "gore", "hp": 30, "level": 2, "power": 2,
             "attack_mode": "melee",
             "components": [{
                 "id": "cleave", "timing": "proactive", "priority": 10,
                 "target_row": "front", "action_type": "attack",
                 "telegraph": "Cleave",
                 "verbs": [{"kind": "deal_damage", "amount": 4,
                            "target": {"mode": "chosen", "side": "ally",
                                       "targeted": True}}]}]}
    st = _state([_char("a", row="front", hp=20), _char("b", row="front", hp=20)],
                [swipe])
    st = _drive_to_enemy_window(st)
    st = _pass_all(st)
    assert st.character("a").hp == 16 and st.character("b").hp == 16


def test_positional_intent_telegraph_names_the_row():
    from ltg_combat.serialize import intent_category, veiled_intent
    st = _state([_char("p", row="front", power=2, hp=20)], [_cleaver()])
    st = _do(st, kind="end_turn")                             # intents are declared
    e = st.enemies[0]
    assert intent_category(e.round_intent) == "row assault"
    entry = veiled_intent(st, e)
    assert entry["target_row"] == "front"
    assert "front of your party" in entry["line"]


def test_bad_target_row_is_rejected_by_the_loader():
    import pytest
    swipe = _cleaver()
    swipe["components"][0]["target_row"] = "flank"
    with pytest.raises(ValueError, match="target_row"):
        _state([_char("p")], [swipe])
    volley = {"id": "bal", "name": "bal", "hp": 20, "level": 2,
              "intent": {"name": "Rake", "amount": 3, "target_row": "behind",
                         "intent_type": "attack"}}
    with pytest.raises(ValueError, match="target_row"):
        _state([_char("p")], [volley])


# --- §L-2.2: you cannot counter footwork ---------------------------------------- #
def test_move_matches_no_counter_filter():
    item = StackItem(kind="move", source_id="p", source_side="party",
                     label="Move to rear", effects=[], target_id="rear")
    for filt in ("action", "spell", "ability", "attack", "activated", "triggered"):
        assert not _filter_matches(filt, item)
