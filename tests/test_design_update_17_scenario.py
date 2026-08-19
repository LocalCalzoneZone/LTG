"""Design Update 17 — the scenario runtime (Phase 1 spine): town mode, dialogue
hooks, Quest Accept → job → adventure, the return to town, defeat/return
(Normal / Hardcore), Everquest, and scenario saves that reload."""

from __future__ import annotations

import copy

import pytest

from ltg_game_server import content, jobs, scenario_content as sc
from ltg_game_server.runs import RunManager
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
    m["quest"]["title"] = f"Quest {act_index + 1}"
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
    """Drive the running adventure to completion through the level-up gates."""
    scen = session.scenario
    adv = session.adventure
    for _ in range(2):
        session.state.result = "victory"
        adv.on_state_change(session.state)
        session._run_hooks()
        for live in list(adv.live_ids):
            session.seats[live] = "c1"
            session.confirm_level_up("c1", live, {})
    session.state.result = "victory"
    adv.on_state_change(session.state)
    session._run_hooks()


def _take_rewards(session, client="c1"):
    """The Rewards modal after Phase III (§D17-4.5): discard everything, accept."""
    scen = session.scenario
    if scen.rewards is None:
        return
    for i in range(len(scen.rewards["items"])):
        session.economy_verb(client, "reward_assign", {"index": i, "target": "discard"})
    session.economy_verb(client, "reward_accept", {})


def _accept_quest(session, client="c1"):
    scen = session.scenario
    outline = scen.outline
    session.clients[client] = object()
    session.town_verb(client, "visit", {"location_id": outline["questgiver_location"]})
    session.town_verb(client, "talk", {"npc_id": outline["questgiver_npc"]})
    conv = scen.town_snapshot()["conversation"]
    accept = next(c for c in conv["choices"] if c["party_wide"] and "go" in c["label"].lower())
    session.town_verb(client, "choose", {"index": accept["index"]})


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
    assert snap["party_sheet"][0]["level"] == 1 and snap["party_sheet"][0]["gold"] == 0
    # The arrival auto-saved.
    saves = runs.run_detail(run_id)["saves"]
    assert saves[-1]["kind"] == "act_start"
    assert saves[-1]["label"] == "Hollowmere · Scenario 1 · Act I · Town — arrival"


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
    assert scen.gold["loadout_soren"] == 10 and scen.flags.get("aud_blessed")
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
    assert sheet[0]["level"] == 3 and sheet[0]["gold"] == 60 and sheet[0]["earned_points"] == 60
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


def test_pregenerated_scenario_act_one_is_instant(runs):
    """A scenario def with Act I materialized + its adventure: no generation
    call at all — the job is ready on arrival."""
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    adv_meta = _fake_adventure_generator([], context={"arc_context": {"act_number": 1}})
    m = sc.validate_materialization(materialization_raw(), town, arc["acts"][0])
    loadouts = content.loadouts_for(["loadout_soren"])
    scen = ScenarioRun(town, arc, ["loadout_soren"], loadouts, {}, town_id="hollowmere",
                       scenario_id="pregen")
    scen.materializer = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM call"))
    meta = runs.create_scenario_run(scen)
    session = SessionManager().create(None, run_id=meta["run_id"], run_manager=runs, scenario=scen)
    session.async_hook = lambda s, kind: None if kind == "adventure_job" else _drive(s, kind)
    session.scenario_enter_town(m)
    jobs.RUNNER.prepare_pregenerated(session, adv_meta["id"])
    assert scen.adventure_job["state"] == "ready" and not scen.adventure_ready  # not unlocked yet
    _accept_quest(session)
    assert scen.adventure_ready
