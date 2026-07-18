"""The autoplay balance harness (Design Update 12 §D12-3).

A headless, deterministic autoplayer over the engine's public contract —
``legal_actions(state)`` / ``apply_action(state, action)`` — that plays complete
fights and adventures and reports metrics. It is NOT a learned AI and not an
opponent: policies are fixed, versioned, scripted heuristics, because they are
the measuring stick — a balance change's effect is only readable if the stick
doesn't move. Absolute win rates read low (a greedy bot underplays combos,
stances, and interception); the harness's product is DELTAS — between builds,
encounters, difficulties, and balance patches. No LLM anywhere in the loop.

Console script: ``ltg-autoplay`` (run / report / diff / soak). This package
depends only on ``ltg_combat`` + ``ltg_core`` and composes fights through the
same ``compose_spec`` / ``state_from_dict`` path the servers use; adventure
runs replicate the game server's carry-over/level-up rules (§D10-2/3) in
``runner.py`` — the session layer is never imported.
"""

from .policies import GreedyPolicy, RandomPolicy, SPEND_PLANS, make_policy
from .runner import ROUND_CAP, run_adventure, run_one, spec_hash

__all__ = [
    "GreedyPolicy",
    "RandomPolicy",
    "SPEND_PLANS",
    "make_policy",
    "ROUND_CAP",
    "run_adventure",
    "run_one",
    "spec_hash",
]
