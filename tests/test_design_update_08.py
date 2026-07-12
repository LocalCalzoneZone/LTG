"""Design Update 08 — Tier One: veiled intents (§D8-1), afflictions & charge
(§D8-2), heroic actions (§D8-3), and smart auto-pass (§D8-4).

Engine behaviour is driven through the two-function contract; the veiling
contract is asserted against the seat-filtered snapshot (the seam §D8-1.4 moves).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ltg_combat.engine import apply_action, auto_pass_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import (
    Card,
    Character,
    Charge,
    DealDamage,
    Poison,
    Regen,
    t_chosen,
    t_self,
)

CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}
CHOSEN_ALLY_T = {"mode": "chosen", "side": "ally", "targeted": True}
SELF = {"mode": "self"}


def _card(cid, name, timing, cost, effects, level=1):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": level, "type": "Spell", "timing": timing, "cost": cost,
            "effects": effects, "validated": True}


def _char(cid, power=3, hp=30, hand=0, library=None, identity=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": identity or ["U"], "row": "front", "attack_mode": "melee",
            "library": library or []}


def _enemy(eid, hp=10, amount=2, level=3):
    return {"id": eid, "name": eid, "hp": hp, "level": level,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _state(party, enemies, tweak=None):
    st = state_from_dict({"party": party, "enemies": enemies})
    if tweak:
        tweak(st)
    return st


def _do(st, kind, **match):
    """Apply the first legal action of `kind` matching the given fields."""
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal '{kind}' action ({match}) among "
                         f"{[a.label for a in legal_actions(st)]}")


def _drive_turn(st):
    """End turns / pass windows until the turn counter advances or the game ends."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    return st


# ========================================================================== #
# §D8-2.1 poison
# ========================================================================== #
def _venom_card(amount=2, turns=None):
    eff = {"kind": "poison", "amount": amount, "target": CHOSEN_ENEMY_T}
    if turns is not None:
        eff["turns"] = turns
    return _card("venom", "Venom", "sorcery", {"colors": {"U": 1}}, [eff])


def test_poison_places_now_and_ticks_at_upkeep():
    st = _state([_char("p", hand=1, library=[_venom_card(2)])], [_enemy("e", hp=12)])
    st = _do(st, "cast", card_id="venom")
    st = _do(st, "pass")  # own window — resolve
    e = st.enemy("e")
    assert e.poison_counters == 2
    assert e.hp == 10 and e.max_hp == 10        # −0/−1 each, now
    assert len(e.poison_effects) == 1
    st = _drive_turn(st)                        # to turn 2's upkeep tick
    e = st.enemy("e")
    assert e.poison_counters == 4               # ticked again
    assert e.max_hp == 8


def test_poison_is_not_damage_and_ignores_prevention():
    st = _state([_char("p", hand=1, library=[_venom_card(1)])], [_enemy("e", hp=8)])

    def shield(s):
        from ltg_combat.state import PreventTag
        s.enemy("e").prevent_tags.append(PreventTag("damage", None))
    shield(st)
    st = _do(st, "cast", card_id="venom")
    st = _do(st, "pass")
    assert st.enemy("e").poison_counters == 1   # a clock that ignores the shield wall


def test_poison_kills_on_effective_hp():
    st = _state([_char("p", hand=1, library=[_venom_card(2)])], [_enemy("e", hp=2)])
    st = _do(st, "cast", card_id="venom")
    st = _do(st, "pass")
    assert st.enemy("e") is None                # poison kills
    assert any(ev.type == "enemy_died" for ev in st.log)


def test_any_healing_cures_poison_and_sheds_the_counters():
    mend = _card("mend", "Mend", "instant", {"colors": {"U": 1}},
                 [{"kind": "heal", "amount": 2, "target": SELF}])
    poisoner = Component(id="spit", archetype="Debilitate", priority=10, cooldown=9,
                         verbs=[Poison(amount=1, target=t_chosen("ally", targeted=True))],
                         target_rule="valuation", telegraph="Venom Spit")
    st = _state([_char("p", hp=20, hand=1, library=[mend])], [_enemy("e")],
                tweak=lambda s: s.enemy("e").components.append(poisoner))
    st = _drive_turn(st)                        # enemy poisons; turn-2 upkeep ticks
    p = st.character("p")
    assert p.poison_effects and p.poison_counters == 2  # 1 on landing + 1 tick
    assert p.max_hp == 18                        # −0/−2 folded into max
    st = _do(st, "cast", card_id="mend")
    st = _do(st, "pass")
    p = st.character("p")
    # Playtest ruling: healing cures the ticking AND sheds the counters, reversing
    # each one's −0/−1 (max HP restored, then the heal fills on top).
    assert p.poison_effects == []
    assert p.poison_counters == 0
    assert p.max_hp == 20                        # the −0/−2 is fully reversed


