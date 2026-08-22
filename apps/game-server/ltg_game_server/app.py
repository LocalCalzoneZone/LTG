"""The LTG-Game FastAPI app: REST lobby, per-session WebSocket, static client.

Authority/relay only. Every action flows through the engine via `Session.apply_index`;
this layer computes no rules. See INTERFACE_NOTES.md for the state contract.
"""

from __future__ import annotations

import asyncio
import random
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import appctl, art, content, jobs, llm, scenario_content
from .adventure import AdventureRun
from .runs import RunManager
from .scenario import ScenarioRun
from .session import SessionManager
from .snapshot import priority_fields

APP_ROOT = Path(__file__).resolve().parent.parent          # apps/game-server
FRONTEND_DIST = APP_ROOT.parent / "game-ui" / "dist"       # apps/game-ui/dist

app = FastAPI(title="LTG-Game")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Phase 1: dev-friendly; auth/access-control is deferred.
    allow_methods=["*"],
    allow_headers=["*"],
)

MANAGER = SessionManager()
RUNS = RunManager()


# --------------------------------------------------------------------------- #
# REST: lobby / setup
# --------------------------------------------------------------------------- #
class RunOptionsBody(BaseModel):
    """Update 17 §D17-1: a run's immutable options. Present on an adventure
    start == play it inside a NEW run (saved, resumable, forkable)."""
    difficulty: str = "standard"      # easy / standard / hard
    hardcore: bool = False            # defeat ends the run
    everquest: bool = False           # (scenario layer — recorded, unused in Phase 0)
    name: str = ""


class CreateGameBody(BaseModel):
    character_ids: List[str]
    # Exactly one of these: a standalone encounter, an adventure (Update 10 —
    # the session then runs the three-phase flow: carry-over, level-ups,
    # splashes), a pre-generated scenario, or a town (Town + New: generate an
    # arc for it at start) — the last two ALWAYS create a run (§D17-1).
    encounter_id: Optional[str] = None
    adventure_id: Optional[str] = None
    scenario_id: Optional[str] = None
    town_id: Optional[str] = None
    # Optional (adventures only): create a run around this adventure (§D17-3).
    # Absent == today's throwaway adventure session, byte-identical. Required
    # semantics for scenarios (defaults apply when absent).
    run: Optional[RunOptionsBody] = None
    note: str = ""


@app.get("/api/setup-options")
def setup_options() -> Dict[str, Any]:
    return {
        "characters": content.list_characters(),
        "encounters": content.list_encounters(),
        "adventures": content.list_adventures(),
        **_scenario_setup_options(),
    }


