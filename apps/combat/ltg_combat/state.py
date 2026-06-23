"""The combat state model — a single value the engine reads and rewrites.

Everything the engine needs lives in one `GameState`: the party, the enemies,
autonomous ally tokens, held channels, the stack, the round/phase/priority
bookkeeping, and the accumulating event log. `apply_action` treats state as a
value (it deep-copies before mutating), so a `GameState` is safe to keep, diff,
or re-apply against.

These are plain dataclasses, not `core` models: `core` owns the *card* vocabulary
(the Deckbuilder's contract), while this module owns the *runtime* shape. Cards
and effect primitives stored inside (`hand`, `library`, `StackItem.effects`,
`Channel.card`) are genuine `core` models — the engine never re-invents the
effect schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ltg_core.schema import Card, Effect


# --------------------------------------------------------------------------- #
# Channels (held channeled enchantments, GDD §8)
# --------------------------------------------------------------------------- #
@dataclass
class Channel:
    """A channeled card held in play, anchored to its caster.

    `reserved` is the actual mana paid at cast — it stays out of the pool while
    held (doesn't refresh) and is released all at once when the channel ends.
    `target_id` is the aura target (for a channel that targets a creature).
    """

    card: Card
    holder_id: str
    reserved: List[str] = field(default_factory=list)
    target_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Combatants
# --------------------------------------------------------------------------- #
@dataclass
class CharacterState:
    """A player-character at runtime.

    Starting stats (`max_hp`, `power`, `hand_size`, the mana colours) are inputs
    from the scenario, never derived from an archetype here — the engine is told
    the resolved numbers (brief build-order §1).
    """

    id: str
    name: str
    max_hp: int
    hp: int
    power: int
    hand_size: int
    archetype: str = ""  # display-only label; the engine derives no stats from it
    parry_reduce: int = 2  # how much this character's Parry reduces a hit by
    hand: List[Card] = field(default_factory=list)
    library: List[Card] = field(default_factory=list)  # ordered; top == index 0
    identity: List[str] = field(default_factory=list)   # colours the +1 may lock
    mana_colors: List[str] = field(default_factory=list)  # one per capacity slot
    pool: List[str] = field(default_factory=list)        # spendable mana this turn
    channels: List[Channel] = field(default_factory=list)
    row: str = "front"

    # Temporary defensive layers (all expire at end step in this milestone).
    temp_hp: int = 0          # absorbs damage after prevention (pump toughness / Defend)
    prevent_pool: int = 0     # reduces the next damage this turn (prevent / Parry)
    power_bonus: int = 0      # temporary Power (pump)

    # Per-round / per-turn flags (reset at upkeep).
    used_attack: bool = False
    used_defend: bool = False
    used_parry: bool = False
    acted_mode: Optional[str] = None  # None | "attack" | "cast" | "defend" this turn
    turn_ended: bool = False
    capacity_chosen: bool = False  # locked this turn's +1 capacity colour yet?

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def current_power(self) -> int:
        return self.power + self.power_bonus

    @property
    def capacity(self) -> int:
        return len(self.mana_colors)

    @property
    def reserved(self) -> List[str]:
        """Mana currently locked by held channels."""
        return [color for ch in self.channels for color in ch.reserved]


@dataclass
class TokenState:
    """An autonomous ally token (e.g. a Wisp). Acts on its own each turn and
    dies at 0 HP (unlike a player-character, which is merely incapacitated)."""

    id: str
    name: str
    max_hp: int
    hp: int
    power: int
    row: str = "front"
    temp_hp: int = 0
    prevent_pool: int = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Intent:
    """An enemy's declared next action (the pre-stack form, GDD §5.2)."""

    name: str               # e.g. "Claw"
    action_type: str        # "ability" / "spell"
    effects: List[Effect]   # core effect primitives this intent will resolve
    target_id: Optional[str]  # combatant the intent points at (resolved at declare)


@dataclass
class EnemyState:
    """A minion (bosses are out of scope this milestone). Dies at 0 HP."""

    id: str
    name: str
    max_hp: int
    hp: int
    level: int
    row: str = "front"
    intent: Optional[Intent] = None
    intent_template: Dict[str, Any] = field(default_factory=dict)
    disabled_intent_types: List[str] = field(default_factory=list)  # e.g. ["attack"]

    # Mirror the character's defensive layers so one damage routine serves both.
    temp_hp: int = 0
    prevent_pool: int = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0


# --------------------------------------------------------------------------- #
# The stack
# --------------------------------------------------------------------------- #
@dataclass
class StackItem:
    """One action waiting to resolve (LIFO). Carries the resolved single target.

    For a channeled cast, `card` and `reserved` carry the held-channel payload so
    resolution can start the channel instead of running the effects once.
    """

    kind: str               # "attack" | "spell" | "ability"
    source_id: str
    source_side: str        # "party" | "enemy"
    label: str              # display name (card name / "Basic Attack" / "Claw")
    effects: List[Effect]
    target_id: Optional[str] = None
    card_id: Optional[str] = None
    card: Optional[Card] = None
    reserved: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Actions (engine input) and Events (engine output)
# --------------------------------------------------------------------------- #
@dataclass
class Action:
    """A choice returned by `legal_actions` and consumed by `apply_action`.

    Clients never construct rules — they pick one of these verbatim.
    """

    kind: str               # attack|cast|defend|parry|pass|end_turn|choose_mana|drop_channels
    actor_id: str
    card_id: Optional[str] = None
    target_id: Optional[str] = None
    color: Optional[str] = None  # the locked colour, for choose_mana
    label: str = ""

    def key(self) -> tuple:
        """Identity used to match a chosen action against the legal set."""
        return (self.kind, self.actor_id, self.card_id, self.target_id, self.color)


@dataclass
class Event:
    """One entry in the structured log — the narrator's (future) input and what
    the tests and the text UI read. `data` carries machine-checkable fields."""

    type: str
    msg: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GameState:
    party: List[CharacterState]
    enemies: List[EnemyState]
    tokens: List[TokenState] = field(default_factory=list)
    token_defs: Dict[str, Any] = field(default_factory=dict)  # token_id -> stats
    token_seq: int = 0                # for unique created-token ids
    turn: int = 1
    phase: str = "upkeep"             # upkeep|capacity|draw|intents|player|allies|enemy|end
    stack: List[StackItem] = field(default_factory=list)
    priority: Optional[str] = None    # party member who must decide now
    passes: int = 0                   # consecutive passes in the open window
    acted_enemies: List[str] = field(default_factory=list)
    acted_tokens: List[str] = field(default_factory=list)
    pending_break: List[str] = field(default_factory=list)  # channelers owed a break
    result: Optional[str] = None      # None | "victory" | "defeat"
    log: List[Event] = field(default_factory=list)

    # ---- lookups ---------------------------------------------------------- #
    def character(self, cid: str) -> Optional[CharacterState]:
        return next((c for c in self.party if c.id == cid), None)

    def enemy(self, eid: str) -> Optional[EnemyState]:
        return next((e for e in self.enemies if e.id == eid), None)

    def token(self, tid: str) -> Optional[TokenState]:
        return next((t for t in self.tokens if t.id == tid), None)

    def combatant(self, cid: str):
        return self.character(cid) or self.enemy(cid) or self.token(cid)

    def living_party(self) -> List[CharacterState]:
        return [c for c in self.party if c.alive]

    def living_enemies(self) -> List[EnemyState]:
        return [e for e in self.enemies if e.alive]

    def living_tokens(self) -> List[TokenState]:
        return [t for t in self.tokens if t.alive]
