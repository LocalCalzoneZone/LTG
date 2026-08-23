"""§D19-11 — the `break_channel` verb.

The deliberate answer to a held ritual, on both sides of the table: a hero's
Dispel ends an enemy channeler's rite, an enemy's ritual-breaker ends a hero's
aura. All-or-nothing like a breaking hit (GDD §8) — reserved mana returns and
every ending channel fires its `channel_break` trigger.
"""

from __future__ import annotations

import copy

import pytest

from ltg_combat.engine import (_new_ctx, _resolve_effect_list,
                               _try_declare_component, apply_action, legal_actions)
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import StackItem
from ltg_core.schema import Card, effect_specs
from ltg_core.translation import render_effects


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _card(effects, targets=None, **kw):
    base = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "targets": targets or {},
            "effects": effects, "validated": True}
    base.update(kw)
    return Card.model_validate(base)


DISPEL = {"id": "dispel", "name": "Dispel", "source_name": "Dispel",
          "rarity": "common", "level": 1, "type": "Instant", "timing": "instant",
          "cost": {"generic": 0, "colors": {}},
          "effects": [{"kind": "break_channel",
                       "target": {"mode": "chosen", "side": "enemy", "targeted": True}}],
          "validated": True}

AURA = {"id": "aura", "name": "Warcry", "source_name": "Warcry", "rarity": "common",
        "level": 1, "type": "Enchantment", "timing": "channeled",
        "cost": {"generic": 0, "colors": {"U": 2}},
        "effects": [{"kind": "pump", "power": 2, "toughness": 0,
                     "duration": "while_channeled", "target": {"mode": "self"}}],
        "validated": True}

ENEMY_RITE = {"id": "rite", "archetype": "Debilitate", "timing": "proactive",
              "priority": 10, "channel": True, "target_rule": "self",
              "telegraph": "Bleeding Rite",
              "verbs": [{"kind": "wound", "power": 1, "toughness": 1,
                         "duration": "while_channeled",
                         "target": {"mode": "all", "side": "ally"}}]}


