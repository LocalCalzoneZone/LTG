"""LTG-Game server — a FastAPI + WebSocket authority/relay around the existing
headless combat engine (``ltg_combat``).

This package holds authoritative game state per session and enforces seats
(who may act / who may see which hand). It owns **zero** game rules: legality,
resolution, ordering and state transitions all come from the engine's
``legal_actions`` / ``apply_action``. The current state contract and module map
are in ``docs/architecture.md``; ``docs/design/INTERFACE_NOTES.md`` is the original
(Phase 1) engine ↔ UI reconciliation this layer was built on, still cited by §.
"""
