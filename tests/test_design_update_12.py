"""Design Update 12 — Roadmap Tier One.

§D12-1 Alternate objectives: the closed set survive / waves / race — reserve
zone, End-Step timer ticks, wave/reinforcement deployment, race expiry and the
escalation payload, the win/loss variants, snapshot surfaces, and the content
validation (one objective per adventure, Acts I–II only, mini-boss in the final
wave, T-66 wave body minimums).

Encounters WITHOUT an objective staying byte-identical is asserted by the whole
rest of the suite continuing to pass (the §A/§C harness scenarios carry none).
"""

from __future__ import annotations

import copy

import pytest

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import scale_encounter, state_from_dict
from ltg_core.schema import EncounterObjective


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _hero(hp=60, power=1, cid="hero"):
    return {"id": cid, "name": cid.title(), "hp": hp, "power": power,
            "hand_size": 0, "identity": ["W"], "row": "front",
            "attack_mode": "melee", "library": []}


def _enemy(eid, hp=10, amount=1, level=1, **extra):
    e = {"id": eid, "name": eid.title(), "hp": hp, "level": level,
         "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                    "intent_type": "attack", "targeting": "lowest_hp_party",
                    "mode": "melee"}}
    e.update(extra)
    return e


def _pick(st, kind, **match):
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return a
    return None


