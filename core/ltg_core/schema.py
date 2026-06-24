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
    ConfigDict,
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


class AttackMode(str, Enum):
    """How a combatant's basic attack reaches (Design Update R-1/R-3)."""

    melee = "melee"
    ranged = "ranged"


class Row(str, Enum):
    """Battlefield row. Reach/melee reachability is keyed to these (R-1)."""

    front = "front"
    mid = "mid"
    rear = "rear"


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


# --------------------------------------------------------------------------- #
# Action classification (the stack vocabulary)
# --------------------------------------------------------------------------- #
# Every action has two orthogonal axes: type (spell|ability) and speed
# (active|reactive). Speed is DERIVED, never stored: a spell's speed comes from
# its card `timing`; an ability's from its `ability_kind`.
class ActionType(str, Enum):
    spell = "spell"
    ability = "ability"


class AbilityKind(str, Enum):
    attack = "attack"
    activated = "activated"
    triggered = "triggered"
    reaction = "reaction"


class Speed(str, Enum):
    active = "active"
    reactive = "reactive"
    sustained = "sustained"  # channeled enchantments


_ABILITY_SPEED = {
    AbilityKind.attack: Speed.active,
    AbilityKind.activated: Speed.active,
    AbilityKind.triggered: Speed.reactive,
    AbilityKind.reaction: Speed.reactive,
}
_TIMING_SPEED = {"instant": Speed.reactive, "sorcery": Speed.active, "channeled": Speed.sustained}


def spell_speed(timing: str) -> Speed:
    """instant→reactive, sorcery→active, channeled→sustained."""
    return _TIMING_SPEED[str(timing)]


def ability_speed(ability_kind: AbilityKind) -> Speed:
    """attack/activated→active, triggered/reaction→reactive."""
    return _ABILITY_SPEED[AbilityKind(ability_kind)]


# A counter's filter is a node in the action-type lattice (matching a node also
# matches its descendants — resolution is the engine's job, deferred):
#   action ⊃ {spell, ability ⊃ {attack, activated, triggered}}
FilterNode = Literal["action", "spell", "ability", "attack", "activated", "triggered"]


