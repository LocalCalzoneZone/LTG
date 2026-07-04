"""Setup-options sourcing — the characters and encounters the New Game modal offers.

There is no single content-registry in the engine (see INTERFACE_NOTES §6), so this
module builds one by discovering on-disk loadout / encounter JSON plus the two
built-in scenarios. It is pure *loading* (resolving inputs the engine is handed) —
it computes no rules. All composition goes through the engine's own
``compose_spec`` + ``state_from_dict``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ltg_core.schema import Loadout
from ltg_combat.scenario import (
    SCENARIO_A,
    SCENARIO_C,
    _slug,
    compose_spec,
    state_from_dict,
)
from ltg_combat.state import GameState

# Repo root: apps/game-server/ltg_game_server/content.py -> up 3 == repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Where imported loadouts are saved (Deckbuilder's own loadouts dir, so an imported
# character persists and is shared with the Deckbuilder). Scanned first below.
LOADOUTS_DIR = REPO_ROOT / "apps" / "deckbuilder" / "loadouts"

# Directories scanned for loadout / encounter JSON, in priority order. The first
# file to claim a given id wins (so a curated loadouts dir can shadow examples).
_SCAN_DIRS = [
    LOADOUTS_DIR,
    REPO_ROOT / "examples",
]

# Built-in enemies-only encounters (always available, no file needed).
_BUILTIN_ENCOUNTERS: Dict[str, Dict[str, Any]] = {
    "builtin_a": SCENARIO_A,
    "builtin_c": SCENARIO_C,
}

# Roster characters the user has removed from the picker. Imported loadouts are
# removed by deleting their file; bundled examples (git-tracked repo fixtures the
# tests depend on) are removed by hiding their id here — the file stays put.
HIDDEN_FILE = LOADOUTS_DIR / "hidden.json"
# The same idea for encounters (built-ins and bundled example encounters can't have
# a file deleted, so a removal hides the id instead — see delete_encounter).
ENCOUNTER_HIDDEN_FILE = LOADOUTS_DIR / "encounters_hidden.json"


def _read_id_set(path: Path) -> set:
    try:
        data = json.loads(path.read_text())
        return set(data) if isinstance(data, list) else set()
    except (OSError, json.JSONDecodeError):
        return set()


def _write_id_set(path: Path, ids: set) -> None:
    LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(ids)))


def _hidden() -> set:
    return _read_id_set(HIDDEN_FILE)


def _set_hidden(ids: set) -> None:
    _write_id_set(HIDDEN_FILE, ids)


def _enc_hidden() -> set:
    return _read_id_set(ENCOUNTER_HIDDEN_FILE)


def _set_enc_hidden(ids: set) -> None:
    _write_id_set(ENCOUNTER_HIDDEN_FILE, ids)


def _iter_json() -> List[Path]:
    seen: set[str] = set()
    out: List[Path] = []
    for d in _SCAN_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            if p.name in seen:
                continue
            seen.add(p.name)
            out.append(p)
    return out


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# Characters (validated Deckbuilder loadouts)
# --------------------------------------------------------------------------- #
def _character_registry() -> Dict[str, Dict[str, Any]]:
    """id -> {meta, loadout(raw dict)} for every file that validates as a Loadout."""
    reg: Dict[str, Dict[str, Any]] = {}
    for path in _iter_json():
        raw = _load_json(path)
        if raw is None or "character" not in raw:
            continue
        try:
            lo = Loadout.model_validate(raw)
        except Exception:
            continue
        cid = path.stem
        char = lo.character
        reg[cid] = {
            "meta": {
                "id": cid,
                "name": char.name,
                "archetype": char.preset or "Custom",  # display label; presets or a custom build
                "colors": [c.value for c in char.colors],
                "identity": [c.value for c in char.starting_mana],
                "description": char.description,
                "portrait": char.portrait,  # data URL / image URL (may be "")
                "card_count": len(lo.cards),
                # Every roster character can be removed from the picker: imported
                # ones delete their file, examples are hidden (see delete_loadout).
                "deletable": True,
            },
            "loadout": raw,
            "path": path,
        }
    return reg


def portrait_of(character_id: str) -> str:
    entry = _character_registry().get(character_id)
    return entry["meta"]["portrait"] if entry else ""


def save_loadout(raw_loadout: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + persist an imported Deckbuilder loadout, returning its meta.

    Saved into the Deckbuilder loadouts dir as ``<name-slug>.json`` (overwriting a
    same-named character). Raises ValueError on an invalid loadout.
    """
    try:
        lo = Loadout.model_validate(raw_loadout)
    except Exception as exc:  # pydantic ValidationError et al.
        raise ValueError(f"invalid loadout: {exc}") from exc
    LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    cid = _slug(lo.character.name) or "character"
    path = LOADOUTS_DIR / f"{cid}.json"
    path.write_text(json.dumps(raw_loadout, indent=2))
    entry = _character_registry().get(path.stem)
    return entry["meta"] if entry else {"id": path.stem, "name": lo.character.name}