def _drive_round(st):
    """End turns / pass windows until the round counter advances or the game ends."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    return st


def _drive_to_result(st, attack=False, guard=400):
    for _ in range(guard):
        if st.result is not None:
            return st
        acts = legal_actions(st)
        if not acts:
            return st
        act = None
        if attack:
            act = next((a for a in acts if a.kind == "attack"), None)
        act = act or next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    raise AssertionError("fight did not terminate")


# ========================================================================== #
# §D12-1.1 — the objective object
# ========================================================================== #
def test_no_objective_means_none_on_state():
    st = state_from_dict({"party": [_hero()], "enemies": [_enemy("wolf")]})
    assert st.objective is None


def test_objective_schema_rejects_malformed_shapes():
    good = {"kind": "survive", "turns": 5}
    EncounterObjective.model_validate(good)
    for bad in (
        {"kind": "protect"},                                # unknown kind
        {"kind": "survive"},                                # no timer
        {"kind": "survive", "turns": 0},                    # empty timer
        {"kind": "survive", "turns": 4, "target": "x"},     # foreign field
        {"kind": "waves"},                                  # no later waves
        {"kind": "waves", "waves": [[]]},                   # empty wave
        {"kind": "race", "turns": 3},                       # no target
        {"kind": "race", "turns": 3, "target": "x",
         "fail": "escalate"},                               # escalate, no payload
        {"kind": "race", "turns": 3, "target": "x", "fail": "defeat",
         "escalation": {"telegraph": "x", "verbs": [
             {"kind": "deal_damage", "amount": 1,
              "target": {"mode": "all", "side": "ally"}}]}},  # defeat + payload
    ):
        with pytest.raises(Exception):
            EncounterObjective.model_validate(bad)


def test_race_target_must_be_fielded():
    with pytest.raises(ValueError, match="not fielded"):
        state_from_dict({
            "party": [_hero()], "enemies": [_enemy("wolf")],
            "objective": {"kind": "race", "target": "ghost", "turns": 3,
                          "fail": "defeat"}})


# ========================================================================== #
# §D12-1.2 — survive
# ========================================================================== #
def _survive_spec(turns=3, reinforce_turn=2):
    return {
        "party": [_hero()],
        "enemies": [_enemy("wolf", hp=30)],
        "objective": {"kind": "survive", "turns": turns,
                      "reinforcements": [{"turn": reinforce_turn,
                                          "layouts": {"1": ["wolf"]}}]},
    }


def test_survive_timer_wins_at_round_n_end_step():
    st = state_from_dict(_survive_spec(turns=3))
    st = _drive_to_result(st)
    assert st.result == "victory"
    assert st.objective.rounds_done == 3
    # Withdrawal is flavour: no kill credit, no death triggers.
    assert any(e.type == "withdraw" for e in st.log)
    assert not any(e.type == "enemy_died" for e in st.log)
    assert any(e.type == "win" and e.data.get("objective") == "survive"
               for e in st.log)


def test_survive_reinforcements_deploy_at_their_round_intents_step():
    st = state_from_dict(_survive_spec(turns=4, reinforce_turn=2))
    # Turn 1: the reinforcement waits in reserve — off-field, untargetable.
    view = settle(st)
    assert [e.id for e in view.living_enemies()] == ["wolf"]
    reserved = view.enemy("wolf_2")
    assert reserved is not None and reserved.reserve
    assert _pick(st, "attack", target_id="wolf_2") is None
    st = _drive_round(st)
    # Turn 2: deployed at the Enemy Intents step, declaring the same step.
    view = settle(st)
    arrived = view.enemy("wolf_2")
    assert arrived is not None and not arrived.reserve
    assert arrived.intent is not None
    assert any(e.type == "reinforcements" for e in st.log)


def test_survive_reserves_block_kill_victory_but_not_the_timer():
    # Kill the only fielded wolf on turn 1: the reinforcement (turn 3) is still
    # unarrived, so the act does NOT end — the party holds until it lands.
    spec = _survive_spec(turns=5, reinforce_turn=3)
    spec["party"] = [_hero(power=30)]
    st = state_from_dict(spec)
    st = apply_action(st, _pick(st, "attack", target_id="wolf"))[0]
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    assert st.result is None  # the reserve keeps the encounter live
    # Killing the reinforcement too ends it the standard way.
    st = _drive_to_result(st, attack=True)
    assert st.result == "victory"
    assert any(e.type == "win" and "All enemies defeated" in e.msg for e in st.log)


# ========================================================================== #
# §D12-1.3 — waves
# ========================================================================== #
def _waves_spec():
    return {
        "party": [_hero(power=10)],
        "enemies": [_enemy("wolf", hp=3), _enemy("bear", hp=3, level=2)],
        "layouts": {"1": ["wolf"]},
        "objective": {"kind": "waves", "waves": [{"1": ["bear", "wolf"]}]},
    }


def test_waves_reserves_block_victory_and_deploy_next_round():
    st = state_from_dict(scale_encounter(_waves_spec(), 1))
    view = settle(st)
    assert [e.id for e in view.living_enemies()] == ["wolf"]
    assert {e.id for e in view.reserve_enemies()} == {"bear", "wolf_2"}
    # Kill wave 1: the encounter stays live (reserves block by construction)…
    st = apply_action(st, _pick(st, "attack", target_id="wolf"))[0]
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    assert st.result is None
    turn_killed = st.turn
    # …and wave 2 deploys at the START of the NEXT round's Enemy Intents step
    # (the party gets the End Step and Upkeep breather first).
    view = settle(st)
    assert view.turn == turn_killed and not view.living_enemies()
    st = _drive_round(st)
    view = settle(st)
    assert {e.id for e in view.living_enemies()} == {"bear", "wolf_2"}
    assert all(e.intent is not None for e in view.living_enemies())
    assert st.objective.wave_index == 1
    assert any(e.type == "wave_deployed" and e.data.get("wave") == 2
               for e in st.log)
    # Clearing the final wave wins the standard way.
    st = _drive_to_result(st, attack=True)
    assert st.result == "victory"


def test_wave_deploys_on_home_rows():
    spec = _waves_spec()
    spec["enemies"][1]["row"] = "front"
    spec["enemies"][1]["home_row"] = "rear"
    st = state_from_dict(scale_encounter(spec, 1))
    st = apply_action(st, _pick(st, "attack", target_id="wolf"))[0]
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    st = _drive_round(st)
    view = settle(st)
    assert view.enemy("bear").row == "rear"


# ========================================================================== #
# §D12-1.4 — race
# ========================================================================== #
def _race_spec(turns=2, fail="escalate", target_hp=99):
    obj = {"kind": "race", "target": "ritualist", "turns": turns, "fail": fail}
    if fail == "escalate":
        obj["escalation"] = {
            "telegraph": "The Rite Completes",
            "verbs": [
                {"kind": "counters", "power": 2, "toughness": 2,
                 "target": {"mode": "all", "side": "enemy"}},
                {"kind": "deal_damage", "amount": 3,
                 "target": {"mode": "all", "side": "ally"}},
            ]}
    return {
        "party": [_hero()],
        "enemies": [_enemy("ritualist", hp=target_hp, amount=0),
                    _enemy("guard", hp=40, amount=0)],
        "objective": obj,
    }


def test_race_completes_when_the_marked_enemy_dies():
    spec = _race_spec(turns=4, fail="defeat", target_hp=3)
    spec["party"] = [_hero(power=5)]
    st = state_from_dict(spec)
    st = apply_action(st, _pick(st, "attack", target_id="ritualist"))[0]
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    assert st.objective.status == "complete"
    assert any(e.type == "objective_complete" for e in st.log)
    # The act continues to standard victory (mop up) — not an instant win.
    assert st.result is None
    st = _drive_to_result(st, attack=True)
    assert st.result == "victory"


def test_race_expiry_with_fail_defeat_loses_the_act():
    st = state_from_dict(_race_spec(turns=2, fail="defeat"))
    st = _drive_to_result(st)
    assert st.result == "defeat"
    assert any(e.type == "loss" and e.data.get("objective") == "race"
               for e in st.log)


def test_race_expiry_with_fail_escalate_fires_the_payload_on_the_stack():
    st = state_from_dict(_race_spec(turns=2))
    hero_hp = st.party[0].hp
    # Round 1 and round 2 pass with the ritualist untouched.
    st = _drive_round(st)
    st = _drive_round(st)
    assert st.objective.status == "failed"
    # The payload sits on the stack, sourced from the marked enemy, answerable.
    assert st.stack and st.stack[-1].label == "The Rite Completes"
    assert st.stack[-1].source_id == "ritualist"
    assert legal_actions(st)  # the party may respond
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    # The eruption resolved: permanent counters on the enemy side + the AoE.
    assert st.party[0].hp == hero_hp - 3
    assert st.enemy("guard").counters == 2  # a permanent +2/+2 landed
    # The fight continues under standard victory.
    assert st.result is None


def test_race_clock_ignores_stun_and_a_bounced_target_returns_at_expiry():
    # Bounce the marked enemy on round 2 (it redeploys next intents step), then
    # let the clock expire: bounced is NOT defeated; the enemy returns first.
    st = state_from_dict(_race_spec(turns=1))
    obj = st.objective
    target = st.enemy("ritualist")
    target.in_hand = True  # as if bounced mid-round
    st = _drive_round(st)
    assert obj.status in ("failed",) or st.objective.status == "failed"
    assert not st.enemy("ritualist").in_hand  # returned before the payload
    assert st.stack and st.stack[-1].source_id == "ritualist"


def test_race_controlled_target_snaps_back_at_expiry():
    from ltg_combat.state import TokenState
    st = state_from_dict(_race_spec(turns=1))
    # Simulate MIND CONTROL: the marked enemy is a party-side token; its
    # EnemyState left the roster with `revert` holding the body.
    body = st.enemy("ritualist")
    st.enemies.remove(body)
    st.tokens.append(TokenState(
        id="ritualist_tok", name="Ritualist (dominated)", max_hp=body.max_hp,
        hp=body.hp, power=2, controlled_by="hero", control_left=None,
        revert=body))
    st = _drive_round(st)
    # Controlled is not defeated (§D12-1.4): the domination shattered at the
    # fail moment and the payload fired from the returned enemy.
    assert st.objective.status == "failed"
    assert st.enemy("ritualist") is not None
    assert not any(t.id == "ritualist_tok" for t in st.tokens)
    assert st.stack and st.stack[-1].source_id == "ritualist"


def test_race_exiled_target_counts_as_defeated():
    st = state_from_dict(_race_spec(turns=3, fail="defeat", target_hp=5))
    from ltg_combat.engine import _kill_enemy
    _kill_enemy(st, st.enemy("ritualist"), leaves_corpse=False, death_event=False)
    st = _drive_round(st)
    assert st.objective.status == "complete"


# ========================================================================== #
# §D12-1.5 — surfaces (snapshot / serialize)
# ========================================================================== #
def test_objective_banner_and_doom_badge_in_snapshot():
    from ltg_game_server.snapshot import build_snapshot
    st = state_from_dict(_race_spec(turns=3))
    snap = build_snapshot(st, {"hero"})
    assert snap["objective"]["kind"] == "race"
    assert snap["objective"]["status"] == "active"
    assert "3 rounds remain" in snap["objective"]["line"]
    badge = {c["id"]: c["doom_clock"] for c in snap["creatures"]}
    assert badge["ritualist"] == 3 and badge["guard"] is None


def test_reserve_enemies_do_not_render():
    from ltg_game_server.snapshot import build_snapshot
    st = state_from_dict(scale_encounter(_waves_spec(), 1))
    snap = build_snapshot(st, {"hero"})
    assert [c["id"] for c in snap["creatures"]] == ["wolf"]
    assert snap["objective"]["line"] == "Wave 1 of 2"


def test_game_over_carries_the_objective_outcome_line():
    from ltg_game_server.snapshot import build_snapshot
    st = state_from_dict(_survive_spec(turns=2, reinforce_turn=2))
    st = _drive_to_result(st)
    snap = build_snapshot(st, {"hero"})
    assert snap["game_over"]["result"] == "victory"
    assert "held the line" in snap["game_over"]["objective_line"]


def test_survive_banner_counts_down_each_end_step():
    from ltg_combat.serialize import objective_block
    st = state_from_dict(_survive_spec(turns=3))
    assert objective_block(settle(st))["line"] == "Survive: 3 rounds remain"
    st = _drive_round(st)
    assert objective_block(settle(st))["line"] == "Survive: 2 rounds remain"


# ========================================================================== #
# §D12-1 — content validation (adventure standing rules)
# ========================================================================== #
from ltg_game_server import content  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_content(tmp_path):
    """Keep saved encounters/adventures/acts/hidden files out of the real
    content + loadouts state."""
    dirs = [content.CONTENT_DIR, content.LOADOUTS_DIR]
    before = {d: ({p.name for p in d.glob("*.json")} if d.is_dir() else set())
              for d in dirs}
    saved_hidden = {p: (p.read_text() if p.exists() else None)
                    for p in (content.HIDDEN_FILE, content.ENCOUNTER_HIDDEN_FILE,
                              content.ADVENTURE_HIDDEN_FILE)}
    try:
        yield
    finally:
        for d in dirs:
            if d.is_dir():
                for p in d.glob("*.json"):
                    if p.name not in before[d]:
                        p.unlink(missing_ok=True)
        for p, original in saved_hidden.items():
            if original is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(original)


def _adv_enemy(eid, name, level, hp=4, boss=False):
    e = {"id": eid, "name": name, "hp": hp, "level": level, "row": "front",
         "attack_mode": "melee", "power": 1,
         "description": f"A {name.lower()} of the test faction."}
    if boss:
        e["is_boss"] = True
    return e


def _adv_act(name, enemies, boss_id=None,
             narration="You arrive. The test begins.", objective=None):
    ids = [e["id"] for e in enemies if not e.get("is_boss")]
    filler = ids[0]
    layouts = {}
    for size in range(1, 5):
        roster = [filler] * (2 * size)
        if boss_id:
            roster[0] = boss_id
        layouts[str(size)] = roster
    act = {"name": name, "scene": f"The {name} scene, painted in test grey.",
           "enemies": enemies, "layouts": layouts, "narration": narration}
    if objective is not None:
        act["objective"] = objective
    return act


def _survive_objective(turns=5):
    return {"kind": "survive", "turns": turns,
            "reinforcements": [{"turn": 3, "layouts": {
                "1": ["guard"], "2": ["guard"], "3": ["guard"], "4": ["guard"]}}]}


def _adventure(act1_objective=None, act2_objective=None, act3_objective=None):
    return {
        "name": "Test Keep",
        "flavor": "Three rooms, one tyrant.",
        "acts": [
            _adv_act("The Gate", [_adv_enemy("guard", "Guard", 1)],
                     objective=act1_objective),
            _adv_act("The Courtyard", [_adv_enemy("knight", "Knight", 2)],
                     objective=act2_objective),
            _adv_act("The Throne Room",
                     [_adv_enemy("footman", "Footman", 1),
                      _adv_enemy("tyrant", "Tyrant", 4, hp=20, boss=True)],
                     boss_id="tyrant", objective=act3_objective),
        ],
    }


def test_adventure_accepts_one_objective_on_an_early_act():
    meta = content.save_adventure(_adventure(act1_objective=_survive_objective()))
    detail = content.adventure_detail(meta["id"])
    assert detail["acts"][0]["objective"]["kind"] == "survive"
    assert "objective" not in detail["acts"][1]


def test_adventure_rejects_two_objectives():
    with pytest.raises(ValueError, match="at most one objective"):
        content.save_adventure(_adventure(
            act1_objective=_survive_objective(),
            act2_objective=_survive_objective()))


def test_adventure_rejects_an_act_three_objective():
    with pytest.raises(ValueError, match="Act III"):
        content.save_adventure(_adventure(act3_objective=_survive_objective()))


def test_waves_act_requires_the_miniboss_in_the_final_wave():
    # An act with a mini-boss and a waves objective: the boss belongs in the
    # LAST wave, never in the layouts (wave 1) or an earlier wave.
    def waves_act(final_has_boss=True, boss_in_layouts=False):
        enemies = [_adv_enemy("cutpurse", "Cutpurse", 1),
                   _adv_enemy("captain", "Captain", 3, hp=10, boss=True)]
        per_size = lambda ids: {str(s): list(ids) for s in range(1, 5)}  # noqa: E731
        act = _adv_act("The Pit", enemies,
                       boss_id="captain" if boss_in_layouts else None)
        act["objective"] = {"kind": "waves", "waves": [
            per_size(["cutpurse", "cutpurse", "cutpurse", "cutpurse"]),
            per_size(["captain", "cutpurse", "cutpurse", "cutpurse"]
                     if final_has_boss else
                     ["cutpurse", "cutpurse", "cutpurse", "cutpurse"]),
        ]}
        return act

    adv = _adventure()
    adv["acts"][1] = waves_act()
    content.save_adventure(adv)  # valid: boss in the final wave only

    adv = _adventure()
    adv["acts"][1] = waves_act(final_has_boss=False)
    with pytest.raises(ValueError, match="FINAL wave"):
        content.save_adventure(adv)

    adv = _adventure()
    adv["acts"][1] = waves_act(boss_in_layouts=True)
    with pytest.raises(ValueError, match="not wave 1"):
        content.save_adventure(adv)


def test_waves_act_body_minimums_t66():
    # Each wave ≥ 1× party size; ≥ 2× total across waves. A wave of one body
    # fails at size 2+.
    enemies = [_adv_enemy("cutpurse", "Cutpurse", 1)]
    act = _adv_act("The Pit", enemies)
    act["objective"] = {"kind": "waves", "waves": [
        {str(s): ["cutpurse"] for s in range(1, 5)}]}  # 1 body at every size
    adv = _adventure()
    adv["acts"][0] = act
    with pytest.raises(ValueError, match="every wave fields at least"):
        content.save_adventure(adv)


def test_race_target_must_be_in_every_layout():
    enemies = [_adv_enemy("guard", "Guard", 1),
               _adv_enemy("ritualist", "Ritualist", 2, hp=8)]
    act = _adv_act("The Rite", enemies)  # layouts field only guards
    act["objective"] = {
        "kind": "race", "target": "ritualist", "turns": 4, "fail": "escalate",
        "escalation": {"telegraph": "The Rite Completes", "verbs": [
            {"kind": "deal_damage", "amount": 3,
             "target": {"mode": "all", "side": "ally"}}]}}
    adv = _adventure()
    adv["acts"][0] = act
    with pytest.raises(ValueError, match="every layout"):
        content.save_adventure(adv)


# ========================================================================== #
# §D12-2 — Enemy insight
# ========================================================================== #
from ltg_combat.state import AmplifyTag  # noqa: E402


def _ult_card(cid="ult", amount=5):
    return {"id": cid, "name": "Doombolt", "source_name": "Doombolt",
            "rarity": "rare", "level": 1, "type": "Sorcery",
            "timing": "sorcery", "cost": {},
            "effects": [{"kind": "deal_damage", "amount": amount,
                         "target": {"mode": "chosen", "side": "enemy",
                                    "targeted": True}}],
            "validated": True}


def _two_heroes(spec_extra_b=None):
    a = _hero(hp=20, cid="alys")            # lower HP: the pre-insight pick
    b = dict(_hero(hp=40, cid="brom"))
    if spec_extra_b:
        b.update(spec_extra_b)
    return [a, b]


def _valuation_enemy(amount=2):
    return {"id": "stalker", "name": "Stalker", "hp": 30, "level": 3,
            "intent": {"name": "Pounce", "amount": amount,
                       "action_type": "ability", "intent_type": "attack",
                       "targeting": "valuation", "mode": "melee"}}


def _declared_target(st):
    view = settle(st)
    return view.enemies[0].intent.target_id


def test_primed_amplify_tag_draws_the_default_attack():
    st = state_from_dict({"party": _two_heroes(), "enemies": [_valuation_enemy()]})
    assert _declared_target(st) == "alys"  # baseline: lowest effective HP
    st = state_from_dict({"party": _two_heroes(), "enemies": [_valuation_enemy()]})
    st.party[1].amplify_tags.append(AmplifyTag(event="any_damage", multiplier=2))
    assert _declared_target(st) == "brom"  # the primed threat outranks role/HP


def test_spendable_gauge_at_80_reads_as_primed():
    party = _two_heroes({"ultimate": _ult_card()})
    st = state_from_dict({"party": party, "enemies": [_valuation_enemy()]})
    st.party[1].ultimate_gauge = 80
    assert _declared_target(st) == "brom"
    # A spent ultimate threatens nothing — back to the normal order.
    st = state_from_dict({"party": party, "enemies": [_valuation_enemy()]})
    st.party[1].ultimate_gauge = 80
    st.party[1].ultimate_used = True
    assert _declared_target(st) == "alys"
    # And a gauge without an authored ultimate is not a threat either.
    st = state_from_dict({"party": _two_heroes(), "enemies": [_valuation_enemy()]})
    st.party[1].ultimate_gauge = 100
    assert _declared_target(st) == "alys"


def test_primed_tag_outscores_the_gauge():
    party = [dict(_hero(hp=20, cid="alys"), ultimate=_ult_card("u1")),
             _hero(hp=40, cid="brom")]
    st = state_from_dict({"party": party, "enemies": [_valuation_enemy()]})
    st.party[0].ultimate_gauge = 100            # score 1
    st.party[1].double_next.append("spell")     # score 2
    assert _declared_target(st) == "brom"


def test_finishable_still_outranks_primed():
    party = [dict(_hero(cid="alys"), hp=2),     # finishable by the 2-damage hit
             _hero(hp=40, cid="brom")]
    st = state_from_dict({"party": party, "enemies": [_valuation_enemy(amount=2)]})
    st.party[1].amplify_tags.append(AmplifyTag(event="any_damage", multiplier=3))
    assert _declared_target(st) == "alys"


def test_gauge_punisher_condition_and_primed_hero_rule():
    punisher = {
        "id": "watcher", "name": "Watcher", "hp": 20, "level": 3, "power": 1,
        "components": [{
            "id": "gauge_punish", "archetype": "Debilitate",
            "timing": "proactive", "priority": 20,
            "condition": {"kind": "hero_gauge_pct", "op": ">=", "value": 80},
            "target_rule": "primed_hero",
            "telegraph": "Punish the Gathering Storm",
            "verbs": [{"kind": "wound", "power": 1, "toughness": 1,
                       "target": {"mode": "chosen", "side": "ally",
                                  "targeted": True}}]}]}
    party = _two_heroes({"ultimate": _ult_card()})
    # Gauge low: the condition fails; the default attack declares instead.
    st = state_from_dict({"party": party, "enemies": [punisher]})
    view = settle(st)
    assert view.enemies[0].intent.name == "Watcher Attack"
    # Gauge high: the punisher arms and aims at the primed hero.
    st = state_from_dict({"party": party, "enemies": [punisher]})
    st.party[1].ultimate_gauge = 90
    view = settle(st)
    assert view.enemies[0].intent.name == "Punish the Gathering Storm"
    assert view.enemies[0].intent.target_id == "brom"


def test_hero_primed_condition_counts_tag_holders():
    comp = {
        "id": "spike_breaker", "archetype": "Punish", "timing": "proactive",
        "priority": 20,
        "condition": {"kind": "hero_primed", "op": ">=", "value": 1},
        "target_rule": "primed_hero", "telegraph": "Break the Spike",
        "verbs": [{"kind": "deal_damage", "amount": 2,
                   "target": {"mode": "chosen", "side": "ally",
                              "targeted": True}}]}
    enemy = {"id": "warden", "name": "Warden", "hp": 20, "level": 3,
             "power": 1, "components": [comp]}
    st = state_from_dict({"party": _two_heroes(), "enemies": [enemy]})
    assert settle(st).enemies[0].intent.name == "Warden Attack"
    st = state_from_dict({"party": _two_heroes(), "enemies": [enemy]})
    st.party[1].amplify_tags.append(AmplifyTag())
    view = settle(st)
    assert view.enemies[0].intent.name == "Break the Spike"
    assert view.enemies[0].intent.target_id == "brom"


def test_primed_hero_rule_falls_back_to_valuation():
    comp = {
        "id": "always_on", "archetype": "Punish", "timing": "proactive",
        "priority": 20, "target_rule": "primed_hero",
        "telegraph": "Hunting Strike",
        "verbs": [{"kind": "deal_damage", "amount": 2,
                   "target": {"mode": "chosen", "side": "ally",
                              "targeted": True}}]}
    enemy = {"id": "hunter", "name": "Hunter", "hp": 20, "level": 3,
             "power": 1, "components": [comp]}
    st = state_from_dict({"party": _two_heroes(), "enemies": [enemy]})
    view = settle(st)
    # Nobody primed: the rule still fires, on the valuation pick.
    assert view.enemies[0].intent.name == "Hunting Strike"
    assert view.enemies[0].intent.target_id == "alys"


def test_on_ultimate_cast_punish_fires_and_pays_the_caster():
    punisher = {
        "id": "tyrant", "name": "Tyrant", "hp": 30, "level": 4, "power": 2,
        "components": [{
            "id": "contempt", "archetype": "Punish", "timing": "reactive",
            "trigger": "on_ultimate_cast", "priority": 10,
            "target_rule": "trigger_source",
            "telegraph": "Price of Glory",
            "verbs": [{"kind": "deal_damage", "amount": 2,
                       "target": {"mode": "chosen", "side": "ally",
                                  "targeted": True}}]}]}
    party = [dict(_hero(hp=30, cid="alys"), ultimate=_ult_card())]
    st = state_from_dict({"party": party, "enemies": [punisher]})
    st.party[0].ultimate_gauge = 100
    ult = _pick(st, "use_ultimate", target_id="tyrant")
    assert ult is not None
    st = apply_action(st, ult)[0]
    st = apply_action(st, _pick(st, "pass"))[0]  # the caster passes — the answer comes
    # The punish reaction sits above the ultimate on the stack.
    assert [i.label for i in st.stack] == ["Doombolt (Ultimate)", "Price of Glory"]
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    assert st.party[0].hp == 28          # the tyrant made them pay…
    assert st.enemy("tyrant").hp == 25   # …but the limit break landed


def test_t70_counter_guardrail():
    def counter_comp(once=True):
        return {"id": "contempt", "archetype": "Counter", "timing": "reactive",
                "trigger": "on_ultimate_cast", "priority": 5,
                "once_per_encounter": once,
                "target_rule": "trigger_source",
                "telegraph": "Tyrant's Contempt",
                "verbs": [{"kind": "counter", "filter": "ability"}]}

    party = [dict(_hero(hp=30, cid="alys"), ultimate=_ult_card())]
    # Boss-only.
    with pytest.raises(ValueError, match="boss-only"):
        state_from_dict({"party": party, "enemies": [
            {"id": "minion", "name": "Minion", "hp": 5, "level": 2, "power": 1,
             "components": [counter_comp()]}]})
    # Once per encounter.
    with pytest.raises(ValueError, match="once_per_encounter"):
        state_from_dict({"party": party, "enemies": [
            {"id": "king", "name": "King", "hp": 30, "level": 6, "power": 3,
             "is_boss": True, "components": [counter_comp(once=False)]}]})
    # The legal form counters the ultimate on the stack — and the party could
    # have responded to the counter itself before it resolved.
    st = state_from_dict({"party": party, "enemies": [
        {"id": "king", "name": "King", "hp": 30, "level": 6, "power": 3,
         "is_boss": True, "components": [counter_comp()]}]})
    st.party[0].ultimate_gauge = 100
    st = apply_action(st, _pick(st, "use_ultimate", target_id="king"))[0]
    st = apply_action(st, _pick(st, "pass"))[0]  # the caster passes — the answer comes
    assert st.stack[-1].label == "Tyrant's Contempt"
    while st.stack and st.result is None:
        st = apply_action(st, _pick(st, "pass"))[0]
    assert st.enemy("king").hp == 30  # the limit break was cancelled
    assert any(e.type == "countered" and "Doombolt" in e.msg for e in st.log)


# ========================================================================== #
# §D12-3 — the autoplay balance harness
# ========================================================================== #
import json  # noqa: E402

from ltg_combat.autoplay import make_policy, run_adventure, run_one  # noqa: E402
from ltg_combat.autoplay.report import aggregate, diff_reports, render_report  # noqa: E402
from ltg_combat.autoplay.soak import soak  # noqa: E402
from ltg_combat.scenario import SCENARIO_A, SCENARIO_C  # noqa: E402
from ltg_core.schema import Character  # noqa: E402


def test_run_one_is_deterministic_for_the_full_repro_key():
    """§D12-3.4: identical (spec, policy version, seed) → an identical record."""
    p = make_policy("greedy")
    assert run_one(SCENARIO_A, p, seed=7) == run_one(SCENARIO_A, p, seed=7)
    r1, r2 = run_one(SCENARIO_A, p, seed=7), run_one(SCENARIO_A, p, seed=8)
    assert (r1["seed"], r2["seed"]) == (7, 8)
    assert r1["spec_hash"] == r2["spec_hash"]  # same spec, different seed


def test_policies_terminate_and_record_metrics():
    for name in ("random", "greedy"):
        rec = run_one(SCENARIO_C, make_policy(name), seed=3)
        assert rec["result"] in ("victory", "defeat", "anomaly")
        assert rec["rounds"] <= 51
        assert rec["policy_version"].startswith(name)
        mira = rec["characters"]["mira"]
        for key in ("damage_dealt", "damage_taken", "healing_done",
                    "cards_cast", "mana_granted", "mana_wasted",
                    "dead_in_hand"):
            assert isinstance(mira[key], int)


def test_greedy_hunts_the_race_target_first():
    """Rule 1/4: the marked enemy leads the kill order (§D12-3.3)."""
    spec = {
        "party": [_hero(hp=40, power=3, cid="hero")],
        "enemies": [_enemy("guard", hp=6, amount=0),
                    _enemy("ritualist", hp=6, amount=0)],
        "objective": {"kind": "race", "target": "ritualist", "turns": 5,
                      "fail": "defeat"},
    }
    rec = run_one(spec, make_policy("greedy"), seed=1)
    assert rec["result"] == "victory"
    assert rec["objective"]["status"] == "complete"
    died = rec["enemies"]
    assert died["ritualist"]["died_round"] <= died["guard"]["died_round"]


def test_greedy_defends_under_a_survive_objective():
    """Rule 6: survive → Defend bias (no finish available, hold the line)."""
    spec = {
        "party": [_hero(hp=40, power=1, cid="hero")],
        "enemies": [_enemy("wolf", hp=50, amount=2)],
        "objective": {"kind": "survive", "turns": 3},
    }
    rec = run_one(spec, make_policy("greedy"), seed=1)
    assert rec["result"] == "victory"  # held out to the timer


def test_spend_plans_produce_valid_builds():
    from ltg_combat.autoplay.policies import SPEND_PLANS
    lo = json.load(open("apps/deckbuilder/loadouts/soren.json"))
    base = dict(lo["character"], level=2)
    for plan in SPEND_PLANS:
        new, spent = make_policy("greedy", plan).spend_level_up(dict(base), 30)
        assert 0 <= spent <= 30
        Character.model_validate(new)  # every plan yields a legal build
    hp_new, _ = make_policy("greedy", "greedy-hp").spend_level_up(dict(base), 30)
    assert hp_new["hp"] == base["hp"] + 12  # 30 points = six +2 steps (T5-02)


def test_run_adventure_replicates_the_act_boundary():
    lo = json.load(open("apps/deckbuilder/loadouts/soren.json"))

    def act(name, hp, boss=False):
        e = {"id": "foe", "name": f"{name} Foe", "hp": hp, "level": 1,
             "power": 1, "intent": {"name": "Hit", "amount": 1,
                                    "action_type": "ability",
                                    "intent_type": "attack",
                                    "targeting": "lowest_hp_party",
                                    "mode": "melee"}}
        if boss:
            e["is_boss"] = True
        return {"name": name, "enemies": [e]}

    adv = {"name": "Tiny Keep",
           "acts": [act("Gate", 4), act("Yard", 5), act("Throne", 8, boss=True)]}
    p = make_policy("greedy", "greedy-power")
    rec = run_adventure(adv, [lo], p, seed=3)
    assert rec["kind"] == "adventure"
    assert rec["result"] == "victory"
    assert [a["result"] for a in rec["acts"]] == ["victory"] * 3
    assert rec == run_adventure(adv, [lo], p, seed=3)  # deterministic


def test_soak_smoke_slice():
    """§D12-3.7: the CI soak — seeded random games asserting engine invariants
    after every action. Exists to catch determinism breaks and crashes."""
    rep = soak([SCENARIO_A, SCENARIO_C], 200)
    assert rep["failures"] == []
    assert rep["results"]["victory"] + rep["results"]["defeat"] == 200


def test_report_flags_t72_outliers_and_diff_is_zero_on_itself():
    p = make_policy("greedy")
    records = [run_one(SCENARIO_A, p, seed=s) for s in range(20)]
    agg = aggregate(records)
    cell = agg["cells"][0]
    assert cell["n"] == 20
    assert 0.0 <= cell["win_rate"] <= 1.0
    # §A greedy sits outside the 30–85% band on standard → a T-72 flag fires
    # (generous thresholds are the point of the smoke slice, not a gate).
    if not 0.30 <= cell["win_rate"] <= 0.85:
        assert any("win rate" in f for f in cell["flags"])
    text = render_report(agg)
    assert "greedy-1.2.0" in text and "deltas" in text
    d = diff_reports(agg, agg)
    assert "+0%" in d and "MEASURING" not in d
    # A moved measuring stick is loudly flagged.
    agg2 = json.loads(json.dumps(agg))
    agg2["policy_versions"] = ["greedy-9.9.9"]
    assert "measuring stick moved" in diff_reports(agg, agg2)


def test_autoplay_cli_smoke_slice(tmp_path):
    """§D12-3.7: a 2-cell matrix through the real CLI — run, report, diff."""
    from ltg_combat.autoplay.cli import main
    spec_a = dict(SCENARIO_A)
    path = tmp_path / "scenario_a.json"
    path.write_text(json.dumps(spec_a))
    out_a = tmp_path / "a.jsonl"
    out_b = tmp_path / "b.jsonl"
    assert main(["run", "--content", str(path), "--seeds", "10",
                 "--policy", "greedy,random", "--out", str(out_a)]) == 0
    assert main(["run", "--content", str(path), "--seeds", "10",
                 "--policy", "greedy,random", "--out", str(out_b)]) == 0
    assert out_a.read_text() == out_b.read_text()  # byte-identical reruns
    assert main(["report", str(out_a)]) == 0
    assert main(["diff", str(out_a), str(out_b)]) == 0
