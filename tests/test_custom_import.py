"""Custom-card JSON import (/api/cards/import-custom): entries get the same
MTG rules-text translation pass as Scryfall imports, malformed entries are
reported per-card without failing the batch, and nothing is ever replaced —
the endpoint only returns cards for the client to APPEND to the loadout."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ltg_deckbuilder import app as db_app
from ltg_deckbuilder import ingest


@pytest.fixture()
def client():
    return TestClient(db_app.app)


def _entry(**over):
    base = {
        "name": "Ember Lash",
        "type": "instant",
        "mana_cost": "{1}{R}",
        "effect": "Ember Lash deals 3 damage to any target.",
        # In-character effect description → the editor's Flavour field.
        "flavour": "A whip of living flame, snapped across the battlefield to sear a single foe.",
    }
    base.update(over)
    return base


def test_import_custom_translates_and_maps_fields(client):
    res = client.post("/api/cards/import-custom", json={"cards": [_entry()]})
    assert res.status_code == 200
    body = res.json()
    assert body["errors"] == []
    [item] = body["cards"]
    card = item["card"]
    assert card["name"] == "Ember Lash"
    assert card["source_name"] == "Ember Lash"
    assert card["timing"] == "instant"
    assert card["cost"] == {"generic": 1, "colors": {"R": 1}}
    assert card["level"] == 2  # converted cost
    # `flavour` maps onto Card.flavor_text — the Deckbuilder's "how the
    # effect works 'in character'" editor field.
    assert card["flavor_text"] == (
        "A whip of living flame, snapped across the battlefield to sear a single foe."
    )
    assert card["rarity"] == "common"  # default
    assert card["validated"] is False  # humans ratify effects, always
    # The oracle-style damage line must have translated into effects.
    assert card["effects"], card
    assert card["needs_translation"] is False
    assert card["translated_text"]


def test_import_custom_untranslatable_is_flagged_not_rejected(client):
    entry = _entry(name="Weirdling", effect="Exsanguinate the fourth moon.")
    res = client.post("/api/cards/import-custom", json={"cards": [entry]})
    body = res.json()
    assert body["errors"] == []
    [item] = body["cards"]
    assert item["card"]["needs_translation"] is True
    assert item["card"]["effects"] == []


def test_import_custom_bad_entries_reported_per_card(client):
    cards = [
        _entry(),
        {"type": "instant", "effect": "Draw a card."},          # no name
        _entry(name="Golem", type="artifact"),                   # bad type
        _entry(name="Blank", effect=""),                         # no effect
    ]
    res = client.post("/api/cards/import-custom", json={"cards": cards})
    body = res.json()
    assert len(body["cards"]) == 1
    assert len(body["errors"]) == 3
    reasons = {e["name"]: e["reason"] for e in body["errors"]}
    assert "name" in reasons["card #2"]
    assert "type" in reasons["Golem"]
    assert "effect" in reasons["Blank"]


def test_import_custom_enchantment_is_channeled(client):
    entry = _entry(
        name="Wardsong", type="Enchantment", mana_cost="1WW",
        effect="Creatures you control get +0/+1.",
    )
    res = client.post("/api/cards/import-custom", json={"cards": [entry]})
    [item] = res.json()["cards"]
    assert item["card"]["timing"] == "channeled"
    assert item["card"]["type"] == "Enchantment"
    assert item["card"]["cost"] == {"generic": 1, "colors": {"W": 2}}


def test_parse_mana_cost_loose_forms():
    assert ingest.parse_mana_cost_loose("{2}{G}{G}").model_dump() == {
        "generic": 2, "colors": {"G": 2}}
    assert ingest.parse_mana_cost_loose("2GG").model_dump() == {
        "generic": 2, "colors": {"G": 2}}
    assert ingest.parse_mana_cost_loose(3).model_dump() == {"generic": 3, "colors": {}}
    assert ingest.parse_mana_cost_loose("").model_dump() == {"generic": 0, "colors": {}}