def delete_loadout(character_id: str) -> None:
    """Remove a character from the picker. An imported loadout (in LOADOUTS_DIR)
    has its file deleted; a bundled example is hidden instead (its git-tracked file
    is left intact). Raises ValueError on an unknown id."""
    entry = _character_registry().get(character_id)
    if entry is None:
        raise ValueError(f"unknown character: {character_id}")
    path: Path = entry["path"]
    if path.parent == LOADOUTS_DIR:
        path.unlink(missing_ok=True)
    else:
        hidden = _hidden()
        hidden.add(character_id)
        _set_hidden(hidden)


def list_characters() -> List[Dict[str, Any]]:
    hidden = _hidden()
    return [entry["meta"] for cid, entry in _character_registry().items() if cid not in hidden]


def loadout_for(character_id: str) -> Optional[Dict[str, Any]]:
    entry = _character_registry().get(character_id)
    return copy.deepcopy(entry["loadout"]) if entry else None


# --------------------------------------------------------------------------- #
# Encounters (enemies-only scenarios + the two built-ins)
# --------------------------------------------------------------------------- #
def _encounter_registry() -> Dict[str, Dict[str, Any]]:
    """id -> {name, enemies, tokens, source, path}.

    ``source`` is ``"builtin"`` (a hardcoded scenario, no file), ``"user"`` (a saved
    file in LOADOUTS_DIR — editable/deletable in place) or ``"example"`` (a bundled
    git-tracked fixture). A ``user`` file whose stem matches a built-in / example id
    shadows it, so an edited built-in overrides its hardcoded base. Hidden ids are
    NOT filtered here (build/edit still resolve them); ``list_encounters`` filters."""
    reg: Dict[str, Dict[str, Any]] = {}
    for eid, scen in _BUILTIN_ENCOUNTERS.items():
        reg[eid] = {
            "name": scen["name"],
            "enemies": copy.deepcopy(scen["enemies"]),
            "tokens": copy.deepcopy(scen.get("tokens", {})),
            "source": "builtin",
            "path": None,
        }
    for path in _iter_json():
        raw = _load_json(path)
        # Enemies-only: has an enemies list and NO party (a full scenario_*.json
        # carries a party and is skipped — its enemies still live in a builtin).
        if raw is None or "party" in raw or not isinstance(raw.get("enemies"), list):
            continue
        eid = path.stem
        reg[eid] = {
            "name": raw.get("name", eid),
            "enemies": copy.deepcopy(raw["enemies"]),
            "tokens": copy.deepcopy(raw.get("tokens", {})),
            "source": "user" if path.parent == LOADOUTS_DIR else "example",
            "path": path,
        }
    return reg


def _encounter_meta(eid: str, scen: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": eid,
        "name": scen["name"],
        "enemy_names": [e.get("name", "?") for e in scen["enemies"]],
        "enemy_count": len(scen["enemies"]),
        # Everything is removable and editable: a user file is deleted/overwritten,
        # a built-in or example is hidden / shadowed by an override file.
        "deletable": True,
        "editable": True,
    }


def list_encounters() -> List[Dict[str, Any]]:
    hidden = _enc_hidden()
    return [_encounter_meta(eid, scen)
            for eid, scen in _encounter_registry().items() if eid not in hidden]


def encounter_for(encounter_id: str) -> Optional[Dict[str, Any]]:
    scen = _encounter_registry().get(encounter_id)
    if scen is None:
        return None
    return {
        "name": scen["name"],
        "enemies": copy.deepcopy(scen["enemies"]),
        "tokens": copy.deepcopy(scen["tokens"]),
    }


def encounter_detail(encounter_id: str) -> Optional[Dict[str, Any]]:
    """The full, editable encounter (id + name + raw enemy specs + tokens)."""
    scen = _encounter_registry().get(encounter_id)
    if scen is None:
        return None
    return {
        "id": encounter_id,
        "name": scen["name"],
        "enemies": copy.deepcopy(scen["enemies"]),
        "tokens": copy.deepcopy(scen["tokens"]),
    }