def test_bounded_poison_concludes_after_its_turns():
    st = _state([_char("p", hand=1, library=[_venom_card(1, turns=1)])],
                [_enemy("e", hp=12)])
    st = _do(st, "cast", card_id="venom")
    st = _do(st, "pass")
    st = _drive_turn(st)                        # the one bounded tick
    e = st.enemy("e")
    assert e.poison_counters == 2
    assert e.poison_effects == []               # concluded on its own
    st = _drive_turn(st)
    assert st.enemy("e").poison_counters == 2   # no further ticking


# ========================================================================== #
# §D8-2.2 regen
# ========================================================================== #
def test_regen_ticks_cure_poison_and_annihilate():
    tonic = _card("tonic", "Tonic", "sorcery", {"colors": {"U": 1}},
                  [{"kind": "regen", "amount": 1, "target": SELF}])
    poisoner = Component(id="spit", archetype="Debilitate", priority=10, cooldown=9,
                         verbs=[Poison(amount=2, target=t_chosen("ally", targeted=True))],
                         target_rule="valuation", telegraph="Venom Spit")
    st = _state([_char("p", hand=1, library=[tonic])], [_enemy("e")],
                tweak=lambda s: s.enemy("e").components.append(poisoner))
    st = _drive_turn(st)                        # 2 on landing + 2 at the next tick
    assert st.character("p").poison_counters == 4
    st = _do(st, "cast", card_id="tonic")
    st = _do(st, "pass")
    p = st.character("p")
    assert p.poison_effects == []               # a regen tick counts as healing
    assert p.poison_counters == 3 and p.regen_counters == 0  # 1:1 annihilation


def test_regen_broken_by_damage_that_connects():
    tonic = _card("tonic", "Tonic", "sorcery", {"colors": {"U": 1}},
                  [{"kind": "regen", "amount": 1, "target": SELF}])
    st = _state([_char("p", hand=1, library=[tonic], hp=20)], [_enemy("e", amount=3)])
    st = _do(st, "cast", card_id="tonic")
    st = _do(st, "pass")
    assert st.character("p").regen_effects
    st = _drive_turn(st)                        # the enemy's 3-damage hit connects
    p = st.character("p")
    assert p.regen_effects == []                # broken
    assert p.regen_counters == 1                # counters remain


# ========================================================================== #
# §D8-2.5 infect
# ========================================================================== #
def test_infect_poisons_on_connect_first_counter_at_next_upkeep():
    from ltg_combat import engine
    st = _state([_char("p", hp=20)], [_enemy("e", amount=2)],
                tweak=lambda s: s.enemy("e").keywords.update({"infect": "encounter"}))
    # Unit-level: the connecting hit applies the effect but places NO counter now
    # — a venomed blade wounds now and sickens later (D8-2.5).
    engine._deal_damage(st, st.character("p"), 2, source="Claw",
                        source_obj=st.enemy("e"), damage_kind="attack")
    p = st.character("p")
    assert len(p.poison_effects) == 1 and p.poison_effects[0].pending
    assert p.poison_counters == 0
    # Integration: each further connecting hit stacks its own effect; ticks land.
    st = _drive_turn(st)                        # enemy hit + the next upkeep tick
    p = st.character("p")
    assert len(p.poison_effects) == 2
    assert p.poison_counters >= 1


def test_infect_banned_at_creation_but_grantable():
    with pytest.raises(ValidationError):
        Character(name="X", colors=["U"], starting_mana=["U"], keyword="infect")
    # grantable via grant_keyword (registry allows it)
    c = Card.model_validate(_card("g", "Plaguetouch", "instant", {},
                                  [{"kind": "grant_keyword", "keywords": ["infect"],
                                    "target": CHOSEN_ALLY_T}]))
    assert c.effects[0].keywords == ["infect"]


