"""Towns and scenarios — the standalone content behind Scenario Mode
(Design Update 17 §D17-1, §D17-5.1, §D17-6.1).

A **town** is a pre-generated stage: name, region flavour, a scene, and its
locations — the four REQUIRED functions (inn / weaponsmith / artificer /
apothecary), one location each, plus 1–3 flavour locations — every location
with 1–2 resident NPCs carrying persona prose (no dialogue, no inventory: those
are act materializations). A town is the starting point for many scenarios.

A **scenario** (pre-generated) is a town reference + an arc (villain, stakes,
three act outlines) + Act I fully materialized (town portion + adventure) so
New Scenario is instant; Acts II–III are always dynamic.

Both live as JSON under the tracked content dir — ``content/towns/<id>.json``
and ``content/scenarios/<id>.json`` — so a commit ships them to every install
(the same rule encounters and adventures follow). Hidden ids live beside the
other hidden lists in the gitignored loadouts dir.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import content

TOWNS_DIR = content.CONTENT_DIR / "towns"
SCENARIOS_DIR = content.CONTENT_DIR / "scenarios"
TOWN_HIDDEN_FILE = content.LOADOUTS_DIR / "towns_hidden.json"
SCENARIO_HIDDEN_FILE = content.LOADOUTS_DIR / "scenarios_hidden.json"

# §D17-5.1: the four required functions (one location each) …
REQUIRED_FUNCTIONS = ("inn", "weaponsmith", "artificer", "apothecary")
# … plus 1–3 flavour locations that host questgivers and handoff NPCs.
FLAVOR_FUNCTIONS = ("tavern", "shrine", "witch_hut", "guard_post", "market",
                    "docks", "library", "graveyard", "gate", "manor", "well",
                    "chapel", "stables", "warrens", "flavor")
MIN_FLAVOR = 1
MAX_FLAVOR = 3
ACT_COUNT = 3

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", (text or "").lower()).strip("_")[:60]


def _hidden(path: Path) -> set:
    return content._read_id_set(path)


def _set_hidden(path: Path, ids: set) -> None:
    content._write_id_set(path, ids)


def _load_dir(d: Path, kind: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        raw = content._load_json(p)
        if raw is None or raw.get("kind") != kind:
            continue
        out[p.stem] = raw
    return out


def _write(d: Path, item_id: str, raw: Dict[str, Any]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Towns
# --------------------------------------------------------------------------- #
def validate_town(raw: Dict[str, Any]) -> Dict[str, Any]:
    """§D17-5.1 town validation: the four functions present (one each), 1–3
    flavour locations, every location has a scene and 1–2 NPCs, every NPC a
    portrait_desc and persona. Returns the cleaned town (ids slugged, unknown
    keys dropped). Raises ValueError with a human message."""
    if not isinstance(raw, dict):
        raise ValueError("town must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("town needs a name")
    scene = str(raw.get("scene") or "").strip()
    if not scene:
        raise ValueError("town needs a scene (the town map's painted view)")
    locs_raw = raw.get("locations")
    if not isinstance(locs_raw, list) or not locs_raw:
        raise ValueError("town needs a locations list")
    seen_fn: Dict[str, str] = {}
    seen_ids: set = set()
    seen_npc: set = set()
    locations: List[Dict[str, Any]] = []
    flavor_count = 0
    for i, loc in enumerate(locs_raw, start=1):
        if not isinstance(loc, dict):
            raise ValueError(f"location {i} must be an object")
        lname = str(loc.get("name") or "").strip()
        if not lname:
            raise ValueError(f"location {i} needs a name")
        fn = str(loc.get("function") or "").strip().lower()
        if fn in REQUIRED_FUNCTIONS:
            if fn in seen_fn:
                raise ValueError(f"two locations claim the {fn}: {seen_fn[fn]} and {lname}")
            seen_fn[fn] = lname
        else:
            if fn not in FLAVOR_FUNCTIONS:
                fn = "flavor"
            flavor_count += 1
        lid = _slug(str(loc.get("id") or lname)) or f"location_{i}"
        if lid in seen_ids:
            lid = f"{lid}_{i}"
        seen_ids.add(lid)
        lscene = str(loc.get("scene") or "").strip()
        if not lscene:
            raise ValueError(f"location '{lname}' needs a scene")
        npcs_raw = loc.get("npcs")
        if not isinstance(npcs_raw, list) or not (1 <= len(npcs_raw) <= 2):
            raise ValueError(f"location '{lname}' needs 1–2 resident NPCs")
        npcs: List[Dict[str, Any]] = []
        for j, npc in enumerate(npcs_raw, start=1):
            if not isinstance(npc, dict):
                raise ValueError(f"NPC {j} at '{lname}' must be an object")
            nname = str(npc.get("name") or "").strip()
            if not nname:
                raise ValueError(f"NPC {j} at '{lname}' needs a name")
            if not str(npc.get("portrait_desc") or "").strip():
                raise ValueError(f"NPC '{nname}' needs a portrait_desc")
            if not str(npc.get("persona") or "").strip():
                raise ValueError(f"NPC '{nname}' needs persona prose")
            nid = _slug(str(npc.get("id") or nname)) or f"npc_{i}_{j}"
            if nid in seen_npc:
                nid = f"{nid}_{i}{j}"
            seen_npc.add(nid)
            npcs.append({
                "id": nid, "name": nname,
                "role": str(npc.get("role") or "").strip(),
                "persona": str(npc.get("persona") or "").strip(),
                "portrait_desc": str(npc.get("portrait_desc") or "").strip(),
                "art_url": str(npc.get("art_url") or ""),
            })
        locations.append({
            "id": lid, "name": lname, "function": fn, "scene": lscene,
            "description": str(loc.get("description") or "").strip(),
            "art_url": str(loc.get("art_url") or ""),
            "npcs": npcs,
        })
    missing = [fn for fn in REQUIRED_FUNCTIONS if fn not in seen_fn]
    if missing:
        raise ValueError("town is missing required locations: " + ", ".join(missing))
    if not (MIN_FLAVOR <= flavor_count <= MAX_FLAVOR):
        raise ValueError(f"town needs {MIN_FLAVOR}–{MAX_FLAVOR} flavour locations "
                         f"(tavern, shrine, …) — it has {flavor_count}")
    return {
        "kind": "town",
        "name": name,
        "region_flavor": str(raw.get("region_flavor") or "").strip(),
        "scene": scene,
        "art_url": str(raw.get("art_url") or ""),
        "locations": locations,
    }


def _town_registry() -> Dict[str, Dict[str, Any]]:
    return _load_dir(TOWNS_DIR, "town")


def _town_meta(tid: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    locs = raw.get("locations") or []
    return {
        "id": tid,
        "name": raw.get("name", tid),
        "region_flavor": raw.get("region_flavor", ""),
        "art_url": raw.get("art_url", ""),
        "location_count": len(locs),
        "npc_count": sum(len(l.get("npcs") or []) for l in locs),
        "art_missing": sum(1 for l in locs if not l.get("art_url"))
                       + sum(1 for l in locs for n in (l.get("npcs") or []) if not n.get("art_url"))
                       + (0 if raw.get("art_url") else 1),
    }


def list_towns() -> List[Dict[str, Any]]:
    hidden = _hidden(TOWN_HIDDEN_FILE)
    return [_town_meta(tid, raw) for tid, raw in _town_registry().items()
            if tid not in hidden]


def town_detail(town_id: str) -> Optional[Dict[str, Any]]:
    raw = _town_registry().get(town_id)
    if raw is None:
        return None
    return {"id": town_id, **copy.deepcopy(raw)}


def save_town(raw: Dict[str, Any], town_id: Optional[str] = None) -> Dict[str, Any]:
    cleaned = validate_town(raw)
    tid = town_id or _slug(cleaned["name"]) or "town"
    _write(TOWNS_DIR, tid, cleaned)
    hidden = _hidden(TOWN_HIDDEN_FILE)
    if tid in hidden:
        hidden.discard(tid)
        _set_hidden(TOWN_HIDDEN_FILE, hidden)
    return _town_meta(tid, cleaned)


def delete_town(town_id: str) -> None:
    """Remove a town: its file goes (it is content, never a bundled fixture); if
    something keeps it around, hide the id."""
    if town_id not in _town_registry():
        raise ValueError(f"unknown town: {town_id}")
    p = TOWNS_DIR / f"{town_id}.json"
    p.unlink(missing_ok=True)
    if town_id in _town_registry():
        hidden = _hidden(TOWN_HIDDEN_FILE)
        hidden.add(town_id)
        _set_hidden(TOWN_HIDDEN_FILE, hidden)


def find_location(town: Dict[str, Any], location_id: str) -> Optional[Dict[str, Any]]:
    for loc in town.get("locations") or []:
        if loc.get("id") == location_id:
            return loc
    return None


def find_npc(town: Dict[str, Any], npc_id: str) -> "Optional[tuple[Dict[str, Any], Dict[str, Any]]]":
    """(location, npc) for an npc id, or None."""
    for loc in town.get("locations") or []:
        for npc in loc.get("npcs") or []:
            if npc.get("id") == npc_id:
                return loc, npc
    return None


def location_of_function(town: Dict[str, Any], fn: str) -> Optional[Dict[str, Any]]:
    for loc in town.get("locations") or []:
        if loc.get("function") == fn:
            return loc
    return None


# --------------------------------------------------------------------------- #
# Arcs (validated shape; generated by llm.generate_arc)
# --------------------------------------------------------------------------- #
def validate_arc(raw: Dict[str, Any], town: Dict[str, Any]) -> Dict[str, Any]:
    """§D17-6.1: title, villain, stakes, three act outlines each naming a
    questgiver location + NPC that exist in the town."""
    if not isinstance(raw, dict):
        raise ValueError("arc must be an object")
    title = str(raw.get("title") or "").strip()
    villain = str(raw.get("villain") or "").strip()
    stakes = str(raw.get("stakes") or "").strip()
    if not title or not villain or not stakes:
        raise ValueError("arc needs a title, a villain, and stakes")
    acts_raw = raw.get("acts")
    if not isinstance(acts_raw, list) or len(acts_raw) != ACT_COUNT:
        raise ValueError(f"arc needs exactly {ACT_COUNT} act outlines")
    acts: List[Dict[str, Any]] = []
    for i, act in enumerate(acts_raw, start=1):
        if not isinstance(act, dict):
            raise ValueError(f"act {i} outline must be an object")
        atitle = str(act.get("title") or "").strip()
        hook = str(act.get("hook") or "").strip()
        theme = str(act.get("adventure_theme") or "").strip()
        if not atitle or not hook or not theme:
            raise ValueError(f"act {i} needs a title, a hook, and an adventure_theme")
        qloc = str(act.get("questgiver_location") or "").strip()
        qnpc = str(act.get("questgiver_npc") or "").strip()
        found = find_npc(town, qnpc)
        if found is None:
            # Tolerate the model naming the NPC by display name.
            for loc in town.get("locations") or []:
                for npc in loc.get("npcs") or []:
                    if npc.get("name", "").lower() == qnpc.lower():
                        found = (loc, npc)
        if found is None:
            raise ValueError(f"act {i}: questgiver_npc '{qnpc}' is not an NPC of this town")
        loc, npc = found
        handoff = act.get("handoff")
        handoff_id = None
        if handoff:
            hf = find_npc(town, str(handoff))
            if hf is None:
                for l2 in town.get("locations") or []:
                    for n2 in l2.get("npcs") or []:
                        if n2.get("name", "").lower() == str(handoff).lower():
                            hf = (l2, n2)
            handoff_id = hf[1]["id"] if hf else None
        acts.append({
            "title": atitle, "hook": hook,
            "questgiver_location": loc["id"], "questgiver_npc": npc["id"],
            "handoff": handoff_id,
            "adventure_theme": theme,
            "tone_notes": str(act.get("tone_notes") or "").strip(),
        })
        del qloc  # the location is derived from the NPC (single source of truth)
    return {"title": title, "villain": villain, "stakes": stakes, "acts": acts}


# --------------------------------------------------------------------------- #
# Scenarios (pre-generated: town + arc + Act I materialized)
# --------------------------------------------------------------------------- #
def _scenario_registry() -> Dict[str, Dict[str, Any]]:
    return _load_dir(SCENARIOS_DIR, "scenario")


def _scenario_meta(sid: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    arc = raw.get("arc") or {}
    return {
        "id": sid,
        "title": arc.get("title") or raw.get("title") or sid,
        "town_id": raw.get("town_id", ""),
        "town_name": raw.get("town_name", ""),
        "villain": arc.get("villain", ""),
        "stakes": arc.get("stakes", ""),
        "act_titles": [a.get("title", "") for a in arc.get("acts", [])],
        "act1_adventure_id": (raw.get("act1") or {}).get("adventure_id", ""),
        "difficulty": raw.get("difficulty", ""),
    }


def list_scenarios() -> List[Dict[str, Any]]:
    hidden = _hidden(SCENARIO_HIDDEN_FILE)
    return [_scenario_meta(sid, raw) for sid, raw in _scenario_registry().items()
            if sid not in hidden]


def scenario_detail(scenario_id: str) -> Optional[Dict[str, Any]]:
    raw = _scenario_registry().get(scenario_id)
    if raw is None:
        return None
    return {"id": scenario_id, **copy.deepcopy(raw)}


def save_scenario(raw: Dict[str, Any], scenario_id: Optional[str] = None) -> Dict[str, Any]:
    """Persist a pre-generated scenario: ``{town_id, arc, act1: {materialization,
    adventure_id}, difficulty}``. The arc is validated against the town."""
    town_id = str(raw.get("town_id") or "")
    town = town_detail(town_id)
    if town is None:
        raise ValueError(f"unknown town: {town_id}")
    arc = validate_arc(raw.get("arc") or {}, town)
    act1 = raw.get("act1") or {}
    if not isinstance(act1, dict) or not act1.get("adventure_id"):
        raise ValueError("a pre-generated scenario carries Act I's adventure_id")
    if content.adventure_detail(str(act1["adventure_id"])) is None:
        raise ValueError(f"unknown adventure for Act I: {act1['adventure_id']}")
    cleaned = {
        "kind": "scenario",
        "title": arc["title"],
        "town_id": town_id,
        "town_name": town["name"],
        "arc": arc,
        "act1": {"adventure_id": str(act1["adventure_id"]),
                 "materialization": copy.deepcopy(act1.get("materialization") or {})},
        "difficulty": str(raw.get("difficulty") or ""),
    }
    sid = scenario_id or _slug(arc["title"]) or "scenario"
    _write(SCENARIOS_DIR, sid, cleaned)
    hidden = _hidden(SCENARIO_HIDDEN_FILE)
    if sid in hidden:
        hidden.discard(sid)
        _set_hidden(SCENARIO_HIDDEN_FILE, hidden)
    return _scenario_meta(sid, cleaned)


def delete_scenario(scenario_id: str) -> None:
    if scenario_id not in _scenario_registry():
        raise ValueError(f"unknown scenario: {scenario_id}")
    (SCENARIOS_DIR / f"{scenario_id}.json").unlink(missing_ok=True)
    if scenario_id in _scenario_registry():
        hidden = _hidden(SCENARIO_HIDDEN_FILE)
        hidden.add(scenario_id)
        _set_hidden(SCENARIO_HIDDEN_FILE, hidden)


# --------------------------------------------------------------------------- #
# Act materialization — the act's generated town portion (§D17-6.2)
# --------------------------------------------------------------------------- #
def validate_materialization(raw: Dict[str, Any], town: Dict[str, Any],
                             act_outline: Dict[str, Any]) -> Dict[str, Any]:
    """``{quest: {title, text}, arrival: str, dialogues: {npc_id: tree},
    flavor: {npc_id: line}, stock?: {location_id: [...]}}``. The questgiver's
    tree must exist and carry the Quest Accept choice (a `grant_quest` +
    `unlock_adventure` pair) — with a `defeated_once`-gated branch written up
    front so a Normal-mode return re-offers the quest."""
    from .dialogue import validate_dialogue  # local: dialogue imports nothing here
    if not isinstance(raw, dict):
        raise ValueError("materialization must be an object")
    quest = raw.get("quest") or {}
    if not isinstance(quest, dict):
        raise ValueError("quest must be an object")
    qtitle = str(quest.get("title") or "").strip()
    qtext = str(quest.get("text") or "").strip()
    if not qtitle or not qtext:
        raise ValueError("quest needs a title and text")
    arrival = str(raw.get("arrival") or "").strip()
    if not arrival:
        raise ValueError("materialization needs the arrival paragraph")
    dialogues_raw = raw.get("dialogues") or {}
    if not isinstance(dialogues_raw, dict):
        raise ValueError("dialogues must be a map of npc id → tree")
    dialogues: Dict[str, Dict[str, Any]] = {}
    for npc_id, tree in dialogues_raw.items():
        npc_id = str(npc_id)
        found = find_npc(town, npc_id)
        if found is None:
            # tolerate display names
            for loc in town.get("locations") or []:
                for npc in loc.get("npcs") or []:
                    if npc.get("name", "").lower() == npc_id.lower():
                        found = (loc, npc)
        if found is None:
            raise ValueError(f"dialogue for unknown NPC '{npc_id}'")
        try:
            dialogues[found[1]["id"]] = validate_dialogue(tree)
        except ValueError as exc:
            raise ValueError(f"dialogue for {found[1]['name']}: {exc}") from exc
    qnpc = act_outline.get("questgiver_npc")
    if qnpc not in dialogues:
        raise ValueError(f"the questgiver ({qnpc}) has no dialogue tree")
    accept = False
    for node in dialogues[qnpc]["nodes"].values():
        for ch in node["choices"]:
            kinds = {h["kind"] for h in ch["effects"]}
            if "grant_quest" in kinds and "unlock_adventure" in kinds:
                accept = True
    if not accept:
        raise ValueError("the questgiver's tree needs a Quest Accept choice carrying "
                         "both grant_quest and unlock_adventure hooks")
    flavor_raw = raw.get("flavor") or {}
    flavor: Dict[str, str] = {}
    if isinstance(flavor_raw, dict):
        for npc_id, line in flavor_raw.items():
            found = find_npc(town, str(npc_id))
            if found is None:
                for loc in town.get("locations") or []:
                    for npc in loc.get("npcs") or []:
                        if npc.get("name", "").lower() == str(npc_id).lower():
                            found = (loc, npc)
            if found and str(line or "").strip():
                flavor[found[1]["id"]] = str(line).strip()
    return {
        "quest": {"title": qtitle, "text": qtext},
        "arrival": arrival,
        "dialogues": dialogues,
        "flavor": flavor,
        "stock": copy.deepcopy(raw.get("stock") or {}),
    }
