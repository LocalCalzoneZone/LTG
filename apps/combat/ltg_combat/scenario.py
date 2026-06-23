"""Encounters as explicit engine inputs — the §A default, plus a JSON loader.

A *scenario* (a loadout/encounter) is data the engine consumes, not rules. It
supplies resolved starting stats (HP / Power / hand size / mana colours), the
exact ordered library (determinism depends on it), the opening hand size, and the
minions. Cards are real `core` models, schema-validated on the way in.

One dict shape is the single source of truth: `SCENARIO_A` is the §A fight, and
`state_from_dict` turns any such dict (default or loaded from a file) into a
`GameState`. `build_state()` is the §A default; `load_scenario(path)` reads a
scenario JSON in the same shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from ltg_core.schema import Card

from .state import CharacterState, EnemyState, GameState

# Readable target descriptors (the §6 aliases, in their canonical structured form).
TARGETED_ENEMY = {"mode": "chosen", "side": "enemy", "targeted": True}
TARGETED_ALLY = {"mode": "chosen", "side": "ally", "targeted": True}
SELF = {"mode": "self"}

_TIMING_TYPE = {"instant": "Instant", "sorcery": "Sorcery", "channeled": "Enchantment"}


def _cd(cid, name, timing, cost, level, effects, rarity="common") -> Dict[str, Any]:
    """A card as a plain dict (validated to a `core` Card by `state_from_dict`)."""
    return {
        "id": cid, "name": name, "source_name": name, "rarity": rarity,
        "level": level, "type": _TIMING_TYPE[timing], "timing": timing,
        "cost": cost, "effects": effects, "validated": True,
    }


# --------------------------------------------------------------------------- #
# §A — the canonical minions fight (the single source of truth for the default)
# --------------------------------------------------------------------------- #
SCENARIO_A: Dict[str, Any] = {
    "name": "§A — Skitterling & Brute (minions)",
    "party": [
        {
            "id": "soren", "name": "Soren", "archetype": "Fighter",
            "hp": 25, "power": 2, "hand_size": 2, "identity": ["G", "W"],
            "library": [
                _cd("guard", "Guard", "instant", {"colors": {"W": 1}}, 1,
                    [{"kind": "prevent", "amount": 2, "target": TARGETED_ALLY,
                      "duration": "this_turn"}]),
                _cd("sunlance", "Sunlance", "sorcery", {"colors": {"W": 1}}, 1,
                    [{"kind": "deal_damage", "amount": 3, "target": TARGETED_ENEMY}]),
                _cd("steady_blade", "Steady Blade", "instant", {"colors": {"G": 1}}, 1,
                    [{"kind": "pump", "power": 1, "toughness": 1, "target": TARGETED_ALLY,
                      "duration": "end_of_turn"}]),
                _cd("mend", "Mend", "instant", {"colors": {"W": 1}}, 1,
                    [{"kind": "heal", "amount": 3, "target": TARGETED_ALLY}]),
                _cd("valors_edge", "Valor's Edge", "instant", {"colors": {"G": 1}}, 2,
                    [{"kind": "pump", "power": 2, "toughness": 2, "target": TARGETED_ALLY,
                      "duration": "end_of_turn"}], rarity="uncommon"),
                _cd("bulwark", "Bulwark", "sorcery", {"colors": {"W": 1}}, 1,
                    [{"kind": "pump", "power": 0, "toughness": 3, "target": SELF,
                      "duration": "end_of_turn"}]),
            ],
        },
        {
            "id": "ys", "name": "Ys", "archetype": "Tactician",
            "hp": 15, "power": 1, "hand_size": 4, "identity": ["U", "B"],
            "library": [
                _cd("unmake", "Unmake", "sorcery", {"generic": 1, "colors": {"B": 1}}, 2,
                    [{"kind": "destroy", "target": TARGETED_ENEMY},
                     {"kind": "lose_life", "amount": {"ref": "destroyed_target.level"},
                      "target": SELF}], rarity="uncommon"),
                _cd("mind_spike", "Mind Spike", "instant", {"colors": {"U": 1}}, 1,
                    [{"kind": "deal_damage", "amount": 2, "target": TARGETED_ENEMY}]),
                _cd("whispers", "Whispers", "sorcery", {"colors": {"U": 1}}, 1,
                    [{"kind": "draw", "amount": 1, "target": SELF}]),
                _cd("sift", "Sift", "sorcery", {"colors": {"U": 1}}, 1,
                    [{"kind": "scry", "amount": 1, "target": SELF}]),
                _cd("nightcreep", "Nightcreep", "sorcery", {"colors": {"B": 1}}, 1,
                    [{"kind": "deal_damage", "amount": 2, "target": TARGETED_ENEMY}]),
                _cd("leech", "Leech", "instant", {"colors": {"B": 1}}, 1,
                    [{"kind": "deal_damage", "amount": 1, "target": TARGETED_ENEMY},
                     {"kind": "heal", "amount": 1, "target": SELF}]),
            ],
        },
    ],
    "enemies": [
        {"id": "skitterling", "name": "Skitterling", "hp": 3, "level": 1,
         "intent": {"name": "Claw", "amount": 2, "action_type": "ability"}},
        {"id": "brute", "name": "Brute", "hp": 8, "level": 3,
         "intent": {"name": "Smash", "amount": 4, "action_type": "ability"}},
    ],
}


# --------------------------------------------------------------------------- #
# §C — the channeling fight (Channeler Mira vs Cinder & Maul)
# --------------------------------------------------------------------------- #
SCENARIO_C: Dict[str, Any] = {
    "name": "§C — Mira channels (Cinder & Maul)",
    "party": [
        {
            "id": "mira", "name": "Mira", "archetype": "Channeler",
            "hp": 15, "power": 1, "hand_size": 2, "parry_reduce": 2,
            "identity": ["U", "U", "B", "B"],
            "library": [
                _cd("still_the_blade", "Still the Blade", "channeled", {"colors": {"U": 1}}, 2,
                    [{"kind": "disable", "intent_type": "attack", "target": TARGETED_ENEMY,
                      "duration": "while_channeled"}], rarity="uncommon"),
                _cd("swarm_hex", "Swarm Hex", "channeled", {"colors": {"B": 1}}, 2,
                    [{"kind": "create_token", "token_id": "wisp", "count": 1, "trigger": "upkeep"},
                     {"kind": "lose_life", "amount": 1, "target": SELF, "trigger": "upkeep"}],
                    rarity="uncommon"),
                _cd("mind_spike", "Mind Spike", "instant", {"colors": {"U": 1}}, 1,
                    [{"kind": "deal_damage", "amount": 2, "target": TARGETED_ENEMY}]),
                _cd("leech", "Leech", "instant", {"colors": {"B": 1}}, 1,
                    [{"kind": "deal_damage", "amount": 1, "target": TARGETED_ENEMY},
                     {"kind": "heal", "amount": 1, "target": SELF}]),
            ],
        },
    ],
    "tokens": {"wisp": {"name": "Wisp", "hp": 1, "power": 1}},
    "enemies": [
        {"id": "cinder", "name": "Cinder", "hp": 6, "level": 2,
         "intent": {"name": "Ember", "amount": 2, "action_type": "ability",
                    "intent_type": "attack", "targeting": "lowest_hp_party"}},
        # Maul goes for the caster directly, ignoring tokens.
        {"id": "maul", "name": "Maul", "hp": 10, "level": 4,
         "intent": {"name": "Crush", "amount": 5, "action_type": "ability",
                    "intent_type": "attack", "targeting": "mira"}},
    ],
}


# --------------------------------------------------------------------------- #
# Build / load
# --------------------------------------------------------------------------- #
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def state_from_dict(spec: Dict[str, Any]) -> GameState:
    """Build the pre-upkeep setup state from a scenario dict.

    The opening hand is the top `hand_size` of the ordered library (the rest is
    the draw pile). Mana starts empty; the turn-1 upkeep refreshes it.
    """
    party: List[CharacterState] = []
    for p in spec["party"]:
        library = [Card.model_validate(c) for c in p["library"]]
        hand_size = int(p["hand_size"])
        hand = [c.model_copy(deep=True) for c in library[:hand_size]]
        draw_pile = [c.model_copy(deep=True) for c in library[hand_size:]]
        party.append(CharacterState(
            id=p.get("id", _slug(p["name"])), name=p["name"],
            archetype=p.get("archetype", ""), max_hp=int(p["hp"]), hp=int(p["hp"]),
            power=int(p["power"]), hand_size=hand_size, hand=hand, library=draw_pile,
            identity=list(p["identity"]), mana_colors=list(p["identity"]), pool=[],
            parry_reduce=int(p.get("parry_reduce", 2)), row=p.get("row", "front"),
        ))

    enemies: List[EnemyState] = []
    for e in spec["enemies"]:
        enemies.append(EnemyState(
            id=e.get("id", _slug(e["name"])), name=e["name"],
            max_hp=int(e["hp"]), hp=int(e["hp"]), level=int(e["level"]),
            row=e.get("row", "front"), intent_template=dict(e["intent"]),
        ))

    return GameState(party=party, enemies=enemies, turn=1, phase="upkeep",
                     token_defs=dict(spec.get("tokens", {})))


def build_state() -> GameState:
    """The §A.3 setup state: encounter start, before Turn 1's upkeep."""
    return state_from_dict(SCENARIO_A)


def build_channeling_state() -> GameState:
    """The §C.3 setup state: the channeling fight, before Turn 1's upkeep."""
    return state_from_dict(SCENARIO_C)


def load_scenario(path) -> GameState:
    """Load a scenario JSON (same shape as `SCENARIO_A`) into a setup state."""
    raw = json.loads(Path(path).read_text())
    return state_from_dict(raw)


def scenario_name(spec: Dict[str, Any] = None) -> str:
    return (spec or SCENARIO_A).get("name", "scenario")


# --- small readers used by the harness / tests ----------------------------- #
def hand_names(char) -> List[str]:
    return [c.name for c in char.hand]


def mana(char) -> List[str]:
    return list(char.pool)