@app.post("/api/games")
async def create_game(body: CreateGameBody) -> Dict[str, Any]:
    if body.scenario_id or body.town_id:
        return await _create_scenario_game(body)
    if bool(body.encounter_id) == bool(body.adventure_id):
        raise HTTPException(400, "choose an encounter or an adventure")
    try:
        if body.adventure_id:
            run = AdventureRun(body.adventure_id)
            seed = random.randrange(2**31)
            state, portraits, game_art, encounter_id = run.start(
                body.character_ids, seed=seed)
            run_id = None
            if body.run is not None:
                meta = RUNS.create_adventure_run(
                    run, options=body.run.model_dump(exclude={"name"}),
                    name=body.run.name)
                run_id = meta["run_id"]
            session = MANAGER.create(state, name=run.name, portraits=portraits,
                                     encounter_id=encounter_id, art=game_art,
                                     adventure=run, run_id=run_id,
                                     run_manager=RUNS if run_id else None)
            if run_id:
                session.save_point("adventure_start", seed)  # the first auto-save
            return {"session_id": session.id, "run_id": run_id}
        state, portraits, game_art = content.build_state(
            body.character_ids, body.encounter_id, seed=random.randrange(2**31)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    encounter = content.encounter_for(body.encounter_id)
    session = MANAGER.create(state, name=encounter["name"] if encounter else "",
                             portraits=portraits,
                             encounter_id=body.encounter_id, art=game_art)
    return {"session_id": session.id}


# --------------------------------------------------------------------------- #
# Scenario Mode (Update 17): starting a run, the async driver, town verbs
# --------------------------------------------------------------------------- #
def _scenario_setup_options() -> Dict[str, Any]:
    return {"scenarios": scenario_content.list_scenarios(),
            "towns": scenario_content.list_towns()}


async def _create_scenario_game(body: CreateGameBody) -> Dict[str, Any]:
    """New Game → Scenarios (§D17-7): a pre-generated scenario (Act I instant)
    or Town + New (an arc generates now, blocking; the town portion of Act I
    generates under the entry splash). Always a run."""
    opts = (body.run or RunOptionsBody()).model_dump()
    name = opts.pop("name", "")
    try:
        loadouts = content.loadouts_for(body.character_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    materialization = None
    if body.scenario_id:
        sdef = scenario_content.scenario_detail(body.scenario_id)
        if sdef is None:
            raise HTTPException(404, "no such scenario")
        town = scenario_content.town_detail(sdef["town_id"])
        if town is None:
            raise HTTPException(400, f"the scenario's town ({sdef['town_id']}) is missing")
        arc = sdef["arc"]
        materialization = (sdef.get("act1") or {}).get("materialization") or None
        pregen_adventure = (sdef.get("act1") or {}).get("adventure_id")
        town_id, scenario_id = sdef["town_id"], body.scenario_id
    else:
        town = scenario_content.town_detail(body.town_id or "")
        if town is None:
            raise HTTPException(404, "no such town")
        try:
            party = llm.party_summary_from_loadouts(loadouts)
            arc = await asyncio.to_thread(llm.generate_arc, town, party,
                                          opts.get("difficulty", "standard"),
                                          None, body.note or "")
        except ValueError as exc:
            raise HTTPException(502, str(exc))
        pregen_adventure = None
        town_id, scenario_id = body.town_id or "", ""
    scenario = ScenarioRun(town, arc, body.character_ids, loadouts, opts,
                           town_id=town_id, scenario_id=scenario_id)
    meta = RUNS.create_scenario_run(scenario, name=name)
    session = MANAGER.create(None, name=meta["name"], adventure=None,
                             run_id=meta["run_id"], run_manager=RUNS, scenario=scenario)
    session.async_hook = _scenario_async
    session.scenario_enter_town(materialization)
    if materialization is None:
        _scenario_async(session, "materialize")
    elif pregen_adventure:
        session.pregenerated_act1 = {
            "adventure_id": pregen_adventure,
            "quest_id": (sdef.get("act1") or {}).get("quest_id", ""),
        }
    # A pre-generated Act I is already materialized here: its spoils are frozen,
    # so start painting them while the party is still reading the arrival text.
    _queue_spoils_art(session)
    return {"session_id": session.id, "run_id": meta["run_id"]}


def _scenario_async(session, kind: str) -> None:
    """The session's hook for work that leaves the lock: LLM calls off-thread,
    the confirmation timer. Schedules a task on the running loop (or runs the
    generation inline when there is no loop — tests)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if kind == "materialize":
        if loop is None:
            session.materialize_act()
        else:
            loop.create_task(_materialize_task(session))
    elif kind == "new_arc":
        if loop is None:
            _new_arc_sync(session)
        else:
            loop.create_task(_new_arc_task(session))
    elif kind == "adventure_job":
        sc = session.scenario
        if sc is None:
            return
        pre = session.pregenerated_act1
        if pre is not None:
            session.pregenerated_act1 = None
            # The pre-written Act I only fits the option it was written for; any
            # other answer takes the ordinary road and generates its own.
            if not pre.get("quest_id") or pre["quest_id"] == sc.quest.get("id"):
                jobs.RUNNER.prepare_pregenerated(session, pre["adventure_id"])
                return
        if sc.adventure_detail is not None and sc.adventure_job.get("state") == "ready":
            return  # a reload: already ready
        jobs.RUNNER.start(session, _broadcast, _refresh_sessions_art)
    elif kind == "confirm_timer" and loop is not None:
        loop.create_task(_confirm_timer(session))


async def _materialize_task(session) -> None:
    await asyncio.to_thread(session.materialize_act)
    await _broadcast(session)
    _queue_spoils_art(session)     # the act's spoils are frozen now — start painting


def _new_arc_sync(session) -> None:
    sc = session.scenario
    party = llm.party_summary_from_loadouts(sc.loadouts, sc.levels())
    prev = sc.previous_arcs + [{"title": sc.arc["title"], "villain": sc.arc["villain"],
                                "outcome": "defeated"}]
    arc = sc.arc_generator(sc.town, party, sc.options.get("difficulty", "standard"), prev)
    session.new_arc(arc)
    session.materialize_act()


async def _new_arc_task(session) -> None:
    try:
        await asyncio.to_thread(_new_arc_sync, session)
    except ValueError as exc:
        if session.scenario is not None:
            session.scenario.materialize_error = f"new arc: {exc}"
            session.scenario.materializing = False
    await _broadcast(session)
    _queue_spoils_art(session)


async def _confirm_timer(session) -> None:
    c = session.confirm
    if c is None:
        return
    cid = c["id"]
    await asyncio.sleep(max(0.0, c["deadline"] - __import__("time").time()))
    async with session.lock():
        session.expire_confirm(cid)
    await _broadcast(session)
    _after_town_change(session)


def _after_town_change(session) -> None:
    """A town verb may have swapped the session into adventure mode: start the
    pacer so the opening auto-passes drain visibly."""
    if session.state is not None:
        session.start_pacer(_broadcast)
    _queue_spoils_art(session)


def _queue_spoils_art(session) -> None:
    """Paint the act's spoils AHEAD of the boss (§D17-4.5). The act freezes its
    drops on arrival in town, so this queue — the same sequential art queue the
    town and the adventure use — has the whole town visit and the whole ride
    out to work in. Idempotent: only drops still without a picture are queued,
    and one already on disk is adopted rather than repainted."""
    sc = getattr(session, "scenario", None)
    if sc is None or not sc.spoils():
        return
    key = f"spoils:{session.run_id or id(session)}:{sc.scenario_number}:{sc.act_index}"

    async def _refresh(_key: str) -> None:
        await _broadcast(session)

    items_ = art.spoil_art_items(sc.spoils(), sc.set_spoil_art)
    if not items_:
        return
    try:
        art.QUEUE.start_items(key, items_, _refresh)
    except RuntimeError:
        pass  # no running loop (tests / sync callers)


@app.post("/api/characters")
def import_character(body: Dict[str, Any]) -> Dict[str, Any]:
    """Import a Deckbuilder loadout JSON so it becomes an available character.

    Persists it to the loadouts dir; returns the new character's meta.
    """
    try:
        meta = content.save_loadout(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"character": meta}


@app.delete("/api/characters/{character_id}")
def delete_character(character_id: str) -> Dict[str, Any]:
    """Remove an imported character (bundled examples are refused)."""
    try:
        content.delete_loadout(character_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# REST: runs & saves (Update 17 §D17-3) — Load Game
# --------------------------------------------------------------------------- #
@app.get("/api/runs")
def list_runs() -> Dict[str, Any]:
    """The Load Game list: every run under saves/, newest first."""
    return {"runs": RUNS.list_runs()}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> Dict[str, Any]:
    """One run with its saves, oldest → newest (each loadable / deletable)."""
    try:
        return RUNS.run_detail(run_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/runs/{run_id}/saves/{save_id}/load")
def load_save(run_id: str, save_id: str) -> Dict[str, Any]:
    """Rebuild the save's session (the exact adventure + party it points at)
    and return its id; continuing appends new saves — a fork when this save
    was not the newest (§D17-3.1)."""
    try:
        meta, adventure, state, portraits, game_art, encounter_id = RUNS.load_save(run_id, save_id)
        scenario = (RUNS.load_scenario_save(run_id, save_id)
                    if RUNS.is_scenario_save(run_id, save_id) else None)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if scenario is None:
        session = MANAGER.create(state, name=adventure.name, portraits=portraits,
                                 encounter_id=encounter_id, art=game_art,
                                 adventure=adventure, run_id=run_id, run_manager=RUNS)
        return {"session_id": session.id, "run_id": run_id}
    if scenario.mode == "adventure" and adventure is not None:
        # Stamps this act's level-up schedule onto the restored run, and
        # re-opens the act-end screen if the save sat inside it (§D17-2.3).
        scenario.adopt_adventure(adventure)
        session = MANAGER.create(state, name=meta["name"], portraits=portraits,
                                 encounter_id=encounter_id, art=game_art,
                                 adventure=adventure, run_id=run_id, run_manager=RUNS,
                                 scenario=scenario)
    else:
        scenario.mode = "town" if scenario.mode != "complete" else "complete"
        session = MANAGER.create(None, name=meta["name"], run_id=run_id,
                                 run_manager=RUNS, scenario=scenario)
        # A town save whose act never materialized (a crash mid-generation)
        # resumes the generation; a pending adventure job resumes too.
        if scenario.act is None and scenario.mode == "town":
            scenario.materializing = True
            _scenario_async(session, "materialize")
        job = scenario.adventure_job.get("state")
        if scenario.adventure_unlocked and job in ("pending", "failed", "idle") \
                and scenario.adventure_detail is None:
            _scenario_async(session, "adventure_job")
    session.async_hook = _scenario_async
    # A save taken inside an act's WRAP-UP (§D17-2.3) — the spoils modal or the
    # act-end level-up screen — resumes where it stopped instead of stalling in
    # a won adventure with nothing driving it.
    if scenario.act_wrapup and session.adventure is not None and session.adventure.complete:
        session._scenario_transitions()
    # Resume the spoils art: anything already on disk is adopted, the rest queued.
    _queue_spoils_art(session)
    return {"session_id": session.id, "run_id": run_id}


@app.delete("/api/runs/{run_id}/saves/{save_id}")
def delete_save(run_id: str, save_id: str) -> Dict[str, Any]:
    try:
        RUNS.delete_save(run_id, save_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> Dict[str, Any]:
    try:
        RUNS.delete_run(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# REST: encounter authoring (create / edit / delete)
# --------------------------------------------------------------------------- #
class SaveEncounterBody(BaseModel):
    id: Optional[str] = None          # present == edit that id; absent == create
    encounter: Dict[str, Any]         # {name, enemies:[...], tokens?}


@app.get("/api/encounters/{encounter_id}")
def get_encounter(encounter_id: str) -> Dict[str, Any]:
    """The full editable encounter (name + raw enemy specs + tokens)."""
    detail = content.encounter_detail(encounter_id)
    if detail is None:
        raise HTTPException(404, "no such encounter")
    return detail


@app.post("/api/encounters")
def save_encounter(body: SaveEncounterBody) -> Dict[str, Any]:
    """Create or edit an encounter, returning its meta."""
    try:
        meta = content.save_encounter(body.encounter, body.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"encounter": meta}


@app.delete("/api/encounters/{encounter_id}")
def delete_encounter(encounter_id: str) -> Dict[str, Any]:
    """Remove an encounter (a built-in / example is hidden, a user file is deleted)."""
    try:
        content.delete_encounter(encounter_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# REST: adventures (Design Update 10) — list/detail/edit/delete + generation.
# Phases are ordinary encounters (reserved ids) edited through the encounter
# endpoints above; the wrapper (name, flavor, narrations) is edited here.
# --------------------------------------------------------------------------- #
class AdventureInfoBody(BaseModel):
    name: Optional[str] = None
    flavor: Optional[str] = None
    narrations: Optional[List[str]] = None


class GenerateAdventureBody(BaseModel):
    character_ids: List[str]
    difficulty: str = "standard"
    note: str = ""


@app.get("/api/adventures/{adventure_id}")
def get_adventure(adventure_id: str) -> Dict[str, Any]:
    """The full adventure: wrapper fields + each phase's embedded encounter."""
    detail = content.adventure_detail(adventure_id)
    if detail is None:
        raise HTTPException(404, "no such adventure")
    return detail


@app.put("/api/adventures/{adventure_id}")
def put_adventure_info(adventure_id: str, body: AdventureInfoBody) -> Dict[str, Any]:
    """Update the adventure-level fields (name, flavor, narrations)."""
    try:
        meta = content.save_adventure_info(
            adventure_id, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"adventure": meta}


@app.delete("/api/adventures/{adventure_id}")
def delete_adventure(adventure_id: str) -> Dict[str, Any]:
    """Remove an adventure and its phase files."""
    try:
        content.delete_adventure(adventure_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/adventures/generate")
def generate_adventure(body: GenerateAdventureBody) -> Dict[str, Any]:
    """Generate + persist a whole three-phase adventure in one model call,
    scoped to the picked party and difficulty; returns its meta."""
    try:
        meta = llm.generate_adventure(body.character_ids, body.difficulty, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"adventure": meta}


# --------------------------------------------------------------------------- #
# REST: LLM settings + encounter generation
# --------------------------------------------------------------------------- #
class LlmSettingsBody(BaseModel):
    # All optional: send only what changed. `api_key` absent/"" leaves the stored
    # key untouched; `api_key: null` clears it (see llm.save_settings). A field
    # missing here is silently STRIPPED from the body before llm.save_settings
    # ever sees it — keep this model in sync with the settings keys.
    api_key: Optional[str] = None
    model: Optional[str] = None
    task_models: Optional[Dict[str, Optional[str]]] = None   # per-task overrides ("" = default)
    instructions: Optional[str] = None
    art_style: Optional[str] = None
    scenario_tone: Optional[str] = None
    art_backend: Optional[str] = None
    comfyui_url: Optional[str] = None
    comfyui_workflow: Optional[str] = None


class GenerateEncounterBody(BaseModel):
    character_ids: List[str]
    difficulty: str = "standard"
    note: str = ""


@app.get("/api/llm/settings")
def get_llm_settings() -> Dict[str, Any]:
    """Public LLM settings for the Options UI (model, instructions, models list,
    whether a key is set) — never the raw key."""
    return llm.public_settings()


@app.put("/api/llm/settings")
def put_llm_settings(body: LlmSettingsBody) -> Dict[str, Any]:
    """Persist a partial settings update; returns the refreshed public settings."""
    try:
        return llm.save_settings(body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/encounters/generate")
def generate_encounter(body: GenerateEncounterBody) -> Dict[str, Any]:
    """Generate + persist a new encounter scoped to the picked party and difficulty,
    returning its meta (so the client can immediately start a game with it)."""
    try:
        meta = llm.generate_encounter(body.character_ids, body.difficulty, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"encounter": meta}


# --------------------------------------------------------------------------- #
# REST: art generation (scene backdrops + enemy portraits)
# --------------------------------------------------------------------------- #
class GenerateArtBody(BaseModel):
    kind: str                        # "scene" | "enemy"
    enemy_id: Optional[str] = None   # POOL enemy id (a clone's base_id), enemy art only
    text: Optional[str] = None       # optional prompt-subject override (editor's
                                     # live textarea); never written back


async def _refresh_sessions_art(encounter_id: str) -> None:
    """Push the encounter's current art into every live game built from it, so
    all seated players see a mid-game generation/removal immediately."""
    fresh = content.encounter_art(encounter_id)
    for session in MANAGER.all():
        if session.encounter_id == encounter_id:
            session.set_art(fresh)
            await _broadcast(session)


@app.post("/api/encounters/{encounter_id}/art")
async def generate_encounter_art(encounter_id: str, body: GenerateArtBody) -> Dict[str, Any]:
    """Generate (or regenerate) the scene backdrop / one enemy's portrait.

    Persists the image + the updated encounter JSON (so replays include the art)
    and refreshes any running session on this encounter. Returns ``{"url": ...}``.
    The generation call blocks on the image model, so it runs in a worker thread —
    the event loop (and everyone's websockets) stay live.
    """
    try:
        result = await asyncio.to_thread(
            art.generate, encounter_id, body.kind, body.enemy_id, body.text or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    await _refresh_sessions_art(encounter_id)
    return result


@app.delete("/api/encounters/{encounter_id}/art")
async def delete_encounter_art(encounter_id: str, kind: str,
                               enemy_id: Optional[str] = None) -> Dict[str, Any]:
    """Remove the scene's / one enemy's generated art (file + JSON reference)."""
    try:
        result = art.remove(encounter_id, kind, enemy_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    await _refresh_sessions_art(encounter_id)
    return result


# --------------------------------------------------------------------------- #
# REST: the art queue — "Generate all art" (Update 10 §D10-6.4). POST enqueues
# every still-missing image (idempotent); GET polls progress. The adventure
# variant covers its phases in order (Phase I first, so play can start while later
# phases paint); completed images broadcast to sessions as they land.
# --------------------------------------------------------------------------- #
@app.post("/api/encounters/{encounter_id}/art/all")
async def start_encounter_art_queue(encounter_id: str) -> Dict[str, Any]:
    if content.encounter_detail(encounter_id) is None:
        raise HTTPException(404, "no such encounter")
    return art.QUEUE.start(f"encounter:{encounter_id}", [encounter_id],
                           _refresh_sessions_art)


@app.get("/api/encounters/{encounter_id}/art/all")
def encounter_art_queue_status(encounter_id: str) -> Dict[str, Any]:
    return art.QUEUE.status(f"encounter:{encounter_id}")


@app.post("/api/adventures/{adventure_id}/art/all")
async def start_adventure_art_queue(adventure_id: str) -> Dict[str, Any]:
    detail = content.adventure_detail(adventure_id)
    if detail is None:
        raise HTTPException(404, "no such adventure")
    phase_ids = [a["encounter_id"] for a in detail["phases"]]
    return art.QUEUE.start(f"adventure:{adventure_id}", phase_ids,
                           _refresh_sessions_art)


@app.get("/api/adventures/{adventure_id}/art/all")
def adventure_art_queue_status(adventure_id: str) -> Dict[str, Any]:
    return art.QUEUE.status(f"adventure:{adventure_id}")


# --------------------------------------------------------------------------- #
# REST: towns & scenarios (Update 17 §D17-5.1 / §D17-6.1 — Options → Towns /
# Options → Scenarios): list / detail / save / delete / generate / art.
# --------------------------------------------------------------------------- #
class SaveTownBody(BaseModel):
    id: Optional[str] = None
    town: Dict[str, Any]


class GenerateTownBody(BaseModel):
    note: str = ""


class TownArtBody(BaseModel):
    kind: str                     # town | location | npc
    target_id: Optional[str] = None
    text: str = ""


class GenerateScenarioBody(BaseModel):
    town_id: str
    difficulty: str = "standard"
    note: str = ""


@app.get("/api/towns")
def list_towns() -> Dict[str, Any]:
    return {"towns": scenario_content.list_towns()}


@app.get("/api/towns/{town_id}")
def get_town(town_id: str) -> Dict[str, Any]:
    t = scenario_content.town_detail(town_id)
    if t is None:
        raise HTTPException(404, "no such town")
    return t


@app.post("/api/towns")
def save_town(body: SaveTownBody) -> Dict[str, Any]:
    try:
        return {"town": scenario_content.save_town(body.town, body.id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.delete("/api/towns/{town_id}")
def delete_town(town_id: str) -> Dict[str, Any]:
    try:
        scenario_content.delete_town(town_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/towns/generate")
async def generate_town(body: GenerateTownBody) -> Dict[str, Any]:
    try:
        meta = await asyncio.to_thread(llm.generate_town, body.note)
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    return {"town": meta}


@app.post("/api/towns/{town_id}/topics")
async def generate_town_topics(town_id: str) -> Dict[str, Any]:
    """Write the standing flavour topics of every resident who has none — the
    scenario-agnostic exchanges that make each townsperson worth talking to."""
    try:
        meta = await asyncio.to_thread(llm.generate_town_topics, town_id)
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    return {"town": meta}


async def _refresh_town_art(_key: str) -> None:
    """Town art landed: push it into every live scenario session in that town."""
    for session in MANAGER.all():
        sc = getattr(session, "scenario", None)
        if sc is not None and _key == f"town:{sc.town_id}":
            sc.reload_town_art()
            await _broadcast(session)


@app.post("/api/towns/{town_id}/art")
async def generate_town_art(town_id: str, body: TownArtBody) -> Dict[str, Any]:
    try:
        result = await asyncio.to_thread(art.generate_town_art, town_id, body.kind,
                                         body.target_id, body.text or "")
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    await _refresh_town_art(f"town:{town_id}")
    return result


@app.post("/api/towns/{town_id}/art/all")
async def start_town_art_queue(town_id: str) -> Dict[str, Any]:
    if scenario_content.town_detail(town_id) is None:
        raise HTTPException(404, "no such town")
    return art.QUEUE.start_items(f"town:{town_id}", art.town_art_items(town_id),
                                 _refresh_town_art)


@app.get("/api/towns/{town_id}/art/all")
def town_art_queue_status(town_id: str) -> Dict[str, Any]:
    return art.QUEUE.status(f"town:{town_id}")


# --------------------------------------------------------------------------- #
# REST: equipment (Update 17 §D17-4.3 — Options → Equipment)
# --------------------------------------------------------------------------- #
class SaveItemBody(BaseModel):
    id: Optional[str] = None
    item: Dict[str, Any]


@app.get("/api/items")
def list_items() -> Dict[str, Any]:
    from . import items as _items
    return {"items": _items.list_items()}


@app.get("/api/items/{item_id}")
def get_item(item_id: str) -> Dict[str, Any]:
    from . import items as _items
    d = _items.item_detail(item_id)
    if d is None:
        raise HTTPException(404, "no such item")
    return d


@app.post("/api/items")
def save_item(body: SaveItemBody) -> Dict[str, Any]:
    from . import items as _items
    try:
        return {"item": _items.save_item(body.item, body.id)}
    except Exception as exc:
        raise HTTPException(422, str(exc))


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str) -> Dict[str, Any]:
    from . import items as _items
    try:
        _items.delete_item(item_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/items/{item_id}/art")
async def generate_item_art(item_id: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(art.generate_item_art, item_id)
    except ValueError as exc:
        raise HTTPException(502, str(exc))


async def _refresh_nothing(_key: str) -> None:
    return None


@app.post("/api/items/art/all")
async def start_item_art_queue() -> Dict[str, Any]:
    return art.QUEUE.start_items("items", art.item_art_items(), _refresh_nothing)


@app.get("/api/items/art/all")
def item_art_queue_status() -> Dict[str, Any]:
    return art.QUEUE.status("items")


@app.get("/api/scenarios")
def list_scenarios() -> Dict[str, Any]:
    return {"scenarios": scenario_content.list_scenarios()}


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> Dict[str, Any]:
    sdef = scenario_content.scenario_detail(scenario_id)
    if sdef is None:
        raise HTTPException(404, "no such scenario")
    return sdef


@app.delete("/api/scenarios/{scenario_id}")
def delete_scenario(scenario_id: str) -> Dict[str, Any]:
    try:
        scenario_content.delete_scenario(scenario_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/scenarios/generate")
async def generate_scenario(body: GenerateScenarioBody) -> Dict[str, Any]:
    """Pre-generate a scenario for a town: the arc plus Act I fully materialized
    (town portion + adventure) so New Scenario is instant (§D17-6.1). Art for
    the Act I adventure queues afterwards; town art has its own button."""
    from .scenario import pregenerate_scenario
    try:
        meta = await asyncio.to_thread(pregenerate_scenario, body.town_id,
                                       body.difficulty, body.note)
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    adv_id = meta.get("act1_adventure_id")
    if adv_id:
        detail = content.adventure_detail(adv_id)
        if detail:
            art.QUEUE.start(f"adventure:{adv_id}",
                            [a["encounter_id"] for a in detail["phases"]],
                            _refresh_sessions_art)
    return {"scenario": meta}


@app.get("/api/games/{session_id}")
def game_status(session_id: str) -> Dict[str, Any]:
    session = MANAGER.get(session_id)
    if session is None:
        raise HTTPException(404, "no such session")
    return {
        "session_id": session.id,
        "name": session.name,
        "seats": dict(session.seats),
        "clients": len(session.clients),
    }


# --------------------------------------------------------------------------- #
# WebSocket: live play (state broadcast + action submission)
# --------------------------------------------------------------------------- #
async def _send(ws: WebSocket, msg: Dict[str, Any]) -> None:
    try:
        await ws.send_json(msg)
    except Exception:
        pass  # a dead socket is cleaned up on the disconnect path


def _prompt_msg(session) -> Dict[str, Any]:
    """The public priority pair. Computed directly rather than by building an
    unseated snapshot and reading two fields off it — this runs once per
    broadcast, and a snapshot is the expensive thing the broadcast already
    builds per client."""
    if session.state is None:
        return {"type": "prompt", "holder_character_id": None, "kind": None}
    return {"type": "prompt", **priority_fields(session.state)}


async def _broadcast(session) -> None:
    """Push a fresh (per-client filtered) state + seats + prompt to everyone."""
    prompt = _prompt_msg(session)
    # public_result suppresses a non-final phase victory in an adventure (the phase
    # boundary is a level-up gate, not a game over); plain encounters unchanged.
    result = session.public_result()
    for cid, ws in list(session.clients.items()):
        await _send(ws, {"type": "seats", **session.seats_payload(cid)})
        await _send(ws, {"type": "state", **session.snapshot_for(cid)})
        await _send(ws, prompt)
        if result is not None:
            await _send(ws, {"type": "game_over", "result": result})


@app.websocket("/ws/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: str) -> None:
    session = MANAGER.get(session_id)
    if session is None:
        # `fatal` tells the client this can never succeed (sessions live in
        # memory — a restart wipes them), so it must stop its reconnect loop
        # instead of hammering the dead id every second.
        await ws.accept()
        await ws.send_json({"type": "error", "message": "no such session",
                            "fatal": True})
        await ws.close()
        return

    await ws.accept()
    client_id = session.add_client(ws)
    await _send(ws, {"type": "hello", "client_id": client_id, "session_id": session.id})
    await _send(ws, {"type": "seats", **session.seats_payload(client_id)})
    await _send(ws, {"type": "state", **session.snapshot_for(client_id)})
    await _send(ws, _prompt_msg(session))
    # A client is here and there is a loop: pick up any spoils art still unpainted
    # (a loaded save queues from its sync endpoint, where there is no loop).
    _queue_spoils_art(session)

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "heartbeat":
                await _send(ws, {"type": "heartbeat"})

            elif mtype == "claim_seat":
                session.claim(client_id, list(msg.get("character_ids", [])))
                await _broadcast(session)

            elif mtype == "release_seat":
                session.release(client_id, list(msg.get("character_ids", [])))
                await _broadcast(session)

            elif mtype == "submit_action":
                action = msg.get("action", {})
                index = action.get("index")
                if not isinstance(index, int):
                    await _send(ws, {"type": "error", "message": "action.index required"})
                    continue
                mana = action.get("mana")
                if mana is not None and not isinstance(mana, list):
                    await _send(ws, {"type": "error", "message": "action.mana must be a list"})
                    continue
                async with session.lock():
                    try:
                        # drain=False: the player's own action lands instantly;
                        # the synthetic follow-up (auto-passes, resolutions,
                        # enemy steps) drains PACED — one broadcast per step,
                        # a beat between the ones worth watching.
                        session.apply_index(client_id, index, mana, drain=False)
                    except Exception as exc:
                        # ValueError is a rejection (illegal index / not your seat).
                        # Anything else is an engine fault mid-resolution — report it
                        # and keep the socket, because dropping it here would release
                        # this client's seats and force everyone to re-claim their
                        # characters. `apply_action` works on a deep copy, so the
                        # session's state is still the last good one either way.
                        if not isinstance(exc, ValueError):
                            traceback.print_exc()
                        await _send(ws, {"type": "error", "message": str(exc) or
                                         f"{type(exc).__name__} while resolving"})
                        # Re-sync just this client so its optimistic arming reverts.
                        await _send(ws, {"type": "state", **session.snapshot_for(client_id)})
                        continue
                await _broadcast(session)
                session.start_pacer(_broadcast)

            elif mtype == "town":
                # Scenario Mode (Update 17 §D17-5.2): a town verb — visit /
                # leave / talk / choose / attribute / start_adventure / save.
                async with session.lock():
                    try:
                        verb = str(msg.get("verb") or "")
                        if session.scenario is not None and session.state is not None:
                            # In a fight: only the economy verbs (gear at the
                            # gate, the rewards modal) apply.
                            session.economy_verb(client_id, verb, msg.get("payload") or {})
                        else:
                            session.town_verb(client_id, verb, msg.get("payload") or {})
                    except ValueError as exc:
                        await _send(ws, {"type": "error", "message": str(exc)})
                        continue
                await _broadcast(session)
                _after_town_change(session)

            elif mtype == "confirm":
                # The all-players confirmation (T-84): yes / no / cancel.
                async with session.lock():
                    cid_ = int(msg.get("id") or 0)
                    if msg.get("cancel"):
                        session.cancel_confirm(client_id, cid_)
                    else:
                        session.answer_confirm(client_id, cid_, bool(msg.get("yes", True)))
                await _broadcast(session)
                _after_town_change(session)

            elif mtype == "retry_job":
                if session.scenario is not None:
                    _scenario_async(session, "adventure_job")
                await _broadcast(session)

            elif mtype == "confirm_level_up":
                # The between-phases gate (Update 10 §D10-3.3): one confirmation
                # per controlled character; the last confirmation composes the
                # next phase (carry-over applied) before the broadcast.
                async with session.lock():
                    try:
                        session.confirm_level_up(
                            client_id,
                            str(msg.get("character_id") or ""),
                            msg.get("build") or {})
                    except ValueError as exc:
                        await _send(ws, {"type": "error", "message": str(exc)})
                        await _send(ws, {"type": "state", **session.snapshot_for(client_id)})
                        continue
                await _broadcast(session)

            else:
                await _send(ws, {"type": "error", "message": f"unknown message: {mtype}"})

    except WebSocketDisconnect:
        pass
    finally:
        session.remove_client(client_id)
        await _broadcast(session)


# --------------------------------------------------------------------------- #
# Static art: served from the tracked content dir, with the legacy loadouts art
# dir as a read-only fallback (pre-split installs), under one /art URL space. +
# static client (mounted last so /api/* wins)
# --------------------------------------------------------------------------- #
app.include_router(appctl.router)


# Every art filename is unique to its bytes — generated pieces carry a random
# token per write (art._write_image), cached portraits their content hash — so a
# URL here never changes what it serves and the browser can keep it forever.
# Worth saying out loud: portraits are re-referenced by every state broadcast,
# and a revalidation round-trip per image per client adds up on a remote host.
_ART_CACHE_CONTROL = "public, max-age=31536000, immutable"


@app.get(art.ART_URL_PREFIX + "/{image_path:path}")
def serve_art(image_path: str) -> FileResponse:
    for base in (art.ART_DIR, art.LEGACY_ART_DIR):
        p = (base / image_path).resolve()
        if p.is_relative_to(base.resolve()) and p.is_file():
            return FileResponse(p, headers={"Cache-Control": _ART_CACHE_CONTROL})
    raise HTTPException(status_code=404, detail="no such image")


# Panel animation clips (Update 16): uploaded through the deckbuilder into the
# gitignored loadouts/anim/<char>/ folder; content/anim/ is a tracked fallback
# for clips shipped with the repo. Same URL scheme as the deckbuilder's preview.
ANIM_DIRS = (content.LOADOUTS_DIR / "anim", content.CONTENT_DIR / "anim")


@app.get("/anim/{clip_path:path}")
def serve_anim(clip_path: str) -> FileResponse:
    for base in ANIM_DIRS:
        p = (base / clip_path).resolve()
        if p.is_relative_to(base.resolve()) and p.is_file():
            return FileResponse(p)
    raise HTTPException(status_code=404, detail="no such animation")


_PLACEHOLDER = """<!doctype html><html><head><meta charset="utf-8">
<title>LTG-Game</title></head><body style="font-family:system-ui;padding:2rem">
<h1>LTG-Game</h1>
<p>The client bundle isn't built yet. Build it with:</p>
<pre>cd apps/game-ui &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>or run <code>LTG-Game</code> (it builds automatically). The API is live at
<code>/api/setup-options</code>.</p></body></html>"""


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="client")
else:
    @app.get("/", response_class=HTMLResponse)
    def _placeholder() -> str:
        return _PLACEHOLDER
