"""Design Update 17 — the scenario runtime (Phase 1 spine): town mode, dialogue
hooks, Quest Accept → job → adventure, the return to town, defeat/return
(Normal / Hardcore), Everquest, and scenario saves that reload."""

from __future__ import annotations

import copy

import pytest

from ltg_game_server import content, jobs, scenario_content as sc
from ltg_game_server.runs import RunManager
from ltg_game_server import scenario as sc_run
from ltg_game_server.scenario import ScenarioRun
from ltg_game_server.session import SessionManager

from tests.test_design_update_10 import _adventure, _isolate  # noqa: F401 (fixture)
from tests.test_design_update_17_towns import (arc_raw, materialization_raw, town_raw)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TOWNS_DIR", tmp_path / "towns")
    monkeypatch.setattr(sc, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(sc, "TOWN_HIDDEN_FILE", tmp_path / "th.json")
    monkeypatch.setattr(sc, "SCENARIO_HIDDEN_FILE", tmp_path / "sh.json")


@pytest.fixture
def runs(tmp_path):
    return RunManager(root=tmp_path / "saves")


def _fake_materializer(town, arc, act_index, party_state, prev=""):
    m = materialization_raw()
    m["quests"][0]["title"] = f"Quest {act_index + 1}"
    m["quests"][1]["title"] = f"Quest {act_index + 1}, the other way"
    if party_state.get("flags", {}).get("defeated_once"):
        m["arrival"] = "You limp back up the causeway."
    outline = arc["acts"][act_index]
    # The questgiver changes per act in the fixture arc; give each one the tree.
    m["dialogues"][outline["questgiver_npc"]] = m["dialogues"].pop("sister_aud", None) or \
        materialization_raw()["dialogues"]["sister_aud"]
    return sc.validate_materialization(m, town, outline)


def _fake_adventure_generator(character_ids, difficulty="standard", note="", **kw):
    """Persist the Update 10 test adventure under a fresh id (run_only)."""
    adv = _adventure()
    adv["run_only"] = True
    ctx = (kw.get("context") or {}).get("arc_context") or {}
    adv["name"] = f"Adventure for act {ctx.get('act_number', '?')}"
    return content.save_adventure(adv)


def _start(runs, options=None, materialization="fake"):
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    loadouts = content.loadouts_for(["loadout_soren", "loadout_ys"])
    scen = ScenarioRun(town, arc, ["loadout_soren", "loadout_ys"], loadouts,
                       options or {"difficulty": "standard"}, town_id="hollowmere")
    scen.materializer = _fake_materializer
    meta = runs.create_scenario_run(scen, name="Test scenario")
    sm = SessionManager()
    session = sm.create(None, name="Test", run_id=meta["run_id"], run_manager=runs, scenario=scen)
    session.async_hook = lambda s, kind: _drive(s, kind)
    session.scenario_enter_town(None if materialization == "fake" else materialization)
    if materialization == "fake":
        session.materialize_act()
    return session, scen, meta["run_id"]


def _drive(session, kind):
    """The test stand-in for app._scenario_async: everything inline."""
    if kind == "materialize":
        session.materialize_act()
    elif kind == "adventure_job":
        jobs.AdventureJobRunner(_fake_adventure_generator).start(session, None, None)
    elif kind == "new_arc":
        scen = session.scenario
        arc = sc.validate_arc(arc_raw(), scen.town)
        arc["title"] = "The Second Siege"
        session.new_arc(arc)
        session.materialize_act()


def _win_adventure(session):
    """Drive the running adventure to completion through its boundary gates —
    level-up screens and Phase Clear interludes alike (§D17-2.3)."""
    adv = session.adventure
    for _ in range(len(adv.phases)):
        session.state.result = "victory"
        adv.on_state_change(session.state)
        session._run_hooks()
        if adv.complete:
            break
        for live in list(adv.live_ids):
            session.seats[live] = "c1"
            session.confirm_level_up("c1", live, {})


def _confirm_act_end_level_up(session, client="c1"):
    """The act-end level-up screen queued behind the spoils (§D17-2.3): every
    seat presses confirm (spending nothing) and the party rides to town."""
    adv = session.adventure
    if adv is None or not adv.is_final_gate:
        return False
    for live in list(adv.live_ids):
        session.seats[live] = client
        session.confirm_level_up(client, live, {})
    return True


def _take_rewards(session, client="c1"):
    """The Rewards modal after Phase III (§D17-4.5): discard everything, accept."""
    scen = session.scenario
    if scen.rewards is None:
        return
    for i in range(len(scen.rewards["items"])):
        session.economy_verb(client, "reward_assign", {"index": i, "target": "discard"})
    session.economy_verb(client, "reward_accept", {})
    _confirm_act_end_level_up(session, client)


def _walk_to_questgiver(session, client="c1"):
    scen = session.scenario
    outline = scen.outline
    session.clients[client] = object()
    session.town_verb(client, "visit", {"location_id": outline["questgiver_location"]})
    session.town_verb(client, "talk", {"npc_id": outline["questgiver_npc"]})
    return scen.town_snapshot()["conversation"]


def _accept_quest(session, client="c1", which=0):
    """Take the ``which``-th offer on the questgiver's opening node."""
    scen = session.scenario
    conv = _walk_to_questgiver(session, client)
    offers = [c for c in conv["choices"] if c["party_wide"]]
    session.town_verb(client, "choose", {"index": offers[which]["index"]})
    return offers


def test_arrival_materializes_and_town_snapshot_shape(runs):
    session, scen, run_id = _start(runs)
    snap = session.snapshot_for("c1")
    assert snap["mode"] == "town" and snap["location"] is None
    assert snap["splash"]["kind"] == "town" and "causeway" in snap["splash"]["text"]
    assert [l["function"] for l in snap["town"]["locations"]][:4] == ["inn", "weaponsmith", "artificer", "apothecary"]
    assert snap["quest_log"]["quest"]["status"] == "offered"
    # The journal opens with the intro; the quest text is NOT shown until accepted.
    assert snap["quest_log"]["quest"]["text"] == "" and snap["quest_log"]["journal"][0]["kind"] == "intro"
    assert "villain" not in snap["quest_log"]
    assert snap["scenario"]["act_number"] == 1 and snap["scenario"]["acts_total"] == 3
    assert [p["id"] for p in snap["party_sheet"]] == ["loadout_soren", "loadout_ys"]
    assert snap["party_sheet"][0]["level"] == 1
    assert snap["party_sheet"][0]["gold"] == sc_run.STARTING_GOLD   # T-87: the opening purse
    # The arrival auto-saved.
    saves = runs.run_detail(run_id)["saves"]
    assert saves[-1]["kind"] == "act_start"
    assert saves[-1]["label"] == "Hollowmere · Scenario 1 · Act I · Town — arrival"


def test_location_splash_describes_the_room_not_an_npc_line(runs):
    # Walking into a room reads the ROOM (its interior scene, the same text the
    # interior art is painted from) — not a greeting lifted out of an NPC's
    # flavour line, which used to arrive as a snippet of a conversation nobody
    # had started.
    session, scen, _ = _start(runs)
    session.clients["c1"] = object()
    session.town_verb("c1", "visit", {"location_id": "tolls_forge"})
    splash = session.snapshot_for("c1")["splash"]
    loc = sc.find_location(scen.town, "tolls_forge")
    assert splash["kind"] == "location" and splash["title"] == loc["name"]
    assert splash["text"] == loc["interior_scene"]
    assert splash["text"] != scen.act["flavor"].get("bram_toll")


def test_the_town_wears_no_labels(runs):
    # Which location holds the questgiver, and who has a tree, are NOT in the
    # snapshot: the party finds out by walking in and talking (§D17-5.2).
    session, scen, _ = _start(runs)
    snap = session.snapshot_for("c1")
    for loc in snap["town"]["locations"]:
        assert "questgiver" not in loc and "has_dialogue" not in loc
    session.clients["c1"] = object()
    session.town_verb("c1", "visit", {"location_id": "the_salt_shrine"})
    for npc in session.snapshot_for("c1")["location"]["npcs"]:
        assert "questgiver" not in npc and "has_dialogue" not in npc


def test_only_one_npc_at_a_shop_keeps_the_counter(runs):
    town = sc.validate_town(town_raw())
    town["locations"][1]["npcs"].append(
        {"name": "Nessa Toll", "role": "apprentice", "persona": "Nessa sweeps and watches.",
         "portrait_desc": "A soot-smudged girl with a broom."})
    town = sc.validate_town(town)
    session, scen, _ = _start(runs)
    scen.town = town
    session.clients["c1"] = object()
    session.town_verb("c1", "visit", {"location_id": "tolls_forge"})
    npcs = session.snapshot_for("c1")["location"]["npcs"]
    assert [n["merchant"] for n in npcs] == [True, False]


def test_the_act_offers_several_quests_and_the_choice_steers_the_adventure(runs):
    session, scen, _ = _start(runs)
    conv = _walk_to_questgiver(session)
    offers = [c for c in conv["choices"] if c["party_wide"]]
    assert len(offers) >= 2                                   # a real choice
    assert len(scen.quest_options) == 2
    session.town_verb("c1", "choose", {"index": offers[1]["index"]})
    assert scen.quest["status"] == "accepted"
    assert scen.quest["title"] == "Quest 1, the other way"
    assert scen.quest["id"] == "the_shore_road"
    # The accepted approach — not the arc outline's — is what the adventure
    # generator is handed.
    theme = scen.adventure_context()["arc_context"]["act"]["adventure_theme"]
    assert "reed-shore at night" in theme
    assert scen.arc["acts"][0]["adventure_theme"] not in theme


def test_deferring_makes_the_npc_ask_again_next_time(runs):
    session, scen, _ = _start(runs)
    conv = _walk_to_questgiver(session)
    defer = next(c for c in conv["choices"] if "get back to you" in c["label"])
    assert defer["party_wide"] is False                        # nobody is bound by it
    session.town_verb("c1", "choose", {"index": defer["index"]})
    assert scen.conversation is None and not scen.flags.get("quest_accepted")
    assert scen.flags["deferred_sister_aud"] is True
    assert "think on it" in scen.journal[-1]["text"]
    # Walking back up: the NPC opens by asking, with every offer still standing.
    conv = _walk_to_questgiver(session)
    assert conv["text"].startswith("Well —")
    labels = [c["label"] for c in conv["choices"]]
    assert len([c for c in conv["choices"] if c["party_wide"]]) == 2
    assert any("Not yet" in l for l in labels)                 # and put it off again
    offers = [c for c in conv["choices"] if c["party_wide"]]
    session.town_verb("c1", "choose", {"index": offers[0]["index"]})
    assert scen.quest["status"] == "accepted"
    assert not any(f.startswith("deferred_") for f in scen.flags)


def test_an_npc_without_a_tree_still_holds_a_conversation(runs):
    # Every townsperson is worth walking up to: their greeting, then the topics
    # the town and the act gave them, each as something the party can ask about.
    session, scen, _ = _start(runs)
    session.clients["c1"] = object()
    session.town_verb("c1", "visit", {"location_id": "tolls_forge"})
    session.town_verb("c1", "talk", {"npc_id": "bram_toll"})
    conv = scen.town_snapshot()["conversation"]
    assert conv["text"] == "Steel's honest. Lakes aren't."
    labels = [c["label"] for c in conv["choices"]]
    assert labels == ["Heard anything off the water?", "Farewell."]
    session.town_verb("c1", "choose", {"index": 0})
    assert "fishers" in scen.town_snapshot()["conversation"]["text"]


def test_quest_accept_fires_hooks_saves_and_generates_the_adventure(runs):
    session, scen, run_id = _start(runs)
    _accept_quest(session)
    assert scen.quest["status"] == "accepted" and scen.flags["quest_accepted"]
    assert scen.adventure_unlocked
    kinds = [e["kind"] for e in scen.journal]
    assert kinds[0] == "intro" and "heard" in kinds and "quest" in kinds
    assert scen.quest_log()["quest"]["text"]  # revealed once agreed
    # The job ran inline (test driver) → ready with a frozen adventure.
    assert scen.adventure_job["state"] == "ready" and scen.adventure_ready
    assert scen.adventure_detail["name"] == "Adventure for act 1"
    kinds = [s["kind"] for s in runs.run_detail(run_id)["saves"]]
    assert kinds == ["act_start", "quest_accept"]
    # The generated adventure is a run's — out of the New Game picker.
    assert all(not a.get("run_only") for a in content.list_adventures())
    assert any(a["name"].startswith("Adventure for act") for a in content.list_adventures(include_run_only=True))
    # The conversation continued to the "go" node; a flavour choice ends it.
    conv = session.snapshot_for("c1")["conversation"]
    assert conv["node_id"] == "go"
    session.town_verb("c1", "choose", {"index": 0})
    assert scen.gold["loadout_soren"] == sc_run.STARTING_GOLD + 10   # the give_gold hook
    assert scen.flags.get("aud_blessed")
    assert session.snapshot_for("c1")["conversation"] is None


def test_start_adventure_win_and_return_to_next_act(runs):
    session, scen, run_id = _start(runs)
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    assert session.state is not None and scen.mode == "adventure"
    assert session.snapshot_for("c1")["mode"] == "adventure"
    assert set(session.seats) == set(session.adventure.live_ids)   # seats remapped
    _win_adventure(session)
    assert scen.rewards is not None                                # the spoils first
    _take_rewards(session)
    # Back in town, Act II, materialized inline by the driver; the act saved.
    assert scen.mode == "town" and scen.act_index == 1 and session.state is None
    assert scen.flags["act_1_complete"] and scen.quest["title"] == "Quest 2"
    assert scen.completed_acts[0]["quest"] == "Quest 1"
    assert set(session.seats) == {"loadout_soren", "loadout_ys"}
    # Two level-ups earned → level 3, 60 gold each (T-85), points carried.
    sheet = session.snapshot_for("c1")["party_sheet"]
    assert sheet[0]["level"] == 3 and sheet[0]["earned_points"] == 60
    assert sheet[0]["gold"] == sc_run.STARTING_GOLD + 60
    kinds = [s["kind"] for s in runs.run_detail(run_id)["saves"]]
    assert kinds == ["act_start", "quest_accept", "adventure_start", "phase_boundary",
                     "phase_boundary", "adventure_end", "rewards", "act_start"]
    labels = [s["label"] for s in runs.run_detail(run_id)["saves"]]
    assert labels[2] == "Hollowmere · Scenario 1 · Act I · Adventure, Phase 1"
    assert labels[-1] == "Hollowmere · Scenario 1 · Act II · Town — arrival"


def test_town_save_reloads_in_town_with_the_same_act_and_adventure(runs):
    session, scen, run_id = _start(runs)
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "save", {})       # manual Save Game
    saves = runs.run_detail(run_id)["saves"]
    assert saves[-1]["auto"] is False and saves[-1]["label"].endswith("Town — the square")
    scen2 = runs.load_scenario_save(run_id, saves[-1]["save_id"])
    assert scen2.mode == "town" and scen2.act["quest"]["title"] == "Quest 1"
    assert scen2.adventure_detail["name"] == scen.adventure_detail["name"]  # the SAME adventure
    assert scen2.adventure_unlocked and scen2.adventure_job["state"] == "ready"
    assert scen2.quest["status"] == "accepted"
    # An adventure-mode save reloads through load_save + load_scenario_save.
    session.town_verb("c1", "start_adventure", {})
    saves = runs.run_detail(run_id)["saves"]
    assert saves[-1]["kind"] == "adventure_start"
    _meta, adv, state, _p, _a, eid = runs.load_save(run_id, saves[-1]["save_id"])
    scen3 = runs.load_scenario_save(run_id, saves[-1]["save_id"])
    assert scen3.mode == "adventure" and adv is not None and eid.endswith("__phase1")


