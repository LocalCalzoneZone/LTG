"""Cockpit tests: the loadout→engine adapter, end-to-end play from loadouts, and
the FastAPI backend's endpoints. The cockpit owns zero rules, so the proof that
matters is that a fight assembled from Deckbuilder loadouts + an enemies-only
scenario plays to the SAME results as the scripted §A / §C traces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ltg_combat.harness import run_channeling_scenario, run_scenario
from ltg_combat.scenario import (
    build_channeling_state,
    build_state,
    state_from_loadouts,
)
import ltg_combat.server as server

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def _setup_sig(state):
    party = [(c.id, c.name, c.archetype, c.hp, c.power, c.hand_size, c.mana_colors,
              [x.id for x in c.hand], [x.id for x in c.library]) for c in state.party]
    enemies = [(e.id, e.name, e.hp, e.level) for e in state.enemies]
    return party, enemies, state.token_defs


# --------------------------------------------------------------------------- #
# Adapter: loadouts + enemies-only scenario reproduce the canonical setups
# --------------------------------------------------------------------------- #
def test_loadouts_reproduce_scenario_a_setup():
    built = build_state()
    assembled = state_from_loadouts(
        [_load("loadout_soren.json"), _load("loadout_ys.json")],
        _load("encounter_a.json"),
    )
    assert _setup_sig(assembled) == _setup_sig(built)


def test_loadouts_reproduce_scenario_c_setup():
    built = build_channeling_state()
    assembled = state_from_loadouts([_load("loadout_mira.json")], _load("encounter_c.json"))
    assert _setup_sig(assembled) == _setup_sig(built)


# --------------------------------------------------------------------------- #
# End-to-end: a loadout-assembled fight plays to the scripted results
# --------------------------------------------------------------------------- #
def test_scenario_a_plays_to_victory_from_loadouts():
    state = state_from_loadouts(
        [_load("loadout_soren.json"), _load("loadout_ys.json")],
        _load("encounter_a.json"),
    )
    final = run_scenario(state=state)  # all §A assertions run against this setup
    assert final.result == "victory"


def test_scenario_c_plays_through_from_loadouts():
    state = state_from_loadouts([_load("loadout_mira.json")], _load("encounter_c.json"))
    final = run_channeling_scenario(state=state)
    assert final.result is None  # §C ends mid-fight, exactly like the canonical trace
    assert len(final.party[0].channels) == 0  # the break released the channels


# --------------------------------------------------------------------------- #
# Backend endpoints
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    server.SESSION = server.Session()  # fresh session per test
    return TestClient(server.app)


def test_load_validate_start_and_play(client):
    # No fight yet.
    assert client.get("/api/state").json()["loaded"] is False

    # Load two characters + the enemies-only scenario via the API.
    for slot, name in [(0, "loadout_soren.json"), (1, "loadout_ys.json")]:
        r = client.post("/api/load/character", json={"slot": slot, "loadout": _load(name)})
        assert r.status_code == 200
    r = client.post("/api/load/scenario", json={"scenario": _load("encounter_a.json")})
    assert r.status_code == 200 and r.json()["enemy_count"] == 2

    # Start: the engine bootstraps the opening (upkeep + intents); a decision waits.
    state = client.post("/api/start", json={"overrides": {}}).json()
    assert state["loaded"] and state["turn"] == 1
    # Turn order is randomized per start (seeded initiative): either hero may open.
    assert state["acting_id"] in ("soren", "ys")
    assert state["menu"], "the engine should offer legal actions"
    # Intents are visible on the enemy panels.
    assert any(e["intent"] for e in state["enemies"])

    # Apply the first menu action that is a direct (non-submenu) action.
    direct = next(m for m in state["menu"] if m.get("index") is not None and not m.get("targets"))
    after = client.post("/api/action", json={"index": direct["index"]}).json()
    assert after["history"]["length"] == 2

    # Time-travel back, then forward, lands on the same deterministic states.
    back = client.post("/api/step", json={"delta": -1}).json()
    assert back["history"]["index"] == 0
    fwd = client.post("/api/step", json={"delta": 1}).json()
    assert fwd["history"]["index"] == 1

    # Raw inspector returns the full underlying state.
    raw = client.get("/api/raw").json()
    assert "party" in raw and "stack" in raw


def test_scenario_rejects_party(client):
    r = client.post("/api/load/scenario", json={"scenario": {"party": [], "enemies": []}})
    assert r.status_code == 422


def test_invalid_loadout_rejected(client):
    r = client.post("/api/load/character", json={"slot": 0, "loadout": {"character": {}}})
    assert r.status_code == 422


def test_builtin_scenario_and_overrides(client):
    client.post("/api/load/character", json={"slot": 0, "loadout": _load("loadout_mira.json")})
    assert client.post("/api/scenario/builtin/c").json()["enemy_count"] == 2
    state = client.post("/api/start", json={"overrides": {}}).json()
    maul = next(e for e in state["enemies"] if e["id"] == "maul")
    assert maul["max_hp"] == 10

    # Quick-setup: what if Maul had 20 HP? Rebuild and confirm.
    ov = {"enemies": {"maul": {"hp": 20}}}
    state = client.post("/api/overrides", json={"overrides": ov}).json()
    maul = next(e for e in state["enemies"] if e["id"] == "maul")
    assert maul["max_hp"] == 20
