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
from typing import Any, Dict, List, Optional, Tuple

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
    attack_mode: str = "melee"  # melee | ranged (R-1/R-3) — drives reachability
    level: int = 1              # ordering / level-gates (R-6)
    hand: List[Card] = field(default_factory=list)
    library: List[Card] = field(default_factory=list)  # ordered; top == index 0
    graveyard: List[Card] = field(default_factory=list)  # spent / channelled cards (R-9)
    exile: List[Card] = field(default_factory=list)      # cards removed from the game (move_card)
    identity: List[str] = field(default_factory=list)   # colours the +1 may lock
    mana_colors: List[str] = field(default_factory=list)  # one per capacity slot
    pool: List[str] = field(default_factory=list)        # spendable mana this turn
    channels: List[Channel] = field(default_factory=list)
    # Position model (Design Update 02 §M-B). `row` is the *current* (physical) row —
    # what intents and the melee wall read; it changes only at End step. `committed`
    # is what this character's OWN actions/reactions read (Mitigate adjacency); forced
    # moves write it immediately. `pending_voluntary` holds a chosen Move's destination,
    # resolved into `row` at End step (it grants no reach mid-turn).
    row: str = "front"
    committed: str = "front"
    pending_voluntary: Optional[str] = None

    # Unified HP model (Design Update R-7): damage reduces `hp` directly; `temp_mod`
    # is the net of end-of-turn pump (+) / wound (−) modifiers and expires at End.
    # Lethality is checked on effective_hp = hp + temp_mod.
    temp_mod: int = 0
    prevent_pool: int = 0     # numeric pre-damage reduction (R-11 numeric prevent)
    prevent_tags: List[str] = field(default_factory=list)  # nullifiers (R-11 prevent)
    power_bonus: int = 0      # temporary Power (pump +, wound −)
    protection: int = 0       # negates the next N spells/attacks (protection)
    # Granted keyword statics: {keyword: duration}. Duration drives expiry at the
    # end step (end_of_turn/this_turn) or channel break (while_channeled); 'encounter'
    # / 'permanent' persist. The engine reads these for keyword behaviour (GDD §7).
    keywords: Dict[str, str] = field(default_factory=dict)

    # Per-round / per-turn flags (reset at upkeep).
    used_attack: bool = False
    used_defend: bool = False
    used_mitigate: bool = False
    acted_mode: Optional[str] = None  # None | "attack" | "cast" | "defend" | "move" this turn
    turn_ended: bool = False
    capacity_chosen: bool = False  # locked this turn's +1 capacity colour yet?

    @property
    def effective_hp(self) -> int:
        return self.hp + self.temp_mod

    @property
    def alive(self) -> bool:
        # A player-character is "up" while effective_hp > 0; ≤ 0 is incapacitated
        # (recoverable — R-7). Lethality everywhere is keyed to effective_hp.
        return self.effective_hp > 0

    @property
    def current_power(self) -> int:
        return max(0, self.power + self.power_bonus)

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
    attack_mode: str = "melee"
    level: int = 1
    intent: Optional["Intent"] = None  # telegraphed in the Intents step (R-5)
    temp_mod: int = 0
    prevent_pool: int = 0
    prevent_tags: List[str] = field(default_factory=list)
    protection: int = 0
    power_bonus: int = 0  # temporary Power (pump +, wound −) — tokens can be anthemed
    keywords: Dict[str, str] = field(default_factory=dict)

    @property
    def effective_hp(self) -> int:
        return self.hp + self.temp_mod

    @property
    def alive(self) -> bool:
        return self.effective_hp > 0

    @property
    def current_power(self) -> int:
        return max(0, self.power + self.power_bonus)


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
    # The enemy's attack power (its basic damage). Drives `fight`; its telegraphed
    # intent still carries its own `amount`. Defaults to the intent amount at build.
    power: int = 0
    row: str = "front"
    attack_mode: str = "melee"  # melee | ranged (R-1) — enemy attacks are classified too
    intent: Optional[Intent] = None
    intent_template: Dict[str, Any] = field(default_factory=dict)
    # An optional weaker ranged attack (R-1 heuristics): the enemy falls back to it
    # when its melee attack can't reach the target the heuristic wants. Same shape as
    # `intent_template` (name/amount/action_type); empty == melee-only.
    ranged_template: Dict[str, Any] = field(default_factory=dict)
    stunned: int = 0           # intents to skip (stun); decremented as they would declare
    taunted_by: Optional[str] = None  # forced to target this character id (taunt, this turn)
    # Suspended by a channeled `exile` (GDD §8): off the board (not targetable, can't
    # act, doesn't block victory) but still alive — it returns when the channel breaks.
    # A spell's exile removes the enemy outright instead, so this stays False there.
    exiled: bool = False

    # Mirror the character's HP model so one damage routine serves both. An enemy's
    # `power_bonus` adjusts its declared intent damage (so a wound blunts its attack).
    temp_mod: int = 0
    prevent_pool: int = 0
    prevent_tags: List[str] = field(default_factory=list)
    protection: int = 0
    power_bonus: int = 0
    keywords: Dict[str, str] = field(default_factory=dict)

    @property
    def effective_hp(self) -> int:
        return self.hp + self.temp_mod

    @property
    def alive(self) -> bool:
        return self.effective_hp > 0

    @property
    def current_power(self) -> int:
        return max(0, self.power + self.power_bonus)


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
    # Per-site targets for independent multi-target cards (see Action.targets);
    # ordered by target site, with targets[0] == target_id. Empty otherwise.
    targets: Tuple[str, ...] = ()
    card_id: Optional[str] = None
    card: Optional[Card] = None
    reserved: List[str] = field(default_factory=list)
    uid: int = 0            # unique stack id (so a counter can name the action it answers)
    mode: Optional[int] = None  # chosen modal mode index (None for a non-modal cast)
    cast_mode: str = "action"   # "action" (proactive) | "reaction" (cast into a window)
    attack_mode: Optional[str] = None  # melee | ranged, for an attack action (R-1)
    # A declared Mitigate on this attack (Update 02 §M-A): `mitigate_by` is the
    # mitigator's id, `mitigate_for` the protected character (== mitigate_by for self
    # mode, an ally's id for interception). Applied per hit at resolution.
    mitigate_by: Optional[str] = None
    mitigate_for: Optional[str] = None


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
    mode: Optional[int] = None   # chosen modal mode index, for a modal cast
    # Per-site targets for a card whose effects target independently (e.g. Agony
    # Warp). Ordered by target site; targets[0] mirrors target_id (the primary).
    # Empty for single-target cards, which use target_id alone.
    targets: Tuple[str, ...] = ()
    choice: Optional[int] = None  # picked candidate handle, for a choose_card action
    label: str = ""

    def key(self) -> tuple:
        """Identity used to match a chosen action against the legal set."""
        return (self.kind, self.actor_id, self.card_id, self.target_id,
                self.color, self.mode, self.targets, self.choice)


