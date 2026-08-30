"""Towns and scenarios — the standalone content behind Scenario Mode
(Design Update 17 §D17-1, §D17-5.1, §D17-6.1).

A **town** is a pre-generated stage: name, region flavour, a scene, and its
locations — the four REQUIRED functions (inn / weaponsmith / artificer /
apothecary), one location each, plus flavour locations — every location with
resident NPCs carrying persona prose and a few scenario-agnostic TOPICS (the
flavour things they will talk about in any campaign). Quests, dialogue trees and
shop stock are act materializations, not town content. A town is the starting
point for many scenarios; locations and NPCs can be added to one at any time in
the town editor.

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
# … the three that keep a shop counter (one vendor NPC each — see below) …
MERCHANT_FUNCTIONS = ("weaponsmith", "artificer", "apothecary")
# … plus flavour locations that host questgivers and handoff NPCs.
FLAVOR_FUNCTIONS = ("tavern", "shrine", "witch_hut", "guard_post", "market",
                    "docks", "library", "graveyard", "gate", "manor", "well",
                    "chapel", "stables", "warrens", "flavor")
MIN_FLAVOR = 1
# Generation asks for 1–3; the editor may add more places and more residents to
# a town afterwards, so the gate is generous.
MAX_FLAVOR = 8
MIN_NPCS = 1
MAX_NPCS = 4
MAX_TOPICS = 4
# A quest with fewer than this many ways to take it is not a choice (§D17-5.4).
MIN_QUEST_OPTIONS = 2
MAX_QUEST_OPTIONS = 4
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
def clean_topics(raw: Any, where: str) -> List[Dict[str, Any]]:
    """An NPC's flavour exchanges: ``[{"ask": <what the party says>, "reply":
    <the NPC's answer>, "requires"?: [<flag>, …]}]``. Every NPC carries at least
    one so that talking to ANYONE is a conversation with something in it, not a
    single greeting (§D17-5.4). Town topics are scenario-agnostic; an act adds
    its own — and an act topic may be GATED on knowledge flags (§D20-1: what the
    fisherman thinks of the orc camp only becomes askable once somebody has told
    the party there IS an orc camp)."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{where}: topics must be a list")
    out: List[Dict[str, Any]] = []
    for t in raw[:MAX_TOPICS]:
        requires: List[str] = []
        if isinstance(t, str):
            ask, reply = "", t.strip()
        elif isinstance(t, dict):
            ask = str(t.get("ask") or t.get("prompt") or t.get("label") or "").strip()
            reply = str(t.get("reply") or t.get("line") or t.get("text") or "").strip()
            req = t.get("requires") or []
            if not isinstance(req, list):
                raise ValueError(f"{where}: a topic's requires must be a list of flags")
            requires = [str(f).strip() for f in req if str(f).strip()]
        else:
            raise ValueError(f"{where}: a topic must be an object with ask and reply")
        if not reply:
            raise ValueError(f"{where}: a topic needs the NPC's reply")
        row: Dict[str, Any] = {"ask": ask or "Tell us something of this place.", "reply": reply}
        if requires:
            row["requires"] = requires
        out.append(row)
    return out


