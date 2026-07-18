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

from ltg_core.schema import EncounterObjective, Loadout
from ltg_combat.scenario import (
    SCENARIO_A,
    SCENARIO_C,
    _slug,
    compose_spec,
    scale_encounter,
    sized_roster,
    state_from_dict,
)
from ltg_combat.state import GameState

# Repo root: apps/game-server/ltg_game_server/content.py -> up 3 == repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Where imported loadouts are saved (Deckbuilder's own loadouts dir, so an imported
# character persists and is shared with the Deckbuilder). Scanned first below.
# Gitignored: this is per-install user data, never shared through the repo.
LOADOUTS_DIR = REPO_ROOT / "apps" / "deckbuilder" / "loadouts"

# Curated shared content (encounters, adventures, and their art) — git-TRACKED,
# so every install gets it via clone/pull. Runtime never writes here; content is
# promoted from LOADOUTS_DIR by scripts/publish_content.py. Edits/deletes on
# another install shadow/hide (source "example" semantics), keeping its checkout
# clean so `git pull` always fast-forwards.
CONTENT_DIR = REPO_ROOT / "content"

# Directories scanned for loadout / encounter JSON, in priority order. The first
# file to claim a given id wins (so a user's loadouts dir can shadow curated
# content, which in turn shadows the bundled examples).
_SCAN_DIRS = [
    LOADOUTS_DIR,
    CONTENT_DIR,
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
# And for adventures (a bundled example adventure survives file deletion).
ADVENTURE_HIDDEN_FILE = LOADOUTS_DIR / "adventures_hidden.json"

# Acts per adventure (Design Update 10, T-61).
ACT_COUNT = 3

# --------------------------------------------------------------------------- #
# Balance register: the global enemy Power bump. Every enemy fields +2 Power
# over its authored chassis (+4 for a boss) — applied at build time in
# `build_state_from_loadouts`, the one choke point every real game passes
# through (standalone encounters and adventure acts alike), so authored
# content, bundled examples, and LLM-generated encounters are all lifted
# uniformly. Authored JSON keeps its original numbers.
# --------------------------------------------------------------------------- #
ENEMY_POWER_BONUS = 2
BOSS_POWER_BONUS = 4


def _bump_enemy_power(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the balance-register Power bump to a (scaled) encounter's enemies:
    the chassis `power` and any attack-type intent template amounts (melee and
    ranged fallback), so both framework and legacy enemies swing harder.
    Component ability amounts are untouched — the bump is to Power, not spells."""
    out = dict(scenario)
    enemies: List[Dict[str, Any]] = []
    for e in scenario.get("enemies", []):
        if not isinstance(e, dict):
            enemies.append(e)
            continue
        e = copy.deepcopy(e)
        bump = BOSS_POWER_BONUS if e.get("is_boss") else ENEMY_POWER_BONUS
        base_power = e.get("power", e.get("intent", {}).get("amount", 0))
        try:
            e["power"] = int(base_power) + bump
        except (TypeError, ValueError):
            e["power"] = bump
        for key in ("intent", "ranged_intent"):
            tmpl = e.get(key)
            if (isinstance(tmpl, dict) and isinstance(tmpl.get("amount"), int)
                    and tmpl.get("intent_type", "attack") == "attack"):
                tmpl["amount"] += bump
        enemies.append(e)
    out["enemies"] = enemies
    return out


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


def _adv_hidden() -> set:
    return _read_id_set(ADVENTURE_HIDDEN_FILE)


def _set_adv_hidden(ids: set) -> None:
    _write_id_set(ADVENTURE_HIDDEN_FILE, ids)


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
            "difficulty": str(raw.get("difficulty") or ""),
            "enemies": copy.deepcopy(raw["enemies"]),
            "tokens": copy.deepcopy(raw.get("tokens", {})),
            "layouts": copy.deepcopy(raw.get("layouts", {})) if isinstance(raw.get("layouts"), dict) else {},
            "objective": copy.deepcopy(raw.get("objective")) if isinstance(raw.get("objective"), dict) else None,
            "source": "user" if path.parent == LOADOUTS_DIR else "example",
            "path": path,
        }
    return reg


def _encounter_meta(eid: str, scen: Dict[str, Any]) -> Dict[str, Any]:
    layouts = scen.get("layouts") or {}
    return {
        "id": eid,
        "name": scen["name"],
        "difficulty": scen.get("difficulty", ""),  # "made at" flag ("" = unstamped)
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
    # An adventure's acts are stored as ordinary encounter files (so the editor,
    # the art system, and game building all work on them unchanged) but they are
    # not standalone content: the picker lists the ADVENTURE, never its acts.
    hidden = _enc_hidden() | _adventure_act_ids()
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
        **({"objective": copy.deepcopy(scen["objective"])} if scen.get("objective") else {}),
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
        "difficulty": scen.get("difficulty", ""),
        "enemies": copy.deepcopy(scen["enemies"]),
        "tokens": copy.deepcopy(scen["tokens"]),
        "layouts": copy.deepcopy(scen.get("layouts", {})),
        **({"objective": copy.deepcopy(scen["objective"])} if scen.get("objective") else {}),
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
    # The difficulty the content was MADE at (llm.py stamps generation; absent
    # for hand-authored work). A display flag only — never a rules input.
    if str(raw.get("difficulty") or "").strip():
        cleaned["difficulty"] = str(raw["difficulty"]).strip()
    # Parse the objective's kind first — a `waves` objective moves the
    # mini-boss coverage rule from the layouts (wave 1) to the final wave.
    objective_raw = raw.get("objective")
    obj_kind = objective_raw.get("kind") if isinstance(objective_raw, dict) else None
    layouts = _validate_layouts(raw.get("layouts"), enemies,
                                boss_in_reserve=(obj_kind == "waves"))
    if layouts:
        cleaned["layouts"] = layouts
    objective = _validate_objective(objective_raw, enemies, layouts)
    if objective is not None:
        cleaned["objective"] = objective
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


def _validate_layouts(layouts: Any, enemies: List[Dict[str, Any]],
                      boss_in_reserve: bool = False) -> Dict[str, List[str]]:
    """Check per-party-size layouts (optional). Each key is a party size ("1".."4"),
    each value a list of enemy ids from the roster (repeats allowed — they clone).
    Returns the cleaned {size: [ids]} dict ({} when absent). Raises ValueError on
    unknown ids, empty rosters, or a missing boss (the centerpiece plays at every
    party size — unless `boss_in_reserve`: a `waves` objective fields its
    mini-boss in the FINAL wave instead, checked by `_validate_objective`)."""
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
        if not boss_in_reserve:
            missing_boss = sorted(boss_ids - set(ids))
            if missing_boss:
                raise ValueError(f"layouts[{size}]: the boss ({missing_boss[0]}) must "
                                 "appear at every party size")
        out[str(int(size))] = ids
    return out


def _objective_roster_ids(roster: Any) -> List[str]:
    """Every id an authored wave/reinforcement roster mentions, across its
    per-size variants (or the plain list itself)."""
    if isinstance(roster, dict):
        out: List[str] = []
        for ids in roster.values():
            out.extend(str(i) for i in (ids or []))
        return out
    return [str(i) for i in (roster or [])]


def _validate_objective(raw_obj: Any, enemies: List[Dict[str, Any]],
                        layouts: Dict[str, List[str]]) -> Optional[Dict[str, Any]]:
    """Validate an encounter's optional objective (§D12-1): the schema shape,
    roster ids against the pool, the race target's presence in every layout,
    and — for `waves` — the mini-boss's final-wave placement. Returns the
    cleaned dict, or None when absent."""
    if raw_obj is None:
        return None
    try:
        obj = EncounterObjective.model_validate(raw_obj)
    except Exception as exc:
        raise ValueError(f"objective: {exc}") from exc
    known = {str(e.get("id", _slug(str(e.get("name", ""))))) for e in enemies
             if isinstance(e, dict)}
    boss_ids = {str(e.get("id")) for e in enemies
                if isinstance(e, dict) and e.get("is_boss")}

    def check_ids(ids: List[str], where: str) -> None:
        unknown = sorted(set(ids) - known)
        if unknown:
            raise ValueError(
                f"objective {where}: unknown enemy id(s): {', '.join(unknown)}")

    raw = obj.model_dump(mode="json", exclude_none=True)
    if obj.kind == "waves":
        for i, wave in enumerate(raw.get("waves", []), start=2):
            check_ids(_objective_roster_ids(wave), f"wave {i}")
        if boss_ids:
            boss = next(iter(boss_ids))
            waves = raw.get("waves", [])
            sizes = [int(s) for s in layouts.keys()] or [1]
            for size in sizes:
                final = sized_roster(waves[-1], size)
                if boss not in final:
                    raise ValueError(
                        f"objective: the mini-boss ({boss}) must appear in the "
                        f"FINAL wave at every party size (missing at size {size})")
                for i, wave in enumerate(waves[:-1], start=2):
                    if boss in sized_roster(wave, size):
                        raise ValueError(
                            f"objective: the mini-boss ({boss}) belongs in the "
                            f"final wave, not wave {i}")
                if boss in layouts.get(str(size), []):
                    raise ValueError(
                        f"objective: the mini-boss ({boss}) belongs in the "
                        "final wave, not wave 1 (the layouts)")
    elif obj.kind == "survive":
        for r in raw.get("reinforcements", []):
            check_ids(_objective_roster_ids(r.get("layouts") or r.get("ids")),
                      f"reinforcements (turn {r.get('turn')})")
    else:  # race
        target = str(obj.target)
        if target not in known:
            raise ValueError(f"objective: marked target '{target}' is not in "
                             "the enemy pool")
        for size, roster in (layouts or {}).items():
            if target not in roster:
                raise ValueError(
                    f"objective: the marked target ({target}) must be fielded "
                    f"in every layout (missing at size {size})")
    return raw


def _art_file_exists(url: str) -> bool:
    """Whether an /art/ reference's file is still on disk (user art or published
    content art). Non-/art/ references (data URLs etc.) count as existing."""
    if not url.startswith("/art/"):
        return True
    rel = url[len("/art/"):]
    return ((LOADOUTS_DIR / "art" / rel).is_file()
            or (CONTENT_DIR / "art" / rel).is_file())


def _carry_art_refs(cleaned: Dict[str, Any], eid: str) -> None:
    """Never let a save orphan persisted art. The editor posts its own state,
    which can predate art generated since it loaded (the queue persists images
    server-side, one file save per image) — so a missing/empty image ref
    inherits the stored one, provided its file still exists. Deliberate removal
    is safe: the art DELETE route deletes the file before it saves, so a
    dangling stored ref is never carried."""
    prev = _encounter_registry().get(eid)
    if prev is None:
        return

    def key(e: Dict[str, Any]) -> str:
        return str(e.get("id") or _slug(str(e.get("name", ""))))

    if not cleaned.get("scene_image"):
        old = str(prev.get("scene_image") or "")
        if old and _art_file_exists(old):
            cleaned["scene_image"] = old
    prev_by = {key(e): e for e in prev.get("enemies", []) if isinstance(e, dict)}
    for e in cleaned.get("enemies", []):
        if isinstance(e, dict) and not e.get("image"):
            img = str((prev_by.get(key(e)) or {}).get("image") or "")
            if img and _art_file_exists(img):
                e["image"] = img
    prev_toks = prev.get("tokens") or {}
    for k, t in (cleaned.get("tokens") or {}).items():
        if isinstance(t, dict) and not t.get("image"):
            img = str((prev_toks.get(k) or {}).get("image") or "")
            if img and _art_file_exists(img):
                t["image"] = img


def save_encounter(raw: Dict[str, Any], encounter_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate + persist an encounter, returning its meta.

    Writes ``<id>.json`` into LOADOUTS_DIR. With no ``encounter_id`` the id is the
    name slug (a fresh encounter); with one it overwrites/overrides that id (editing
    a user file, or shadowing a built-in / example). Saving un-hides the id."""
    cleaned = _validate_encounter(raw)
    eid = encounter_id or _slug(cleaned["name"]) or "encounter"
    _carry_art_refs(cleaned, eid)
    # "Made at" survives edits from clients that don't round-trip the field.
    if not cleaned.get("difficulty"):
        prev = _encounter_registry().get(eid)
        if prev and prev.get("difficulty"):
            cleaned["difficulty"] = prev["difficulty"]
    # An adventure act edited through this path must keep its adventure valid
    # (Act III boss constraints, §D10-4.1) — checked before anything persists.
    _check_act_edit(eid, cleaned)
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
# Adventures — the three-act run (Design Update 10)
#
# An adventure is a WRAPPER (name, flavor, per-act narration) over three acts,
# each a complete standard encounter. The wrapper persists as its own JSON
# (kind: "adventure"); each act persists as an ordinary encounter file with the
# reserved id "<adventure_id>__act<n>" — so the encounter editor, the art system,
# and the game-build path all work on an act unchanged. Act ids never appear in
# the standalone encounter list (see list_encounters).
# --------------------------------------------------------------------------- #
def act_encounter_id(adventure_id: str, act_number: int) -> str:
    """The reserved encounter id behind one act (act_number is 1-based)."""
    return f"{adventure_id}__act{act_number}"


def _adventure_registry() -> Dict[str, Dict[str, Any]]:
    """id -> {name, flavor, acts:[{narration, encounter_id}], source, path}."""
    reg: Dict[str, Dict[str, Any]] = {}
    for path in _iter_json():
        raw = _load_json(path)
        if raw is None or raw.get("kind") != "adventure":
            continue
        acts = raw.get("acts")
        if not isinstance(acts, list):
            continue
        reg[path.stem] = {
            "name": str(raw.get("name") or path.stem),
            "flavor": str(raw.get("flavor") or ""),
            "difficulty": str(raw.get("difficulty") or ""),
            "acts": copy.deepcopy(acts),
            "source": "user" if path.parent == LOADOUTS_DIR else "example",
            "path": path,
        }
    return reg


def _adventure_act_ids() -> set:
    """Every encounter id claimed as an act by a registered adventure."""
    out: set = set()
    for adv in _adventure_registry().values():
        for act in adv["acts"]:
            if isinstance(act, dict) and act.get("encounter_id"):
                out.add(str(act["encounter_id"]))
    return out


def _adventure_meta(aid: str, adv: Dict[str, Any]) -> Dict[str, Any]:
    act_names = []
    reg = _encounter_registry()
    for act in adv["acts"]:
        eid = str(act.get("encounter_id", "")) if isinstance(act, dict) else ""
        scen = reg.get(eid)
        act_names.append(scen["name"] if scen else eid)
    return {
        "id": aid,
        "name": adv["name"],
        "flavor": adv["flavor"],
        "difficulty": adv.get("difficulty", ""),  # "made at" flag ("" = unstamped)
        "act_names": act_names,
        "deletable": True,
        "editable": True,
    }


def list_adventures() -> List[Dict[str, Any]]:
    hidden = _adv_hidden()
    return [_adventure_meta(aid, adv)
            for aid, adv in _adventure_registry().items() if aid not in hidden]


def adventure_detail(adventure_id: str) -> Optional[Dict[str, Any]]:
    """The full adventure: wrapper fields plus each act's embedded encounter
    detail (the same shape `encounter_detail` returns, plus `narration`)."""
    adv = _adventure_registry().get(adventure_id)
    if adv is None:
        return None
    acts = []
    for act in adv["acts"]:
        eid = str(act.get("encounter_id", "")) if isinstance(act, dict) else ""
        enc = encounter_detail(eid)
        if enc is None:
            return None  # a wrapper pointing at a missing act file is unusable
        acts.append({"narration": str(act.get("narration") or ""),
                     "encounter_id": eid, **enc})
    return {"id": adventure_id, "name": adv["name"], "flavor": adv["flavor"],
            "difficulty": adv.get("difficulty", ""), "acts": acts}


def _act_boss_levels(enemies: List[Dict[str, Any]]) -> "tuple[List[int], int]":
    """(boss levels, highest enemy level) for one act's enemy pool."""
    bosses = [int(e.get("level", 0)) for e in enemies
              if isinstance(e, dict) and e.get("is_boss")]
    highest = max((int(e.get("level", 0)) for e in enemies if isinstance(e, dict)),
                  default=0)
    return bosses, highest


def _validate_act(cleaned: Dict[str, Any]) -> None:
    """Adventure acts are held to the generated-encounter bar (§D10-4.1): party-
    size layouts "1"–"4" with the party outnumbered (2×, duplicates count), and
    every enemy described (the art / narration systems feed on it). Standalone
    encounters stay free of these extras."""
    layouts = cleaned.get("layouts") or {}
    objective = cleaned.get("objective") or {}
    waves = objective.get("waves", []) if objective.get("kind") == "waves" else []
    for size in range(1, 5):
        roster = layouts.get(str(size))
        if not isinstance(roster, list):
            raise ValueError('needs a "layouts" object with keys "1"–"4" '
                             "(one enemy roster per party size)")
        if waves:
            # T-66: with a `waves` objective the 2× outnumbering spreads across
            # the waves — every wave fields ≥ 1× party size, ≥ 2× in total.
            counts = [len(roster)] + [len(sized_roster(w, size)) for w in waves]
            thin = [i + 1 for i, n in enumerate(counts) if n < size]
            if thin:
                raise ValueError(
                    f'wave {thin[0]} fields fewer than {size} enemies at '
                    f'layouts["{size}"] — every wave fields at least 1× the party')
            if sum(counts) < 2 * size:
                raise ValueError(
                    f'layouts["{size}"]: only {sum(counts)} enemies across all '
                    f"waves — a party of {size} must face at least {2 * size} in total")
        elif len(roster) < 2 * size:
            raise ValueError(
                f'layouts["{size}"] fields only {len(roster)} enemies — a party '
                f"of {size} must be outnumbered with at least {2 * size}")
    undescribed = [str(e.get("name", "?")) for e in cleaned.get("enemies", [])
                   if isinstance(e, dict)
                   and not str(e.get("description") or "").strip()]
    if undescribed:
        raise ValueError('every enemy needs a "description": '
                         + ", ".join(undescribed))


def _validate_adventure(acts: List[Dict[str, Any]],
                        narrations: List[str]) -> None:
    """The §D10-4.1 adventure-level checks, over already act-valid encounters.

    ``acts`` are the three cleaned encounter dicts in order; ``narrations`` the
    three act narrations. Per-act validity (layouts, minimum bodies, at most one
    boss) is `_validate_encounter`'s job and assumed done."""
    if len(acts) != ACT_COUNT:
        raise ValueError(f"an adventure has exactly {ACT_COUNT} acts")
    for i, text in enumerate(narrations, start=1):
        if not str(text or "").strip():
            raise ValueError(f"act {i} is missing its narration")
    # Objectives (§D12-1.1): at most ONE per adventure, on Acts I–II only —
    # Act III is always the standard boss kill (the climax stays a fight).
    with_objective = [i for i, act in enumerate(acts, start=1)
                      if act.get("objective")]
    if len(with_objective) > 1:
        raise ValueError("an adventure carries at most one objective "
                         f"(acts {', '.join(map(str, with_objective))} all have one)")
    if ACT_COUNT in with_objective:
        raise ValueError("Act III is always the standard boss kill — "
                         "objectives may appear on Acts I and II only")
    finale_bosses, _ = _act_boss_levels(acts[-1]["enemies"])
    if len(finale_bosses) != 1:
        raise ValueError("Act III must contain exactly one boss (is_boss)")
    finale_level = finale_bosses[0]
    for i, act in enumerate(acts, start=1):
        bosses, highest = _act_boss_levels(act["enemies"])
        if i < ACT_COUNT and bosses and bosses[0] >= finale_level:
            raise ValueError(
                f"act {i}'s mini-boss (level {bosses[0]}) must be strictly "
                f"lower level than Act III's boss (level {finale_level})")
        if highest > finale_level:
            raise ValueError(
                f"act {i} fields a level-{highest} enemy above Act III's boss "
                f"(level {finale_level}) — the boss is the adventure's "
                "highest-level enemy")


def save_adventure(raw: Dict[str, Any],
                   adventure_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate + persist an adventure (wrapper + three act files), returning its
    meta. Each act passes the exact `_validate_encounter` gate an encounter takes;
    then the §D10-4.1 adventure-level checks run; only then does anything persist.

    ``raw`` is ``{name, flavor, acts: [{narration, ...encounter}, ×3]}``."""
    if not isinstance(raw, dict):
        raise ValueError("adventure must be an object")
    acts_raw = raw.get("acts")
    if not isinstance(acts_raw, list) or len(acts_raw) != ACT_COUNT:
        raise ValueError(f"an adventure has exactly {ACT_COUNT} acts")
    name = str(raw.get("name") or "Adventure")
    # Objective placement (§D12-1.1) — checked BEFORE the per-act deep dive so
    # the standing rules produce their own message, not an id error from an act
    # that should never have carried an objective at all.
    with_objective = [i for i, act in enumerate(acts_raw, start=1)
                      if isinstance(act, dict) and act.get("objective")]
    if len(with_objective) > 1:
        raise ValueError("an adventure carries at most one objective "
                         f"(acts {', '.join(map(str, with_objective))} all have one)")
    if ACT_COUNT in with_objective:
        raise ValueError("Act III is always the standard boss kill — "
                         "objectives may appear on Acts I and II only")
    cleaned_acts: List[Dict[str, Any]] = []
    narrations: List[str] = []
    for i, act in enumerate(acts_raw, start=1):
        if not isinstance(act, dict):
            raise ValueError(f"act {i} must be an object")
        try:
            cleaned = _validate_encounter(act)
            _validate_act(cleaned)
        except ValueError as exc:
            raise ValueError(f"act {i}: {exc}") from exc
        cleaned_acts.append(cleaned)
        narrations.append(str(act.get("narration") or "").strip())
    _validate_adventure(cleaned_acts, narrations)

    aid = adventure_id or _slug(name) or "adventure"
    LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    act_entries = []
    for i, (act, narration) in enumerate(zip(cleaned_acts, narrations), start=1):
        eid = act_encounter_id(aid, i)
        (LOADOUTS_DIR / f"{eid}.json").write_text(json.dumps(act, indent=2))
        act_entries.append({"narration": narration, "encounter_id": eid})
    wrapper = {"kind": "adventure", "name": name,
               "flavor": str(raw.get("flavor") or ""), "acts": act_entries}
    if str(raw.get("difficulty") or "").strip():  # "made at" flag (llm.py stamps it)
        wrapper["difficulty"] = str(raw["difficulty"]).strip()
    (LOADOUTS_DIR / f"{aid}.json").write_text(json.dumps(wrapper, indent=2))
    hidden = _adv_hidden()
    if aid in hidden:
        hidden.discard(aid)
        _set_adv_hidden(hidden)
    adv = _adventure_registry().get(aid)
    return _adventure_meta(aid, adv) if adv else {"id": aid, "name": name}


def save_adventure_info(adventure_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update the adventure-level fields only — name, flavor, the per-act
    narrations — leaving the act encounters untouched. Returns the meta."""
    adv = _adventure_registry().get(adventure_id)
    if adv is None:
        raise ValueError(f"unknown adventure: {adventure_id}")
    name = str(patch.get("name") or adv["name"])
    flavor = patch.get("flavor")
    flavor = adv["flavor"] if flavor is None else str(flavor)
    narrations = patch.get("narrations")
    acts = copy.deepcopy(adv["acts"])
    if narrations is not None:
        if not isinstance(narrations, list) or len(narrations) != len(acts):
            raise ValueError(f"narrations must be a list of {len(acts)}")
        for act, text in zip(acts, narrations):
            if not str(text or "").strip():
                raise ValueError("every act needs a non-empty narration")
            act["narration"] = str(text)
    wrapper = {"kind": "adventure", "name": name, "flavor": flavor, "acts": acts}
    if adv.get("difficulty"):  # the "made at" flag rides through info edits
        wrapper["difficulty"] = adv["difficulty"]
    LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    (LOADOUTS_DIR / f"{adventure_id}.json").write_text(json.dumps(wrapper, indent=2))
    fresh = _adventure_registry().get(adventure_id)
    return _adventure_meta(adventure_id, fresh)


def delete_adventure(adventure_id: str) -> None:
    """Remove an adventure and its act files. A bundled example that survives
    the deletion is hidden instead (mirroring delete_encounter)."""
    adv = _adventure_registry().get(adventure_id)
    if adv is None:
        raise ValueError(f"unknown adventure: {adventure_id}")
    for act in adv["acts"]:
        eid = str(act.get("encounter_id", "")) if isinstance(act, dict) else ""
        if eid:
            (LOADOUTS_DIR / f"{eid}.json").unlink(missing_ok=True)
    (LOADOUTS_DIR / f"{adventure_id}.json").unlink(missing_ok=True)
    if adventure_id in _adventure_registry():
        hidden = _adv_hidden()
        hidden.add(adventure_id)
        _set_adv_hidden(hidden)


def _check_act_edit(eid: str, cleaned: Dict[str, Any]) -> None:
    """Adventure-level gate on an act edited through the ordinary encounter save
    path: re-run the §D10-4.1 checks with the edited act substituted, BEFORE
    anything persists. A non-act encounter id passes straight through."""
    for aid, adv in _adventure_registry().items():
        act_ids = [str(a.get("encounter_id", "")) for a in adv["acts"]
                   if isinstance(a, dict)]
        if eid not in act_ids:
            continue
        _validate_act(cleaned)
        acts: List[Dict[str, Any]] = []
        reg = _encounter_registry()
        for act_eid in act_ids:
            if act_eid == eid:
                acts.append(cleaned)
                continue
            scen = reg.get(act_eid)
            if scen is None:
                raise ValueError(f"adventure {aid} is missing act file {act_eid}")
            acts.append({"name": scen["name"], "enemies": scen["enemies"]})
        narrations = [str(a.get("narration") or "") for a in adv["acts"]
                      if isinstance(a, dict)]
        try:
            _validate_adventure(acts, narrations)
        except ValueError as exc:
            raise ValueError(f"adventure '{adv['name']}': {exc}") from exc
        return


# --------------------------------------------------------------------------- #
# Game build (mirrors the cockpit's Session.start — engine setup path only)
# --------------------------------------------------------------------------- #
def _pool_id(enemy: Dict[str, Any]) -> str:
    return str(enemy.get("id") or _slug(str(enemy.get("name", ""))))


def encounter_art(encounter_id: str) -> Dict[str, Any]:
    """The encounter's current art references, keyed by POOL enemy id:
    ``{"scene": url, "enemies": {pool_id: url}, "descriptions": {pool_id: text}}``
    ("" / absent when none). ``descriptions`` carries each enemy's art-direction
    prose (physical appearance) so the inspect view can show it. Token
    definitions (a Swarm's spawns) are creatures too — their art rides the
    same maps, keyed by the token def's key (a live spawn ``huskling_3`` resolves
    back to ``huskling`` in the snapshot)."""
    scen = _encounter_registry().get(encounter_id)
    if scen is None:
        return {"scene": "", "enemies": {}, "descriptions": {}}
    enemies = {_pool_id(e): str(e["image"]) for e in scen["enemies"]
               if isinstance(e, dict) and e.get("image")}
    descriptions = {_pool_id(e): str(e.get("description") or "").strip()
                    for e in scen["enemies"] if isinstance(e, dict)}
    for tid, tok in (scen.get("tokens") or {}).items():
        if not isinstance(tok, dict):
            continue
        if tok.get("image"):
            enemies[str(tid)] = str(tok["image"])
        if tok.get("description"):
            descriptions[str(tid)] = str(tok["description"]).strip()
    return {"scene": scen.get("scene_image", ""), "enemies": enemies,
            "descriptions": descriptions}


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
    loadouts = loadouts_for(character_ids)
    return build_state_from_loadouts(loadouts, encounter_id, seed=seed)


def loadouts_for(character_ids: List[str]) -> List[Dict[str, Any]]:
    """The raw loadout dicts behind a picked party, in pick order. Raises
    ValueError on an empty party / unknown ids."""
    if not character_ids:
        raise ValueError("choose at least one character")
    loadouts: List[Dict[str, Any]] = []
    for cid in character_ids:
        lo = loadout_for(cid)
        if lo is None:
            raise ValueError(f"unknown character: {cid}")
        loadouts.append(lo)
    return loadouts


def build_state_from_loadouts(loadouts: List[Dict[str, Any]], encounter_id: str,
                              seed: Optional[int] = None
                              ) -> "tuple[GameState, Dict[str, str], Dict[str, Any]]":
    """`build_state` with the loadouts already in hand — the adventure layer uses
    this to field leveled (adventure-local) builds against an act."""
    scenario = encounter_for(encounter_id)
    if scenario is None:
        raise ValueError(f"unknown encounter: {encounter_id}")
    pool_ids = {_pool_id(e) for e in scenario["enemies"] if isinstance(e, dict)}
    # Party-size scaling: an encounter with per-size layouts fields the roster
    # designed for THIS party's size (clamped to the nearest defined layout).
    scenario = scale_encounter(scenario, len(loadouts))
    # Balance register: +2 Power to every enemy fielded, +4 to a boss.
    scenario = _bump_enemy_power(scenario)
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
    # Loadout character descriptions, for the inspect view (the engine drops
    # them like portraits, so they ride the session's art bundle).
    art["char_descriptions"] = {
        entry["id"]: str(raw.get("character", {}).get("description") or "")
        for entry, raw in zip(spec["party"], loadouts)
    }
    return state, portraits, art
