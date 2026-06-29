"""The LTG Combat text UI — a thin, playable terminal client (Step 2).

It is a thin wrapper over the engine and owns ZERO rules. Its whole job each
decision-point is: render the state the engine reports, render the legal actions
the engine reports, collect the player's choice and build the exact `Action` the
engine expects, call `apply_action`, render the events the engine emits. It never
computes legality, targets, costs, damage, or turn order — every such question is
answered by `legal_actions` / `apply_action`. Rewriting this file changes no
outcome.

Launch it with `python -m ltg_combat repl [scenario.json]` (defaults to the §A
fight). Pick menu numbers; `q` quits.
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Callable, List, Optional

from ltg_core.schema import Card

from .engine import apply_action, legal_actions, settle
from .scenario import SCENARIO_A, build_state, load_scenario, scenario_name
from .state import Action, GameState

_WUBRG = ["W", "U", "B", "R", "G"]
_RULE = "─" * 60


# --------------------------------------------------------------------------- #
# Rendering the state
# --------------------------------------------------------------------------- #
def _cost_str(card: Card) -> str:
    pips = ""
    if card.cost.generic:
        pips += "{" + str(card.cost.generic) + "}"
    counts = {c.value: n for c, n in card.cost.colors.items()}
    for color in _WUBRG:
        pips += ("{" + color + "}") * counts.get(color, 0)
    return pips or "{0}"


def _pip_str(colors: List[str]) -> str:
    """A list of colour letters as compact pips, e.g. ['U','B'] -> '{U}{B}'."""
    counts = Counter(colors)
    return "".join(("{" + c + "}") * counts[c] for c in _WUBRG if counts[c]) or "{0}"


def _mana_str(char) -> str:
    """Available-by-colour over capacity, e.g. 'W:1/1 G:0/1'."""
    avail = Counter(char.pool)
    cap = Counter(char.mana_colors)
    parts = [f"{color}:{avail.get(color, 0)}/{cap[color]}"
             for color in _WUBRG if cap[color]]
    return " ".join(parts) or "(no mana)"


def _status_str(char) -> str:
    bits = []
    if char.temp_mod:
        bits.append(f"{'+' if char.temp_mod >= 0 else ''}{char.temp_mod} tempHP")
    if char.prevent_pool:
        bits.append(f"reduce {char.prevent_pool}")
    for tag in char.prevent_tags:
        bits.append(f"prevent {tag}")
    if char.power_bonus:
        bits.append(f"{'+' if char.power_bonus >= 0 else ''}{char.power_bonus} Pow")
    for kw in char.keywords:
        bits.append(kw)
    if char.acted_mode and char.alive and not char.turn_ended:
        bits.append(char.acted_mode)
    if char.turn_ended:
        bits.append("turn done")
    return ", ".join(bits)


def _phase_label(state: GameState) -> str:
    if state.result is not None:
        return "game over"
    if state.stack:
        return "reaction window"
    return {"upkeep": "upkeep", "capacity": "start of turn — lock mana",
            "draw": "upkeep", "intents": "enemy intents",
            "player": "player actions", "allies": "ally actions",
            "enemy": "enemy actions", "end": "end step"}.get(state.phase, state.phase)


def _render(state: GameState, acting_id: Optional[str]) -> str:
    lines: List[str] = []
    lines.append(_RULE)
    lines.append(f" TURN {state.turn}  ·  {_phase_label(state)}")
    lines.append(_RULE)

    lines.append("PARTY")
    for c in state.party:
        marker = "▶" if c.id == acting_id else " "
        head = f" {marker} {c.name} — {c.archetype or 'character'}"
        incap = "  [INCAPACITATED]" if not c.alive else ""
        lines.append(f"{head}{incap}")
        status = _status_str(c)
        reserved = f"   reserved {_pip_str(c.reserved)}" if c.reserved else ""
        statline = f"     HP {c.hp}/{c.max_hp}   mana {_mana_str(c)}{reserved}   row {c.row}"
        lines.append(statline + (f"   ({status})" if status else ""))
        if c.channels:
            chans = "  ".join(f"{ch.card.name} (holds {_pip_str(ch.reserved)})"
                              for ch in c.channels)
            lines.append(f"     channeling: {chans}")
        if c.hand:
            cards = "  ".join(f"{card.name} {_cost_str(card)}/{card.timing.value}"
                              for card in c.hand)
        else:
            cards = "(empty)"
        lines.append(f"     hand: {cards}")

    if state.tokens:
        lines.append("ALLIES")
        for t in state.tokens:
            lines.append(f"   {t.name}  HP {t.hp}/{t.max_hp}  Power {t.power}  row {t.row}")

    lines.append("ENEMIES")
    if not state.enemies:
        lines.append("   (none remaining)")
    for e in state.enemies:
        intent = "no intent"
        if e.intent is not None:
            tgt = state.combatant(e.intent.target_id)
            amt = e.intent.effects[0].amount if e.intent.effects else "?"
            intent = f"{e.intent.name} ({amt}) → {tgt.name if tgt else '?'}"
        lines.append(f"   {e.name}  HP {e.hp}/{e.max_hp}  Lv{e.level}  row {e.row}"
                     f"   intent: {intent}")

    if state.stack:
        lines.append("STACK (top → bottom)")
        for item in reversed(state.stack):
            src = state.combatant(item.source_id)
            tgt = state.combatant(item.target_id)
            ts = f" → {tgt.name}" if tgt else ""
            lines.append(f"   • {item.label} (by {src.name if src else '?'}{ts})")
    return "\n".join(lines)


def _decision_line(state: GameState, acting_id: str) -> str:
    actor = state.character(acting_id)
    who = actor.name if actor else "?"
    if state.stack:
        return f"\n» {who}'s reaction window — react or pass:"
    if state.phase == "capacity":
        return f"\n» {who} — lock the colour of your +1 mana capacity (before drawing):"
    return f"\n» {who}'s turn — choose an action:"


# --------------------------------------------------------------------------- #
# Building the menu from the engine's legal actions (presentation only)
# --------------------------------------------------------------------------- #
class _Entry:
    """A top-level menu entry: a single action, or a target sub-menu."""

    def __init__(self, label: str, action: Optional[Action] = None,
                 submenu: Optional[List] = None):
        self.label = label
        self.action = action
        self.submenu = submenu  # list of (label, Action|None) — None == Back


def _hand_card(state: GameState, actor_id: str, card_id: str) -> Optional[Card]:
    actor = state.character(actor_id)
    return next((c for c in actor.hand if c.id == card_id), None) if actor else None


def _target_label(state: GameState, action: Action) -> str:
    tgt = state.combatant(action.target_id)
    if tgt is None:
        return "self"
    hp = f" (HP {tgt.hp}/{tgt.max_hp})"
    return f"{tgt.name}{hp}"


def _build_menu(state: GameState, actions: List[Action]) -> List[_Entry]:
    """Group the engine's actions for legibility — Attack then choose an enemy,
    multi-target casts behind a 'choose target' sub-menu. Pure presentation:
    every entry maps back to an Action the engine already offered."""
    # A mid-resolution choice (card move / scry placement) is exclusive: list each
    # pick as its own entry and nothing else.
    choices = [a for a in actions if a.kind in ("choose_card", "choose_scry")]
    if choices:
        return [_Entry(a.label, action=a) for a in choices]

    mana = [a for a in actions if a.kind == "choose_mana"]
    attacks = [a for a in actions if a.kind == "attack"]
    casts = [a for a in actions if a.kind == "cast"]
    others = [a for a in actions
              if a.kind in ("defend", "mitigate", "move", "pass", "end_turn")]

    entries: List[_Entry] = []
    for a in mana:
        entries.append(_Entry(a.label, action=a))

    # Attack is one menu item; the enemy is chosen in a sub-menu (choosing which
    # enemy to attack is a separate step from any targeting an effect does).
    if len(attacks) == 1:
        entries.append(_Entry(attacks[0].label, action=attacks[0]))
    elif len(attacks) > 1:
        sub = [(_target_label(state, a), a) for a in attacks]
        sub.append(("← Back", None))
        entries.append(_Entry("Attack — choose enemy", submenu=sub))

    seen: List[str] = []
    for a in casts:
        if a.card_id in seen:
            continue
        seen.append(a.card_id)
        group = [c for c in casts if c.card_id == a.card_id]
        card = _hand_card(state, a.actor_id, a.card_id)
        name = card.name if card else (group[0].label)
        cost = _cost_str(card) if card else ""
        timing = card.timing.value if card else ""
        if len(group) == 1:
            entries.append(_Entry(group[0].label, action=group[0]))
        else:
            sub = [(_target_label(state, g), g) for g in group]
            sub.append(("← Back", None))
            entries.append(_Entry(f"Cast {name} {cost} ({timing}) — choose target",
                                  submenu=sub))

    for a in others:
        entries.append(_Entry(a.label, action=a))
    return entries


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
def _print_menu(out: Callable[[str], None], labels: List[str]) -> None:
    for i, label in enumerate(labels, 1):
        out(f"  {i}. {label}")


def _read_index(read: Callable[[], str], out: Callable[[str], None],
                n: int) -> Optional[int]:
    """Read a 1..n choice; return 0-based index, or None to quit."""
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
        out(f"  (enter 1-{n}, or q to quit)")


def _select_action(state: GameState, actions: List[Action],
                   read, out) -> Optional[Action]:
    """Render the menu (with any sub-menu) and return the chosen Action, or None
    to quit. Targets shown are exactly those the engine offered."""
    menu = _build_menu(state, actions)
    while True:
        _print_menu(out, [e.label for e in menu])
        idx = _read_index(read, out, len(menu))
        if idx is None:
            return None
        entry = menu[idx]
        if entry.action is not None:
            return entry.action
        # Drill into the target sub-menu.
        out("   choose target:")
        _print_menu(out, [label for label, _ in entry.submenu])
        sidx = _read_index(read, out, len(entry.submenu))
        if sidx is None:
            return None
        _, action = entry.submenu[sidx]
        if action is None:  # Back
            continue
        return action


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
def _run_game(state: GameState, read, out):
    """Play one game to its end (or quit). Returns (final_state, quit?)."""
    while state.result is None:
        actions = legal_actions(state)
        if not actions:
            break
        # Render the settled view the engine's decision is about, so the panel
        # (e.g. the just-drawn hand) always matches the menu. Drive the real
        # `state` through apply_action below.
        view = settle(state)
        acting_id = actions[0].actor_id
        out(_render(view, acting_id))
        out(_decision_line(view, acting_id))
        action = _select_action(view, actions, read, out)
        if action is None:
            out("\nQuit.")
            return state, True
        state, events = apply_action(state, action)
        out("\n  events:")
        for e in events:
            out(f"    • {e.msg}")
        out("")

    out(_render(state, None))
    banner = {"victory": "*** VICTORY — the party wins! ***",
              "defeat": "*** DEFEAT — the party falls. ***"}.get(state.result, "*** game ended ***")
    out(f"\n{banner}  (turn {state.turn})")
    return state, False


def play(state: Optional[GameState] = None, read: Callable[[], str] = input,
         out: Callable[[str], None] = print, scenario_path: Optional[str] = None,
         title: Optional[str] = None) -> GameState:
    """Run the text UI: play, then offer restart (same deterministic setup) or
    quit. `read` / `out` are injectable so the loop can be scripted in a test."""
    if state is None:
        state = load_scenario(scenario_path) if scenario_path else build_state()
    initial = copy.deepcopy(state)
    name = title or (scenario_name() if scenario_path is None else scenario_path)

    out(_RULE)
    out(" LTG Combat — text UI")
    out(f" scenario: {name}")
    out(" pick a number at each prompt; q quits.")
    out(_RULE)

    final = state
    while True:
        final, quit_now = _run_game(copy.deepcopy(initial), read, out)
        if quit_now:
            return final
        out("\nPlay again?")
        _print_menu(out, ["Restart this fight (same deterministic setup)", "Quit"])
        idx = _read_index(read, out, 2)
        if idx != 0:  # Quit or EOF
            out("\nThanks for playing.")
            return final


def main(argv: Optional[List[str]] = None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    scenario_path = argv[0] if argv else None
    try:
        play(scenario_path=scenario_path)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except FileNotFoundError:
        print(f"error: no scenario file at {scenario_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
