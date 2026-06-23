"""LTG Deckbuilder — the designer-facing authoring app.

Offline, write-heavy authoring: Scryfall import, deterministic translation,
character building, effect editing, human ratification, and JSON export. It
imports the shared vocabulary from `ltg_core` and emits a validated loadout JSON
that LTG Combat consumes. No combat runtime lives here.
"""