def test_normal_defeat_returns_to_town_with_defeated_once(runs):
    session, scen, run_id = _start(runs)
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    session.state.result = "defeat"
    session._run_hooks()
    # The defeat splash holds: still in the fight's session, loss suppressed,
    # until the party presses on ("forced to flee").
    assert scen.defeat_pending and session.public_result() is None and session.state is not None
    assert session.snapshot_for("c1")["defeat_pending"] is True
    session.economy_verb("c1", "flee", {})
    assert scen.mode == "town" and scen.flags["defeated_once"] and scen.act_index == 0
    assert any("forced to flee" in e["text"] for e in scen.journal)
    assert scen.quest["status"] == "offered"           # not advanced; re-offered
    assert "limp" in session.snapshot_for("c1")["splash"]["text"]  # defeat-aware materialization
    assert scen.adventure_detail is None and not scen.adventure_unlocked
    # The bloodied branch is visible now.
    outline = scen.outline
    session.town_verb("c1", "visit", {"location_id": outline["questgiver_location"]})
    session.town_verb("c1", "talk", {"npc_id": outline["questgiver_npc"]})
    labels = [c["label"] for c in session.snapshot_for("c1")["conversation"]["choices"]]
    assert "We came back bloodied." in labels
    # Accepting again generates a FRESH adventure.
    accept = next(c for c in session.snapshot_for("c1")["conversation"]["choices"] if c["party_wide"])
    session.town_verb("c1", "choose", {"index": accept["index"]})
    assert scen.adventure_ready