def validate_town(raw: Dict[str, Any]) -> Dict[str, Any]:
    """§D17-5.1 town validation: the four functions present (one each), at least
    one flavour location, every location has an INTERIOR scene (what a character
    standing inside sees — the location backdrop) and an EXTERIOR scene (its
    frontage — the town-map card), 1–%d NPCs, every NPC a portrait_desc and
    persona. Returns the cleaned town (ids slugged, unknown keys dropped).

    Two things the cleaner settles rather than rejects:

    - **the counter**: a shop location may house several people, but exactly ONE
      of them sells (`vendor: true`); the rest are there to be talked to. The
      first NPC marked `vendor` wins, else the first resident.
    - **topics**: each NPC's scenario-agnostic flavour exchanges
      (`[{"ask", "reply"}]`) — what they will talk about in any campaign. An act
      adds its own on top; the runtime builds a conversation out of both.

    Legacy towns with a single `scene`/`art_url` load them as the interior.
    Raises ValueError with a human message.""" % MAX_NPCS
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
        interior = str(loc.get("interior_scene") or loc.get("scene") or "").strip()
        exterior = str(loc.get("exterior_scene") or "").strip()
        if not interior:
            raise ValueError(f"location '{lname}' needs an interior scene (what a visitor sees inside)")
        interior_art = str(loc.get("interior_art_url") or loc.get("art_url") or "")
        exterior_art = str(loc.get("exterior_art_url") or "")
        npcs_raw = loc.get("npcs")
        if not isinstance(npcs_raw, list) or not (MIN_NPCS <= len(npcs_raw) <= MAX_NPCS):
            raise ValueError(f"location '{lname}' needs {MIN_NPCS}–{MAX_NPCS} resident NPCs")
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
                "topics": clean_topics(npc.get("topics"), f"NPC '{nname}'"),
                "vendor": bool(npc.get("vendor")),
            })
        # One counter per shop: the marked vendor, else the first resident. Any
        # other merchant-location NPC is there for the conversation.
        if fn in MERCHANT_FUNCTIONS:
            seller = next((n for n in npcs if n["vendor"]), npcs[0])
            for n in npcs:
                n["vendor"] = n is seller
        else:
            for n in npcs:
                n["vendor"] = False
        locations.append({
            "id": lid, "name": lname, "function": fn,
            "description": str(loc.get("description") or "").strip(),
            "exterior_scene": exterior, "exterior_art_url": exterior_art,
            "interior_scene": interior, "interior_art_url": interior_art,
            # Legacy readers (`scene` / `art_url`) see the interior.
            "scene": interior, "art_url": interior_art,
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
        "topics_missing": sum(1 for l in locs for n in (l.get("npcs") or [])
                              if not (n.get("topics") or [])),
        "region_flavor": raw.get("region_flavor", ""),
        "art_url": raw.get("art_url", ""),
        "location_count": len(locs),
        "npc_count": sum(len(l.get("npcs") or []) for l in locs),
        "art_missing": sum(1 for l in locs if not (l.get("interior_art_url") or l.get("art_url")))
                       + sum(1 for l in locs if l.get("exterior_scene") and not l.get("exterior_art_url"))
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


def vendor_of(location: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The one NPC who keeps the counter at a shop location, or None. Other
    residents of a shop are there for the conversation only (§D17-5.1)."""
    if (location or {}).get("function") not in MERCHANT_FUNCTIONS:
        return None
    npcs = location.get("npcs") or []
    return next((n for n in npcs if n.get("vendor")), npcs[0] if npcs else None)


def location_of_function(town: Dict[str, Any], fn: str) -> Optional[Dict[str, Any]]:
    for loc in town.get("locations") or []:
        if loc.get("function") == fn:
            return loc
    return None


# --------------------------------------------------------------------------- #
# Arcs (validated shape; generated by llm.generate_arc)
# --------------------------------------------------------------------------- #
# §D20-2: how many people/places one scenario may bring to town.
MAX_CAST = 4
MAX_PLACES = 2


def _clean_acts_list(raw: Any, where: str) -> List[int]:
    """Which acts (1-based) a cast member / place is present for. Empty = all."""
    if raw in (None, "", []):
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{where}: acts must be a list of act numbers")
    out = []
    for a in raw:
        try:
            n = int(a)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: acts must be numbers 1–{ACT_COUNT}")
        if not 1 <= n <= ACT_COUNT:
            raise ValueError(f"{where}: act {n} is out of range (1–{ACT_COUNT})")
        if n not in out:
            out.append(n)
    return sorted(out)


def _validate_cast_and_places(raw: Dict[str, Any], town: Dict[str, Any]
                              ) -> "tuple[List[Dict[str, Any]], List[Dict[str, Any]]]":
    """§D20-2: the scenario's own additions to the town — validated like town
    content, but they live on the ARC and appear only while it runs.

    ``places``: 0–{MAX_PLACES} extra locations (a camp outside the walls, the
    burned mill) — flavour functions only, interior + exterior scenes like any
    location, no resident town NPCs of their own (the cast stands there).
    ``cast``: 0–{MAX_CAST} NPCs the scenario brings to town — a questgiver
    riding in, a rival crew, a friend who is not what they seem. Each stands at
    a town location or one of the arc's places, may be limited to certain acts,
    and may carry a ``secret``: one line only the WRITERS see (it never renders),
    so a betrayal can be authored in Act I and paid off in Act III."""
    places: List[Dict[str, Any]] = []
    seen_ids = {l["id"] for l in town.get("locations") or []}
    for i, pl in enumerate((raw.get("places") or [])[:MAX_PLACES], start=1):
        if not isinstance(pl, dict):
            raise ValueError(f"place {i} must be an object")
        name = str(pl.get("name") or "").strip()
        interior = str(pl.get("interior_scene") or pl.get("scene") or "").strip()
        if not name or not interior:
            raise ValueError(f"place {i} needs a name and an interior_scene")
        fn = str(pl.get("function") or "flavor").strip().lower()
        if fn not in FLAVOR_FUNCTIONS:
            fn = "flavor"
        pid = _slug(str(pl.get("id") or name)) or f"place_{i}"
        while pid in seen_ids:
            pid = f"{pid}_{i}"
        seen_ids.add(pid)
        places.append({
            "id": pid, "name": name, "function": fn,
            "description": str(pl.get("description") or "").strip(),
            "interior_scene": interior,
            "exterior_scene": str(pl.get("exterior_scene") or "").strip(),
            "interior_art_url": str(pl.get("interior_art_url") or ""),
            "exterior_art_url": str(pl.get("exterior_art_url") or ""),
            "acts": _clean_acts_list(pl.get("acts"), f"place '{name}'"),
        })
    cast: List[Dict[str, Any]] = []
    npc_ids = {n["id"] for l in town.get("locations") or [] for n in l.get("npcs") or []}
    place_ids = {p["id"] for p in places}
    for j, npc in enumerate((raw.get("cast") or [])[:MAX_CAST], start=1):
        if not isinstance(npc, dict):
            raise ValueError(f"cast member {j} must be an object")
        name = str(npc.get("name") or "").strip()
        if not name:
            raise ValueError(f"cast member {j} needs a name")
        if not str(npc.get("portrait_desc") or "").strip():
            raise ValueError(f"cast member '{name}' needs a portrait_desc")
        if not str(npc.get("persona") or "").strip():
            raise ValueError(f"cast member '{name}' needs persona prose")
        where = _slug(str(npc.get("location") or ""))
        if where not in seen_ids and where not in place_ids:
            raise ValueError(f"cast member '{name}' stands at '{npc.get('location')}', "
                             "which is neither a town location nor one of the arc's places")
        nid = _slug(str(npc.get("id") or name)) or f"cast_{j}"
        while nid in npc_ids:
            nid = f"{nid}_{j}"
        npc_ids.add(nid)
        cast.append({
            "id": nid, "name": name,
            "role": str(npc.get("role") or "").strip(),
            "persona": str(npc.get("persona") or "").strip(),
            "portrait_desc": str(npc.get("portrait_desc") or "").strip(),
            "art_url": str(npc.get("art_url") or ""),
            "location": where,
            "acts": _clean_acts_list(npc.get("acts"), f"cast member '{name}'"),
            # One line for the WRITERS (the act generator sees it; the player
            # never does): what this person is actually up to.
            "secret": str(npc.get("secret") or "").strip(),
            "topics": clean_topics(npc.get("topics"), f"cast member '{name}'"),
        })
    return cast, places


def town_for_act(town: Dict[str, Any], arc: Dict[str, Any],
                 act_index: int) -> Dict[str, Any]:
    """§D20-2: the town AS THIS ACT SEES IT — the base town plus the arc's
    places and cast present this act, merged as ordinary locations/NPCs (marked
    ``"_scenario": True``) so every downstream reader (the town screen, the
    dialogue validators, the journal) needs no new cases. Idempotent: previously
    merged entries are stripped first, so it can run on an already-composed
    town."""
    out = copy.deepcopy(town)
    locs = [l for l in out.get("locations") or [] if not l.get("_scenario")]
    for l in locs:
        l["npcs"] = [n for n in l.get("npcs") or [] if not n.get("_scenario")]
    act_no = act_index + 1
    for pl in arc.get("places") or []:
        if pl.get("acts") and act_no not in pl["acts"]:
            continue
        entry = copy.deepcopy(pl)
        entry.pop("acts", None)
        entry.update({"_scenario": True, "npcs": [],
                      # Legacy readers (`scene` / `art_url`) see the interior.
                      "scene": entry.get("interior_scene", ""),
                      "art_url": entry.get("interior_art_url", "")})
        locs.append(entry)
    by_id = {l["id"]: l for l in locs}
    for npc in arc.get("cast") or []:
        if npc.get("acts") and act_no not in npc["acts"]:
            continue
        loc = by_id.get(npc.get("location"))
        if loc is None:
            continue  # its place is not present this act — the visitor waits too
        entry = {k: copy.deepcopy(v) for k, v in npc.items()
                 if k not in ("location", "acts", "secret")}
        entry.update({"_scenario": True, "vendor": False})
        loc["npcs"] = list(loc.get("npcs") or []) + [entry]
    out["locations"] = locs
    return out


def validate_arc(raw: Dict[str, Any], town: Dict[str, Any]) -> Dict[str, Any]:
    """§D17-6.1: title, villain, stakes, three act outlines each naming a
    questgiver location + NPC that exist in the town — or in the arc's own CAST
    (§D20-2: a scenario may bring its own questgiver to town)."""
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
    # §D20-2: the scenario's own people and places, validated before the act
    # outlines so a questgiver may be one of them.
    cast, places = _validate_cast_and_places(raw, town)
    cast_by_id = {c["id"]: c for c in cast}
    cast_by_name = {c["name"].lower(): c for c in cast}
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
        member = cast_by_id.get(qnpc) or cast_by_name.get(qnpc.lower())
        if found is None and member is not None:
            # A cast questgiver (§D20-2) — present every act they give quests in.
            if member["acts"] and i not in member["acts"]:
                raise ValueError(f"act {i}: questgiver '{member['name']}' is a cast "
                                 f"member who is not in town that act (acts {member['acts']})")
            found = ({"id": member["location"]}, member)
        if found is None:
            raise ValueError(f"act {i}: questgiver_npc '{qnpc}' is not an NPC of "
                             "this town or of the scenario's cast")
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
            if hf is None:
                m2 = cast_by_id.get(str(handoff)) or cast_by_name.get(str(handoff).lower())
                if m2 is not None:
                    hf = ({"id": m2["location"]}, m2)
            handoff_id = hf[1]["id"] if hf else None
        acts.append({
            "title": atitle, "hook": hook,
            "questgiver_location": loc["id"], "questgiver_npc": npc["id"],
            "handoff": handoff_id,
            "adventure_theme": theme,
            "tone_notes": str(act.get("tone_notes") or "").strip(),
        })
        del qloc  # the location is derived from the NPC (single source of truth)
    out = {"title": title, "villain": villain, "stakes": stakes, "acts": acts}
    if cast:
        out["cast"] = cast
    if places:
        out["places"] = places
    # The loot lexicon (§D17-4.5) is drawn in code when the scenario is made and
    # rides the arc from there on — validation carries it through untouched.
    lex = raw.get("loot_lexicon")
    if isinstance(lex, dict) and lex.get("forms"):
        out["loot_lexicon"] = copy.deepcopy(lex)
    return out


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
    if not isinstance(act1, dict) or not act1.get("materialization"):
        raise ValueError("a pre-generated scenario carries Act I's town materialization")
    # The Act I ADVENTURE is optional (§D20-3): a town-only scenario generates
    # the ride-out on quest accept, exactly as every later act does — so the
    # quest options stay real (only the one taken is ever written).
    if act1.get("adventure_id") and content.adventure_detail(str(act1["adventure_id"])) is None:
        raise ValueError(f"unknown adventure for Act I: {act1['adventure_id']}")
    cleaned = {
        "kind": "scenario",
        "title": arc["title"],
        "town_id": town_id,
        "town_name": town["name"],
        "arc": arc,
        # `quest_id`: WHICH of Act I's quest options the pre-written adventure
        # was written for. Take any other option and the run generates its own
        # (§D17-6.3) — the ride out follows the choice, not the other way round.
        "act1": {"adventure_id": str(act1["adventure_id"]),
                 "quest_id": str(act1.get("quest_id") or ""),
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
def _resolve_npc(town: Dict[str, Any], key: str
                 ) -> "Optional[tuple[Dict[str, Any], Dict[str, Any]]]":
    """An NPC by id, tolerating the writer naming them by display name."""
    found = find_npc(town, str(key))
    if found is not None:
        return found
    for loc in town.get("locations") or []:
        for npc in loc.get("npcs") or []:
            if npc.get("name", "").lower() == str(key).lower():
                return loc, npc
    return None


def _clean_quests(raw: Dict[str, Any]) -> List[Dict[str, str]]:
    """The act's quest OPTIONS (§D17-5.4): what the party may agree to this act.
    At least two — different problems to solve, different branches of the same
    trouble, or different ways to go at it — because the combat half of the act
    is not written until one is accepted, so the choice is free agency. A legacy
    single ``quest`` object is read as one option."""
    quests_raw = raw.get("quests")
    if not quests_raw and isinstance(raw.get("quest"), dict):
        quests_raw = [raw["quest"]]
    if not isinstance(quests_raw, list) or not quests_raw:
        raise ValueError("the act needs a quests list")
    if len(quests_raw) < MIN_QUEST_OPTIONS:
        raise ValueError(
            f"the act offers {len(quests_raw)} quest — the party must have at least "
            f"{MIN_QUEST_OPTIONS} to choose between (different troubles to answer, "
            "different branches of the same trouble, or different ways to go at it)")
    if len(quests_raw) > MAX_QUEST_OPTIONS:
        raise ValueError(f"the act offers more than {MAX_QUEST_OPTIONS} quests — trim it")
    quests: List[Dict[str, str]] = []
    seen: set = set()
    for i, q in enumerate(quests_raw, start=1):
        if not isinstance(q, dict):
            raise ValueError(f"quest {i} must be an object")
        title = str(q.get("title") or "").strip()
        text = str(q.get("text") or "").strip()
        if not title or not text:
            raise ValueError(f"quest {i} needs a title and text")
        qid = _slug(str(q.get("id") or title)) or f"quest_{i}"
        if qid in seen:
            qid = f"{qid}_{i}"
        seen.add(qid)
        quests.append({"id": qid, "title": title, "text": text,
                       # How THIS choice changes the ride out — required, and
                       # distinct per option (§D20-3): the options are REAL, so
                       # each names its own place and its own trouble, and the
                       # theme is what the adventure generator is handed.
                       "adventure_theme": str(q.get("adventure_theme") or "").strip()})
    themes = [q["adventure_theme"] for q in quests]
    if any(not t for t in themes):
        raise ValueError(
            "every quest option needs its own adventure_theme — one line naming "
            "the PLACE that option's ride-out happens in and what the party does "
            "there (the combat half is generated from it)")
    lowered = [t.lower() for t in themes]
    if len(set(lowered)) != len(lowered):
        raise ValueError(
            "two quest options share an adventure_theme — the options must be "
            "materially different rides (different places, different objectives), "
            "not the same dungeon approached twice")
    return quests


def _bind_quest_hooks(dialogues: Dict[str, Dict[str, Any]],
                      quests: List[Dict[str, str]]) -> None:
    """Resolve every ``grant_quest`` / ``defer_quest`` hook onto a real quest id
    (bare hooks bind to the only option; a title is tolerated for an id), and
    hold the two rules the town phase rests on:

    - every quest option has at least one ACCEPT choice somewhere in the act —
      one NPC may hold them all, or they may be spread across the town;
    - every node that offers an accept also offers a DEFER ("let us get back to
      you"), so the party is never cornered into agreeing to talk their way out.
    """
    by_id = {q["id"]: q for q in quests}
    by_title = {q["title"].lower(): q for q in quests}
    accepted: set = set()
    for npc_id, tree in dialogues.items():
        for nid, node in tree["nodes"].items():
            offers = False
            defers = False
            for ch in node["choices"]:
                kinds = {h["kind"] for h in ch["effects"]}
                for h in ch["effects"]:
                    if h["kind"] not in ("grant_quest", "defer_quest"):
                        continue
                    key = str(h.get("quest") or "")
                    q = by_id.get(_slug(key)) or by_title.get(key.lower())
                    if q is None:
                        if key:
                            raise ValueError(
                                f"{npc_id}: node '{nid}' choice '{ch['label']}' points at "
                                f"quest '{key}', which is not one of this act's quests "
                                f"({', '.join(sorted(by_id))})")
                        if len(quests) > 1 and h["kind"] == "grant_quest":
                            raise ValueError(
                                f"{npc_id}: node '{nid}' choice '{ch['label']}' accepts a quest "
                                "without saying which — put the option's id in the hook: "
                                '{"kind": "grant_quest", "quest": "<id>"}')
                        q = quests[0]
                        # A bare defer is just "not yet" — it names no option.
                        if h["kind"] == "defer_quest":
                            defers = True
                            continue
                    h["quest"] = q["id"]
                    if h["kind"] == "grant_quest":
                        if "unlock_adventure" not in kinds:
                            raise ValueError(
                                f"{npc_id}: node '{nid}' choice '{ch['label']}' grants a quest "
                                "without unlock_adventure — an acceptance carries both hooks")
                        offers = True
                        accepted.add(q["id"])
                    else:
                        defers = True
            if offers and not defers:
                raise ValueError(
                    f"{npc_id}: node '{nid}' offers the quest with no way to put the answer "
                    'off — add a choice with effects [{"kind": "defer_quest"}] '
                    '("Let us get back to you — we have business to see to first.")')
    missing = [q["title"] for q in quests if q["id"] not in accepted]
    if missing:
        raise ValueError("no one in town offers " + ", ".join(f'"{t}"' for t in missing)
                         + " — every quest option needs an accept choice carrying "
                           'grant_quest (with its id) and unlock_adventure')


def validate_materialization(raw: Dict[str, Any], town: Dict[str, Any],
                             act_outline: Dict[str, Any],
                             flags_known: Optional[set] = None) -> Dict[str, Any]:
    """``{quests: [{id, title, text, adventure_theme?}, …], arrival: str,
    dialogues: {npc_id: tree}, flavor: {npc_id: line}, topics: {npc_id:
    [{ask, reply}]}, reask: {npc_id: line}, accepted/declined/committed:
    {npc_id: line} (optional closing lines), stock?: {location_id: [...]}}``.

    The gates: at least two quest OPTIONS, each with an accept choice (a
    ``grant_quest`` + ``unlock_adventure`` pair) somewhere in the act's trees; a
    ``defer_quest`` out beside every offer; the outline's questgiver has a tree
    with a ``defeated_once``-gated branch written up front so a Normal-mode
    return re-offers the quest; and every NPC of the town has SOMETHING to say —
    a tree, a topic (theirs or the act's), or at least a greeting line."""
    from .dialogue import check_flag_consistency, validate_dialogue  # local: dialogue imports nothing here
    if not isinstance(raw, dict):
        raise ValueError("materialization must be an object")
    quests = _clean_quests(raw)
    arrival = str(raw.get("arrival") or "").strip()
    if not arrival:
        raise ValueError("materialization needs the arrival paragraph")
    dialogues_raw = raw.get("dialogues") or {}
    if not isinstance(dialogues_raw, dict):
        raise ValueError("dialogues must be a map of npc id → tree")
    dialogues: Dict[str, Dict[str, Any]] = {}
    for npc_id, tree in dialogues_raw.items():
        found = _resolve_npc(town, str(npc_id))
        if found is None:
            raise ValueError(f"dialogue for unknown NPC '{npc_id}'")
        try:
            dialogues[found[1]["id"]] = validate_dialogue(tree)
        except ValueError as exc:
            raise ValueError(f"dialogue for {found[1]['name']}: {exc}") from exc
    qnpc = act_outline.get("questgiver_npc")
    if qnpc not in dialogues:
        raise ValueError(f"the questgiver ({qnpc}) has no dialogue tree")
    # The narration floor (beta playtest): dialogue that only ever SPEAKS reads
    # as a chat log — every physical fact (the splinted arm, the drawn seam)
    # stays invisible, and the player can't follow who is doing what. A tree of
    # any real size must carry unvoiced beats; the questgiver's — the act's
    # storytelling spine — must carry at least two.
    for npc_id, tree in dialogues.items():
        nodes = tree["nodes"]
        if len(nodes) < 4:
            continue  # a greeting tree may be all voice
        beats = sum(1 for n in nodes.values() if n.get("speaker") == "narration")
        need = 2 if npc_id == qnpc else 1
        if beats < need:
            found = _resolve_npc(town, npc_id)
            name = found[1]["name"] if found else npc_id
            raise ValueError(
                f"dialogue for {name} has {beats} narration node(s) across "
                f"{len(nodes)} nodes — it needs at least {need}. Narration "
                'nodes ({"speaker": "narration"}) are stage directions: what '
                "the NPC does with their hands, what the party notices, what a "
                "name just used refers to. Put one after each major reveal so "
                "the scene reads like a novel, not a transcript")
    _bind_quest_hooks(dialogues, quests)
    flavor: Dict[str, str] = {}
    for npc_id, line in (raw.get("flavor") or {}).items():
        found = _resolve_npc(town, str(npc_id))
        if found and str(line or "").strip():
            flavor[found[1]["id"]] = str(line).strip()
    topics: Dict[str, List[Dict[str, str]]] = {}
    for npc_id, rows in (raw.get("topics") or {}).items():
        found = _resolve_npc(town, str(npc_id))
        if found is None:
            continue
        cleaned = clean_topics(rows, f"act topics for {found[1]['name']}")
        if cleaned:
            topics[found[1]["id"]] = cleaned
    def _npc_lines(key: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        rows = raw.get(key) or {}
        if not isinstance(rows, dict):
            return out
        for npc_id, line in rows.items():
            found = _resolve_npc(town, str(npc_id))
            if found and str(line or "").strip():
                out[found[1]["id"]] = str(line).strip()
        return out
    reask = _npc_lines("reask")
    # The questgiver's closing lines (optional, defaults in the run): what
    # they say when the party accepts, when the party puts it off, and when
    # the party is already sworn to another offer this act.
    accepted = _npc_lines("accepted")
    declined = _npc_lines("declined")
    committed = _npc_lines("committed")
    # §D20-1: every flag gating a choice or an act topic must be reachable —
    # standing, already true in the run, or settable by a hook in these trees.
    gated_topics: set = set()
    for rows in topics.values():
        for row in rows:
            gated_topics.update(row.get("requires") or [])
    problems = check_flag_consistency(dialogues, gated_topics,
                                      set(flags_known or ()))
    if problems:
        raise ValueError("; ".join(problems))
    # Nobody in town is a closed door: every resident answers with a tree, a
    # topic of their own, the act's topics, or at least a greeting line.
    silent = [npc["name"] for loc in town.get("locations") or [] for npc in loc.get("npcs") or []
              if npc["id"] not in dialogues and npc["id"] not in topics
              and npc["id"] not in flavor and not (npc.get("topics") or [])]
    if silent:
        raise ValueError("these townsfolk have nothing to say this act: "
                         + ", ".join(silent)
                         + " — give each one a line in \"flavor\" or an exchange in \"topics\"")
    return {
        "quests": quests,
        # Legacy readers (and the journal before a choice is made) see the first.
        "quest": {"title": quests[0]["title"], "text": quests[0]["text"]},
        "arrival": arrival,
        "dialogues": dialogues,
        "flavor": flavor,
        "topics": topics,
        "reask": reask,
        "accepted": accepted,
        "declined": declined,
        "committed": committed,
        "stock": copy.deepcopy(raw.get("stock") or {}),
    }
