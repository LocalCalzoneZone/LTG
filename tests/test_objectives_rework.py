"""The objectives rework (beta playtest 2026-08-30): a race the party solves by
one-shotting the marked minion on turn 1 is a checkbox, not a set piece.

- RACE GUARDS: while any guard body stands undefeated, the party cannot TARGET
  the marked enemy — basic attacks and spell picks alike refuse it; area damage
  still clips it. The last guard's fall is logged as a beat. Guard ids are pool
  ids, expanded over clones at build.
- DEADLINE: the hard clock — defeat every enemy within N rounds or the phase is
  lost. Nothing interacts with it.
"""

from __future__ import annotations

import pytest

from ltg_combat.engine import _begin_turn, _end_step, apply_action, legal_actions
from ltg_combat.scenario import scale_encounter, state_from_dict
from ltg_core.schema import EncounterObjective

from tests.test_design_update_12 import _drive_round, _enemy, _hero, _pick


def _race_state(guards=("warden",), layout_extra=()):
    enemies = [_enemy("ritualist", hp=8), _enemy("warden", hp=6),
               _enemy("husk", hp=4)]
    spec = scale_encounter({
        "party": [_hero(power=3)],
        "enemies": enemies,
        "layouts": {"1": ["ritualist", "warden", "husk", *layout_extra]},
        "objective": {"kind": "race", "target": "ritualist", "turns": 4,
                      "guards": list(guards), "fail": "escalate",
                      "escalation": {"telegraph": "The Rite",
                                     "verbs": [{"kind": "deal_damage", "amount": 2,
                                                "target": {"mode": "all",
                                                           "side": "ally"}}]}},
    }, party_size=1)
    return state_from_dict(spec)


def test_a_guarded_target_cannot_be_attacked():
    st = _race_state()
    assert _pick(st, "attack", target_id="ritualist") is None   # shielded
    assert _pick(st, "attack", target_id="warden") is not None  # the guard is fair game


def test_killing_the_guard_exposes_the_target():
    st = _race_state()
    for _ in range(4):   # warden hp 6, hero power 3 — two swings over two turns
        a = _pick(st, "attack", target_id="warden")
        if a is not None:
            st = apply_action(st, a)[0]
            while st.stack:
                p = _pick(st, "pass")
                if p is None:
                    break
                st = apply_action(st, p)[0]
        if st.enemy("warden") is None:
            break
        st = _drive_round(st)
    assert st.enemy("warden") is None
    assert any(e.type == "guards_down" for e in st.log)
    st = _drive_round(st)      # a fresh turn: the sword is available again
    assert _pick(st, "attack", target_id="ritualist") is not None


def test_guard_clones_all_count():
    """Guards are POOL ids: a layout that fields the warden twice keeps the
    shield up until BOTH bodies fall."""
    st = _race_state(layout_extra=("warden",))
    assert [g for g in st.objective.guards] == ["warden", "warden_2"]
    st.enemies = [e for e in st.enemies if e.id != "warden"]   # one body down
    assert _pick(st, "attack", target_id="ritualist") is None  # still shielded


def test_the_schema_rejects_guardless_shapes_only_where_illegal():
    with pytest.raises(Exception):
        EncounterObjective.model_validate(
            {"kind": "survive", "turns": 3, "guards": ["x"]})
    EncounterObjective.model_validate(     # race guards are legal
        {"kind": "race", "target": "t", "turns": 3, "guards": ["g"],
         "fail": "defeat"})


# --------------------------------------------------------------------------- #
# Deadline
# --------------------------------------------------------------------------- #
def _deadline_state(turns=2):
    return state_from_dict({
        "party": [_hero(power=1)],
        "enemies": [_enemy("brute", hp=50)],
        "objective": {"kind": "deadline", "turns": turns},
    })


def test_the_deadline_defeats_a_slow_party():
    st = _deadline_state(turns=2)
    st = _drive_round(st)          # round 1 passes idle
    st = _drive_round(st)          # round 2 completes — clock expires
    assert st.result == "defeat"
    assert any(e.type == "loss" and e.data.get("objective") == "deadline"
               for e in st.log)


def test_killing_everything_beats_the_clock():
    st = state_from_dict({
        "party": [_hero(power=60)],
        "enemies": [_enemy("brute", hp=10)],
        "objective": {"kind": "deadline", "turns": 3},
    })
    a = _pick(st, "attack", target_id="brute")
    st = apply_action(st, a)[0]
    while st.stack and st.result is None:
        p = _pick(st, "pass")
        if p is None:
            break
        st = apply_action(st, p)[0]
    assert st.result == "victory"


def test_deadline_schema_shape():
    EncounterObjective.model_validate({"kind": "deadline", "turns": 5})
    with pytest.raises(Exception):
        EncounterObjective.model_validate(
            {"kind": "deadline", "turns": 5, "target": "x"})


# --------------------------------------------------------------------------- #
# The generation gate
# --------------------------------------------------------------------------- #
def test_generation_requires_guards_and_mounting_pressure():
    from ltg_game_server import llm
    race = {"objective": {"kind": "race", "target": "t", "turns": 4}}
    assert any("guards" in p for p in llm._objective_problems(race))
    ok = {"objective": {"kind": "race", "target": "t", "turns": 4,
                        "guards": ["g"]}}
    assert llm._objective_problems(ok) == []
    lazy = {"objective": {"kind": "survive", "turns": 5,
                          "reinforcements": [{"turn": 3}]}}
    assert any("MOUNT" in p for p in llm._objective_problems(lazy))
    clock = {"objective": {"kind": "deadline", "turns": 9}}
    assert any("4-6" in p for p in llm._objective_problems(clock))
    assert llm._objective_problems({}) == []
