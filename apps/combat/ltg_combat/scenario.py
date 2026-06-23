"""The §A encounter, built as explicit engine inputs.

This is the *scenario* (a loadout/encounter), not the engine. It supplies the
resolved starting stats (HP / Power / hand size / mana colours), the exact
library order, the opening hands, and the two minions — everything the engine
treats as input. Cards are real `core` models (schema-validated), so the engine
reads the same effect vocabulary the Deckbuilder emits.

`build_state()` returns the raw pre-upkeep state (the §A.3 setup, before the
turn-1 draw). Handing that straight to `legal_actions` / `apply_action` lets the
engine bootstrap the opening automatically.
"""

from __future__ import annotations

from typing import Dict, List

from ltg_core.schema import Card

from .state import CharacterState, EnemyState, GameState

# Readable target descriptors (the §6 aliases, in their canonical structured form).
TARGETED_ENEMY = {"mode": "chosen", "side": "enemy", "targeted": True}
TARGETED_ALLY = {"mode": "chosen", "side": "ally", "targeted": True}
SELF = {"mode": "self"}


def _card(cid, name, timing, cost, level, effects, rarity="common") -> Card:
    """Validate one scenario card through `core`'s schema."""
    type_ = {"instant": "Instant", "sorcery": "Sorcery", "channeled": "Enchantment"}[timing]
    return Card.model_validate({
        "id": cid, "name": name, "source_name": name, "rarity": rarity,
        "level": level, "type": type_, "timing": timing, "cost": cost,
        "effects": effects, "validated": True,
    })


# --------------------------------------------------------------------------- #
# §A.1 — the loadouts (ordered libraries, top -> bottom)
# --------------------------------------------------------------------------- #
SOREN_LIBRARY: List[Card] = [
    _card("guard", "Guard", "instant", {"colors": {"W": 1}}, 1,
          [{"kind": "prevent", "amount": 2, "target": TARGETED_ALLY, "duration": "this_turn"}]),
    _card("sunlance", "Sunlance", "sorcery", {"colors": {"W": 1}}, 1,
          [{"kind": "deal_damage", "amount": 3, "target": TARGETED_ENEMY}]),
    _card("steady_blade", "Steady Blade", "instant", {"colors": {"G": 1}}, 1,
          [{"kind": "pump", "power": 1, "toughness": 1, "target": TARGETED_ALLY,
            "duration": "end_of_turn"}]),
    _card("mend", "Mend", "instant", {"colors": {"W": 1}}, 1,
          [{"kind": "heal", "amount": 3, "target": TARGETED_ALLY}]),
    _card("valors_edge", "Valor's Edge", "instant", {"colors": {"G": 1}}, 2,
          [{"kind": "pump", "power": 2, "toughness": 2, "target": TARGETED_ALLY,
            "duration": "end_of_turn"}], rarity="uncommon"),
    _card("bulwark", "Bulwark", "sorcery", {"colors": {"W": 1}}, 1,
          [{"kind": "pump", "power": 0, "toughness": 3, "target": SELF,
            "duration": "end_of_turn"}]),
]

YS_LIBRARY: List[Card] = [
    _card("unmake", "Unmake", "sorcery", {"generic": 1, "colors": {"B": 1}}, 2,
          [{"kind": "destroy", "target": TARGETED_ENEMY},
           {"kind": "lose_life", "amount": {"ref": "destroyed_target.level"}, "target": SELF}],
          rarity="uncommon"),
    _card("mind_spike", "Mind Spike", "instant", {"colors": {"U": 1}}, 1,
          [{"kind": "deal_damage", "amount": 2, "target": TARGETED_ENEMY}]),
    _card("whispers", "Whispers", "sorcery", {"colors": {"U": 1}}, 1,
          [{"kind": "draw", "amount": 1, "target": SELF}]),
    _card("sift", "Sift", "sorcery", {"colors": {"U": 1}}, 1,
          [{"kind": "scry", "amount": 1, "target": SELF}]),
    _card("nightcreep", "Nightcreep", "sorcery", {"colors": {"B": 1}}, 1,
          [{"kind": "deal_damage", "amount": 2, "target": TARGETED_ENEMY}]),
    _card("leech", "Leech", "instant", {"colors": {"B": 1}}, 1,
          [{"kind": "deal_damage", "amount": 1, "target": TARGETED_ENEMY},
           {"kind": "heal", "amount": 1, "target": SELF}]),
]


def _member(cid, name, hp, power, hand_size, identity, library: List[Card]) -> CharacterState:
    """Deal the opening hand off the top of the ordered library (the rest is the
    draw pile). Mana starts empty; the turn-1 upkeep refreshes it."""
    hand = [c.model_copy(deep=True) for c in library[:hand_size]]
    draw_pile = [c.model_copy(deep=True) for c in library[hand_size:]]
    return CharacterState(
        id=cid, name=name, max_hp=hp, hp=hp, power=power, hand_size=hand_size,
        hand=hand, library=draw_pile, identity=list(identity),
        mana_colors=list(identity), pool=[],
    )


def build_state() -> GameState:
    """The §A.3 setup state: encounter start, before Turn 1's upkeep."""
    soren = _member("soren", "Soren", hp=25, power=2, hand_size=2,
                    identity=["G", "W"], library=SOREN_LIBRARY)
    ys = _member("ys", "Ys", hp=15, power=1, hand_size=4,
                 identity=["U", "B"], library=YS_LIBRARY)

    skitterling = EnemyState(id="skitterling", name="Skitterling", max_hp=3, hp=3, level=1,
                             intent_template={"name": "Claw", "amount": 2, "action_type": "ability"})
    brute = EnemyState(id="brute", name="Brute", max_hp=8, hp=8, level=3,
                       intent_template={"name": "Smash", "amount": 4, "action_type": "ability"})

    return GameState(party=[soren, ys], enemies=[skitterling, brute], turn=1, phase="upkeep")


def hand_names(char) -> List[str]:
    return [c.name for c in char.hand]


def mana(char) -> List[str]:
    return list(char.pool)
