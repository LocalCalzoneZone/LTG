"""Roadmap M1.8: generation workers run off the event loop, and every read or
write of the live session goes through `jobs.call_locked`, which runs it under
the session lock ON the loop. So a worker never mutates a session while a
player's action holds the lock."""

from __future__ import annotations

import asyncio
import threading

from ltg_game_server import jobs


class _Session:
    def __init__(self):
        self._lock = None

    def lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock


def test_a_worker_write_waits_for_the_lock_and_runs_on_the_loop():
    session = _Session()
    seen = {}

    async def main():
        loop = asyncio.get_running_loop()
        order = []

        def worker():
            def write():
                seen["thread"] = threading.current_thread() is threading.main_thread()
                order.append("worker write")
                return 42
            seen["result"] = jobs.call_locked(session, loop, write)

        async with session.lock():            # a player's action holds the lock…
            task = asyncio.ensure_future(asyncio.to_thread(worker))
            await asyncio.sleep(0.05)
            order.append("player done")       # …the worker's write must wait
        await task
        return order

    order = asyncio.run(main())
    assert order == ["player done", "worker write"]
    assert seen == {"thread": True, "result": 42}   # ran on the loop's thread


def test_call_locked_runs_inline_without_a_loop_or_on_the_loop_itself():
    session = _Session()
    assert jobs.call_locked(session, None, lambda: "sync") == "sync"

    async def main():
        return jobs.call_locked(session, asyncio.get_running_loop(), lambda: "inline")
    assert asyncio.run(main()) == "inline"