def _validate_encounter(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Structurally check an authored encounter and confirm the engine can build it.

    Returns the cleaned ``{name, enemies, tokens}`` dict (no stray keys like ``id``).
    Raises ValueError with a human message on anything malformed."""
    if not isinstance(raw, dict):
        raise ValueError("encounter must be an object")
    enemies = raw.get("enemies")
    if not isinstance(enemies, list) or not enemies:
        raise ValueError("an encounter needs at least one enemy")
    for e in enemies:
        if not isinstance(e, dict) or not str(e.get("name", "")).strip():
            raise ValueError("every enemy needs a name")
        name = e["name"]
        try:
            if int(e["hp"]) <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{name}: hp must be a positive number")
        try:
            if int(e["level"]) <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{name}: level must be a positive number")
        # An enemy defines its behaviour either through a legacy `intent` template or
        # through the Update-04 framework (`components`, with the basic attack derived
        # from Power). A plain chassis with neither is legal — it just attacks. So the
        # only requirement is that, if an `intent` is present, it carries a name.
        intent = e.get("intent")
        if intent is not None and (
            not isinstance(intent, dict) or not str(intent.get("name", "")).strip()
        ):
            raise ValueError(f"{name}: intent, if given, needs a name")
    if sum(1 for e in enemies if isinstance(e, dict) and e.get("is_boss")) > 1:
        raise ValueError("an encounter can have at most one boss")
    cleaned = {
        "name": str(raw.get("name") or "Encounter"),
        "enemies": copy.deepcopy(enemies),
        "tokens": copy.deepcopy(raw.get("tokens", {})) if isinstance(raw.get("tokens"), dict) else {},
    }
    # Authoritative gate: build a throwaway state (a stub 1-character party) so the
    # engine validates every enemy — intents, rows, keywords — exactly as at play.
    stub_party = [{
        "id": "_probe", "name": "_probe", "hp": 1, "power": 1,
        "attack_mode": "melee", "level": 1, "hand_size": 0,
        "identity": ["C"], "library": [],
    }]
    try:
        state_from_dict({**cleaned, "party": stub_party})
    except Exception as exc:  # engine/pydantic validation
        raise ValueError(f"engine rejected the encounter: {exc}") from exc
    return cleaned


def save_encounter(raw: Dict[str, Any], encounter_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate + persist an encounter, returning its meta.

    Writes ``<id>.json`` into LOADOUTS_DIR. With no ``encounter_id`` the id is the
    name slug (a fresh encounter); with one it overwrites/overrides that id (editing
    a user file, or shadowing a built-in / example). Saving un-hides the id."""
    cleaned = _validate_encounter(raw)
    eid = encounter_id or _slug(cleaned["name"]) or "encounter"
    LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    (LOADOUTS_DIR / f"{eid}.json").write_text(json.dumps(cleaned, indent=2))
    hidden = _enc_hidden()
    if eid in hidden:
        hidden.discard(eid)
        _set_enc_hidden(hidden)
    scen = _encounter_registry().get(eid)
    return _encounter_meta(eid, scen) if scen else {"id": eid, "name": cleaned["name"]}


def delete_encounter(encounter_id: str) -> None:
    """Remove an encounter from the picker. A user file (in LOADOUTS_DIR) is deleted;
    if the id still resolves from a built-in or bundled example afterwards it is hidden
    so it stays gone. Raises ValueError on an unknown id."""
    if encounter_id not in _encounter_registry():
        raise ValueError(f"unknown encounter: {encounter_id}")
    (LOADOUTS_DIR / f"{encounter_id}.json").unlink(missing_ok=True)
    # A built-in base or an examples/ fixture survives the file removal — hide it.
    if encounter_id in _encounter_registry():
        hidden = _enc_hidden()
        hidden.add(encounter_id)
        _set_enc_hidden(hidden)


# --------------------------------------------------------------------------- #
# Game build (mirrors the cockpit's Session.start — engine setup path only)
# --------------------------------------------------------------------------- #
def build_state(character_ids: List[str], encounter_id: str,
                seed: Optional[int] = None) -> "tuple[GameState, Dict[str, str]]":
    """Compose party loadouts + an enemies-only encounter into a fresh setup state.

    Returns ``(state, portraits)`` where ``portraits`` maps each (deduped) party
    character id to its loadout portrait (data URL / image URL, "" if none). The
    engine state drops the portrait, so the server carries it alongside for the
    snapshot. Raises ValueError with a human message on unknown ids / empty party.
    """
    if not character_ids:
        raise ValueError("choose at least one character")
    loadouts: List[Dict[str, Any]] = []
    for cid in character_ids:
        lo = loadout_for(cid)
        if lo is None:
            raise ValueError(f"unknown character: {cid}")
        loadouts.append(lo)
    scenario = encounter_for(encounter_id)
    if scenario is None:
        raise ValueError(f"unknown encounter: {encounter_id}")
    spec = compose_spec(loadouts, scenario)
    state = state_from_dict(spec, seed=seed)
    # spec["party"] keeps loadouts' order (compose_spec only dedupes ids in place),
    # so zip recovers the final id -> portrait mapping.
    portraits = {
        entry["id"]: raw.get("character", {}).get("portrait", "")
        for entry, raw in zip(spec["party"], loadouts)
    }
    return state, portraits
