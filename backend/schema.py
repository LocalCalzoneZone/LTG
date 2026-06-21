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
from typing import Dict, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
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


class TargetMode(str, Enum):
    self_ = "self"
    chosen = "chosen"
    all = "all"


class Side(str, Enum):
    ally = "ally"
    enemy = "enemy"
    any = "any"


class TargetDescriptor(BaseModel):
    """How an effect picks what it affects — a mechanical property, not a label.

    `targeted` records whether the effect uses MTG's targeting mechanic (so the
    future engine can let hexproof/shroud interact). It is only meaningful on a
    `chosen` target. "ally" includes you unless `exclude_self`.
    """

    mode: TargetMode
    side: Optional[Side] = None  # omitted for mode:self (always you)
    exclude_self: bool = False
    targeted: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> "TargetDescriptor":
        if self.mode == TargetMode.self_:
            if self.side is not None:
                raise ValueError("mode 'self' must not specify a side")
            if self.targeted:
                raise ValueError("mode 'self' cannot be targeted")
        else:
            if self.side is None:
                raise ValueError(f"mode '{self.mode.value}' requires a side")
        if self.targeted and self.mode != TargetMode.chosen:
            raise ValueError("targeted is only valid when mode is 'chosen'")
        return self


# Convenience constructors used by the registry.
def t_self() -> TargetDescriptor:
    return TargetDescriptor(mode=TargetMode.self_)


def t_chosen(side: str, targeted: bool = False, exclude_self: bool = False) -> TargetDescriptor:
    return TargetDescriptor(
        mode=TargetMode.chosen, side=Side(side), targeted=targeted, exclude_self=exclude_self
    )


def t_all(side: str, exclude_self: bool = False) -> TargetDescriptor:
    return TargetDescriptor(mode=TargetMode.all, side=Side(side), exclude_self=exclude_self)


class Duration(str, Enum):
    end_of_turn = "end_of_turn"
    this_turn = "this_turn"
    encounter = "encounter"
    # Applies continuously while the enchantment is channeled (channeled cards only).
    while_channeled = "while_channeled"


# Effects on channeled cards may fire on a recurring trigger instead of being
# continuous. Only "upkeep" exists for now (start of each of the controller's turns).
TriggerType = Literal["upkeep"]


class Ref(BaseModel):
    """A late-bound value the resolver fills in, e.g. {"ref": "destroyed_target.level"}."""

    ref: str


# Value = int | "all" | {"ref": str}
Value = Union[int, Literal["all"], Ref]


# An effect's target is either a TargetDescriptor OR a "$slot" reference resolved
# at the card level (see Card.targets). Slot refs let several effects share one
# chosen target, so the engine resolves it once and applies it to every effect.
SLOT_REF_PATTERN = r"^\$[A-Za-z_][A-Za-z0-9_]*$"
SlotRef = Annotated[str, StringConstraints(pattern=SLOT_REF_PATTERN)]
TargetOrSlot = Union[TargetDescriptor, SlotRef]


def slot_name(target) -> Optional[str]:
    """Return the slot name if `target` is a "$slot" reference, else None."""
    return target[1:] if isinstance(target, str) and target.startswith("$") else None


# --------------------------------------------------------------------------- #
# Effect primitives (discriminated union on `kind`)
# --------------------------------------------------------------------------- #
class EffectBase(BaseModel):
    """Shared across every primitive: an optional recurring trigger.

    `trigger="upkeep"` makes a channeled effect fire once at the start of each of
    the controller's turns (a discrete event, no `while_channeled` duration).
    """

    trigger: Optional[TriggerType] = None


class DealDamage(EffectBase):
    kind: Literal["deal_damage"] = "deal_damage"
    amount: int
    target: TargetOrSlot
    nonlethal: bool = False


class Heal(EffectBase):
    kind: Literal["heal"] = "heal"
    amount: int
    target: TargetOrSlot


class LoseLife(EffectBase):
    kind: Literal["lose_life"] = "lose_life"
    amount: Value
    target: TargetOrSlot


class Destroy(EffectBase):
    kind: Literal["destroy"] = "destroy"
    target: TargetOrSlot


class Exile(EffectBase):
    kind: Literal["exile"] = "exile"
    target: TargetOrSlot


class Bounce(EffectBase):
    kind: Literal["bounce"] = "bounce"
    target: TargetOrSlot


class CounterIntent(EffectBase):
    kind: Literal["counter_intent"] = "counter_intent"
    target: TargetOrSlot = Field(default_factory=lambda: t_chosen("enemy", targeted=True))


class StripIntent(EffectBase):
    kind: Literal["strip_intent"] = "strip_intent"
    target: TargetOrSlot


class Stun(EffectBase):
    kind: Literal["stun"] = "stun"
    target: TargetOrSlot
    intents: int = 1


class Pump(EffectBase):
    kind: Literal["pump"] = "pump"
    power: int
    toughness: int
    target: TargetOrSlot
    duration: Duration = Duration.end_of_turn


class Wound(EffectBase):
    kind: Literal["wound"] = "wound"
    power: int
    toughness: int
    target: TargetOrSlot
    duration: Duration = Duration.end_of_turn


class Counters(EffectBase):
    kind: Literal["counters"] = "counters"
    power: int
    toughness: int
    target: TargetOrSlot
    duration: Duration = Duration.encounter


class Prevent(EffectBase):
    kind: Literal["prevent"] = "prevent"
    amount: Value
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Protection(EffectBase):
    kind: Literal["protection"] = "protection"
    target: TargetOrSlot
    scope: str = "next_spell_or_attack"


class Draw(EffectBase):
    kind: Literal["draw"] = "draw"
    amount: int
    target: TargetOrSlot = Field(default_factory=t_self)


