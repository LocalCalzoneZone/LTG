"""The Autoplay Tester's FastAPI app (§D13-4.1) — API + static frontend.

Serves the Brasswork & Ink lab UI at ``/`` and the JSON API under ``/api``.
The Tester reads the game's content registry through ``ltg_game_server``
(one-way library edge) and never writes game content — the single exception
is the explicit gauntlet-promotion endpoint, which goes through the normal
authored-content gate.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ltg_game_server import content as game_content

from . import gauntlets, jobs, probes

APP_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app = FastAPI(title="LTG — Autoplay Tester")
runner = jobs.JobRunner()


@app.middleware("http")
async def _no_store(request, call_next):
    """API responses must never be heuristically cached — the lab polls live
    job/verdict state, and a stale /api/roster shows yesterday's chips."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class ProbeBody(BaseModel):
    kind: str                       # card | skill | ultimate | character | enemy_schema
    gauntlet_id: str
    preset: str = "quick"
    character_id: Optional[str] = None
    card_id: Optional[str] = None
    character_ids: Optional[List[str]] = None   # enemy_schema party


class GenerateBody(BaseModel):
    name: str
    character_ids: List[str]
    count: int = 4
    difficulty: str = "standard"
    note: str = ""


class PromoteBody(BaseModel):
    encounter_file: str


# --------------------------------------------------------------------------- #
# Roster
# --------------------------------------------------------------------------- #
@app.get("/api/roster")
def api_roster() -> dict:
    """Every loadout the registry sees, with its latest verdict chip and the
    probe-able pieces (cards, heroics)."""
    latest: Dict[str, Dict[str, Any]] = {}
    for v in jobs.list_verdicts():            # newest-first
        rid = v.get("subject", {}).get("roster_id") \
            or v.get("subject", {}).get("character_id")
        if rid and rid not in latest:
            latest[rid] = v
    characters = []
    for meta in game_content.list_characters():
        lo = game_content.loadout_for(meta["id"]) or {}
        char = lo.get("character", {})
        characters.append({
            **{k: meta[k] for k in ("id", "name", "archetype", "colors",
                                    "description", "portrait", "card_count")},
            "level": char.get("level", 1),
            "cards": [{"id": c.get("id"), "name": c.get("name"),
                       "timing": c.get("timing"), "rarity": c.get("rarity")}
                      for c in lo.get("cards", [])],
            "has_skill": bool(char.get("skill")),
            "has_ultimate": bool(char.get("ultimate")),
            "skill_name": (char.get("skill") or {}).get("name", ""),
            "ultimate_name": (char.get("ultimate") or {}).get("name", ""),
            "last_verdict": latest.get(meta["id"]),
        })
    return {"characters": characters}


@app.get("/api/deckbuilder-url/{character_id}")
def api_deckbuilder_url(character_id: str) -> dict:
    """The Deckbuilder's edit deep link for this character (its save posts
    through /api/loadout/update-game — the existing flow)."""
    if game_content.loadout_for(character_id) is None:
        raise HTTPException(404, f"unknown character: {character_id}")
    port = os.environ.get("LTG_DECKBUILDER_PORT", "8000")
    return {"url": f"http://localhost:{port}/?edit={character_id}"}


# --------------------------------------------------------------------------- #
# Gauntlets
# --------------------------------------------------------------------------- #
@app.get("/api/gauntlets")
def api_gauntlets() -> dict:
    return {"gauntlets": gauntlets.list_gauntlets(),
            "baseline": gauntlets.baseline_gauntlet_id()}


