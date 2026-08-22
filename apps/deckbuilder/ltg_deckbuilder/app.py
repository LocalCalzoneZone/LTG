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
    CREATION_BUDGET,
    CREATION_KEYWORD_COST,
    KEYWORDS,
    Loadout,
    MAX_KEYWORDS,
    MAX_POWER_BOUGHT,
    MODE_VALUES,
    PRICE_STATS,
    CORPSE_LEGAL_EFFECTS,
    REF_VALUES,
    Row,
    SIDE_VALUES,
    deck_status,
    effect_specs,
    price_list,
)
from ltg_core.lints import lint_card
from ltg_core.translation import render_effects

from . import ingest, scryfall, update

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


class ImportCustomBody(BaseModel):
    cards: List[dict]


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


@app.post("/api/cards/import-custom")
def api_import_custom(body: ImportCustomBody) -> dict:
    """Import hand-authored custom cards from JSON (schema documented in
    apps/deckbuilder/CUSTOM_CARD_SCHEMA.md). Cards are ADDED to the loadout,
    never replacing existing ones. Each card's `effect` text gets the same
    deterministic translation pass as Scryfall imports — untranslated text
    flags the card `needs_translation` for hand-authoring, it never blocks.
    A malformed entry is reported in `errors` without failing the batch.
    """
    out, errors = [], []
    for i, entry in enumerate(body.cards):
        label = (entry.get("name") if isinstance(entry, dict) else None) or f"card #{i + 1}"
        try:
            card = ingest.build_custom_card(entry)
        except Exception as exc:
            errors.append({"name": str(label), "reason": str(exc)})
            continue
        out.append({"card": card.model_dump(), "lints": lint_card(card)})
    return {"cards": out, "errors": errors}


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
    """Param descriptors per primitive + target-builder vocab, for the editor.
    `refs` is the registry of resolvable value references (name → display label)
    that backs the editor's reference dropdown."""
    return {"specs": effect_specs(), "modes": MODE_VALUES, "sides": SIDE_VALUES,
            "refs": REF_VALUES,
            # §D19-5: the verbs whose chosen target may be CORPSE-exclusive
            # (state: "corpse") — the editor shows its "corpse only" checkbox
            # for exactly these.
            "corpse_kinds": sorted(CORPSE_LEGAL_EFFECTS)}


class CharacterPriceBody(BaseModel):
    character: dict


