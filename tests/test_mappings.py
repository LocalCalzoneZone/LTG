"""Scryfall mapping (mocked) + translation registry + renderer + deck status."""

from unittest.mock import patch

from ltg_deckbuilder import scryfall
from ltg_core.translation import render_effects, translate
from ltg_deckbuilder.ingest import build_card, forbidden_type, parse_mana_cost
from ltg_core.schema import Loadout, deck_status

GIANT_GROWTH_SCRYFALL = {
    "name": "Giant Growth",
    "mana_cost": "{G}",
    "cmc": 1.0,
    "type_line": "Instant",
    "oracle_text": "Target creature gets +3/+3 until end of turn.",
    "rarity": "common",
    "color_identity": ["G"],
}

COUNTERSPELL_SCRYFALL = {
    "name": "Counterspell",
    "mana_cost": "{U}{U}",
    "cmc": 2.0,
    "type_line": "Instant",
    "oracle_text": "Counter target spell.",
    "rarity": "common",
    "color_identity": ["U"],
}


def test_build_card_from_mocked_scryfall_fetch():
    with patch.object(
        scryfall, "fetch_named", return_value=GIANT_GROWTH_SCRYFALL
    ) as mocked:
        data = scryfall.fetch_named("Giant Growth")
        mocked.assert_called_once_with("Giant Growth")

    card = build_card(data)
    assert card.source_name == "Giant Growth"
    assert card.id == "giant_growth"
    assert card.level == 1
    assert card.timing.value == "instant"
    assert card.rarity.value == "common"
    assert card.cost.colors == {"G": 1}
    assert card.cost.generic == 0
    assert card.effects[0].kind == "pump"
    assert card.effects[0].power == 3
    assert not card.needs_translation


def test_counterspell_translates_to_counter_and_is_instant():
    card = build_card(COUNTERSPELL_SCRYFALL)
    assert card.effects[0].kind == "counter"
    assert card.effects[0].filter == "action"
    assert card.effects[0].target.target_class == "action"
    # An instant is reactive by derivation — no separate flag.
    assert card.timing.value == "instant"
    assert card.speed.value == "reactive"
    assert card.cost.colors == {"U": 2}


def test_unrecognized_card_flagged_needs_translation():
    weird = {
        "name": "Strange Brew",
        "mana_cost": "{3}{R}",
        "cmc": 4.0,
        "type_line": "Sorcery",
        "oracle_text": "Some entirely bespoke mechanic with no known template.",
        "rarity": "rare",
    }
    card = build_card(weird)
    assert card.effects == []
    assert card.needs_translation is True
    assert card.translated_text == ""


def test_import_endpoint_never_blocks_and_reports_missing():
    from fastapi.testclient import TestClient
    from ltg_deckbuilder.app import app

    creature = {"name": "Grizzly Bears", "mana_cost": "{1}{G}", "cmc": 2.0,
                "type_line": "Creature — Bear", "rarity": "common", "oracle_text": ""}

    def fake(name):
        if name == "Grizzly Bears":
            return creature
        raise ValueError("not found")

    client = TestClient(app)
    with patch.object(scryfall, "fetch_best", side_effect=fake):
        r = client.post("/api/cards/import",
                        json={"names": ["Grizzly Bears", "Zzz Nope"]}).json()
    # forbidden type (Creature) imports anyway; the missing name is reported.
    assert len(r["cards"]) == 1
    assert r["cards"][0]["card"]["type"] == "Creature — Bear"
    assert r["not_found"] == ["Zzz Nope"]


def test_nonstandard_scryfall_rarity_normalized():
    # Real cards (e.g. Black Lotus) report rarities outside the LTG four;
    # they must fold onto a valid rarity, not crash the builder.
    lotus = {
        "name": "Black Lotus",
        "mana_cost": "{0}",
        "cmc": 0.0,
        "type_line": "Artifact",
        "oracle_text": "{T}, Sacrifice Black Lotus: Add three mana of any one color.",
        "rarity": "bonus",
    }
    card = build_card(lotus)
    assert card.rarity.value == "mythic"
    assert card.needs_translation is True


def test_forbidden_types_detected():
    assert forbidden_type("Legendary Creature — Elf Warrior") == "Creature"
    assert forbidden_type("Artifact — Equipment") == "Artifact"
    assert forbidden_type("Basic Land — Forest") == "Land"
    assert forbidden_type("Legendary Planeswalker — Jace") == "Planeswalker"


def test_allowed_spell_types_pass():
    assert forbidden_type("Instant") is None
    assert forbidden_type("Sorcery") is None
    assert forbidden_type("Enchantment — Aura") is None


def test_sign_in_blood_translates_simple_card():
    sib = {
        "name": "Sign in Blood",
        "mana_cost": "{B}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
        "oracle_text": "Target player draws two cards and loses 2 life.",
        "rarity": "common",
    }
    card = build_card(sib)
    kinds = {e.kind: e for e in card.effects}
    assert "draw" in kinds and kinds["draw"].amount == 2
    assert "lose_life" in kinds and kinds["lose_life"].amount == 2
    assert card.needs_translation is False
    assert "Draw 2" in card.translated_text and "2 HP" in card.translated_text


def test_feed_the_swarm_still_uses_ref_lose_life():
    # Ensure the numeric lose-life rule did not break the "equal to" ref case.
    feed = {
        "name": "Feed the Swarm",
        "mana_cost": "{1}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
        "oracle_text": "Destroy target creature or enchantment. You lose life equal to its mana value.",
        "rarity": "common",
    }
    card = build_card(feed)
    lose = next(e for e in card.effects if e.kind == "lose_life")
    assert lose.amount.ref == "destroyed_target.level"


def test_parse_mana_cost():
    cost = parse_mana_cost("{1}{B}{B}")
    assert cost.generic == 1
    assert cost.colors == {"B": 2}


def test_renderer_matches_brief_example():
    from ltg_core.schema import DealDamage, t_chosen

    text = render_effects([DealDamage(amount=3, target=t_chosen("enemy", targeted=True))])
    assert text == "Deal 3 damage to an enemy."


def test_feed_the_swarm_two_step_translation():
    feed = {
        "name": "Feed the Swarm",
        "mana_cost": "{1}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
        "oracle_text": "Destroy target creature or enchantment. You lose life equal to its mana value.",
        "rarity": "common",
    }
    card = build_card(feed)
    kinds = [e.kind for e in card.effects]
    assert "destroy" in kinds and "lose_life" in kinds


def test_deck_status_reports_warnings():
    loadout = Loadout.model_validate(
        {
            "character": {
                "name": "Test",
                "archetype": "Fighter",
                "colors": ["U", "B"],
                "starting_mana": ["U", "G"],
            },
            "cards": [
                build_card(COUNTERSPELL_SCRYFALL).model_dump(),
                build_card(COUNTERSPELL_SCRYFALL).model_dump(),
                build_card(GIANT_GROWTH_SCRYFALL).model_dump(),
            ],
        }
    )
    status = deck_status(loadout)
    assert status["size"]["count"] == 3
    assert "Counterspell" in status["duplicates"]
    assert "Giant Growth" in status["off_color"]  # G outside U/B identity
    assert status["starting_mana_outside_identity"] == ["G"]