def _enemy(eid="ogre", hp=30, components=None, row="front"):
    return {"id": eid, "name": eid, "hp": hp, "level": 3, "power": 2, "row": row,
            "components": components or [],
            "intent": {"name": "Hit", "amount": 2, "action_type": "attack",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _hero(library, identity=("U",), hand=1):
    return {"id": "p", "name": "p", "hp": 30, "power": 2, "hand_size": hand,
            "identity": list(identity), "row": "front", "attack_mode": "melee",
            "library": library}


def _drive(st, until, budget=300):
    for _ in range(budget):
        if until(st):
            return st
        acts = legal_actions(st)
        if not acts:
            return st
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    return st


# --------------------------------------------------------------------------- #
# Authoring surfaces
# --------------------------------------------------------------------------- #
def test_the_verb_is_offered_to_the_editor_and_reads_naturally():
    assert "break_channel" in effect_specs()          # the deckbuilder's kind list
    single = _card([{"kind": "break_channel",
                     "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])
    assert render_effects(single.effects) == "Break the chosen enemy's channels."
    swept = _card([{"kind": "break_channel", "target": {"mode": "all", "side": "enemy"}}])
    assert render_effects(swept.effects) == "Break the channels of all enemies."
    # As a rider chained on a shared slot it needs its subjectless phrase.
    chained = _card([{"kind": "deal_damage", "amount": 3, "target": "$T1"},
                     {"kind": "break_channel", "target": "$T1"}],
                    {"T1": {"mode": "chosen", "side": "enemy", "targeted": True}})
    assert render_effects(chained.effects, chained.targets) == (
        "Choose an enemy: they take 3 damage, then have their channels broken.")


def test_an_enemy_intent_carrying_it_reads_as_interference():
    from ltg_combat.serialize import intent_category
    from ltg_combat.state import Intent
    from ltg_core.schema import BreakChannel, TargetDescriptor
    eff = BreakChannel(target=TargetDescriptor.model_validate(
        {"mode": "chosen", "side": "ally", "targeted": True}))
    intent = Intent(name="Shatter", action_type="ability", effects=[eff], target_id="p")
    assert intent_category(intent) == "interference"


# --------------------------------------------------------------------------- #
# Player → enemy
# --------------------------------------------------------------------------- #
def test_a_hero_card_ends_an_enemy_rite_and_lifts_its_aura():
    st = state_from_dict({
        "party": [_hero([copy.deepcopy(DISPEL), _filler("x")])],
        "enemies": [_enemy("chanter", components=[copy.deepcopy(ENEMY_RITE)])]})
    st = _drive(st, lambda s: bool(s.enemies[0].channels))
    assert st.enemies[0].channels                       # the rite is up
    assert st.character("p").power_bonus == -1          # its wound aura bites

    st = _drive(st, lambda s: any(a.kind == "cast" and a.card_id == "dispel"
                                  for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "dispel")
    st = apply_action(st, cast)[0]
    st = _drive(st, lambda s: not s.stack)

    assert st.enemies[0].channels == []                 # broken
    assert st.character("p").power_bonus == 0           # the aura lifted with it
    assert any(l.type == "channel_end" and l.data.get("reason") == "Dispel"
               for l in st.log)


# --------------------------------------------------------------------------- #
# Enemy → player
# --------------------------------------------------------------------------- #
BREAKER = {"id": "shatter", "archetype": "Debilitate", "timing": "proactive",
           "priority": 10, "target_rule": "channeling_player",
           "telegraph": "Shatter Concentration",
           "condition": {"kind": "hero_channeling", "op": ">=", "value": 1},
           "verbs": [{"kind": "deal_damage", "amount": 3,
                      "target": {"mode": "chosen", "side": "ally", "targeted": True}},
                     {"kind": "break_channel",
                      "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}


def _channelling_hero_state():
    """Drive until the hero is holding the aura — casting it when offered."""
    st = state_from_dict({
        "party": [_hero([copy.deepcopy(AURA), _filler("x"), _filler("y")],
                        identity=("U", "U", "U"), hand=2)],
        "enemies": [_enemy(components=[copy.deepcopy(BREAKER)])]})
    for _ in range(300):
        if st.character("p").channels:
            return st
        acts = legal_actions(st)
        if not acts:
            return st
        a = (next((x for x in acts if x.kind == "cast" and x.card_id == "aura"), None)
             or next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    return st


def test_an_enemy_rider_breaks_a_heros_channel_and_returns_the_mana():
    st = _channelling_hero_state()
    hero = st.character("p")
    assert hero.current_power == 4 and len(hero.pool) == 1      # 2 mana reserved

    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert intent is not None and intent.target_id == "p"       # channeling_player
    item = StackItem(kind="ability", source_id=e.id, source_side="enemy",
                     label=intent.name, effects=intent.effects,
                     target_id=intent.target_id)
    _resolve_effect_list(st, item, item.effects, _new_ctx(st, item))

    hero = st.character("p")
    assert hero.channels == []                 # the aura is gone
    assert hero.current_power == 2             # its pump lifted with it
    assert hero.hp == 27                       # the rider's damage still landed
    assert len(hero.pool) == 3                 # the reserved mana came back (§8)
    assert any(l.type == "mana_released" for l in st.log)


def test_the_gate_keeps_it_from_firing_into_an_empty_board():
    """`hero_channeling` + `channeling_player`: with nothing held the component
    is not eligible, so the enemy falls through to its next rule."""
    st = state_from_dict({
        "party": [_hero([_filler("a"), _filler("b")])],
        "enemies": [_enemy(components=[copy.deepcopy(BREAKER)])]})
    e = st.enemies[0]
    assert _try_declare_component(st, e, e.components[0]) is None


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #
def test_breaking_a_holder_with_nothing_held_is_a_clean_no_op():
    st = state_from_dict({
        "party": [_hero([copy.deepcopy(DISPEL), _filler("x")])],
        "enemies": [_enemy("quiet")]})
    st = _drive(st, lambda s: any(a.kind == "cast" and a.card_id == "dispel"
                                  for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "dispel")
    st = apply_action(st, cast)[0]
    st = _drive(st, lambda s: not s.stack)
    assert any(l.type == "no_channel" for l in st.log)
    assert st.enemies[0].hp == 30              # nothing else happened


def test_a_channel_break_trigger_still_springs():
    """Breaking a ritual deliberately fires its dying sting, exactly as a
    breaking hit does — the answer is not a free out."""
    rite = copy.deepcopy(ENEMY_RITE)
    rite["verbs"].append({"kind": "deal_damage", "amount": 4,
                          "trigger": "channel_break",
                          "target": {"mode": "all", "side": "ally"}})
    st = state_from_dict({
        "party": [_hero([copy.deepcopy(DISPEL), _filler("x")])],
        "enemies": [_enemy("chanter", components=[rite])]})
    st = _drive(st, lambda s: bool(s.enemies[0].channels))
    hp_before = st.character("p").hp
    st = _drive(st, lambda s: any(a.kind == "cast" and a.card_id == "dispel"
                                  for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "dispel")
    st = apply_action(st, cast)[0]
    st = _drive(st, lambda s: not s.stack)
    assert st.enemies[0].channels == []
    assert st.character("p").hp == hp_before - 4        # the sting landed
