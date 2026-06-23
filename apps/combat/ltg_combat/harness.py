"""The scripted-scenario harness — the engine's correctness proof.

This drives the §A (minions) and §C (channeling) fights to completion through
ONLY `legal_actions` / `apply_action`, asserting the expected state at every
marked step. It owns zero rules: it reads state to decide which scripted choice
to pick, and reads the event log to confirm what happened — but it never computes
legality or damage. Both scenarios are the regression spine.

Run it directly (`python -m ltg_combat harness`) for a readable PASS/FAIL trace,
or call `run_scenario()` / `run_channeling_scenario()` from a test. Every
assertion is deterministic.
"""

from __future__ import annotations

from typing import List, Optional

from .engine import apply_action, legal_actions
from .scenario import build_channeling_state, build_state, hand_names, mana
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
    _check("Soren proactive action spent", soren.acted_mode == "attack")
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
    # carries through the End step and pauses at Turn 2's first decision: the
    # capacity-colour choice (which comes BEFORE the draw).
    state = _pass_window(state)
    soren, ys = state.party

    # --- TURN 1 — End step (HP-stable; observed at the next pause) ---------- #
    _say("§A.4 — Turn 1 end step")
    _check("Ys HP 12 (Claw fully prevented)", ys.hp == 12)
    _check("Soren HP 25", soren.hp == 25)
    _check("Skitterling HP 1", state.enemy("skitterling").hp == 1)
    _check("Brute dead", state.enemy("brute") is None)
    _check("Not won yet (Skitterling alive)", state.result is None)
    _check("Turn is 2", state.turn == 2)

    # --- TURN 2 — Capacity colour choice, BEFORE the draw ------------------ #
    _say("§A.4 — Turn 2 capacity choice (pre-draw)")
    opening = legal_actions(state)
    _check("Turn 2 opens on Soren's capacity choice",
           bool(opening) and all(a.kind == "choose_mana" for a in opening)
           and opening[0].actor_id == "soren")
    _check("Choice precedes the draw: Soren still capacity 2, no Mend yet",
           soren.capacity == 2 and "Mend" not in hand_names(soren))
    # Each character locks a colour (the colour doesn't affect §A's asserted
    # values; the draw/refresh/intents then run automatically).
    state, _ = _do(state, kind="choose_mana", actor_id="soren", color="G")
    state, _ = _do(state, kind="choose_mana", actor_id="ys", color="U")
    soren, ys = state.party

    # --- TURN 2 — Upkeep (draw + refresh) + Intents ------------------------ #
    _say("§A.4 — Turn 2 upkeep")
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


