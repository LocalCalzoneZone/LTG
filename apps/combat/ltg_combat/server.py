"""The cockpit backend — a thin FastAPI layer over the pure engine.

It holds the live game **state** (a value) plus the deterministic timeline of past
states, and exposes endpoints to: load characters (Deckbuilder loadout JSON) and
an enemies-only scenario, start/restart a fight (with quick-setup overrides), read
the current state + legal actions, apply an action, step back/forward through
history, and fetch raw state for the inspector.

It owns ZERO rules. It calls `legal_actions` / `apply_action` / `settle` and
serializes what they return; it never computes legality, targets, costs, damage,
turn order, or break/reservation logic. Rewriting the front end changes no outcome.
"""

from __future__ import annotations

import copy
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from ltg_core.schema import Loadout

from .engine import apply_action, legal_actions, settle
from .scenario import (
    SCENARIO_A,
    SCENARIO_C,
    compose_spec,
    party_entry_from_loadout,
    state_from_dict,
)
from .serialize import build_menu, serialize_actions, serialize_state, to_jsonable
from .state import Action, GameState

APP_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = APP_ROOT / "frontend"

app = FastAPI(title="LTG Combat — Playtest Cockpit")


# --------------------------------------------------------------------------- #
# Session: the live timeline + the loaded inputs
# --------------------------------------------------------------------------- #
class Session:
    """In-memory session. `history` is the deterministic list of past states;
    `cursor` indexes the one currently shown (time-travel just moves it)."""

    def __init__(self) -> None:
        self.slots: List[Optional[Dict[str, Any]]] = [None, None, None, None]
        self.scenario: Optional[Dict[str, Any]] = None
        self.scenario_name: str = ""
        self.overrides: Dict[str, Any] = {}
        self.history: List[GameState] = []
        self.cursor: int = -1

    @property
    def current(self) -> Optional[GameState]:
        if 0 <= self.cursor < len(self.history):
            return self.history[self.cursor]
        return None

    def start(self) -> None:
        loadouts = [s for s in self.slots if s is not None]
        if not loadouts:
            raise HTTPException(400, "load at least one character before starting")
        if self.scenario is None:
            raise HTTPException(400, "load a scenario (enemies) before starting")
        spec = compose_spec(loadouts, self.scenario, self.overrides)
        # Each fight shuffles every library before the opening hand (a fresh seed per
        # start); the seed is recorded on the state so the timeline still replays.
        self.history = [state_from_dict(spec, seed=random.randrange(2**31))]
        self.cursor = 0

    def push(self, state: GameState) -> None:
        # Truncate any forward (re-)states, then append the new one.
        self.history = self.history[: self.cursor + 1]
        self.history.append(state)
        self.cursor = len(self.history) - 1


SESSION = Session()


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class CharacterBody(BaseModel):
    slot: int
    loadout: dict


class ScenarioBody(BaseModel):
    scenario: dict


class ActionBody(BaseModel):
    index: int


class StepBody(BaseModel):
    delta: int


class GotoBody(BaseModel):
    index: int


class OverridesBody(BaseModel):
    overrides: dict


# --------------------------------------------------------------------------- #
# Rendering the current decision point
# --------------------------------------------------------------------------- #
def _render(session: Session) -> Dict[str, Any]:
    """The full payload the front end needs: the settled display view, the menu
    built from the engine's legal actions, and the history meta for time-travel."""
    stored = session.current
    if stored is None:
        return {"loaded": False, "slots": _slots_summary(session),
                "scenario_name": session.scenario_name}

    view = settle(stored)                 # display-ready (runs the auto prelude)
    actions = legal_actions(stored)       # the engine's legal choices right now
    acting_id = actions[0].actor_id if actions else None

    payload = serialize_state(view, log_source=stored)
    payload.update({
        "loaded": True,
        "acting_id": acting_id,
        "menu": build_menu(view, actions),
        "actions": serialize_actions(view, actions),
        "history": {
            "index": session.cursor,
            "length": len(session.history),
            "can_back": session.cursor > 0,
            "can_forward": session.cursor < len(session.history) - 1,
        },
        "slots": _slots_summary(session),
        "scenario_name": session.scenario_name,
        "overrides": session.overrides,
        "determinism": "Each fight shuffles every library before the opening hand; "
                       "draws then come from that shuffled order (a shuffle effect "
                       "re-randomises). The shuffle is seeded, so the timeline replays.",
    })
    return payload


