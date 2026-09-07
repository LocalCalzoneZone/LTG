"""Design Update 24 — campaigns, the interlude and the road ahead (§D24-3,
§D24-4, §D24-5, §B.2, §B.5).

A scenario game is a campaign; Act III's victory writes `scenario_complete`
and the ledger entry while the planner is queued at boss death; Continue
enters the interlude (act-shaped, no quest, the hooks foreshadowed as
topics); the inn's rest opens the rest screen instead of healing; choosing a
hook applies days, journals the bridge, keeps progression, clears scenario
knowledge, swaps towns (stored town state applied on return), generates a
new town from a seed with a worldbook page, and hands the note to the arc
writer; Quit at the menu leaves a `between` campaign Load reopens; the
newest save wins."""

from __future__ import annotations

import copy

import pytest

from ltg_game_server import app as game_app
from ltg_game_server import content, jobs, scenario_content as sc, world
from ltg_game_server.runs import RunManager
from ltg_game_server.scenario import ScenarioRun
from ltg_game_server.session import SessionManager

from tests.test_design_update_10 import _adventure, _isolate  # noqa: F401 (fixture)
from tests.test_design_update_17_scenario import (_accept_quest, _fake_adventure_generator,
                                                  _fake_materializer, _take_rewards,
                                                  _win_adventure)
