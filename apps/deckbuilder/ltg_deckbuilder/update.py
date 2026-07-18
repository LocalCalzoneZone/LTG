"""App-control routes: self-update over git, and quit — thin wrappers over
ltg_core.selfupdate (the one shared updater; the game server exposes the same
routes). The update UI lives in the game's Options → Settings; the deckbuilder
keeps the routes so either running app can drive an update."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter

from ltg_core import selfupdate

# Where the sibling game server answers for the all-apps quit (LTG-Start runs
# both on their defaults; override for a non-standard port).
GAME_PORT = int(os.environ.get("LTG_GAME_PORT", "8020"))

router = APIRouter(prefix="/api")


@router.get("/update/check")
def check() -> Dict[str, Any]:
    return selfupdate.check_update()


@router.post("/update/apply")
def apply() -> Dict[str, Any]:
    return selfupdate.apply_update()


@router.post("/quit")
def quit_app(scope: str = "all") -> Dict[str, Any]:
    """Shut down (the topbar Quit button). Quitting is for the PAIR: scope
    "all" also asks the game server to quit; "self" (what the sibling sends)
    stops the bounce. Responds first; the process exits moments later."""
    if scope == "all":
        selfupdate.quit_sibling(GAME_PORT)
    selfupdate.schedule_exit()
    return {"ok": True}
