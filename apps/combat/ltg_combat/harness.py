"""The scripted-scenario harness — the engine's correctness proof (brief §A).

This drives the §A fight to completion through ONLY `legal_actions` /
`apply_action`, asserting the expected state at every marked step. It owns zero
rules: it reads state to decide which scripted choice to pick, and reads the
event log to confirm what happened — but it never computes legality or damage.

Run it directly (`python -m ltg_combat harness`) for a readable PASS/FAIL trace,
or call `run_scenario()` from a test. Every assertion is deterministic.
"""

from __future__ import annotations

from typing import List, Optional

from .engine import apply_action, legal_actions
from .scenario import build_state, hand_names, mana
from .state import Action, Event, GameState

_VERBOSE = False


def _say(msg: str) -> None:
    if _VERBOSE:
        print(msg)


def _check(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    _say(f"  ok · {label}")


def _pick(state: GameState, **criteria) -> Action:
    """Find the unique legal action matching the given fields."""
    for a in legal_actions(state):
        if all(getattr(a, k) == v for k, v in criteria.items()):
            return a
    raise AssertionError(f"no legal action matching {criteria}; "
                         f"legal={[a.label for a in legal_actions(state)]}")


def _do(state: GameState, **criteria):
    """Apply the uniquely-matching legal action; return (state', events)."""
    return apply_action(state, _pick(state, **criteria))


def _in_window(state: GameState) -> bool:
    """True while a reaction window is open (the priority player may react/pass)."""
    return state.result is None and bool(state.stack)


def _pass_window(state: GameState) -> GameState:
    """Pass for whoever holds priority until the open window(s) fully resolve and
    control returns to a main phase (or the game ends)."""
    while _in_window(state):
        state, _ = apply_action(state, _pick(state, kind="pass"))
    return state


def _events_of_type(events: List[Event], type_: str) -> List[Event]:
    return [e for e in events if e.type == type_]


def run_scenario(verbose: bool = False) -> GameState:
    """Play §A; assert every marked state. Raises AssertionError on any mismatch."""
    global _VERBOSE
    _VERBOSE = verbose

    state = build_state()
    soren, ys = state.party
    skitter = state.enemy("skitterling")
    brute = state.enemy("brute")

    # --- §A.3 Setup (encounter start, before Turn 1) ----------------------- #
    _say("§A.3 — setup")
    _check("Soren HP 25", soren.hp == 25)
    _check("Soren opening hand [Guard, Sunlance]", hand_names(soren) == ["Guard", "Sunlance"])
    _check("Ys HP 15", ys.hp == 15)
    _check("Ys opening hand [Unmake, Mind Spike, Whispers, Sift]",
           hand_names(ys) == ["Unmake", "Mind Spike", "Whispers", "Sift"])
    _check("Skitterling HP 3", skitter.hp == 3)
    _check("Brute HP 8", brute.hp == 8)

    # --- TURN 1 — Upkeep + Enemy Intents (run automatically before Soren acts) #
    # The first apply_action bootstraps the opening: its events carry the draws,
    # the mana refresh, and the declared intents.
    _say("\nTURN 1 — Soren attacks Skitterling")
    state, ev = _do(state, kind="attack", target_id="skitterling")
    soren, ys = state.party

    _say("§A.4 — Turn 1 upkeep")
    draws = {e.data["character"]: e.data["card_name"] for e in _events_of_type(ev, "draw")}
    _check("Soren drew Steady Blade", draws.get("soren") == "Steady Blade")
    _check("Ys drew Nightcreep", draws.get("ys") == "Nightcreep")
    _check("Soren hand now [Guard, Sunlance, Steady Blade]",
           hand_names(soren) == ["Guard", "Sunlance", "Steady Blade"])
    _check("Ys hand now [Unmake, Mind Spike, Whispers, Sift, Nightcreep]",
           hand_names(ys) == ["Unmake", "Mind Spike", "Whispers", "Sift", "Nightcreep"])
    _check("Soren mana capacity 2", soren.capacity == 2)
    _check("Ys mana capacity 2", ys.capacity == 2)

    _say("§A.4 — Turn 1 intents")
    intents = {e.data["enemy"]: e.data["target"] for e in _events_of_type(ev, "intent_declared")}
    _check("Skitterling Claw targets Ys", intents.get("skitterling") == "ys")
    _check("Brute Smash targets Ys", intents.get("brute") == "ys")

    # The attack is on the stack; nobody reacts -> resolve it.
    state = _pass_window(state)
    soren, ys = state.party
    _check("Skitterling HP 1 after Soren's attack", state.enemy("skitterling").hp == 1)
    _check("Soren proactive action spent", soren.proactive_spent)
    _check("Soren mana still [G, W]", mana(soren) == ["G", "W"])

    state, _ = _do(state, kind="end_turn", actor_id="soren")

    # --- TURN 1 — Player action 2: Ys casts Unmake on Brute ---------------- #
    _say("\nTURN 1 — Ys casts Unmake on Brute")
    state, ev = _do(state, kind="cast", card_id="unmake", target_id="brute")
    state = _pass_window(state)  # nobody counters -> Unmake resolves
    soren, ys = state.party
    _check("Brute removed", state.enemy("brute") is None)
    _check("Ys HP 12 (lost destroyed_target.level = 3)", ys.hp == 12)
    _check("Ys mana empty", mana(ys) == [])
    _check("Brute's Smash intent discarded (Brute gone)",
           all(e.id != "brute" for e in state.enemies))

    state, _ = _do(state, kind="end_turn", actor_id="ys")

    # --- TURN 1 — Enemy actions: Skitterling executes Claw; Soren Guards Ys - #
    _say("\nTURN 1 — Skitterling executes Claw; Soren reacts with Guard on Ys")
    _check("Reaction window open on Claw", _in_window(state))
    _check("Soren has priority", state.priority == "soren")
    state, _ = _do(state, kind="cast", card_id="guard", target_id="ys")
    soren, ys = state.party
    _check("Soren mana now [G] (paid W for Guard)", mana(soren) == ["G"])

    # Guard resolves first (LIFO), then Claw — fully prevented. _pass_window
    # carries through the End step and into Turn 2's automatic upkeep/intents.
    state = _pass_window(state)
    soren, ys = state.party

    # --- TURN 1 — End step (HP-stable; observed at the next pause) ---------- #
    _say("§A.4 — Turn 1 end step")
    _check("Ys HP 12 (Claw fully prevented)", ys.hp == 12)
    _check("Soren HP 25", soren.hp == 25)
    _check("Skitterling HP 1", state.enemy("skitterling").hp == 1)
    _check("Brute dead", state.enemy("brute") is None)
    _check("Not won yet (Skitterling alive)", state.result is None)

    # --- TURN 2 — Upkeep + Intents ----------------------------------------- #
    _say("§A.4 — Turn 2 upkeep")
    _check("Turn is 2", state.turn == 2)
    _check("Soren drew Mend -> [Sunlance, Steady Blade, Mend]",
           hand_names(soren) == ["Sunlance", "Steady Blade", "Mend"])
    _check("Ys drew Leech -> [Mind Spike, Whispers, Sift, Nightcreep, Leech]",
           hand_names(ys) == ["Mind Spike", "Whispers", "Sift", "Nightcreep", "Leech"])
    _check("Soren capacity 3 (+1 on turn 2)", soren.capacity == 3)
    _check("Ys capacity 3 (+1 on turn 2)", ys.capacity == 3)
    _check("Skitterling re-declares Claw -> Ys",
           state.enemy("skitterling").intent is not None
           and state.enemy("skitterling").intent.target_id == "ys")

    # --- TURN 2 — Soren kills Skitterling; win check fires ------------------ #
    _say("\nTURN 2 — Soren attacks Skitterling (lethal)")
    state, _ = _do(state, kind="attack", target_id="skitterling")
    state = _pass_window(state)
    soren, ys = state.party
    _check("Skitterling dead", state.enemy("skitterling") is None)
    _check("Result = party victory", state.result == "victory")
    _check("Final Soren HP 25", soren.hp == 25)
    _check("Final Ys HP 12", ys.hp == 12)
    _check("Turns taken = 2", state.turn == 2)

    _say("\nALL ASSERTIONS PASSED")
    return state


def main() -> int:
    try:
        run_scenario(verbose=True)
    except AssertionError as exc:
        print(f"\n{exc}")
        return 1
    print("\n§A scenario: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