def test_hardcore_defeat_ends_the_run(runs):
    session, scen, run_id = _start(runs, options={"difficulty": "hard", "hardcore": True})
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    session.state.result = "defeat"
    session._run_hooks()
    session.economy_verb("c1", "flee", {})
    assert scen.dead and scen.mode == "complete"
    assert session.snapshot_for("c1")["mode"] == "complete"
    assert runs.list_runs()[0]["dead"] is True


def test_standard_ends_after_act_three_and_everquest_rolls_a_new_arc(runs):
    for everquest in (False, True):
        session, scen, run_id = _start(runs, options={"everquest": everquest})
        for act in range(3):
            _accept_quest(session)
            session.town_verb("c1", "leave", {})
            session.town_verb("c1", "start_adventure", {})
            _win_adventure(session)
            _take_rewards(session)
        if everquest:
            assert scen.mode == "town" and scen.scenario_number == 2 and scen.act_index == 0
            assert scen.arc["title"] == "The Second Siege"
            assert scen.previous_arcs[0]["title"] == "The Siege of Hollowmere"
            assert scen.flags.get("act_1_complete") is None
        else:
            assert scen.mode == "complete" and session.pending_transition == "scenario_complete"


def test_all_players_confirmation_gates_party_wide_moves(runs):
    session, scen, run_id = _start(runs)
    session.clients["c1"] = object()
    session.clients["c2"] = object()
    session.town_verb("c1", "visit", {"location_id": "the_salt_shrine"})
    assert scen.location_id is None and session.confirm is not None
    payload = session.snapshot_for("c2")["confirm"]
    assert payload["kind"] == "visit" and not payload["answered"] and payload["yes_count"] == 1
    session.answer_confirm("c2", payload["id"], True)
    assert session.confirm is None and scen.location_id == "the_salt_shrine"
    # A "no" cancels; the initiator can cancel too.
    session.town_verb("c1", "leave", {})
    session.answer_confirm("c2", session.confirm["id"], False)
    assert session.confirm is None and scen.location_id == "the_salt_shrine"
    session.town_verb("c2", "leave", {})
    session.cancel_confirm("c2", session.confirm["id"])
    assert session.confirm is None
    # Timeout → yes.
    session.town_verb("c2", "leave", {})
    session.confirm["deadline"] -= 100
    session.expire_confirm(session.confirm["id"])
    assert scen.location_id is None


