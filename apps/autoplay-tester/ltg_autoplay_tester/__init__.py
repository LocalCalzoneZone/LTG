"""The Autoplay Tester (Design Update 13) — probes, gauntlets, verdicts.

A standalone playtest-lab app over the §D12-3 harness: automated A/B analyses
(probes) of one card, one Skill/Ultimate, or one whole character, run against
versioned encounter sets (gauntlets), producing balance recommendations
(verdicts). The Tester never edits content itself — player characters change
only through the Deckbuilder's edit flow, and enemy-schema recommendations are
report-only.

Dependency edges (decided 2026-07-16): ltg_core + ltg_combat (the harness)
plus ltg_game_server AS A LIBRARY (content registry, LLM client) — one-way;
the game server never imports this package.
"""

__version__ = "0.1.0"
