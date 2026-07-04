"""Boss framework (§F-9) + expanded enemy Debilitate (§F-3): player-side stun and
taunt-us, the on_ally_below_X trigger, boss removal immunity outside the execute
window (≤25% max HP), the one-shot auto-firing Enrage component, and phase gates.

Driven through the engine's legal_actions / apply_action contract wherever the
behaviour is player-visible; phase-gate eligibility is asserted directly."""

from __future__ import annotations

from ltg_combat.engine import _component_eligible, apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import Heal, Stun, Taunt, t_chosen


# --------------------------------------------------------------------------- #
# Harness (conventions from test_enemy_reaction / test_taunt)
# --------------------------------------------------------------------------- #
def _free_instant(cid, effects):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "effects": effects,
            "validated": True}


def _char(cid, power=3, hp=30, hand=None):
    hand = hand or []
    return {"id": cid, "name": cid, "hp": hp, "power": power,
            "hand_size": len(hand), "identity": ["U"], "row": "front",
            "attack_mode": "melee", "library": hand}


def _enemy(eid, hp=10, amount=2, level=3):
    return {"id": eid, "name": eid, "hp": hp, "level": level,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _state(party, enemies, tweak=None, **spec_extra):
    st = state_from_dict({"party": party, "enemies": enemies, **spec_extra})
    if tweak:
        tweak(st)
    return st


def _act(st, **kw):
    a = next(a for a in legal_actions(st)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(st, a)[0]


def _pass_all(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


# --------------------------------------------------------------------------- #
# Player-side stun (enemy Debilitate)
# --------------------------------------------------------------------------- #
def _stunner_on_hit():
    return Component(id="daze", archetype="Debilitate", timing="reactive",
                     trigger="on_hit", cooldown=2, priority=20,
                     verbs=[Stun(target=t_chosen("ally", targeted=True))],
                     target_rule="trigger_source", telegraph="Dazing Blow")


def test_enemy_stun_denies_player_main_window():
    st = _state([_char("p", power=2)], [_enemy("e", hp=20)],
                tweak=lambda s: s.enemies[0].components.append(_stunner_on_hit()))
    st = _act(st, kind="attack", actor_id="p")   # hit the enemy -> on_hit stun back
    st = _pass_all(st)
    p = st.character("p")
    assert p.stunned == 1
    # The proactive window collapses to a single labelled End Turn.
    acts = legal_actions(st)
    assert [a.kind for a in acts] == ["end_turn"]
    assert "Stunned" in acts[0].label
    # Ending the stunned turn spends the stack.
    st = apply_action(st, acts[0])[0]
    assert st.character("p").stunned == 0


# --------------------------------------------------------------------------- #
# Player-side taunt-us (enemy Debilitate)
# --------------------------------------------------------------------------- #
def _taunter_on_hit():
    return Component(id="challenge", archetype="Debilitate", timing="reactive",
                     trigger="on_hit", cooldown=2, priority=20,
                     verbs=[Taunt(target=t_chosen("ally", targeted=True))],
                     target_rule="trigger_source", telegraph="Face me!")


def test_enemy_taunt_binds_attacks_to_the_taunter():
    st = _state([_char("p")], [_enemy("e1", hp=20), _enemy("e2", hp=20)],
                tweak=lambda s: s.enemies[0].components.append(_taunter_on_hit()))
    st = _act(st, kind="attack", actor_id="p", target_id="e1")
    st = _pass_all(st)
    assert st.character("p").taunted_to == "e1"


def test_taunt_restricts_targets_and_dies_with_taunter():
    # Settle PAST upkeep first (upkeep clears the per-turn taunt), then bind.
    st = settle(_state([_char("p")], [_enemy("e1", hp=20), _enemy("e2", hp=20)]))
    st.party[0].taunted_to = "e1"
    attacks = [a for a in legal_actions(st) if a.kind == "attack"]
    assert {a.target_id for a in attacks} == {"e1"}          # bound to the taunter
    st.enemies[0].hp = 0                                     # taunter dies
    attacks = [a for a in legal_actions(st) if a.kind == "attack"]
    assert {a.target_id for a in attacks} == {"e2"}          # bind lifted


# --------------------------------------------------------------------------- #
# on_ally_below_X trigger
# --------------------------------------------------------------------------- #
def _rescue_below_50():
    return Component(id="rescue", archetype="Fortify", timing="reactive",
                     trigger="on_ally_below_50", cooldown=2, priority=15,
                     verbs=[Heal(amount=5, target=t_chosen("ally", targeted=True))],
                     target_rule="lowest_hp_ally", telegraph="Emergency Mend")


def test_on_ally_below_trigger_fires_on_the_crossing():
    # p (power 6) hits the 10-HP bruiser -> 4 HP (<50%) -> the medic reacts, heal 5.
    st = _state([_char("p", power=6)], [_enemy("bruiser", hp=10), _enemy("medic", hp=8)],
                tweak=lambda s: s.enemies[1].components.append(_rescue_below_50()))
    st = _act(st, kind="attack", actor_id="p", target_id="bruiser")
    st = _pass_all(st)
    assert any(ev.type == "enemy_react" and ev.data.get("enemy") == "medic"
               for ev in st.log)
    assert st.enemy("bruiser").hp == 9                        # 10 - 6 + 5


def test_on_ally_below_does_not_fire_above_threshold():
    # power 4 -> bruiser at 6/10 (60%): no crossing, no reaction.
    st = _state([_char("p", power=4)], [_enemy("bruiser", hp=10), _enemy("medic", hp=8)],
                tweak=lambda s: s.enemies[1].components.append(_rescue_below_50()))
    st = _act(st, kind="attack", actor_id="p", target_id="bruiser")
    st = _pass_all(st)
    assert not any(ev.type == "enemy_react" for ev in st.log)


# --------------------------------------------------------------------------- #
# Boss: removal immunity outside the execute window
# --------------------------------------------------------------------------- #
_DOOM = _free_instant("doom", [{"kind": "destroy",
                                "target": {"mode": "chosen", "side": "enemy",
                                           "targeted": True}}])
_UNDERTOW = _free_instant("undertow", [{"kind": "bounce",
                                        "target": {"mode": "chosen", "side": "enemy",
                                                   "targeted": True}}])


def _boss(hp=20, level=6, **extra):
    e = _enemy("boss", hp=hp, level=level)
    e["is_boss"] = True
    e.update(extra)
    return e


def test_boss_shrugs_destroy_above_25_percent():
    st = _state([_char("p", hand=[dict(_DOOM)])], [_boss(hp=20)])
    st = _act(st, kind="cast", card_id="doom", target_id="boss")
    st = _pass_all(st)
    boss = st.enemy("boss")
    assert boss.alive and boss.hp == 20
    assert any(ev.type == "boss_immune" for ev in st.log)


def test_boss_destroyed_inside_execute_window():
    st = _state([_char("p", hand=[dict(_DOOM)])], [_boss(hp=20)],
                tweak=lambda s: setattr(s.enemies[0], "hp", 5))   # 25% of 20
    st = _act(st, kind="cast", card_id="doom", target_id="boss")
    st = _pass_all(st)
    boss = st.enemy("boss")   # a killed enemy leaves the roster (None) or lies dead
    assert boss is None or not boss.alive


def test_boss_shrugs_bounce_above_25_percent():
    st = _state([_char("p", hand=[dict(_UNDERTOW)])], [_boss(hp=20)])
    st = _act(st, kind="cast", card_id="undertow", target_id="boss")
    st = _pass_all(st)
    boss = st.enemy("boss")
    assert boss.alive and not boss.in_hand
    assert any(ev.type == "boss_immune" for ev in st.log)


# --------------------------------------------------------------------------- #
# Boss: enrage (auto-fires once, at the crossing) + phase gates
# --------------------------------------------------------------------------- #
_ZAP = _free_instant("zap", [{"kind": "deal_damage", "amount": 1,
                              "target": {"mode": "chosen", "side": "enemy",
                                         "targeted": True}}])

_ENRAGE_SPEC = {  # authored form: the loader canonicalises Enrage (§F-9)
    "id": "fury", "archetype": "Enrage", "priority": 5,
    "target_rule": "self", "telegraph": "Volcanic Fury",
    "verbs": [{"kind": "counters", "power": 3, "toughness": 0,
               "target": {"mode": "self"}}],
}


def test_enrage_fires_once_at_the_crossing():
    st = _state([_char("p", power=16, hand=[dict(_ZAP)])],
                [_boss(hp=20, components=[dict(_ENRAGE_SPEC)])])
    boss = st.enemy("boss")
    base_power = boss.power
    st = _act(st, kind="attack", actor_id="p", target_id="boss")  # 20 -> 4 (<=25%)
    st = _pass_all(st)
    boss = st.enemy("boss")
    assert boss.enraged
    assert any(ev.type == "enrage" for ev in st.log)
    fires = [ev for ev in st.log if ev.type == "enemy_react"
             and ev.data.get("label") == "Volcanic Fury"]
    assert len(fires) == 1
    assert boss.power == base_power + 3                       # the counters landed
    # A second hit in the window must NOT refire the once-per-encounter enrage.
    st = _act(st, kind="cast", card_id="zap", target_id="boss")
    st = _pass_all(st)
    fires = [ev for ev in st.log if ev.type == "enemy_react"
             and ev.data.get("label") == "Volcanic Fury"]
    assert len(fires) == 1


def test_loader_canonicalises_enrage_component():
    st = _state([_char("p")], [_boss(hp=20, components=[dict(_ENRAGE_SPEC)])])
    comp = st.enemy("boss").components[0]
    assert comp.timing == "reactive"
    assert comp.trigger == "on_enrage"
    assert comp.once_per_encounter


def test_phase_gates_flip_with_enrage():
    pre = Component(id="pre", archetype="Burst", phase="pre_enrage")
    post = Component(id="post", archetype="Burst", phase="post_enrage")
    st = _state([_char("p")], [_boss(hp=20)])
    boss = st.enemy("boss")
    assert _component_eligible(st, boss, pre)
    assert not _component_eligible(st, boss, post)
    boss.enraged = True
    assert not _component_eligible(st, boss, pre)
    assert _component_eligible(st, boss, post)
