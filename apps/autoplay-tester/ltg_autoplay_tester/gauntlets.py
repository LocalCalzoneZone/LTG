"""Gauntlets (§D13-2) — the versioned encounter sets probes run against.

A gauntlet is a directory under ``data/gauntlets/<id>/`` holding encounter
JSONs and a ``manifest.json``. Its **content hash** covers every listed file:
verdicts stamp it, and two verdicts compare only when hashes match (the
content is part of the measuring stick).

Generated gauntlets are minted through the game server's LLM machinery with
``persist=False`` — the same validation gate, but nothing enters the game's
scan directories (the quarantine, §D13-2.3). ``promote`` copies a keeper into
the game through ``content.save_encounter`` when it earns it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ltg_game_server import content as game_content
from ltg_game_server import llm as game_llm

APP_ROOT = Path(__file__).resolve().parent.parent          # apps/autoplay-tester
DATA_DIR = APP_ROOT / "data"
GAUNTLET_DIR = DATA_DIR / "gauntlets"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "gauntlet"


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def gauntlet_hash(gdir: Path, manifest: Dict[str, Any]) -> str:
    """Stable hash over the manifest and every file it lists, in name order."""
    h = hashlib.sha256()
    h.update(json.dumps(manifest, sort_keys=True).encode("utf-8"))
    names = list(manifest.get("encounters", []))
    if manifest.get("sparring_partner"):
        names.append(manifest["sparring_partner"])
    for name in sorted(names):
        p = gdir / name
        if p.exists():
            h.update(name.encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def list_gauntlets() -> List[Dict[str, Any]]:
    out = []
    if not GAUNTLET_DIR.is_dir():
        return out
    for mpath in sorted(GAUNTLET_DIR.glob("*/manifest.json")):
        try:
            manifest = _read(mpath)
        except (json.JSONDecodeError, OSError):
            continue
        gdir = mpath.parent
        out.append({
            "id": gdir.name,
            "name": manifest.get("name", gdir.name),
            "created": manifest.get("created", ""),
            "frozen": bool(manifest.get("frozen", False)),
            "generated": bool(manifest.get("generated", False)),
            "encounters": len(manifest.get("encounters", [])),
            "has_adventure": bool(manifest.get("adventure")),
            "hash": gauntlet_hash(gdir, manifest),
            "notes": manifest.get("notes", ""),
        })
    return out


def load_gauntlet(gauntlet_id: str) -> Dict[str, Any]:
    """The full gauntlet: manifest fields, hash, encounter dicts (in manifest
    order), the inline-acts adventure (assembled from act_files), and the
    sparring-partner loadout if the manifest names one."""
    gdir = GAUNTLET_DIR / gauntlet_id
    mpath = gdir / "manifest.json"
    if not mpath.exists():
        raise ValueError(f"unknown gauntlet: {gauntlet_id}")
    manifest = _read(mpath)
    encounters = []
    for name in manifest.get("encounters", []):
        enc = _read(gdir / name)
        enc.setdefault("name", Path(name).stem)
        enc["_file"] = name
        encounters.append(enc)
    adventure = None
    adv = manifest.get("adventure")
    if isinstance(adv, dict) and adv.get("act_files"):
        adventure = {"name": adv.get("name", "Adventure"),
                     "acts": [_read(gdir / n) for n in adv["act_files"]]}
    partner = None
    if manifest.get("sparring_partner"):
        partner = _read(gdir / manifest["sparring_partner"])
    return {
        "id": gauntlet_id,
        "name": manifest.get("name", gauntlet_id),
        "hash": gauntlet_hash(gdir, manifest),
        "frozen": bool(manifest.get("frozen", False)),
        "generated": bool(manifest.get("generated", False)),
        "encounters": encounters,
        "adventure": adventure,
        "sparring_partner": partner,
        "manifest": manifest,
        "dir": str(gdir),
    }


def baseline_gauntlet_id() -> Optional[str]:
    """The newest frozen baseline (baseline-1, baseline-2, …), or None."""
    baselines = sorted(g["id"] for g in list_gauntlets()
                       if g["frozen"] and g["id"].startswith("baseline-"))
    return baselines[-1] if baselines else None


def generate_gauntlet(name: str, character_ids: List[str], count: int = 4,
                      difficulty: str = "standard", note: str = "") -> Dict[str, Any]:
    """Mint a generated gauntlet: `count` encounters through the game server's
    generator (same repair loop + engine gate, ``persist=False`` so nothing
    touches the game's picker), written under data/gauntlets/. Returns the
    gauntlet summary. Raises ValueError on LLM/config failures."""
    gid = _slug(name)
    gdir = GAUNTLET_DIR / gid
    if (gdir / "manifest.json").exists():
        raise ValueError(f"gauntlet '{gid}' already exists — pick a new name "
                         "(gauntlets are immutable once minted)")
    encounters: List[Dict[str, Any]] = []
    for i in range(max(1, count)):
        enc = game_llm.generate_encounter(
            character_ids, difficulty=difficulty,
            note=(note + f" (set piece {i + 1} of {count})").strip(),
            persist=False)
        encounters.append(enc)
    gdir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, enc in enumerate(encounters, start=1):
        fname = f"{i:02d}_{_slug(enc.get('name', f'encounter-{i}'))}.json"
        (gdir / fname).write_text(json.dumps(enc, indent=2) + "\n")
        files.append(fname)
    manifest = {
        "name": name, "created": _today(), "frozen": True, "generated": True,
        "notes": f"LLM-minted test gauntlet ({difficulty}"
                 + (f"; note: {note}" if note else "") + "). Quarantined — "
                 "never in the game's picker unless promoted.",
        "encounters": files,
    }
    (gdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return next(g for g in list_gauntlets() if g["id"] == gid)


def promote_encounter(gauntlet_id: str, encounter_file: str) -> Dict[str, Any]:
    """Copy one gauntlet encounter into the game through the normal authored-
    content gate (`content.save_encounter`) — the explicit exit from quarantine."""
    gdir = GAUNTLET_DIR / gauntlet_id
    path = gdir / encounter_file
    if not path.exists():
        raise ValueError(f"unknown encounter file: {gauntlet_id}/{encounter_file}")
    enc = _read(path)
    enc.pop("_file", None)
    return game_content.save_encounter(enc)


def _today() -> str:
    import datetime
    return datetime.date.today().isoformat()
