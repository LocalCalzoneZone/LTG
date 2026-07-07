"""Enemy SPELLS (GDD action taxonomy): enemies have no cards, so "spell" is a
thematic class on a component (`action_type: "spell"` — Fireball, a curse), but
it is mechanically real: the component stacks as kind "spell", the UI tags it
"spell", and spell-only counters (Negate/Dispel, filter "spell") answer it.
Physical components stay "ability"; reactions land as "triggered" (Retaliate),
which "ability"/"action" counters answer and "spell" counters don't."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.serialize import _stack_list, action_mode

_NEGATE = {"id": "negate", "name": "Negate", "source_name": "Negate",
           "rarity": "common", "level": 1, "type": "Instant", "timing": "instant",
           "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "counter", "filter": "spell",
                        "target": {"class": "action", "side": "enemy"}}],
           "validated": True}


def _enemy(components, eid="mage"):
    return {"id": eid, "name": eid, "hp": 12, "level": 3,
            "intent": {"name": "Bash", "amount": 1, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"},
            "components": components}


_FIREBALL = {  # proactive, spell-classed — Negate's prey
    "id": "fireball", "archetype": "Burst", "timing": "proactive",
    "priority": 20, "cooldown": 2, "target_rule": "valuation",
    "action_type": "spell", "telegraph": "Fireball — deal 4",
    "verbs": [{"kind": "deal_damage", "amount": 4,
               "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}

_SPOREFOG = {  # proactive, physical — NOT a spell
    "id": "sporefog", "archetype": "Debilitate", "timing": "proactive",
    "priority": 20, "cooldown": 2, "target_rule": "valuation",
    "telegraph": "Spore Fog — wound",
    "verbs": [{"kind": "wound", "power": 1, "toughness": 1,
               "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}

_RETALIATE = {  # reactive, physical — a TRIGGERED ability
    "id": "retaliate", "archetype": "Punish", "timing": "reactive",
    "trigger": "on_hit", "cooldown": 2, "priority": 25,
    "target_rule": "trigger_source", "telegraph": "Retaliate — deal 2",
    "verbs": [{"kind": "deal_damage", "amount": 2,
               "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}


def _state(components, hand=None):
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 3,
                   "hand_size": len(hand or []), "identity": ["U"], "row": "front",
                   "attack_mode": "melee", "library": hand or []}],
        "enemies": [_enemy(components)],
    })


def _run_to_enemy_stack(st):
    """End the turn and stop when the enemy's action sits on the stack."""
    while not st.stack:
        acts = legal_actions(st)
        a = (next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    return st


def test_spell_component_stacks_as_spell():
    st = _run_to_enemy_stack(_state([dict(_FIREBALL)]))
    (row,) = _stack_list(st)
    assert row["kind"] == "spell" and row["mode"] == "spell"
    assert "Fireball" in row["label"]


def test_ability_component_stays_ability():
    st = _run_to_enemy_stack(_state([dict(_SPOREFOG)]))
    (row,) = _stack_list(st)
    assert row["kind"] == "ability" and row["mode"] == "ability"


def test_negate_counters_the_fireball():
    st = _run_to_enemy_stack(_state([dict(_FIREBALL)], hand=[dict(_NEGATE)]))
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "negate")
    st = apply_action(st, cast)[0]
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    assert any(e.type == "countered" for e in st.log)
    assert st.character("p").hp == 20              # the Fireball never landed


def test_negate_cannot_answer_a_physical_ability():
    st = _run_to_enemy_stack(_state([dict(_SPOREFOG)], hand=[dict(_NEGATE)]))
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "negate"]
    assert casts == []                             # nothing spell-kind to counter


def test_reaction_lands_as_triggered_and_spell_counter_ignores_it():
    st = _state([dict(_RETALIATE)], hand=[dict(_NEGATE)])
    att = next(a for a in legal_actions(st) if a.kind == "attack")
    st = apply_action(st, att)[0]                  # the swing goes on the stack
    st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    # …the hit resolved, and the on_hit Retaliate now sits on the stack.
    row = next(r for r in _stack_list(st) if "Retaliate" in r["label"])
    assert row["kind"] == "triggered"
    assert row["mode"] == "ability"                # UI vocabulary: it's an ability
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "negate"]
    assert casts == []                             # a spell counter can't touch it
    assert action_mode("triggered", "melee") == "ability"