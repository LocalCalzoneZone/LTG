"""The job queue (§D13-4.1) — probes are minutes-long; the UI must not block.

One worker thread executes jobs sequentially (each probe already saturates the
CPU by fanning its games across a process pool); the queue survives restarts:
every job persists a manifest under ``data/runs/`` on each transition, and a
finished job's verdict lands in ``data/verdicts/``. On startup, jobs that were
``running`` when the process died are re-marked ``interrupted`` — determinism
makes re-running them free of surprises.

Cancellation is soft: the cancel flag is checked from the probe's progress
callback, which raises out of the run loop at the next completed game batch.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import enemy_analysis, gauntlets, probes

RUNS_DIR = gauntlets.DATA_DIR / "runs"
VERDICTS_DIR = gauntlets.DATA_DIR / "verdicts"

# Fan each probe's games across this many processes.
WORKERS = max(1, (os.cpu_count() or 4) - 2)


class JobCancelled(Exception):
    pass


class JobRunner:
    """The one-worker queue. All public methods are thread-safe."""

    def __init__(self) -> None:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._cancel: set = set()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._load_existing()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    # -- persistence ---------------------------------------------------------- #
    def _load_existing(self) -> None:
        for path in sorted(RUNS_DIR.glob("*.json")):
            try:
                job = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if job.get("status") in ("queued", "running"):
                job["status"] = "interrupted"
                job["error"] = "the Tester was restarted mid-run — re-run freely"
                self._save(job)
            self._jobs[job["id"]] = job

    def _save(self, job: Dict[str, Any]) -> None:
        (RUNS_DIR / f"{job['id']}.json").write_text(
            json.dumps(job, indent=2, default=str))

    # -- public --------------------------------------------------------------- #
    def submit(self, kind: str, params: Dict[str, Any],
               title: str) -> Dict[str, Any]:
        job = {
            "id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "kind": kind,
            "title": title,
            "params": params,
            "status": "queued",
            "progress": {"done": 0, "total": 0, "label": ""},
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished": None,
            "verdict_id": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job["id"]] = job
            self._save(job)
        self._queue.put(job["id"])
        return dict(job)

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()),
                          key=lambda j: j["id"], reverse=True)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] not in ("queued", "running"):
                return False
            self._cancel.add(job_id)
            if job["status"] == "queued":
                job["status"] = "cancelled"
                self._save(job)
        return True

    # -- the worker ------------------------------------------------------------ #
    def _run_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job["status"] != "queued":
                    continue
                job["status"] = "running"
                self._save(job)
            try:
                verdict = self._execute(job)
                with self._lock:
                    if verdict is not None:
                        vid = job["id"]
                        (VERDICTS_DIR / f"{vid}.json").write_text(
                            json.dumps(verdict, indent=2, default=str))
                        job["verdict_id"] = vid
                    job["status"] = "done"
                    job["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    self._save(job)
            except JobCancelled:
                with self._lock:
                    job["status"] = "cancelled"
                    job["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    self._save(job)
            except Exception as exc:  # surfaced to the queue view, never fatal
                with self._lock:
                    job["status"] = "failed"
                    job["error"] = f"{type(exc).__name__}: {exc}"
                    job["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    self._save(job)
            finally:
                self._cancel.discard(job_id)

    def _progress(self, job: Dict[str, Any]):
        last_save = [0.0]

        def cb(done: int, total: int, label: str) -> None:
            if job["id"] in self._cancel:
                raise JobCancelled()
            with self._lock:
                job["progress"] = {"done": done, "total": total, "label": label}
                now = time.time()
                if now - last_save[0] > 2.0:  # throttle disk writes
                    last_save[0] = now
                    self._save(job)
        return cb

    def _execute(self, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from ltg_game_server import content as game_content

        kind = job["kind"]
        p = job["params"]
        progress = self._progress(job)

        if kind == "generate_gauntlet":
            progress(0, 1, "calling the model")
            gauntlets.generate_gauntlet(
                p["name"], p.get("character_ids") or [],
                count=int(p.get("count", 4)),
                difficulty=p.get("difficulty", "standard"),
                note=p.get("note", ""))
            progress(1, 1, "done")
            return None

        gauntlet = gauntlets.load_gauntlet(p["gauntlet_id"])
        if kind == "enemy_schema":
            loadouts = [game_content.loadout_for(cid)
                        for cid in p["character_ids"]]
            if any(lo is None for lo in loadouts):
                raise ValueError("unknown character in party")
            verdict = enemy_analysis.probe_enemy_schema(
                loadouts, gauntlet, p.get("preset", "quick"),
                jobs=WORKERS, progress=progress)
        else:
            roster_id = p["character_id"]
            loadout = game_content.loadout_for(roster_id)
            if loadout is None:
                raise ValueError(f"unknown character: {roster_id}")
            if kind == "card":
                verdict = probes.probe_card(
                    loadout, p["card_id"], gauntlet, p.get("preset", "quick"),
                    jobs=WORKERS, progress=progress)
            elif kind in ("skill", "ultimate"):
                verdict = probes.probe_heroic(
                    loadout, kind, gauntlet, p.get("preset", "quick"),
                    jobs=WORKERS, progress=progress)
            elif kind == "character":
                roster = [game_content.loadout_for(m["id"])
                          for m in game_content.list_characters()]
                roster = [lo for lo in roster if lo is not None]
                verdict = probes.probe_character(
                    loadout, roster, gauntlet, p.get("preset", "quick"),
                    jobs=WORKERS, progress=progress)
            else:
                raise ValueError(f"unknown probe kind: {kind}")
            verdict["subject"]["roster_id"] = roster_id
        verdict["job_id"] = job["id"]
        verdict["title"] = job["title"]
        return verdict


def list_verdicts() -> List[Dict[str, Any]]:
    """Newest-first verdict summaries (the full report loads by id)."""
    out = []
    if not VERDICTS_DIR.is_dir():
        return out
    for path in sorted(VERDICTS_DIR.glob("*.json"), reverse=True):
        try:
            v = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "id": path.stem,
            "title": v.get("title", path.stem),
            "kind": v.get("kind"),
            "subject": v.get("subject", {}),
            "flag": v.get("flag"),
            "combo_blind": v.get("combo_blind", False),
            "screening_only": v.get("screening_only", False),
            "preset": v.get("preset"),
            "created": v.get("created"),
            "gauntlet": v.get("gauntlet", {}),
            "policy_version": v.get("policy_version"),
            "recommendation": v.get("recommendation", ""),
        })
    return out


def load_verdict(verdict_id: str) -> Optional[Dict[str, Any]]:
    path = VERDICTS_DIR / f"{verdict_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
