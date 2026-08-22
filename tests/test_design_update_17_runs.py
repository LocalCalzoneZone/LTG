"""Design Update 17 §D17-3 — runs, saves, and the content store (Phase 0).

The branching save tree: a run around an adventure; auto-saves at adventure
start / every phase boundary / adventure end; the content store is
hash-addressed and immutable; loading a save rebuilds the EXACT phase-start
state (same seed → identical composition); continuing an older save forks
(appends) rather than overwriting; delete removes only the snapshot.
"""

from __future__ import annotations

import json

import pytest

from ltg_game_server import content
from ltg_game_server.adventure import AdventureRun
from ltg_game_server.runs import RunManager, RunStore, content_hash
from ltg_game_server.session import SessionManager

from tests.test_design_update_10 import _adventure, _isolate  # noqa: F401 (fixture)


def _party_state_sig(state):
    """A stable fingerprint of a composed party: hp / hand / library order."""
    return [(c.id, c.hp, c.max_hp, c.ultimate_gauge,
             [k.id for k in c.hand], [k.id for k in c.library])
            for c in state.party]


@pytest.fixture
def runs(tmp_path):
    return RunManager(root=tmp_path / "saves")


def _start(runs, seed=11):
    aid = content.save_adventure(_adventure())["id"]
    adv = AdventureRun(aid)
    state, portraits, art, eid = adv.start(["loadout_soren", "loadout_ys"], seed=seed)
    meta = runs.create_adventure_run(adv, options={"difficulty": "hard", "hardcore": False},
                                     name="Test run")
    runs.save(meta["run_id"], adv, "adventure_start", seed)
    return meta["run_id"], adv, state


def test_content_store_is_hash_addressed_and_immutable(tmp_path):
    st = RunStore("run-a", tmp_path)
    st.write_run({"run_id": "run-a", "schema_version": 1})
    h1 = st.put({"b": 2, "a": [1, 2]})
    h2 = st.put({"a": [1, 2], "b": 2})   # key order never matters
    assert h1 == h2 == content_hash({"a": [1, 2], "b": 2})
    assert st.get(h1) == {"a": [1, 2], "b": 2}
    path = st.content_dir / f"{h1}.json"
    mtime = path.stat().st_mtime_ns
    st.put({"a": [1, 2], "b": 2})        # a second put is a no-op
    assert path.stat().st_mtime_ns == mtime
    with pytest.raises(KeyError):
        st.get("0" * 64)


def test_run_created_with_first_autosave_and_frozen_adventure(runs):
    run_id, adv, _state = _start(runs)
    listing = runs.list_runs()
    assert [r["run_id"] for r in listing] == [run_id]
    assert listing[0]["options"] == {"difficulty": "hard", "hardcore": False, "everquest": False}
    assert [p["id"] for p in listing[0]["party"]] == ["loadout_soren", "loadout_ys"]
    detail = runs.run_detail(run_id)
    assert len(detail["saves"]) == 1
    assert detail["saves"][0]["kind"] == "adventure_start"
    assert detail["saves"][0]["label"] == "Test Keep · Adventure start"
    # The adventure is frozen into the content store: editing / deleting the
    # live adventure afterwards cannot touch what the run points at.
    st = runs.store(run_id)
    ref = st.read_run()["scenario"]["adventure_ref"]
    assert st.get(ref)["name"] == "Test Keep"
    content.delete_adventure(adv.adventure_id)
    assert st.get(ref)["phases"][0]["name"] == "The Gate"


def test_boundary_save_reloads_the_identical_next_phase(runs):
    run_id, adv, state = _start(runs)
    # Play to the phase boundary and level up.
    soren, ys = state.party
    soren.hp = 3
    soren.graveyard = soren.library[:2]
    soren.library = soren.library[2:]
    soren.ultimate_gauge = 100
    state.result = "victory"
    adv.on_state_change(state)
    adv.confirm_level_up(soren.id, {})
    adv.confirm_level_up(ys.id, {"hp": 17})
    seed = 12345
    row = runs.save(run_id, adv, "phase_boundary", seed)      # BEFORE advance
    assert row["label"] == "Test Keep · Adventure, Phase 2"
    live_state, _p, _a, eid = adv.advance(seed=seed)
    assert eid.endswith("__phase2")

    # Load the boundary save: same phase, same composition, same builds.
    saves = runs.run_detail(run_id)["saves"]
    assert [s["kind"] for s in saves] == ["adventure_start", "phase_boundary"]
    _meta, adv2, state2, _portraits, _art, eid2 = runs.load_save(run_id, saves[-1]["save_id"])
    assert eid2 == eid and adv2.phase_index == 1
    assert _party_state_sig(state2) == _party_state_sig(live_state)
    assert adv2.loadouts[1]["character"]["hp"] == 17
    assert adv2.earned == adv.earned and adv2.banked == adv.banked
    assert adv2.loadouts[0]["character"]["earned_points"] == 10   # Phase I pays +10
    assert adv2.loadouts[0]["character"]["level"] == 2