@app.get("/api/character-model")
def api_character_model() -> dict:
    """The points-buy character-creation model (Design Update 05 §P-1..P-4,
    Update 17 §D17-2.2): the single source of truth for the Deckbuilder's build
    UI — budget, the escalating price curve, keyword costs/bans, guardrails.
    There are no presets: the points-buy is the only creation path."""
    keywords = {
        kw: {"cost": cost, "display": KEYWORDS.get(kw, {}).get("display", kw),
             "gloss": KEYWORDS.get(kw, {}).get("gloss", "")}
        for kw, cost in CREATION_KEYWORD_COST.items()
    }
    return {
        "budget": CREATION_BUDGET,
        "baseline": {"hp": BASELINE_HP, "mana": BASELINE_MANA, "cards": BASELINE_CARDS},
        "base_power": {m.value: p for m, p in BASE_POWER.items()},
        # T-79: curve[stat][n-1] is the price of the nth purchase counted from
        # baseline (an hp_step is one +2 pair). The list is long enough that a
        # client never runs off its end at any plausible spend.
        "curve": {stat: price_list(stat) for stat in PRICE_STATS},
        # Back-compat for a browser still holding the pre-Update-17 app.js:
        # the retired flat table (first-step prices) and an empty preset map,
        # so a stale client renders instead of throwing mid-load.
        "costs": {"hp_step": price_list("hp_step", 1)[0], "mana": price_list("mana", 1)[0],
                  "card": price_list("card", 1)[0], "power": price_list("power", 1)[0]},
        "presets": {},
        "caps": {"power_bought": MAX_POWER_BOUGHT, "keywords": MAX_KEYWORDS},
        "keywords": keywords,
        "banned_keywords": sorted(BANNED_CREATION_KEYWORDS),
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
        "points_over": char.points_over,  # advisory overage (Update 17 §D17-2.2)
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


# --------------------------------------------------------------------------- #
# Panel animations (Update 16): clip files live on disk beside the loadouts —
# loadouts/anim/<character_slug>/<file> — and the loadout JSON stores only the
# URL path (/anim/<slug>/<file>), which both this app and the game server serve.
# Never inline a clip into the JSON: they are megabytes and the JSON rides every
# game snapshot.
# --------------------------------------------------------------------------- #
ANIM_DIR = LOADOUT_DIR / "anim"
ANIM_URL_PREFIX = "/anim"
ANIM_EXTS = {"webm", "mp4", "webp", "gif"}


class AnimUploadBody(BaseModel):
    character: str   # the character name (slugged into the folder)
    filename: str    # original filename; extension picks the format
    data: str        # base64 payload (a data URL or bare base64)


def _anim_slug_dir(character: str) -> Path:
    slug = _slug(character)
    if not slug:
        raise HTTPException(status_code=400, detail="invalid character name")
    return ANIM_DIR / slug


@app.post("/api/anim/upload")
def api_anim_upload(body: AnimUploadBody) -> dict:
    """Write one clip to disk; return its URL path for the loadout to reference."""
    import base64
    import re as _re

    ext = Path(body.filename).suffix.lower().lstrip(".")
    if ext not in ANIM_EXTS:
        raise HTTPException(status_code=422,
                            detail=f"unsupported animation format .{ext} "
                                   f"(use {', '.join(sorted(ANIM_EXTS))})")
    stem = _re.sub(r"[^a-z0-9]+", "_", Path(body.filename).stem.lower()).strip("_") or "clip"
    payload = body.data.split(",", 1)[1] if body.data.startswith("data:") else body.data
    try:
        raw = base64.b64decode(payload)
    except Exception:
        raise HTTPException(status_code=422, detail="animation payload is not valid base64")
    folder = _anim_slug_dir(body.character)
    folder.mkdir(parents=True, exist_ok=True)
    # Never clobber: a re-upload of the same name gets a numeric suffix.
    path, n = folder / f"{stem}.{ext}", 1
    while path.exists():
        n += 1
        path = folder / f"{stem}_{n}.{ext}"
    path.write_bytes(raw)
    return {"file": f"{ANIM_URL_PREFIX}/{folder.name}/{path.name}",
            "bytes": len(raw), "kind": "video" if ext in ("webm", "mp4") else "image"}


class AnimDeleteBody(BaseModel):
    file: str  # the URL path returned by upload


@app.post("/api/anim/delete")
def api_anim_delete(body: AnimDeleteBody) -> dict:
    """Remove a clip file. Only paths under /anim/ resolve; anything else is refused."""
    rel = body.file[len(ANIM_URL_PREFIX) + 1:] if body.file.startswith(ANIM_URL_PREFIX + "/") else None
    if not rel:
        raise HTTPException(status_code=400, detail="not an animation path")
    target = (ANIM_DIR / rel).resolve()
    if not target.is_relative_to(ANIM_DIR.resolve()):
        raise HTTPException(status_code=400, detail="invalid animation path")
    if target.exists():
        target.unlink()
        return {"deleted": body.file}
    return {"deleted": None}


@app.get(ANIM_URL_PREFIX + "/{anim_path:path}")
def api_anim_file(anim_path: str):
    """Serve a clip for the in-builder preview (the game server has its own route)."""
    from fastapi.responses import FileResponse

    target = (ANIM_DIR / anim_path).resolve()
    if not target.is_relative_to(ANIM_DIR.resolve()) or not target.is_file():
        raise HTTPException(status_code=404, detail="animation not found")
    return FileResponse(str(target))


def _slug(name: str) -> str:
    import re

    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def _safe_path(name: str) -> Path:
    slug = _slug(name)
    if not slug:
        raise HTTPException(status_code=400, detail="invalid loadout name")
    return LOADOUT_DIR / f"{slug}.json"


# --------------------------------------------------------------------------- #
# Self-update routes (update.py), then the static frontend (mounted last so
# /api/* wins)
# --------------------------------------------------------------------------- #
app.include_router(update.router)

if FRONTEND_DIR.exists():
    from fastapi.responses import FileResponse

    @app.get("/", include_in_schema=False)
    def _index() -> FileResponse:
        # index.html carries the cache-busting ?v= numbers for app.js/styles.css;
        # it must never be cached itself, or a browser keeps the old script
        # against a new API after an update.
        return FileResponse(FRONTEND_DIR / "index.html",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
