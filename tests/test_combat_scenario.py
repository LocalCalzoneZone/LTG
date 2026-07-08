"""Combat engine tests — the §A scenario is the regression spine.

These exercise the engine through its two-function contract only, exactly as the
two clients do.
"""

from __future__ import annotations

import copy

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.harness import run_channeling_scenario, run_scenario
from ltg_combat.repl import play
from ltg_combat.scenario import build_channeling_state, build_state


def test_scenario_passes():
    """The whole §A hand-trace reproduces every asserted state (the proof)."""
    state = run_scenario(verbose=False)
    assert state.result == "victory"
    assert state.turn == 3  # Soren melee/3 + Guard'd Ys; Brute falls on turn 3


def test_channeling_scenario_passes():
    """The §C channeling hand-trace reproduces every asserted state (the proof)."""
    state = run_channeling_scenario(verbose=False)
    # Channeling-specific end state: channels broke, Mira survived the breaking hit.
    # (Mira 7, not 5: Cinder's wounded Ember now does 0 on turn 1 too — the swing
    # re-checks the enemy's current Power at resolution, R-7.)
    assert state.party[0].hp == 7
    assert state.party[0].channels == []


def test_channeling_scenario_is_deterministic():
    a = run_channeling_scenario(verbose=False)
    b = run_channeling_scenario(verbose=False)
    assert [(c.name, c.hp) for c in a.party] == [(c.name, c.hp) for c in b.party]
    assert [(e.name, e.hp) for e in a.enemies] == [(e.name, e.hp) for e in b.enemies]


def test_voluntary_drop_ends_all_channels_and_releases_mana():
    """Voluntary drop appears in legal_actions, ends ALL channels at once, spends
    the cards, and releases the reserved mana into the pool."""
    state = build_channeling_state()

    def do(**kw):
        nonlocal state
        a = next(a for a in legal_actions(state)
                 if all(getattr(a, k) == v for k, v in kw.items()))
        state, _ = apply_action(state, a)

    # Turn 1: hold both channels.
    do(kind="cast", card_id="still_the_blade", target_id="cinder")
    do(kind="pass")
    do(kind="cast", card_id="swarm_hex")
    do(kind="pass")
    mira = state.party[0]
    assert len(mira.channels) == 2
    pool_before = sorted(mira.pool)

    # Voluntary drops are instant-speed and unrestricted (Update 06): offered the
    # moment the channels are held — even on the cast turn. One per channel plus a
    # "drop all". Use the drop-all (no card_id) to end them at once.
    drop = [a for a in legal_actions(state) if a.kind == "drop_channels"]
    assert len(drop) == 3                              # 2 per-channel + drop all
    drop_all = next(a for a in drop if a.card_id is None)
    state, events = apply_action(state, drop_all)
    mira = state.party[0]
    assert mira.channels == []                       # all channels ended at once
    assert "still the blade" in [c.name.lower() for c in mira.graveyard]  # already in graveyard (R-9)
    # Reserved U+B released back into the pool (a respondable trigger opened).
    assert sorted(mira.pool) == sorted(pool_before + ["U", "B"])
    assert any(e.type == "mana_released" for e in events)
    # Cinder's wound aura was lifted with the channel (Power back to 0).
    assert state.enemy("cinder").power_bonus == 0


def test_scenario_is_deterministic():
    """Same inputs -> identical final state, every time."""
    a = run_scenario(verbose=False)
    b = run_scenario(verbose=False)
    assert a.result == b.result
    assert [(c.name, c.hp) for c in a.party] == [(c.name, c.hp) for c in b.party]
    assert [(c.name, c.hp) for c in a.party] == [("Soren", 25), ("Ys", 11)]
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


def test_text_ui_plays_scenario_to_victory():
    """The text UI reaches victory through the engine interface, owning no rules.

    Rather than a brittle fixed script (the §A line is now multi-turn), we drive
    the real menu with a simple deterministic strategy — pick a target when a
    sub-menu is open, otherwise attack, lock mana, take an offensive cast, pass in
    a reaction window, or end the turn — and assert the engine reaches victory."""
    pending_menu: list = []

    def fake_out(line):
        if "\n" in line:
            return
        m = line.strip()
        if m.startswith("1. "):
            pending_menu.clear()
        if ". " in m and m.split(".", 1)[0].isdigit():
            num, label = m.split(". ", 1)
            pending_menu.append((int(num), label))

    calls = {"n": 0}

    def fake_read():
        calls["n"] += 1
        if calls["n"] > 300:
            return "q"  # safety valve — never reached in a healthy engine
        menu = list(pending_menu)

        def pick(pred):
            return next((str(n) for n, l in menu if pred(l)), None)

        return (
            pick(lambda l: l.startswith("Quit"))                 # leave the restart prompt
            or pick(lambda l: "(HP " in l and "Back" not in l)   # a target sub-menu is open
            or pick(lambda l: l.startswith("Attack"))            # attack (inline or opener)
            or pick(lambda l: l.startswith("Lock +1"))           # lock the +1 capacity colour
            or pick(lambda l: l.startswith("Cast") and " on " in l)  # an offensive/targeted cast
            or pick(lambda l: l == "Pass")                       # don't react in a window
            or pick(lambda l: l == "End turn")
            or (str(menu[0][0]) if menu else "q")
        )

    final = play(state=build_state(), read=fake_read, out=fake_out)
    assert final.result == "victory"


def test_text_ui_can_load_scenario_json(tmp_path):
    """The UI can launch a scenario JSON; a loaded §A equals the built default."""
    import json
    from ltg_combat.scenario import SCENARIO_A, load_scenario

    path = tmp_path / "scen.json"
    path.write_text(json.dumps(SCENARIO_A))
    loaded = load_scenario(str(path))
    built = build_state()
    assert [(c.name, c.hp, c.archetype, [x.id for x in c.hand]) for c in loaded.party] \
        == [(c.name, c.hp, c.archetype, [x.id for x in c.hand]) for c in built.party]
    assert [(e.name, e.hp, e.level) for e in loaded.enemies] \
        == [(e.name, e.hp, e.level) for e in built.enemies]
