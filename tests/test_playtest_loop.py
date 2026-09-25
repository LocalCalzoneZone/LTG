"""Roadmap M3.1–M3.4 — the playtest loop's tools.

- M3.3 the playtest profile: one switch routes every text task to the
  playtest model (the Deckbuilder's flavour too) and idles the automatic art;
- M3.4 the tape: record replies, replay them by prompt hash (or the closest
  same-kind prompt), replay-only never calls out and needs no key;
- M3.2 autopilot: the autoplay policy plays a live session's fight;
- M3.1 jump-to states: every state builds through the real scenario code,
  loads, and leaves the content library untouched.

The LLM is never called: the transport is replaced by a counter."""

from __future__ import annotations

import asyncio
import json

import pytest

from ltg_game_server import app as game_app
from ltg_game_server import autopilot, content, devstates, llm, tape
from ltg_game_server.runs import RunManager
from ltg_game_server.session import SessionManager


@pytest.fixture(autouse=True)
def _clean_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm_settings.json")
    monkeypatch.setattr(tape, "TAPE_DIR", tmp_path / "tape")
    monkeypatch.delenv("LTG_PLAYTEST", raising=False)
    monkeypatch.delenv("LTG_LLM_TAPE", raising=False)


@pytest.fixture
def live(monkeypatch):
    """The transport: counts calls and answers with a numbered reply."""
    calls = []

    def fake_live(api_key, model, messages, max_tokens, timeout):
        calls.append({"model": model, "messages": messages})
        return json.dumps({"n": len(calls)})
    monkeypatch.setattr(llm, "_live_chat", fake_live)
    return calls


def _msgs(user, system="sys"):
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------- #
# M3.3 — the playtest profile
# --------------------------------------------------------------------------- #
def test_the_playtest_profile_routes_every_task_to_the_playtest_model():
    llm.save_settings({"model": "anthropic/claude-opus-5",
                       "task_models": {"adventures": "anthropic/claude-opus-5-fast"}})
    assert llm.model_for("adventures") == "anthropic/claude-opus-5-fast"
    llm.save_settings({"playtest": True})
    for task in ("encounters", "adventures", "towns", "scenarios"):
        assert llm.model_for(task) == llm.PLAYTEST_MODEL
    llm.save_settings({"playtest_model": "google/gemini-3.8-flash"})
    assert llm.model_for("towns") == "google/gemini-3.8-flash"
    llm.save_settings({"playtest": False})
    assert llm.model_for("adventures") == "anthropic/claude-opus-5-fast"


def test_the_environment_forces_the_profile_without_writing_it(monkeypatch):
    monkeypatch.setenv("LTG_PLAYTEST", "1")
    assert llm.playtest_on() and llm.public_settings()["playtest_forced"]
    llm.save_settings({"model": "openai/gpt-5.6-sol"})       # any save
    on_disk = json.loads(llm.SETTINGS_PATH.read_text())
    assert on_disk["playtest"] is False                        # the env was not persisted


def test_the_deckbuilder_flavour_follows_the_profile(tmp_path, monkeypatch):
    from ltg_deckbuilder import flavour
    (tmp_path / "llm_settings.json").write_text(json.dumps(
        {"model": "anthropic/claude-opus-5", "playtest": True}))
    assert flavour.load_llm_settings(tmp_path)["model"] == flavour.PLAYTEST_MODEL == llm.PLAYTEST_MODEL
    (tmp_path / "llm_settings.json").write_text(json.dumps({"model": "anthropic/claude-opus-5"}))
    assert flavour.load_llm_settings(tmp_path)["model"] == "anthropic/claude-opus-5"
    monkeypatch.setenv("LTG_PLAYTEST", "1")
    assert flavour.load_llm_settings(tmp_path)["model"] == flavour.PLAYTEST_MODEL


def test_the_profile_idles_the_automatic_art(monkeypatch):
    from ltg_game_server import art

    def boom(*a, **kw):
        raise AssertionError("art was queued under the playtest profile")
    monkeypatch.setattr(art, "scenario_cast_art_items", boom)
    monkeypatch.setattr(art, "spoil_art_items", boom)

    class _Sc:
        arc = {"cast": [{"id": "x"}]}
        town = {"scene": ""}
        scenario_number = 1
        act_index = 0

        def spoils(self):
            return [{"id": "item"}]

    class _Session:
        scenario = _Sc()
        run_id = "r"
    monkeypatch.setenv("LTG_PLAYTEST", "1")
    game_app._queue_cast_art(_Session())
    game_app._queue_spoils_art(_Session())


