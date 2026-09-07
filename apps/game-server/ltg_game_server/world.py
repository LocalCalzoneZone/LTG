"""The worldbook — the shared, append-only book of what a traveller knows
about each town and region (Design Update 24 §D24-8.3).

Built like towns: a tracked content directory, ``content/world/``, holding one
JSON per entry plus a ``regions.json``. It sits BESIDE the campaign ladder, not
on it: every campaign reads it, and every town generation appends to it. The
rules that keep it useful:

- **Every town has an entry.** ``generate_town`` writes one in the same call;
  a town without an entry is a validation warning in Options → World, never a
  crash — the writers simply get no neighbours for it.
- **Neighbours are symmetric** and written on the newer town: ``append_entry``
  adds the reverse edge onto each named neighbour.
- **A region is named once.** A new town joins an existing region or founds
  one (the founding call carries the region's gist).
- **The book is brief on purpose.** What Karzum IS lives here; what happened
  there lives on the campaign (§D24-8.2 town state). Nobody ever receives the
  whole book: the act writer gets the current town's entry, the arc writer
  and the interlude planner add the neighbours' one-liners, the town
  generator gets the region and the neighbours it is placed beside.

Entry shape::

    {"kind": "world_entry", "town_id": "karzum", "name": "Karzum",
     "region_id": "kholdrun_reach", "gist": "one paragraph",
     "notable": ["Poppy, keeper of the Kettle and Anvil", …],
     "neighbours": [{"town_id": "nalindor", "how": "three days north by the Greatway"}],
     "added_by": "generate_town | import | backfill | scenario:<id>"}

    regions.json: {"regions": [{"id", "name", "gist"}, …]}
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import content

WORLD_DIR = content.CONTENT_DIR / "world"
REGIONS_FILE = "regions.json"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_NOTABLE = 6
MAX_NEIGHBOURS = 4
# A gist is "what a traveller knows" — one paragraph, never a history.
MAX_GIST_WORDS = 160


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", (text or "").lower()).strip("_")[:60]


def _dir() -> Path:
    # Read through the module attribute so tests may repoint it.
    return WORLD_DIR


def _read(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _write(path: Path, raw: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Regions
# --------------------------------------------------------------------------- #
def regions() -> List[Dict[str, Any]]:
    raw = _read(_dir() / REGIONS_FILE) or {}
    out: List[Dict[str, Any]] = []
    for r in raw.get("regions") or []:
        if isinstance(r, dict) and r.get("id"):
            out.append({"id": str(r["id"]), "name": str(r.get("name") or r["id"]),
                        "gist": str(r.get("gist") or "")})
    return out


def region_for(region_id: str) -> Optional[Dict[str, Any]]:
    return next((r for r in regions() if r["id"] == region_id), None)


def _write_regions(rows: List[Dict[str, Any]]) -> None:
    _write(_dir() / REGIONS_FILE, {"regions": rows})


def add_region(region: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    """Found a region (idempotent by id: an existing one is kept unless
    ``force``). Returns the stored row."""
    row = validate_region(region)
    rows = regions()
    for i, r in enumerate(rows):
        if r["id"] == row["id"]:
            if force:
                rows[i] = row
                _write_regions(rows)
            return rows[i]
    rows.append(row)
    _write_regions(rows)
    return row


def validate_region(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("a region must be an object with id, name and gist")
    name = str(raw.get("name") or "").strip()
    rid = _slug(str(raw.get("id") or name))
    if not rid or not name:
        raise ValueError("a region needs a name (and an id)")
    gist = str(raw.get("gist") or "").strip()
    if not gist:
        raise ValueError(f"region '{name}' needs a gist — one paragraph on climate, peoples, what the land is known for")
    return {"id": rid, "name": name, "gist": gist}


# --------------------------------------------------------------------------- #
# Entries
# --------------------------------------------------------------------------- #
def validate_entry(raw: Any, town_id: str = "", known_towns: Optional[set] = None) -> Dict[str, Any]:
    """Clean one entry. ``known_towns`` (when given) is the set of town ids a
    neighbour may name — the book's own entries plus the town being added; an
    unknown neighbour is refused, because a dangling edge is a road to
    nowhere. Raises ValueError with a human message."""
    if not isinstance(raw, dict):
        raise ValueError("world entry must be an object")
    tid = _slug(str(raw.get("town_id") or town_id or ""))
    if not tid:
        raise ValueError("world entry needs a town_id")
    name = str(raw.get("name") or "").strip() or tid.replace("_", " ").title()
    gist = str(raw.get("gist") or "").strip()
    if not gist:
        raise ValueError(f"world entry for {name} needs a gist — one paragraph on what a traveller knows of the place")
    words = gist.split()
    if len(words) > MAX_GIST_WORDS:
        gist = " ".join(words[:MAX_GIST_WORDS])
    region_id = _slug(str(raw.get("region_id") or ""))
    new_region = raw.get("new_region")
    if isinstance(new_region, dict) and new_region:
        region = validate_region(new_region)
        region_id = region["id"]
    else:
        region = None
    if not region_id:
        raise ValueError(f"world entry for {name} needs a region_id (or a new_region to found)")
    notable_raw = raw.get("notable") or []
    if not isinstance(notable_raw, list):
        raise ValueError("notable must be a list of short lines")
    notable = [str(n).strip() for n in notable_raw if str(n).strip()][:MAX_NOTABLE]
    neighbours: List[Dict[str, str]] = []
    seen: set = set()
    for n in (raw.get("neighbours") or [])[:MAX_NEIGHBOURS]:
        if isinstance(n, str):
            n = {"town_id": n, "how": ""}
        if not isinstance(n, dict):
            raise ValueError("each neighbour is {town_id, how}")
        nid = _slug(str(n.get("town_id") or n.get("id") or n.get("name") or ""))
        if not nid or nid == tid or nid in seen:
            continue
        if known_towns is not None and nid not in known_towns:
            raise ValueError(f"neighbour '{nid}' is not a town in the worldbook "
                             f"(known: {', '.join(sorted(known_towns)) or 'none'})")
        seen.add(nid)
        neighbours.append({"town_id": nid, "how": str(n.get("how") or "").strip()})
    out: Dict[str, Any] = {
        "kind": "world_entry",
        "town_id": tid,
        "name": name,
        "region_id": region_id,
        "gist": gist,
        "notable": notable,
        "neighbours": neighbours,
        "added_by": str(raw.get("added_by") or "import"),
    }
    if region is not None:
        out["new_region"] = region
    return out


def _entry_path(town_id: str) -> Path:
    return _dir() / f"{_slug(town_id)}.json"


def list_entries() -> List[Dict[str, Any]]:
    d = _dir()
    if not d.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        if p.name == REGIONS_FILE:
            continue
        raw = _read(p)
        if raw is None or raw.get("kind") != "world_entry":
            continue
        out.append(copy.deepcopy(raw))
    return out


def entry_for(town_id: str) -> Optional[Dict[str, Any]]:
    raw = _read(_entry_path(town_id))
    if raw is None or raw.get("kind") != "world_entry":
        return None
    return copy.deepcopy(raw)


def neighbours_of(town_id: str) -> List[Dict[str, Any]]:
    """The entries this town sits near, each with the ``how`` of the road
    between them (from either side's edge)."""
    me = entry_for(town_id)
    if me is None:
        return []
    out: List[Dict[str, Any]] = []
    for n in me.get("neighbours") or []:
        other = entry_for(n["town_id"])
        if other is not None:
            out.append({**other, "how": n.get("how", "")})
    return out


def append_entry(entry: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    """Add an entry to the book: validates, founds a new region if the entry
    carries one, writes the entry, and writes the REVERSE neighbour edge onto
    each named neighbour (§D24-8.3). Refuses to overwrite an existing entry
    unless ``force`` (the book is append-only in play; Options → World edits
    pass ``force``). Returns the stored entry."""
    known = {e["town_id"] for e in list_entries()}
    cleaned = validate_entry(entry, known_towns=known | {_slug(str(entry.get("town_id") or ""))})
    if cleaned["town_id"] in known and not force:
        raise ValueError(f"the worldbook already has an entry for {cleaned['town_id']}")
    new_region = cleaned.pop("new_region", None)
    if new_region is not None:
        add_region(new_region)
    elif region_for(cleaned["region_id"]) is None:
        # A region named but never founded: found it with an empty gist so
        # the book stays consistent; the editor can fill it in.
        add_region({"id": cleaned["region_id"], "name": cleaned["region_id"].replace("_", " ").title(),
                    "gist": "(unwritten)"})
    _write(_entry_path(cleaned["town_id"]), cleaned)
    for n in cleaned["neighbours"]:
        other = entry_for(n["town_id"])
        if other is None:
            continue
        edges = list(other.get("neighbours") or [])
        if not any(e.get("town_id") == cleaned["town_id"] for e in edges):
            edges.append({"town_id": cleaned["town_id"], "how": n.get("how", "")})
            other["neighbours"] = edges[:MAX_NEIGHBOURS + 2]
            _write(_entry_path(other["town_id"]), other)
    return cleaned


def update_entry(town_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Options → World: edit gist / notable / neighbours / region of an
    existing entry (or create one by hand for a town without one)."""
    current = entry_for(town_id) or {"town_id": town_id, "added_by": "import"}
    merged = {**current, **{k: v for k, v in patch.items() if k in
                            ("name", "region_id", "new_region", "gist", "notable", "neighbours")}}
    merged["town_id"] = town_id
    return append_entry(merged, force=True)


def remove_entry(town_id: str) -> None:
    p = _entry_path(town_id)
    if p.is_file():
        p.unlink()
    for other in list_entries():
        edges = [e for e in other.get("neighbours") or [] if e.get("town_id") != _slug(town_id)]
        if len(edges) != len(other.get("neighbours") or []):
            other["neighbours"] = edges
            _write(_entry_path(other["town_id"]), other)


# --------------------------------------------------------------------------- #
# Views for the writers and the client
# --------------------------------------------------------------------------- #
def context_for(town_id: str) -> Dict[str, Any]:
    """What a writer may see of the book for one town: its entry, its region
    and its neighbours (one line each). Never the whole book."""
    entry = entry_for(town_id)
    if entry is None:
        return {"entry": None, "region": None, "neighbours": []}
    return {"entry": entry, "region": region_for(entry["region_id"]),
            "neighbours": neighbours_of(town_id)}


def placement_context(anchor_town_id: str = "", region_id: str = "") -> Dict[str, Any]:
    """What the town generator gets when a town is placed (§D24-9.1): the
    region it joins (or "found one"), and the known towns it sits beside —
    the anchor and the anchor's neighbours."""
    anchor = entry_for(anchor_town_id) if anchor_town_id else None
    rid = region_id or (anchor["region_id"] if anchor else "")
    region = region_for(rid) if rid else None
    beside: List[Dict[str, Any]] = []
    if anchor is not None:
        beside.append(anchor)
        for n in neighbours_of(anchor_town_id):
            if n["town_id"] not in {b["town_id"] for b in beside}:
                beside.append(n)
    return {"region": region, "anchor_town_id": anchor_town_id if anchor else "",
            "neighbours": beside, "known_towns": sorted(e["town_id"] for e in list_entries())}


def overview() -> Dict[str, Any]:
    """Options → World: regions with their towns, plus the towns that have no
    entry yet (a warning row, not an error)."""
    from . import scenario_content as sc
    entries = list_entries()
    by_region: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        by_region.setdefault(e["region_id"], []).append(e)
    rows = []
    for r in regions():
        rows.append({**r, "towns": by_region.pop(r["id"], [])})
    for rid, towns in by_region.items():   # entries naming an unfounded region
        rows.append({"id": rid, "name": rid.replace("_", " ").title(), "gist": "", "towns": towns})
    have = {e["town_id"] for e in entries}
    missing = [{"id": t["id"], "name": t["name"]} for t in sc.list_towns() if t["id"] not in have]
    return {"regions": rows, "missing": missing,
            "towns": [{"town_id": e["town_id"], "name": e["name"]} for e in entries]}