# ========================================================================== #
# §D8-2.4 charge — the windup
# ========================================================================== #
def _gatherer(threshold=2):
    gather = Component(id="gather", archetype="Escalate", priority=10,
                       verbs=[Charge(amount=1)], target_rule="self",
                       telegraph="Gathering Storm")
    boom = Component(id="boom", archetype="Burst", timing="reactive",
                     trigger="on_charge_full", charge_threshold=threshold,
                     verbs=[DealDamage(amount=7, target=t_chosen("ally", targeted=True))],
                     target_rule="valuation", telegraph="Stormburst")
    return [gather, boom]


def test_charge_gathers_then_detonates_onto_the_stack():
    st = _state([_char("p", hp=30)], [_enemy("e")],
                tweak=lambda s: s.enemy("e").components.extend(_gatherer(2)))
    st = _drive_turn(st)                        # gather 1
    assert st.enemy("e").charge == 1
    # Turn 2: the second gather reaches the threshold — the detonation goes on
    # the stack mid-step and charge resets AT PUSH, before it resolves.
    turn = st.turn
    seen_detonation_window = False
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        view = settle(st)
        if view.stack and view.stack[-1].label == "Stormburst":
            seen_detonation_window = True
            assert view.enemy("e").charge == 0  # consumed as it hit the stack
        act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    assert seen_detonation_window
    assert any(ev.type == "charge_detonate" for ev in st.log)
    assert st.character("p").hp < 30            # it landed


def test_gather_intent_is_veiled_as_gathering():
    from ltg_combat.serialize import intent_category
    st = _state([_char("p")], [_enemy("e")],
                tweak=lambda s: s.enemy("e").components.extend(_gatherer(2)))
    view = settle(st)
    assert intent_category(view.enemy("e").intent) == "gathering"


def test_charge_rejected_on_player_cards():
    with pytest.raises(ValidationError):
        Card.model_validate(_card("z", "Windup", "sorcery", {},
                                  [{"kind": "charge", "amount": 2}]))


# ========================================================================== #
# §D8-1 veiled intents
# ========================================================================== #
def _snapshot(st, controlled={"p"}):
    from ltg_game_server.snapshot import build_snapshot
    return build_snapshot(st, set(controlled))


def test_snapshot_veils_attack_intents():
    st = _state([_char("p")], [_enemy("e", amount=4)])
    snap = _snapshot(st)
    (entry,) = snap["intents"]
    assert entry["category"] == "threat"
    assert entry["target_id"] == "p"
    assert "Hit" not in entry["line"] and "4" not in entry["line"]
    creature = snap["creatures"][0]
    assert set(creature["intent"]) >= {"category", "target_id", "line", "status"}
    assert "Hit" not in str(creature["intent"])
    assert "4" not in str(creature["intent"].get("line", ""))


def test_support_and_spell_categories():
    from ltg_combat.serialize import intent_category
    from ltg_combat.state import Intent
    from ltg_core.schema import Heal
    heal_intent = Intent(name="Mend Ally", action_type="ability",
                         effects=[Heal(amount=3, target=t_self())], target_id="e")
    assert intent_category(heal_intent) == "support"
    spell_intent = Intent(name="Fireball", action_type="spell",
                          effects=[DealDamage(amount=5, target=t_chosen("ally", targeted=True))],
                          target_id="p")
    assert intent_category(spell_intent) == "spellcraft"


def test_strip_reveals_what_was_prevented():
    strip = _card("unravel", "Unravel", "instant", {"colors": {"U": 1}},
                  [{"kind": "strip_intent", "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", hand=1, library=[strip])], [_enemy("e", amount=4)])
    st = _do(st, "cast", card_id="unravel")
    st = _do(st, "pass")
    ev = next(ev for ev in st.log if ev.type == "strip_intent")
    assert "Hit — deal 4" in ev.data.get("reveal", "")   # the reward rule (D8-1.3)
    snap = _snapshot(st)
    (entry,) = snap["intents"]
    assert entry["status"] == "stripped"
    assert "Hit" in entry["reveal"]


def test_stunned_enemy_reads_as_reeling():
    st = _state([_char("p")], [_enemy("e")],
                tweak=lambda s: setattr(s.enemy("e"), "stunned", 1))
    snap = _snapshot(st)
    (entry,) = snap["intents"]
    assert entry["status"] == "stunned"
    assert "no intent" in entry["line"]


