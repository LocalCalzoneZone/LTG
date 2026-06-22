"""LTG Combat — the player-facing deterministic runtime (SCAFFOLD ONLY).

Combat ingests a finished, validated loadout JSON (the contract the Deckbuilder
emits) and will execute deterministic rules over it. It depends only on
`ltg_core`; it never imports the Deckbuilder, reads its live state, or uses
Scryfall, translation, or an LLM at runtime.

This task scaffolds the JSON-in path only: `loader.load_loadout` validates a
loadout through `core`, and `engine.run` is a stub marked `TODO: combat engine`.
"""

from __future__ import annotations

from .loader import LoadoutError, load_loadout, validate_loadout
from .engine import run

__all__ = ["LoadoutError", "load_loadout", "validate_loadout", "run"]