def _pregen_session(runs, adventure_id, quest_id, generated=None):
    """A scenario def with Act I materialized + its adventure already written."""
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = sc.validate_materialization(materialization_raw(), town, arc["acts"][0])
    loadouts = content.loadouts_for(["loadout_soren"])
    scen = ScenarioRun(town, arc, ["loadout_soren"], loadouts, {}, town_id="hollowmere",
                       scenario_id="pregen")
    scen.materializer = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM call"))
    meta = runs.create_scenario_run(scen)
    session = SessionManager().create(None, run_id=meta["run_id"], run_manager=runs, scenario=scen)
    pending = {"adventure_id": adventure_id, "quest_id": quest_id}

    def hook(s, kind):
        """The app's `_scenario_async` for this job, in miniature."""
        if kind != "adventure_job":
            return _drive(s, kind)
        pre = s.pregenerated_act1
        if pre is not None:
            s.pregenerated_act1 = None
            if not pre["quest_id"] or pre["quest_id"] == s.scenario.quest.get("id"):
                jobs.RUNNER.prepare_pregenerated(s, pre["adventure_id"])
                return
        def gen(*a, **kw):
            if generated is not None:
                generated.append(kw.get("context"))
            return _fake_adventure_generator(*a, **kw)

        jobs.AdventureJobRunner(gen).start(s, None, None)

    session.async_hook = hook
    session.scenario_enter_town(m)
    session.pregenerated_act1 = pending
    return session, scen


