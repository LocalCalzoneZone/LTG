"""Boss pressure (beta playtest 2026-08-30): the endgame problem was that the
best line was always "burn the minions, leave the boss to last" — by the time
the ≤25% enrage fired, the board was empty and the fury was a joke.

Two dials answer it, both authored on the enemy block and enforced on generated
bosses: `enrage_round` (fury boils over UNBIDDEN at the start of that round —
the boss will not wait to be bloodied) and `neglect` (a boss that goes a whole
round unhurt, from round 2, gains permanent +N/+N — ignoring the centerpiece
compounds)."""

from __future__ import annotations

from ltg_combat.engine import _begin_turn, _end_step, apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _char(cid, power=3, hp=30):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": "front", "attack_mode": "melee",
            "library": []}


def _boss(**kw):
    e = {"id": "boss", "name": "boss", "hp": 20, "level": 5, "is_boss": True,
         "intent": {"name": "Smash", "amount": 3, "action_type": "ability",
                    "intent_type": "attack", "targeting": "lowest_hp_party",
                    "mode": "melee"}}
    e.update(kw)
    return e


def _minion(eid="minion"):
    return {"id": eid, "name": eid, "hp": 10, "level": 2,
            "intent": {"name": "Jab", "amount": 1, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _attack(st, target_id):
    a = next(a for a in legal_actions(st)
             if a.kind == "attack" and a.target_id == target_id)
    st = apply_action(st, a)[0]
    while st.stack:
        p = next((x for x in legal_actions(st) if x.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


# --------------------------------------------------------------------------- #
# Timed enrage
# --------------------------------------------------------------------------- #
def test_the_boss_enrages_on_schedule_at_full_hp():
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(enrage_round=3)]})
    boss = st.enemies[0]
    assert not boss.enraged
    st.turn = 2
    _begin_turn(st)
    assert not boss.enraged                    # not yet — round 3 is the fuse
    st.turn = 3
    _begin_turn(st)
    assert boss.enraged                        # full HP; fury came anyway
    assert any(ev.type == "enrage" and ev.data.get("timed") for ev in st.log)


def test_the_hp_enrage_still_fires_first_when_bloodied_early():
    st = state_from_dict({"party": [_char("p", power=16)],
                          "enemies": [_boss(enrage_round=5)]})
    st = _attack(st, "boss")                   # 16 of 20 — well under 25%
    assert st.enemies[0].enraged
    st.turn = 5
    _begin_turn(st)                            # the timed path must not re-fire
    assert sum(1 for ev in st.log if ev.type == "enrage" and ev.data.get("timed")) == 0


def test_no_enrage_round_means_the_old_behaviour():
    st = state_from_dict({"party": [_char("p")], "enemies": [_boss()]})
    st.turn = 9
    _begin_turn(st)
    assert not st.enemies[0].enraged


# --------------------------------------------------------------------------- #
# Neglect
# --------------------------------------------------------------------------- #
def test_an_unhurt_boss_swells_at_the_end_step():
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(neglect=1), _minion()]})
    st.turn = 2
    _begin_turn(st)
    st = _attack(st, "minion")                 # the party ignores the boss…
    _end_step(st)
    boss = st.enemy("boss")                    # apply_action returns a new state
    assert boss.power == 4 and boss.max_hp == 21 and boss.counters == 1
    assert any(ev.type == "neglect" for ev in st.log)


def test_hitting_the_boss_stops_the_swelling():
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(neglect=1), _minion()]})
    st.turn = 2
    _begin_turn(st)
    st = _attack(st, "boss")
    _end_step(st)
    boss = st.enemy("boss")
    assert boss.counters == 0                  # bloodied this round: no growth
    assert not any(ev.type == "neglect" for ev in st.log)


def test_round_one_is_a_grace_round():
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(neglect=1)]})
    assert st.turn == 1
    _begin_turn(st)
    _end_step(st)
    assert st.enemies[0].counters == 0         # setup breath — no punishment yet


def test_neglect_compounds_round_over_round():
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(neglect=2), _minion()]})
    boss = st.enemies[0]
    for turn in (2, 3):
        st.turn = turn
        _begin_turn(st)
        _end_step(st)
    assert boss.power == 3 + 4 and boss.counters == 4


# --------------------------------------------------------------------------- #
# §D23-5 — neglect counts every party-sourced HP drop
# --------------------------------------------------------------------------- #
def _poison_card(cid="venom", amount=2):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "poison", "amount": amount,
                         "target": {"mode": "chosen", "side": "enemy",
                                    "targeted": True}}]}


