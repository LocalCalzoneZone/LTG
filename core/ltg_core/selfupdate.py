"""Install tooling for standalone checkouts — self-update over git, and quit.

Not game vocabulary: this lives in ltg_core only so the deckbuilder and the
game server share exactly one updater (both expose it as /api/update/* and
/api/quit). The whole game ships as one git checkout, so an update is
`git fetch` + fast-forward + reinstall requirements — and it covers every app
in the repo at once.

User data (apps/deckbuilder/loadouts — characters, settings, generated art)
is gitignored, so an update can never touch saves; --ff-only means a checkout
with local commits or edits refuses cleanly instead of merging. The running
server keeps executing old code — callers tell the user to relaunch after a
successful update.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str, timeout: float = 45) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(("git",) + args, cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=timeout)


def _target() -> str:
    """The ref we update towards: the branch's upstream if it has one (the dev
    checkout follows its own branch), else origin/main (a standalone install)."""
    r = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "origin/main"


def _error(msg: str, detail: str = "") -> Dict[str, Any]:
    return {"supported": True, "error": msg, "detail": detail.strip()[:2000]}


def _fetch() -> Optional[Dict[str, Any]]:
    """Fetch from origin; an error dict on failure, None on success."""
    if not (REPO_ROOT / ".git").exists():
        return {"supported": False,
                "error": "This install isn't a git checkout, so it can't self-update."}
    try:
        f = _git("fetch", "--quiet", "origin", timeout=60)
    except subprocess.TimeoutExpired:
        return _error("Couldn't reach GitHub (timed out). Are you online?")
    if f.returncode != 0:
        return _error("Couldn't reach GitHub to check for updates.", f.stderr)
    return None


def check_update() -> Dict[str, Any]:
    """{supported, behind, target, log} — or {supported, error, detail}."""
    err = _fetch()
    if err:
        return err
    target = _target()
    behind = _git("rev-list", "--count", f"HEAD..{target}")
    if behind.returncode != 0:
        return _error(f"Couldn't compare against {target}.", behind.stderr)
    n = int(behind.stdout.strip() or 0)
    log: List[str] = []
    if n:
        log = _git("log", "--pretty=%s", "-15", f"HEAD..{target}").stdout.splitlines()
    return {"supported": True, "behind": n, "target": target, "log": log}


def apply_update() -> Dict[str, Any]:
    """Fast-forward to the target and reinstall requirements.
    {supported, updated: True} — or {supported, error, detail}."""
    err = _fetch()
    if err:
        return err
    target = _target()
    try:
        ff = _git("merge", "--ff-only", target, timeout=120)
    except subprocess.TimeoutExpired:
        return _error("The update timed out mid-merge — try again.")
    if ff.returncode != 0:
        return _error(
            "Couldn't apply the update cleanly — this checkout has local "
            "changes git won't overwrite. Ask your game admin for help.", ff.stderr)
    # Re-resolve dependencies with the venv's own interpreter (new/updated
    # requirements ride in with the pull).
    try:
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r",
             str(REPO_ROOT / "requirements.txt")],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return _error("Dependency install timed out. Close the app, delete the "
                      ".venv folder, and relaunch to repair.")
    if pip.returncode != 0:
        return _error("Code updated, but dependency install failed. Close the "
                      "app, delete the .venv folder, and relaunch to repair.",
                      pip.stderr)
    return {"supported": True, "updated": True}


def schedule_exit(delay: float = 0.4) -> None:
    """Hard-exit the server process shortly after the current request returns —
    the Quit button. os._exit skips atexit/uvicorn teardown deliberately: these
    apps write synchronously per-request, and the launcher window closes on a
    clean 0."""
    threading.Timer(delay, os._exit, args=(0,)).start()