def test_pregenerated_scenario_act_one_is_instant(runs):
    """Take the option Act I was written for and there is no generation call at
    all — the pre-written adventure is frozen into the run and the job is ready."""
    adv_meta = _fake_adventure_generator([], context={"arc_context": {"act_number": 1}})
    session, scen = _pregen_session(runs, adv_meta["id"], "the_lantern_goes_out")
    assert scen.adventure_job["state"] == "idle" and not scen.adventure_ready
    _accept_quest(session, which=0)
    assert scen.adventure_ready and scen.adventure_id == adv_meta["id"]


def test_pregenerated_act_one_is_dropped_when_the_party_takes_the_other_road(runs):
    """The pre-written adventure belongs to ONE of Act I's options; any other
    answer generates its own, so the ride out always follows the choice."""
    adv_meta = _fake_adventure_generator([], context={"arc_context": {"act_number": 1}})
    generated = []
    session, scen = _pregen_session(runs, adv_meta["id"], "the_lantern_goes_out", generated)
    _accept_quest(session, which=1)
    assert scen.quest["id"] == "the_shore_road"
    assert scen.adventure_ready and session.pregenerated_act1 is None
    # A fresh adventure was written, for the road the party actually took.
    assert len(generated) == 1
    assert "reed-shore at night" in generated[0]["arc_context"]["act"]["adventure_theme"]


