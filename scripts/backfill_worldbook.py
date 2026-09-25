"""Backfill the worldbook (Design Update 24 §D24-8.3, §B.6).

For each town under ``content/towns`` without a worldbook entry, one short
LLM call over the town file returns ONLY the ``world_entry`` (region — joined
or founded — gist, notable names, neighbours among the towns already in the
book). The entry is written through ``world.append_entry`` and printed for
review. Idempotent: towns that already have an entry are skipped, so the
script can be re-run after a hand edit or a failed call.

Run once from the repo root (needs an OpenRouter key in Options → LLM):

    .venv/bin/python scripts/backfill_worldbook.py            # every town
    .venv/bin/python scripts/backfill_worldbook.py karzum     # one town
    .venv/bin/python scripts/backfill_worldbook.py --dry-run  # print the prompts only
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from ltg_game_server import llm, scenario_content as sc, world

BACKFILL_INSTRUCTIONS = r"""
You write ONE PAGE of the WORLDBOOK for LTG, a painterly tactical fantasy card
game: the shared book of what a traveller knows about each town. You are given
an existing town (its people and places) and the book as it stands (regions and
the towns already in it). Return ONLY JSON.

TONE:
%TONE%

%CONCRETE%

Write the town's "world_entry":
- "region_id": the id of an EXISTING region this town belongs to, OR
  "new_region": {"id": snake_case, "name", "gist": one paragraph — climate,
  peoples, what the land is known for}. Found a region only when none of the
  existing ones fits the town's own region_flavor.
- "gist": ONE paragraph — what a traveller knows of this place: what it is,
  what it makes, what it is known for. No history, no politics beyond a
  sentence, NO plot. Brief on purpose.
- "notable": 2–4 short lines a traveller would have heard of (a person, a
  landmark, a trade), drawn from the town file.
- "neighbours": 0–2 of the towns ALREADY IN THE BOOK (their ids exactly), each
  with "how": one line on the road between. Prefer towns whose regions could
  plausibly border this one; leave it empty if nothing fits. Never invent one.

Output contract:
{"world_entry": {"region_id": "<id>" | "new_region": {"id": "...", "name": "...", "gist": "..."},
                 "gist": "...", "notable": ["..."], "neighbours": [{"town_id": "...", "how": "..."}]}}
"""


def _book_block() -> str:
    lines = ["# THE BOOK SO FAR"]
    regs = world.regions()
    if regs:
        lines.append("Regions:")
        for r in regs:
            lines.append(f'- [{r["id"]}] {r["name"]} — {r["gist"]}')
    else:
        lines.append("Regions: none yet — you will found the first.")
    entries = world.list_entries()
    if entries:
        lines.append("Towns in the book:")
        for e in entries:
            lines.append(f'- [{e["town_id"]}] {e["name"]} (region {e["region_id"]}): {e["gist"]}')
    else:
        lines.append("Towns in the book: none yet.")
    return "\n".join(lines)


def prompt_for(town: Dict[str, Any]) -> str:
    return "\n\n".join([llm._town_block(town, topics=False), _book_block(),
                        "Write this town's world_entry now. Return ONLY the JSON."])


def backfill(town_ids: List[str], dry_run: bool = False) -> List[Dict[str, Any]]:
    written: List[Dict[str, Any]] = []
    for tid in town_ids:
        if world.entry_for(tid) is not None:
            print(f"[skip] {tid}: already in the book")
            continue
        town = sc.town_detail(tid)
        if town is None:
            print(f"[skip] {tid}: no such town")
            continue
        user = prompt_for(town)
        if dry_run:
            print(f"\n===== {tid} =====\n{user}\n")
            continue
        known = {e["town_id"] for e in world.list_entries()}

        def fix(raw: Dict[str, Any], _tid: str = tid, _town: Dict[str, Any] = town) -> Dict[str, Any]:
            entry = raw.get("world_entry") if isinstance(raw.get("world_entry"), dict) else raw
            return world.validate_entry({**entry, "town_id": _tid, "name": _town["name"],
                                         "added_by": "backfill"}, known_towns=known | {_tid})

        entry = llm._scenario_chat(BACKFILL_INSTRUCTIONS.replace("%VOICE%", ""), user, 3, fix,
                                   "world entry", task="towns")
        stored = world.append_entry(entry)
        written.append(stored)
        print(f"\n===== {tid} =====\n{json.dumps(stored, indent=2, ensure_ascii=False)}\n")
    return written


def main(argv: List[str]) -> int:
    dry = "--dry-run" in argv
    ids = [a for a in argv if not a.startswith("--")]
    if not ids:
        ids = [t["id"] for t in sc.list_towns()]
    backfill(ids, dry_run=dry)
    missing = [t["id"] for t in sc.list_towns() if world.entry_for(t["id"]) is None]
    if missing and not dry:
        print("still without an entry: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