def test_unknown_tape_modes_and_models_are_refused():
    with pytest.raises(ValueError):
        llm.save_settings({"tape": "sometimes"})
    with pytest.raises(ValueError):
        llm.save_settings({"playtest_model": "nope/nope"})
    pub = llm.public_settings()
    assert [m["id"] for m in pub["tape_modes"]] == list(tape.TAPE_MODES)
    assert pub["tape"] == "off" and pub["playtest"] is False


# --------------------------------------------------------------------------- #
# M3.4 — the tape
# --------------------------------------------------------------------------- #
def test_off_records_nothing(live):
    llm._chat("sk", "m", _msgs("hello"), kind="town")
    assert tape.summary() == {}


def test_record_then_replay_answers_without_a_call(live):
    llm.save_settings({"tape": "record"})
    first = llm._chat("sk", "m", _msgs("the act prompt"), kind="act")
    assert len(live) == 1 and tape.summary() == {"act": 1}
    llm.save_settings({"tape": "replay"})
    assert llm._chat("sk", "other-model", _msgs("the act prompt"), kind="act") == first
    assert len(live) == 1                                     # answered from the tape


def test_replay_falls_back_to_the_closest_prompt_of_the_same_kind(live):
    llm.save_settings({"tape": "record"})
    base = "\n".join(f"line {i}" for i in range(20))
    first = llm._chat("sk", "m", _msgs(base), kind="arc")
    llm.save_settings({"tape": "replay"})
    # A fresh roll or a new ledger line changes one line of twenty: close enough.
    assert llm._chat("sk", "m", _msgs(base + "\nsignature: a new roll"), kind="arc") == first
    assert len(live) == 1
    # Another kind never borrows it; a different prompt goes live and is recorded.
    llm._chat("sk", "m", _msgs(base), kind="town")
    llm._chat("sk", "m", _msgs("something else entirely"), kind="arc")
    assert len(live) == 3 and tape.summary() == {"arc": 2, "town": 1}


def test_replay_matches_the_repair_depth(live):
    llm.save_settings({"tape": "record"})
    llm._chat("sk", "m", _msgs("prompt"), kind="act")
    repair = _msgs("prompt") + [{"role": "assistant", "content": "bad"},
                                {"role": "user", "content": "That output was rejected: x"}]
    fixed = llm._chat("sk", "m", repair, kind="act")
    llm.save_settings({"tape": "replay"})
    assert llm._chat("sk", "m", repair, kind="act") == fixed
    assert len(live) == 2


def test_replay_only_never_calls_out_and_needs_no_key(live):
    llm.save_settings({"tape": "record"})
    rec = llm._chat("sk", "m", _msgs("known"), kind="town")
    llm.save_settings({"tape": "replay_only"})
    settings = llm.load_settings()
    assert settings["api_key"] == ""
    llm.require_key(settings)                                 # replay needs no key
    assert llm._chat("", "m", _msgs("known"), kind="town") == rec
    with pytest.raises(ValueError, match="replay only"):
        llm._chat("", "m", _msgs("never seen"), kind="town")
    assert len(live) == 1


def test_a_live_miss_still_needs_a_key(live):
    llm.save_settings({"tape": "replay"})
    with pytest.raises(ValueError, match="API key"):
        llm._chat("", "m", _msgs("never seen"), kind="town")
    llm.save_settings({"tape": "off"})
    with pytest.raises(ValueError, match="API key"):
        llm.require_key(llm.load_settings())


def test_the_environment_sets_the_tape(live, monkeypatch):
    monkeypatch.setenv("LTG_LLM_TAPE", "record")
    llm._chat("sk", "m", _msgs("x"), kind="encounter")
    assert tape.summary() == {"encounter": 1}
    assert llm.public_settings()["tape_forced"]


