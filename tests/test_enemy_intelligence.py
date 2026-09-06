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


# --------------------------------------------------------------------------- #
# §D23-6 — the enemy is less solved
# --------------------------------------------------------------------------- #
def _rule(cid, priority=30, **kw):
    out = {"id": cid, "archetype": "Burst", "timing": "proactive",
           "priority": priority, "target_rule": "valuation", "telegraph": cid,
           "verbs": [dict(_HIT)]}
    out.update(kw)
    return out


def _tied_kit():
    """Three rules the author placed in the SAME band — the case authoring order
    used to resolve identically in every fight, making the kit solvable once."""
    return [_rule("alpha"), _rule("beta"), _rule("gamma")]


def _declared_name(seed, turn=1):
    st = state_from_dict({"party": [_char("p", hp=200)],
                          "enemies": [_enemy("e", components=_tied_kit())]},
                         seed=seed)
    st.turn = turn
    return settle(st).enemies[0].round_intent.name


def test_a_tie_inside_a_band_is_broken_by_the_fights_seed():
    """§D23-6: same seed, same fight; different fights differ. Priority still
    decides — only ties inside a band move."""
    assert _declared_name(7) == _declared_name(7)          # reproducible
    picks = {_declared_name(s) for s in range(1, 40)}
    assert len(picks) > 1, "authoring order must not decide every fight"


def test_the_seeded_tiebreak_varies_across_turns_within_one_fight():
    """The same band must not lock onto one rule for a whole encounter."""
    picks = {_declared_name(11, turn=t) for t in range(1, 12)}
    assert len(picks) > 1


def test_priority_still_outranks_the_seeded_tiebreak():
    kit = [_rule("first", priority=10), _rule("second"), _rule("third")]
    for seed in range(1, 20):
        st = state_from_dict({"party": [_char("p", hp=200)],
                              "enemies": [_enemy("e", components=kit)]}, seed=seed)
        assert settle(st).enemies[0].round_intent.name == "first"


# --- the new conditions ------------------------------------------------------ #
def _gated_pick(condition, party, turn=1):
    """The name the gated rule declares — "gated" when its condition holds, the
    fallback basic attack when it does not."""
    kit = [_rule("gated", priority=10, condition=condition)]
    st = state_from_dict({"party": party,
                          "enemies": [_enemy("e", components=kit)]})
    st.turn = turn
    return settle(st).enemies[0].round_intent.name


def test_hero_in_row_reads_position():
    crowd = [_char("a", row="front"), _char("b", row="front")]
    spread = [_char("a", row="front"), _char("b", row="rear")]
    cond = {"kind": "hero_in_row", "row": "front", "op": ">=", "value": 2}
    assert _gated_pick(cond, crowd) == "gated"
    assert _gated_pick(cond, spread) != "gated"


def test_hero_hp_pct_reads_the_most_wounded_hero():
    cond = {"kind": "hero_hp_pct", "op": "<=", "value": 30}
    hurt = [_char("a", hp=30), _char("b", hp=30)]

    def wound(st):
        st.character("b").hp = 5
    kit = [_rule("gated", priority=10, condition=cond)]
    st = state_from_dict({"party": hurt, "enemies": [_enemy("e", components=kit)]})
    assert settle(st).enemies[0].round_intent.name != "gated"   # everyone healthy
    st2 = state_from_dict({"party": hurt, "enemies": [_enemy("e", components=kit)]})
    wound(st2)
    assert settle(st2).enemies[0].round_intent.name == "gated"


def test_corpse_count_reads_the_bodies_on_the_field():
    cond = {"kind": "corpse_count", "op": ">=", "value": 1}
    kit = [_rule("gated", priority=10, condition=cond)]
    st = state_from_dict({"party": [_char("p")],
                          "enemies": [_enemy("e", components=kit),
                                      _enemy("f", hp=1)]})
    assert settle(st).enemies[0].round_intent.name != "gated"
    st2 = state_from_dict({"party": [_char("p")],
                           "enemies": [_enemy("e", components=kit),
                                       _enemy("f", hp=1)]})
    from ltg_combat.engine import _kill_enemy
    _kill_enemy(st2, st2.enemy("f"))
    assert settle(st2).enemies[0].round_intent.name == "gated"


def test_turn_mod_reads_as_a_rhythm():
    cond = {"kind": "turn_mod", "mod": 3, "value": 0}
    party = [_char("p", hp=200)]
    assert _gated_pick(cond, party, turn=3) == "gated"
    assert _gated_pick(cond, party, turn=6) == "gated"
    assert _gated_pick(cond, party, turn=4) != "gated"