def _slots_summary(session: Session) -> List[Optional[Dict[str, Any]]]:
    out: List[Optional[Dict[str, Any]]] = []
    for raw in session.slots:
        if raw is None:
            out.append(None)
            continue
        entry = party_entry_from_loadout(raw)
        out.append({
            "name": entry["name"], "archetype": entry["archetype"],
            "hp": entry["hp"], "power": entry["power"],
            "hand_size": entry["hand_size"], "identity": entry["identity"],
            "card_count": len(entry["library"]), "id": entry["id"],
        })
    return out


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/state")
def api_state() -> dict:
    return _render(SESSION)


@app.post("/api/load/character")
def api_load_character(body: CharacterBody) -> dict:
    if not 0 <= body.slot < 4:
        raise HTTPException(400, "slot must be 0–3")
    try:
        Loadout.model_validate(body.loadout)  # the single validation gate
    except ValidationError as exc:
        raise HTTPException(422, _errors("loadout invalid", exc))
    SESSION.slots[body.slot] = body.loadout
    return {"ok": True, "slots": _slots_summary(SESSION)}


@app.post("/api/clear/character")
def api_clear_character(body: CharacterBody) -> dict:
    if 0 <= body.slot < 4:
        SESSION.slots[body.slot] = None
    return {"ok": True, "slots": _slots_summary(SESSION)}


@app.post("/api/load/scenario")
def api_load_scenario(body: ScenarioBody) -> dict:
    scen = body.scenario
    if "enemies" not in scen or not isinstance(scen["enemies"], list):
        raise HTTPException(422, "scenario must contain an 'enemies' list")
    if "party" in scen:
        raise HTTPException(422, "a scenario is enemies-only — it must not contain a 'party'")
    SESSION.scenario = scen
    SESSION.scenario_name = scen.get("name", "encounter")
    return {"ok": True, "scenario_name": SESSION.scenario_name,
            "enemy_count": len(scen["enemies"])}


@app.post("/api/scenario/builtin/{which}")
def api_builtin_scenario(which: str) -> dict:
    """Convenience: load §A or §C's enemies (and tokens) as the scenario, so the
    cockpit can demo the canonical fights without a file on hand."""
    src = {"a": SCENARIO_A, "c": SCENARIO_C}.get(which.lower())
    if src is None:
        raise HTTPException(404, "unknown built-in scenario (use 'a' or 'c')")
    scen = {"name": src["name"], "enemies": copy.deepcopy(src["enemies"]),
            "tokens": copy.deepcopy(src.get("tokens", {}))}
    SESSION.scenario = scen
    SESSION.scenario_name = scen["name"]
    return {"ok": True, "scenario_name": scen["name"],
            "enemy_count": len(scen["enemies"])}


@app.post("/api/start")
def api_start(body: Optional[OverridesBody] = None) -> dict:
    if body is not None:
        SESSION.overrides = body.overrides
    SESSION.start()
    return _render(SESSION)


@app.post("/api/overrides")
def api_overrides(body: OverridesBody) -> dict:
    """Apply quick-setup overrides and rebuild the fight from the start."""
    SESSION.overrides = body.overrides
    SESSION.start()
    return _render(SESSION)


@app.post("/api/action")
def api_action(body: ActionBody) -> dict:
    stored = SESSION.current
    if stored is None:
        raise HTTPException(400, "no fight in progress")
    actions = legal_actions(stored)
    if not 0 <= body.index < len(actions):
        raise HTTPException(400, "action index out of range")
    new_state, _events = apply_action(stored, actions[body.index])
    SESSION.push(new_state)
    return _render(SESSION)


@app.post("/api/step")
def api_step(body: StepBody) -> dict:
    """Step the deterministic timeline backward / forward (time-travel)."""
    SESSION.cursor = max(0, min(len(SESSION.history) - 1, SESSION.cursor + body.delta))
    return _render(SESSION)


@app.post("/api/goto")
def api_goto(body: GotoBody) -> dict:
    if SESSION.history:
        SESSION.cursor = max(0, min(len(SESSION.history) - 1, body.index))
    return _render(SESSION)


@app.get("/api/raw")
def api_raw() -> dict:
    """The full raw underlying state at the current cursor (the inspector's
    'why did the engine do that' view)."""
    stored = SESSION.current
    if stored is None:
        raise HTTPException(400, "no fight in progress")
    return to_jsonable(settle(stored))


def _errors(prefix: str, exc: ValidationError) -> str:
    parts = "; ".join(".".join(str(p) for p in e["loc"]) + ": " + e["msg"]
                      for e in exc.errors())
    return f"{prefix}: {parts}"


# --------------------------------------------------------------------------- #
# Static frontend (mounted last so /api/* wins)
# --------------------------------------------------------------------------- #
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
