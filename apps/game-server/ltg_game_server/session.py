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
import random
import secrets
from typing import Any, Dict, List, Optional, Set

from ltg_combat.engine import apply_action, auto_pass_action, legal_actions
from ltg_combat.state import GameState

from .adventure import AdventureRun
from .snapshot import build_snapshot

# Safety valve for the auto-pass loop (D8-4): each synthetic action strictly
# advances the game, but cap the chain so a rules bug can never spin forever.
_AUTO_CAP = 200

# Resolution pacing (the MTG-Arena beat): over the WebSocket path, synthetic
# auto-advance steps drain asynchronously — one broadcast per step, with a
# pause after any step worth watching — so a chain of auto-passes and stack
# resolutions arrives as a readable sequence instead of one collapsed jump.
# Server wall-clock, so every connected client sees the same beats. Player
# clicks are never delayed; only the synthetic steps between them are.
PACE_BEAT_S = 1.1   # after a resolution / an effect landing — watch it finish
PACE_HOLD_S = 0.6   # after a pass on a live stack — the about-to-resolve hold
PACE_STEP_S = 0.18  # after silent bookkeeping (an auto end-turn on an empty board)

# Log entry types whose appearance in a step's delta means "the player should
# watch this land" — the step earns the full beat.
_PACE_VISIBLE = frozenset({
    "resolve", "damage", "heal", "wound", "intent_execute", "channel_trigger",
    "charge_detonate", "enemy_died", "token_died", "revive", "incapacitated",
    "enemy_move", "intent_declared",
})


def _short_id(n: int = 8) -> str:
    return secrets.token_urlsafe(6)[:n]


