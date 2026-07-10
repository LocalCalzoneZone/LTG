"""Enrage as a HARD TURN (§F-9 upgraded): crossing 25% shakes off stun/taunt,
resets the boss's component cooldowns (once_per_encounter stays spent), and the
Enrage component still fires once with all its verbs."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _char(cid, power=16, hp=40):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": "front", "attack_mode": "melee",
            "library": []}


_ENRAGE = {"id": "fury", "archetype": "Enrage", "priority": 5,
           "target_rule": "self", "telegraph": "FURY",
           "verbs": [{"kind": "counters", "power": 2, "toughness": 2,
                      "target": {"mode": "self"}},
                     {"kind": "deal_damage", "amount": 3,
                      "target": {"mode": "all", "side": "ally"}}]}

_BREATH = {"id": "breath", "archetype": "Burst", "timing": "proactive",
           "priority": 30, "cooldown": 3, "target_rule": "valuation",
           "telegraph": "Breath",
           "verbs": [{"kind": "deal_damage", "amount": 4,
                      "target": {"mode": "chosen", "side": "ally",
                                 "targeted": True}}]}


def _boss_state(tweak=None):
    st = state_from_dict({
        "party": [_char("p")],
        "enemies": [{"id": "tyrant", "name": "Tyrant", "hp": 20, "level": 6,
                     "power": 3, "is_boss": True, "attack_mode": "melee",
                     "components": [dict(_BREATH), dict(_ENRAGE)]}],
    })
    if tweak:
        tweak(st)
    return st


def _act(st, **kw):
    a = next(a for a in legal_actions(st)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(st, a)


def _pass_all(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def test_enrage_shakes_off_control_and_resets_cooldowns():
    def setup(s):
        boss = s.enemy("tyrant")
        boss.stunned = 2
        boss.taunted_by = "p"
        boss.cooldowns = {"breath": 99, "spent_once": 10 ** 9}
    st = _boss_state(tweak=setup)
    st, _ = _act(st, kind="attack", target_id="tyrant")   # 20 -> 4: enrage crossing
    st = _pass_all(st)
    boss = st.enemy("tyrant")
    assert boss.enraged
    assert boss.stunned == 0 and boss.taunted_by is None  # control shaken off
    assert "breath" not in boss.cooldowns                 # kit reset
    assert boss.cooldowns.get("spent_once") == 10 ** 9    # the drama stays spent
    assert any(ev.type == "enrage" for ev in st.log)


def test_enrage_component_fires_all_its_verbs_once():
    st = _boss_state()
    hp0 = st.party[0].hp
    st, _ = _act(st, kind="attack", target_id="tyrant")
    st = _pass_all(st)
    boss = st.enemy("tyrant")
    assert boss.counters == 2 and boss.power == 3 + 2     # permanent surge
    assert st.party[0].hp == hp0 - 3                      # the hall burned
    # once_per_encounter bookkeeping: the enrage never returns.
    assert boss.cooldowns.get("fury", 0) >= 10 ** 9
