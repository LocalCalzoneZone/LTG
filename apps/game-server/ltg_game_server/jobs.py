"""Generation jobs — the adventure job behind Start Adventure (Design Update 17
§D17-6.3).

``adventure_job = {state: idle | pending | generated | art_queued | ready |
failed, progress [n, m], adventure_ref, error?}`` — persisted with the run
(written into run.json as it changes) and reflected on the greyed Start
Adventure button. `ready` is reached at *adventure generated*: art is
best-effort and continues in the background even after the adventure starts.
Failure after retries → "Generation failed — Retry"; the quest stays accepted;
the town never wedges. A reload/restart resumes the job from its saved state.

Save-consistency rule: the generated adventure is written to the run's content
store the moment it validates, so a manual inn save after accepting the quest
reloads the SAME adventure — never a re-roll.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from . import art, content, llm

Generator = Callable[..., Dict[str, Any]]


class AdventureJobRunner:
    """Runs one session's adventure generation off-thread and steps the job
    state machine. `generator` is `llm.generate_adventure` (tests swap it)."""

    def __init__(self, generator: Optional[Generator] = None) -> None:
        self.generator: Generator = generator or llm.generate_adventure

    # -- the state machine (sync; the caller holds the session lock) -------- #
    @staticmethod
    def set_state(sc: Any, state: str, **fields: Any) -> None:
        job = dict(sc.adventure_job)
        job["state"] = state
        job.update(fields)
        sc.adventure_job = job

    def persist(self, session: Any) -> None:
        """Write the job state into run.json (cheap; not a save row)."""
        if session.run_id and session.run_manager and session.scenario:
            try:
                session.run_manager.set_job(session.run_id, session.scenario.adventure_job)
            except Exception:
                pass

    def prepare_pregenerated(self, session: Any, adventure_id: str) -> None:
        """A pre-generated Act I: the adventure already exists — freeze it into
        the run's content store and mark the job ready at once."""
        sc = session.scenario
        detail = content.adventure_detail(adventure_id)
        if detail is None:
            self.set_state(sc, "failed", error=f"the scenario's Act I adventure ({adventure_id}) is missing")
            self.persist(session)
            return
        ref = None
        if session.run_id and session.run_manager:
            ref = session.run_manager.put_content(session.run_id, detail)
        sc.attach_adventure(adventure_id, detail, ref)
        self.set_state(sc, "ready", adventure_ref=ref, error=None,
                       progress=[len(detail["phases"]), len(detail["phases"])])
        self.persist(session)

    def generate_sync(self, session: Any) -> None:
        """Generate the act's adventure NOW (blocking): the body of the
        background task, also usable inline by tests."""
        sc = session.scenario
        try:
            meta = self.generator(
                [], sc.options.get("difficulty", "standard"), note="",
                loadouts=sc.loadouts, levels=sc.levels(),
                base_level=sc.effective_level(), context=sc.adventure_context(),
                phase_levels=sc.phase_budget_levels(), run_only=True)
            detail = content.adventure_detail(meta["id"])
            if detail is None:
                raise ValueError("the generated adventure did not persist")
            ref = None
            if session.run_id and session.run_manager:
                ref = session.run_manager.put_content(session.run_id, detail)
            sc.attach_adventure(meta["id"], detail, ref)
            self.set_state(sc, "ready", adventure_ref=ref, error=None,
                           progress=[0, len(detail["phases"])])
        except Exception as exc:
            self.set_state(sc, "failed", error=str(exc))
        self.persist(session)

    # -- async driver ------------------------------------------------------- #
    async def run(self, session: Any, broadcast: Callable[[Any], Awaitable[None]],
                  refresh_art: Callable[[str], Awaitable[None]]) -> None:
        """Generate off-thread, then queue the adventure's art (Phase I first)."""
        sc = session.scenario
        if sc is None:
            return
        async with session.lock():
            self.set_state(sc, "pending", error=None)
            self.persist(session)
        await broadcast(session)
        await asyncio.to_thread(self.generate_sync, session)
        await broadcast(session)
        if sc.adventure_job.get("state") == "ready" and sc.adventure_id:
            detail = sc.adventure_detail or {}
            phase_ids = [p["encounter_id"] for p in detail.get("phases", [])]
            try:
                art.QUEUE.start(f"adventure:{sc.adventure_id}", phase_ids, refresh_art)
            except RuntimeError:
                pass  # no running loop (tests)

    def start(self, session: Any, broadcast: Callable[[Any], Awaitable[None]],
              refresh_art: Callable[[str], Awaitable[None]]) -> None:
        """Schedule `run` on the event loop; a no-op if a job is in flight."""
        sc = session.scenario
        if sc is None or sc.adventure_job.get("state") == "pending":
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (tests / sync callers): run inline.
            self.set_state(sc, "pending", error=None)
            self.generate_sync(session)
            return
        loop.create_task(self.run(session, broadcast, refresh_art))


RUNNER = AdventureJobRunner()


class InterludeJobRunner:
    """Update 24 §D24-5.1: the ONE planner call, queued the moment the closing
    act's boss falls — before the spoils are even shown — so by the time gear
    is assigned it is usually done. The result lands on
    `ScenarioRun.pending_interlude`, in the run's content store, and
    `interlude_ready` is broadcast so the scenario-end menu can show a spinner
    when the player is faster than the writer. A Continue pressed early is
    honoured the moment the planner returns."""

    def __init__(self) -> None:
        self.runner: Optional[Callable[[Any], Dict[str, Any]]] = None   # tests swap it

    def generate_sync(self, session: Any) -> None:
        sc = session.scenario
        if sc is None:
            return
        try:
            if self.runner is not None:
                sc.pending_interlude = self.runner(sc)
                sc.interlude_job = {"state": "ready", "error": None}
            else:
                sc.generate_interlude()
            if session.run_id and session.run_manager:
                try:
                    session.run_manager.update_campaign(session.run_id, sc)
                except Exception:
                    pass
        except Exception as exc:
            sc.pending_interlude = None
            sc.interlude_job = {"state": "failed", "error": str(exc)}
        if sc.interlude_job.get("state") == "ready" and sc.continue_requested:
            try:
                session.continue_campaign()
            except ValueError:
                pass

    async def run(self, session: Any, broadcast: Callable[[Any], Awaitable[None]]) -> None:
        sc = session.scenario
        if sc is None:
            return
        async with session.lock():
            sc.interlude_job = {"state": "pending", "error": None}
        await broadcast(session)
        await asyncio.to_thread(self._generate_locked, session)
        await broadcast(session)

    def _generate_locked(self, session: Any) -> None:
        # The generation itself runs off-thread; only the hand-over back into
        # the session (a Continue pressed meanwhile) needs the lock, which the
        # sync path takes for the whole call — cheap, since the call is the
        # slow part and nothing else moves the session at the scenario's end.
        self.generate_sync(session)

    def start(self, session: Any, broadcast: Optional[Callable[[Any], Awaitable[None]]]) -> None:
        sc = session.scenario
        if sc is None or sc.interlude_job.get("state") == "pending":
            return
        if sc.pending_interlude is not None:
            sc.interlude_job = {"state": "ready", "error": None}
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            sc.interlude_job = {"state": "pending", "error": None}
            self.generate_sync(session)
            return
        loop.create_task(self.run(session, broadcast or _noop_broadcast))


async def _noop_broadcast(_session: Any) -> None:
    return None


INTERLUDE = InterludeJobRunner()
