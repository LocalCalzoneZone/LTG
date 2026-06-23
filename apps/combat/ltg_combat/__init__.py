"""LTG Combat — the player-facing deterministic runtime.

A headless, deterministic engine that ingests a loadout/encounter and executes
LTG's combat rules. Its whole contract is two pure functions —
`legal_actions(state)` and `apply_action(state, action)` — over a single
`GameState` value; everything else (the scripted harness, the text REPL) drives
the game through those two alone and owns zero rules.

It depends only on `ltg_core` (the effect vocabulary / card schema); it never
imports the Deckbuilder, touches Scryfall, or uses an LLM at runtime.
"""

from __future__ import annotations

from .engine import apply_action, legal_actions, run
from .loader import LoadoutError, load_loadout, validate_loadout
from .scenario import build_state
from .state import Action, Event, GameState

__all__ = [
    "legal_actions",
    "apply_action",
    "build_state",
    "GameState",
    "Action",
    "Event",
    "run",
    "LoadoutError",
    "load_loadout",
    "validate_loadout",
]
