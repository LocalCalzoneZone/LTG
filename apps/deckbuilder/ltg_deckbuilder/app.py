"""FastAPI app: Scryfall search/add, loadout validate/save/load, schema export.

Serves the static frontend at `/` so the whole tool runs from one command:
    uvicorn ltg_deckbuilder.app:app --reload

The vocabulary (schema, translation, lints) is imported from `ltg_core`; this
module owns only app concerns — web routes, persistence, Scryfall ingestion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from ltg_core.schema import (
    BANNED_CREATION_KEYWORDS,
    BASE_POWER,
    BASELINE_CARDS,
    BASELINE_HP,
    BASELINE_MANA,
    Card,
    Character,
    COST_CARD,
    COST_HP_STEP,
    COST_MANA,
    COST_POWER,
    CREATION_BUDGET,
    CREATION_KEYWORD_COST,
    KEYWORDS,
    Loadout,
    MAX_KEYWORDS,
    MAX_POWER_BOUGHT,
    MODE_VALUES,
    PRESETS,
    Row,
    SIDE_VALUES,
    deck_status,
    effect_specs,
)
from ltg_core.lints import lint_card
from ltg_core.translation import render_effects

from . import ingest, scryfall

# app.py lives at apps/deckbuilder/ltg_deckbuilder/app.py; the frontend and the
# loadout store sit at the deckbuilder app root (one level up from the package).
APP_ROOT = Path(__file__).resolve().parent.parent
LOADOUT_DIR = APP_ROOT / "loadouts"
FRONTEND_DIR = APP_ROOT / "frontend"
# Bundled example loadouts (repo /examples) — readable fallbacks for the edit
# flow (Options → Characters → Edit), never written to. A save/update of an
# example writes into LOADOUT_DIR, shadowing it (same rule as the game server).
EXAMPLES_DIR = APP_ROOT.parent.parent / "examples"

app = FastAPI(title="Langelier Tactical Game — Deck Builder")


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class AddCardBody(BaseModel):
    source_name: str


class LoadoutBody(BaseModel):
    loadout: dict


class CardBody(BaseModel):
    card: dict


class ImportBody(BaseModel):
    names: List[str]


# --------------------------------------------------------------------------- #
# Scryfall
# --------------------------------------------------------------------------- #
@app.get("/api/scryfall/search")
def api_search(q: str = "") -> dict:
    try:
        return {"matches": scryfall.search(q)}
    except Exception as exc:  # network / upstream errors → 502
        raise HTTPException(status_code=502, detail=f"Scryfall error: {exc}")


@app.post("/api/cards/import")
def api_import(body: ImportBody) -> dict:
    """Bulk-import a pasted deck list. Builds EVERY card (no type/colour/count
    gate) so nothing interrupts the import; problems are flagged in the UI, not
    blocked. Names that Scryfall can't resolve are reported in `not_found`.
    """
    # Resolve the whole list in batches of 75 (one request each) instead of
    # 1-2 requests per card; firing ~80 rapid requests for a 40-card list got us
    # rate-limited (HTTP 429) partway through, silently dropping most cards.
    # A batch failure (rate limit, timeout, bad identifier) must not 500 the
    # whole import — fall back to treating every name as unmatched and let the
    # per-name fuzzy path below sort them out.
    try:
        found, unmatched = scryfall.fetch_collection(body.names)
    except Exception:
        found, unmatched = {}, list(body.names)

    # The batch endpoint is exact-match only; recover the rest with a per-name
    # fuzzy fallback (the throttled, slower path — but only for the few misses).
    not_found = []
    for name in unmatched:
        try:
            found[name] = scryfall.fetch_best(name)
        except Exception:
            not_found.append(name)

    out = []
    for name in body.names:
        data = found.get(name)
        if data is None:
            continue
        try:
            card = ingest.build_card(data)
        except Exception:
            not_found.append(name)
            continue
        out.append({"card": card.model_dump(), "lints": lint_card(card)})
    return {"cards": out, "not_found": not_found}


@app.post("/api/cards/add")
def api_add_card(body: AddCardBody) -> Card:
    try:
        data = scryfall.fetch_named(body.source_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scryfall error: {exc}")

    bad = ingest.forbidden_type(data.get("type_line", ""))
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"{data.get('name', 'This card')} is a {bad}; "
            f"LTG loadouts only accept spells (no {', '.join(ingest.FORBIDDEN_TYPES)}).",
        )
    return ingest.build_card(data)


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
# Per-card validation / re-render / lints (powers the guided effect editor)
# --------------------------------------------------------------------------- #
@app.get("/api/effect-specs")
def api_effect_specs() -> dict:
    """Param descriptors per primitive + target-builder vocab, for the editor."""
    return {"specs": effect_specs(), "modes": MODE_VALUES, "sides": SIDE_VALUES}


class CharacterPriceBody(BaseModel):
    character: dict


@app.get("/api/character-model")
def api_character_model() -> dict:
    """The points-buy character-creation model (Design Update 05, §P-1..P-4): the
    single source of truth for the Deckbuilder's build UI — budget, flat costs,
    keyword costs/bans, guardrails, and the four archetypes as loadable presets."""
    presets = {}
    for a, p in PRESETS.items():
        presets[a.value] = {
            "hp": p["hp"], "mana": p["mana"], "cards": p["cards"],
            "power_bought": p["power"], "attack_mode": p["mode"].value,
        }
    keywords = {
        kw: {"cost": cost, "display": KEYWORDS.get(kw, {}).get("display", kw),
             "gloss": KEYWORDS.get(kw, {}).get("gloss", "")}
        for kw, cost in CREATION_KEYWORD_COST.items()
    }
    return {
        "budget": CREATION_BUDGET,
        "baseline": {"hp": BASELINE_HP, "mana": BASELINE_MANA, "cards": BASELINE_CARDS},
        "base_power": {m.value: p for m, p in BASE_POWER.items()},
        "costs": {"hp_step": COST_HP_STEP, "mana": COST_MANA,
                  "card": COST_CARD, "power": COST_POWER},
        "caps": {"power_bought": MAX_POWER_BOUGHT, "keywords": MAX_KEYWORDS},
        "keywords": keywords,
        "banned_keywords": sorted(BANNED_CREATION_KEYWORDS),
        "presets": presets,
        "modes": MODE_VALUES,
        "rows": [r.value for r in Row],
    }


@app.post("/api/character/price")
def api_character_price(body: CharacterPriceBody) -> dict:
    """Validate a build and return its points/stat block for live UI feedback.

    Non-blocking by design: an over-budget or malformed build returns `valid:
    False` with the reasons rather than a 4xx, so the editor can show the overage
    while the player keeps adjusting."""
    try:
        char = Character.model_validate(body.character)
    except ValidationError as exc:
        return {"valid": False, "errors": _format_errors(exc),
                "points_spent": None, "points_remaining": None, "stat_block": None}
    return {
        "valid": True,
        "errors": [],
        "points_spent": char.points_spent,
        "points_remaining": char.points_remaining,
        "stat_block": char.stat_block,
    }


@app.post("/api/cards/validate")
def api_validate_card(body: CardBody) -> dict:
    """Structurally validate a card, re-derive its text from effects, and lint.

    `effects` (+ `targets`) is the source of truth: unless `text_override` is
    set, `translated_text` is re-rendered here so text never drifts from effects.
    """
    try:
        card = Card.model_validate(body.card)
    except ValidationError as exc:
        return {"valid": False, "errors": _format_errors(exc), "card": None, "lints": []}

    if not card.text_override:
        card.translated_text = render_effects(
            card.effects, card.targets, channeled=card.timing.value == "channeled"
        )

    return {
        "valid": True,
        "errors": [],
        "card": card.model_dump(),
        "lints": lint_card(card),
    }


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
        # Fall back to the bundled examples (read-only): lets the game's
        # "Edit in Deckbuilder" open characters that only exist as examples.
        example = EXAMPLES_DIR / f"{_slug(name)}.json"
        if example.exists():
            path = example
        else:
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


def _build_engine_loadout(raw: dict):
    """(engine_loadout, omitted) — ONLY structurally-valid, validated cards, texts
    re-rendered, character stats resolved. Raises HTTPException 422 on a bad
    character. Shared by the file export and the in-place game update."""
    try:
        character = Character.model_validate(raw.get("character", {}))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=["character invalid: " + e for e in _format_errors(exc)],
        )

    exported, omitted = [], []
    for i, raw_card in enumerate(raw.get("cards", [])):
        name = raw_card.get("name") or raw_card.get("source_name") or f"card #{i + 1}"
        try:
            card = Card.model_validate(raw_card)
        except ValidationError as exc:
            omitted.append({"name": name, "reason": "structurally invalid: " + "; ".join(_format_errors(exc))})
            continue
        if not card.validated:
            omitted.append({"name": name, "reason": "not validated — ratify its effects first"})
            continue
        if not card.text_override:
            card.translated_text = render_effects(
                card.effects, card.targets, channeled=card.timing.value == "channeled"
            )
        exported.append(card.model_dump())

    # Include the resolved stats for the engine's convenience (they match the table).
    engine_loadout = {
        "ltg_version": raw.get("ltg_version", "0.1"),
        "character": {**character.model_dump(), "stats": character.stats},
        "cards": exported,
    }
    return engine_loadout, omitted


@app.post("/api/loadout/export")
def api_export(body: LoadoutBody) -> dict:
    """Emit an engine loadout containing ONLY structurally-valid, validated cards.

    Unvalidated or malformed cards are omitted and reported (explicit behaviour);
    this is separate from the normal Save, which keeps drafts as-is.
    """
    engine_loadout, omitted = _build_engine_loadout(body.loadout)
    return {
        "engine_loadout": engine_loadout,
        "exported_count": len(engine_loadout["cards"]),
        "omitted": omitted,
    }


class UpdateGameBody(BaseModel):
    name: str            # the game character id being edited (the file stem)
    loadout: dict


@app.post("/api/loadout/update-game")
def api_update_game(body: UpdateGameBody) -> dict:
    """The edit-flow save (Options → Characters → Edit): write the engine-ready
    loadout over the game's character file, keeping the ORIGINAL id even if the
    character was renamed — so the game updates in place rather than forking.
    Editing a bundled example writes into LOADOUT_DIR, shadowing it (the same
    rule the game server applies). The game re-scans per request: the updated
    character appears in the next New Game without a restart."""
    engine_loadout, omitted = _build_engine_loadout(body.loadout)
    if not engine_loadout["cards"]:
        raise HTTPException(status_code=422,
                            detail=["nothing to update — no validated cards"])
    path = _safe_path(body.name)
    LOADOUT_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(engine_loadout, indent=2))
    return {
        "updated": path.stem,
        "exported_count": len(engine_loadout["cards"]),
        "omitted": omitted,
    }


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