# ========================================================================== #
# §D8-3 heroic actions & the ultimate gauge
# ========================================================================== #
def _skill_card():
    return _card("skl", "Flash Step", "sorcery", {},
                 [{"kind": "pump", "power": 1, "toughness": 1, "target": SELF,
                   "duration": "this_turn"}])


def _ultimate_card():
    return _card("ult", "Starfall", "sorcery", {},
                 [{"kind": "deal_damage", "amount": 9, "target": CHOSEN_ENEMY_T}])


def _heroic_state(gauge=0, hp=30):
    def wire(s):
        p = s.character("p")
        p.skill = Card.model_validate(_skill_card())
        p.ultimate = Card.model_validate(_ultimate_card())
        p.ultimate_gauge = gauge
    return _state([_char("p", hp=hp)], [_enemy("e", hp=12)], tweak=wire)


def test_gauge_charges_from_actions_damage_and_defend():
    st = _state([_char("p", power=3)], [_enemy("e", hp=12, amount=2)])
    st = _do(st, "attack")
    st = _do(st, "pass")   # attack resolves
    p = st.character("p")
    assert p.ultimate_gauge == 2 + 3            # +2 action, +1 per damage connected
    st = _drive_turn(st)                        # enemy hits back for 2
    assert st.character("p").ultimate_gauge == 5 + 2   # +1 per HP lost
    st = _do(st, "defend")
    assert st.character("p").ultimate_gauge == 7 + 5   # Defend earns +5 (D8-3.3)


def test_skill_is_an_activated_action_once_per_encounter_and_charges_gauge():
    """Update 11: the Skill is an activated ability — an action that CONSUMES
    the proactive action (no attack afterwards without vigilance)."""
    st = _heroic_state()
    assert any(a.kind == "use_skill" for a in legal_actions(st))
    st = _do(st, "use_skill")
    view = settle(st)
    assert view.stack[-1].kind == "activated"   # a spell counter can't answer it
    st = _do(st, "pass")
    p = st.character("p")
    # +5 for the Skill, +1 for the temp HP its pump granted (the toughness half).
    assert p.skill_used and p.ultimate_gauge == 6
    assert not any(a.kind == "use_skill" for a in legal_actions(st))
    # …and it CONSUMED the proactive action: no attack this turn.
    assert p.acted_mode == "skill"
    assert not any(a.kind == "attack" for a in legal_actions(st))


def test_skill_locked_out_after_attacking_and_not_offered_in_reaction_windows():
    st = _heroic_state()
    st = _do(st, "attack")
    # The attack's own reaction window: the Skill (active speed) never reacts.
    assert not any(a.kind == "use_skill" for a in legal_actions(st))
    st = _do(st, "pass")
    # Back in the main phase, the proactive action is spent — no Skill.
    assert not any(a.kind == "use_skill" for a in legal_actions(st))


def test_vigilance_lets_the_skill_ride_alongside_an_attack():
    st = _heroic_state()
    st.character("p").keywords["vigilance"] = ""
    st = _do(st, "attack")
    st = _do(st, "pass")
    assert any(a.kind == "use_skill" for a in legal_actions(st))
    st = _do(st, "use_skill")
    st = _do(st, "pass")
    assert st.character("p").skill_used


def test_ultimate_gated_on_full_gauge_and_spends_it():
    st = _heroic_state(gauge=99)
    assert not any(a.kind == "use_ultimate" for a in legal_actions(st))
    st2 = _heroic_state(gauge=100)
    assert any(a.kind == "use_ultimate" for a in legal_actions(st2))
    st2 = _do(st2, "use_ultimate")
    p = st2.character("p")
    assert p.ultimate_used and p.ultimate_gauge == 0
    assert p.acted_mode == "ultimate"           # it consumed the proactive action


def test_ultimate_damage_lands():
    st = _heroic_state(gauge=100)
    st = _do(st, "use_ultimate")
    st = _do(st, "pass")
    assert st.enemy("e").hp == 3


def test_ally_downed_charges_the_rest_of_the_party():
    st = _state([_char("a", hp=10), _char("b", hp=30)], [_enemy("e", amount=12)])
    st = _drive_turn(st)                        # the 12-damage hit downs "a"
    a, b = st.character("a"), st.character("b")
    assert not a.alive
    assert b.ultimate_gauge >= 25


