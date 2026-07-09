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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ltg_core.schema import Loadout
from ltg_combat.scenario import (
    SCENARIO_A,
    SCENARIO_C,
    _slug,
    compose_spec,
    scale_encounter,
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
            "scene": scen.get("scene", ""),
            "scene_image": "",
            "enemies": copy.deepcopy(scen["enemies"]),
            "tokens": copy.deepcopy(scen.get("tokens", {})),
            "layouts": copy.deepcopy(scen.get("layouts", {})),
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
            "scene": str(raw.get("scene") or ""),
            "scene_image": str(raw.get("scene_image") or ""),
            "enemies": copy.deepcopy(raw["enemies"]),
            "tokens": copy.deepcopy(raw.get("tokens", {})),
            "layouts": copy.deepcopy(raw.get("layouts", {})) if isinstance(raw.get("layouts"), dict) else {},
            "source": "user" if path.parent == LOADOUTS_DIR else "example",
            "path": path,
        }
    return reg


def _encounter_meta(eid: str, scen: Dict[str, Any]) -> Dict[str, Any]:
    layouts = scen.get("layouts") or {}
    return {
        "id": eid,
        "name": scen["name"],
        "enemy_names": [e.get("name", "?") for e in scen["enemies"]],
        "enemy_count": len(scen["enemies"]),
        # Party sizes this encounter carries dedicated layouts for ([] == fixed
        # roster) — the picker can badge "scales 1–4".
        "scales": sorted(int(k) for k in layouts.keys() if str(k).isdigit()),
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
        "scene_image": scen.get("scene_image", ""),
        "enemies": copy.deepcopy(scen["enemies"]),
        "tokens": copy.deepcopy(scen["tokens"]),
        "layouts": copy.deepcopy(scen.get("layouts", {})),
    }


def encounter_detail(encounter_id: str) -> Optional[Dict[str, Any]]:
    """The full, editable encounter (id + name + scene + raw enemy specs + tokens).
    `scene` and the per-enemy `description` fields feed the image-generation /
    narration systems; the editor round-trips them untouched."""
    scen = _encounter_registry().get(encounter_id)
    if scen is None:
        return None
    return {
        "id": encounter_id,
        "name": scen["name"],
        "scene": scen.get("scene", ""),
        "scene_image": scen.get("scene_image", ""),
        "enemies": copy.deepcopy(scen["enemies"]),
        "tokens": copy.deepcopy(scen["tokens"]),
        "layouts": copy.deepcopy(scen.get("layouts", {})),
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
        # The battle backdrop (LLM-generated; "" for hand-authored encounters).
        # Rides the file for the image-generation / narration systems — as do the
        # per-enemy "description" fields, which travel inside the enemy dicts.
        "scene": str(raw.get("scene") or ""),
        # Generated art references (art.py): the backdrop URL here, per-enemy
        # "image" URLs inside the enemy dicts (the deepcopy carries them).
        "scene_image": str(raw.get("scene_image") or ""),
        "enemies": copy.deepcopy(enemies),
        "tokens": copy.deepcopy(raw.get("tokens", {})) if isinstance(raw.get("tokens"), dict) else {},
    }
    layouts = _validate_layouts(raw.get("layouts"), enemies)
    if layouts:
        cleaned["layouts"] = layouts
    # Authoritative gate: build a throwaway state (a stub 1-character party) so the
    # engine validates every enemy — intents, rows, keywords — exactly as at play.
    # With layouts, every per-size roster must build too (clones included).
    stub_party = [{
        "id": "_probe", "name": "_probe", "hp": 1, "power": 1,
        "attack_mode": "melee", "level": 1, "hand_size": 0,
        "identity": ["C"], "library": [],
    }]
    probe_specs = [cleaned]
    probe_specs.extend(scale_encounter(cleaned, int(size)) for size in layouts.keys())
    for spec in probe_specs:
        try:
            state_from_dict({**spec, "party": stub_party})
        except Exception as exc:  # engine/pydantic validation
            raise ValueError(f"engine rejected the encounter: {exc}") from exc
    return cleaned


