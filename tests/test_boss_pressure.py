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
