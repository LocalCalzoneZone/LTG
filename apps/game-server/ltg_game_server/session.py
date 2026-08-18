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
import time
from typing import Any, Callable, Dict, List, Optional, Set

from ltg_combat.engine import apply_action, auto_pass_action, legal_actions
from ltg_combat.state import GameState

from .adventure import AdventureRun
from .snapshot import build_snapshot

if False:  # typing only (avoid an import cycle at runtime)
    from .runs import RunManager  # noqa: F401
    from .scenario import ScenarioRun  # noqa: F401

# T-84: the all-players confirmation auto-yes timeout.
CONFIRM_TIMEOUT_S = 30.0

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
    def __init__(self, session_id: str, state: Optional[GameState], name: str = "",
                 portraits: Optional[Dict[str, str]] = None,
                 encounter_id: str = "",
                 art: Optional[Dict[str, Any]] = None,
                 adventure: Optional[AdventureRun] = None,
                 run_id: Optional[str] = None,
                 run_manager: Optional["RunManager"] = None,
                 scenario: Optional["ScenarioRun"] = None) -> None:
        self.id = session_id
        self.name = name
        # The run this session plays inside (Update 17 §D17-3), or None for a
        # plain encounter / an adventure outside a run (byte-identical to
        # before). Save points call back into the manager; every save appends.
        self.run_id = run_id
        self.run_manager = run_manager
        self._end_saved = False
        self.last_save: Optional[Dict[str, Any]] = None
        # The scenario (campaign) this session plays, or None (§D17-1). With a
        # scenario the session has TWO modes: town (state is None; the town
        # screen is the snapshot) and adventure (an AdventureRun + engine
        # state, exactly as an adventure outside a scenario).
        self.scenario = scenario
        # The app layer's hook for work that must leave the lock (LLM calls
        # off-thread, timers): called with (session, kind) after a transition.
        self.async_hook: Optional[Callable[["Session", str], None]] = None
        # The all-players confirmation (T-84), or None.
        self.confirm: Optional[Dict[str, Any]] = None
        self._confirm_seq = 0
        # The last scenario transition ("next_act" / "scenario_complete" /
        # "everquest" / "town" / "dead") — informational, for the app + tests.
        self.pending_transition: Optional[str] = None
        self.state = state  # authoritative (un-settled) engine state (None in town)
        # Presentation pacing (engine settle stops): ONLY the game server's
        # states are paced — the runner, cockpit and tests never set this.
        if self.state is not None:
            self.state.paced = True
        # The adventure this session runs, or None for a plain encounter —
        # every adventure behaviour below is gated on it (Update 10 §D10-7).
        self.adventure = adventure
        # character_id -> portrait (data URL / image URL); the engine drops it.
        self.portraits: Dict[str, str] = portraits or {}
        # Which encounter this game was built from, and its generated art
        # ({"scene": url, "enemies": {pool_id: url}, "base_of": {live_id: pool_id}})
        # — the engine drops both; art can be regenerated mid-game (see app.py's
        # art endpoints, which call set_art + re-broadcast).
        self.encounter_id = encounter_id
        self.art: Dict[str, Any] = art or {"scene": "", "enemies": {}, "base_of": {}}
        # character_id -> client_id (None == unclaimed). In town the seats are
        # the roster ids; in combat the live ids (remapped by slot).
        if state is not None:
            self.seats: Dict[str, Optional[str]] = {c.id: None for c in state.party}
        elif scenario is not None:
            self.seats = {cid: None for cid in scenario.character_ids}
        else:
            self.seats = {}
        # Smart auto-pass (D8-4) runs from the first snapshot: a character with
        # nothing meaningful to do at the opening window is passed for, silently.
        if self.state is not None:
            self._auto_advance()
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
        if self.state is None:
            raise ValueError("no fight is in progress")
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
            self._run_hooks()

    def _auto_advance(self) -> None:
        """Drain every no-decision priority stop (D8-4): while the engine-truth
        check says the priority holder's legal set holds nothing beyond
        pass/end_turn (with the drop-channels refinement), submit the synthetic
        action through the same `apply_action` path a click takes. Each is logged
        distinctly ("… passes (auto)"). Choices and the capacity pick always
        wait; the cockpit, being a debugger, never runs this."""
        if self.state is None:
            return
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
            self._run_hooks()

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
                if self.state is None:
                    return
                pending = auto_pass_action(self.state)
            if pending is None:
                return
            if pending.kind == "settle":
                await asyncio.sleep(PACE_BEAT_S)  # watch the resolution land
            async with self.lock():
                # Re-read after any sleep: a player may have acted meanwhile.
                if self.state is None:
                    return
                action = auto_pass_action(self.state)
                if action is None:
                    return
                stack_live = bool(self.state.stack)
                log_before = len(self.state.log)
                new_state, _events = apply_action(self.state, action)
                self.state = new_state
                if self.adventure is not None:
                    self.adventure.on_state_change(self.state)
                    self._run_hooks()
                effects = any(e.type in _PACE_VISIBLE
                              for e in self.state.log[log_before:])
                dwell = (PACE_BEAT_S if effects
                         else PACE_HOLD_S if stack_live
                         else PACE_STEP_S)
            await broadcast(self)
            await asyncio.sleep(dwell)

    # -- runs (Update 17 §D17-3) ---------------------------------------------- #
    def save_point(self, kind: str, seed: Optional[int], auto: bool = True) -> None:
        """Write a save for the bound run (no-op outside a run). Never raises
        into the game: a failed save is logged on the session, not fatal."""
        if self.run_id is None or self.run_manager is None:
            return
        if self.adventure is None and self.scenario is None:
            return
        try:
            self.last_save = self.run_manager.save(self.run_id, self.adventure,
                                                   kind, seed, auto=auto,
                                                   scenario=self.scenario)
        except Exception as exc:  # pragma: no cover — disk trouble
            self.last_save = {"error": str(exc), "kind": kind}

    def _run_hooks(self) -> None:
        """After any adventure state change: the adventure-end auto-save, the
        Hardcore death mark on defeat (§D17-6.4), and — inside a scenario —
        the return to town / the end of the run."""
        if self.adventure is None or self.state is None:
            return
        if self.run_id is None or self.run_manager is None:
            if self.scenario is not None:
                self._scenario_transitions()
            return
        if self.adventure.complete and not self._end_saved:
            self._end_saved = True
            self.save_point("adventure_end", None)
            if self.scenario is not None:
                self._scenario_transitions()
        elif self.state.result == "defeat" and not self._end_saved:
            self._end_saved = True
            if self.scenario is not None:
                self._scenario_transitions()
            else:
                try:
                    run = self.run_manager.run_detail(self.run_id)
                    if run.get("options", {}).get("hardcore"):
                        self.run_manager.mark_dead(self.run_id)
                except Exception:
                    pass

    # -- scenarios (Update 17) ------------------------------------------------ #
    def _scenario_transitions(self) -> None:
        """The adventure ended inside a scenario: won → the next act (or the
        scenario's end / a new Everquest arc); lost → Normal returns to town
        with `defeated_once`, Hardcore ends the run. The town screen shows the
        return splash while the next act materializes off-thread."""
        sc = self.scenario
        if sc is None or self.adventure is None or self.state is None:
            return
        if self.adventure.complete:
            transition = sc.on_adventure_complete(self.state)
            self.pending_transition = transition
            if transition == "next_act":
                self._enter_town(materialization=None)
                self._request_async("materialize")
            elif transition == "everquest":
                self._enter_town(materialization=None)
                self._request_async("new_arc")
            else:  # scenario_complete
                self._enter_town(materialization=None, complete=True)
        elif self.state.result == "defeat":
            outcome = sc.on_adventure_defeat(self.state)
            self.pending_transition = outcome
            if outcome == "dead":
                if self.run_id and self.run_manager:
                    try:
                        self.run_manager.mark_dead(self.run_id)
                    except Exception:
                        pass
                self._enter_town(materialization=None, complete=True)
            else:
                self._enter_town(materialization=None)
                self._request_async("materialize")

    def _request_async(self, kind: str) -> None:
        if self.async_hook is not None:
            self.async_hook(self, kind)

    def _remap_seats(self, from_ids: List[str], to_ids: List[str]) -> None:
        owners = [self.seats.get(a) for a in from_ids]
        self.seats = {b: owners[i] if i < len(owners) else None for i, b in enumerate(to_ids)}

    def _enter_town(self, materialization: Optional[Dict[str, Any]],
                    complete: bool = False) -> None:
        """Swap the session into town mode (state None); the return splash
        (or the run's end) is what the clients see next."""
        sc = self.scenario
        assert sc is not None
        live_ids = list(self.adventure.live_ids) if self.adventure else []
        self.adventure = None
        self.state = None
        self.encounter_id = ""
        self.art = {"scene": "", "enemies": {}, "base_of": {}}
        self._end_saved = False
        if live_ids:
            self._remap_seats(live_ids, sc.character_ids)
        else:
            self.seats = {cid: self.seats.get(cid) for cid in sc.character_ids}
        if complete:
            sc.mode = "complete"
            sc.splash = None
            return
        sc.arrive(materialization)
        if materialization is not None:
            self.save_point("act_start", None)

    def scenario_enter_town(self, materialization: Optional[Dict[str, Any]]) -> None:
        """First arrival (a fresh scenario run) — public wrapper."""
        self._enter_town(materialization)

    def materialize_act(self) -> None:
        """Run the act's town-portion generation (BLOCKING — the app runs it in
        a thread); on success auto-save the act start."""
        sc = self.scenario
        if sc is None:
            return
        try:
            sc.materialize()
        except ValueError:
            return
        self.save_point("act_start", None)

    def new_arc(self, arc: Dict[str, Any]) -> None:
        sc = self.scenario
        if sc is None:
            return
        sc.begin_next_arc(arc)
        if self.run_id and self.run_manager:
            try:
                self.run_manager.set_arc(self.run_id, arc)
            except Exception:
                pass
        sc.arrive(None)

    def start_adventure(self) -> None:
        """Start Adventure (after the all-players confirmation): compose Phase I
        from the run's party and swap into adventure mode; auto-save."""
        sc = self.scenario
        if sc is None:
            raise ValueError("this game is not a scenario")
        if sc.mode != "town" or sc.conversation is not None:
            raise ValueError("leave the conversation first")
        if not sc.adventure_ready:
            raise ValueError("the adventure is not ready yet")
        seed = random.randrange(2**31)
        state, portraits, art, eid = sc.start_adventure(seed=seed)
        self.adventure = sc.adventure
        self.state = state
        self.state.paced = True
        self.portraits = portraits
        self.art = art
        self.encounter_id = eid
        self._end_saved = False
        self._remap_seats(sc.character_ids, list(sc.adventure.live_ids))
        self._auto_advance()
        self.save_point("adventure_start", seed)

    def town_verb(self, client_id: str, verb: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """A town action from a client. Party-wide verbs (visit / leave / start
        adventure / party-wide dialogue choices / rest) go through
        `request_confirm`; per-player ones apply at once. Returns the hooks
        fired (dialogue) so the app can start jobs / saves."""
        sc = self.scenario
        if sc is None or sc.mode != "town":
            raise ValueError("not in town")
        if sc.dead:
            raise ValueError("this run is over")
        if verb == "dismiss_splash":
            sc.clear_splash()
            return []
        if verb == "visit":
            loc_id = str(payload.get("location_id") or "")
            loc = next((l for l in sc.town["locations"] if l["id"] == loc_id), None)
            if loc is None:
                raise ValueError("no such location")
            self.request_confirm(client_id, "visit", f"Visit {loc['name']}?",
                                 lambda: sc.visit(loc_id))
            return []
        if verb == "leave":
            self.request_confirm(client_id, "leave", "Leave for the town square?", sc.leave)
            return []
        if verb == "talk":
            sc.talk(str(payload.get("npc_id") or ""))
            sc.conversation.initiator = client_id  # type: ignore[union-attr]
            return []
        if verb == "attribute":
            self._require_initiator(client_id)
            sc.attribute(str(payload.get("character_id") or ""))
            return []
        if verb == "end_talk":
            sc.end_conversation()
            return []
        if verb == "choose":
            self._require_initiator(client_id)
            index = int(payload.get("index", -1))
            if sc.choice_is_party_wide(index):
                label = sc.choice_label(index)
                is_accept = False
                node = sc.conversation.node if sc.conversation else None
                if node:
                    kinds = {h["kind"] for h in node["choices"][index].get("effects", [])}
                    is_accept = "grant_quest" in kinds
                prompt = (f'Accept "{sc.quest.get("title", "the quest")}" as your next quest?'
                          if is_accept else f"{label}")
                self.request_confirm(client_id, "choice", prompt,
                                     lambda: self._fire_choice(index))
                return []
            return self._fire_choice(index)
        if verb == "start_adventure":
            if not sc.adventure_ready:
                raise ValueError("the adventure is not ready yet")
            name = sc.adventure_detail.get("name", "the adventure") if sc.adventure_detail else "the adventure"
            self.request_confirm(client_id, "start_adventure", f"Ride out — {name}?",
                                 self.start_adventure)
            return []
        if verb == "save":
            self.save_point("town", None, auto=False)
            return []
        raise ValueError(f"unknown town verb: {verb}")

    def _require_initiator(self, client_id: str) -> None:
        sc = self.scenario
        conv = sc.conversation if sc else None
        if conv is None:
            raise ValueError("no conversation")
        if getattr(conv, "initiator", client_id) != client_id and len(self.clients) > 1:
            raise ValueError("the player who started the conversation chooses")

    def _fire_choice(self, index: int) -> List[Dict[str, Any]]:
        sc = self.scenario
        assert sc is not None
        fired = sc.choose(index)
        kinds = [h["kind"] for h in fired]
        if "unlock_adventure" in kinds or "grant_quest" in kinds:
            # Quest Accept (§D17-5.4): hooks fired → auto-save → the job.
            self.save_point("quest_accept", None)
            self._request_async("adventure_job")
        elif "rest" in kinds:
            self.save_point("inn", None, auto=False)
        return fired

    # -- the all-players confirmation (T-84) ---------------------------------- #
    def request_confirm(self, client_id: str, kind: str, label: str,
                        action: Callable[[], Any]) -> None:
        """Every connected player answers; 30 s → yes; the initiator may cancel;
        a single "no" cancels. With one player connected it simply runs."""
        if self.confirm is not None:
            raise ValueError("another confirmation is already pending")
        players = [cid for cid in self.clients]
        if len(players) <= 1:
            action()
            return
        self._confirm_seq += 1
        self.confirm = {"id": self._confirm_seq, "kind": kind, "label": label,
                        "initiator": client_id, "yes": {client_id},
                        "deadline": time.time() + CONFIRM_TIMEOUT_S,
                        "_action": action}
        self._request_async("confirm_timer")

    def answer_confirm(self, client_id: str, confirm_id: int, yes: bool) -> None:
        c = self.confirm
        if c is None or c["id"] != confirm_id:
            return
        if not yes:
            self.confirm = None
            return
        c["yes"].add(client_id)
        if all(cid in c["yes"] for cid in self.clients):
            self._resolve_confirm()

    def cancel_confirm(self, client_id: str, confirm_id: int) -> None:
        c = self.confirm
        if c is None or c["id"] != confirm_id:
            return
        if c["initiator"] == client_id:
            self.confirm = None

    def expire_confirm(self, confirm_id: int) -> None:
        c = self.confirm
        if c is not None and c["id"] == confirm_id and time.time() >= c["deadline"] - 0.01:
            self._resolve_confirm()

    def _resolve_confirm(self) -> None:
        c = self.confirm
        self.confirm = None
        if c is not None:
            c["_action"]()

    def confirm_payload(self, client_id: str) -> Optional[Dict[str, Any]]:
        c = self.confirm
        if c is None:
            return None
        return {"id": c["id"], "kind": c["kind"], "label": c["label"],
                "initiator": c["initiator"], "you_are_initiator": c["initiator"] == client_id,
                "answered": client_id in c["yes"],
                "yes_count": len(c["yes"]), "player_count": len(self.clients),
                "seconds_left": max(0, int(c["deadline"] - time.time()))}

    # -- adventures (Update 10) ----------------------------------------------- #
    def public_result(self) -> Optional[str]:
        """The result the CLIENTS should see: a non-final phase victory is a phase
        boundary (the level-up gate), not a game over."""
        if self.state is None:
            return None
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
            seed = random.randrange(2**31)
            # The phase-boundary auto-save (§D17-3.2) is taken BEFORE the next
            # phase composes, with the seed it will compose with — a reload
            # replays `advance` and lands on the identical state.
            self.save_point("phase_boundary", seed)
            state, portraits, art, encounter_id = self.adventure.advance(seed=seed)
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
        if self.state is None:
            return self._town_snapshot(client_id)
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
        if self.run_id is not None:
            snap["run"] = {"run_id": self.run_id, "last_save": self.last_save}
        if self.scenario is not None:
            snap["mode"] = "adventure"
            snap["scenario"] = self.scenario.town_snapshot()["scenario"]
            snap["quest_log"] = self.scenario.quest_log()
            snap["party_sheet"] = self.scenario.party_block()
        snap["confirm"] = self.confirm_payload(client_id)
        return snap

    def _town_snapshot(self, client_id: str) -> Dict[str, Any]:
        """The town-mode state message (Update 17 §D17-5.2): no engine state —
        the town screen, the conversation, the quest log, the party sheet."""
        sc = self.scenario
        assert sc is not None
        town = sc.town_snapshot()
        return {
            "mode": "town" if sc.mode != "complete" else "complete",
            "session_id": self.id,
            "encounter_id": "",
            "priority": {"holder_character_id": None, "kind": None},
            "result": None,
            "game_over": None,
            "party": [],  # the combat party list is empty; see party_sheet
            "party_sheet": town.pop("party"),
            "run": {"run_id": self.run_id, "last_save": self.last_save},
            "confirm": self.confirm_payload(client_id),
            **town,
        }


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create(self, state: Optional[GameState], name: str = "",
               portraits: Optional[Dict[str, str]] = None,
               encounter_id: str = "",
               art: Optional[Dict[str, Any]] = None,
               adventure: Optional[AdventureRun] = None,
               run_id: Optional[str] = None,
               run_manager: Optional["RunManager"] = None,
               scenario: Optional["ScenarioRun"] = None) -> Session:
        session_id = _short_id()
        while session_id in self._sessions:
            session_id = _short_id()
        session = Session(session_id, state, name=name, portraits=portraits,
                          encounter_id=encounter_id, art=art,
                          adventure=adventure, run_id=run_id,
                          run_manager=run_manager, scenario=scenario)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def all(self) -> List[Session]:
        return list(self._sessions.values())
