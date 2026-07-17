"""Soak mode (§D12-3.6) — the free fuzzer.

Seeded random-policy games asserting engine invariants after every action:
HP within bounds, the ultimate gauge within 0–100, enemy charge non-negative,
``legal_actions`` non-empty whenever the game is undecided, ``apply_action``
never raising, and termination under the round cap. Failures write the repro
key ``(spec hash, policy version, seed)`` and the stop-state summary to the
report — because the engine is deterministic, the repro IS the key.

(The design's "mana ≤ capacity" bound is asserted as non-negativity only:
`add_mana` rituals legitimately push a pool past capacity for a turn.)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..engine import apply_action, legal_actions
from ..scenario import state_from_dict
from ..state import GameState
from .policies import Policy, RandomPolicy
from .runner import ACTION_CAP, ROUND_CAP, _policy_rng, spec_hash


def check_invariants(st: GameState) -> List[str]:
    """The between-actions invariant sweep. Returns human-readable violations."""
    problems: List[str] = []
    for c in st.party:
        if not 0 <= c.hp <= c.max_hp:
            problems.append(f"{c.id}: hp {c.hp} outside [0, {c.max_hp}]")
        if not 0 <= c.ultimate_gauge <= 100:
            problems.append(f"{c.id}: gauge {c.ultimate_gauge} outside [0, 100]")
        if len(c.pool) < 0 or len(c.reserved) > c.capacity:
            problems.append(f"{c.id}: reserved {len(c.reserved)} > capacity "
                            f"{c.capacity}")
    for e in st.enemies:
        if not 0 <= e.hp <= e.max_hp:
            problems.append(f"{e.id}: hp {e.hp} outside [0, {e.max_hp}]")
        if e.charge < 0:
            problems.append(f"{e.id}: charge {e.charge} negative")
    for t in st.tokens:
        if t.hp > t.max_hp:
            problems.append(f"{t.id}: hp {t.hp} above max {t.max_hp}")
    if st.result is not None and st.stack:
        problems.append("game decided with a non-empty stack")
    return problems


def _stop_state(st: GameState, actions: int) -> Dict[str, Any]:
    return {
        "turn": st.turn, "phase": st.phase, "actions": actions,
        "stack": [i.label for i in st.stack],
        "party_hp": {c.id: c.hp for c in st.party},
        "enemy_hp": {e.id: e.hp for e in st.enemies},
        "last_events": [f"{e.type}: {e.msg}" for e in st.log[-8:]],
    }


def soak(specs: List[Dict[str, Any]], games: int,
         policy: Optional[Policy] = None, seed0: int = 0,
         round_cap: int = ROUND_CAP,
         out: Optional[str] = None) -> Dict[str, Any]:
    """Run `games` seeded random-policy fights round-robin over `specs`,
    checking invariants after every action. Returns (and optionally writes)
    the failure report."""
    policy = policy or RandomPolicy()
    failures: List[Dict[str, Any]] = []
    results = {"victory": 0, "defeat": 0}
    for g in range(games):
        spec = specs[g % len(specs)]
        seed = seed0 + g
        h = spec_hash(spec)
        rng = _policy_rng(h, policy, seed)
        st = state_from_dict(spec, seed=seed)
        actions = 0
        failure = None
        try:
            while st.result is None:
                if st.turn > round_cap:
                    failure = f"round cap exceeded ({round_cap}, T-71)"
                    break
                acts = legal_actions(st)
                if not acts:
                    failure = "legal_actions empty while the game is undecided"
                    break
                st, _ = apply_action(st, acts[rng.randrange(len(acts))])
                actions += 1
                if actions > ACTION_CAP:
                    failure = f"action cap exceeded ({ACTION_CAP})"
                    break
                problems = check_invariants(st)
                if problems:
                    failure = "; ".join(problems)
                    break
        except Exception as exc:  # apply_action must never raise
            failure = f"exception: {type(exc).__name__}: {exc}"
        if failure is not None:
            failures.append({
                "repro": {"spec_hash": h, "policy_version": policy.version,
                          "seed": seed},
                "spec_name": spec.get("name", ""),
                "error": failure,
                "stop_state": _stop_state(st, actions),
            })
        elif st.result in results:
            results[st.result] += 1
    report = {
        "games": games,
        "policy_version": policy.version,
        "specs": [s.get("name", "") for s in specs],
        "results": results,
        "failures": failures,
    }
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return report