def test_ultimate_cost_rejected_in_schema():
    with pytest.raises(ValidationError):
        Character(name="X", colors=["U"], starting_mana=["U"],
                  ultimate=_card("u", "Nope", "sorcery", {"generic": 1},
                                 [{"kind": "draw", "amount": 1, "target": SELF}]))


def test_skill_timing_never_instant_legacy_coerced_to_sorcery():
    """Update 11: a Skill is an action or channeled — never instant. A legacy
    instant skill loads coerced to sorcery; sorcery and channeled round-trip."""
    ch = Character(name="X", colors=["U"], starting_mana=["U"],
                   skill=_card("s", "Trick", "instant", {},
                               [{"kind": "draw", "amount": 1, "target": SELF}]))
    assert ch.skill.timing.value == "sorcery"
    ch2 = Character(name="X", colors=["U"], starting_mana=["U"],
                    skill=_card("s", "Ward Stance", "channeled", {},
                                [{"kind": "pump", "power": 0, "toughness": 1,
                                  "duration": "while_channeled", "target": SELF}]))
    assert ch2.skill.timing.value == "channeled"


# ========================================================================== #
# §D8-4 smart auto-pass / auto end-turn
# ========================================================================== #
def test_auto_pass_offered_only_when_nothing_meaningful():
    st = _state([_char("p")], [_enemy("e")])
    st = _do(st, "attack")                      # own window, empty hand
    auto = auto_pass_action(st)
    assert auto is not None and auto.kind == "pass" and auto.auto


def test_auto_pass_ignores_the_skill_in_reaction_windows():
    """Update 11: the Skill is main-phase-only, so an unused Skill no longer
    blocks auto-pass inside a reaction window."""
    st = _heroic_state()
    st = _do(st, "attack")
    auto = auto_pass_action(st)
    assert auto is not None and auto.kind == "pass"


def test_no_auto_end_turn_while_the_skill_could_still_be_used():
    """In the MAIN phase an unspent Skill is a real option: no auto end-turn."""
    st = _heroic_state()
    assert auto_pass_action(st) is None


def test_no_auto_end_turn_before_acting():
    st = _state([_char("p")], [_enemy("e")])
    assert auto_pass_action(st) is None         # attack/defend/move are real options


def test_channeler_is_never_auto_passed():
    """§D8-4.1 amended: a held channel is a standing decision (drop it to free
    the reserved mana, shed a stance, or keep holding) — so no window is
    auto-passed and no turn auto-ended while the holder is channeling."""
    chant = _card("chant", "Chant", "channeled", {"colors": {"U": 1}},
                  [{"kind": "pump", "power": 1, "toughness": 0,
                    "duration": "while_channeled", "target": SELF}])
    st = _state([_char("p", hand=1, library=[chant])], [_enemy("e")])
    st = _do(st, "cast", card_id="chant")
    st = _do(st, "pass")                    # the channel starts (turn action spent)
    assert auto_pass_action(st) is None     # main phase: no auto end-turn
    st = _do(st, "end_turn")
    st = _do(st, "mitigate")                # spend the window's one real option…
    assert auto_pass_action(st) is None     # …the held channel still keeps it open


def test_session_auto_drives_no_decision_stops():
    from ltg_game_server.session import Session
    st = _state([_char("p")], [_enemy("e", amount=1)])
    sess = Session("s1", st)
    sess.claim("cli", ["p"])
    acts = legal_actions(sess.state)
    idx = next(i for i, a in enumerate(acts) if a.kind == "attack")
    sess.apply_index("cli", idx)
    # The attack's own window auto-passed and the spent turn auto-ended…
    assert any(ev.type == "pass" and ev.data.get("auto") for ev in sess.state.log)
    assert any(ev.type == "end_turn" and ev.data.get("auto") for ev in sess.state.log)
    # …but the enemy attack's window WAITS: a ready Mitigate is a real decision
    # that auto-pass never hides (D8-4.3).
    acts = legal_actions(sess.state)
    assert any(a.kind == "mitigate" for a in acts)
    sess.apply_index("cli", next(i for i, a in enumerate(acts) if a.kind == "pass"))
    # After the real pass, the rest of the round auto-drives to the next decision.
    assert sess.state.turn == 2
