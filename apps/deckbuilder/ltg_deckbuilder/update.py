"""App-control routes: self-update over git, and quit — thin wrappers over
ltg_core.selfupdate (the one shared updater; the game server exposes the same
routes). The update UI lives in the game's Options → Settings; the deckbuilder
keeps the routes so either running app can drive an update."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from ltg_core import selfupdate

router = APIRouter(prefix="/api")


@router.get("/update/check")
def check() -> Dict[str, Any]:
    return selfupdate.check_update()


@router.post("/update/apply")
def apply() -> Dict[str, Any]:
    return selfupdate.apply_update()


@router.post("/quit")
def quit_app() -> Dict[str, Any]:
    """Shut the server down (the topbar Quit button). Responds first; the
    process exits moments later."""
    selfupdate.schedule_exit()
    return {"ok": True}
