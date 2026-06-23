"""LTG core — the shared vocabulary and single source of truth.

This package owns the effect schema, target descriptors, the keyword &
translation registry, the renderer, the lint/validator, and the loadout JSON
schema. It is the contract both apps depend on:

  * the Deckbuilder *emits* a validated loadout JSON
  * Combat *consumes* it

`core` depends on neither app and contains nothing app-specific — no Scryfall
client, no web routes, no UI. Import the vocabulary from here:

    from ltg_core import Loadout, Card, render_effects, lint_card
"""

from __future__ import annotations

from . import schema, translation, lints
from .schema import *  # noqa: F401,F403  (re-export the schema vocabulary)
from .translation import render_effects, translate
from .lints import lint_card, LINT_RULES

__all__ = [
    "schema",
    "translation",
    "lints",
    "render_effects",
    "translate",
    "lint_card",
    "LINT_RULES",
]