@dataclass
class Event:
    """One entry in the structured log — the narrator's (future) input and what
    the tests and the text UI read. `data` carries machine-checkable fields."""

    type: str
    msg: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingChoice:
    """A mid-resolution prompt: the chooser must pick which card(s) a move_card
    effect moves. Set on the GameState to pause the flow (like the capacity-colour
    choice); cleared once `need` picks are made, then resolution of `remaining`
    (the stack item's not-yet-resolved top-level effects) resumes.

    `candidates` holds live references to the same Card objects that sit in the
    chooser's zones — `copy.deepcopy(state)` preserves that sharing via its memo,
    so a picked card is removed from the right zone by identity."""

    chooser_id: str
    effect: "Effect"                     # the move_card effect being resolved
    candidates: List["Card"]             # the cards the chooser may pick from
    need: int                            # cards still to move
    remaining: List["Effect"]            # effects to resolve after this move completes
    item: "StackItem"                    # the originating stack item (to resume on)


@dataclass
class GameState:
    party: List[CharacterState]
    enemies: List[EnemyState]
    tokens: List[TokenState] = field(default_factory=list)
    token_defs: Dict[str, Any] = field(default_factory=dict)  # token_id -> stats
    token_seq: int = 0                # for unique created-token ids
    stack_seq: int = 0                # for unique StackItem.uid
    # Randomness (opt-in): when a scenario is built with a seed the library is
    # shuffled at setup and stays shuffled; `rng_seed` (+ a bump per shuffle effect)
    # makes any in-game shuffle reproducible. None == the deterministic fixed order.
    rng_seed: Optional[int] = None
    shuffle_count: int = 0            # bumped each time a shuffle effect re-randomises a library
    pending_ramp: List[Dict[str, Any]] = field(default_factory=list)  # deferred capacity, applied at begin_turn
    turn: int = 1
    phase: str = "upkeep"             # upkeep|capacity|draw|intents|player|allies|enemy|end
    stack: List[StackItem] = field(default_factory=list)
    priority: Optional[str] = None    # party member who must decide now
    passes: int = 0                   # consecutive passes in the open window
    acted_enemies: List[str] = field(default_factory=list)
    acted_tokens: List[str] = field(default_factory=list)
    pending_break: List[str] = field(default_factory=list)  # channelers owed a break
    pending_choice: Optional["PendingChoice"] = None  # mid-resolution card-move choice
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
        # Channel-exiled enemies are alive but out of play: not targetable, can't act,
        # and don't count toward "are there enemies left" (so the encounter can end
        # while one is suspended — it is then permanently exiled).
        return [e for e in self.enemies if e.alive and not e.exiled]

    def living_tokens(self) -> List[TokenState]:
        return [t for t in self.tokens if t.alive]
