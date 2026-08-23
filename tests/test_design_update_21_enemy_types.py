"""Design Update 21 — enemy types & supertypes.

TYPE = what the creature IS (race: undead, goblin, construct …); CLASS = what
it DOES (role: archer, warrior, wizard …). Up to 2 of each, required at
generation, closed registries. They anchor the art prompt and feed the
target_property card conditions. Player characters carry the same type line
from the sheet (§D21-4).
"""

from __future__ import annotations

import copy

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import (CREATURE_CLASSES, CREATURE_TYPES, Card,
                             TargetPropertyCondition)


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _enemy(eid, types=None, classes=None, hp=10):
    return {"id": eid, "name": eid, "hp": hp, "level": 1, "row": "front",
            "types": types or [], "classes": classes or [],
            "intent": {"name": "Hit", "amount": 1, "action_type": "attack",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


SMITE = {"id": "smite", "name": "Smite", "source_name": "Smite", "rarity": "common",
         "level": 1, "type": "Sorcery", "timing": "sorcery",
         "cost": {"generic": 0, "colors": {}},
         "effects": [{"kind": "conditional",
                      "condition": {"kind": "target_property", "property": "type",
                                    "type": "undead"},
                      "effects": [{"kind": "deal_damage", "amount": 5,
                                   "target": {"mode": "chosen", "side": "enemy",
                                              "targeted": True}}]}],
         "validated": True}


def test_registries_and_condition_validation():
    assert "undead" in CREATURE_TYPES and "wizard" in CREATURE_CLASSES
    TargetPropertyCondition(property="type", type="goblin")
    TargetPropertyCondition.model_validate({"property": "class", "class": "archer"})
    with pytest.raises(ValueError):
        TargetPropertyCondition(property="type", type="kaiju")
    with pytest.raises(ValueError):
        TargetPropertyCondition(property="class")         # value required
    Card.model_validate(SMITE)


def test_the_loader_cleans_and_caps_the_tags():
    st = state_from_dict({
        "party": [{"id": "p", "name": "p", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [_filler("a"), _filler("b")]}],
        "enemies": [_enemy("bones", types=["Undead", "goblin", "beast"],
                           classes="Archer")]})
    e = st.enemy("bones")
    assert e.types == ["undead", "goblin"]        # slugged, capped at 2
    assert e.classes == ["archer"]             # a lone string tolerated


def test_the_condition_gates_on_type_and_supertype():
    st = state_from_dict({
        "party": [{"id": "p", "name": "p", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [copy.deepcopy(SMITE), copy.deepcopy(SMITE)]}],
        "enemies": [_enemy("bones", types=["undead"], classes=["archer"]),
                    _enemy("wolf", types=["beast"], classes=["hunter"])]})
    for _ in range(100):
        acts = legal_actions(st)
        casts = [a for a in acts if a.kind == "cast" and a.card_id == "smite"]
        if casts:
            st = apply_action(st, next(a for a in casts if a.target_id == "bones"))[0]
            break
        a = next((a for a in acts if a.kind == "pass"), None) or \
            next((a for a in acts if a.kind == "end_turn"), None) or acts[0]
        st = apply_action(st, a)[0]
    while st.stack:
        a = next((x for x in legal_actions(st) if x.kind == "pass"), None)
        if a is None:
            break
        st = apply_action(st, a)[0]
    assert st.enemy("bones").hp == 5              # undead: the smite lands
    # Second copy at the wolf: the condition fails, nothing happens.
    for _ in range(100):
        acts = legal_actions(st)
        casts = [a for a in acts if a.kind == "cast" and a.card_id == "smite"]
        if casts:
            st = apply_action(st, next(a for a in casts if a.target_id == "wolf"))[0]
            break
        a = next((a for a in acts if a.kind == "pass"), None) or \
            next((a for a in acts if a.kind == "end_turn"), None) or acts[0]
        st = apply_action(st, a)[0]
    while st.stack:
        a = next((x for x in legal_actions(st) if x.kind == "pass"), None)
        if a is None:
            break
        st = apply_action(st, a)[0]
    assert st.enemy("wolf").hp == 10              # a beast is not an undead


def test_a_corpse_keeps_its_types_and_the_risen_gain_undead():
    from ltg_combat.engine import _clean_tags_rise, _kill_enemy
    st = state_from_dict({
        "party": [{"id": "p", "name": "p", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [_filler("a"), _filler("b")]}],
        "enemies": [_enemy("gob", types=["goblin"], classes=["scout"]),
                    _enemy("other")]})
    _kill_enemy(st, st.enemy("gob"))
    corpse = st.corpse("gob")
    assert corpse is not None and corpse.types == ["goblin"]
    assert corpse.classes == ["scout"]
    assert _clean_tags_rise(["goblin"]) == ["undead", "goblin"]
    assert _clean_tags_rise(["undead"]) == ["undead"]


def test_the_generation_gate_demands_the_tags():
    from ltg_game_server.llm import _type_problems
    bare = {"enemies": [{"name": "Ogre"}]}
    problems = _type_problems(bare)
    assert len(problems) == 2 and all("1–2" in p for p in problems)
    bad = {"enemies": [{"name": "X", "types": ["kaiju"],
                        "classes": ["warrior", "archer", "scout"]}]}
    msgs = " | ".join(_type_problems(bad))
    assert "kaiju" in msgs and "at most 2" in msgs
    good = {"enemies": [{"name": "Ogre", "types": ["giant"], "classes": ["brute"]}]}
    assert _type_problems(good) == []


def test_the_gold_examples_obey_the_gate():
    import re
    from ltg_game_server import llm
    from ltg_game_server.llm import _type_problems
    text = llm.DEFAULT_INSTRUCTIONS
    enemies = []
    for m in re.finditer(r'"id":"([a-z_]+)".*?"types":(\[[^\]]*\]).*?"classes":(\[[^\]]*\])',
                         text):
        import json
        enemies.append({"name": m.group(1), "types": json.loads(m.group(2)),
                        "classes": json.loads(m.group(3))})
    assert len(enemies) >= 10                     # every example enemy is tagged
    assert _type_problems({"enemies": enemies}) == []


def test_the_art_prompt_carries_the_type_line():
    from ltg_game_server.art import enemy_prompt
    p = enemy_prompt({"scene": "a pit"},
                     {"name": "Gravewarden", "description": "A tall thing.",
                      "types": ["undead"], "classes": ["knight"]})
    assert "It is: undead, knight." in p
    # Untagged legacy enemies get no stray line.
    p2 = enemy_prompt({"scene": "a pit"}, {"name": "Ogre", "description": "Big."})
    assert "It is:" not in p2


def test_card_text_reads_naturally():
    from ltg_core.translation import render_effects
    c = Card.model_validate(SMITE)
    assert "an enemy that is an undead" in render_effects(c.effects)


def test_a_heros_type_line_reaches_combat_and_conditions():
    """§D21-4: the sheet's types/classes ride the loadout → party entry →
    CharacterState, so an enemy (or ally card) condition can read them."""
    st = state_from_dict({
        "party": [{"id": "t", "name": "Turin", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "types": ["human"], "classes": ["cleric", "knight"],
                   "library": [_filler("a"), _filler("b")]}],
        "enemies": [_enemy("gob", types=["goblin"], classes=["scout"])]})
    hero = st.character("t")
    assert hero.types == ["human"] and hero.classes == ["cleric", "knight"]


def test_character_sheet_rejects_unknown_tags_and_caps_at_two():
    from ltg_core.schema import Character
    with pytest.raises(ValueError, match="unknown creature type"):
        Character(name="X", colors=["W"], starting_mana=["W"], types=["kaiju"])
    c = Character(name="X", colors=["W"], starting_mana=["W"],
                  classes=["warrior", "warrior", "archer", "scout"])
    assert c.classes == ["warrior", "archer"]     # deduped, capped