class Session:
    def __init__(self, session_id: str, state: GameState, name: str = "",
                 portraits: Optional[Dict[str, str]] = None,
                 encounter_id: str = "",
                 art: Optional[Dict[str, Any]] = None,
                 adventure: Optional[AdventureRun] = None) -> None:
        self.id = session_id
        self.name = name
        self.state = state  # authoritative (un-settled) engine state
        # Presentation pacing (engine settle stops): ONLY the game server's
        # states are paced — the runner, cockpit and tests never set this.
        self.state.paced = True
        # The adventure this session runs, or None for a plain encounter —
        # every adventure behaviour below is gated on it (Update 10 §D10-7).
        self.adventure = adventure
        # Smart auto-pass (D8-4) runs from the first snapshot: a character with
        # nothing meaningful to do at the opening window is passed for, silently.
        self._auto_advance()
        # character_id -> portrait (data URL / image URL); the engine drops it.
        self.portraits: Dict[str, str] = portraits or {}
        # Which encounter this game was built from, and its generated art
        # ({"scene": url, "enemies": {pool_id: url}, "base_of": {live_id: pool_id}})
        # — the engine drops both; art can be regenerated mid-game (see app.py's
        # art endpoints, which call set_art + re-broadcast).
        self.encounter_id = encounter_id
        self.art: Dict[str, Any] = art or {"scene": "", "enemies": {}, "base_of": {}}
        # character_id -> client_id (None == unclaimed)
        self.seats: Dict[str, Optional[str]] = {c.id: None for c in state.party}
        # client_id -> websocket-like send target (set by the app layer)
        self.clients: Dict[str, Any] = {}
        # Created lazily from within the event loop: a Session is constructed by the
        # sync REST endpoint (a threadpool worker with no running loop on 3.9).
        self._lock: Optional[asyncio.Lock] = None
        # The one live pacing task draining synthetic steps (ws path only).
        self._pacer: Optional["asyncio.Task[None]"] = None

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
                    mana: Optional[List[str]] = None,
                    drain: bool = True) -> None:
        """Validate + apply a legal-action index submitted by `client_id`.

        `mana` is an optional explicit payment (the exact colours to spend) for a
        cast whose generic portion could be paid multiple ways; the engine
        re-validates it covers the cost.

        `drain=True` (the default, and every non-ws caller) runs the smart
        auto-pass chain synchronously, exactly as before. The ws path passes
        `drain=False` and starts the PACED drain instead (`start_pacer`), so
        the synthetic steps arrive as separate, spaced broadcasts.

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
        if drain:
            # Smart auto-pass / auto end-turn (D8-4): after every state change,
            # submit synthetic actions for seats with no meaningful option.
            self._auto_advance()
        elif self.adventure is not None:
            # The paced drain runs the hook per step; the player's own action
            # still needs one here (it may itself have won the phase).
            self.adventure.on_state_change(self.state)

    def _auto_advance(self) -> None:
        """Drain every no-decision priority stop (D8-4): while the engine-truth
        check says the priority holder's legal set holds nothing beyond
        pass/end_turn (with the drop-channels refinement), submit the synthetic
        action through the same `apply_action` path a click takes. Each is logged
        distinctly ("… passes (auto)"). Choices and the capacity pick always
        wait; the cockpit, being a debugger, never runs this."""
        for _ in range(_AUTO_CAP):
            action = auto_pass_action(self.state)
            if action is None:
                break
            new_state, _events = apply_action(self.state, action)
            self.state = new_state
        # Adventure hook: a won phase opens the level-up gate; a won finale marks
        # the run complete. No-op (and never reached) for plain encounters.
        if self.adventure is not None:
            self.adventure.on_state_change(self.state)

    # -- paced auto-advance (the ws path's resolution rhythm) ------------------ #
    def start_pacer(self, broadcast: Any) -> None:
        """Ensure one paced-drain task is running. `broadcast` is an async
        callable taking this session (the app layer's `_broadcast`). Idempotent:
        a live pacer already drains everything there is to drain."""
        if self._pacer is not None and not self._pacer.done():
            return
        self._pacer = asyncio.get_event_loop().create_task(
            self._drain_paced(broadcast))

    async def _drain_paced(self, broadcast: Any) -> None:
        """The synchronous `_auto_advance` chain, unrolled over wall time: one
        synthetic step per broadcast, a full beat after any step the player
        should watch (a resolution landing, or a pass while something sits on
        the stack — the about-to-resolve moment), a blink after bookkeeping.

        The SETTLE step (engine settle stop: a resolution just emptied the
        stack) sleeps BEFORE applying instead — that leading beat is the
        window in which the resolution's animations play out with nothing
        else moving; only then does the flow take its next step (the next
        enemy's declaration, the phase flip), as its own broadcast.

        The lock is held only while stepping, never while sleeping, so real
        player actions interleave freely; each iteration re-reads the live
        state, so anything a player does mid-drain is simply drained from."""
        for _ in range(_AUTO_CAP):
            async with self.lock():
                pending = auto_pass_action(self.state)
            if pending is None:
                return
            if pending.kind == "settle":
                await asyncio.sleep(PACE_BEAT_S)  # watch the resolution land
            async with self.lock():
                # Re-read after any sleep: a player may have acted meanwhile.
                action = auto_pass_action(self.state)
                if action is None:
                    return
                stack_live = bool(self.state.stack)
                log_before = len(self.state.log)
                new_state, _events = apply_action(self.state, action)
                self.state = new_state
                if self.adventure is not None:
                    self.adventure.on_state_change(self.state)
                effects = any(e.type in _PACE_VISIBLE
                              for e in self.state.log[log_before:])
                dwell = (PACE_BEAT_S if effects
                         else PACE_HOLD_S if stack_live
                         else PACE_STEP_S)
            await broadcast(self)
            await asyncio.sleep(dwell)

    # -- adventures (Update 10) ----------------------------------------------- #
    def public_result(self) -> Optional[str]:
        """The result the CLIENTS should see: a non-final phase victory is a phase
        boundary (the level-up gate), not a game over."""
        result = self.state.result
        if (self.adventure is not None
                and self.adventure.suppresses_result(result)):
            return None
        return result

    def confirm_level_up(self, client_id: str, character_id: str,
                         build: Dict[str, Any]) -> None:
        """Apply one seat's level-up confirmation; when the last seat confirms,
        compose the next phase (carry-over applied) and swap it in."""
        if self.adventure is None:
            raise ValueError("this game is not an adventure")
        if self.seats.get(character_id) != client_id:
            raise ValueError("you do not control that character")
        self.adventure.confirm_level_up(character_id, build)
        if self.adventure.all_confirmed():
            state, portraits, art, encounter_id = self.adventure.advance(
                seed=random.randrange(2**31))
            self.state = state
            self.state.paced = True  # a fresh phase's state is paced like the first
            self.portraits = portraits
            self.art = art
            self.encounter_id = encounter_id
            self._auto_advance()

    def set_art(self, art: Dict[str, Any]) -> None:
        """Swap in fresh art references (scene + pool-enemy urls), keeping this
        session's live-id -> pool-id map (the roster never changes mid-game) and
        the party's loadout descriptions (encounter_art knows neither)."""
        self.art = {**art, "base_of": self.art.get("base_of", {}),
                    "char_descriptions": self.art.get("char_descriptions", {})}

    # -- snapshots ----------------------------------------------------------- #
    def snapshot_for(self, client_id: str) -> Dict[str, Any]:
        controlled = self.controlled_by(client_id)
        snap = build_snapshot(self.state, controlled,
                              self.portraits, art=self.art,
                              encounter_id=self.encounter_id)
        if self.adventure is not None:
            # The adventure block (phase, narration, the per-seat level-up gate) —
            # and a suppressed result at a non-final phase boundary, where the
            # engine's "victory" means "phase won", not "game over".
            snap["adventure"] = self.adventure.snapshot_block(self.state, controlled)
            result = self.public_result()
            snap["result"] = result
            snap["game_over"] = {"result": result} if result is not None else None
        return snap


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create(self, state: GameState, name: str = "",
               portraits: Optional[Dict[str, str]] = None,
               encounter_id: str = "",
               art: Optional[Dict[str, Any]] = None,
               adventure: Optional[AdventureRun] = None) -> Session:
        session_id = _short_id()
        while session_id in self._sessions:
            session_id = _short_id()
        session = Session(session_id, state, name=name, portraits=portraits,
                          encounter_id=encounter_id, art=art,
                          adventure=adventure)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def all(self) -> List[Session]:
        return list(self._sessions.values())