def test_start_save_reloads_phase_one_and_forks_append(runs):
    run_id, adv, state = _start(runs, seed=7)
    saves = runs.run_detail(run_id)["saves"]
    _meta, adv2, state2, _p, _a, eid = runs.load_save(run_id, saves[0]["save_id"])
    assert eid.endswith("__phase1") and adv2.phase_index == 0
    assert _party_state_sig(state2) == _party_state_sig(state)
    # Continue from the OLD save: a new row appends (a fork), nothing overwritten.
    runs.save(run_id, adv2, "phase_boundary", 99)
    runs.save(run_id, adv2, "phase_boundary", 100)
    saves = runs.run_detail(run_id)["saves"]
    assert len(saves) == 3
    assert saves[0]["saved_at"] <= saves[1]["saved_at"] <= saves[2]["saved_at"]
    # Delete one save: only its snapshot goes; content survives.
    runs.delete_save(run_id, saves[1]["save_id"])
    assert len(runs.run_detail(run_id)["saves"]) == 2
    st = runs.store(run_id)
    assert list(st.content_dir.glob("*.json"))
    runs.delete_run(run_id)
    assert runs.list_runs() == []
    with pytest.raises(KeyError):
        runs.run_detail(run_id)


def test_session_autosaves_at_boundaries_and_end(runs):
    """The Session calls back into the RunManager: a phase-boundary save when
    the last seat confirms (before the next phase composes), an adventure_end
    save when the finale is won; the snapshot exposes the run block."""
    aid = content.save_adventure(_adventure())["id"]
    adv = AdventureRun(aid)
    state, portraits, art, eid = adv.start(["loadout_soren"], seed=3)
    meta = runs.create_adventure_run(adv)
    sm = SessionManager()
    session = sm.create(state, name=adv.name, portraits=portraits, encounter_id=eid,
                        art=art, adventure=adv, run_id=meta["run_id"], run_manager=runs)
    session.save_point("adventure_start", 3)
    session.claim("c1", session.controlled_by("c1") | {adv.live_ids[0]})
    session.seats[adv.live_ids[0]] = "c1"
    for _ in range(2):
        session.state.result = "victory"
        session.adventure.on_state_change(session.state)
        session._run_hooks()
        session.confirm_level_up("c1", adv.live_ids[0], {})
    kinds = [s["kind"] for s in runs.run_detail(meta["run_id"])["saves"]]
    assert kinds == ["adventure_start", "phase_boundary", "phase_boundary"]
    # Win the finale → adventure_end (once).
    session.state.result = "victory"
    session.adventure.on_state_change(session.state)
    session._run_hooks()
    session._run_hooks()
    kinds = [s["kind"] for s in runs.run_detail(meta["run_id"])["saves"]]
    assert kinds[-1] == "adventure_end" and kinds.count("adventure_end") == 1
    snap = session.snapshot_for("c1")
    assert snap["run"]["run_id"] == meta["run_id"]
    assert snap["run"]["last_save"]["kind"] == "adventure_end"


def test_hardcore_defeat_marks_the_run_dead(runs):
    aid = content.save_adventure(_adventure())["id"]
    adv = AdventureRun(aid)
    state, portraits, art, eid = adv.start(["loadout_soren"], seed=3)
    meta = runs.create_adventure_run(adv, options={"hardcore": True})
    sm = SessionManager()
    session = sm.create(state, adventure=adv, run_id=meta["run_id"], run_manager=runs,
                        portraits=portraits, encounter_id=eid, art=art)
    session.save_point("adventure_start", 3)
    session.state.result = "defeat"
    session._run_hooks()
    assert runs.list_runs()[0]["dead"] is True
    save_id = runs.run_detail(meta["run_id"])["saves"][0]["save_id"]
    with pytest.raises(ValueError, match="Hardcore"):
        runs.load_save(meta["run_id"], save_id)


def test_save_snapshot_is_small_and_self_contained(runs):
    run_id, adv, _state = _start(runs)
    st = runs.store(run_id)
    save = st.list_saves()[0]
    raw = json.loads((st.saves_dir / f"{save['save_id']}.json").read_text())
    assert raw["schema_version"] == 1
    # Loadouts live in the content store (portraits are the bulk); the snapshot
    # holds references only.
    assert "loadouts" not in raw["party"] and len(raw["party"]["loadout_refs"]) == 2
    assert all((st.content_dir / f"{h}.json").exists() for h in raw["party"]["loadout_refs"])
    assert (st.content_dir / f"{raw['adventure']['ref']}.json").exists()