class ActionTarget(BaseModel):
    """A stack action, targeted by a counter. Inherently targeted; enemy-side."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    target_class: Literal["action"] = Field("action", alias="class")
    side: Side = Side.enemy


class Duration(str, Enum):
    end_of_turn = "end_of_turn"
    this_turn = "this_turn"
    encounter = "encounter"
    # Applies continuously while the enchantment is channeled (channeled cards only).
    while_channeled = "while_channeled"


# Effects on channeled cards may fire on a recurring trigger instead of being
# continuous: "upkeep" (start of each of your turns) or "capacity_increase"
# (landfall — whenever your mana capacity goes up).
TriggerType = Literal["upkeep", "capacity_increase"]


class Ref(BaseModel):
    """A late-bound value the resolver fills in, e.g. {"ref": "destroyed_target.level"}."""

    ref: str


# Value = int | "all" | {"ref": str}
Value = Union[int, Literal["all"], Ref]


# --------------------------------------------------------------------------- #
# Keyword registry — the source of truth for grantable evergreen statics. A
# grant effect references a keyword by name; the engine reads it and applies its
# rule. Retired keywords are kept here but can't be granted.
# --------------------------------------------------------------------------- #
KEYWORDS = {
    "flying": {"display": "Flying", "gloss": "on defence, struck only by ranged, other flyers, or reach (R-1)", "grantable": True, "params": []},
    "reach": {"display": "Reach", "gloss": "its melee may strike flyers, and pins an enemy melee-flyer to rows not behind it (R-1)", "grantable": True, "params": []},
    "first_strike": {"display": "First Strike", "gloss": "act/cast on your turn, then hold the basic attack as a reaction that may kill the attacker first (R-12)", "grantable": True, "params": []},
    "double_strike": {"display": "Double Strike", "gloss": "the basic attack strikes twice", "grantable": True, "params": []},
    "vigilance": {"display": "Vigilance", "gloss": "may attack and still act/defend", "grantable": True, "params": []},
    "trample": {"display": "Trample", "gloss": "excess damage cleaves past the target", "grantable": True, "params": []},
    "deathtouch": {"display": "Deathtouch", "gloss": "mini-execute: its damage can destroy a minion", "grantable": True, "params": []},
    "lifelink": {"display": "Lifelink", "gloss": "heal equal to the damage it deals", "grantable": True, "params": []},
    "hexproof": {"display": "Hexproof", "gloss": "can't be targeted by enemy effects (attacks still hit)", "grantable": True, "params": []},
    "indestructible": {"display": "Indestructible", "gloss": "can't be reduced below 1 HP by damage; still dies to exile or a −X/−X to effective HP ≤ 0", "grantable": True, "params": []},
    "protection": {"display": "Protection", "gloss": "prevents the next spell or attack", "grantable": True, "params": ["from"]},
    # Retired — not grantable.
    "menace": {"display": "Menace", "gloss": "", "grantable": False, "params": []},
    "ward": {"display": "Ward", "gloss": "", "grantable": False, "params": []},
    "convoke": {"display": "Convoke", "gloss": "", "grantable": False, "params": []},
}
GRANTABLE_KEYWORDS = [k for k, v in KEYWORDS.items() if v["grantable"]]


def _check_grant_keywords(keywords: List[str], params: Optional[dict], for_grant: bool) -> None:
    """Validate keyword names + params for grant/remove effects."""
    for kw in keywords:
        if kw == "all" and not for_grant:
            continue  # "remove all abilities"
        info = KEYWORDS.get(kw)
        if info is None:
            raise ValueError(f"unknown keyword '{kw}'")
        if for_grant and not info["grantable"]:
            raise ValueError(f"keyword '{kw}' is retired and not grantable")
    if params:
        allowed = set()
        for kw in keywords:
            allowed |= set(KEYWORDS.get(kw, {}).get("params", []))
        for p in params:
            if p not in allowed:
                raise ValueError(f"param '{p}' is not supported by these keywords")


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
    amount: Value  # int, "all", or a {ref} like mana_capacity ("for each …")
    target: TargetOrSlot
    nonlethal: bool = False


class Heal(EffectBase):
    kind: Literal["heal"] = "heal"
    amount: Value
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


class Counter(EffectBase):
    """Cancel an enemy action on the stack, filtered by type."""

    kind: Literal["counter"] = "counter"
    filter: FilterNode = "action"
    target: ActionTarget = Field(default_factory=lambda: ActionTarget(side=Side.enemy))


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
    """Nullify a named thing for a duration (R-11): `prevent [parameter]` — e.g.
    `prevent combat_damage` makes attack actions against the target deal no damage.
    The parameter names what is nullified; scope is defined by that parameter."""

    kind: Literal["prevent"] = "prevent"
    parameter: str = "combat_damage"
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Protection(EffectBase):
    kind: Literal["protection"] = "protection"
    target: TargetOrSlot
    scope: str = "next_spell_or_attack"


class Draw(EffectBase):
    kind: Literal["draw"] = "draw"
    amount: Value
    target: TargetOrSlot = Field(default_factory=t_self)


class Scry(EffectBase):
    kind: Literal["scry"] = "scry"
    amount: Value
    target: TargetOrSlot = Field(default_factory=t_self)


# Card-logistics zones. `library` as a *source* means "search anywhere in it"; `drawn`
# means "among the cards drawn earlier this resolution". `library_shuffle` is a
# destination meaning "shuffled into the library".
MoveSource = Literal["drawn", "library_top", "library_bottom", "library", "hand", "graveyard", "exile"]
MoveDest = Literal["hand", "library_top", "library_bottom", "library_shuffle", "graveyard", "exile"]


class MoveCard(EffectBase):
    """Move card(s) between zones — the general card-logistics primitive (draw is the
    common special case). Optionally filtered by type/level; can shuffle after (e.g. a
    library search). You move your own cards, so the target is always yourself."""

    kind: Literal["move_card"] = "move_card"
    count: int = 1
    source: MoveSource = "library"
    destination: MoveDest = "hand"
    filter_type: Optional[Literal["instant", "sorcery", "channeled"]] = None
    # Level filtering is off unless the comparator is set to something other than
    # 'any' (which means "any level — no filter"); filter_level is read only then.
    filter_level_compare: Literal["any", "exactly", "or_more", "or_less"] = "any"
    filter_level: int = 1
    shuffle_after: bool = False
    target: TargetOrSlot = Field(default_factory=t_self)


class CreateToken(EffectBase):
    kind: Literal["create_token"] = "create_token"
    token_id: str
    count: int = 1
    # The token's stats. None means "inherit from the scenario's token def" (legacy
    # scenarios that declare a top-level `tokens` map); the deckbuilder authors them
    # explicitly so a card is self-contained.
    power: Optional[int] = None
    hp: Optional[int] = None
    keywords: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "CreateToken":
        if self.keywords:
            _check_grant_keywords(self.keywords, None, for_grant=True)
        return self


class Taunt(EffectBase):
    kind: Literal["taunt"] = "taunt"
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Revive(EffectBase):
    kind: Literal["revive"] = "revive"
    target: TargetOrSlot
    to_fraction: float = 0.5


class GrantKeyword(EffectBase):
    """Attach one or more registry keywords to a creature for a duration."""

    kind: Literal["grant_keyword"] = "grant_keyword"
    keywords: List[str] = Field(min_length=1)
    params: Optional[Dict[str, str]] = None
    target: TargetOrSlot
    duration: Duration = Duration.end_of_turn

    @model_validator(mode="after")
    def _check(self) -> "GrantKeyword":
        _check_grant_keywords(self.keywords, self.params, for_grant=True)
        return self


class RemoveKeyword(EffectBase):
    """Remove named keyword(s) from a creature — or `["all"]` for all abilities."""

    kind: Literal["remove_keyword"] = "remove_keyword"
    keywords: List[str] = Field(min_length=1)
    params: Optional[Dict[str, str]] = None
    target: TargetOrSlot
    duration: Duration = Duration.end_of_turn

    @model_validator(mode="after")
    def _check(self) -> "RemoveKeyword":
        _check_grant_keywords(self.keywords, self.params, for_grant=False)
        return self


# LTG has no land cards; lands survive only as references inside ramp/ritual
# spells, translated into the capacity model (the land names are dropped).
RampColor = Literal["W", "U", "B", "R", "G", "choice"]
Availability = Literal["immediate", "tapped", "deferred"]


class Ramp(EffectBase):
    """Raise mana *capacity* (the lands-equivalent), above the natural +1/turn.

    availability: immediate (capacity + pool now) | tapped (capacity now, pool
    next refresh) | deferred (capacity added at the start of your next turn).
    """

    kind: Literal["ramp"] = "ramp"
    amount: int = 1
    color: RampColor = "choice"
    availability: Availability = "tapped"


class AddMana(EffectBase):
    """A ritual: a one-time burst into your CURRENT pool this turn (no capacity)."""

    kind: Literal["add_mana"] = "add_mana"
    amount: int = 1
    color: RampColor = "B"


# Leaf effects (everything except the container effects modal/conditional). These
# are what a mode or a conditional branch may contain — so containers never nest
# inside one another (no modal-in-modal), which keeps the union non-recursive.
LEAF_EFFECT_CLASSES = [
    DealDamage,
    Heal,
    LoseLife,
    Destroy,
    Exile,
    Bounce,
    Counter,
    StripIntent,
    Stun,
    Pump,
    Wound,
    Counters,
    Prevent,
    Protection,
    Draw,
    Scry,
    MoveCard,
    CreateToken,
    Taunt,
    Revive,
    GrantKeyword,
    RemoveKeyword,
    Ramp,
    AddMana,
]

LeafEffect = Annotated[Union[tuple(LEAF_EFFECT_CLASSES)], Field(discriminator="kind")]


# --------------------------------------------------------------------------- #
# Container effects: modal ("Choose one") and conditional ("If …, then …").
# --------------------------------------------------------------------------- #
class Mode(BaseModel):
    """One option of a modal card; the player picks exactly one mode at cast."""

    label: str = ""
    effects: List[LeafEffect] = Field(min_length=1)


class Modal(EffectBase):
    """Choose one — the card may be cast for any one of its modes."""

    kind: Literal["modal"] = "modal"
    modes: List[Mode] = Field(min_length=2)


class CastModeCondition(BaseModel):
    """True when the card was cast at this speed (action = proactive, reaction = response)."""

    kind: Literal["cast_mode"] = "cast_mode"
    mode: Literal["action", "reaction"]


class TargetPropertyCondition(BaseModel):
    """True when the (main) target has a property — a keyword, a side, or a level
    (compared with exactly / or_more / or_less)."""

    kind: Literal["target_property"] = "target_property"
    property: Literal["has_keyword", "side", "level"]
    keyword: Optional[str] = None
    side: Optional[Side] = None
    level: Optional[int] = None
    compare: Literal["exactly", "or_more", "or_less"] = "exactly"

    @model_validator(mode="after")
    def _coherent(self) -> "TargetPropertyCondition":
        if self.property == "has_keyword":
            if self.keyword is None:
                raise ValueError("target_property 'has_keyword' requires a keyword")
            if self.keyword not in KEYWORDS:
                raise ValueError(f"unknown keyword '{self.keyword}'")
        if self.property == "side" and self.side is None:
            raise ValueError("target_property 'side' requires a side")
        if self.property == "level" and self.level is None:
            raise ValueError("target_property 'level' requires a level")
        return self


Condition = Annotated[
    Union[CastModeCondition, TargetPropertyCondition], Field(discriminator="kind")
]


class Conditional(EffectBase):
    """Apply extra effect(s) only if a condition holds (target property or cast mode)."""

    kind: Literal["conditional"] = "conditional"
    condition: Condition
    effects: List[LeafEffect] = Field(min_length=1)


EFFECT_CLASSES = LEAF_EFFECT_CLASSES + [Modal, Conditional]

Effect = Annotated[
    Union[tuple(EFFECT_CLASSES)],
    Field(discriminator="kind"),
]


def iter_effects(effects):
    """Yield every effect, descending into modal modes and conditional branches."""
    for e in effects:
        yield e
        if getattr(e, "kind", None) == "modal":
            for m in e.modes:
                yield from iter_effects(m.effects)
        elif getattr(e, "kind", None) == "conditional":
            yield from iter_effects(e.effects)


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
    if annotation is ActionTarget:  # counter's fixed enemy-action target
        return {"control": "action_target"}
    origin = _t.get_origin(annotation)
    args = _t.get_args(annotation)
    if origin is Literal:  # e.g. FilterNode
        return {"control": "enum", "options": list(args)}
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
            if inner is int:
                return {"control": "int", "optional": True}
            if inner is float:
                return {"control": "float", "optional": True}
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
            if fname == "params":
                continue  # niche (e.g. protection.from) — edit via raw JSON
            if fname == "keywords":
                opts = list(GRANTABLE_KEYWORDS)
                if kind == "remove_keyword":
                    opts.append("all")
                labels = {k: KEYWORDS.get(k, {}).get("display", k) for k in opts}
                labels["all"] = "All abilities"
                # grant/remove require at least one keyword; create_token's are optional.
                params.append({"name": "keywords", "control": "keyword_list",
                               "options": opts, "labels": labels,
                               "required": finfo.is_required()})
                continue
            if fname in ("modes", "condition", "effects"):
                # Container fields (modal modes / conditional branch). The guided
                # editor shows a summary; deep edits go through the raw-JSON hatch.
                params.append({"name": fname, "control": "nested", "required": True})
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
    timing: Timing  # instant/sorcery/channeled — also derives the card's speed
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
        # Descend into modal modes / conditional branches so nested effects are
        # checked too.
        for effect in iter_effects(self.effects):
            name = slot_name(getattr(effect, "target", None))
            if name is not None and name not in self.targets:
                raise ValueError(
                    f"effect references undeclared slot '${name}'; declare it in 'targets'"
                )
            if effect.kind in ("draw", "scry", "move_card"):
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
            if effect.trigger is not None:
                if not is_channeled:
                    raise ValueError(f"trigger '{effect.trigger}' is only valid on channeled cards")
                if getattr(effect, "duration", None) == Duration.while_channeled:
                    raise ValueError("a triggered effect must not also be 'while_channeled'")
        return self

    def resolved_target(self, effect) -> Optional[TargetDescriptor]:
        """The effect's effective descriptor, resolving a slot ref if present."""
        target = getattr(effect, "target", None)
        name = slot_name(target)
        if name is not None:
            return self.targets.get(name)
        return target

    # Player cards are always spells; their speed derives from `timing`
    # (instant→reactive, sorcery→active, channeled→sustained). Never stored.
    @property
    def action_type(self) -> ActionType:
        return ActionType.spell

    @property
    def speed(self) -> Speed:
        return spell_speed(self.timing.value)