def test_a_poisoned_boss_does_not_swell_from_neglect():
    """The bug this fixes: a poison deck whittling the boss down was told it had
    NEGLECTED the boss — because only `_deal_damage` set the flag — and the boss
    grew every round for winning correctly."""
    st = state_from_dict({"party": [_char("p")], "enemies": [_boss(neglect=2)]})
    boss = st.enemies[0]
    boss.poison_counters = 2
    st.turn = 3
    _begin_turn(st)                # clears hurt_this_round
    from ltg_combat.engine import _tick_afflictions_one
    _tick_afflictions_one(st, boss)
    _end_step(st)
    assert boss.max_hp == 20, "the poison tick counts as hurting it"


def test_life_loss_counts_as_hurting_the_boss():
    from ltg_combat.engine import _r_lose_life
    from ltg_core.schema import LoseLife
    st = state_from_dict({"party": [_char("p")], "enemies": [_boss(neglect=2)]})
    boss = st.enemies[0]
    st.turn = 3
    _begin_turn(st)
    _r_lose_life(st, None, LoseLife(amount=3, target={"mode": "self"}), boss, {})
    _end_step(st)
    assert boss.max_hp == 20


def test_a_wound_counts_as_hurting_the_boss():
    from ltg_combat.engine import _r_wound
    from ltg_core.schema import Wound
    st = state_from_dict({"party": [_char("p")], "enemies": [_boss(neglect=2)]})
    boss = st.enemies[0]
    st.turn = 3
    _begin_turn(st)
    _r_wound(st, None, Wound(power=1, toughness=2, target={"mode": "self"}), boss, {})
    _end_step(st)
    assert boss.max_hp == 20


def test_a_genuinely_ignored_boss_still_swells():
    """The control — the dial has to keep its teeth."""
    st = state_from_dict({"party": [_char("p")], "enemies": [_boss(neglect=2)]})
    boss = st.enemies[0]
    st.turn = 3
    _begin_turn(st)
    _end_step(st)
    assert boss.max_hp == 22


# --------------------------------------------------------------------------- #
# §D23-5 — one-beat enrage
# --------------------------------------------------------------------------- #
_ENRAGE_COMP = {"id": "fury", "archetype": "Burst", "timing": "reactive",
                "trigger": "on_enrage", "once_per_encounter": True,
                "priority": 10, "target_rule": "valuation",
                "telegraph": "Wrathfall",
                "verbs": [{"kind": "deal_damage", "amount": 4,
                           "target": {"mode": "chosen", "side": "ally",
                                      "targeted": True}}]}


def test_the_timed_enrage_lands_its_component_in_the_same_beat():
    """§D23-5. The announcement used to arrive at Upkeep and the blow whenever
    the next unrelated resolution happened to open a window — two events, turns
    apart, reading as a bug."""
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(enrage_round=3,
                                            components=[dict(_ENRAGE_COMP)])]})
    st.turn = 3
    _begin_turn(st)
    assert st.enemies[0].enraged
    assert st.stack and st.stack[-1].label == "Wrathfall"


def test_the_hp_enrage_still_waits_for_its_reaction_window():
    """The ≤25% crossing keeps the ordinary on_enrage path — it happens
    mid-combat, where the next window is right there."""
    st = state_from_dict({"party": [_char("p", power=16)],
                          "enemies": [_boss(components=[dict(_ENRAGE_COMP)])]})
    st = _attack(st, "boss")
    assert st.enemies[0].enraged
    assert any(ev.type == "enemy_react" for ev in st.log)


# --------------------------------------------------------------------------- #
# §D23-5 — a late boss counts its fuses from arrival
# --------------------------------------------------------------------------- #
def test_a_reserve_boss_fuse_starts_when_it_arrives():
    """A boss held back for a later wave used to walk in already furious: its
    `enrage_round` was measured against the encounter clock, which had long since
    passed it."""
    from ltg_combat.engine import _deploy_reserve
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(enrage_round=3), _minion()]})
    boss = st.enemies[0]
    boss.reserve = True
    st.turn = 6
    _deploy_reserve(st, "boss")
    assert boss.deployed_turn == 6
    _begin_turn(st)
    assert not boss.enraged, "it has been on the board for one round, not three"
    st.turn = 8
    _begin_turn(st)
    assert boss.enraged                        # its own round 3