def _validate_layouts(layouts: Any, enemies: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Check per-party-size layouts (optional). Each key is a party size ("1".."4"),
    each value a list of enemy ids from the roster (repeats allowed — they clone).
    Returns the cleaned {size: [ids]} dict ({} when absent). Raises ValueError on
    unknown ids, empty rosters, or a missing boss (the centerpiece plays at every
    party size)."""
    if layouts is None:
        return {}
    if not isinstance(layouts, dict):
        raise ValueError("layouts must be an object of party size -> enemy id list")
    known = {str(e.get("id", _slug(str(e.get("name", ""))))) for e in enemies
             if isinstance(e, dict)}
    boss_ids = {str(e.get("id")) for e in enemies
                if isinstance(e, dict) and e.get("is_boss")}
    out: Dict[str, List[str]] = {}
    for size, roster in layouts.items():
        if not str(size).isdigit() or not 1 <= int(size) <= 8:
            raise ValueError(f"layouts: '{size}' is not a party size (use \"1\"..\"4\")")
        if not isinstance(roster, list) or not roster:
            raise ValueError(f"layouts[{size}]: must be a non-empty list of enemy ids")
        ids = [str(i) for i in roster]
        unknown = sorted(set(ids) - known)
        if unknown:
            raise ValueError(f"layouts[{size}]: unknown enemy id(s): {', '.join(unknown)}")
        missing_boss = sorted(boss_ids - set(ids))
        if missing_boss:
            raise ValueError(f"layouts[{size}]: the boss ({missing_boss[0]}) must "
                             "appear at every party size")
        out[str(int(size))] = ids
    return out


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
def _pool_id(enemy: Dict[str, Any]) -> str:
    return str(enemy.get("id") or _slug(str(enemy.get("name", ""))))


def encounter_art(encounter_id: str) -> Dict[str, Any]:
    """The encounter's current art references, keyed by POOL enemy id:
    ``{"scene": url, "enemies": {pool_id: url}}`` ("" / absent when none).
    Token definitions (a Swarm's spawns) are creatures too — their art rides the
    same map, keyed by the token def's key (a live spawn ``huskling_3`` resolves
    back to ``huskling`` in the snapshot)."""
    scen = _encounter_registry().get(encounter_id)
    if scen is None:
        return {"scene": "", "enemies": {}}
    enemies = {_pool_id(e): str(e["image"]) for e in scen["enemies"]
               if isinstance(e, dict) and e.get("image")}
    for tid, tok in (scen.get("tokens") or {}).items():
        if isinstance(tok, dict) and tok.get("image"):
            enemies[str(tid)] = str(tok["image"])
    return {"scene": scen.get("scene_image", ""), "enemies": enemies}


def _base_of(scaled_enemies: List[Dict[str, Any]], pool_ids: "set[str]") -> Dict[str, str]:
    """live enemy id -> pool enemy id. A layout clone gets ``<base>_<n>``
    (scale_encounter guarantees clone ids never collide with pool ids), so a live
    id not in the pool maps back by stripping the numeric suffix."""
    out: Dict[str, str] = {}
    for e in scaled_enemies:
        live = _pool_id(e)
        base = live if live in pool_ids else re.sub(r"_\d+$", "", live)
        out[live] = base if base in pool_ids else live
    return out


def build_state(character_ids: List[str], encounter_id: str,
                seed: Optional[int] = None
                ) -> "tuple[GameState, Dict[str, str], Dict[str, Any]]":
    """Compose party loadouts + an enemies-only encounter into a fresh setup state.

    Returns ``(state, portraits, art)``: ``portraits`` maps each (deduped) party
    character id to its loadout portrait, and ``art`` carries the encounter's
    generated images (``{"scene": url, "enemies": {pool_id: url}, "base_of":
    {live_id: pool_id}}``) — the engine state drops both, so the server carries
    them alongside for the snapshot. Raises ValueError with a human message on
    unknown ids / empty party.
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
    pool_ids = {_pool_id(e) for e in scenario["enemies"] if isinstance(e, dict)}
    # Party-size scaling: an encounter with per-size layouts fields the roster
    # designed for THIS party's size (clamped to the nearest defined layout).
    scenario = scale_encounter(scenario, len(character_ids))
    spec = compose_spec(loadouts, scenario)
    state = state_from_dict(spec, seed=seed)
    # spec["party"] keeps loadouts' order (compose_spec only dedupes ids in place),
    # so zip recovers the final id -> portrait mapping.
    portraits = {
        entry["id"]: raw.get("character", {}).get("portrait", "")
        for entry, raw in zip(spec["party"], loadouts)
    }
    art = encounter_art(encounter_id)
    art["base_of"] = _base_of(
        [e for e in scenario["enemies"] if isinstance(e, dict)], pool_ids)
    return state, portraits, art