class Archetype(str, Enum):
    Fighter = "Fighter"
    Tactician = "Tactician"
    Caster = "Caster"
    Channeler = "Channeler"


# Single source of truth for archetype stats. Stats are a function of
# (archetype, level); at level 1 they equal this table. Retune here.
ARCHETYPE_STATS = {
    Archetype.Fighter: {"starting_hp": 25, "starting_hand": 2, "starting_mana": 2},
    Archetype.Tactician: {"starting_hp": 15, "starting_hand": 4, "starting_mana": 2},
    Archetype.Caster: {"starting_hp": 10, "starting_hand": 3, "starting_mana": 3},
    Archetype.Channeler: {"starting_hp": 15, "starting_hand": 2, "starting_mana": 4},
}

# Attack profile = (mode, power), sitting alongside HP/hand/mana (Design Update R-3).
# Basic-attack damage = Power. Fighter is melee-only; the others choose one profile
# at creation, fixed thereafter. The first key listed is the archetype's default.
ARCHETYPE_ATTACK = {
    Archetype.Fighter: {AttackMode.melee: 3},
    Archetype.Tactician: {AttackMode.ranged: 1, AttackMode.melee: 2},
    Archetype.Channeler: {AttackMode.ranged: 1, AttackMode.melee: 2},
    Archetype.Caster: {AttackMode.ranged: 2, AttackMode.melee: 1},
}


