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

from ltg_core.schema import Card, Loadout

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
            "hp": 25, "power": 3, "attack_mode": "melee", "level": 1,
            "hand_size": 2, "identity": ["G", "W"],
            "library": [
                _cd("guard", "Guard", "instant", {"colors": {"W": 1}}, 1,
                    [{"kind": "prevent", "parameter": "combat_damage", "target": TARGETED_ALLY,
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
            "hp": 15, "power": 1, "attack_mode": "ranged", "level": 1,
            "hand_size": 4, "identity": ["U", "B"],
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
         "intent": {"name": "Claw", "amount": 2, "action_type": "ability", "mode": "melee"}},
        {"id": "brute", "name": "Brute", "hp": 8, "level": 3,
         "intent": {"name": "Smash", "amount": 4, "action_type": "ability", "mode": "melee"}},
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
            "hp": 15, "power": 1, "attack_mode": "ranged", "level": 1,
            "hand_size": 2, "parry_reduce": 2, "identity": ["U", "U", "B", "B"],
            "library": [
                # With `disable` retired (R-11), Still the Blade now blunts the
                # enemy's attack: a continuous −2/−0 wound aura while channeled.
                _cd("still_the_blade", "Still the Blade", "channeled", {"colors": {"U": 1}}, 2,
                    [{"kind": "wound", "power": 2, "toughness": 0, "target": TARGETED_ENEMY,
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
    "tokens": {"wisp": {"name": "Wisp", "hp": 1, "power": 1, "attack_mode": "melee"}},
    "enemies": [
        {"id": "cinder", "name": "Cinder", "hp": 6, "level": 2,
         "intent": {"name": "Ember", "amount": 2, "action_type": "ability",
                    "intent_type": "attack", "targeting": "lowest_hp_party", "mode": "melee"}},
        # Maul goes for the caster directly, ignoring tokens.
        {"id": "maul", "name": "Maul", "hp": 10, "level": 4,
         "intent": {"name": "Crush", "amount": 5, "action_type": "ability",
                    "intent_type": "attack", "targeting": "mira", "mode": "melee"}},
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
            attack_mode=p.get("attack_mode", "melee"), level=int(p.get("level", 1)),
        ))

    enemies: List[EnemyState] = []
    for e in spec["enemies"]:
        enemies.append(EnemyState(
            id=e.get("id", _slug(e["name"])), name=e["name"],
            max_hp=int(e["hp"]), hp=int(e["hp"]), level=int(e["level"]),
            row=e.get("row", "front"), intent_template=dict(e["intent"]),
            attack_mode=e.get("intent", {}).get("mode", "melee"),
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


# --------------------------------------------------------------------------- #
# Cockpit assembly: Deckbuilder loadouts (party) + an enemies-only scenario.
#
# The cockpit loads characters and the encounter from SEPARATE files — the exact
# Deckbuilder loadout JSON per party slot, and an enemies-only scenario JSON. The
# helpers below adapt those two inputs into the one scenario dict `state_from_dict`
# already understands. This is *loading* (resolving inputs the engine is handed),
# not rules: every resolved number flows into the engine, which alone decides
# legality, costs, damage and turn order.
# --------------------------------------------------------------------------- #

def party_entry_from_loadout(raw_loadout: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt one Deckbuilder loadout export into an engine party-entry dict.

    The loadout is validated through `core` (the single gate). Resolved starting
    numbers come from the archetype tables (HP / hand size / mana capacity), and
    Power + attack mode from the character's chosen attack profile (Design Update
    R-3). The card-list order becomes the deterministic library order; the opening
    hand is its top `hand_size`. `identity` is the starting-mana capacity (one entry
    per slot), exactly as the §A/§C scenario party entries express it.
    """
    lo = Loadout.model_validate(raw_loadout)
    char = lo.character
    stats = char.stats
    return {
        "id": _slug(char.name),
        "name": char.name,
        "archetype": char.archetype.value,
        "hp": stats["starting_hp"],
        "power": char.power,                 # from the (archetype, attack mode) profile
        "attack_mode": stats["attack_mode"],
        "row": char.row.value,
        "level": char.level,
        "hand_size": stats["starting_hand"],
        "identity": [c.value for c in char.starting_mana],
        "parry_reduce": 2,
        "library": [c.model_dump(mode="json") for c in lo.cards],
    }


def compose_spec(loadouts: List[Dict[str, Any]], scenario: Dict[str, Any],
                 overrides: Dict[str, Any] = None) -> Dict[str, Any]:
    """Compose the combined scenario dict from N party loadouts + an enemies-only
    scenario, applying any quick-setup overrides. Party-slot ids are de-duplicated
    so two copies of the same character can share the board."""
    party = [party_entry_from_loadout(lo) for lo in loadouts]
    _dedupe_ids(party)
    spec = {
        "name": scenario.get("name", "encounter"),
        "party": party,
        "enemies": [dict(e) for e in scenario.get("enemies", [])],
        "tokens": dict(scenario.get("tokens", {})),
    }
    if overrides:
        _apply_overrides(spec, overrides)
    return spec


def state_from_loadouts(loadouts: List[Dict[str, Any]], scenario: Dict[str, Any],
                        overrides: Dict[str, Any] = None) -> GameState:
    """Build a setup `GameState` from party loadouts + an enemies-only scenario."""
    return state_from_dict(compose_spec(loadouts, scenario, overrides))


def _dedupe_ids(party: List[Dict[str, Any]]) -> None:
    seen: Dict[str, int] = {}
    for entry in party:
        base = entry["id"]
        if base in seen:
            seen[base] += 1
            entry["id"] = f"{base}_{seen[base]}"
        else:
            seen[base] = 1


def _apply_overrides(spec: Dict[str, Any], overrides: Dict[str, Any]) -> None:
    """Quick-setup tweaks, applied to the composed spec before it becomes state.

    Shape: {"party": {char_id: {hp, power, mana:[...], library:[card_id,...]}},
            "enemies": {enemy_id: {hp, intent_amount}}}.
    """
    party_ov = overrides.get("party", {})
    for entry in spec["party"]:
        ov = party_ov.get(entry["id"])
        if not ov:
            continue
        if "hp" in ov and ov["hp"] is not None:
            entry["hp"] = int(ov["hp"])
        if "power" in ov and ov["power"] is not None:
            entry["power"] = int(ov["power"])
        if ov.get("mana"):
            entry["identity"] = list(ov["mana"])
        if ov.get("library"):
            entry["library"] = _reorder_library(entry["library"], ov["library"])

    enemy_ov = overrides.get("enemies", {})
    for enemy in spec["enemies"]:
        ov = enemy_ov.get(enemy.get("id", _slug(enemy["name"])))
        if not ov:
            continue
        if "hp" in ov and ov["hp"] is not None:
            enemy["hp"] = int(ov["hp"])
        if "intent_amount" in ov and ov["intent_amount"] is not None:
            enemy.setdefault("intent", {})["amount"] = int(ov["intent_amount"])


def _reorder_library(library: List[Dict[str, Any]], order: List[str]) -> List[Dict[str, Any]]:
    """Reorder a library by an explicit list of card ids (determinism control).
    Listed ids come first in the given order; any unlisted cards keep their order."""
    by_id = {c["id"]: c for c in library}
    out = [by_id[cid] for cid in order if cid in by_id]
    listed = set(order)
    out.extend(c for c in library if c["id"] not in listed)
    return out


# --- small readers used by the harness / tests ----------------------------- #
def hand_names(char) -> List[str]:
    return [c.name for c in char.hand]


def mana(char) -> List[str]:
    return list(char.pool)
