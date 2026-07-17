"""``ltg-autoplay`` — the balance harness CLI (§D12-3.5).

    ltg-autoplay run  --parties soren.json lasarre.json --content pit.json
                      --difficulties standard,hard --sizes 1-4 --seeds 200
                      --policy greedy --out runs/base.jsonl
    ltg-autoplay report runs/base.jsonl          # aggregate tables + outliers
    ltg-autoplay diff   runs/base.jsonl runs/after.jsonl
    ltg-autoplay soak   --games 10000 --policy random

Content files are engine-shaped JSON:
  * an enemies-only encounter (optionally with layouts / an objective) — needs
    --parties (Deckbuilder loadout exports); the size axis picks the first N;
  * an adventure with INLINE acts ({"acts": [<encounter>, ×3]}) — run through
    the §D10-2/3 carry-over and level-up rules;
  * a full scenario with an embedded party (the §A/§C shape) — runs as-is
    (the size/party axes don't apply).

NOT ``ltg-combat harness`` — that is the scripted-proof command and keeps its
name and behaviour untouched.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..scenario import SCENARIO_A, SCENARIO_C, compose_spec, scale_encounter
from .policies import SPEND_PLANS, make_policy
from .report import aggregate, diff_reports, load_records, render_report
from .runner import (
    ROUND_CAP,
    _bump_enemy_power,
    _scale_difficulty,
    prepare_scenario,
    run_adventure,
    run_one,
)
from .soak import soak


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a JSON object")
    data.setdefault("name", Path(path).stem)
    return data


def _parse_sizes(text: str) -> List[int]:
    out: List[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def _content_mode(content: Dict[str, Any]) -> str:
    if isinstance(content.get("acts"), list):
        return "adventure"
    if isinstance(content.get("party"), list):
        return "scenario"
    return "encounter"


def _run_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """One (content × difficulty × size × policy × spend × seed) run — a
    top-level function so process pools can pickle it."""
    policy = make_policy(task["policy"], task["spend"])
    if task["mode"] == "adventure":
        return run_adventure(task["content"], task["loadouts"], policy,
                             task["seed"], difficulty=task["difficulty"],
                             power_bump=task["power_bump"],
                             label=task["label"], round_cap=task["round_cap"])
    return run_one(task["spec"], policy, task["seed"],
                   difficulty=task["difficulty"], label=task["label"],
                   round_cap=task["round_cap"])


def _build_tasks(args) -> List[Dict[str, Any]]:
    contents = [_load_json(p) for p in args.content]
    loadouts = [_load_json(p) for p in (args.parties or [])]
    difficulties = [d.strip() for d in args.difficulties.split(",") if d.strip()]
    sizes = _parse_sizes(args.sizes)
    policies = [p.strip() for p in args.policy.split(",") if p.strip()]
    spends = [s.strip() for s in args.spend.split(",") if s.strip()]
    power_bump = not args.raw_power

    tasks: List[Dict[str, Any]] = []
    for content in contents:
        mode = _content_mode(content)
        for difficulty in difficulties:
            for policy in policies:
                for spend in spends:
                    base = {"difficulty": difficulty, "policy": policy,
                            "spend": spend, "power_bump": power_bump,
                            "label": content["name"],
                            "round_cap": args.round_cap}
                    if mode == "scenario":
                        spec = copy.deepcopy(content)
                        _scale_difficulty(spec, difficulty)
                        spec = scale_encounter(spec, len(spec["party"]))
                        if power_bump:
                            _bump_enemy_power(spec)
                        for seed in range(args.seeds):
                            tasks.append({**base, "mode": "spec", "spec": spec,
                                          "seed": seed})
                        continue
                    if not loadouts:
                        raise SystemExit(
                            f"{content['name']}: enemies-only content needs "
                            "--parties (Deckbuilder loadout JSONs)")
                    for size in sizes:
                        if size > len(loadouts):
                            continue
                        party = loadouts[:size]
                        if mode == "adventure":
                            for seed in range(args.seeds):
                                tasks.append({**base, "mode": "adventure",
                                              "content": content,
                                              "loadouts": party, "seed": seed})
                        else:
                            scenario = prepare_scenario(
                                content, size, difficulty, power_bump)
                            spec = compose_spec(party, scenario)
                            for seed in range(args.seeds):
                                tasks.append({**base, "mode": "spec",
                                              "spec": spec, "seed": seed})
    return tasks


def _cmd_run(args) -> int:
    tasks = _build_tasks(args)
    if not tasks:
        print("nothing to run (check --sizes against --parties)", file=sys.stderr)
        return 2
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            records = list(pool.map(_run_task, tasks))
    else:
        records = [_run_task(t) for t in tasks]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    anomalies = sum(1 for r in records if r.get("anomaly"))
    print(f"{len(records)} run(s) → {out}"
          + (f" · ⚑ {anomalies} anomalies" if anomalies else ""))
    print(render_report(aggregate(records)))
    return 0


def _cmd_report(args) -> int:
    agg = aggregate(load_records(args.file))
    if args.json:
        print(json.dumps(agg, indent=2))
    else:
        print(render_report(agg))
    return 0


def _cmd_diff(args) -> int:
    print(diff_reports(aggregate(load_records(args.a)),
                       aggregate(load_records(args.b))))
    return 0


def _cmd_soak(args) -> int:
    if args.content:
        specs = [_load_json(p) for p in args.content]
        # Enemies-only content composes against the given parties; full
        # scenarios run as-is.
        loadouts = [_load_json(p) for p in (args.parties or [])]
        prepared = []
        for c in specs:
            if _content_mode(c) == "encounter":
                if not loadouts:
                    raise SystemExit(f"{c['name']}: soak over enemies-only "
                                     "content needs --parties")
                prepared.append(compose_spec(
                    loadouts, prepare_scenario(c, len(loadouts))))
            else:
                prepared.append(c)
        specs = prepared
    else:
        specs = [SCENARIO_A, SCENARIO_C]  # the built-in default soup
    policy = make_policy(args.policy)
    report = soak(specs, args.games, policy, seed0=args.seed0,
                  round_cap=args.round_cap, out=args.out)
    ok = not report["failures"]
    print(f"soak: {report['games']} game(s), policy {report['policy_version']} "
          f"— {report['results']['victory']} won / "
          f"{report['results']['defeat']} lost · "
          + ("no invariant failures"
             if ok else f"{len(report['failures'])} FAILURE(S)"))
    for f in report["failures"][:10]:
        print(f"  ⚑ {f['spec_name']} seed {f['repro']['seed']}: {f['error']}")
        print(f"    repro: {json.dumps(f['repro'], sort_keys=True)}")
    if args.out:
        print(f"report → {args.out}")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ltg-autoplay",
        description="LTG autoplay balance harness (§D12-3): deterministic "
                    "scripted policies, measured runs, and the diff.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="play a matrix of fights to JSONL")
    run_p.add_argument("--parties", nargs="*", default=[],
                       help="Deckbuilder loadout JSONs (size N uses the first N)")
    run_p.add_argument("--content", nargs="+", required=True,
                       help="encounter / adventure / full-scenario JSONs")
    run_p.add_argument("--difficulties", default="standard")
    run_p.add_argument("--sizes", default="1-4")
    run_p.add_argument("--seeds", type=int, default=200)
    run_p.add_argument("--policy", default="greedy")
    run_p.add_argument("--spend", default="balanced",
                       help=f"level-up spend plan(s): {', '.join(SPEND_PLANS)}")
    run_p.add_argument("--out", default="runs/autoplay.jsonl")
    run_p.add_argument("--raw-power", action="store_true",
                       help="skip the T-64 enemy Power bump (the retro diff)")
    run_p.add_argument("--round-cap", type=int, default=ROUND_CAP)
    run_p.add_argument("--jobs", type=int, default=1)
    run_p.set_defaults(fn=_cmd_run)

    rep_p = sub.add_parser("report", help="aggregate a JSONL run file")
    rep_p.add_argument("file")
    rep_p.add_argument("--json", action="store_true")
    rep_p.set_defaults(fn=_cmd_report)

    diff_p = sub.add_parser("diff", help="per-cell deltas between two run files")
    diff_p.add_argument("a")
    diff_p.add_argument("b")
    diff_p.set_defaults(fn=_cmd_diff)

    soak_p = sub.add_parser("soak", help="random-policy invariant fuzzing")
    soak_p.add_argument("--games", type=int, default=1000)
    soak_p.add_argument("--policy", default="random")
    soak_p.add_argument("--content", nargs="*", default=[])
    soak_p.add_argument("--parties", nargs="*", default=[])
    soak_p.add_argument("--seed0", type=int, default=0)
    soak_p.add_argument("--round-cap", type=int, default=ROUND_CAP)
    soak_p.add_argument("--out", default="")
    soak_p.set_defaults(fn=_cmd_soak)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
