"""Generation jobs — the adventure job behind Start Adventure (Design Update 17
§D17-6.3).

``adventure_job = {state: idle | pending | ready | failed, progress [n, m],
adventure_ref, error?}`` — persisted with the run
(written into run.json as it changes) and reflected on the greyed Start
Adventure button. `ready` is reached at *adventure generated*: art is
best-effort and continues in the background even after the adventure starts.
Failure after retries → "Generation failed — Retry"; the quest stays accepted;
the town never wedges. A reload/restart resumes the job from its saved state.
(§D17-6.3 also names `generated` and `art_queued`; nothing sets them. Readers
still accept them — `scenario.py`, `types.ts` — so old saves stay valid.)

Save-consistency rule: the generated adventure is written to the run's content
store the moment it validates, so a manual inn save after accepting the quest
reloads the SAME adventure — never a re-roll.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from . import art, content, llm

Generator = Callable[..., Dict[str, Any]]


def call_locked(session: Any, loop: Optional[asyncio.AbstractEventLoop],
                fn: Callable[[], Any]) -> Any:
    """Run ``fn`` under the session lock ON THE EVENT LOOP, from a worker
    thread, and return its result (roadmap M1.8). Workers compute off-thread
    (the LLM call, the file writes); every read of the live session and every
    write to it goes through here, so a worker never races the players' own
    actions. With no loop (tests, sync callers) it simply calls ``fn``, and on
    the loop thread itself it does too: code there runs between awaits, so it
    is already atomic against every other coroutine (and waiting on the loop
    from the loop would deadlock)."""
    if loop is None or running_loop() is loop:
        return fn()

    async def _go() -> Any:
        async with session.lock():
            return fn()

    return asyncio.run_coroutine_threadsafe(_go(), loop).result()


def running_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class AdventureJobRunner:
    """Runs one session's adventure generation off-thread and steps the job
    state machine. `generator` is `llm.generate_adventure` (tests swap it)."""

    def __init__(self, generator: Optional[Generator] = None) -> None:
        self.generator: Generator = generator or llm.generate_adventure
        # Sessions with a job running in this process (a persisted flag would
        # survive a crash and wedge the resume).
        self._inflight: set = set()

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
            except Exception:  # noqa: BLE001
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

    def generate_sync(self, session: Any,
                      loop: Optional[asyncio.AbstractEventLoop] = None,
                      on_art: Optional[Callable[[str, List[str]], None]] = None) -> None:
        """Generate the act's adventure NOW (blocking): the body of the
        background task, also usable inline by tests. ``loop`` is the event
        loop when this runs on a worker thread: the session is read and
        written only through `call_locked` (M1.8).

        §D25-3: the adventure is written a phase at a time. The job turns
        `ready` the moment Phase I lands (Start Adventure lights up) and keeps
        writing II and III; each phase is frozen into the run as it lands and
        handed to a running adventure (`Session.phase_landed`), so a party
        waiting at a boundary rides on. A job that already holds an outline
        and some phases RESUMES from the first missing one. ``on_art(aid,
        encounter_ids)`` (called on the loop) queues a landed phase's art."""
        sc = session.scenario
        key = id(session)
        if key in self._inflight:
            return
        self._inflight.add(key)

        def inputs() -> Dict[str, Any]:
            import copy as _copy
            job = sc.adventure_job
            resume = None
            if job.get("adventure_id") and job.get("outline") and sc.adventure_detail:
                resume = {"adventure_id": job["adventure_id"], "outline": job["outline"]}
            deeds = [[str(e.get("text") or "") for e in sc.chronicle_of(cid)]
                     for cid in sc.character_ids] if hasattr(sc, "chronicle_of") else None
            return dict(difficulty=sc.options.get("difficulty", "standard"),
                        loadouts=_copy.deepcopy(sc.loadouts), levels=sc.levels(),
                        base_level=sc.effective_level(), context=sc.adventure_context(),
                        phase_levels=sc.phase_budget_levels(), deeds=deeds, resume=resume)

        def freeze(aid: str) -> "tuple[Dict[str, Any], Optional[str]]":
            detail = content.adventure_detail(aid)
            if detail is None:
                raise ValueError("the generated adventure did not persist")
            ref = None
            if session.run_id and session.run_manager:
                ref = session.run_manager.put_content(session.run_id, detail)
            return detail, ref

        def landed(aid: str, detail: Dict[str, Any], ref: Optional[str]) -> None:
            """Apply one landed phase (on the loop, under the lock)."""
            n = len(detail["phases"])
            total = int(detail.get("phases_total") or n)
            if sc.adventure_id not in (None, aid) and sc.adventure_detail is not None:
                return  # the act moved on (a defeat re-roll); this job is stale
            sc.attach_adventure(aid, detail, ref)
            self.set_state(sc, "ready", adventure_ref=ref, error=None,
                           progress=[n, total], phases_ready=n, phases_total=total,
                           adventure_id=aid, outline=detail.get("outline"),
                           writing=n < total, phase_error=None)
            self.persist(session)
            if getattr(session, "adventure", None) is not None and \
                    session.adventure.adventure_id == aid:
                session.phase_landed(detail)
            if on_art is not None:
                on_art(aid, [p["encounter_id"] for p in detail["phases"]])

        try:
            kw = call_locked(session, loop, inputs)

            def on_phase(index: int, aid: str) -> None:
                detail, ref = freeze(aid)
                call_locked(session, loop, lambda: landed(aid, detail, ref))

            meta = self.generator(
                [], kw.pop("difficulty"), note="", run_only=True, on_phase=on_phase, **kw)
            detail, ref = freeze(meta["id"])
            call_locked(session, loop, lambda: landed(meta["id"], detail, ref))
        except Exception as exc:  # noqa: BLE001
            def fail() -> None:
                job = sc.adventure_job
                if int(job.get("phases_ready") or 0) > 0 and sc.adventure_detail is not None:
                    # Phase I (at least) is playable: the job stays ready and
                    # the boundary shows the error with a Retry (§D25-3).
                    self.set_state(sc, "ready", writing=False, phase_error=str(exc))
                    if getattr(session, "adventure", None) is not None:
                        session.adventure.phase_error = str(exc)
                else:
                    self.set_state(sc, "failed", error=str(exc), writing=False)
                self.persist(session)
            call_locked(session, loop, fail)
        finally:
            self._inflight.discard(key)

    # -- async driver ------------------------------------------------------- #
    async def run(self, session: Any, broadcast: Callable[[Any], Awaitable[None]],
                  refresh_art: Callable[[str], Awaitable[None]]) -> None:
        """Generate off-thread; each landed phase queues its art (Phase I
        first) and is broadcast."""
        sc = session.scenario
        if sc is None:
            return
        loop = asyncio.get_running_loop()
        async with session.lock():
            if sc.adventure_job.get("state") != "ready":
                self.set_state(sc, "pending", error=None)
            else:
                self.set_state(sc, "ready", writing=True, phase_error=None)
            self.persist(session)
        await broadcast(session)

        def on_art(aid: str, encounter_ids: List[str]) -> None:
            # Runs on the loop (inside call_locked): queue, then broadcast.
            loop.create_task(broadcast(session))
            if llm.playtest_on():   # the playtest profile (M3.3) leaves it unpainted
                return
            try:
                art.QUEUE.start(f"adventure:{aid}", encounter_ids, refresh_art)
            except RuntimeError:
                pass  # no running loop (tests)

        await asyncio.to_thread(self.generate_sync, session, loop, on_art)
        await broadcast(session)

    def start(self, session: Any, broadcast: Callable[[Any], Awaitable[None]],
              refresh_art: Callable[[str], Awaitable[None]]) -> None:
        """Schedule `run` on the event loop; a no-op if a job is in flight."""
        sc = session.scenario
        if sc is None or id(session) in self._inflight:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (tests / sync callers): run inline.
            if sc.adventure_job.get("state") != "ready":
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

    def generate_sync(self, session: Any,
                      loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """The planner call (blocking). On a worker thread (``loop`` given) the
        writer's inputs are read, and its result applied, under the session
        lock on the loop; only the LLM call runs unlocked (M1.8)."""
        sc = session.scenario
        if sc is None:
            return
        try:
            if self.runner is not None:
                result = self.runner(sc)          # tests' stand-in for the writer
            else:
                args = call_locked(session, loop, sc.interlude_inputs)
                result = sc.interlude_generator(*args)
        except Exception as exc:  # noqa: BLE001
            def fail() -> None:
                sc.pending_interlude = None
                sc.interlude_job = {"state": "failed", "error": str(exc)}
            call_locked(session, loop, fail)
            return

        def apply() -> None:
            sc.take_interlude(result)
            if session.run_id and session.run_manager:
                try:
                    session.run_manager.update_campaign(session.run_id, sc)
                except Exception:  # noqa: BLE001
                    pass
            if sc.continue_requested:
                try:
                    session.continue_campaign()
                except ValueError:
                    pass
        call_locked(session, loop, apply)

    async def run(self, session: Any, broadcast: Callable[[Any], Awaitable[None]]) -> None:
        sc = session.scenario
        if sc is None:
            return
        async with session.lock():
            sc.interlude_job = {"state": "pending", "error": None}
        await broadcast(session)
        await asyncio.to_thread(self.generate_sync, session, asyncio.get_running_loop())
        await broadcast(session)

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
