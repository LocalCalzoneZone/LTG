"""Explicit mana payment for a cast (UI-driven non-deterministic mana selection).

When a spell's generic pips could be paid more than one way from the pool, the
client lets the player choose which colours to spend and submits them on the
action. The engine's `_pay` honours that choice after validating it exactly
settles the cost; an invalid choice is rejected (the engine stays the authority).
"""

import pytest

from ltg_core.schema import Card
from ltg_combat.engine import _pay, _validate_payment
from ltg_combat.state import CharacterState


def _card(cost):
    return Card.model_validate({
        "id": "spell", "name": "Test Spell", "source_name": "Test Spell",
        "rarity": "common", "level": 2, "type": "Sorcery", "timing": "sorcery",
        "cost": cost, "effects": [],
    })


def _char(pool):
    return CharacterState(id="c", name="Caster", max_hp=10, hp=10, power=1,
                          hand_size=0, identity=list("UB"),
                          mana_colors=list(pool), pool=list(pool))


def test_explicit_payment_spends_exactly_the_chosen_colours():
    # Cost 2B, pool UUBB -> the player may pay the generic 2 as U+U (keeping a B).
    char = _char("UUBB")
    card = _card({"generic": 2, "colors": {"B": 1}})
    paid = _pay(char, card, explicit=["B", "U", "U"])
    assert sorted(paid) == ["B", "U", "U"]
    assert sorted(char.pool) == ["B"]  # one B remains, as chosen


def test_explicit_payment_alternate_choice():
    # Same cost/pool, the other legal split: generic paid as U+B, keeping a U.
    char = _char("UUBB")
    card = _card({"generic": 2, "colors": {"B": 1}})
    paid = _pay(char, card, explicit=["B", "U", "B"])
    assert sorted(paid) == ["B", "B", "U"]
    assert sorted(char.pool) == ["U"]


def test_deterministic_payment_unchanged_without_explicit():
    # No explicit choice -> WUBRG order (U before B for the generic).
    char = _char("UUBB")
    card = _card({"generic": 2, "colors": {"B": 1}})
    paid = _pay(char, card)
    assert sorted(paid) == ["B", "U", "U"]


def test_payment_missing_required_colour_is_rejected():
    char = _char("UUBB")
    card = _card({"generic": 2, "colors": {"B": 1}})
    with pytest.raises(ValueError):
        _validate_payment(char, card, ["U", "U", "U"])  # no B for the coloured pip


def test_payment_wrong_total_is_rejected():
    char = _char("UUBB")
    card = _card({"generic": 2, "colors": {"B": 1}})
    with pytest.raises(ValueError):
        _validate_payment(char, card, ["B", "U"])  # only 2 mana, cost needs 3


def test_payment_beyond_pool_is_rejected():
    char = _char("UBB")
    card = _card({"generic": 2, "colors": {"B": 1}})
    with pytest.raises(ValueError):
        _validate_payment(char, card, ["B", "U", "U"])  # only one U in pool