# --------------------------------------------------------------------------- #
# M3.2 — autopilot
# --------------------------------------------------------------------------- #
def _fight_session():
    state, portraits, art = content.build_state(["loadout_soren", "loadout_ys"],
                                                "encounter_a", seed=5)
    return SessionManager().create(state, name="t", portraits=portraits, art=art,
                                   encounter_id="encounter_a")


def test_a_chunk_plays_decisions_without_touching_its_input():
    s = _fight_session()
    before = s.state
    log_len = len(before.log)
    after, made, stop = autopilot.play_chunk(before, seed=1, max_actions=15)
    assert made > 0 and stop is None
    assert len(before.log) == log_len and after is not before
    assert after.paced == before.paced


def test_autopilot_is_a_playtest_tool():
    s = _fight_session()
    with pytest.raises(ValueError, match="playtest"):
        s.set_autopilot(True)
    assert s.autopilot_view() == {"on": False, "available": False, "note": None}


def test_autopilot_plays_the_fight_to_its_end(monkeypatch):
    monkeypatch.setenv("LTG_PLAYTEST", "1")
    s = _fight_session()
    s.set_autopilot(True)
    broadcasts = []

    async def broadcast(_session):
        broadcasts.append(_session.state.turn)

    asyncio.run(s._drive_autopilot(broadcast))
    assert s.state.result in ("victory", "defeat") or s.autopilot_note
    assert broadcasts                                          # the table saw it move
    assert s.snapshot_for("nobody")["autopilot"]["available"] is True


def test_autopilot_discards_a_chunk_when_a_player_acted_meanwhile():
    s = _fight_session()
    before = s.state
    after, made, _ = autopilot.play_chunk(before, seed=1, max_actions=5)
    s.state = after                                             # someone else moved first
    assert s._autopilot_commit(before, after, made) is False


# --------------------------------------------------------------------------- #
# M3.1 — jump-to states
# --------------------------------------------------------------------------- #
PARTY = ["loadout_soren", "loadout_ys"]
EXPECT = {"act": ("act_start", "town", 1, 1), "ready": ("town", "town", 1, 1),
          "defeat": ("act_start", "town", 1, 1), "between": ("scenario_complete", "complete", 1, 2),
          "interlude": ("interlude", "interlude", 1, 2), "scenario2": ("act_start", "town", 2, 0)}


def _library_files():
    return sorted(str(p.relative_to(content.CONTENT_DIR)) for p in content.CONTENT_DIR.rglob("*.json"))


@pytest.mark.parametrize("state", devstates.STATES)
def test_every_state_builds_loads_and_writes_no_content(state, tmp_path):
    runs = RunManager(root=tmp_path / "saves")
    before = _library_files()
    out = devstates.build(state, "karzum", PARTY, act=2, runs=runs, seed=3)
    kind, mode, scenario_number, act_index = EXPECT[state]
    assert out["save"]["kind"] == kind
    scen = runs.load_scenario_save(out["run_id"], out["save"]["save_id"])
    assert scen.scenario_number == scenario_number
    assert scen.act_index == act_index
    assert scen.mode in (mode, "town")
    assert _library_files() == before                          # nothing entered content/
    if state == "ready":
        assert scen.adventure_ready and scen.quest["status"] != "none"
    if state == "defeat":
        assert scen.flags.get("defeated_once") and out["defeats"] == 1
    if state in ("between", "interlude", "scenario2"):
        run = runs.store(out["run_id"]).read_run()
        entry = run["ledger"][0]
        assert entry["outcome"] == "victory" and len(entry["acts"]) == 3
        assert all(a["boss"] for a in entry["acts"])           # a boss fell in every act
        assert scen.levels()[0] > 1                            # the party levelled on the way
    if state == "interlude":
        assert {h["kind"] for h in scen.hooks()} >= {"stay"}


def test_autopilot_fights_record_what_really_happened(tmp_path):
    runs = RunManager(root=tmp_path / "saves")
    out = devstates.build("ready", "karzum", PARTY, act=2, fights="autopilot", runs=runs, seed=11)
    scen = runs.load_scenario_save(out["run_id"], out["save"]["save_id"])
    assert scen.act_index == 1 and scen.flags.get("act_1_complete")
    log = scen.act_logs[0]
    assert log["boss"] and log["defeats"] == out["defeats"]


