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
    # Every value names the span the effect is active FOR (not the event that ends
    # it), matching `encounter` / `while_channeled`. `this_turn` covers the rest of
    # the current turn and expires at the End step — the former `end_of_turn` was a
    # synonym for exactly this and is aliased below for legacy data.
    this_turn = "this_turn"
    encounter = "encounter"
    # Applies continuously while the enchantment is channeled (channeled cards only).
    while_channeled = "while_channeled"

    @classmethod
    def _missing_(cls, value):
        # Legacy alias: `end_of_turn` was merged into `this_turn` (identical
        # behaviour). Old saved cards still load and normalise to `this_turn`.
        if value == "end_of_turn":
            return cls.this_turn
        return None


# Effects on channeled cards may fire on a trigger instead of being continuous:
# "channel_start" (once, as the channel begins — the MTG analogue is an
# enchantment's "when ~ enters the battlefield" trigger), "upkeep" (start of
# each of your turns), "capacity_increase" (landfall — whenever your mana
# capacity goes up), or "channel_break" (once, as a respondable stack trigger,
# when the channel ends — dropped or broken, for any reason; the MTG analogue
# is a "when this leaves play" / sacrifice ability).
TriggerType = Literal["channel_start", "upkeep", "capacity_increase", "channel_break"]

# Combat events a channeled effect can watch (EventTrigger below), and whose
# events count — relative to the channel's HOLDER: "you" = the holder,
# "target" = the channel's chosen target, "ally" = anyone on the holder's side
# (including the holder), "enemy" = anyone opposing, "any" = anyone at all.
# "death" covers both forms of falling: an enemy/token dying and a player
# character being incapacitated (a holder's own channels break on their
# incapacitation, but the trigger fires first — a death rattle).
TRIGGER_EVENTS = ["attack", "damage_taken", "life_gain", "spell_cast", "card_draw",
                  "death"]
TRIGGER_WHO = ["you", "target", "ally", "enemy", "any"]


class EventTrigger(BaseModel):
    """A channeled effect that fires on a combat event: someone attacks, is
    dealt damage, gains life, casts a spell (optionally of one card type),
    draws a card, or dies / is incapacitated. `who` scopes whose events count,
    relative to the holder."""

    event: Literal["attack", "damage_taken", "life_gain", "spell_cast", "card_draw",
                   "death"]
    who: Literal["you", "target", "ally", "enemy", "any"] = "you"
    # spell_cast only: fire only for this card type (instant/sorcery/channeled).
    spell_type: Optional[Timing] = None

    @model_validator(mode="after")
    def _coherent(self) -> "EventTrigger":
        if self.spell_type is not None and self.event != "spell_cast":
            raise ValueError("spell_type is only valid on a 'spell_cast' event trigger")
        return self


# A trigger is either one of the fixed channel-lifecycle triggers or an event watch.
Trigger = Union[TriggerType, EventTrigger]


class Ref(BaseModel):
    """A late-bound value the resolver fills in, e.g. {"ref": "destroyed_target.level"}."""

    ref: str


# The value references the engine can resolve, with display labels. The editor
# builds its "reference" dropdown from this registry — no free-text refs.
# (mana_capacity also has its own shortcut in the editor's value control.)
REF_VALUES = {
    "mana_capacity": "your mana capacity",
    "destroyed_target.level": "the destroyed target's level",
    "casting_cost": "this card's casting cost (mana paid, X included)",
    "x": "X (chosen at cast)",
    # The number of player characters in the encounter (downed members still
    # count — incapacitation is recoverable, the seat remains).
    "party_size": "the party size (number of players)",
    # Live combat stats, read at RESOLUTION (a pump landing first changes them).
    # "caster" is the card's controller; "target" is the creature the effect is
    # landing on (per-creature for a mode:all effect — each reads its own stats).
    "caster_power": "your Power (the caster's, at resolution)",
    "caster_hp": "your current HP (the caster's, at resolution)",
    "target_power": "the target's Power",
    "target_hp": "the target's current HP",
}


# Value = int | "all" | {"ref": str}
Value = Union[int, Literal["all"], Ref]

