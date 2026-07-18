"""Aggregation and the diff (§D12-3.5) — the tool's whole reason to exist.

Raw runner output is JSONL (one RunRecord per line). ``aggregate`` folds it to
per-cell tables — (party × content × difficulty × size × policy × spend plan) —
with win rate, mean rounds, damage shares, and outlier flags against the T-72
thresholds. ``diff_reports`` aligns two aggregates on the same matrix and shows
per-cell deltas: every Rebalance Register change should land with one.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# T-72 outlier thresholds (standard difficulty for the win-rate band).
WIN_RATE_BAND = (0.30, 0.85)
MEAN_ROUNDS_MAX = 12.0
DAMAGE_SHARE_MIN = 0.10

FOOTER = ("Note (§D12-7): the launch greedy policy does not sequence "
          "amplify→spike combo lines — combo-deck win rates read artificially "
          "low. Absolute rates are not the product; deltas are.")

CELL_KEY = ("party", "content", "difficulty", "size", "policy", "spend_plan")


def load_records(path: str) -> List[Dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _cell_key(rec: Dict[str, Any]) -> Tuple:
    return tuple(rec.get(k) for k in CELL_KEY)


def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    cells: Dict[Tuple, Dict[str, Any]] = {}
    versions = sorted({r.get("policy_version", "?") for r in records})
    for rec in records:
        cell = cells.setdefault(_cell_key(rec), {
            **{k: rec.get(k) for k in CELL_KEY},
            "n": 0, "wins": 0, "anomalies": 0, "rounds": [],
            "damage": {}, "damage_total": 0,
        })
        cell["n"] += 1
        if rec.get("result") == "victory":
            cell["wins"] += 1
        if rec.get("anomaly"):
            cell["anomalies"] += 1
        cell["rounds"].append(rec.get("rounds", 0))
        for cid, m in (rec.get("characters") or {}).items():
            dealt = int(m.get("damage_dealt", 0) or 0)
            cell["damage"][cid] = cell["damage"].get(cid, 0) + dealt
            cell["damage_total"] += dealt

    out = []
    for key in sorted(cells, key=lambda k: tuple(str(x) for x in k)):
        c = cells[key]
        n = c["n"]
        win_rate = c["wins"] / n if n else 0.0
        mean_rounds = sum(c["rounds"]) / n if n else 0.0
        shares = {cid: (d / c["damage_total"] if c["damage_total"] else 0.0)
                  for cid, d in sorted(c["damage"].items())}
        flags = []
        if c["difficulty"] == "standard" and not (
                WIN_RATE_BAND[0] <= win_rate <= WIN_RATE_BAND[1]):
            flags.append(f"win rate {win_rate:.0%} outside "
                         f"{WIN_RATE_BAND[0]:.0%}–{WIN_RATE_BAND[1]:.0%}")
        if mean_rounds > MEAN_ROUNDS_MAX:
            flags.append(f"mean rounds {mean_rounds:.1f} > {MEAN_ROUNDS_MAX:g}")
        for cid, share in shares.items():
            if share < DAMAGE_SHARE_MIN:
                flags.append(f"{cid} contributes {share:.0%} of party damage "
                             f"(< {DAMAGE_SHARE_MIN:.0%})")
        if c["anomalies"]:
            flags.append(f"{c['anomalies']} anomalous run(s)")
        out.append({
            **{k: c[k] for k in CELL_KEY},
            "n": n, "win_rate": round(win_rate, 4),
            "mean_rounds": round(mean_rounds, 2),
            "anomalies": c["anomalies"],
            "damage_share": {cid: round(s, 4) for cid, s in shares.items()},
            "flags": flags,
        })
    return {"cells": out, "policy_versions": versions, "footer": FOOTER}


def render_report(agg: Dict[str, Any]) -> str:
    lines = []
    header = (f"{'content':<32} {'party':<20} {'diff':<9} {'sz':>2} "
              f"{'policy':<8} {'spend':<12} {'n':>5} {'win%':>6} {'rounds':>7}")
    lines.append(header)
    lines.append("-" * len(header))
    for c in agg["cells"]:
        lines.append(
            f"{str(c['content'])[:32]:<32} {str(c['party'])[:20]:<20} "
            f"{str(c['difficulty']):<9} {c['size']:>2} {str(c['policy']):<8} "
            f"{str(c['spend_plan']):<12} {c['n']:>5} {c['win_rate']:>6.0%} "
            f"{c['mean_rounds']:>7.1f}")
        for cid, share in c["damage_share"].items():
            lines.append(f"    damage {cid}: {share:.0%}")
        for f in c["flags"]:
            lines.append(f"    ⚑ {f}")
    lines.append("")
    lines.append(f"policy versions: {', '.join(agg['policy_versions'])}")
    lines.append(agg["footer"])
    return "\n".join(lines)


def diff_reports(agg_a: Dict[str, Any], agg_b: Dict[str, Any]) -> str:
    """Per-cell deltas, B relative to A — same matrix, before/after."""
    a_cells = {tuple(c[k] for k in CELL_KEY): c for c in agg_a["cells"]}
    b_cells = {tuple(c[k] for k in CELL_KEY): c for c in agg_b["cells"]}
    lines = []
    header = (f"{'content':<32} {'party':<20} {'diff':<9} {'sz':>2} "
              f"{'policy':<8} {'Δwin%':>7} {'Δrounds':>8} {'n(A→B)':>10}")
    lines.append(header)
    lines.append("-" * len(header))
    for key in sorted(set(a_cells) | set(b_cells),
                      key=lambda k: tuple(str(x) for x in k)):
        a, b = a_cells.get(key), b_cells.get(key)
        if a is None or b is None:
            side = "B only" if a is None else "A only"
            c = a or b
            lines.append(f"{str(c['content'])[:32]:<32} "
                         f"{str(c['party'])[:20]:<20} {str(c['difficulty']):<9} "
                         f"{c['size']:>2} {str(c['policy']):<8}   ({side})")
            continue
        dwin = b["win_rate"] - a["win_rate"]
        drounds = b["mean_rounds"] - a["mean_rounds"]
        lines.append(
            f"{str(a['content'])[:32]:<32} {str(a['party'])[:20]:<20} "
            f"{str(a['difficulty']):<9} {a['size']:>2} {str(a['policy']):<8} "
            f"{dwin:>+7.0%} {drounds:>+8.1f} {a['n']:>4}→{b['n']:<4}")
    va, vb = agg_a["policy_versions"], agg_b["policy_versions"]
    if va != vb:
        lines.append("")
        lines.append(f"⚑ POLICY VERSIONS DIFFER (A: {', '.join(va)} · "
                     f"B: {', '.join(vb)}) — the measuring stick moved; "
                     "these deltas are not comparable.")
    lines.append("")
    lines.append(agg_a["footer"])
    return "\n".join(lines)
