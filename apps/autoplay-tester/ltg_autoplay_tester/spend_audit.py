"""The Update 17 spend-audit (§D17-2.2, Phase 0 gate): do the four level-up
spend plans stay within the T-74 band of each other on the T-79 price curve
across the levels a scenario actually walks?

The bench's per-character spend audit (probes.py) plays ONE three-phase
adventure — levels 1 → 3. A scenario chains adventures, so this harness chains
the baseline gauntlet's adventure ``stages`` times on one loadout: earned
points carry (levels derive from them, T-78), the leveled build carries, HP
refills between adventures (the inn), and every phase level-up is spent by the
plan. Enemy pressure climbs per stage so a leveled party still meets a fight
(the fixtures are fixed-level; without the climb every stage past the first
saturates at the ceiling).

Usage (from the repo root)::

    .venv/bin/python -m ltg_autoplay_tester.spend_audit [--seeds 8] [--stages 3]

Prints a per-stage table: plan → win rate, and the max plan-vs-plan spread
against the T-74 band (OVER_PP). This is a diagnostic, not a verdict.
"""

from __future__ import annotations

import argparse
import copy
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

import ltg_core.schema as schema
from ltg_combat.autoplay.policies import SPEND_PLANS, make_policy
from ltg_combat.autoplay.runner import run_adventure

from .gauntlets import baseline_gauntlet_id, load_gauntlet
from .probes import OVER_PP, POLICY, _apply_pressure

REPO = Path(__file__).resolve().parents[3]
LOADOUTS = REPO / "apps" / "deckbuilder" / "loadouts"

# Pressure per stage: the base ladder × a per-stage climb so a level-5 party
# (stage 3) still meets resistance from the level-1..3 fixtures.
BASE_LADDER = tuple(round(0.4 + 0.2 * i, 1) for i in range(9))   # 0.4–2.0
STAGE_CLIMB = (1.0, 1.6, 2.2, 2.8, 3.4, 4.0)


def _chain(args: Tuple[Dict[str, Any], Dict[str, Any], str, float, int, int, str, Dict[str, Any]]
           ) -> List[Tuple[int, int, int]]:
    """One chain: (loadout, adventure, plan, mult, seed, stages, cid, curve) →
    per-stage (stage, won, level_after). ``curve`` overrides PRICE_CURVE entries
    for a what-if (applied in the worker — the pool spawns fresh interpreters)."""
    loadout, adventure, plan, mult, seed, stages, _cid, curve = args
    for stat, prices in (curve or {}).items():
        schema.PRICE_CURVE[stat] = tuple(prices)
    lo = copy.deepcopy(loadout)
    policy = make_policy(POLICY, plan)
    out = []
    for stage in range(1, stages + 1):
        m = mult * STAGE_CLIMB[min(stage, len(STAGE_CLIMB)) - 1]
        adv = {"name": adventure.get("name", "adventure"),
               "phases": [_apply_pressure(p, m) for p in adventure["phases"]]}
        rec = run_adventure(adv, [lo], policy, seed * 1000 + stage)
        won = rec["result"] == "victory"
        if rec.get("final_builds"):
            lo["character"] = rec["final_builds"][0]  # the leveled build carries
        out.append((stage, 1 if won else 0, int(lo["character"].get("level", 1))))
        if not won:
            # A lost adventure ends the chain for this seed (a Normal-mode
            # scenario would re-run it; for the audit the plan's rate at later
            # stages counts the loss forward — a plan that dies early stays dead).
            for later in range(stage + 1, stages + 1):
                out.append((later, 0, int(lo["character"].get("level", 1))))
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--stages", type=int, default=3)
    ap.add_argument("--chars", nargs="*", default=None,
                    help="loadout stems (default: every non-legacy loadout)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--curve", default=None,
                    help='what-if T-79 override, JSON: {"power": [15,15,20,25,30]}')
    args = ap.parse_args()
    curve = json.loads(args.curve) if args.curve else {}
    for stat, prices in curve.items():
        schema.PRICE_CURVE[stat] = tuple(prices)
    print("price curve:", {k: list(v) for k, v in schema.PRICE_CURVE.items()})

    g = load_gauntlet(baseline_gauntlet_id())
    adventure = g["adventure"]
    loadouts: Dict[str, Dict[str, Any]] = {}
    for path in sorted(LOADOUTS.glob("*.json")):
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict) or "character" not in raw:
            continue  # hidden lists, encounters, adventures
        ch = raw.get("character") or {}
        if "archetype" in ch or ch.get("legacy"):
            continue
        if args.chars and path.stem not in args.chars:
            continue
        loadouts[path.stem] = raw
    if not loadouts:
        raise SystemExit("no loadouts found under apps/deckbuilder/loadouts")

    tasks = [(lo, adventure, plan, mult, seed, args.stages, cid, curve)
             for cid, lo in loadouts.items()
             for plan in SPEND_PLANS
             for mult in BASE_LADDER
             for seed in range(args.seeds)]
    print(f"gauntlet {baseline_gauntlet_id()} · {len(loadouts)} characters · "
          f"{len(SPEND_PLANS)} plans · {len(BASE_LADDER)} pressures · "
          f"{args.seeds} seeds · {args.stages} stages → {len(tasks)} chains")

    # plan -> stage -> [wins, runs]; also per character for the footnote.
    tally: Dict[str, Dict[int, List[int]]] = {
        p: {s: [0, 0] for s in range(1, args.stages + 1)} for p in SPEND_PLANS}
    per_char: Dict[str, Dict[str, List[int]]] = {
        cid: {p: [0, 0] for p in SPEND_PLANS} for cid in loadouts}
    levels: Dict[str, Dict[int, set]] = {p: {} for p in SPEND_PLANS}
    names = list(loadouts)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for task, results in zip(tasks, ex.map(_chain, tasks, chunksize=8)):
            _lo, _adv, plan, _mult, _seed, _stages, cid, _curve = task
            for stage, won, level in results:
                tally[plan][stage][0] += won
                tally[plan][stage][1] += 1
                levels[plan].setdefault(stage, set()).add(level)
                per_char[cid][plan][0] += won
                per_char[cid][plan][1] += 1

    print()
    print(f"{'plan':14s}" + "".join(f"  stage {s:<2d}(L{'/'.join(map(str, sorted(levels['balanced'].get(s, {1}))))})".ljust(20) for s in range(1, args.stages + 1)))
    for plan in SPEND_PLANS:
        row = f"{plan:14s}"
        for s in range(1, args.stages + 1):
            w, n = tally[plan][s]
            row += f"  {100 * w / max(1, n):6.1f}%".ljust(20)
        print(row)
    print()
    for s in range(1, args.stages + 1):
        rates = {p: 100 * tally[p][s][0] / max(1, tally[p][s][1]) for p in SPEND_PLANS}
        hi = max(rates, key=rates.get)
        lo_ = min(rates, key=rates.get)
        spread = rates[hi] - rates[lo_]
        verdict = "in band" if spread <= OVER_PP else "OVER the T-74 band"
        print(f"stage {s}: spread {spread:.1f} pp ({hi} {rates[hi]:.1f}% vs "
              f"{lo_} {rates[lo_]:.1f}%) — {verdict} (band ±{OVER_PP:g} pp)")
    print()
    print("per character (all stages pooled):")
    for cid in names:
        row = f"  {cid:12s}"
        for p in SPEND_PLANS:
            w, n = per_char[cid][p]
            row += f"  {p} {100 * w / max(1, n):5.1f}%"
        print(row)


if __name__ == "__main__":
    main()