class Scry(EffectBase):
    kind: Literal["scry"] = "scry"
    amount: int
    target: TargetOrSlot = Field(default_factory=t_self)


class CreateToken(EffectBase):
    kind: Literal["create_token"] = "create_token"
    token_id: str
    count: int = 1


class Taunt(EffectBase):
    kind: Literal["taunt"] = "taunt"
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Disable(EffectBase):
    kind: Literal["disable"] = "disable"
    intent_type: str
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Revive(EffectBase):
    kind: Literal["revive"] = "revive"
    target: TargetOrSlot
    to_fraction: float = 0.5


EFFECT_CLASSES = [
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
]

Effect = Annotated[
    Union[tuple(EFFECT_CLASSES)],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Editor metadata — describes each primitive's params so the frontend editor
# can build typed inputs. Derived from the models, so adding a primitive above
# automatically surfaces in the guided editor (no JS change needed).
# --------------------------------------------------------------------------- #
import typing as _t  # noqa: E402


def _control_for(annotation) -> dict:
    """Classify a field annotation into a UI control descriptor."""
    if annotation is bool:
        return {"control": "bool"}
    if annotation is int:
        return {"control": "int"}
    if annotation is float:
        return {"control": "float"}
    origin = _t.get_origin(annotation)
    args = _t.get_args(annotation)
    if origin is Union:
        if TargetDescriptor in args:  # TargetOrSlot
            return {"control": "target"}
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args and len(non_none) == 1:  # Optional[...] → optional enum
            inner = non_none[0]
            if _t.get_origin(inner) is Literal:
                return {"control": "enum", "options": list(_t.get_args(inner)), "optional": True}
            if isinstance(inner, type) and issubclass(inner, Enum):
                return {"control": "enum", "options": [e.value for e in inner], "optional": True}
        return {"control": "value"}  # Value = int | "all" | {ref}
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"control": "enum", "options": [e.value for e in annotation]}
    return {"control": "str"}


def effect_specs() -> dict:
    """Per-kind param descriptors for the guided editor."""
    from pydantic_core import PydanticUndefined

    specs = {}
    for cls in EFFECT_CLASSES:
        kind = cls.model_fields["kind"].default
        params = []
        for fname, finfo in cls.model_fields.items():
            if fname == "kind":
                continue
            spec = {"name": fname, **_control_for(finfo.annotation)}
            default = finfo.default
            if default is PydanticUndefined and finfo.default_factory is not None:
                default = finfo.default_factory()
            if default is not PydanticUndefined:
                if isinstance(default, BaseModel):
                    spec["default"] = default.model_dump(mode="json")
                elif isinstance(default, Enum):
                    spec["default"] = default.value
                else:
                    spec["default"] = default
                spec["required"] = False
            else:
                spec["required"] = True
            params.append(spec)
        # Keep `trigger` (a base-class field) last so it reads after the kind's
        # own params in the editor.
        params.sort(key=lambda p: p["name"] == "trigger")
        specs[kind] = {"params": params}
    return specs


MODE_VALUES = [m.value for m in TargetMode]
SIDE_VALUES = [s.value for s in Side]


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
    # Shared target slots: {slot_name: chosen TargetDescriptor}. Most cards
    # declare none and use direct descriptors; slots are only added when several
    # effects must hit the SAME chosen target (see SlotRef).
    targets: Dict[str, TargetDescriptor] = Field(default_factory=dict)
    needs_translation: bool = False
    # True when the translated_text was authored by hand (do not auto-render).
    text_override: bool = False
    # True when a human has ratified this card's effects. Any edit resets it.
    validated: bool = False

    @model_validator(mode="after")
    def _check_targets(self) -> "Card":
        # Shared slots must be `chosen` (only chosen targets have a choice to share).
        for name, desc in self.targets.items():
            if desc.mode != TargetMode.chosen:
                raise ValueError(f"shared slot '{name}' must be mode 'chosen'")
        # Slot refs must point at declared slots; draw/scry can't hit enemies.
        for effect in self.effects:
            name = slot_name(getattr(effect, "target", None))
            if name is not None and name not in self.targets:
                raise ValueError(
                    f"effect references undeclared slot '${name}'; declare it in 'targets'"
                )
            if effect.kind in ("draw", "scry"):
                desc = self.resolved_target(effect)
                if desc is not None and desc.side == Side.enemy:
                    raise ValueError(
                        f"{effect.kind} cannot target an enemy (enemies have no library)"
                    )
            # Channeled-only persistence: while_channeled / upkeep are illegal on
            # one-shot cards, and an effect can't be both continuous and recurring.
            is_channeled = self.timing == Timing.channeled
            if getattr(effect, "duration", None) == Duration.while_channeled and not is_channeled:
                raise ValueError("duration 'while_channeled' is only valid on channeled cards")
            if effect.trigger == "upkeep":
                if not is_channeled:
                    raise ValueError("trigger 'upkeep' is only valid on channeled cards")
                if getattr(effect, "duration", None) == Duration.while_channeled:
                    raise ValueError("an upkeep effect must not also be 'while_channeled'")
        return self

    def resolved_target(self, effect) -> Optional[TargetDescriptor]:
        """The effect's effective descriptor, resolving a slot ref if present."""
        target = getattr(effect, "target", None)
        name = slot_name(target)
        if name is not None:
            return self.targets.get(name)
        return target


class Character(BaseModel):
    name: str
    description: str = ""
    # Optional portrait, stored inline as a data URL (or any image URL) so a
    # saved loadout stays self-contained. Empty when unset.
    portrait: str = ""
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

    untranslated = sum(
        1 for c in cards if c.needs_translation and not c.validated
    )

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
