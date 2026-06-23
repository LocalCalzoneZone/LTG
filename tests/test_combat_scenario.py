"""Combat engine tests — the §A scenario is the regression spine.

These exercise the engine through its two-function contract only, exactly as the
two clients do.
"""

from __future__ import annotations

import copy

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.harness import run_scenario
from ltg_combat.repl import play
from ltg_combat.scenario import build_state


def test_scenario_passes():
    """The whole §A hand-trace reproduces every asserted state (the proof)."""
    state = run_scenario(verbose=False)
    assert state.result == "victory"
    assert state.turn == 2


def test_scenario_is_deterministic():
    """Same inputs -> identical final state, every time."""
    a = run_scenario(verbose=False)
    b = run_scenario(verbose=False)
    assert a.result == b.result
    assert [(c.name, c.hp) for c in a.party] == [(c.name, c.hp) for c in b.party]
    assert [(c.name, c.hp) for c in a.party] == [("Soren", 25), ("Ys", 12)]
    assert a.enemies == [] and b.enemies == []


def test_apply_action_does_not_mutate_input():
    """State is a value: apply_action must not touch the state handed to it."""
    state = build_state()
    snapshot = copy.deepcopy(state)
    action = legal_actions(state)[0]
    apply_action(state, action)
    # The original is unchanged (still pre-upkeep, same hands, empty log).
    assert state.turn == snapshot.turn and state.phase == snapshot.phase
    assert [c.hp for c in state.party] == [c.hp for c in snapshot.party]
    assert state.log == [] and not state.stack


def test_legal_actions_is_read_only():
    """Calling legal_actions emits nothing and changes nothing."""
    state = build_state()
    before = copy.deepcopy(state)
    legal_actions(state)
    assert state.log == before.log == []
    assert state.phase == before.phase


def test_first_decision_is_sorens_main_phase():
    """The opening prelude (upkeep + intents) runs automatically; the first
    player decision is Soren's main phase with his proactive options present."""
    actions = legal_actions(build_state())
    kinds = {a.kind for a in actions}
    assert "attack" in kinds and "end_turn" in kinds
    # Soren can attack either enemy and cast his sorcery (Sunlance).
    labels = [a.label for a in actions]
    assert any("Attack Skitterling" in s for s in labels)
    assert any("Sunlance" in s for s in labels)


def test_illegal_action_is_rejected():
    """An action not in the legal set is refused (the engine is the authority)."""
    import pytest
    from ltg_combat.state import Action

    state = build_state()
    bogus = Action(kind="attack", actor_id="ys", target_id="nope")
    with pytest.raises(ValueError):
        apply_action(state, bogus)


def test_repl_plays_scenario_to_victory():
    """Client B reaches the same result through the engine interface, owning no
    rules. We feed the §A choices as menu numbers via injected I/O."""
    # The scripted picks: each step selects a legal menu option by matching label
    # substrings, so the test fails loudly if the menu shape drifts.
    script = [
        "Attack Skitterling",   # T1 Soren attacks
        "Pass", "Pass",          # resolve the attack
        "End turn",              # Soren ends
        "Unmake on Brute",      # T1 Ys casts Unmake on Brute (engine offers both enemies)
        "Pass", "Pass",          # resolve Unmake
        "End turn",              # Ys ends
        "Guard on Ys",          # T1 Soren reacts to Claw with Guard on Ys
        "Pass", "Pass", "Pass", "Pass",  # resolve Guard then Claw
        "Attack Skitterling",   # T2 Soren attacks (lethal)
        "Pass", "Pass",          # resolve -> victory
    ]
    outputs: list = []
    pending_menu: list = []

    def fake_out(line):
        outputs.append(line)
        # Track the most recently printed numbered menu so we can map a label.
        if line.strip().startswith("1. "):
            pending_menu.clear()
        m = line.strip()
        if m[:2].rstrip(".").isdigit() and ". " in m:
            num, label = m.split(". ", 1)
            pending_menu.append((int(num), label))

    step = {"i": 0}

    def fake_read():
        want = script[step["i"]]
        step["i"] += 1
        # Find the menu entry whose label contains the wanted substring.
        for num, label in pending_menu:
            if want in label:
                return str(num)
        raise AssertionError(f"no menu option matching '{want}' in {pending_menu}")

    final = play(state=build_state(), read=fake_read, out=fake_out)
    assert final.result == "victory"
    assert step["i"] == len(script)  # every scripted choice was consumed
