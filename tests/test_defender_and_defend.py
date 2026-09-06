"""Defend's new magnitude, and the `defender` keyword.

DEFEND now grants temp HP equal to BASE Power instead of a flat 3, so the stat
that decides what your swing is worth also decides what turtling is worth — a
heavy hitter has a real choice every turn instead of always attacking.

DEFENDER is the shield-wall keyword: no basic attack ever, but the Defend is
FREED (§D23-2) — raise the shield and still take one more verb (a cast, a Move,
a Skill, an Ultimate). §D23-2 repealed the "rooted" clause in full: a defender
walks and dashes to Mitigate like anyone else. Hero-only — the engine reads it in
the party's action paths and nowhere on the enemy side.
"""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _sorcery(cid):
    """Sorcery-speed, so casting it needs the PROACTIVE action — the only kind of
    card that can show whether Defend spent that action. (An instant is castable
    whenever you can pay, so it proves nothing here.)"""
    out = _filler(cid)
    out.update(type="Sorcery", timing="sorcery")
    return out


def _char(cid, power=2, hp=30, row="front", keywords=None, library=None, hand=1):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": ["U"], "row": row, "attack_mode": "melee",
            "keywords": keywords or [],
            "library": library or [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid="e", hp=30, target="lowest_hp_party", amount=2, mode="melee"):
    return {"id": eid, "name": eid, "hp": hp, "level": 2, "power": 2,
            "attack_mode": mode,
            "intent": {"name": "Bash", "amount": amount, "action_type": "attack",
                       "intent_type": "attack", "targeting": target,
                       "mode": mode}}


def _state(party, enemies=None):
    return state_from_dict({"party": party, "enemies": enemies or [_enemy()]})


def _kinds(st, kind, actor=None):
    return [a for a in legal_actions(st)
            if a.kind == kind and (actor is None or a.actor_id == actor)]