def test_a_reserve_boss_gets_its_own_grace_round_before_neglect():
    from ltg_combat.engine import _deploy_reserve
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_boss(neglect=2), _minion()]})
    boss = st.enemies[0]
    boss.reserve = True
    st.turn = 5
    _deploy_reserve(st, "boss")
    _begin_turn(st)
    _end_step(st)
    assert boss.max_hp == 20, "the arrival round is its grace round"
    st.turn = 6
    _begin_turn(st)
    _end_step(st)
    assert boss.max_hp == 22


# --------------------------------------------------------------------------- #
# §D23-5 — objectives may modify the boss fight
# --------------------------------------------------------------------------- #
def _phase(objective=None, boss_id="boss"):
    enemies = [{"id": boss_id, "name": boss_id, "is_boss": True, "level": 5},
               {"id": "lieutenant", "name": "lieutenant", "level": 3}]
    out = {"enemies": enemies}
    if objective is not None:
        out["objective"] = objective
    return out


def _phase_three_problem(objective):
    from ltg_game_server.content import _phase_three_objective_problem
    return _phase_three_objective_problem(_phase(objective))


def test_a_guarded_race_on_the_boss_is_a_legal_phase_three_objective():
    assert _phase_three_problem({"kind": "race", "turns": 4, "target": "boss",
                                 "guards": ["lieutenant"]}) is None


def test_a_deadline_is_a_legal_phase_three_objective():
    assert _phase_three_problem({"kind": "deadline", "turns": 5}) is None


def test_a_waves_schedule_ending_on_the_boss_is_legal_on_phase_three():
    assert _phase_three_problem({"kind": "waves",
                                 "waves": [["lieutenant"], ["boss"]]}) is None


def test_a_race_marking_a_minion_is_refused_on_phase_three():
    problem = _phase_three_problem({"kind": "race", "turns": 4,
                                    "target": "lieutenant", "guards": ["boss"]})
    assert problem and "THE BOSS" in problem


def test_an_unguarded_race_is_refused_on_phase_three():
    problem = _phase_three_problem({"kind": "race", "turns": 4, "target": "boss",
                                    "guards": []})
    assert problem and "guards" in problem


def test_a_survive_objective_still_cannot_replace_the_climax():
    """The line §D23-5 draws: an objective may SHAPE the boss fight, never let
    the party win by waiting the boss out."""
    problem = _phase_three_problem({"kind": "survive", "turns": 5})
    assert problem and "replaces the boss kill" in problem


def test_a_waves_objective_whose_last_wave_lacks_the_boss_is_refused():
    problem = _phase_three_problem({"kind": "waves",
                                    "waves": [["boss"], ["lieutenant"]]})
    assert problem and "FINAL wave" in problem


def test_phase_three_without_an_objective_is_unchanged():
    assert _phase_three_problem(None) is None


def _adventure_phases(phase3_objective=None):
    """Three minimal phase-valid encounter dicts (the adventure-level checks are
    what is under test; per-phase validity is `_validate_encounter`'s job)."""
    def phase(n, enemies):
        return {"name": f"Phase {n}", "enemies": enemies}
    return [
        phase(1, [{"id": "grunt", "name": "grunt", "level": 2}]),
        phase(2, [{"id": "captain", "name": "captain", "level": 3,
                   "is_boss": True}]),
        dict(phase(3, [{"id": "boss", "name": "boss", "level": 5, "is_boss": True},
                       {"id": "lieutenant", "name": "lieutenant", "level": 3}]),
             **({"objective": phase3_objective} if phase3_objective else {})),
    ]


def test_the_adventure_gate_accepts_a_modifier_objective_on_phase_three():
    """§D23-5 wiring: the blanket "Phases I and II only" veto is gone, replaced
    by the shape check."""
    from ltg_game_server.content import _validate_adventure
    _validate_adventure(_adventure_phases({"kind": "race", "turns": 4,
                                           "target": "boss",
                                           "guards": ["lieutenant"]}),
                        ["one", "two", "three"])


def test_the_adventure_gate_still_refuses_a_climax_replacing_objective():
    import pytest
    from ltg_game_server.content import _validate_adventure
    with pytest.raises(ValueError, match="Phase III"):
        _validate_adventure(_adventure_phases({"kind": "survive", "turns": 5}),
                            ["one", "two", "three"])


def test_the_adventure_gate_still_allows_only_one_objective():
    import pytest
    from ltg_game_server.content import _validate_adventure
    phases = _adventure_phases({"kind": "deadline", "turns": 5})
    phases[0]["objective"] = {"kind": "deadline", "turns": 5}
    with pytest.raises(ValueError, match="at most one objective"):
        _validate_adventure(phases, ["one", "two", "three"])
