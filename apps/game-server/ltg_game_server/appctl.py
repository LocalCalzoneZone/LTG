"""App-control routes: self-update over git, and quit — thin wrappers over
ltg_core.selfupdate (the one shared updater; the deckbuilder exposes the same
routes). Surfaced in the client under Options → Settings. One update covers
the whole checkout — game, deckbuilder, and shared content alike."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter

from ltg_core import selfupdate

# Where the sibling deckbuilder answers for the all-apps quit (LTG-Start runs
# both on their defaults; override for a non-standard port).
DECKBUILDER_PORT = int(os.environ.get("LTG_DECKBUILDER_PORT", "8000"))

router = APIRouter(prefix="/api")


@router.get("/update/check")
def check() -> Dict[str, Any]:
    return selfupdate.check_update()


@router.post("/update/apply")
def apply() -> Dict[str, Any]:
    return selfupdate.apply_update()


@router.post("/quit")
def quit_app(scope: str = "all") -> Dict[str, Any]:
    """Shut down (the top-ribbon Quit button). Quitting is for the PAIR: scope
    "all" also asks the deckbuilder to quit; "self" (what the sibling sends)
    stops the bounce. Responds first; the process exits moments later. This
    ends the session for every connected player — it is the host's control."""
    if scope == "all":
        selfupdate.quit_sibling(DECKBUILDER_PORT)
    selfupdate.schedule_exit()
    return {"ok": True}
