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


def _hidden() -> set:
    try:
        data = json.loads(HIDDEN_FILE.read_text())
        return set(data) if isinstance(data, list) else set()
    except (OSError, json.JSONDecodeError):
        return set()


def _set_hidden(ids: set) -> None:
    LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    HIDDEN_FILE.write_text(json.dumps(sorted(ids)))


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
                "archetype": char.archetype.value,
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
    """id -> enemies-only scenario dict {name, enemies, tokens?}."""
    reg: Dict[str, Dict[str, Any]] = {}
    for eid, scen in _BUILTIN_ENCOUNTERS.items():
        reg[eid] = {
            "name": scen["name"],
            "enemies": copy.deepcopy(scen["enemies"]),
            "tokens": copy.deepcopy(scen.get("tokens", {})),
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
        }
    return reg


def list_encounters() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for eid, scen in _encounter_registry().items():
        out.append({
            "id": eid,
            "name": scen["name"],
            "enemy_names": [e.get("name", "?") for e in scen["enemies"]],
            "enemy_count": len(scen["enemies"]),
        })
    return out


def encounter_for(encounter_id: str) -> Optional[Dict[str, Any]]:
    scen = _encounter_registry().get(encounter_id)
    return copy.deepcopy(scen) if scen else None


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
