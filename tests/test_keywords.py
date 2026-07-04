"""Granting & removing keywords: registry-backed grant_keyword / remove_keyword."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ltg_core.translation import render_effects
from ltg_deckbuilder.ingest import build_card
from ltg_core.schema import Card, effect_specs

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CHOSEN_ALLY = {"class": "creature", "mode": "chosen", "side": "ally", "targeted": True}


def card(effects, **kw):
    base = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant"}
    base.update(kw)
    return Card.model_validate({**base, "effects": effects})


def render(effects, **kw):
    c = card(effects, **kw)
    return render_effects(c.effects, c.targets, channeled=(c.timing.value == "channeled"))


# --- worked examples -------------------------------------------------------- #
def test_grant_flying_render():
    assert render([{"kind": "grant_keyword", "keywords": ["flying"],
                    "target": CHOSEN_ALLY, "duration": "this_turn"}]) \
        == "An ally gains Flying until end of turn."


def test_grant_trample_channeled_render():
    assert render([{"kind": "grant_keyword", "keywords": ["trample"],
                    "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"}],
                  type="Enchantment", timing="channeled") \
        == "While channeled: all allies have Trample."


def test_pump_and_grant_compose():
    c = card([
        {"kind": "pump", "power": 2, "toughness": 2, "target": CHOSEN_ALLY, "duration": "this_turn"},
        {"kind": "grant_keyword", "keywords": ["first_strike"], "target": CHOSEN_ALLY, "duration": "this_turn"},
    ])
    kinds = [e.kind for e in c.effects]
    assert kinds == ["pump", "grant_keyword"]
    assert "First Strike" in render_effects(c.effects, c.targets)


def test_remove_renderings():
    assert render([{"kind": "remove_keyword", "keywords": ["flying"], "target": CHOSEN_ALLY}]) \
        == "An ally loses Flying."
    assert render([{"kind": "remove_keyword", "keywords": ["all"], "target": CHOSEN_ALLY}]) \
        == "An ally loses all abilities."


def test_grant_verb_agrees_with_target_number():
    plural = render([{"kind": "grant_keyword", "keywords": ["lifelink"],
                      "target": {"mode": "all", "side": "ally"}, "duration": "this_turn"}])
    assert plural == "All allies gain Lifelink until end of turn."
    single = render([{"kind": "grant_keyword", "keywords": ["flying"],
                      "target": CHOSEN_ALLY, "duration": "this_turn"}])
    assert single == "An ally gains Flying until end of turn."


def test_protection_from_param_renders():
    assert render([{"kind": "grant_keyword", "keywords": ["protection"], "params": {"from": "red"},
                    "target": CHOSEN_ALLY}]) \
        == "An ally gains Protection from red until end of turn."


# --- validation ------------------------------------------------------------- #
def test_retired_keyword_rejected():
    with pytest.raises(ValidationError):
        card([{"kind": "grant_keyword", "keywords": ["menace"], "target": CHOSEN_ALLY}])


def test_unknown_keyword_rejected():
    with pytest.raises(ValidationError):
        card([{"kind": "grant_keyword", "keywords": ["wibble"], "target": CHOSEN_ALLY}])


def test_param_only_where_supported():
    with pytest.raises(ValidationError):
        card([{"kind": "grant_keyword", "keywords": ["flying"], "params": {"from": "red"},
               "target": CHOSEN_ALLY}])


def test_while_channeled_grant_rejected_on_instant():
    with pytest.raises(ValidationError):
        card([{"kind": "grant_keyword", "keywords": ["flying"], "target": CHOSEN_ALLY,
               "duration": "while_channeled"}])


def test_empty_keywords_rejected():
    with pytest.raises(ValidationError):
        card([{"kind": "grant_keyword", "keywords": [], "target": CHOSEN_ALLY}])


# --- auto-translation ------------------------------------------------------- #
def test_auto_grant_flying():
    c = build_card({"name": "Jump", "cmc": 1.0, "type_line": "Instant", "rarity": "common",
                    "oracle_text": "Target creature gains flying until end of turn."})
    assert c.effects[0].kind == "grant_keyword"
    assert c.effects[0].keywords == ["flying"]
    assert "Flying" in c.translated_text


# --- editor metadata + fixtures --------------------------------------------- #
def test_effect_specs_keyword_list():
    specs = effect_specs()
    kw = next(p for p in specs["grant_keyword"]["params"] if p["name"] == "keywords")
    assert kw["control"] == "keyword_list"
    assert "flying" in kw["options"] and "menace" not in kw["options"]
    assert kw["labels"]["flying"] == "Flying"
    rm = next(p for p in specs["remove_keyword"]["params"] if p["name"] == "keywords")
    assert "all" in rm["options"]


@pytest.mark.parametrize("name", ["grant_flying", "trample_anthem"])
def test_keyword_fixtures_round_trip(name):
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    c = Card.model_validate(data)
    assert Card.model_validate(c.model_dump()) == c
