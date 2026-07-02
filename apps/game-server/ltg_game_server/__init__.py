"""LTG-Game server — a FastAPI + WebSocket authority/relay around the existing
headless combat engine (``ltg_combat``).

This package holds authoritative game state per session and enforces seats
(who may act / who may see which hand). It owns **zero** game rules: legality,
resolution, ordering and state transitions all come from the engine's
``legal_actions`` / ``apply_action``. See ``INTERFACE_NOTES.md`` at the repo
root for the engine ↔ UI field reconciliation this layer is built on.
"""