from tests.test_design_update_17_towns import arc_raw, materialization_raw, town_raw


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TOWNS_DIR", tmp_path / "towns")
    monkeypatch.setattr(sc, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(sc, "TOWN_HIDDEN_FILE", tmp_path / "th.json")
    monkeypatch.setattr(sc, "SCENARIO_HIDDEN_FILE", tmp_path / "sh.json")
    monkeypatch.setattr(world, "WORLD_DIR", tmp_path / "world")
    # The two towns of this world: Hollowmere (home) and Bellhollow (a neighbour).
    sc.save_town(town_raw("Hollowmere"),
                 world_entry={"new_region": {"id": "the_fens", "name": "The Fens", "gist": "Wet and grey."},
                              "gist": "A fen-edge causeway town.", "notable": ["the Salt Shrine"]})
    sc.save_town(town_raw("Bellhollow"),
                 world_entry={"region_id": "the_fens", "gist": "A bell-foundry town up the causeway.",
                              "neighbours": [{"town_id": "hollowmere", "how": "two days north"}]})


@pytest.fixture
def runs(tmp_path):
    return RunManager(root=tmp_path / "saves")


def interlude_raw():
    """A valid planner reply for Hollowmere: no quest, one stay / one
    neighbour / one new hook, each foreshadowed by a resident."""
    return {
        "interlude": {
            "arrival": "You come back up the causeway to bells and dry bread.",
            "days": 5,
            "dialogues": {
                "marra_quill": {"root": "r", "nodes": {"r": {"speaker": "npc", "text": "A room, heroes?",
                                "choices": [{"label": "Take a room.", "effects": [{"kind": "rest"}]},
                                            {"label": "Not yet."}]}}},
                "sister_aud": {"root": "r", "nodes": {"r": {"speaker": "npc", "text": "The lake is quiet. Take this.",
                               "choices": [{"label": "Thank you.", "effects": [{"kind": "give_gold", "amount": 5}]}]}}},
            },
            "flavor": {"bram_toll": "Steel's still honest.", "ysolde_vane": "Lenses, heroes?",
                       "old_hesk": "Marsh-root, cheap today.", "corwen": "You did it, then."},
            "town_state_delta": {"the_salt_shrine": {"description": "The shrine, dry at last."}},
        },
        "hooks": [
            {"id": "stay_reeds", "kind": "stay", "narration": "You spend a fortnight in Hollowmere. Then the reeds sing again.",
             "bridge": "The morning the reeds sing, Sister Aud is at your door.", "days": 14,
             "foreshadow": [{"npc_id": "corwen", "ask": "Sleeping well?", "reply": "Not since the reeds started up again."}]},
            {"id": "bells", "kind": "neighbour", "town_id": "bellhollow",
             "narration": "You take the causeway north to Bellhollow, where the bells have stopped.",
             "bridge": "You arrive in Bellhollow under a silent tower.", "days": 4,
             "foreshadow": [{"npc_id": "bram_toll", "ask": "Any word from up the road?", "reply": "Bellhollow's bells have gone quiet."}]},
            {"id": "the_stair", "kind": "new", "town_seed": {"name": "Greywater", "line": "a mining camp above the fens"},
             "narration": "You follow the ore-carts up to Greywater, a camp that has lost its foreman.",
             "bridge": "You reach Greywater at dusk, the carts idle.", "days": 6,
             "foreshadow": [{"npc_id": "old_hesk", "ask": "Where's the ore from?", "reply": "Greywater, up the stair — though the carts have stopped."}]},
        ],
    }


def _fake_interlude(scen):
    town = scen.interlude_town()
    known = {e["town_id"] for e in world.list_entries()}
    return sc.validate_interlude(interlude_raw(), town, scen.town_id, world_towns=known)


def _fake_town_generator(note, attempts, world_ctx, seed, added_by=""):
    anchor = (world_ctx or {}).get("anchor_town_id") or "hollowmere"
    return sc.save_town(town_raw(seed["name"]),
                        world_entry={"region_id": (world_ctx or {}).get("region", {}).get("id", "the_fens"),
                                     "gist": f"{seed['name']} — {seed.get('line', '')}",
                                     "neighbours": [{"town_id": anchor, "how": "a day up the stair"}],
                                     "added_by": added_by})


def _make_arc_generator(seen):
    def gen(town, party, difficulty, previous_arcs=None, note="", **kw):
        seen.append({"town": town.get("name"), "note": note, **kw})
        arc = copy.deepcopy(arc_raw())
        arc["title"] = f"The Second Siege of {town.get('name')}"
        return sc.validate_arc(arc, town)
    return gen


def _drive(session, kind):
    if kind == "materialize":
        session.materialize_act()
    elif kind == "adventure_job":
        jobs.AdventureJobRunner(_fake_adventure_generator).start(session, None, None)
    elif kind == "interlude":
        runner = jobs.InterludeJobRunner()
        runner.runner = _fake_interlude
        runner.start(session, None)
    elif kind == "continue":
        game_app._continue_sync(session)


def _start(runs, seen_arcs=None):
    town = sc.town_detail("hollowmere")
    arc = sc.validate_arc(arc_raw(), town)
    loadouts = content.loadouts_for(["loadout_soren", "loadout_ys"])
    loadouts[0]["character"]["brief_situation"] = "low on coin, high on grudge"
    scen = ScenarioRun(town, arc, ["loadout_soren", "loadout_ys"], loadouts,
                       {"difficulty": "standard"}, town_id="hollowmere")
    scen.materializer = _fake_materializer
    scen.town_generator = _fake_town_generator
    scen.arc_generator = _make_arc_generator(seen_arcs if seen_arcs is not None else [])
    meta = runs.create_scenario_run(scen, name="Campaign test")
    session = SessionManager().create(None, name="Test", run_id=meta["run_id"], run_manager=runs, scenario=scen)
    session.async_hook = _drive
    session.scenario_enter_town(None)
    session.materialize_act()
    session.clients["c1"] = object()
    return session, scen, meta["run_id"]


def _play_act(session):
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    _win_adventure(session)
    _take_rewards(session)


def _finish_scenario(session):
    for _ in range(3):
        _play_act(session)


def _rest_at_inn(session):
    scen = session.scenario
    session.town_verb("c1", "visit", {"location_id": "the_drowned_lantern"})
    session.town_verb("c1", "talk", {"npc_id": "marra_quill"})
    conv = scen.town_snapshot()["conversation"]
    room = next(c for c in conv["choices"] if "room" in c["label"].lower())
    session.town_verb("c1", "choose", {"index": room["index"]})
    session.town_verb("c1", "end_talk", {})


# --------------------------------------------------------------------------- #
def test_a_scenario_game_creates_a_campaign(runs):
    session, scen, run_id = _start(runs)
    run = runs.store(run_id).read_run()
    assert run["kind"] == "campaign" and run["state"] == "in_scenario"
    assert run["scenario_count"] == 1 and run["current_scenario"] == 1
    assert run["ledger"] == [] and run["towns_visited"] == ["hollowmere"] and run["day"] == 1
    assert run["heroes"]["loadout_soren"]["situation"] == "low on coin, high on grudge"
    assert run["heroes"]["loadout_ys"] == {"situation": "", "chronicle": []}
    listing = runs.list_runs()[0]
    assert listing["kind"] == "campaign" and listing["state"] == "in_scenario"
    assert listing["newest_save_id"] == runs.newest_save(run_id)["save_id"]
    assert session.snapshot_for("c1")["scenario"]["day"] == 1


def test_act_three_victory_writes_the_ledger_and_queues_the_interlude(runs):
    session, scen, run_id = _start(runs)
    for _ in range(2):
        _play_act(session)
    assert scen.pending_interlude is None
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    _win_adventure(session)
    # The planner ran the moment the boss fell — before the spoils were taken.
    assert scen.rewards is not None and scen.pending_interlude is not None
    assert scen.interlude_job["state"] == "ready"
    assert scen.act_logs[2]["boss"] and scen.act_logs[2]["adventure"].startswith("Adventure for act")
    _take_rewards(session)
    assert scen.mode == "complete"
    saves = runs.run_detail(run_id)["saves"]
    assert saves[-1]["kind"] == "scenario_complete"
    run = runs.store(run_id).read_run()
    assert run["state"] == "between"
    assert len(run["ledger"]) == 1
    entry = run["ledger"][0]
    assert entry["scenario"] == 1 and entry["outcome"] == "victory" and entry["town_id"] == "hollowmere"
    assert [a["accepted"]["title"] for a in entry["acts"]] == ["Quest 1", "Quest 2", "Quest 3"]
    assert [a["refused"][0]["title"] for a in entry["acts"]] == [
        "Quest 1, the other way", "Quest 2, the other way", "Quest 3, the other way"]
    assert all(a["boss"] for a in entry["acts"])
    assert "defeated" in entry["one_liner"] and scen.day == 4     # three ride-outs
    snap = session.snapshot_for("c1")
    assert snap["mode"] == "complete" and snap["scenario"]["interlude_ready"] is True


def test_continue_enters_the_interlude_with_the_hooks_foreshadowed(runs):
    session, scen, run_id = _start(runs)
    _finish_scenario(session)
    session.town_verb("c1", "continue_campaign", {})
    assert scen.mode == "interlude"
    snap = session.snapshot_for("c1")
    assert snap["mode"] == "town" and snap["scenario"]["mode"] == "interlude"
    assert snap["scenario"]["act_title"] == "Between scenarios"
    assert snap["quest_log"]["act_title"] == "Between scenarios" and snap["quest_log"]["quest"]["status"] == "none"
    assert snap["interlude"]["rest_screen"] is False and len(snap["interlude"]["hooks"]) == 3
    assert [h["kind"] for h in snap["interlude"]["hooks"]] == ["stay", "neighbour", "new"]
    assert snap["interlude"]["hooks"][1]["town_name"] == "Bellhollow"
    assert snap["interlude"]["hooks"][2]["town_name"] == "Greywater"
    assert snap["interlude"]["situations"]["loadout_soren"] == "low on coin, high on grudge"
    assert "Between scenarios" in snap["splash"]["subtitle"] and scen.day == 4 + 5   # the interlude's days
    # The town remembers the victory (§D24-8.2).
    assert sc.find_location(scen.town, "the_salt_shrine")["description"] == "The shrine, dry at last."
    assert scen.campaign["town_state"]["hollowmere"]["overrides"]["the_salt_shrine"]["description"]
    # Every hook has already been heard in town: the foreshadow rides the topics.
    session.town_verb("c1", "visit", {"location_id": "tolls_forge"})
    session.town_verb("c1", "talk", {"npc_id": "bram_toll"})
    labels = [c["label"] for c in scen.town_snapshot()["conversation"]["choices"]]
    assert "Any word from up the road?" in labels
    session.town_verb("c1", "end_talk", {})
    # No road to ride between scenarios; the save is of kind `interlude`.
    with pytest.raises(ValueError):
        session.town_verb("c1", "start_adventure", {})
    assert runs.run_detail(run_id)["saves"][-1]["kind"] == "interlude"
    assert runs.store(run_id).read_run()["state"] == "interlude"


def test_rest_in_the_interlude_opens_the_rest_screen_and_does_not_heal(runs):
    session, scen, run_id = _start(runs)
    _finish_scenario(session)
    session.town_verb("c1", "continue_campaign", {})
    scen.hp["loadout_soren"] = 3
    _rest_at_inn(session)
    assert scen.rest_screen is True and scen.hp["loadout_soren"] == 3
    assert session.snapshot_for("c1")["interlude"]["rest_screen"] is True
    session.town_verb("c1", "rest_back", {})
    assert scen.rest_screen is False and scen.hp["loadout_soren"] == 3
    # The situation editor lives on the rest screen (§D24-7.4).
    session.town_verb("c1", "set_situation", {"character_id": "loadout_ys", "text": "wary of the reeds"})
    assert scen.situation_of("loadout_ys") == "wary of the reeds"
    assert scen.party_state()["members"][1]["situation"] == "wary of the reeds"


def test_choosing_stay_starts_the_next_scenario_in_the_same_town(runs):
    seen = []
    session, scen, run_id = _start(runs, seen)
    _finish_scenario(session)
    scen.flags["knows_watchtower"] = True
    session.town_verb("c1", "continue_campaign", {})
    scen.hp["loadout_soren"] = 3
    gold_before = dict(scen.gold)
    spent_before = dict(scen.spent)
    _rest_at_inn(session)
    day_before = scen.day
    session.town_verb("c1", "choose_hook", {"index": 0, "note": ""})
    assert scen.scenario_number == 2 and scen.act_index == 0 and scen.mode == "town"
    assert scen.town_id == "hollowmere" and scen.arc["title"] == "The Second Siege of Hollowmere"
    assert scen.day == day_before + 14
    assert scen.hp["loadout_soren"] is None                         # the time skip heals
    assert scen.gold == gold_before and scen.spent == spent_before  # progression kept
    # Scenario knowledge is gone; only "who the party has met here" carries
    # over, re-seeded from the town state (§D24-8.2).
    assert "knows_watchtower" not in scen.flags and not any(k.startswith("knows_") for k in scen.flags)
    assert all(k.startswith("_met_") for k in scen.flags) and scen.flags["_met_sister_aud"]
    assert scen.rest_screen is False and scen.act is not None
    # The bridge closed the previous scenario's journal.
    bridge = next(e for e in scen.journal if "reeds sing" in e["text"] and e["kind"] == "event")
    assert bridge["scenario"] == 1
    kinds = [s["kind"] for s in runs.run_detail(run_id)["saves"]]
    assert kinds[-3:] == ["interlude", "hooks_chosen", "act_start"]
    run = runs.store(run_id).read_run()
    assert run["scenario_count"] == 2 and run["state"] == "in_scenario"
    assert run["ledger"][0]["scenario"] == 1 and run["hooks"]["chosen"] == 0
    # The arc writer was handed the ledger, the party's layers, the world and the hook.
    assert seen[-1]["town"] == "Hollowmere"
    assert seen[-1]["ledger"][0]["outcome"] == "victory"
    assert seen[-1]["hook"]["kind"] == "stay" and "Sister Aud" in seen[-1]["hook"]["bridge"]
    assert seen[-1]["world_ctx"]["entry"]["town_id"] == "hollowmere"
    assert seen[-1]["party_state"]["members"][0]["situation"] == "low on coin, high on grudge"


def test_choosing_a_neighbour_swaps_the_town_and_stores_town_state(runs):
    session, scen, run_id = _start(runs)
    _finish_scenario(session)
    session.town_verb("c1", "continue_campaign", {})
    scen.flags["aud_blessed"] = True      # a custom flag set in Hollowmere
    _rest_at_inn(session)
    session.town_verb("c1", "choose_hook", {"index": 1})
    assert scen.town_id == "bellhollow" and scen.town["name"] == "Bellhollow"
    assert scen.campaign["towns_visited"] == ["hollowmere", "bellhollow"]
    assert scen.campaign["current_town_id"] == "bellhollow"
    left = scen.campaign["town_state"]["hollowmere"]
    assert left["flags"] == {"aud_blessed": True}
    assert "marra_quill" in left["met"] and "sister_aud" in left["met"]
    assert left["overrides"]["the_salt_shrine"]["description"] == "The shrine, dry at last."
    assert scen.flags == {}
    assert runs.store(run_id).read_run()["current_town_name"] == "Bellhollow"
    # Coming back: the stored state is composed onto Hollowmere again.
    scen.begin_next_scenario(sc.validate_arc(arc_raw(), sc.town_detail("hollowmere")),
                             sc.town_detail("hollowmere"), "hollowmere")
    assert scen.flags["town:aud_blessed"] is True and scen.flags["_met_marra_quill"] is True
    assert sc.find_location(scen.town, "the_salt_shrine")["description"] == "The shrine, dry at last."


def test_choosing_somewhere_new_generates_the_town_with_a_worldbook_page(runs):
    session, scen, run_id = _start(runs)
    _finish_scenario(session)
    session.town_verb("c1", "continue_campaign", {})
    _rest_at_inn(session)
    session.town_verb("c1", "choose_hook", {"index": 2})
    assert scen.town_id == "greywater" and sc.town_detail("greywater") is not None
    entry = world.entry_for("greywater")
    assert entry["region_id"] == "the_fens" and entry["added_by"].startswith("scenario:")
    assert entry["neighbours"] == [{"town_id": "hollowmere", "how": "a day up the stair"}]
    assert {n["town_id"] for n in world.entry_for("hollowmere")["neighbours"]} == {"bellhollow", "greywater"}


def test_the_fourth_card_reaches_the_arc_writer(runs):
    seen = []
    session, scen, run_id = _start(runs, seen)
    _finish_scenario(session)
    session.town_verb("c1", "continue_campaign", {})
    _rest_at_inn(session)
    session.town_verb("c1", "choose_hook", {
        "index": 3, "note": "the causeway is under water",
        "custom": {"kind": "neighbour", "town_id": "bellhollow"}})
    assert scen.town_id == "bellhollow"
    hook = seen[-1]["hook"]
    assert hook["custom"] is True and hook["kind"] == "neighbour"
    assert "under water" in hook["narration"] and seen[-1]["note"] == "the causeway is under water"
    # The custom card is validated: a new town needs a name, a neighbour a town.
    session2, scen2, _ = _start(runs)
    _finish_scenario(session2)
    session2.town_verb("c1", "continue_campaign", {})
    _rest_at_inn(session2)
    with pytest.raises(ValueError):
        session2.town_verb("c1", "choose_hook", {"index": 3, "custom": {"kind": "new"}})
    with pytest.raises(ValueError):
        session2.town_verb("c1", "choose_hook", {"index": 3, "custom": {"kind": "neighbour", "town_id": "atlantis"}})
    with pytest.raises(ValueError):
        session2.town_verb("c1", "choose_hook", {"index": 7})


def test_quit_at_the_menu_leaves_a_between_campaign_that_load_reopens(runs):
    session, scen, run_id = _start(runs)
    _finish_scenario(session)
    hooks_then = [h["id"] for h in scen.pending_interlude["hooks"]]
    # Quit: nothing else is pressed. The Load list shows a `between` campaign.
    row = runs.list_runs()[0]
    assert row["state"] == "between" and row["newest_save_id"] == runs.newest_save(run_id)["save_id"]
    scen2 = runs.load_scenario_save(run_id, row["newest_save_id"])
    assert scen2.mode == "complete" and scen2.pending_interlude is not None
    session2 = SessionManager().create(None, run_id=run_id, run_manager=runs, scenario=scen2)
    session2.async_hook = _drive
    assert session2.continue_campaign() is True
    assert scen2.mode == "interlude"
    assert [h["id"] for h in scen2.hooks()] == hooks_then       # the SAME three hooks
    assert scen2.campaign["ledger"][0]["scenario"] == 1


def test_a_continue_pressed_before_the_planner_returns_is_honoured(runs):
    session, scen, run_id = _start(runs)
    # Swallow the interlude request so the planner "is still writing".
    session.async_hook = lambda s, k: None if k == "interlude" else _drive(s, k)
    _finish_scenario(session)
    assert scen.pending_interlude is None and scen.interlude_job["state"] == "idle"
    session.town_verb("c1", "continue_campaign", {})
    assert scen.mode == "complete" and scen.continue_requested is True
    # The planner returns: the hand-over runs the continue at once.
    runner = jobs.InterludeJobRunner()
    runner.runner = _fake_interlude
    runner.start(session, None)
    assert scen.mode == "interlude" and scen.continue_requested is False


def test_newest_save_wins_after_loading_an_older_one(runs):
    session, scen, run_id = _start(runs)
    _play_act(session)
    saves = runs.run_detail(run_id)["saves"]
    older = saves[0]                     # the Act I arrival
    scen2 = runs.load_scenario_save(run_id, older["save_id"])
    session2 = SessionManager().create(None, run_id=run_id, run_manager=runs, scenario=scen2)
    session2.async_hook = _drive
    session2.clients["c1"] = object()
    session2.town_verb("c1", "save", {})     # playing on from the fork makes a NEWER save
    newest = runs.newest_save(run_id)
    assert newest["save_id"] != saves[-1]["save_id"]
    assert newest["label"].endswith("Act I · Town — the square")
    assert scen2.scenario_number == 1 and scen2.act_index == 0


def test_a_schema_one_run_loads_as_a_campaign(runs):
    session, scen, run_id = _start(runs)
    st = runs.store(run_id)
    run = st.read_run()
    for k in ("kind", "state", "scenario_count", "current_scenario", "ledger", "towns_visited",
              "current_town_id", "town_state", "heroes", "hooks", "day"):
        run.pop(k, None)
    run["schema_version"] = 1
    run["options"]["everquest"] = True
    st.write_run(run)
    save = runs.newest_save(run_id)
    snap = st.read_save(save["save_id"])
    snap["scenario"].pop("campaign", None)
    (st.saves_dir / f"{save['save_id']}.json").write_text(__import__("json").dumps(snap))
    meta = runs.list_runs()[0]
    assert meta["kind"] == "campaign" and meta["state"] == "in_scenario" and "everquest" not in meta["options"]
    scen2 = runs.load_scenario_save(run_id, save["save_id"])
    assert scen2.campaign["ledger"] == [] and set(scen2.campaign["heroes"]) == {"loadout_soren", "loadout_ys"}
    assert "everquest" not in scen2.options
