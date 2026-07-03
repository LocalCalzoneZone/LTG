"""Sessions: authoritative engine state + seats + connected clients.

A `Session` owns exactly one engine `GameState` (authoritative) and the seat map
`character_id -> client_id`. Seats are a pure server concept — the engine is
seat-unaware (INTERFACE_NOTES §5). The session enforces two things the engine does
not: hidden information (a client only ever receives hands/legal-actions for
characters it controls) and action gating (a client may only act for characters it
controls). Legality itself is always the engine's `apply_action`.

In-memory only for Phase 1 (a restart drops games).
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Dict, List, Optional, Set

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.state import GameState

from .snapshot import build_snapshot


def _short_id(n: int = 8) -> str:
    return secrets.token_urlsafe(6)[:n]


class Session:
    def __init__(self, session_id: str, state: GameState, name: str = "",
                 portraits: Optional[Dict[str, str]] = None) -> None:
        self.id = session_id
        self.name = name
        self.state = state  # authoritative (un-settled) engine state
        # character_id -> portrait (data URL / image URL); the engine drops it.
        self.portraits: Dict[str, str] = portraits or {}
        # character_id -> client_id (None == unclaimed)
        self.seats: Dict[str, Optional[str]] = {c.id: None for c in state.party}
        # client_id -> websocket-like send target (set by the app layer)
        self.clients: Dict[str, Any] = {}
        # Created lazily from within the event loop: a Session is constructed by the
        # sync REST endpoint (a threadpool worker with no running loop on 3.9).
        self._lock: Optional[asyncio.Lock] = None

    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # -- clients ------------------------------------------------------------- #
    def add_client(self, ws: Any) -> str:
        client_id = _short_id()
        self.clients[client_id] = ws
        return client_id

    def remove_client(self, client_id: str) -> None:
        self.clients.pop(client_id, None)
        # Release that client's seats so others can claim them.
        for cid, owner in self.seats.items():
            if owner == client_id:
                self.seats[cid] = None

    # -- seats --------------------------------------------------------------- #
    def controlled_by(self, client_id: str) -> Set[str]:
        return {cid for cid, owner in self.seats.items() if owner == client_id}

    def claim(self, client_id: str, character_ids: List[str]) -> None:
        for cid in character_ids:
            if cid in self.seats and self.seats[cid] in (None, client_id):
                self.seats[cid] = client_id

    def release(self, client_id: str, character_ids: List[str]) -> None:
        for cid in character_ids:
            if self.seats.get(cid) == client_id:
                self.seats[cid] = None

    def seats_payload(self, client_id: str) -> Dict[str, Any]:
        return {
            "seats": dict(self.seats),
            "you": sorted(self.controlled_by(client_id)),
        }

    # -- actions (authority) ------------------------------------------------- #
    def apply_index(self, client_id: str, index: int,
                    mana: Optional[List[str]] = None) -> None:
        """Validate + apply a legal-action index submitted by `client_id`.

        `mana` is an optional explicit payment (the exact colours to spend) for a
        cast whose generic portion could be paid multiple ways; the engine
        re-validates it covers the cost.

        Raises ValueError (turned into an `error` message) on any rejection:
        out-of-range index, a character the client does not control, or an action
        the engine no longer considers legal.
        """
        actions = legal_actions(self.state)
        if not 0 <= index < len(actions):
            raise ValueError("action index out of range")
        action = actions[index]
        if self.seats.get(action.actor_id) != client_id:
            raise ValueError("you do not control that character")
        if mana is not None:
            action.mana = list(mana)
        # apply_action re-validates against the engine's current legal set as well.
        new_state, _events = apply_action(self.state, action)
        self.state = new_state

    # -- snapshots ----------------------------------------------------------- #
    def snapshot_for(self, client_id: str) -> Dict[str, Any]:
        return build_snapshot(self.state, self.controlled_by(client_id), self.portraits)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create(self, state: GameState, name: str = "",
               portraits: Optional[Dict[str, str]] = None) -> Session:
        session_id = _short_id()
        while session_id in self._sessions:
            session_id = _short_id()
        session = Session(session_id, state, name=name, portraits=portraits)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions
