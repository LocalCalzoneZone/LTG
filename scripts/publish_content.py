#!/usr/bin/env python3
"""Promote locally saved encounters / adventures into the tracked content dir.

The game saves everything you author into the gitignored user-data dir
(apps/deckbuilder/loadouts). This script moves the shareable pieces —
encounter and adventure JSON plus their generated art — into content/ (and
content/art/), where git tracks them, so a commit + push ships them to every
install. Characters, settings, and hidden-id files are never touched.

Usage (from the repo root):
    python scripts/publish_content.py            # list what's publishable
    python scripts/publish_content.py --all      # publish everything listed
    python scripts/publish_content.py <id> ...   # publish specific ids
                                                 # (an adventure brings its acts)

After publishing, review with `git status`, then commit.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
LOADOUTS_DIR = REPO_ROOT / "apps" / "deckbuilder" / "loadouts"
CONTENT_DIR = REPO_ROOT / "content"
USER_ART_DIR = LOADOUTS_DIR / "art"
CONTENT_ART_DIR = CONTENT_DIR / "art"

# Per-install bookkeeping that must never leave the machine (llm_settings holds
# the API key). These are excluded by shape anyway; the list is belt-and-braces.
_NEVER = {"llm_settings.json", "hidden.json", "encounters_hidden.json",
          "adventures_hidden.json"}


def _kind(raw: Dict) -> Optional[str]:
    """"encounter" / "adventure" for shareable files, None for everything else
    (characters have "character", settings files have neither shape)."""
    if raw.get("kind") == "adventure" and isinstance(raw.get("acts"), list):
        return "adventure"
    if isinstance(raw.get("enemies"), list) and "party" not in raw and "character" not in raw:
        return "encounter"
    return None


def _publishable() -> Dict[str, str]:
    """id -> kind for every shareable JSON currently in the user-data dir."""
    out: Dict[str, str] = {}
    if not LOADOUTS_DIR.is_dir():
        return out
    for p in sorted(LOADOUTS_DIR.glob("*.json")):
        if p.name in _NEVER:
            continue
        try:
            raw = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        k = _kind(raw) if isinstance(raw, dict) else None
        if k:
            out[p.stem] = k
    return out


def _act_ids(adventure_id: str) -> List[str]:
    try:
        raw = json.loads((LOADOUTS_DIR / f"{adventure_id}.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [str(a["encounter_id"]) for a in raw.get("acts", [])
            if isinstance(a, dict) and a.get("encounter_id")]


def _move_art(content_id: str) -> bool:
    """Merge loadouts/art/<id> into content/art/<id>. A moved file replaces any
    older file for the same slot (slot-<token>.<ext> — the token varies per
    regeneration), so re-publishing doesn't accumulate stale images."""
    src = USER_ART_DIR / content_id
    if not src.is_dir():
        return False
    dst = CONTENT_ART_DIR / content_id
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        slot = f.name.rsplit("-", 1)[0]
        for old in dst.glob(f"{slot}-*.*"):
            old.unlink()
        shutil.move(str(f), str(dst / f.name))
    shutil.rmtree(src, ignore_errors=True)
    return True


def publish(content_id: str, kind: str) -> None:
    ids = [content_id] + (_act_ids(content_id) if kind == "adventure" else [])
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    for cid in ids:
        src = LOADOUTS_DIR / f"{cid}.json"
        moved_json = src.is_file()
        if moved_json:
            shutil.move(str(src), str(CONTENT_DIR / f"{cid}.json"))
        moved_art = _move_art(cid)
        if moved_json or moved_art:
            what = " + art" if moved_art else ""
            print(f"  published {cid}.json{what}")


def main(argv: List[str]) -> int:
    table = _publishable()
    if not argv:
        if not table:
            print("Nothing to publish — no encounters or adventures in "
                  f"{LOADOUTS_DIR.relative_to(REPO_ROOT)}.")
            return 0
        print("Publishable (run again with --all, or pass ids):")
        for cid, kind in table.items():
            print(f"  {cid}  ({kind})")
        return 0

    wanted = list(table) if argv == ["--all"] else argv
    unknown = [w for w in wanted if w not in table]
    if unknown:
        print(f"error: not publishable (unknown id, or not an encounter/adventure): "
              f"{', '.join(unknown)}", file=sys.stderr)
        return 1
    # Adventures first so their acts move through the adventure path (with art).
    for cid in sorted(wanted, key=lambda c: table[c] != "adventure"):
        if (LOADOUTS_DIR / f"{cid}.json").is_file():
            publish(cid, table[cid])
    print("Done. Review with `git status`, then commit to share.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
