"""Install tooling for standalone checkouts — self-update over git, and quit.

Not game vocabulary: this lives in ltg_core only so the deckbuilder and the
game server share exactly one updater (both expose it as /api/update/* and
/api/quit). The whole game ships as one git checkout, so an update is
`git fetch` + fast-forward + reinstall requirements — and it covers every app
in the repo at once.

Characters, settings and saves are gitignored (apps/deckbuilder/loadouts, and
saves/), so an update can never touch them. Encounters, adventures, towns,
scenarios and their art are NOT: the game writes those into the tracked
content/ dir on purpose, so authoring them here ships them to every install —
but it also means a player install that edits or generates one has a dirty
tree, and --ff-only then refuses. That refusal is why _ff_failure names the
exact blockers rather than guessing. The running server keeps executing old
code — callers tell the user to relaunch after a successful update.
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
        return _ff_failure(target, ff.stderr)
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


def _ff_failure(target: str, stderr: str) -> Dict[str, Any]:
    """Explain a refused fast-forward in terms the player can read back to us.

    `git merge --ff-only` refuses for several unrelated reasons and its own
    stderr is terse, so we ask git what actually stands in the way: commits this
    install made on its own, and/or files it has changed. Naming them beats the
    old blanket "you have local changes" — which was a guess, and was wrong
    whenever the real cause was a local commit or a diverged branch."""
    ahead = _git("rev-list", "--count", f"{target}..HEAD")
    n_ahead = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else 0

    st = _git("status", "--porcelain")
    # Porcelain v1: "XY <path>". Keep the status code — " M" (edited), "??"
    # (untracked) and "UU" (conflicted) need different advice from us.
    entries = [ln.rstrip() for ln in st.stdout.splitlines() if ln.strip()] \
        if st.returncode == 0 else []
    dirty = [e for e in entries if not e.startswith("??")]
    untracked = [e for e in entries if e.startswith("??")]

    reasons: List[str] = []
    if n_ahead:
        reasons.append(f"{n_ahead} local commit{'' if n_ahead == 1 else 's'} "
                       f"this install made on its own")
    if dirty:
        reasons.append(f"{len(dirty)} changed file{'' if len(dirty) == 1 else 's'}")
    if not reasons:
        # Nothing obvious — most often an untracked file sitting where an
        # incoming one wants to land. Let git's own words through.
        reasons.append("something git won't overwrite")

    blocks: List[str] = []
    if dirty:
        blocks.append("\n".join(["Changed files:"] + [f"  {e}" for e in dirty[:40]]))
    if untracked:
        blocks.append("\n".join(["New files not in git:"]
                                 + [f"  {e}" for e in untracked[:20]]))
    if stderr.strip():
        blocks.append(stderr.strip())

    return _error(
        "Couldn't apply the update cleanly — " + " and ".join(reasons) +
        " stand in the way. Send your game admin the details below.",
        "\n\n".join(blocks))


def schedule_exit(delay: float = 0.4) -> None:
    """Hard-exit the server process shortly after the current request returns —
    the Quit button. os._exit skips atexit/uvicorn teardown deliberately: these
    apps write synchronously per-request, and the launcher window closes on a
    clean 0."""
    threading.Timer(delay, os._exit, args=(0,)).start()


def quit_sibling(port: int, timeout: float = 2.0) -> bool:
    """Ask the sibling app on localhost:`port` to quit (scope=self, so it never
    bounces back). Quitting is all-or-nothing for the pair — the Quit button
    says it closes the Game AND the Deckbuilder. Returns whether the sibling
    acknowledged; a sibling that isn't running is simply not there to quit."""
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/quit?scope=self", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except OSError:
        return False
