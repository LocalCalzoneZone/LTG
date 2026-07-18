"""Enemy-schema analysis (§D13-3.2) — attribution over the generation vocabulary.

Given a gauntlet's run records and its encounter JSONs, attribute outcomes to
the GENERATION vocabulary — component archetypes, blessed patterns, chassis
shapes — not to individual enemies. Encounters carrying a feature are compared
against encounters without it (same party/size/difficulty cells); big deltas
flag the feature's *price*, and the verdict maps each flag to its existing
lever: the archetype base costs, the chassis table, the verb magnitude
schedule, B(L), and the T-values.

Report-only by decision (2026-07-16): the output is a proposed Rebalance
Register delta plus a prompt-patch note — a human applies it through
Options → LLM.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from ltg_combat.autoplay import make_policy
from ltg_combat.autoplay.report import FOOTER, aggregate

from .probes import PRESETS, _cell_tasks, _run_batch, POLICY, SPEND

# Flag thresholds: a feature is implicated when the with/without win-rate gap
# exceeds this (percentage points) with at least MIN_SIDE encounters per side.
FLAG_PP = 10.0
MIN_SIDE = 2

# Feature → the lever its flag points at (the §D13-3.2 mapping).
LEVERS: Dict[str, str] = {
    "archetype:punish": "Punish base cost (3) in the component price table",
    "archetype:fortify": "Fortify base cost (3) / heal magnitude L+2",
    "archetype:ward": "Ward base cost (3)",
    "archetype:evasive": "Evasive base cost (2)",
    "archetype:burst": "Burst base cost (4) / deal_damage magnitude L+1",
    "archetype:debilitate": "Debilitate base cost (4)",
    "archetype:escalate": "Escalate base cost (4)",
    "archetype:drain": "Drain base cost (5) / magnitude ceil(L/2)+1",
    "archetype:counter": "Counter base cost (3) + reactive +2",
    "archetype:swarm": "Swarm base cost (6) / token cap (T-27)",
    "archetype:necromancy": "Necromancy base cost (5)",
    "pattern:channel": "channelled-component multiplier (×1.5)",
    "pattern:windup": "windup pricing (2× magnitude allowance, threshold rule)",
    "pattern:reactive": "the reactive +2 flat modifier",
    "pattern:boss": "boss budget (2.5 × B(L)) / double level weight",
    "pattern:poison": "poison magnitude (amount 1/tick)",
    "pattern:regen": "regen magnitude (amount 1/tick)",
    "pattern:control": "stun/taunt pricing inside Debilitate",
    "pattern:aoe": "row/blast magnitude schedule (T-55)",
    "pattern:objective": "objective ranges (T-65/T-67/T-68)",
}


def encounter_features(enc: Dict[str, Any]) -> Set[str]:
    """The generation-vocabulary tags one encounter exercises."""
    feats: Set[str] = set()
    if enc.get("objective"):
        feats.add("pattern:objective")
    for e in enc.get("enemies", []):
        if not isinstance(e, dict):
            continue
        if e.get("is_boss"):
            feats.add("pattern:boss")
        for c in e.get("components", []) or []:
            arch = str(c.get("archetype", "")).strip().lower()
            if arch:
                feats.add(f"archetype:{arch}")
            if c.get("channel"):
                feats.add("pattern:channel")
            if c.get("trigger") == "on_charge_full":
                feats.add("pattern:windup")
            if c.get("timing") == "reactive":
                feats.add("pattern:reactive")
            for v in c.get("verbs", []) or []:
                kind = v.get("kind")
                if kind == "poison":
                    feats.add("pattern:poison")
                if kind == "regen":
                    feats.add("pattern:regen")
                if kind in ("stun", "taunt"):
                    feats.add("pattern:control")
                tgt = v.get("target") or {}
                if tgt.get("mode") == "all" or tgt.get("scope"):
                    feats.add("pattern:aoe")
    return feats


def analyze_records(records: List[Dict[str, Any]],
                    encounters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-feature with/without deltas over per-encounter aggregates."""
    by_enc: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        cell = by_enc.setdefault(rec.get("content", ""), {
            "n": 0, "wins": 0, "rounds": 0})
        cell["n"] += 1
        cell["wins"] += 1 if rec.get("result") == "victory" else 0
        cell["rounds"] += rec.get("rounds", 0)
    enc_stats = {}
    for enc in encounters:
        name = enc.get("name", "")
        cell = by_enc.get(name)
        if cell and cell["n"]:
            enc_stats[name] = {
                "win_rate": cell["wins"] / cell["n"],
                "mean_rounds": cell["rounds"] / cell["n"],
                "features": encounter_features(enc),
            }
    all_features = sorted({f for s in enc_stats.values() for f in s["features"]})
    out = []
    for feat in all_features:
        with_f = [s for s in enc_stats.values() if feat in s["features"]]
        without = [s for s in enc_stats.values() if feat not in s["features"]]
        if not with_f or not without:
            continue
        d_win = (sum(s["win_rate"] for s in with_f) / len(with_f)
                 - sum(s["win_rate"] for s in without) / len(without))
        d_rounds = (sum(s["mean_rounds"] for s in with_f) / len(with_f)
                    - sum(s["mean_rounds"] for s in without) / len(without))
        flagged = (abs(d_win) * 100 >= FLAG_PP
                   and len(with_f) >= MIN_SIDE and len(without) >= MIN_SIDE)
        entry = {
            "feature": feat,
            "encounters_with": len(with_f),
            "encounters_without": len(without),
            "delta_win_pp": round(d_win * 100, 1),
            "delta_rounds": round(d_rounds, 2),
            "flagged": flagged,
            "lever": LEVERS.get(feat, "no mapped lever — inspect by hand"),
        }
        if flagged:
            direction = ("underpriced — raise its cost or trim its magnitude"
                         if d_win < 0 else
                         "overpriced — lower its cost or lift its magnitude")
            entry["proposal"] = (
                f"{feat}: encounters fielding it run {d_win * 100:+.1f} pp "
                f"party win rate and {d_rounds:+.1f} mean rounds vs. the rest "
                f"of the gauntlet at equal budget — likely {direction}. "
                f"Lever: {entry['lever']}.")
        out.append(entry)
    out.sort(key=lambda e: (not e["flagged"], -abs(e["delta_win_pp"])))
    return out


