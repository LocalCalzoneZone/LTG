"""The LTG-Game FastAPI app: REST lobby, per-session WebSocket, static client.

Authority/relay only. Every action flows through the engine via `Session.apply_index`;
this layer computes no rules. See INTERFACE_NOTES.md for the state contract.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import appctl, art, content, llm
from .adventure import AdventureRun
from .session import SessionManager

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


# --------------------------------------------------------------------------- #
# REST: lobby / setup
# --------------------------------------------------------------------------- #
class CreateGameBody(BaseModel):
    character_ids: List[str]
    # Exactly one of these: a standalone encounter, or an adventure (Update 10 —
    # the session then runs the three-act flow: carry-over, level-ups, splashes).
    encounter_id: Optional[str] = None
    adventure_id: Optional[str] = None


@app.get("/api/setup-options")
def setup_options() -> Dict[str, Any]:
    return {
        "characters": content.list_characters(),
        "encounters": content.list_encounters(),
        "adventures": content.list_adventures(),
    }


@app.post("/api/games")
def create_game(body: CreateGameBody) -> Dict[str, Any]:
    if bool(body.encounter_id) == bool(body.adventure_id):
        raise HTTPException(400, "choose an encounter or an adventure")
    try:
        if body.adventure_id:
            run = AdventureRun(body.adventure_id)
            state, portraits, game_art, encounter_id = run.start(
                body.character_ids, seed=random.randrange(2**31))
            session = MANAGER.create(state, name=run.name, portraits=portraits,
                                     encounter_id=encounter_id, art=game_art,
                                     adventure=run)
            return {"session_id": session.id}
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
# Acts are ordinary encounters (reserved ids) edited through the encounter
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
    """The full adventure: wrapper fields + each act's embedded encounter."""
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
    """Remove an adventure and its act files."""
    try:
        content.delete_adventure(adventure_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/adventures/generate")
def generate_adventure(body: GenerateAdventureBody) -> Dict[str, Any]:
    """Generate + persist a whole three-act adventure in one model call,
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
    instructions: Optional[str] = None
    art_style: Optional[str] = None
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
# variant covers its acts in order (Act I first, so play can start while later
# acts paint); completed images broadcast to sessions as they land.
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
    act_ids = [a["encounter_id"] for a in detail["acts"]]
    return art.QUEUE.start(f"adventure:{adventure_id}", act_ids,
                           _refresh_sessions_art)


@app.get("/api/adventures/{adventure_id}/art/all")
def adventure_art_queue_status(adventure_id: str) -> Dict[str, Any]:
    return art.QUEUE.status(f"adventure:{adventure_id}")


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
    snap = session.snapshot_for("")  # unseated view: public priority fields only
    pr = snap["priority"]
    return {"type": "prompt",
            "holder_character_id": pr["holder_character_id"],
            "kind": pr["kind"]}


async def _broadcast(session) -> None:
    """Push a fresh (per-client filtered) state + seats + prompt to everyone."""
    prompt = _prompt_msg(session)
    # public_result suppresses a non-final act victory in an adventure (the act
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
                        session.apply_index(client_id, index, mana)
                    except ValueError as exc:
                        await _send(ws, {"type": "error", "message": str(exc)})
                        # Re-sync just this client so its optimistic arming reverts.
                        await _send(ws, {"type": "state", **session.snapshot_for(client_id)})
                        continue
                await _broadcast(session)

            elif mtype == "confirm_level_up":
                # The between-acts gate (Update 10 §D10-3.3): one confirmation
                # per controlled character; the last confirmation composes the
                # next act (carry-over applied) before the broadcast.
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


@app.get(art.ART_URL_PREFIX + "/{image_path:path}")
def serve_art(image_path: str) -> FileResponse:
    for base in (art.ART_DIR, art.LEGACY_ART_DIR):
        p = (base / image_path).resolve()
        if p.is_relative_to(base.resolve()) and p.is_file():
            return FileResponse(p)
    raise HTTPException(status_code=404, detail="no such image")


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