def default_attack_mode(archetype: Archetype) -> AttackMode:
    """The archetype's default attack mode (first profile listed)."""
    return next(iter(ARCHETYPE_ATTACK[Archetype(archetype)]))


def attack_power(archetype: Archetype, mode: AttackMode, level: int = 1) -> int:
    """Basic-attack Power for an (archetype, attack mode). Level-flat for now (R-3)."""
    profiles = ARCHETYPE_ATTACK[Archetype(archetype)]
    return profiles[AttackMode(mode)]


def archetype_stats(archetype: Archetype, level: int = 1) -> dict:
    """Resolved stats for an (archetype, level). Level is a placeholder for now."""
    return dict(ARCHETYPE_STATS[Archetype(archetype)])


class Character(BaseModel):
    name: str
    description: str = ""
    # Optional portrait, stored inline as a data URL (or any image URL) so a
    # saved loadout stays self-contained. Empty when unset.
    portrait: str = ""
    archetype: Archetype  # required — drives derived stats (see ARCHETYPE_STATS)
    level: int = 1
    colors: List[Color]
    starting_mana: List[Color]
    # Attack profile (R-3) and default battlefield row (R-1). `attack_mode` is
    # chosen at creation; `row` is the character's starting row.
    attack_mode: Optional[AttackMode] = None
    row: Row = Row.front

    @field_validator("colors")
    @classmethod
    def _colors_count(cls, v: List[Color]) -> List[Color]:
        if not (1 <= len(v) <= 3):
            raise ValueError("colors must be 1-3 of W U B R G")
        if len(set(v)) != len(v):
            raise ValueError("colors must be unique")
        return v

    @field_validator("level")
    @classmethod
    def _level_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError("level must be >= 1")
        return v

    @model_validator(mode="after")
    def _mana_count(self) -> "Character":
        amount = archetype_stats(self.archetype, self.level)["starting_mana"]
        if len(self.starting_mana) != amount:
            raise ValueError(
                f"{self.archetype.value} starts with {amount} mana colours; "
                f"got {len(self.starting_mana)}"
            )
        return self

    @model_validator(mode="after")
    def _attack_mode_valid(self) -> "Character":
        """Fill the archetype default when unset; reject a mode the archetype
        can't take (e.g. Fighter is melee-only) — R-3."""
        allowed = ARCHETYPE_ATTACK[Archetype(self.archetype)]
        if self.attack_mode is None:
            object.__setattr__(self, "attack_mode", default_attack_mode(self.archetype))
        elif AttackMode(self.attack_mode) not in allowed:
            raise ValueError(
                f"{self.archetype.value} has no {self.attack_mode.value} attack profile; "
                f"choose one of {[m.value for m in allowed]}"
            )
        return self

    @property
    def power(self) -> int:
        """Basic-attack Power, from the (archetype, attack mode) profile (R-3)."""
        return attack_power(self.archetype, self.attack_mode or default_attack_mode(self.archetype),
                            self.level)

    @property
    def stats(self) -> dict:
        """Derived HP / hand size / mana amount / Power — read-only, from the tables."""
        s = archetype_stats(self.archetype, self.level)
        s["power"] = self.power
        s["attack_mode"] = (self.attack_mode or default_attack_mode(self.archetype)).value
        return s


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

    identity = {c.value for c in loadout.character.colors}

    def off_identity(card) -> bool:
        # A card is off-colour if its cost OR any ramp/add_mana grant introduces a
        # colour outside the deck identity (a "choice" grant is always fine).
        colours = {c.value for c in card.cost.colors.keys()}
        for e in iter_effects(card.effects):
            grant = getattr(e, "color", None)
            if grant is not None and grant != "choice":
                colours.add(grant)
        return bool(colours - identity)

    off_color = sorted({c.name for c in cards if off_identity(c)})

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