def _do(st, **kw):
    a = next(a for a in legal_actions(st)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(st, a)[0]


# --------------------------------------------------------------------------- #
# Defend scales with base Power
# --------------------------------------------------------------------------- #
def test_defend_grants_temp_hp_equal_to_base_power():
    for power in (1, 3, 5):
        st = _state([_char("p", power=power)])
        st = _do(st, kind="defend", actor_id="p")
        assert st.character("p").temp_mod == power


def test_defend_is_no_longer_a_flat_three():
    """The point of the change: a big hitter now gets a big shield."""
    st = _state([_char("p", power=5)])
    st = _do(st, kind="defend", actor_id="p")
    assert st.character("p").temp_mod == 5


def test_defend_reads_its_real_number_on_the_offer():
    st = _state([_char("p", power=4)])
    label = next(a.label for a in legal_actions(st) if a.kind == "defend")
    assert "+4" in label


def test_defend_uses_base_power_not_the_pumped_value():
    """Pumps and wounds move the SWING, not the stance — otherwise a wound would
    quietly shrink your shield too, and the number on the button would lie."""
    st = _state([_char("p", power=3)])
    st.character("p").power_bonus = 4          # a big anthem
    st = _do(st, kind="defend", actor_id="p")
    assert st.character("p").temp_mod == 3      # base Power, not 7


def test_defend_charges_the_gauge_by_the_amount_granted():
    """The gauge rule is +1 per point of temp HP, so it tracks the new magnitude
    instead of the retired flat 3."""
    st = _state([_char("p", power=5)])
    before = st.character("p").ultimate_gauge
    st = _do(st, kind="defend", actor_id="p")
    assert st.character("p").ultimate_gauge - before >= 5


# --------------------------------------------------------------------------- #
# Defender: what it forbids
# --------------------------------------------------------------------------- #
def test_defender_cannot_attack():
    st = _state([_char("p", keywords=["defender"])])
    assert _kinds(st, "attack", "p") == []


def test_a_defender_may_move():
    """§D23-2 repeals the rooting: the wall walks. It buys the shield wall a real
    positional game (step out of a row assault, cover a different lane) without
    giving it back the sword."""
    st = _state([_char("p", keywords=["defender"])])
    assert {a.target_id for a in _kinds(st, "move", "p")} == {"mid", "rear"}


def test_a_defender_may_defend_and_still_move():
    """The freed Defend buys exactly one more verb — the Move is a legal choice
    for it, and the turn is then spent."""
    st = _state([_char("p", keywords=["defender"],
                       library=[_sorcery("s1"), _sorcery("s2")])])
    st = _do(st, kind="defend")
    assert _kinds(st, "cast", "p"), "the freed shield still leaves one verb"
    st = _do(st, kind="move", target_id="rear")
    while st.stack:
        st = _do(st, kind="pass")
    assert st.character("p").row == "rear"
    assert not _kinds(st, "cast", "p"), "…and that one verb is now spent"


def test_defender_holds_no_first_strike_swing():
    """First Strike is still a basic attack — a defender has none, in any window."""
    st = _state([_char("p", keywords=["defender", "first_strike"])])
    st = _do(st, kind="end_turn", actor_id="p")
    while st.result is None and not st.stack:
        acts = legal_actions(st)
        if not acts:
            break
        st = apply_action(st, acts[0])[0]
    if st.stack:                                    # in the enemy's window
        assert _kinds(st, "attack", "p") == []


def test_a_plain_character_still_attacks_and_moves():
    """Control: the gates above are the keyword's doing, not a broken offer."""
    st = _state([_char("p")])
    assert _kinds(st, "attack", "p") and _kinds(st, "move", "p")


# --------------------------------------------------------------------------- #
# Defender: what it grants
# --------------------------------------------------------------------------- #
def test_defender_defends_for_free_and_still_casts():
    """The whole trade: Defend costs no proactive action, so the same turn still
    buys a spell. A plain character's Defend spends the action and locks casting."""
    lib = [_sorcery("rite"), _sorcery("rite2")]
    st = _state([_char("p", keywords=["defender"], library=lib, hand=2)])
    st = _do(st, kind="defend", actor_id="p")
    assert _kinds(st, "cast", "p"), "a defender may still cast after defending"

    plain = _state([_char("q", library=[_sorcery("r"), _sorcery("r2")], hand=2)])
    plain = _do(plain, kind="defend", actor_id="q")
    assert _kinds(plain, "cast", "q") == []       # the ordinary rule is unchanged


def test_defender_defend_is_still_once_per_turn():
    """Free is not unlimited — stacking the buffer every priority window would be
    an infinite shield."""
    st = _state([_char("p", keywords=["defender"], power=3)])
    st = _do(st, kind="defend", actor_id="p")
    assert _kinds(st, "defend", "p") == []
    assert st.character("p").temp_mod == 3


def test_defender_offer_says_it_is_free():
    st = _state([_char("p", keywords=["defender"], power=3)])
    label = next(a.label for a in legal_actions(st) if a.kind == "defend")
    assert "free" in label.lower() and "+3" in label


# --------------------------------------------------------------------------- #
# Defender and Mitigate (the rooted-guard rule)
# --------------------------------------------------------------------------- #
def _to_enemy_window(st):
    while True:
        acts = legal_actions(st)
        if st.stack and any(a.kind == "pass" for a in acts):
            return st
        nxt = next((a for a in acts if a.kind == "end_turn"), None) or acts[0]
        st = apply_action(st, nxt)[0]


def test_a_defender_may_still_mitigate_for_itself():
    st = _state([_char("p", keywords=["defender"], power=4, hp=20)])
    st = _to_enemy_window(st)
    assert any(a.kind == "mitigate" and a.target_id == "p" for a in legal_actions(st))


def test_a_defender_dashes_to_cover_an_adjacent_ally():
    """§D23-2: the wall comes to them. Ally-mode Mitigate relocates the guard to
    the ally's row (§M-A.6); the defender's repealed rooting no longer blocks it,
    which is what makes a shield-wall hero worth a seat next to a squishy one."""
    # RANGED, so the §L-3 melee-interposition redirect doesn't pull the swing onto
    # the front-row wall — the shot reaches past it, which is the case under test.
    st = _state([_char("wall", keywords=["defender"], power=4, hp=30, row="front"),
                 _char("mage", power=1, hp=10, row="mid")],
                [_enemy(target="lowest_hp_party", mode="ranged")])
    st = _to_enemy_window(st)
    assert st.stack[-1].target_id == "mage"       # the shot is aimed past the wall
    assert any(a.kind == "mitigate" and a.actor_id == "wall" and a.target_id == "mage"
               for a in legal_actions(st))


def test_a_plain_guard_may_still_dash_to_an_adjacent_ally():
    """Control for the rule above — the dash is unchanged for everyone else."""
    st = _state([_char("tank", power=4, hp=30, row="front"),
                 _char("mage", power=1, hp=10, row="mid")],
                [_enemy(target="lowest_hp_party", mode="ranged")])
    st = _to_enemy_window(st)
    assert st.stack[-1].target_id == "mage"
    assert any(a.kind == "mitigate" and a.actor_id == "tank" and a.target_id == "mage"
               for a in legal_actions(st))


# --------------------------------------------------------------------------- #
# Hero-only
# --------------------------------------------------------------------------- #
def test_defender_is_registered_and_grantable():
    from ltg_core.schema import KEYWORDS, GRANTABLE_KEYWORDS
    assert "defender" in KEYWORDS and "defender" in GRANTABLE_KEYWORDS


def test_defender_does_not_stop_an_enemy_acting():
    """Hero-only: the engine reads the keyword in the party's action paths only,
    so an enemy wearing it (however it got there) still declares and swings."""
    st = _state([_char("p", hp=20)], [_enemy()])
    st.enemies[0].keywords["defender"] = "encounter"
    st = _to_enemy_window(st)
    assert st.stack, "the enemy still put an action on the stack"
    while st.stack:
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    assert st.character("p").hp < 20              # and it still landed
