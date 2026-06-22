"""Lands & mana: ramp / add_mana effects, land→capacity translation, rendering."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ltg_core.translation import render_effects
from ltg_deckbuilder.ingest import build_card
from ltg_core.schema import Card, Loadout, deck_status

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def card(effects, **kw):
    base = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
            "level": 2, "type": "Sorcery", "timing": "sorcery"}
    base.update(kw)
    return Card.model_validate({**base, "effects": effects})


def render(effects):
    return render_effects(card(effects).effects)


# --- rendering (worked examples + §6) --------------------------------------- #
def test_ramp_renderings():
    assert render([{"kind": "ramp", "amount": 1, "color": "choice", "availability": "tapped"}]) \
        == "Add 1 mana capacity of your choice (not usable this turn)."
    assert render([{"kind": "ramp", "amount": 1, "color": "G", "availability": "immediate"}]) \
        == "Add 1 green mana capacity (usable this turn)."
    assert render([{"kind": "ramp", "amount": 1, "color": "G", "availability": "deferred"}]) \
        == "At the start of your next turn, add 1 green mana capacity."


def test_add_mana_rendering():
    assert render([{"kind": "add_mana", "amount": 3, "color": "B"}]) \
        == "Add 3 black mana to your pool this turn."


# --- auto-build worked examples --------------------------------------------- #
def test_rampant_growth_auto_builds_ramp():
    c = build_card({
        "name": "Rampant Growth", "mana_cost": "{1}{G}", "cmc": 2.0,
        "type_line": "Sorcery", "rarity": "common",
        "oracle_text": "Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.",
    })
    e = c.effects[0]
    assert e.kind == "ramp" and e.color == "choice" and e.availability == "tapped"
    assert c.translated_text == "Add 1 mana capacity of your choice (not usable this turn)."


def test_dark_ritual_auto_builds_add_mana():
    c = build_card({
        "name": "Dark Ritual", "mana_cost": "{B}", "cmc": 1.0,
        "type_line": "Instant", "rarity": "common", "oracle_text": "Add {B}{B}{B}.",
    })
    e = c.effects[0]
    assert e.kind == "add_mana" and e.amount == 3 and e.color == "B"


def test_named_land_maps_to_colour():
    c = build_card({
        "name": "Nature's Lore", "mana_cost": "{1}{G}", "cmc": 2.0,
        "type_line": "Sorcery", "rarity": "common",
        "oracle_text": "Search your library for a Forest card and put it onto the battlefield.",
    })
    assert c.effects[0].kind == "ramp" and c.effects[0].color == "G"
    assert c.effects[0].availability == "immediate"  # not tapped


# --- validation ------------------------------------------------------------- #
def test_bad_availability_rejected():
    with pytest.raises(ValidationError):
        card([{"kind": "ramp", "amount": 1, "color": "G", "availability": "soon"}])


def test_bad_color_rejected():
    with pytest.raises(ValidationError):
        card([{"kind": "add_mana", "amount": 1, "color": "P"}])


def test_off_identity_ramp_flagged_in_deck_status():
    loadout = Loadout.model_validate({
        "character": {"name": "Mono", "archetype": "Fighter", "colors": ["U"], "starting_mana": ["U", "U"]},
        "cards": [{**card([{"kind": "ramp", "amount": 1, "color": "R", "availability": "tapped"}]).model_dump(),
                   "name": "Off Ramp", "cost": {"colors": {"U": 1}}}],
    })
    assert "Off Ramp" in deck_status(loadout)["off_color"]


def test_choice_ramp_not_flagged():
    loadout = Loadout.model_validate({
        "character": {"name": "Mono", "archetype": "Fighter", "colors": ["U"], "starting_mana": ["U", "U"]},
        "cards": [{**card([{"kind": "ramp", "amount": 1, "color": "choice", "availability": "tapped"}]).model_dump(),
                   "name": "Choice Ramp", "cost": {"colors": {"U": 1}}}],
    })
    assert deck_status(loadout)["off_color"] == []


# --- land references: "for each land" + landfall ---------------------------- #
def test_for_each_land_renders_as_capacity():
    cap = {"ref": "mana_capacity"}
    assert render([{"kind": "draw", "amount": cap, "target": {"mode": "self"}}]) \
        == "Draw a card for each point of mana capacity."
    assert render([{"kind": "deal_damage", "amount": cap,
                    "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]) \
        == "Deal 1 damage to an enemy for each point of mana capacity."
    assert render([{"kind": "lose_life", "amount": cap, "target": {"mode": "self"}}]) \
        == "Lose 1 HP for each point of mana capacity."


def test_for_each_land_auto_build():
    c = build_card({
        "name": "Reach", "cmc": 3.0, "type_line": "Sorcery", "rarity": "rare",
        "oracle_text": "Draw a card for each land you control.",
    })
    assert c.effects[0].amount == {"ref": "mana_capacity"} or c.effects[0].amount.ref == "mana_capacity"
    assert c.translated_text == "Draw a card for each point of mana capacity."


def test_landfall_trigger_render_and_validation():
    c = Card.model_validate({
        "id": "x", "name": "x", "source_name": "x", "rarity": "rare", "level": 2,
        "type": "Enchantment", "timing": "channeled",
        "effects": [{"kind": "create_token", "token_id": "treasure", "count": 1,
                     "trigger": "capacity_increase"}],
    })
    assert render_effects(c.effects, c.targets, channeled=True) \
        == "Whenever your mana capacity increases: create a Treasure ally."


def test_capacity_increase_rejected_on_non_channeled():
    with pytest.raises(ValidationError):
        card([{"kind": "heal", "amount": 1, "target": {"mode": "chosen", "side": "ally"},
               "trigger": "capacity_increase"}], timing="sorcery")


# --- fixtures --------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["rampant_growth", "cultivate", "dark_ritual",
                                  "for_each_land", "landfall"])
def test_mana_fixtures_round_trip(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    c = Card.model_validate(data)
    assert Card.model_validate(c.model_dump()) == c