def test_bad_requests_are_refused(tmp_path):
    runs = RunManager(root=tmp_path / "saves")
    for kw in ({"state": "nowhere"}, {"state": "act", "act": 4},
               {"state": "defeat", "hardcore": True}, {"state": "act", "town_id": "atlantis"}):
        with pytest.raises(ValueError):
            devstates.build(character_ids=PARTY, runs=runs, **kw)


def test_the_jump_route_is_gated_on_the_playtest_profile(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(game_app, "RUNS", RunManager(root=tmp_path / "saves"))
    client = TestClient(game_app.app)
    body = {"town_id": "karzum", "character_ids": PARTY, "state": "interlude"}
    assert client.post("/api/playtest/jump", json=body).status_code == 403
    assert client.get("/api/setup-options").json()["playtest"] is False
    monkeypatch.setenv("LTG_PLAYTEST", "1")
    res = client.post("/api/playtest/jump", json=body)
    assert res.status_code == 200, res.text
    session = game_app.MANAGER.get(res.json()["session_id"])
    assert session.scenario.mode == "interlude"


def test_switching_autopilot_off_drops_the_chunk_in_flight(monkeypatch):
    monkeypatch.setenv("LTG_PLAYTEST", "1")
    s = _fight_session()
    s.set_autopilot(True)
    before = s.state
    real = autopilot.play_chunk

    def slow_chunk(state, seed):
        out = real(state, seed)
        s.autopilot = False                    # the player takes the fight back mid-chunk
        return out
    monkeypatch.setattr(autopilot, "play_chunk", slow_chunk)

    async def broadcast(_session):
        pass

    asyncio.run(s._drive_autopilot(broadcast))
    assert s.state is before                   # nothing the policy played landed


# --------------------------------------------------------------------------- #
# M3.11 — T-88: a boss without pressure dials is given the defaults at build
# --------------------------------------------------------------------------- #
def _boss_encounter():
    """A legacy-shaped encounter: a boss with no pressure dials."""
    raw = content.encounter_detail("encounter_a")
    raw = {k: raw[k] for k in ("name", "enemies", "tokens") if k in raw}
    raw["enemies"][0]["is_boss"] = True
    raw["enemies"][0].pop("enrage_round", None)
    raw["enemies"][0].pop("neglect", None)
    return raw


def test_a_legacy_boss_gets_the_default_dials_at_build():
    scen = _boss_encounter()
    state, _, _ = content.build_state_from_loadouts(content.loadouts_for(["loadout_soren"]),
                                                    "encounter_a", seed=1, scenario=scen)
    boss = next(e for e in state.enemies if e.is_boss)
    assert (boss.enrage_round, boss.neglect) == (4, 1) == tuple(content.DEFAULT_BOSS_DIALS.values())
    assert "neglect" not in scen["enemies"][0]              # the caller's copy is untouched


def test_authored_dials_are_left_alone():
    scen = {"enemies": [{"id": "b", "is_boss": True, "enrage_round": 3, "neglect": 0},
                        {"id": "m", "is_boss": False}]}
    content.apply_boss_dials(scen)
    assert scen["enemies"][0]["enrage_round"] == 3 and scen["enemies"][0]["neglect"] == 0
    assert "enrage_round" not in scen["enemies"][1]


def test_the_autoplay_runner_mirrors_the_default_dials():
    from ltg_combat.autoplay import runner
    assert runner.DEFAULT_BOSS_DIALS == content.DEFAULT_BOSS_DIALS
    boss = next(e for e in runner.prepare_scenario(_boss_encounter(), 2)["enemies"] if e.get("is_boss"))
    assert (boss["enrage_round"], boss["neglect"]) == (4, 1)


def test_an_empty_library_rides_stand_in_adventures(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "list_adventures", lambda *a, **k: [])
    runs = RunManager(root=tmp_path / "saves")
    out = devstates.build("between", "karzum", PARTY, runs=runs, seed=2)
    run = runs.store(out["run_id"]).read_run()
    acts = run["ledger"][0]["acts"]
    assert [a["adventure"] for a in acts] == ["Stand-in ride 1", "Stand-in ride 2", "Stand-in ride 3"]
    assert all(a["boss"] for a in acts)
