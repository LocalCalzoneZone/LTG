"""LTG transcription schema — the single source of truth.

Pydantic v2 models for the effect vocabulary, cards, characters and loadouts.
Everything else (frontend, registry, API) round-trips what these models validate.

Design rule: effects DECLARE intent; they never execute it. A model carries
`destroy` + a target — never branching game-state logic. Interpretation lives in
the (future) resolver, not here.

To add a new effect primitive:
  1. Add a model class below (Literal `kind`, its params, sensible defaults).
  2. Add it to the `Effect` union.
  3. Add a renderer in `mappings.RENDERERS` so it produces translated text.
That is the whole change.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Annotated


# --------------------------------------------------------------------------- #
# Enums / scalars
# --------------------------------------------------------------------------- #
class Color(str, Enum):
    W = "W"
    U = "U"
    B = "B"
    R = "R"
    G = "G"


class Rarity(str, Enum):
    common = "common"
    uncommon = "uncommon"
    rare = "rare"
    mythic = "mythic"


class Timing(str, Enum):
    instant = "instant"
    sorcery = "sorcery"
    channeled = "channeled"


class Target(str, Enum):
    self_ = "self"
    an_ally = "an_ally"
    an_enemy = "an_enemy"
    all_enemies = "all_enemies"
    all_allies = "all_allies"
    a_minion = "a_minion"
    the_boss = "the_boss"
    an_ally_token = "an_ally_token"
    an_enemy_intent = "an_enemy_intent"


class Duration(str, Enum):
    end_of_turn = "end_of_turn"
    this_turn = "this_turn"
    encounter = "encounter"


class Ref(BaseModel):
    """A late-bound value the resolver fills in, e.g. {"ref": "destroyed_target.level"}."""

    ref: str


# Value = int | "all" | {"ref": str}
Value = Union[int, Literal["all"], Ref]


# --------------------------------------------------------------------------- #
# Effect primitives (discriminated union on `kind`)
# --------------------------------------------------------------------------- #
class DealDamage(BaseModel):
    kind: Literal["deal_damage"] = "deal_damage"
    amount: int
    target: Target
    nonlethal: bool = False


class Heal(BaseModel):
    kind: Literal["heal"] = "heal"
    amount: int
    target: Target


class LoseLife(BaseModel):
    kind: Literal["lose_life"] = "lose_life"
    amount: Value
    target: Target


class Destroy(BaseModel):
    kind: Literal["destroy"] = "destroy"
    target: Target


class Exile(BaseModel):
    kind: Literal["exile"] = "exile"
    target: Target


class Bounce(BaseModel):
    kind: Literal["bounce"] = "bounce"
    target: Target


class CounterIntent(BaseModel):
    kind: Literal["counter_intent"] = "counter_intent"
    target: Target = Target.an_enemy_intent


class StripIntent(BaseModel):
    kind: Literal["strip_intent"] = "strip_intent"
    target: Target


class Stun(BaseModel):
    kind: Literal["stun"] = "stun"
    target: Target
    intents: int = 1


class Pump(BaseModel):
    kind: Literal["pump"] = "pump"
    power: int
    toughness: int
    target: Target
    duration: Duration = Duration.end_of_turn


class Wound(BaseModel):
    kind: Literal["wound"] = "wound"
    power: int
    toughness: int
    target: Target
    duration: Duration = Duration.end_of_turn


class Counters(BaseModel):
    kind: Literal["counters"] = "counters"
    power: int
    toughness: int
    target: Target
    duration: Duration = Duration.encounter


class Prevent(BaseModel):
    kind: Literal["prevent"] = "prevent"
    amount: Value
    target: Target
    duration: Duration = Duration.this_turn


class Protection(BaseModel):
    kind: Literal["protection"] = "protection"
    target: Target
    scope: str = "next_spell_or_attack"


class Draw(BaseModel):
    kind: Literal["draw"] = "draw"
    amount: int
    target: Target = Target.self_


class Scry(BaseModel):
    kind: Literal["scry"] = "scry"
    amount: int
    target: Target = Target.self_


class CreateToken(BaseModel):
    kind: Literal["create_token"] = "create_token"
    token_id: str
    count: int = 1


class Taunt(BaseModel):
    kind: Literal["taunt"] = "taunt"
    target: Target
    duration: Duration = Duration.this_turn


class Disable(BaseModel):
    kind: Literal["disable"] = "disable"
    intent_type: str
    target: Target


class Revive(BaseModel):
    kind: Literal["revive"] = "revive"
    target: Target
    to_fraction: float = 0.5


Effect = Annotated[
    Union[
        DealDamage,
        Heal,
        LoseLife,
        Destroy,
        Exile,
        Bounce,
        CounterIntent,
        StripIntent,
        Stun,
        Pump,
        Wound,
        Counters,
        Prevent,
        Protection,
        Draw,
        Scry,
        CreateToken,
        Taunt,
        Disable,
        Revive,
    ],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Card / Character / Loadout
# --------------------------------------------------------------------------- #
class Cost(BaseModel):
    """Parsed mana cost. `colors` holds only the pips that are present."""

    generic: int = 0
    colors: Dict[Color, int] = Field(default_factory=dict)

    @field_validator("colors")
    @classmethod
    def _non_negative(cls, v: Dict[Color, int]) -> Dict[Color, int]:
        for color, count in v.items():
            if count < 0:
                raise ValueError(f"colour pip {color} must be >= 0")
        return v


class Card(BaseModel):
    id: str
    name: str
    source_name: str
    rarity: Rarity
    level: int
    type: str
    cost: Cost = Field(default_factory=Cost)
    timing: Timing
    reactive: bool = False
    original_text: str = ""
    translated_text: str = ""
    effects: List[Effect] = Field(default_factory=list)
    needs_translation: bool = False


class Character(BaseModel):
    name: str
    description: str = ""
    colors: List[Color]
    starting_mana: List[Color]

    @field_validator("colors")
    @classmethod
    def _colors_count(cls, v: List[Color]) -> List[Color]:
        if not (1 <= len(v) <= 3):
            raise ValueError("colors must be 1-3 of W U B R G")
        if len(set(v)) != len(v):
            raise ValueError("colors must be unique")
        return v

    @field_validator("starting_mana")
    @classmethod
    def _mana_count(cls, v: List[Color]) -> List[Color]:
        if len(v) != 2:
            raise ValueError("starting_mana must be exactly 2 colours")
        return v


class Loadout(BaseModel):
    ltg_version: str = "0.1"
    character: Character
    cards: List[Card] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Deck status (live, non-blocking advisory — never raises)
# --------------------------------------------------------------------------- #
DECK_LIMIT = 40
RARITY_LIMITS = {"mythic": 2, "rare": 6, "uncommon": 12, "common": 20}


def deck_status(loadout: Loadout) -> dict:
    """Compute the advisory deck-status readout. Warnings, never errors."""
    cards = loadout.cards
    rarity_counts = {r: 0 for r in RARITY_LIMITS}
    for c in cards:
        rarity_counts[c.rarity.value] = rarity_counts.get(c.rarity.value, 0) + 1

    seen: Dict[str, int] = {}
    for c in cards:
        seen[c.source_name] = seen.get(c.source_name, 0) + 1
    duplicates = sorted(name for name, n in seen.items() if n > 1)

    identity = set(loadout.character.colors)
    off_color = sorted(
        {c.name for c in cards if set(c.cost.colors.keys()) - identity}
    )

    untranslated = sum(1 for c in cards if c.needs_translation)

    starting_mana_off = [
        m.value for m in loadout.character.starting_mana if m not in identity
    ]

    return {
        "size": {"count": len(cards), "limit": DECK_LIMIT},
        "rarity": {
            r: {"count": rarity_counts[r], "limit": RARITY_LIMITS[r]}
            for r in RARITY_LIMITS
        },
        "duplicates": duplicates,
        "off_color": off_color,
        "untranslated": untranslated,
        "starting_mana_outside_identity": starting_mana_off,
    }