def probe_enemy_schema(loadouts: List[Dict[str, Any]],
                       gauntlet: Dict[str, Any], preset_name: str = "quick",
                       jobs: int = 1,
                       progress: Optional[Callable[[int, int, str], None]] = None
                       ) -> Dict[str, Any]:
    """Run the party over the gauntlet and attribute outcomes to the enemy
    generation vocabulary. Most meaningful on generated gauntlets (a large
    fresh sample); on the frozen baseline it reads the fixtures themselves."""
    preset = PRESETS[preset_name]
    tasks = _cell_tasks(loadouts, gauntlet, preset)
    records = _run_batch(
        tasks, jobs,
        (lambda i: progress(i, len(tasks), "gauntlet")) if progress else None)
    features = analyze_records(records, gauntlet["encounters"])
    flagged = [f for f in features if f["flagged"]]
    policy = make_policy(POLICY, SPEND)
    return {
        "kind": "enemy_schema",
        "subject": {"gauntlet_id": gauntlet["id"]},
        "preset": preset_name,
        "screening_only": preset_name == "quick",
        "gauntlet": {"id": gauntlet["id"], "hash": gauntlet["hash"],
                     "name": gauntlet["name"]},
        "policy_version": policy.version,
        "spend_plan": SPEND,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "flag": "FLAGS" if flagged else "IN_BAND",
        "combo_blind": False,
        "features": features,
        "proposals": [f["proposal"] for f in flagged],
        "recommendation": (
            f"{len(flagged)} feature(s) flagged — proposed register deltas "
            "below; apply by hand through Options → LLM (report-only by "
            "design)." if flagged else
            "No generation-vocabulary feature moves the needle beyond the "
            f"±{FLAG_PP:g} pp flag threshold on this gauntlet."),
        "ladder": [],
        "cells": aggregate(records)["cells"],
        "footer": FOOTER,
    }