@app.get("/api/gauntlets/{gauntlet_id}")
def api_gauntlet(gauntlet_id: str) -> dict:
    try:
        g = gauntlets.load_gauntlet(gauntlet_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {
        "id": g["id"], "name": g["name"], "hash": g["hash"],
        "frozen": g["frozen"], "generated": g["generated"],
        "has_adventure": bool(g["adventure"]),
        "has_partner": bool(g["sparring_partner"]),
        "encounters": [{"file": e.get("_file"), "name": e.get("name"),
                        "enemies": [x.get("name") for x in e.get("enemies", [])],
                        "objective": (e.get("objective") or {}).get("kind")}
                       for e in g["encounters"]],
    }


@app.post("/api/gauntlets/generate")
def api_generate_gauntlet(body: GenerateBody) -> dict:
    return runner.submit("generate_gauntlet", body.model_dump(),
                         f"Mint gauntlet '{body.name}' ({body.count} encounters)")


@app.post("/api/gauntlets/{gauntlet_id}/promote")
def api_promote(gauntlet_id: str, body: PromoteBody) -> dict:
    try:
        return gauntlets.promote_encounter(gauntlet_id, body.encounter_file)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# --------------------------------------------------------------------------- #
# Probes (jobs)
# --------------------------------------------------------------------------- #
def _estimate(body: ProbeBody) -> Dict[str, Any]:
    """Rough games/minutes before launch (~230 games/s across the pool)."""
    try:
        g = gauntlets.load_gauntlet(body.gauntlet_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    preset = probes.PRESETS.get(body.preset)
    if preset is None:
        raise HTTPException(400, f"unknown preset: {body.preset}")
    cells = (len(g["encounters"]) * len(preset["sizes"])
             * len(preset["difficulties"]) * len(preset.get("pressures", (1,)))
             * preset["seeds"])
    variants = {"card": 2 + (20 if preset["loo_sweep"] else 0) + 4,
                "skill": 2, "ultimate": 2,
                "character": max(2, len(game_content.list_characters())) + 1,
                "enemy_schema": 1}.get(body.kind, 2)
    games = cells * variants
    if body.kind == "character" and g["adventure"]:
        games += max(10, preset["seeds"] // 4) * 4
    return {"games": games, "est_minutes": round(games / 230 / 60, 1),
            "cells": cells, "variants": variants}


@app.post("/api/probes/estimate")
def api_estimate(body: ProbeBody) -> dict:
    return _estimate(body)


@app.post("/api/probes")
def api_submit_probe(body: ProbeBody) -> dict:
    if body.kind in ("card", "skill", "ultimate", "character"):
        if not body.character_id:
            raise HTTPException(400, "character_id is required")
        lo = game_content.loadout_for(body.character_id)
        if lo is None:
            raise HTTPException(404, f"unknown character: {body.character_id}")
        if body.kind == "card":
            if not body.card_id:
                raise HTTPException(400, "card_id is required for a card probe")
            if not any(c.get("id") == body.card_id for c in lo.get("cards", [])):
                raise HTTPException(404, f"{body.character_id} has no card "
                                         f"'{body.card_id}'")
        if body.kind in ("skill", "ultimate") \
                and not (lo.get("character") or {}).get(body.kind):
            raise HTTPException(400, f"{body.character_id} has no {body.kind}")
    elif body.kind == "enemy_schema":
        if not body.character_ids:
            raise HTTPException(400, "character_ids (the party) is required")
    else:
        raise HTTPException(400, f"unknown probe kind: {body.kind}")
    if body.preset not in probes.PRESETS:
        raise HTTPException(400, f"unknown preset: {body.preset}")

    names = {"card": f"Card probe — {body.card_id} ({body.character_id})",
             "skill": f"Skill probe — {body.character_id}",
             "ultimate": f"Ultimate probe — {body.character_id}",
             "character": f"Character probe — {body.character_id}",
             "enemy_schema": f"Enemy-schema probe — {body.gauntlet_id}"}
    job = runner.submit(body.kind, body.model_dump(), names[body.kind])
    job["estimate"] = _estimate(body)
    return job


@app.get("/api/probes")
def api_jobs() -> dict:
    return {"jobs": runner.list_jobs()}


@app.get("/api/probes/{job_id}")
def api_job(job_id: str) -> dict:
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job: {job_id}")
    return job


@app.post("/api/probes/{job_id}/cancel")
def api_cancel(job_id: str) -> dict:
    if not runner.cancel(job_id):
        raise HTTPException(400, "job is not cancellable (already finished?)")
    return {"cancelled": job_id}


# --------------------------------------------------------------------------- #
# Verdicts
# --------------------------------------------------------------------------- #
@app.get("/api/verdicts")
def api_verdicts() -> dict:
    current = {g["id"]: g["hash"] for g in gauntlets.list_gauntlets()}
    out = []
    for v in jobs.list_verdicts():
        gid = v.get("gauntlet", {}).get("id")
        v["stale"] = bool(gid) and current.get(gid) != v.get("gauntlet", {}).get("hash")
        out.append(v)
    return {"verdicts": out}


@app.get("/api/verdicts/{verdict_id}")
def api_verdict(verdict_id: str) -> dict:
    v = jobs.load_verdict(verdict_id)
    if v is None:
        raise HTTPException(404, f"unknown verdict: {verdict_id}")
    current = {g["id"]: g["hash"] for g in gauntlets.list_gauntlets()}
    gid = v.get("gauntlet", {}).get("id")
    v["stale"] = bool(gid) and current.get(gid) != v.get("gauntlet", {}).get("hash")
    return v


# The static frontend (mounted last so /api wins).
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")