# A stat delta (pump/wound/counters power & toughness): a constant or a dynamic
# reference ("+X/+X", "+1 per party member") — never "all", which only makes
# sense for amounts ("draw all", "destroy all damage").
StatValue = Union[int, Ref]


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
    "haste": {"display": "Haste", "gloss": "may take its proactive action and also make a free voluntary move this turn (the move still resolves at End step)", "grantable": True, "params": []},
    "trample": {"display": "Trample", "gloss": "excess damage cleaves past the target", "grantable": True, "params": []},
    "deathtouch": {"display": "Deathtouch", "gloss": "mini-execute: its damage can destroy a minion", "grantable": True, "params": []},
    "lifelink": {"display": "Lifelink", "gloss": "heal equal to the damage it deals", "grantable": True, "params": []},
    "infect": {"display": "Infect", "gloss": "its damage that connects also poisons the victim — a −0/−1 per Upkeep until cured by any healing (D8-2.5)", "grantable": True, "params": []},
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
    An EventTrigger instead fires the effect whenever the watched combat event
    happens (someone attacks, takes damage, gains life, casts, or draws).
    """

    trigger: Optional[Trigger] = None


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


class Poison(EffectBase):
    """A poison effect (Design Update 08 §D8-2.1): places `amount` poison counters
    (each a persistent −0/−1) on resolution and again at the start of each Upkeep,
    until it concludes — the creature dies, receives any healing (an antidote is an
    antidote), or the optional `turns` bound expires. Not damage: it cannot be
    prevented or mitigated and never breaks a channel."""

    kind: Literal["poison"] = "poison"
    amount: Value = 1
    turns: Optional[int] = None  # absent = until concluded by rule
    target: TargetOrSlot


class Regen(EffectBase):
    """The mirror of poison (§D8-2.2): places `amount` regen counters (each a
    persistent +0/+1) on resolution and at each Upkeep until it concludes — the
    creature is dealt damage that connects, or the `turns` bound expires. A regen
    tick counts as healing (it cures poison). Poison and regen counters on the
    same creature annihilate 1:1 as a state-based action."""

    kind: Literal["regen"] = "regen"
    amount: Value = 1
    turns: Optional[int] = None
    target: TargetOrSlot


class Charge(EffectBase):
    """The windup verb (§D8-2.4): the source places `amount` charge counters on
    ITSELF — a visible gauge that detonates a hidden `on_charge_full` component at
    its threshold. Enemy-only: validation rejects it in a loadout (like `draw` on
    an enemy); the player analogue is the ultimate gauge (§D8-3.3)."""

    kind: Literal["charge"] = "charge"
    amount: int = 1


class Destroy(EffectBase):
    kind: Literal["destroy"] = "destroy"
    target: TargetOrSlot


class Exile(EffectBase):
    """Remove a creature from play.

    By default exile is permanent — a spell (instant/sorcery) that exiles puts the
    creature out of the game for good. On a channeled card, `duration:
    while_channeled` makes it reversible: the creature is suspended only while the
    channel holds and returns if the channel breaks (GDD §8). It stays gone if the
    encounter ends first — i.e. the last on-board enemies fall while it is exiled.
    """

    kind: Literal["exile"] = "exile"
    target: TargetOrSlot
    # Permanent when unset; `while_channeled` makes it reversible. Exile has no
    # turn-scoped form, so the type offers only those two states (the editor then
    # shows a "(none) / while_channeled" dropdown).
    duration: Optional[Literal["while_channeled"]] = None


class Bounce(EffectBase):
    kind: Literal["bounce"] = "bounce"
    target: TargetOrSlot


class Fight(EffectBase):
    """Two creatures fight (MTG's 'fight'): each deals damage equal to its power to
    the other, simultaneously.

    `target` is the creature you control, `other` the creature you don't. Both are
    chosen at cast, so author them as two shared target slots (T1 ally, T2 enemy) —
    the editor's "shared slot" link on each target field wires them up.
    """

    kind: Literal["fight"] = "fight"
    target: TargetOrSlot  # the creature you control
    other: TargetOrSlot   # the creature it fights


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
    power: StatValue
    toughness: StatValue
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Wound(EffectBase):
    kind: Literal["wound"] = "wound"
    power: StatValue
    toughness: StatValue
    target: TargetOrSlot
    duration: Duration = Duration.this_turn


class Counters(EffectBase):
    kind: Literal["counters"] = "counters"
    power: StatValue
    toughness: StatValue
    target: TargetOrSlot
    duration: Duration = Duration.encounter


class Prevent(EffectBase):
    """Nullify a named thing for a duration (R-11): `prevent [parameter]` — e.g.
    `prevent combat_damage` makes attack actions against the target deal no damage,
    while `prevent attack` stops the target from attacking at all (Pacifism). The
    parameter names what is nullified; scope is defined by that parameter.

    `uses` disambiguates the two "protection" shapes the parameter can take:
      * `"all"` — nullify EVERY matching instance until the duration ends (Fog:
        "prevent all combat damage this turn"). The shield is not spent by a hit.
      * `"next"` — nullify only the NEXT matching instance, then wear off (a
        one-shot bodyguard, e.g. Gods Willing's protection).
    An action-blocking parameter like `attack` is inherently "all" for its
    duration (a channeled Pacifism keeps the creature from attacking every turn)."""

    kind: Literal["prevent"] = "prevent"
    parameter: str = "combat_damage"
    uses: Literal["all", "next"] = "all"
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
    duration: Duration = Duration.this_turn

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
    duration: Duration = Duration.this_turn

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
    Poison,
    Regen,
    Charge,
    Destroy,
    Exile,
    Bounce,
    Fight,
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
class CastModeCondition(BaseModel):
    """True when the card was cast at this speed (action = proactive, reaction = response)."""

    kind: Literal["cast_mode"] = "cast_mode"
    mode: Literal["action", "reaction"]


class TargetPropertyCondition(BaseModel):
    """True when the (main) target has a property — a keyword, a side, a level
    (compared with exactly / or_more / or_less), or a battlefield row."""

    kind: Literal["target_property"] = "target_property"
    property: Literal["has_keyword", "side", "level", "row"]
    keyword: Optional[str] = None
    side: Optional[Side] = None
    level: Optional[int] = None
    row: Optional[Row] = None
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
        if self.property == "row" and self.row is None:
            raise ValueError("target_property 'row' requires a row")
        return self


class CasterPropertyCondition(BaseModel):
    """True when the CASTER (the spell's controller / a channel's holder) has a
    property — their battlefield row, a keyword, or whether they are actively
    channeling (holding at least one channel)."""

    kind: Literal["caster_property"] = "caster_property"
    property: Literal["row", "has_keyword", "channeling"]
    row: Optional[Row] = None
    keyword: Optional[str] = None

    @model_validator(mode="after")
    def _coherent(self) -> "CasterPropertyCondition":
        if self.property == "row" and self.row is None:
            raise ValueError("caster_property 'row' requires a row")
        if self.property == "has_keyword":
            if self.keyword is None:
                raise ValueError("caster_property 'has_keyword' requires a keyword")
            if self.keyword not in KEYWORDS:
                raise ValueError(f"unknown keyword '{self.keyword}'")
        return self


class SelfHpCondition(BaseModel):
    """True when the caster's HP, as a percentage of max HP, is at/below or
    at/above the threshold (e.g. 'you are at or below half health')."""

    kind: Literal["self_hp"] = "self_hp"
    percent: int = 50
    compare: Literal["or_less", "or_more"] = "or_less"

    @field_validator("percent")
    @classmethod
    def _pct(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("self_hp percent must be between 0 and 100")
        return v


class EnemyCountCondition(BaseModel):
    """True when the number of living enemy creatures compares as given to the
    party's size (living player characters)."""

    kind: Literal["enemy_count"] = "enemy_count"
    compare: Literal["more", "equal", "fewer"] = "more"


class SpellsCastCondition(BaseModel):
    """True when the caster has cast N spells this turn, counting this one
    (the count resets at the start of each of their turns)."""

    kind: Literal["spells_cast"] = "spells_cast"
    count: int = 2
    compare: Literal["exactly", "or_more", "or_less"] = "or_more"

    @field_validator("count")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("spells_cast count must be >= 0")
        return v


Condition = Annotated[
    Union[CastModeCondition, TargetPropertyCondition, CasterPropertyCondition,
          SelfHpCondition, EnemyCountCondition, SpellsCastCondition],
    Field(discriminator="kind"),
]


class Conditional(EffectBase):
    """Apply extra effect(s) only if a condition holds (target property or cast mode)."""

    kind: Literal["conditional"] = "conditional"
    condition: Condition
    effects: List[LeafEffect] = Field(min_length=1)


# A modal mode holds leaf effects and, one level deeper, a conditional
# (modal > conditional > effect). It may NOT hold another modal — the engine has
# no modal-in-modal, and resolution expands only the chosen mode's effects.
ModeEffect = Annotated[
    Union[tuple(LEAF_EFFECT_CLASSES + [Conditional])], Field(discriminator="kind")
]


class Mode(BaseModel):
    """One option of a modal card; the player picks exactly one mode at cast."""

    label: str = ""
    effects: List[ModeEffect] = Field(min_length=1)


class Modal(EffectBase):
    """A 'Choose N' card: pick `choose` of its modes at cast (or `choose` or more
    when `or_more` is set). Defaults to the classic 'Choose one'."""

    kind: Literal["modal"] = "modal"
    modes: List[Mode] = Field(min_length=2)
    choose: int = 1            # how many modes the caster picks
    or_more: bool = False      # "choose N or more" (choose is then the minimum)

    @model_validator(mode="after")
    def _check_choose(self) -> "Modal":
        if self.choose < 1:
            raise ValueError("modal 'choose' must be >= 1")
        if self.choose > len(self.modes):
            raise ValueError("modal 'choose' cannot exceed the number of modes")
        return self


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
        # Value = int | "all" | {ref}; StatValue = int | {ref} — the editor's
        # value control hides the "all" option when the type doesn't admit it.
        spec = {"control": "value"}
        if not any(_t.get_origin(a) is Literal and "all" in _t.get_args(a) for a in args):
            spec["no_all"] = True
        return spec
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
            if fname == "trigger":
                # `trigger` is a union (lifecycle literal | EventTrigger) — give the
                # editor a dedicated control with the full vocabulary.
                params.append({
                    "name": "trigger", "control": "trigger", "optional": True,
                    "default": None, "required": False,
                    "options": list(_t.get_args(TriggerType)),
                    "events": list(TRIGGER_EVENTS), "whos": list(TRIGGER_WHO),
                    "spell_types": [t.value for t in Timing],
                })
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
    """Parsed mana cost. `colors` holds only the pips that are present.

    `x` marks an {X} in the cost: the caster picks X at cast time and pays that
    much extra generic mana. Effects read the choice via the `x` value reference
    (and `casting_cost` = generic + pips + X paid)."""

    generic: int = 0
    colors: Dict[Color, int] = Field(default_factory=dict)
    x: bool = False

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
    # Optional, human-authored prose describing how the effect works "in
    # character" — flavour to accompany the flavour name. Never machine-derived.
    flavor_text: str = ""
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
            if effect.kind == "charge":
                # Charge is the enemy windup verb (D8-2.4); the player analogue is
                # the ultimate gauge. Rejected in a loadout like `draw` on an enemy.
                raise ValueError("charge is enemy-only and cannot appear on a card")
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


# --------------------------------------------------------------------------- #
# Character creation — points-buy against a budget (Design Update 05, §P-1..P-4).
#
# A character is no longer an archetype; it is a *build*: baseline stats plus
# bought steps, priced against a 70-point budget. The four GDD archetypes survive
# only as named 70-point PRESETS (§P-4b) — starting points, not a closed taxonomy.
# The engine consumes the resolved STAT BLOCK (`stat_block`), never a class name.
#
# All magnitudes are playtest starting values (§P-8 Rebalance Register); the
# mechanism is canonical. Only level-1 creation is implemented (flat costs); the
# leveling cliff of §P-6 is [DESIGNED — NOT SCHEDULED] and deliberately absent.
# --------------------------------------------------------------------------- #
CREATION_BUDGET = 70                                    # T5-01
BASELINE_HP = 8                                         # §P-1 free base
BASELINE_MANA = 1
BASELINE_CARDS = 1
# Free base Power per attack mode; melee's higher base pays for its row-restriction.
BASE_POWER = {AttackMode.melee: 2, AttackMode.ranged: 1}  # §P-1

COST_HP_STEP = 5     # per +2 HP step (HP is bought two at a time)   T5-02
COST_MANA = 15       # per +1 mana capacity                          T5-03
COST_CARD = 15       # per +1 starting card                          T5-04
COST_POWER = 10      # per +1 Power above the mode's base            T5-05
MAX_POWER_BOUGHT = 2  # §P-4 Power cap: melee ≤ 4, ranged ≤ 3         T5-14
MAX_KEYWORDS = 1     # §P-3 one keyword at creation                  T5-06

# Buyable keyword costs (§P-3, T5-07..13). The set is deliberately narrow.
CREATION_KEYWORD_COST = {
    "reach": 5, "trample": 10, "first_strike": 15, "lifelink": 15,
    "haste": 15, "vigilance": 20, "flying": 25,
}
# Hard-stop at creation (§P-3, D8-2.5): may exist on enemies / via gear later,
# never bought — infect reaches a hero only by being granted.
BANNED_CREATION_KEYWORDS = {"protection", "hexproof", "indestructible", "deathtouch", "infect"}


class Archetype(str, Enum):
    Fighter = "Fighter"
    Tactician = "Tactician"
    Caster = "Caster"
    Channeler = "Channeler"


# The four archetypes as pre-spent 70-point builds (§P-4b). Each is a *build* the
# Deckbuilder can load, not a class the engine knows about. `mode` is the default
# attack mode (the first profile listed); `power` is Power bought above base. HP is
# re-baselined to the even values that preserve 70-point equality under the 8-HP base.
PRESETS = {
    Archetype.Fighter:   {"hp": 20, "mana": 2, "cards": 2, "power": 1, "mode": AttackMode.melee},
    Archetype.Tactician: {"hp": 12, "mana": 2, "cards": 4, "power": 0, "mode": AttackMode.ranged},
    Archetype.Caster:    {"hp": 8,  "mana": 3, "cards": 3, "power": 1, "mode": AttackMode.ranged},
    Archetype.Channeler: {"hp": 12, "mana": 4, "cards": 2, "power": 0, "mode": AttackMode.ranged},
}

# Pre-Update-05 HP for the same archetypes. Only HP was re-baselined (§P-4b); hand,
# mana, and Power are identical to the new presets. Characters saved before Update
# 05 (an `archetype` key, no build fields) load with these legacy HP values, exempt
# from the even-HP/budget guardrails — the odd legacy values (25/15) cannot be valid
# new builds, and the canonical §A/§C reference traces are tuned to them. New builds
# authored in the Deckbuilder always use the re-baselined PRESETS above.
LEGACY_ARCHETYPE_HP = {
    Archetype.Fighter: 25, Archetype.Tactician: 15,
    Archetype.Caster: 10, Archetype.Channeler: 15,
}


def creation_points(hp: int, mana_capacity: int, starting_cards: int,
                    power_bought: int, keyword: Optional[str]) -> int:
    """Points a build spends against the §P-2 flat creation table."""
    pts = (
        COST_HP_STEP * ((hp - BASELINE_HP) // 2)
        + COST_MANA * (mana_capacity - BASELINE_MANA)
        + COST_CARD * (starting_cards - BASELINE_CARDS)
        + COST_POWER * power_bought
    )
    if keyword:
        pts += CREATION_KEYWORD_COST.get(keyword, 0)
    return pts


def preset_character(archetype: Archetype, name: str, colors, starting_mana,
                     **extra) -> "Character":
    """Materialise a named 70-point preset (§P-4b) into a concrete Character."""
    p = PRESETS[Archetype(archetype)]
    return Character(
        name=name, colors=list(colors), starting_mana=list(starting_mana),
        hp=p["hp"], starting_cards=p["cards"], power_bought=p["power"],
        attack_mode=p["mode"], preset=Archetype(archetype).value, **extra,
    )


class FlavorEntry(BaseModel):
    """Optional display flavour for one evergreen ability (D8-3.4): a custom name
    and a one-line text. Purely presentational — the mechanics are untouched."""

    name: str = ""
    text: str = ""


class AbilityFlavor(BaseModel):
    attack: Optional[FlavorEntry] = None
    defend: Optional[FlavorEntry] = None
    mitigate: Optional[FlavorEntry] = None


class Character(BaseModel):
    name: str
    description: str = ""
    # Optional portrait, stored inline as a data URL (or any image URL) so a
    # saved loadout stays self-contained. Empty when unset.
    portrait: str = ""
    level: int = 1
    colors: List[Color]
    # Starting-mana capacity as a per-slot colour list; its LENGTH is the mana
    # capacity (§P-1), each colour within the character's identity.
    starting_mana: List[Color]

    # --- points-buy build (§P-1..P-4). Baseline is free; these are what was bought. ---
    hp: int = BASELINE_HP                     # total HP; even, ≥ 8, bought in +2 steps
    starting_cards: int = BASELINE_CARDS      # total opening-hand size, ≥ 1
    power_bought: int = 0                     # Power above the mode's base (0..MAX_POWER_BOUGHT)
    attack_mode: AttackMode = AttackMode.melee  # the one owned mode (§P-1)
    keyword: Optional[str] = None             # at most one buyable keyword (§P-3)
    row: Row = Row.front

    # --- heroic actions (Design Update 08 §D8-3): authored on the character sheet
    # with the full card schema — NOT library cards (never drawn, outside the
    # 20-card deck, rarity quotas and the singleton rule; exempt from deck lints).
    # Neither is priced by the 70-point budget for now (§D8-3.5).
    skill: Optional[Card] = None       # once per encounter; timing forced to instant
    ultimate: Optional[Card] = None    # once per encounter; sorcery; zero mana cost
    ability_flavor: AbilityFlavor = Field(default_factory=AbilityFlavor)

    # Display-only label: the preset this build was loaded from, or None for a
    # custom build. The engine derives nothing from it.
    preset: Optional[str] = None
    # True for a pre-Update-05 character migrated from an `archetype` key: it keeps
    # its legacy (possibly odd) HP and is exempt from the even-HP/budget guardrails.
    legacy: bool = False

    @model_validator(mode="before")
    @classmethod
    def _migrate_archetype(cls, data):
        """Back-compat: a pre-Update-05 archetype-only character (an `archetype` key,
        no build fields) loads as its legacy build — legacy HP, preset hand/mana/Power
        — flagged `legacy` so the new guardrails don't reject its odd HP. New builds
        (no `archetype` key) get the full Update-05 points-buy treatment."""
        if not isinstance(data, dict):
            return data
        arch = data.get("archetype")
        if arch is not None and "hp" not in data:
            a = Archetype(arch)
            p = PRESETS[a]
            data = dict(data)
            data["hp"] = LEGACY_ARCHETYPE_HP[a]  # only HP was re-baselined; keep legacy
            data.setdefault("starting_cards", p["cards"])
            data.setdefault("power_bought", p["power"])
            data.setdefault("attack_mode", data.get("attack_mode") or p["mode"].value)
            data.setdefault("preset", a.value)
            data["legacy"] = True
        data.pop("archetype", None)  # retired field; never stored going forward
        return data

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
    def _floors_and_caps(self) -> "Character":
        """Enforce the §P-4 guardrails: floors, HP parity, and the Power cap. A
        migrated legacy character is exempt from HP parity and the Power cap (its
        odd HP / higher Power predate the rule); floors still hold."""
        if self.hp < BASELINE_HP:
            raise ValueError(f"HP floor is {BASELINE_HP} (§P-4)")
        if self.starting_cards < BASELINE_CARDS:
            raise ValueError("starting cards floor is 1 (§P-4)")
        if self.legacy:
            return self
        if self.hp % 2 != 0:
            raise ValueError("HP is bought in 2-point steps and must be even (§P-2)")
        if not (0 <= self.power_bought <= MAX_POWER_BOUGHT):
            cap = BASE_POWER[AttackMode(self.attack_mode)] + MAX_POWER_BOUGHT
            raise ValueError(
                f"Power cap at creation is +{MAX_POWER_BOUGHT} "
                f"({self.attack_mode.value} ≤ {cap}) — §P-4/T5-14"
            )
        return self

    @model_validator(mode="after")
    def _mana_floor(self) -> "Character":
        """Mana capacity is len(starting_mana), and must meet the floor (§P-4). Slots
        outside the colour identity stay a soft advisory (see `deck_status`), not a
        hard error — the same non-blocking treatment as before Update 05."""
        if len(self.starting_mana) < BASELINE_MANA:
            raise ValueError(f"mana floor is {BASELINE_MANA} (§P-4)")
        return self

    @model_validator(mode="after")
    def _keyword_valid(self) -> "Character":
        """At most one keyword, from the buyable set — banned keywords are rejected."""
        kw = self.keyword
        if kw is None:
            return self
        if kw in BANNED_CREATION_KEYWORDS:
            raise ValueError(f"'{kw}' cannot be bought at creation (§P-3 hard stop)")
        if kw not in CREATION_KEYWORD_COST:
            raise ValueError(
                f"'{kw}' is not a buyable creation keyword; "
                f"choose one of {sorted(CREATION_KEYWORD_COST)}"
            )
        return self

    @model_validator(mode="after")
    def _within_budget(self) -> "Character":
        """The build may not spend more than the 70-point creation budget (§P-1).
        Migrated legacy characters are exempt (their odd HP can exceed it)."""
        if not self.legacy and self.points_spent > CREATION_BUDGET:
            raise ValueError(
                f"build spends {self.points_spent} points, over the "
                f"{CREATION_BUDGET}-point creation budget (§P-1)"
            )
        return self

    @model_validator(mode="after")
    def _heroics_valid(self) -> "Character":
        """D8-3.5: the Skill's timing is FORCED to instant and the Ultimate's to
        sorcery (channeled is illegal for both — coerced away rather than
        round-tripped); the Ultimate may never carry a mana cost (the gauge is
        the cost)."""
        if self.skill is not None and self.skill.timing != Timing.instant:
            # Rebuild so Card's own validators re-run against the forced timing
            # (a channeled-only effect then raises instead of slipping through).
            self.skill = Card.model_validate(
                {**self.skill.model_dump(mode="json"), "timing": "instant"})
        if self.ultimate is not None:
            if self.ultimate.timing != Timing.sorcery:
                self.ultimate = Card.model_validate(
                    {**self.ultimate.model_dump(mode="json"), "timing": "sorcery"})
            cost = self.ultimate.cost
            if cost.generic or cost.x or any(cost.colors.values()):
                raise ValueError(
                    "an ultimate never costs mana — the gauge is the cost (§D8-3.2)")
        return self

    @property
    def mana_capacity(self) -> int:
        return len(self.starting_mana)

    @property
    def power(self) -> int:
        """Basic-attack Power = the mode's free base + Power bought (§P-1/§P-2)."""
        return BASE_POWER[AttackMode(self.attack_mode)] + self.power_bought

    @property
    def points_spent(self) -> int:
        """Creation points this build spends against the §P-2 flat table."""
        return creation_points(self.hp, self.mana_capacity, self.starting_cards,
                               self.power_bought, self.keyword)

    @property
    def points_remaining(self) -> int:
        return CREATION_BUDGET - self.points_spent

    @property
    def stat_block(self) -> dict:
        """The §P-4c resolved stat block the combat engine consumes — no class name."""
        return {
            "hp": self.hp,
            "mana_capacity": self.mana_capacity,
            "starting_cards": self.starting_cards,
            "attack_profile": {"mode": self.attack_mode.value, "power": self.power},
            "keywords": [self.keyword] if self.keyword else [],
        }

    @property
    def stats(self) -> dict:
        """Legacy-shaped view (starting_hp / starting_hand / starting_mana / power /
        attack_mode) kept for the scenario loader; sourced from the build."""
        return {
            "starting_hp": self.hp,
            "starting_hand": self.starting_cards,
            "starting_mana": self.mana_capacity,
            "power": self.power,
            "attack_mode": self.attack_mode.value,
            "keywords": [self.keyword] if self.keyword else [],
        }


class Loadout(BaseModel):
    ltg_version: str = "0.1"
    character: Character
    cards: List[Card] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Deck status (live, non-blocking advisory — never raises)
# --------------------------------------------------------------------------- #
# A deck is 20 cards: 1 mythic + 3 rare + 6 uncommon + 10 common, as MINIMUMS.
# Going over 20 is fine as long as the excess is all commons — so the non-common
# rarities are exact quotas (minimum == cap) and common is a floor with no cap.
# Violations WARN in the Deckbuilder; they never block save, export, or play.
DECK_MINIMUM = 20
RARITY_MINIMUMS = {"mythic": 1, "rare": 3, "uncommon": 6, "common": 10}
UNCAPPED_RARITIES = frozenset({"common"})  # only commons may exceed their quota


def deck_status(loadout: Loadout) -> dict:
    """Compute the advisory deck-status readout. Warnings, never errors."""
    cards = loadout.cards
    rarity_counts = {r: 0 for r in RARITY_MINIMUMS}
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
        "size": {"count": len(cards), "minimum": DECK_MINIMUM},
        "rarity": {
            r: {"count": rarity_counts[r], "minimum": RARITY_MINIMUMS[r],
                "capped": r not in UNCAPPED_RARITIES}
            for r in RARITY_MINIMUMS
        },
        "duplicates": duplicates,
        "off_color": off_color,
        "untranslated": untranslated,
        "starting_mana_outside_identity": starting_mana_off,
    }