def run_channeling_scenario(verbose: bool = False) -> GameState:
    """Play §C; assert every marked state (multi-channel casting, reservation, a
    continuous disable aura, a recurring upkeep engine, reduced-below-threshold
    does-not-break, and an all-or-nothing break that releases reserved mana as a
    respondable trigger). Raises AssertionError on any mismatch."""
    global _VERBOSE
    _VERBOSE = verbose

    state = build_channeling_state()
    (mira,) = state.party
    cinder, maul = state.enemies

    # --- §C.3 Setup ------------------------------------------------------- #
    _say("§C.3 — setup")
    _check("Mira HP 15", mira.hp == 15)
    _check("Mira hand [Still the Blade, Swarm Hex]",
           hand_names(mira) == ["Still the Blade", "Swarm Hex"])
    _check("Mira capacity 4 [U,U,B,B]", mira.mana_colors == ["U", "U", "B", "B"])
    _check("No channels", mira.channels == [])
    _check("No tokens", state.tokens == [])
    _check("Cinder HP 6", cinder.hp == 6)
    _check("Maul HP 10", maul.hp == 10)

    # --- TURN 1 — Player: cast two sorcery-speed channels in one Cast turn -- #
    _say("\nTURN 1 — Mira casts Still the Blade on Cinder")
    state, ev = _do(state, kind="cast", card_id="still_the_blade", target_id="cinder")
    (mira,) = state.party
    _say("§C.4 — Turn 1 upkeep (from events)")
    draws = {e.data.get("character"): e.data.get("card_name")
             for e in ev if e.type == "draw"}
    _check("Mira drew Mind Spike", draws.get("mira") == "Mind Spike")
    refresh = next((e for e in ev if e.type == "mana_refresh"), None)
    _check("Turn 1 available mana 4", refresh is not None and len(refresh.data["pool"]) == 4)
    intents = {e.data["enemy"]: e.data["target"] for e in ev if e.type == "intent_declared"}
    _check("Cinder Ember → Mira", intents.get("cinder") == "mira")
    _check("Maul Crush → Mira", intents.get("maul") == "mira")

    state = _pass_window(state)  # Still the Blade resolves → held
    _say("TURN 1 — Mira casts Swarm Hex")
    state, _ = _do(state, kind="cast", card_id="swarm_hex")
    state = _pass_window(state)  # Swarm Hex resolves → held
    (mira,) = state.party

    _say("§C.4 — Turn 1 after both channels")
    _check("Mira holds 2 channels", len(mira.channels) == 2)
    _check("Reserved 2 (1 U + 1 B)", sorted(mira.reserved) == ["B", "U"])
    _check("Available mana 2 [U,B]", sorted(mana(mira)) == ["B", "U"])
    _check("Cinder's Ember intent disabled",
           state.enemy("cinder").intent is None
           and "attack" in state.enemy("cinder").disabled_intent_types)

    state, _ = _do(state, kind="end_turn", actor_id="mira")

    # --- TURN 1 — Enemy: Cinder disabled; Maul Crush, Mira Parries (no break) #
    _say("\nTURN 1 — Maul executes Crush; Mira parries")
    _check("Reaction window: Maul's Crush targets Mira",
           _in_window(state) and state.stack[-1].target_id == "mira"
           and state.stack[-1].label == "Crush")
    state, _ = _do(state, kind="parry", actor_id="mira")  # reduce 5 → 3
    state = _pass_window(state)  # (parry already passed; carry to next pause)
    (mira,) = state.party
    _check("Mira HP 12 (5 parried to 3)", mira.hp == 12)
    _check("Both channels still held (hit reduced below 4)", len(mira.channels) == 2)

    # --- TURN 2 — Upkeep: capacity choice (pre-draw), then recurring engine -- #
    _check("Turn is 2", state.turn == 2)
    _say("§C.4 — Turn 2 capacity choice + recurring")
    opening = legal_actions(state)
    _check("Turn 2 opens on Mira's capacity choice",
           bool(opening) and all(a.kind == "choose_mana" for a in opening))
    state, _ = _do(state, kind="choose_mana", actor_id="mira", color="U")
    (mira,) = state.party
    _check("One Wisp created", len(state.tokens) == 1 and state.tokens[0].name == "Wisp")
    _check("Mira HP 11 (Swarm Hex recurring lose_life 1)", mira.hp == 11)
    _check("Capacity 5", mira.capacity == 5)
    _check("Reserved still 2", len(mira.reserved) == 2)
    _check("Available 3", len(mana(mira)) == 3)
    _check("Mira hand [Mind Spike, Leech]", hand_names(mira) == ["Mind Spike", "Leech"])
    _check("Cinder still disabled, no intent",
           state.enemy("cinder").intent is None
           and "attack" in state.enemy("cinder").disabled_intent_types)
    _check("Maul re-declares Crush → Mira",
           state.enemy("maul").intent is not None
           and state.enemy("maul").intent.target_id == "mira")

    # --- TURN 2 — Player: Mind Spike on Maul, then the Wisp attacks --------- #
    _say("\nTURN 2 — Mira casts Mind Spike on Maul")
    state, _ = _do(state, kind="cast", card_id="mind_spike", target_id="maul")
    state = _pass_window(state)
    (mira,) = state.party
    _check("Maul HP 8 (Mind Spike 2)", state.enemy("maul").hp == 8)
    _check("Available mana 2", len(mana(mira)) == 2)

    state, _ = _do(state, kind="end_turn", actor_id="mira")  # -> Wisp acts
    _check("Wisp's attack on Cinder is on the stack",
           _in_window(state) and state.stack[-1].target_id == "cinder")
    state, _ = _do(state, kind="pass", actor_id="mira")  # Wisp attack resolves
    _check("Cinder HP 5 (Wisp 1)", state.enemy("cinder").hp == 5)

    # --- TURN 2 — Enemy: Maul Crush, unmitigated → BREAK, release, Leech ---- #
    _say("\nTURN 2 — Maul executes Crush; Mira takes it (break)")
    _check("Maul's Crush targets Mira",
           _in_window(state) and state.stack[-1].label == "Crush"
           and state.stack[-1].target_id == "mira")
    state, _ = _do(state, kind="pass", actor_id="mira")  # take the hit: 5 ≥ 4 → break
    (mira,) = state.party
    _check("Breaking hit resolved first: Mira HP 6", mira.hp == 6)
    _check("All channels ended (0 held)", len(mira.channels) == 0)
    _check("Cinder no longer disabled",
           "attack" not in state.enemy("cinder").disabled_intent_types)
    _check("Reserved mana released into pool (≥ 1 B available)", "B" in mana(mira))
    _check("Release trigger is on the stack (respondable)",
           _in_window(state) and state.stack[-1].label == "Mana Release")

    _say("TURN 2 — Mira casts Leech with the released mana")
    state, _ = _do(state, kind="cast", card_id="leech", target_id="maul")
    state = _pass_window(state)  # Leech resolves, then the release trigger resolves
    (mira,) = state.party
    _check("Maul HP 7 (Leech 1)", state.enemy("maul").hp == 7)
    _check("Mira HP 7 (Leech heal 1)", mira.hp == 7)
    _check("Still the Blade & Swarm Hex spent (not in hand, 0 channels)",
           len(mira.channels) == 0
           and "Still the Blade" not in hand_names(mira)
           and "Swarm Hex" not in hand_names(mira))

    _say("\nALL §C ASSERTIONS PASSED")
    return state


def main() -> int:
    try:
        run_scenario(verbose=True)
        print("\n§A scenario: PASS")
        run_channeling_scenario(verbose=True)
        print("\n§C scenario: PASS")
    except AssertionError as exc:
        print(f"\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
