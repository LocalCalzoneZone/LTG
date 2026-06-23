"""LTG Combat engine — the deterministic runtime (SCAFFOLD ONLY).

This is the placeholder entry point. The actual engine — the resolver, turn
structure, the stack, enemy execution, the channel-break / mana-reservation
runtime, the narrator — arrives in the follow-up brief. For now `run` only proves
the JSON-in path: it accepts an already-validated `core` Loadout and stops at the
boundary where combat logic will begin.

Determinism rule for what comes next: no Scryfall, no translation, no LLM at
runtime. The engine reads only the validated loadout and the keyword rules in
`ltg_core`.
"""

from __future__ import annotations

from ltg_core.schema import Loadout


def run(loadout: Loadout) -> None:
    """Execute combat for a validated loadout.

    The loadout has already passed `core`'s schema validator (see
    `ltg_combat.loader`), so the vocabulary is known-good here.
    """
    char = loadout.character
    print(
        f"[ltg-combat] loaded '{char.name}' "
        f"({char.archetype.value}, level {char.level}) "
        f"with {len(loadout.cards)} card(s); stats={char.stats}"
    )

    # TODO: combat engine — resolver, turn structure, the stack, enemy
    # execution, channel-break / mana-reservation runtime, narrator. See the
    # follow-up combat brief. This scaffold only validates the loadout (JSON-in)
    # and hands off here.
    raise NotImplementedError("combat engine not implemented yet (scaffold only)")
