"""Autopilot fights (roadmap M3.2): the autoplay policy plays a live fight.

A playtest tool. While the playtest profile is on (Options → LLM → Playtest),
the combat screen offers Autopilot: the existing greedy policy
(`ltg_combat.autoplay.policies.GreedyPolicy`) makes every party decision, so
a human can play the towns and let the nine fights of a scenario resolve in
seconds. Only the fights: level-up screens, the spoils and every town choice
stay with the players.

The engine is pure, so the policy plays on the session's state off the lock
and off the event loop, a chunk of decisions at a time; the result is
committed only if nobody acted meanwhile (otherwise the chunk is replanned
from the new state). The policy's numbers are not balance evidence (see
docs/architecture.md §11); this is for moving through the game, not for
judging it.
"""

from __future__ import annotations

import copy
import random
from typing import Optional, Tuple

from ltg_combat.autoplay.policies import GreedyPolicy
from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.state import GameState

# Decisions per committed chunk: small enough that the table sees the fight
# move (one broadcast per chunk), large enough that a fight takes seconds.
CHUNK_ACTIONS = 40
# The runner's anomaly caps (autoplay/runner.py): a fight still running past
# them hands back to the players rather than spinning. The action cap counts
# one fight's autopilot decisions.
ROUND_CAP = 50
ACTION_CAP = 20000


def play_chunk(state: GameState, seed: int, max_actions: int = CHUNK_ACTIONS
               ) -> Tuple[GameState, int, Optional[str]]:
    """Play up to ``max_actions`` party decisions from ``state`` (never
    mutated). Returns ``(new_state, decisions_made, stop_reason)``; the
    reason is None while the fight simply goes on or has ended, else
    "round_cap" / "no_actions" (the players take over)."""
    st = copy.deepcopy(state)
    st.paced = False                  # no presentation stops inside a chunk
    policy = GreedyPolicy()
    rng = random.Random(f"{seed}:{st.turn}:{len(st.log)}")
    made = 0
    stop: Optional[str] = None
    while st.result is None and made < max_actions:
        if st.turn > ROUND_CAP:
            stop = "round_cap"
            break
        legal = legal_actions(st)
        if not legal:
            stop = "no_actions"
            break
        st, _ = apply_action(st, policy.choose(st, legal, rng))
        made += 1
    st.paced = state.paced
    return st, made, stop
