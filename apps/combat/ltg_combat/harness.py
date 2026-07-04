"""The scripted-scenario harness — the engine's correctness proof.

This drives the §A (minions) and §C (channeling) fights to completion through
ONLY `legal_actions` / `apply_action`, asserting the expected state at the marked
steps. It owns zero rules: it reads state to decide which scripted choice to pick,
and reads the event log to confirm what happened — but it never computes legality
or damage. Both scenarios are the regression spine, rewritten for Design Update 01
(attack modes + rows, the temp_mod HP model, parameterised prevent, no `disable`).

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


def _locks(state: GameState) -> GameState:
    """Resolve every pending capacity-colour lock at the start of a turn (Green for
    Soren, Blue for the casters — colour is irrelevant to these asserted values)."""
    while True:
        choices = [a for a in legal_actions(state) if a.kind == "choose_mana"]
        if not choices:
            return state
        state, _ = apply_action(state, choices[0])


# --------------------------------------------------------------------------- #
# §A — minions (Soren melee/3, Ys ranged/1)
# --------------------------------------------------------------------------- #
def run_scenario(verbose: bool = False, state: Optional[GameState] = None) -> GameState:
    """Play §A; assert the marked states. Raises AssertionError on any mismatch.

    `state` lets a caller inject an equivalent setup (e.g. one assembled from
    Deckbuilder loadouts via the cockpit) and prove it plays to the same result;
    it defaults to the canonical §A setup."""
    global _VERBOSE
    _VERBOSE = verbose

    state = build_state() if state is None else state
    soren, ys = state.party

    _say("§A.3 — setup (Design Update R-3 profiles)")
    _check("Soren is melee/Power 3", soren.power == 3 and soren.attack_mode == "melee")
    _check("Ys is ranged/Power 1", ys.power == 1 and ys.attack_mode == "ranged")
    _check("Soren opening hand [Guard, Sunlance]", hand_names(soren) == ["Guard", "Sunlance"])
    _check("Skitterling HP 3", state.enemy("skitterling").hp == 3)
    _check("Brute HP 8", state.enemy("brute").hp == 8)

    # --- TURN 1 — Soren's melee one-shots Skitterling (Power 3 ≥ 3 HP) ------- #
    _say("\nTURN 1 — Soren attacks Skitterling (melee 3, lethal)")
    state, ev = _do(state, kind="attack", target_id="skitterling")
    intents = {e.data["enemy"]: e.data["target"] for e in _events_of_type(ev, "intent_declared")}
    _check("Both enemies declare against Ys (lowest effective HP)",
           intents.get("skitterling") == "ys" and intents.get("brute") == "ys")
    state = _pass_window(state)
    _check("Skitterling dies to one melee hit", state.enemy("skitterling") is None)

    _say("TURN 1 — Soren guards Ys (instant: prevent combat_damage)")
    state, _ = _do(state, kind="cast", card_id="guard", target_id="ys")  # free instant
    state = _pass_window(state)
    _check("Ys holds a prevent(combat_damage) tag",
           any(t.parameter == "combat_damage" for t in state.character("ys").prevent_tags))
    state, _ = _do(state, kind="end_turn", actor_id="soren")
    state, _ = _do(state, kind="end_turn", actor_id="ys")

    # Enemy step: Brute's Smash → Ys is fully nullified by Guard. Carry to Turn 2.
    state = _pass_window(state)
    _check("Ys HP 15 — Brute's Smash was prevented", state.character("ys").hp == 15)
    _check("Brute still up at 8", state.enemy("brute").hp == 8)
    _check("Now Turn 2", state.turn == 2)

    # --- TURN 2 — Soren + Ys chip Brute; Guard has lapsed, so Smash lands ---- #
    _say("\nTURN 2 — Soren attacks Brute, Ys Mind Spikes it")
    state = _locks(state)
    state, _ = _do(state, kind="attack", target_id="brute")  # melee 3 → Brute 5
    state = _pass_window(state)
    _check("Brute HP 5 after Soren's melee", state.enemy("brute").hp == 5)
    state, _ = _do(state, kind="end_turn", actor_id="soren")
    state, _ = _do(state, kind="cast", card_id="mind_spike", target_id="brute")  # 2 → 3
    state = _pass_window(state)
    _check("Brute HP 3 after Mind Spike", state.enemy("brute").hp == 3)
    state, _ = _do(state, kind="end_turn", actor_id="ys")
    state = _pass_window(state)  # Brute's Smash 4 → Ys (no Guard this turn)
    _check("Ys HP 11 — took Brute's Smash 4", state.character("ys").hp == 11)
    _check("Now Turn 3", state.turn == 3)

    # --- TURN 3 — Soren finishes Brute before it can act -------------------- #
    _say("\nTURN 3 — Soren kills Brute (lethal)")
    state = _locks(state)
    state, _ = _do(state, kind="attack", target_id="brute")  # melee 3 → 0
    state = _pass_window(state)
    _check("Result = party victory", state.result == "victory")
    _check("Final Soren HP 25", state.character("soren").hp == 25)
    _check("Final Ys HP 11", state.character("ys").hp == 11)

    _say("\nALL §A ASSERTIONS PASSED")
    return state


# --------------------------------------------------------------------------- #
# §C — channeling (Mira: a wound aura + a token engine, reservation, break)
# --------------------------------------------------------------------------- #
def run_channeling_scenario(verbose: bool = False, state: Optional[GameState] = None) -> GameState:
    """Play §C; assert the marked states (two channels in one Cast turn, mana
    reservation, a continuous wound aura that blunts an attacker, a recurring
    upkeep token engine with an ally intent + Ally step, a parry that keeps a hit
    under the break threshold, and an all-or-nothing break that lifts the aura and
    releases the reserved mana). Raises AssertionError on any mismatch."""
    global _VERBOSE
    _VERBOSE = verbose

    state = build_channeling_state() if state is None else state
    (mira,) = state.party

    _say("§C.3 — setup")
    _check("Mira is a ranged/1 Channeler", mira.power == 1 and mira.attack_mode == "ranged")
    _check("Mira hand [Still the Blade, Swarm Hex]",
           hand_names(mira) == ["Still the Blade", "Swarm Hex"])
    _check("Mira capacity 4 [U,U,B,B]", mira.mana_colors == ["U", "U", "B", "B"])
    _check("Cinder HP 6 / Maul HP 10", state.enemy("cinder").hp == 6 and state.enemy("maul").hp == 10)

    # --- TURN 1 — channel both in one Cast turn ----------------------------- #
    _say("\nTURN 1 — Mira channels Still the Blade on Cinder, then Swarm Hex")
    state, _ = _do(state, kind="cast", card_id="still_the_blade", target_id="cinder")
    state = _pass_window(state)  # → held: Cinder takes a continuous −2/−0 wound
    state, _ = _do(state, kind="cast", card_id="swarm_hex")
    state = _pass_window(state)  # → held
    (mira,) = state.party
    _check("Mira holds 2 channels", len(mira.channels) == 2)
    _check("Reserved 1 U + 1 B", sorted(mira.reserved) == ["B", "U"])
    _check("Cinder is wounded -2 Power", state.enemy("cinder").power_bonus == -2)
    state, _ = _do(state, kind="end_turn", actor_id="mira")

    # Enemy step: Cinder's Ember was declared at 2, but the −2 wound now blunts it AT
    # resolution (R-7) — everything re-checks when it resolves — so it lands for 0; then
    # Maul's Crush, which Mira parries below the break threshold (Cinder Lv2 acts before Maul Lv4).
    _say("TURN 1 — Cinder's wounded Ember does 0; Mira parries Maul's Crush (no break)")
    state, _ = _do(state, kind="pass", actor_id="mira")  # Ember 2−2 wound → 0 → Mira 15
    _check("Mira HP 15 after Ember 0 (wound blunts it at resolution)",
           state.character("mira").hp == 15)
    # Crush 4, mitigated by X=ceil(Mira Power 1 / 2)=1 → 3 lands (under the break threshold).
    state, _ = _do(state, kind="mitigate", actor_id="mira", target_id="mira")
    state = _pass_window(state)
    (mira,) = state.party
    _check("Mira HP 12 after the mitigated Crush", mira.hp == 12)
    _check("Both channels survive (3 < break threshold 4)", len(mira.channels) == 2)
    _check("Now Turn 2", state.turn == 2)

    # --- TURN 2 — upkeep token engine + the wound bites the new declaration -- #
    _say("\nTURN 2 — Swarm Hex spawns a Wisp; Cinder's Ember is wounded to 0")
    state = _locks(state)
    (mira,) = state.party
    _check("A Wisp joined (Swarm Hex upkeep)", len(state.tokens) == 1 and state.tokens[0].name == "Wisp")
    _check("Mira HP 11 (Swarm Hex lose 1)", mira.hp == 11)
    _check("Cinder's re-declared Ember is wounded to 0",
           state.enemy("cinder").intent is not None
           and state.enemy("cinder").intent.effects[0].amount == 0)

    _say("TURN 2 — Mira Mind Spikes Maul; the Wisp attacks Cinder")
    state, _ = _do(state, kind="cast", card_id="mind_spike", target_id="maul")  # 2 → 8
    state = _pass_window(state)
    _check("Maul HP 8 after Mind Spike", state.enemy("maul").hp == 8)
    state, _ = _do(state, kind="end_turn", actor_id="mira")
    state, _ = _do(state, kind="pass", actor_id="mira")  # Ally step: Wisp attacks Cinder
    _check("Cinder HP 5 (Wisp 1)", state.enemy("cinder").hp == 5)

    # --- TURN 2 enemy step — Ember does 0; Maul's Crush breaks concentration -- #
    _say("TURN 2 — Cinder's Ember does 0; Mira takes Maul's Crush (break)")
    state, _ = _do(state, kind="pass", actor_id="mira")  # Ember 0 → Mira unchanged
    _check("Mira HP 11 after Ember 0", state.character("mira").hp == 11)
    state, _ = _do(state, kind="pass", actor_id="mira")  # take Crush 4 unmitigated → break (4 ≥ 4)
    (mira,) = state.party
    _check("Mira HP 7 after Crush 4", mira.hp == 7)
    _check("All channels broke (0 held)", len(mira.channels) == 0)
    _check("Cinder's wound lifted on break (Power back to 0)",
           state.enemy("cinder").power_bonus == 0)
    _check("Reserved mana released into the pool",
           "B" in mira.pool or "U" in mira.pool)
    # Mana release no longer uses the stack — it just happens, opening no trigger/window.
    _check("Mana Release does not go on the stack",
           not any(getattr(s, "label", None) == "Mana Release" for s in state.stack))

    state = _pass_window(state)
    _check("Game still going (not a loss)", state.result is None)

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
