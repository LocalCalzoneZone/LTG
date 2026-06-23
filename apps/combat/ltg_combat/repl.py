"""Client B — a thin text/menu REPL over the engine (brief §B).

It prints the state, prints `legal_actions` as a numbered menu, reads a pick,
calls `apply_action`, prints the emitted events, and loops. It owns ZERO rules:
every legal move and every number it shows comes from the engine. If it ever
computed legality or damage itself, that would be a bug.

Driven with the same choices a player would make, it plays the §A encounter to
the same deterministic result the harness proves.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional

from .engine import apply_action, legal_actions
from .scenario import build_state
from .state import Action, GameState


def _render(state: GameState) -> str:
    lines: List[str] = []
    lines.append(f"\n=== Turn {state.turn} · phase: {state.phase} ===")
    lines.append("Party:")
    for c in state.party:
        status = "" if c.alive else " (incapacitated)"
        pool = "[" + ",".join(c.pool) + "]" if c.pool else "(empty)"
        flags = []
        if c.proactive_spent:
            flags.append("acted")
        if c.temp_hp:
            flags.append(f"+{c.temp_hp} tempHP")
        if c.prevent_pool:
            flags.append(f"prevent {c.prevent_pool}")
        extra = f"  {{{', '.join(flags)}}}" if flags else ""
        lines.append(f"  {c.name:6} HP {c.hp:>2}/{c.max_hp}  Pow {c.current_power}  "
                     f"mana {pool} (cap {c.capacity}){status}{extra}")
        lines.append(f"         hand: {', '.join(card.name for card in c.hand) or '(empty)'}")
    lines.append("Enemies:")
    for e in state.enemies:
        intent = ""
        if e.intent is not None:
            tgt = state.combatant(e.intent.target_id)
            tname = tgt.name if tgt else "?"
            amt = e.intent.effects[0].amount if e.intent.effects else "?"
            intent = f"  intent: {e.intent.name} ({amt}) → {tname}"
        lines.append(f"  {e.name:11} HP {e.hp:>2}/{e.max_hp}  (Level {e.level}){intent}")
    if state.stack:
        top = " | ".join(f"{i.label} (by {state.combatant(i.source_id).name})"
                         for i in reversed(state.stack))
        lines.append(f"Stack (top→bottom): {top}")
    return "\n".join(lines)


def _decision_line(state: GameState, actor_id: str) -> str:
    # The acting character comes from the legal actions (all share one actor),
    # not state.priority: before the first apply_action settles the opening
    # upkeep, the raw setup state has no priority assigned yet.
    actor = state.character(actor_id)
    who = actor.name if actor else "?"
    if state.stack:
        return f"\n{who} has priority (reaction window). Choose a reaction or pass:"
    return f"\n{who}'s turn. Choose an action:"


def play(state: Optional[GameState] = None,
         read: Callable[[], str] = input,
         out: Callable[[str], None] = print) -> GameState:
    """Run the interactive loop until the game ends. `read`/`out` are injectable
    so the loop can be scripted in a test."""
    state = state if state is not None else build_state()
    out("LTG Combat — text REPL. Pick a number; Ctrl-D / 'q' to quit.")

    while state.result is None:
        actions = legal_actions(state)
        if not actions:  # no decision pending (shouldn't happen at a pause)
            break
        out(_render(state))
        out(_decision_line(state, actions[0].actor_id))
        for i, a in enumerate(actions, 1):
            out(f"  {i}. {a.label}")

        choice = _read_choice(read, out, len(actions))
        if choice is None:
            out("Quit.")
            return state
        action: Action = actions[choice]
        state, events = apply_action(state, action)
        out("")
        for e in events:
            out(f"  · {e.msg}")

    out(_render(state))
    out(f"\n*** Game over: {state.result} (turn {state.turn}) ***")
    return state


def _read_choice(read, out, n: int) -> Optional[int]:
    while True:
        try:
            raw = read()
        except EOFError:
            return None
        raw = (raw or "").strip().lower()
        if raw in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= n:
            return int(raw) - 1
        out(f"Enter 1-{n} (or q to quit).")


def main(argv: Optional[List[str]] = None) -> int:
    try:
        play()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
