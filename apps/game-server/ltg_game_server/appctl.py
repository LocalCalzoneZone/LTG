"""App-control routes: self-update over git, and quit — thin wrappers over
ltg_core.selfupdate (the one shared updater; the deckbuilder exposes the same
routes). Surfaced in the client under Options → Settings. One update covers
the whole checkout — game, deckbuilder, and shared content alike."""

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
    """Shut the server down (Options → Settings → Quit). Responds first; the
    process exits moments later. This ends the session for every connected
    player — it is the host's control."""
    selfupdate.schedule_exit()
    return {"ok": True}