# --------------------------------------------------------------------------- #
# The level-up schedule (§D17-2.3)
# --------------------------------------------------------------------------- #
def _play_act(session, take_rewards=True):
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    _win_adventure(session)
    if take_rewards:
        _take_rewards(session)


def test_points_are_earned_every_phase_but_spent_on_a_schedule(runs):
    """Opening act: +10 / +20 / +30 as the phases fall, a level-up screen after
    Phase I, a Phase Clear interlude after Phase II, and the act-end screen
    queued behind the spoils (§D17-2.3)."""
    session, scen, _run_id = _start(runs)
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    adv = session.adventure
    soren = adv.live_ids[0]
    assert adv.screen_phases == {0} and adv.final_screen is True

    # Phase I won: +10 in the pool, level 2 reached, and a SPEND screen.
    session.state.result = "victory"
    adv.on_state_change(session.state)
    session._run_hooks()
    assert adv.earned[soren] == 10 and adv.banked[soren] == 10
    assert adv.gate_kind == "levelup" and adv.next_level() == 2
    assert session.public_result() is None
    for live in list(adv.live_ids):
        session.seats[live] = "c1"
        session.confirm_level_up("c1", live, {})
    assert adv.phase_index == 1

    # Phase II won: +20 banks, but the boundary is an INTERLUDE — nothing to buy.
    session.state.result = "victory"
    adv.on_state_change(session.state)
    session._run_hooks()
    assert adv.earned[soren] == 30 and adv.banked[soren] == 30
    assert adv.gate_kind == "interlude"
    with pytest.raises(ValueError, match="interlude"):
        adv.confirm_level_up(soren, {"hp": int(adv.loadouts[0]["character"]["hp"]) + 2})
    for live in list(adv.live_ids):
        session.seats[live] = "c1"
        session.confirm_level_up("c1", live, {})
    assert adv.phase_index == 2

    # Phase III won: +30, and the spoils come FIRST — the level-up is queued.
    session.state.result = "victory"
    adv.on_state_change(session.state)
    session._run_hooks()
    assert adv.earned[soren] == 60 and adv.complete
    assert scen.act_wrapup == "rewards" and scen.rewards is not None
    assert adv.level_up is None                      # not yet: the spoils are open
    _take_rewards(session)
    # 60 points and 60 gold for the act, and the party is in town for Act II.
    assert scen.mode == "town" and scen.act_index == 1
    assert scen.earned["loadout_soren"] == 60
    assert scen.gold["loadout_soren"] == sc_run.STARTING_GOLD + 60
    assert scen.levels() == [3, 3]


