"""The smarter enemy heuristics: wounded-aware support, threat reads, control
spreading, and the new component condition gates (hero_count / hero_channeling /
self_channeling)."""

from __future__ import annotations

from ltg_combat.engine import settle
from ltg_combat.scenario import state_from_dict


def _char(cid, power=3, hp=30, row="front"):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": row, "attack_mode": "melee", "library": []}


def _enemy(eid, components=None, hp=10, power=2, row="front"):
    return {"id": eid, "name": eid, "hp": hp, "level": 3, "power": power,
            "row": row, "attack_mode": "melee",
            "components": components or []}


_HEAL_TGT = {"kind": "heal", "amount": 4,
             "target": {"mode": "chosen", "side": "ally", "targeted": True}}
_STUN = {"kind": "stun", "target": {"mode": "chosen", "side": "ally", "targeted": True}}
_HIT = {"kind": "deal_damage", "amount": 3,
        "target": {"mode": "chosen", "side": "ally", "targeted": True}}


def _mender(rule):
    return {"id": "mend", "archetype": "Fortify", "timing": "proactive",
            "priority": 10, "cooldown": 2, "target_rule": rule,
            "telegraph": "Mend", "verbs": [dict(_HEAL_TGT)]}


def _settled(spec, tweak=None):
    st = state_from_dict(spec)
    if tweak:
        tweak(st)
    return settle(st)  # runs upkeep/draw/intents — enemies have declared


# --- support that skips the unwounded ---------------------------------------- #
def test_wounded_ally_rule_skips_when_warband_is_healthy():
    st = _settled({"party": [_char("p")],
                   "enemies": [_enemy("healer", [_mender("wounded_ally")]),
                               _enemy("grunt")]})
    healer = st.enemy("healer")
    assert healer.intent is not None and "Mend" not in healer.intent.name


def test_wounded_ally_rule_heals_the_hurt_ally():
    st = _settled({"party": [_char("p")],
                   "enemies": [_enemy("healer", [_mender("wounded_ally")]),
                               _enemy("grunt")]},
                  tweak=lambda s: setattr(s.enemy("grunt"), "hp", 4))
    healer = st.enemy("healer")
    assert healer.intent is not None and healer.intent.name == "Mend"
    assert healer.intent.target_id == "grunt"


def test_lowest_hp_ally_pure_heal_skips_full_hp_allies():
    st = _settled({"party": [_char("p")],
                   "enemies": [_enemy("healer", [_mender("lowest_hp_ally")]),
                               _enemy("grunt")]})
    healer = st.enemy("healer")
    assert healer.intent is not None and "Mend" not in healer.intent.name


# --- highest_threat ----------------------------------------------------------- #
def test_highest_threat_targets_the_hardest_hitter():
    comp = {"id": "cut", "archetype": "Burst", "timing": "proactive",
            "priority": 20, "cooldown": 2, "target_rule": "highest_threat",
            "telegraph": "Hamstring", "verbs": [dict(_HIT)]}
    st = _settled({"party": [_char("tank", power=6, hp=30),
                             _char("medic", power=1, hp=8)],
                   "enemies": [_enemy("assassin", [comp])]})
    intent = st.enemy("assassin").intent
    assert intent.name == "Hamstring" and intent.target_id == "tank"


# --- control spreads, never stacks -------------------------------------------- #
def test_stun_valuation_skips_an_already_stunned_hero():
    comp = {"id": "daze", "archetype": "Debilitate", "timing": "proactive",
            "priority": 20, "cooldown": 1, "target_rule": "valuation",
            "telegraph": "Skull Ring", "verbs": [dict(_STUN)]}
    st = _settled({"party": [_char("a", hp=10), _char("b", hp=20)],
                   "enemies": [_enemy("bully", [comp])]},
                  tweak=lambda s: setattr(s.character("a"), "stunned", 1))
    intent = st.enemy("bully").intent
    # "a" is the lowest-HP pick, but it is already locked down — spread to "b".
    assert intent.name == "Skull Ring" and intent.target_id == "b"


def test_taunt_valuation_skips_an_already_taunted_hero():
    # `taunted_to` is a this-turn effect (upkeep clears it), so probe the
    # component-target brain directly at the state where a taunt already landed.
    from ltg_combat.engine import _component_target
    from ltg_combat.scenario import _component_from_dict
    taunt = {"kind": "taunt", "target": {"mode": "chosen", "side": "ally",
                                         "targeted": True}}
    comp = _component_from_dict(
        {"id": "jeer", "archetype": "Debilitate", "timing": "proactive",
         "priority": 20, "cooldown": 1, "target_rule": "valuation",
         "telegraph": "Jeer", "verbs": [taunt]})
    st = state_from_dict({"party": [_char("a", hp=10), _char("b", hp=20)],
                          "enemies": [_enemy("bully", [ ]), _enemy("wall")]})
    st.character("a").taunted_to = "wall"
    picked = _component_target(st, st.enemy("bully"), comp)
    assert picked is not None and picked.id == "b"


# --- the new condition gates --------------------------------------------------- #
def _gated(cond):
    return {"id": "cleave", "archetype": "Burst", "timing": "proactive",
            "priority": 20, "cooldown": 2, "target_rule": "valuation",
            "condition": cond, "telegraph": "Cleave", "verbs": [dict(_HIT)]}


def test_hero_count_condition_gates_on_party_size():
    cond = {"kind": "hero_count", "op": ">=", "value": 2}
    solo = _settled({"party": [_char("p")],
                     "enemies": [_enemy("ogre", [_gated(cond)])]})
    assert "Cleave" not in solo.enemy("ogre").intent.name
    duo = _settled({"party": [_char("p"), _char("q")],
                    "enemies": [_enemy("ogre", [_gated(cond)])]})
    assert duo.enemy("ogre").intent.name == "Cleave"


def test_hero_channeling_condition_arms_the_ritual_breaker():
    cond = {"kind": "hero_channeling", "op": ">=", "value": 1}
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_enemy("ogre", [_gated(cond)])]})
    st = settle(st)
    assert "Cleave" not in st.enemy("ogre").intent.name  # nobody channels


def test_self_channeling_condition_reads_own_channels():
    from ltg_combat.state import EnemyChannel
    cond = {"kind": "self_channeling", "op": ">=", "value": 1}
    st = _settled({"party": [_char("p")],
                   "enemies": [_enemy("ogre", [_gated(cond)])]},
                  tweak=lambda s: s.enemy("ogre").channels.append(
                      EnemyChannel(component_id="x", name="Rite",
                                   holder_id="ogre")))
    assert st.enemy("ogre").intent.name == "Cleave"