def test_a_typod_condition_kind_fails_at_load_not_silently_at_evaluation():
    """It used to fail closed and quietly: the rule simply never fired, and the
    enemy lost a third of its kit for the whole encounter."""
    import pytest
    with pytest.raises(ValueError, match="unknown condition kind"):
        state_from_dict({"party": [_char("p")],
                         "enemies": [_enemy("e", components=[
                             _rule("oops", condition={"kind": "self_hp_prc",
                                                      "op": "<", "value": 50})])]})


# --- grudges ----------------------------------------------------------------- #
def test_a_class_grudge_hunts_whoever_wears_the_role():
    party = [dict(_char("tank"), classes=["warrior"]),
             dict(_char("healer"), classes=["cleric"])]
    kit = [_rule("grudge", priority=10, target_rule="hero_class:cleric")]
    st = state_from_dict({"party": party, "enemies": [_enemy("e", components=kit)]})
    assert settle(st).enemies[0].round_intent.target_id == "healer"


def test_a_type_grudge_reads_the_type_tags():
    party = [dict(_char("man")), dict(_char("elf"), types=["elf"])]
    kit = [_rule("grudge", priority=10, target_rule="hero_type:elf")]
    st = state_from_dict({"party": party, "enemies": [_enemy("e", components=kit)]})
    assert settle(st).enemies[0].round_intent.target_id == "elf"


def test_a_grudge_with_nobody_wearing_the_role_falls_back_to_valuation():
    """A grudge must never turn a rule into a dead slot."""
    party = [dict(_char("tank"), classes=["warrior"])]
    kit = [_rule("grudge", priority=10, target_rule="hero_class:cleric")]
    st = state_from_dict({"party": party, "enemies": [_enemy("e", components=kit)]})
    intent = settle(st).enemies[0].round_intent
    assert intent.name == "grudge" and intent.target_id == "tank"


# --- cadence exemption ------------------------------------------------------- #
def test_the_attack_cadence_never_overrides_the_emergency_band():
    """§D23-6: priority 10-19 is where an author puts "drop everything". The
    §D18-3 cadence was forcing the sword over exactly those rules."""
    from ltg_combat.engine import _pick_enemy_intent
    kit = [_rule("panic", priority=15, cooldown=0)]
    st = state_from_dict({"party": [_char("p", hp=200)],
                          "enemies": [_enemy("e", components=kit)]})
    e = st.enemies[0]
    _pick_enemy_intent(st, e, swing=2, force_swing=True)
    assert e.intent.name == "panic"


def test_the_cadence_still_forces_the_sword_over_an_ordinary_rule():
    from ltg_combat.engine import _pick_enemy_intent
    kit = [_rule("routine", priority=30, cooldown=0)]
    st = state_from_dict({"party": [_char("p", hp=200)],
                          "enemies": [_enemy("e", components=kit)]})
    e = st.enemies[0]
    _pick_enemy_intent(st, e, swing=2, force_swing=True)
    assert e.intent.name != "routine"


# --- cooldowns spend on declaration ------------------------------------------ #
def test_a_stripped_component_still_spends_its_cooldown():
    """§D23-6: strip is a ONE-ROUND answer, not a lock on a one-trick body. The
    cooldown used to start at execution, so unravelling the telegraph cost the
    enemy nothing and it re-declared the same rule for ever."""
    from ltg_combat.engine import _strip_slot
    kit = [_rule("trick", priority=10, cooldown=3)]
    st = state_from_dict({"party": [_char("p", hp=200)],
                          "enemies": [_enemy("e", components=kit)]})
    st = settle(st)
    e = st.enemies[0]
    assert e.round_intent.name == "trick"
    assert e.cooldowns.get("trick", 0) > st.turn      # paid at declaration
    _strip_slot(st, e, slot2=False)
    assert e.cooldowns.get("trick", 0) > st.turn      # …and the strip does not refund it


def test_a_stripped_one_trick_minion_declares_something_else_next_round():
    from ltg_combat.engine import _begin_turn, _declare_enemy_intent, _strip_slot
    kit = [_rule("trick", priority=10, cooldown=3)]
    st = state_from_dict({"party": [_char("p", hp=200)],
                          "enemies": [_enemy("e", components=kit)]})
    st = settle(st)
    _strip_slot(st, st.enemies[0], slot2=False)
    st.turn += 1
    _begin_turn(st)
    _declare_enemy_intent(st, st.enemies[0])
    assert st.enemies[0].intent is not None
    assert st.enemies[0].intent.name != "trick"       # it has to reach for the sword
