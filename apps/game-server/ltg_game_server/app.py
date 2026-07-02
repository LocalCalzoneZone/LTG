"""The LTG-Game FastAPI app: REST lobby, per-session WebSocket, static client.

Authority/relay only. Every action flows through the engine via `Session.apply_index`;
this layer computes no rules. See INTERFACE_NOTES.md for the state contract.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import content
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
    encounter_id: str


@app.get("/api/setup-options")
def setup_options() -> Dict[str, Any]:
    return {
        "characters": content.list_characters(),
        "encounters": content.list_encounters(),
    }


@app.post("/api/games")
def create_game(body: CreateGameBody) -> Dict[str, Any]:
    try:
        state, portraits = content.build_state(
            body.character_ids, body.encounter_id, seed=random.randrange(2**31)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    encounter = content.encounter_for(body.encounter_id)
    session = MANAGER.create(state, name=encounter["name"] if encounter else "",
                             portraits=portraits)
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
    for cid, ws in list(session.clients.items()):
        await _send(ws, {"type": "seats", **session.seats_payload(cid)})
        await _send(ws, {"type": "state", **session.snapshot_for(cid)})
        await _send(ws, prompt)
        if session.state.result is not None:
            await _send(ws, {"type": "game_over", "result": session.state.result})


@app.websocket("/ws/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: str) -> None:
    session = MANAGER.get(session_id)
    if session is None:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "no such session"})
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
                async with session.lock():
                    try:
                        session.apply_index(client_id, index)
                    except ValueError as exc:
                        await _send(ws, {"type": "error", "message": str(exc)})
                        # Re-sync just this client so its optimistic arming reverts.
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
# Static client (mounted last so /api/* and /ws/* win)
# --------------------------------------------------------------------------- #
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
