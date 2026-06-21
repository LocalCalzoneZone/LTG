"""FastAPI app: Scryfall search/add, loadout validate/save/load, schema export.

Serves the static frontend at `/` so the whole tool runs from one command:
    uvicorn backend.app:app --reload
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import mappings, scryfall
from .schema import Card, Loadout, deck_status

ROOT = Path(__file__).resolve().parent.parent
LOADOUT_DIR = ROOT / "loadouts"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="Langelier Tactical Game — Deck Builder")


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class AddCardBody(BaseModel):
    source_name: str


class LoadoutBody(BaseModel):
    loadout: dict


# --------------------------------------------------------------------------- #
# Scryfall
# --------------------------------------------------------------------------- #
@app.get("/api/scryfall/search")
def api_search(q: str = "") -> dict:
    try:
        return {"matches": scryfall.search(q)}
    except Exception as exc:  # network / upstream errors → 502
        raise HTTPException(status_code=502, detail=f"Scryfall error: {exc}")


@app.post("/api/cards/add")
def api_add_card(body: AddCardBody) -> Card:
    try:
        data = scryfall.fetch_named(body.source_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scryfall error: {exc}")
    return mappings.build_card(data)


# --------------------------------------------------------------------------- #
# Loadout validation + status
# --------------------------------------------------------------------------- #
@app.post("/api/loadout/validate")
def api_validate(body: LoadoutBody) -> dict:
    try:
        loadout = Loadout.model_validate(body.loadout)
    except ValidationError as exc:
        return {"valid": False, "errors": _format_errors(exc), "status": None}
    return {"valid": True, "errors": [], "status": deck_status(loadout)}


def _format_errors(exc: ValidationError) -> List[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}")
    return out


# --------------------------------------------------------------------------- #
# Loadout persistence (./loadouts/<name>.json)
# --------------------------------------------------------------------------- #
@app.get("/api/loadouts")
def api_list_loadouts() -> dict:
    LOADOUT_DIR.mkdir(exist_ok=True)
    names = sorted(p.stem for p in LOADOUT_DIR.glob("*.json"))
    return {"loadouts": names}


@app.get("/api/loadout/{name}")
def api_load(name: str) -> dict:
    path = _safe_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No loadout named {name!r}")
    data = json.loads(path.read_text())
    # Validate on the way out so callers always get a known-good shape.
    return Loadout.model_validate(data).model_dump()


@app.post("/api/loadout/save")
def api_save(body: LoadoutBody) -> dict:
    try:
        loadout = Loadout.model_validate(body.loadout)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_format_errors(exc))
    LOADOUT_DIR.mkdir(exist_ok=True)
    name = _slug(loadout.character.name) or "untitled"
    path = _safe_path(name)
    path.write_text(json.dumps(loadout.model_dump(), indent=2))
    return {"saved": name}


@app.get("/api/schema")
def api_schema() -> dict:
    return Loadout.model_json_schema()


def _slug(name: str) -> str:
    import re

    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def _safe_path(name: str) -> Path:
    slug = _slug(name)
    if not slug:
        raise HTTPException(status_code=400, detail="invalid loadout name")
    return LOADOUT_DIR / f"{slug}.json"


# --------------------------------------------------------------------------- #
# Static frontend (mounted last so /api/* wins)
# --------------------------------------------------------------------------- #
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