def test_later_acts_spend_only_at_the_act_end_screen(runs):
    session, scen, _run_id = _start(runs)
    _play_act(session)                                # Act I
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    adv = session.adventure
    assert adv.screen_phases == set() and adv.final_screen is True
    kinds = []
    for _ in range(2):
        session.state.result = "victory"
        adv.on_state_change(session.state)
        session._run_hooks()
        kinds.append(adv.gate_kind)
        for live in list(adv.live_ids):
            session.seats[live] = "c1"
            session.confirm_level_up("c1", live, {})
    assert kinds == ["interlude", "interlude"]        # no mid-adventure shopping
    session.state.result = "victory"
    adv.on_state_change(session.state)
    session._run_hooks()
    soren = adv.live_ids[0]
    # A whole act's 60 points arrive in one screen — on top of Act I's,
    # which this party (a test that buys nothing) also banked.
    assert adv.banked[soren] == 120 and adv.earned[soren] == 120
    _take_rewards(session)
    assert scen.earned["loadout_soren"] == 120
    assert scen.gold["loadout_soren"] == sc_run.STARTING_GOLD + 120
    assert scen.levels() == [4, 4]                    # T-78: 120 → level 4


def test_the_closing_act_has_an_end_screen_only_in_everquest(runs):
    for everquest, expected in ((False, False), (True, True)):
        session, scen, _run_id = _start(runs, options={"everquest": everquest})
        for _ in range(2):
            _play_act(session)
        assert scen.act_index == 2 and scen.is_last_act()
        assert scen.gate_policy()["final_screen"] is expected
        _accept_quest(session)
        session.town_verb("c1", "leave", {})
        session.town_verb("c1", "start_adventure", {})
        _win_adventure(session)
        assert scen.rewards is not None
        _take_rewards(session)
        # Points are earned either way; only Everquest gets to spend them.
        assert scen.earned["loadout_soren"] == 180
        if everquest:
            assert scen.scenario_number == 2 and scen.act_index == 0
            assert scen.banked["loadout_soren"] <= 180
        else:
            assert scen.mode == "complete"


def test_the_sheet_carries_the_level_progress_band(runs):
    session, scen, _run_id = _start(runs)
    row = scen.party_block()[0]
    assert row["earned_points"] == 0 and row["level_floor"] == 0
    assert row["level_ceiling"] == 10 and row["points_to_next_level"] == 10
    _play_act(session)
    row = scen.party_block()[0]
    assert row["level"] == 3 and row["earned_points"] == 60
    assert (row["level_floor"], row["level_ceiling"]) == (60, 105)
    assert row["points_to_next_level"] == 45


def test_a_reload_inside_the_act_wrapup_resumes_it(runs):
    """A save taken between the spoils and the act-end level-up screen comes
    back to that screen — not to a won adventure with nothing driving it, and
    not to a second roll of the spoils (§D17-2.3)."""
    session, scen, run_id = _start(runs)
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    _win_adventure(session)
    for i in range(len(scen.rewards["items"])):
        session.economy_verb("c1", "reward_assign", {"index": i, "target": "discard"})
    session.economy_verb("c1", "reward_accept", {})     # the "rewards" save is here
    assert scen.act_wrapup == "levelup" and session.adventure.is_final_gate

    row = [s for s in runs.run_detail(run_id)["saves"] if s["kind"] == "rewards"][-1]
    scen2 = runs.load_scenario_save(run_id, row["save_id"])
    _meta, adv2, state2, portraits, art, eid = runs.load_save(run_id, row["save_id"])
    assert scen2.act_wrapup == "rewards" and scen2.rewards is None   # spoils placed
    scen2.adopt_adventure(adv2)                                      # what app.py does
    session2 = SessionManager().create(state2, name="reload", portraits=portraits,
                                       encounter_id=eid, art=art, adventure=adv2,
                                       run_id=run_id, run_manager=runs, scenario=scen2)
    session2._scenario_transitions()
    assert adv2.is_final_gate and scen2.act_wrapup == "levelup"
    assert adv2.earned[adv2.live_ids[0]] == 60 and scen2.rewards is None
    assert session2.public_result() is None
    for live in list(adv2.live_ids):
        session2.seats[live] = "c1"
        session2.confirm_level_up("c1", live, {})
    assert scen2.mode == "town" and scen2.act_index == 1
