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
# Prevention shields (R-11 `prevent [parameter]`)
# --------------------------------------------------------------------------- #
@dataclass
class Affliction:
    """One active poison or regen EFFECT riding a creature (Design Update 08 §D8-2).

    The effect is the ticking process; the counters it has placed live on the
    creature's `poison_counters` / `regen_counters` tallies (stats already folded
    in as each counter lands). `turns_left` is the optional authored bound (None =
    until concluded by rule); `pending` marks an infect-applied poison whose FIRST
    counter lands at the next Upkeep rather than on application (§D8-2.5).
    `source_id` is the combatant that applied it — regen ticks credit the applier's
    ultimate gauge (§D8-3.3)."""

    amount: int = 1
    turns_left: Optional[int] = None
    pending: bool = False
    source_id: Optional[str] = None


@dataclass
class AmplifyTag:
    """A one-shot `amplify` priming riding a combatant: their NEXT outgoing
    damage (or heal) matching `event` is `multiplier ×` the amount plus `bonus`.
    Spent by the first matching instance; holds until spent (no end-step wipe —
    a primed combo keeps until it lands)."""

    event: str = "any_damage"   # combat_damage | spell_damage | any_damage | heal
    multiplier: int = 1
    bonus: int = 0


@dataclass
class PreventTag:
    """A `prevent [parameter]` shield riding on one combatant.

    `uses=None` nullifies EVERY matching thing until the tag's duration ends —
    Fog's "prevent all combat damage this turn", or a channeled `prevent attack`
    (Pacifism) that keeps a creature from attacking for as long as it is held. A
    positive `uses` is a one-shot (or N-shot) shield consumed as matches occur —
    Gods Willing's "prevent the next combat damage". Both are wiped at the End
    step; a `while_channeled` tag is re-asserted each turn while the channel holds.
    """

    parameter: str
    uses: Optional[int] = None


# --------------------------------------------------------------------------- #
# Encounter objectives (Design Update 12 §D12-1)
# --------------------------------------------------------------------------- #
@dataclass
class Objective:
    """The encounter's optional objective (§D12-1) — engine-owned state, fully
    public. `rounds_done` counts completed End Steps (the timer tick). Wave and
    reinforcement rosters are CONCRETE enemy ids (resolved at build time); the
    referenced enemies wait in the reserve zone (`EnemyState.reserve`) until
    deployed. `status` tracks the race clock only: 'active' → 'complete' (the
    marked enemy defeated in time — the clock vanishes) or 'failed' (expired;
    with fail 'escalate' the fight continues under standard victory)."""

    kind: str                     # "survive" | "waves" | "race"
    turns: int = 0                # survive/race clock length, in rounds
    rounds_done: int = 0          # End Steps completed (ticks at each)
    status: str = "active"        # active | complete | failed  (race clock)
    # survive: scheduled arrivals — [{"turn": k, "ids": [...], "arrived": bool}]
    reinforcements: List[Dict[str, Any]] = field(default_factory=list)
    # waves: the later waves' enemy ids (top-level layouts are wave 1)
    waves: List[List[str]] = field(default_factory=list)
    wave_index: int = 0           # how many LATER waves have deployed
    # race: the marked enemy and the failure shape
    target_id: Optional[str] = None
    fail: str = "escalate"        # "defeat" | "escalate"
    escalation_telegraph: str = ""
    escalation_verbs: List[Effect] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Channels (held channeled enchantments, GDD §8)
# --------------------------------------------------------------------------- #
@dataclass
class EnemyChannel:
    """An enemy's held channel (GDD §8 mirrored onto the enemy side).

    Enemies have no cards or mana, so the channel is anchored to the COMPONENT
    that started it: its continuous verbs stay applied and its `trigger: upkeep`
    verbs recur until the channel breaks. Break causes: the channeler takes one
    hit of ≥25% max HP, dies, is bounced, or is suspended — plus normal stack
    interaction at cast time (the channel enters play as a counterable action).
    `name` is the component telegraph — the player-facing "what this is doing"."""

    component_id: str
    name: str
    effects: List[Effect] = field(default_factory=list)
    holder_id: str = ""
    target_id: Optional[str] = None
    started_turn: int = 0
    # Row/blast splash victims pinned at first apply (see Channel.splash_ids).
    splash_ids: List[str] = field(default_factory=list)


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
    # The turn this channel was started (display/log bookkeeping). Voluntary drops
    # are instant-speed and unrestricted — legal whenever the holder has priority,
    # even the cast turn (Update 06 playtest ruling; supersedes GDD §8's same-turn
    # hold rule).
    started_turn: int = 0
    # The X chosen at cast (0 for a non-X card) — read by `x`/`casting_cost`
    # value references on the channel's triggered effects.
    x: int = 0
    # Row/blast splash victims (§D9-3.2) pinned when the channel's continuous
    # effect first applied around its pick: the SAME creatures must be covered
    # for the channel's whole life — reasserted each end step and lifted when
    # it ends — even if they moved rows (or are suspended) meanwhile.
    splash_ids: List[str] = field(default_factory=list)


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
    # Position (Design Update 15 §L-1): the single live row. Moves resolve live —
    # action-bound moves (melee lunge, ally-Mitigate dash) write it as the action
    # hits the stack; a voluntary Move writes it when its stack item resolves.
    # Everything (reach, Mitigate adjacency, the wall, intents) reads this value.
    row: str = "front"

    # Unified HP model (Design Update R-7): damage reduces `hp` directly; `temp_mod`
    # is the net of end-of-turn pump (+) / wound (−) modifiers and expires at End.
    # Lethality is checked on effective_hp = hp + temp_mod.
    temp_mod: int = 0
    prevent_pool: int = 0     # numeric pre-damage reduction (R-11 numeric prevent)
    prevent_tags: List[PreventTag] = field(default_factory=list)  # shields (R-11 prevent)
    # Combo primings: one-shot outgoing-damage/heal multipliers (`amplify`) and
    # "next action resolves twice" tags (`double_next` — a list of filter nodes).
    amplify_tags: List[AmplifyTag] = field(default_factory=list)
    double_next: List[str] = field(default_factory=list)
    # The last blow that CONNECTED with this combatant (post-prevention soak+HP),
    # read by the `*_last_damage` value refs. 0 until first hit.
    last_damage_taken: int = 0
    power_bonus: int = 0      # temporary Power (pump +, wound −)
    protection: int = 0       # negates the next N spells/attacks (protection)
    # Granted keyword statics: {keyword: duration}. Duration drives expiry at the
    # end step (this_turn) or channel break (while_channeled); 'encounter'
    # / 'permanent' persist. The engine reads these for keyword behaviour (GDD §7).
    keywords: Dict[str, str] = field(default_factory=dict)
    # Total +1/+1 counters received. The stat change is already folded into
    # `power`/`max_hp` when granted (_r_counters); this tally exists so the UI
    # can show counters as a distinct, permanent thing.
    counters: int = 0
    # Typed counters (D8-2): active poison/regen effects (the ticking processes)
    # and the counters they have placed (stats folded in as each lands; the
    # tallies exist for display and 1:1 annihilation).
    poison_effects: List[Affliction] = field(default_factory=list)
    regen_effects: List[Affliction] = field(default_factory=list)
    poison_counters: int = 0
    regen_counters: int = 0

    # Heroic actions (D8-3): the authored once-per-encounter Skill/Ultimate (core
    # Card models with forced timing), their used flags, the public 0–100 ultimate
    # gauge, and optional display flavour for the evergreen abilities.
    skill: Optional[Card] = None
    ultimate: Optional[Card] = None
    skill_used: bool = False
    ultimate_used: bool = False
    ultimate_gauge: int = 0
    ability_flavor: Dict[str, Any] = field(default_factory=dict)
    # +25-on-ally-downed bookkeeping: set when this character's downing has been
    # credited to the rest of the party, cleared when they stand back up.
    down_credited: bool = False

    # Per-round / per-turn flags (reset at upkeep).
    used_attack: bool = False
    used_defend: bool = False
    used_mitigate: bool = False
    used_move: bool = False  # a stance-replaced Move spent this turn (§D9-2.3)
    acted_mode: Optional[str] = None  # None | "attack" | "cast" | "defend" | "move" this turn
    turn_ended: bool = False
    capacity_chosen: bool = False  # locked this turn's +1 capacity colour yet?
    # Spells cast this turn (reset at upkeep) — read by `spells_cast` conditions.
    spells_cast_turn: int = 0

    # Enemy Debilitate effects on players (Design Update 04 §F-3 "stun / taunt-us").
    # `stunned` = whole turns whose proactive window is denied (decremented as each
    # stunned turn ends); `taunted_to` = the enemy id this character's basic attacks
    # must target while it lives (cleared at upkeep — a this-turn effect).
    stunned: int = 0
    taunted_to: Optional[str] = None

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
class Corpse:
    """The battlefield remains of a dead non-token enemy (Design Update 09 §D9-1).

    An OBJECT, not a creature: it has an identity and a row but no HP and never
    acts. Creature-facing effects cannot resolve on it — only the corpse-legal
    verbs (`control` raises it, `exile` burns it) touch it. `stirring` > 0 marks
    a `rises` corpse: the enemy is NOT defeated and revives in that many Upkeeps
    unless the corpse is exiled or raised first (§D9-1.5). `body` keeps the dead
    EnemyState so a rise (or the inspector) has the full record. Boss corpses are
    inert to `control`, absolutely (§D9-1.4)."""

    id: str
    name: str
    row: str
    power: int
    max_hp: int
    level: int
    attack_mode: str = "melee"
    is_boss: bool = False
    stirring: int = 0
    body: Optional["EnemyState"] = None


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
    # Control bookkeeping (§D9-1.4): a controlled combatant is a party-side token.
    # `controlled_by` is the caster; `control_left` counts End Steps until control
    # ends (None == the encounter). `revert` holds the living enemy that returns
    # when MIND CONTROL ends; a raised undead has revert None and simply crumbles.
    controlled_by: Optional[str] = None
    control_left: Optional[int] = None
    revert: Optional["EnemyState"] = None
    temp_mod: int = 0
    prevent_pool: int = 0
    prevent_tags: List[PreventTag] = field(default_factory=list)
    amplify_tags: List[AmplifyTag] = field(default_factory=list)  # combo primings
    double_next: List[str] = field(default_factory=list)
    last_damage_taken: int = 0
    protection: int = 0
    power_bonus: int = 0  # temporary Power (pump +, wound −) — tokens can be anthemed
    keywords: Dict[str, str] = field(default_factory=dict)
    counters: int = 0  # total +1/+1 counters (stats already folded in; see CharacterState)
    poison_effects: List[Affliction] = field(default_factory=list)  # typed counters (D8-2)
    regen_effects: List[Affliction] = field(default_factory=list)
    poison_counters: int = 0
    regen_counters: int = 0

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
    """An enemy's declared next action (the pre-stack form, GDD §5.2).

    A plain attack still fills `effects` with a DealDamage; a component-declared
    intent carries that component's verbs. `kind` distinguishes a normal action from
    a Move (Design Update 04 §F-7.3), whose "target" is the destination row.
    `source_component` is the id of the component that declared it, so the engine can
    start that component's cooldown when the intent executes."""

    name: str               # e.g. "Claw"
    action_type: str        # "ability" / "spell" / "attack"
    effects: List[Effect]   # core effect primitives this intent will resolve
    target_id: Optional[str]  # combatant the intent points at (resolved at declare)
    kind: str = "action"    # "action" | "move" (Move declares a destination row)
    move_to: Optional[str] = None  # destination row for a Move intent (§F-7.3)
    # The attack mode this intent was declared with (melee | ranged), for a basic
    # attack — read by the §L-3 re-check (only melee intents redirect). None for
    # component telegraphs / Moves.
    attack_mode: Optional[str] = None
    # A POSITIONAL intent (§L-5): aimed at a row, not a combatant. `target_id` is
    # None; occupancy is read at resolution, so vacating the row dodges it.
    target_row: Optional[str] = None
    source_component: Optional[str] = None  # component that declared it (cooldown bookkeeping)
    # The basic attack's BASE Power (pre-bonus), for a default-attack intent. The
    # damage it actually deals is `max(0, attack_power + enemy.power_bonus)`, computed
    # live — so a wound (or anthem) landing AFTER declaration blunts/boosts the swing
    # (R-7). None for component telegraphs / Moves, which carry their own amounts.
    attack_power: Optional[int] = None

    def attack_damage(self, power_bonus: int = 0) -> Optional[int]:
        """Live attack damage: the base attack Power adjusted by the enemy's CURRENT
        power_bonus. Falls back to the telegraphed effect amount for a non-attack
        (component) intent that carries no `attack_power`."""
        if self.attack_power is None:
            return self.display_amount()
        return max(0, self.attack_power + power_bonus)

    def display_amount(self) -> Optional[int]:
        """The damage number to show beside an attack intent (the basic attack's Power),
        or None for a component telegraph / Move, whose text already describes itself.
        Non-damage verbs (create_token, heal, …) carry no `amount`, so this never assumes
        one is present."""
        if self.action_type != "attack":
            return None
        for e in self.effects:
            amt = getattr(e, "amount", None)
            if isinstance(amt, int):
                return amt
        return None


@dataclass
class Component:
    """One instantiated enemy behavior (Design Update 04 §F-3): the "mind" is a blend
    of these. Each contributes one rule to the enemy's merged priority list, evaluated
    first-match-wins in a proactive pass (intent declaration) and reactive passes
    (trigger windows). The engine adds no resolution logic — `verbs` are ordinary §11
    primitives that resolve through the same handlers a card uses.

    `condition` is an optional gate read at evaluation time; its shape is a small dict
    the engine understands, e.g. {"kind": "self_hp_pct", "op": "<", "value": 50} or
    {"kind": "turn", "op": ">=", "value": 3} or {"kind": "ally_count", "op": "<",
    "value": 2}. `cooldown` is whole turns between uses (0/1 = every turn); a component
    that is `once_per_encounter` fires a single time. `id` names the component for
    cooldown bookkeeping (unique within an enemy)."""

    id: str                              # unique within the enemy (cooldown key)
    archetype: str = ""                  # Burst | Evasive | Drain | ... (authoring/label)
    timing: str = "proactive"            # "proactive" | "reactive" (§F-3)
    trigger: Optional[str] = None        # reactive only — from the §F-3.2 vocabulary
    # D8-2.4: an `on_charge_full` reactive fires the moment the enemy's charge
    # reaches this threshold (going on the stack; charge resets as it is pushed).
    charge_threshold: Optional[int] = None
    condition: Optional[Dict[str, Any]] = None  # optional eligibility gate
    cooldown: int = 0                    # whole turns between uses (§F-3.1)
    once_per_encounter: bool = False
    priority: int = 90                   # lower = evaluated first (§F-7.1)
    verbs: List[Effect] = field(default_factory=list)   # §11 primitives this rule runs
    target_rule: str = "valuation"       # self | lowest_hp_ally | valuation | channeling_player | ...
    telegraph: str = ""                  # intent text shown in the Intents list (proactive)
    move_home: bool = False              # a repositioning rule (Evasive/§F-7.3) declares a Move
    # A positional component (§L-5): its intent aims at this ROW, not a combatant
    # (no target pick, taunt ignored, declares even into an empty row). Its verbs
    # should carry row-scoped targets ({"mode": "all", "side": "ally", "rows":
    # [<row>]}) so resolution reads occupancy live. action_type "attack" makes the
    # swipe Mitigate-answerable.
    target_row: Optional[str] = None
    # Boss phase gate (§F-9): None = always; "pre_enrage" = only before the boss
    # enrages; "post_enrage" = only after. Meaningless (ignored) on non-bosses.
    phase: Optional[str] = None
    # GDD action-taxonomy class for what this component puts on the stack.
    # Enemies have no cards, so "spell" is THEMATIC: Fireball/Meteor/Psionic
    # Lance are spells (answered by spell counters like Negate); Life Leech /
    # Sparkbomb / Spore Fog stay abilities. Proactive: "ability" (default) or
    # "spell". Reactive components land as "triggered" unless flagged "spell".
    action_type: str = "ability"
    # A channelled component (§8, enemy side): resolving its intent doesn't run
    # the verbs once — it starts an EnemyChannel. Continuous verbs
    # (duration while_channeled) hold; `trigger: upkeep` verbs recur each turn;
    # anything else fires once as the channel starts.
    channel: bool = False


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
    # Position (Design Update 15 §L-1 / §L-2.3): the single live row — a Move
    # intent relocates the body when it executes in the Enemy step. `home_row`
    # is the spawn/redeploy row its Move behavior regresses toward.
    home_row: str = "front"
    intent: Optional[Intent] = None
    # Boss fury (§D9-4): after enrage a boss declares TWO intents per round; the
    # second sits here and executes right after the first, in declaration order.
    # Always None for non-bosses and pre-enrage.
    intent2: Optional[Intent] = None
    # The "mind" (Design Update 04 §F-3): a blend of components merged into one priority
    # list. Empty == the legacy single-template enemy (the default Attack rule only), so
    # existing content runs unchanged. `cooldowns` maps component id → the turn number it
    # is next usable (a fired component sets this to turn + cooldown; once_per_encounter
    # parks it forever).
    components: List["Component"] = field(default_factory=list)
    cooldowns: Dict[str, int] = field(default_factory=dict)
    is_boss: bool = False       # §F-9: removal-immune outside the execute window; enrages ≤25%
    enraged: bool = False       # one-way: set the first time a boss falls to ≤25% max HP
    created_by: Optional[str] = None  # the enemy that spawned this token (§F-4 per-creator cap)
    # The `rises` trait (§D9-1.5): on death the corpse STIRS and the enemy revives
    # after this many Upkeeps at half max HP (T-52), once per encounter. Cleared
    # as the corpse is created so the risen enemy stays down the second time.
    rises: Optional[int] = None
    intent_template: Dict[str, Any] = field(default_factory=dict)
    # An optional weaker ranged attack (R-1 heuristics): the enemy falls back to it
    # when its melee attack can't reach the target the heuristic wants. Same shape as
    # `intent_template` (name/amount/action_type); empty == melee-only.
    ranged_template: Dict[str, Any] = field(default_factory=dict)
    stunned: int = 0           # intents to skip (stun); decremented as they would declare
    taunted_by: Optional[str] = None  # forced to target this character id (taunt, this turn)
    # Held channels (§8 enemy side): started by channel-components, broken by a
    # ≥25%-max-HP hit, death, bounce, or suspension. See EnemyChannel.
    channels: List[EnemyChannel] = field(default_factory=list)
    # Suspended by a channeled `exile` (GDD §8): off the board (not targetable, can't
    # act, doesn't block victory) but still alive — it returns when the channel breaks.
    # A spell's exile removes the enemy outright instead, so this stays False there.
    exiled: bool = False
    # Bounced to the "in hand" zone (Design Update 03 §E-C): off the battlefield (not
    # targetable, occupies no row, declares nothing) but still on the roster, so it
    # does NOT satisfy victory — it redeploys at the start of its next turn. Distinct
    # from `exiled`, which counts as defeated. HP is retained across the bounce.
    in_hand: bool = False
    # The RESERVE zone (§D12-1): an undeployed wave / reinforcement enemy — off
    # the battlefield, untargetable, NOT defeated. Blocks the standard all-
    # defeated victory (the timer victory of `survive` overrides it). Cleared
    # when the objective deploys the enemy at the Enemy Intents step.
    reserve: bool = False

    # Mirror the character's HP model so one damage routine serves both. An enemy's
    # `power_bonus` adjusts its declared intent damage (so a wound blunts its attack).
    temp_mod: int = 0
    prevent_pool: int = 0
    prevent_tags: List[PreventTag] = field(default_factory=list)
    amplify_tags: List[AmplifyTag] = field(default_factory=list)  # combo primings
    double_next: List[str] = field(default_factory=list)
    last_damage_taken: int = 0
    protection: int = 0
    power_bonus: int = 0
    keywords: Dict[str, str] = field(default_factory=dict)
    counters: int = 0  # total +1/+1 counters (stats already folded in; see CharacterState)
    poison_effects: List[Affliction] = field(default_factory=list)  # typed counters (D8-2)
    regen_effects: List[Affliction] = field(default_factory=list)
    poison_counters: int = 0
    regen_counters: int = 0
    # Charge (D8-2.4): the visible windup gauge the `charge` verb fills. The count
    # is public; what it feeds (the on_charge_full component) is hidden until it fires.
    charge: int = 0

    # Veiled-intents bookkeeping (D8-1.5): this round's declared intent, kept after
    # it leaves `intent` so the intents window can strike the line and — for a
    # strip — show the reveal. Status: none|declared|stripped|stunned|executed|fizzled.
    round_intent: Optional["Intent"] = None
    round_intent_status: str = "none"
    round_intent_reveal: str = ""
    # The second veiled line for an enraged boss (§D9-4) — same lifecycle as the
    # first-slot fields above.
    round_intent2: Optional["Intent"] = None
    round_intent2_status: str = "none"
    round_intent2_reveal: str = ""

    @property
    def effective_hp(self) -> int:
        return self.hp + self.temp_mod

    @property
    def alive(self) -> bool:
        return self.effective_hp > 0

    @property
    def current_power(self) -> int:
        return max(0, self.power + self.power_bonus)

    @property
    def in_execute_window(self) -> bool:
        """§9.4 / §F-9: a boss at ≤25% max HP can finally be removed (destroy /
        exile / bounce / deathtouch). Always True for non-bosses (no immunity)."""
        if not self.is_boss:
            return True
        return self.effective_hp * 4 <= self.max_hp


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
    # An enemy channel-component's intent: resolving it STARTS an EnemyChannel
    # (it doesn't run the verbs once). Countering it on the stack stops the
    # channel from ever existing — normal stack interaction.
    starts_channel: bool = False
    component_id: Optional[str] = None
    mode: Optional[int] = None  # chosen modal mode index (None for a non-modal cast)
    cast_mode: str = "action"   # "action" (proactive) | "reaction" (cast into a window)
    x: int = 0                  # the X chosen at cast (0 for a non-X card)
    attack_mode: Optional[str] = None  # melee | ranged, for an attack action (R-1)
    # A positional intent's row (§L-5): the item strikes every character standing
    # in this row when it RESOLVES (target_id stays None). Read by Mitigate
    # legality (a struck character may answer) and the whiff log.
    target_row: Optional[str] = None
    # Base (pre-bonus) Power of a basic attack. The damage it deals is recomputed at
    # RESOLUTION as max(0, attack_power + source.power_bonus) — so a wound/anthem landing
    # while the swing sits on the stack changes what lands (R-7). None for spells/abilities.
    attack_power: Optional[int] = None
    # A declared Mitigate on this attack (Update 02 §M-A): `mitigate_by` is the
    # mitigator's id, `mitigate_for` the protected character (== mitigate_by for self
    # mode, an ally's id for interception). Applied per hit at resolution.
    mitigate_by: Optional[str] = None
    mitigate_for: Optional[str] = None
    # A COPY on the stack (copy_spell / a double_next echo): resolves normally but
    # never consumes another double_next tag (no infinite echo chains).
    is_copy: bool = False
    # A hero Ultimate on the stack (§D12-2.2): the `on_ultimate_cast` trigger's
    # read. Kind stays "activated" (the GDD taxonomy is unchanged).
    is_ultimate: bool = False
    # A pushed triggered ability (channel_break) whose chosen target / modal mode
    # has not been picked yet: the holder picks as it goes on the stack
    # (MTG-style), before the reaction window opens — mode first (it decides which
    # effects resolve, and so which targets are needed), then target. See
    # engine._raise_next_trigger_pick. Cleared by the picks.
    needs_target: bool = False
    needs_mode: bool = False


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
    # Explicit mana payment for a cast (the exact colours to spend). None == let the
    # engine pay deterministically (WUBRG order). Not part of `key()`: the payment is
    # a settlement detail, not the action's identity, so legality still matches the
    # engine's offered cast. The engine re-validates it covers the cost at apply time.
    mana: Optional[List[str]] = None
    # X chosen for an {X}-cost cast. Part of the action's identity: the engine
    # offers one cast per affordable X value.
    x: Optional[int] = None
    # Marked by the game server's smart auto-pass (D8-4): a synthetic pass/end
    # submitted because the holder had no meaningful option. Presentation only —
    # not part of the action's identity; the log annotates it "(auto)".
    auto: bool = False
    label: str = ""

    def key(self) -> tuple:
        """Identity used to match a chosen action against the legal set."""
        return (self.kind, self.actor_id, self.card_id, self.target_id,
                self.color, self.mode, self.targets, self.choice, self.x)


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
    effect moves, or (for a scry) where each revealed card goes. Set on the
    GameState to pause the flow (like the capacity-colour choice); cleared once the
    picks are made, then resolution of `remaining` (the stack item's not-yet-resolved
    top-level effects) resumes.

    `candidates` holds live references to the same Card objects that sit in the
    chooser's zones — `copy.deepcopy(state)` preserves that sharing via its memo,
    so a picked card is removed from the right zone by identity.

    For a scry (`kind == "scry"`) the chooser assigns each of the `looked` revealed
    top cards to either `top` (in pick order — the first chosen is drawn first) or
    `bottom`; the choice is complete once `candidates` is empty.

    For a trigger-time target pick (`kind == "target"`, a channel_break ability
    just pushed with `needs_target`): the chooser names the creature the triggered
    ability aims at; `effect` is the chosen-target effect (for side/labels),
    `candidates`/`need`/`remaining` are unused.

    For a mode pick on a triggered modal (`kind == "mode"`): `effect` is the modal.
    With `resolve_now` False the pick binds `item.mode` as the trigger goes on the
    stack (channel_break); True means the modal is firing right now (channel_start)
    — the chosen mode resolves immediately and `remaining` then resumes."""

    chooser_id: str
    effect: "Effect"                     # the move_card / scry / chosen-target / modal effect
    candidates: List["Card"]             # the cards the chooser may pick from
    need: int                            # cards still to move (move_card)
    remaining: List["Effect"]            # effects to resolve after this choice completes
    item: "StackItem"                    # the originating stack item (to resume on)
    kind: str = "move"                   # "move" (move_card) | "scry" | "target" | "mode"
    resolve_now: bool = False            # mode pick: resolve the chosen mode immediately
    # Scry accumulators (kind == "scry"): the revealed cards the chooser has so far
    # sent to the top / bottom of the library, in pick order.
    top: List["Card"] = field(default_factory=list)
    bottom: List["Card"] = field(default_factory=list)
    looked: int = 0                      # how many top cards were revealed (scry X)


@dataclass
class GameState:
    party: List[CharacterState]
    enemies: List[EnemyState]
    # Fixed party TURN ORDER (character ids): randomized once at encounter setup
    # (when the scenario is built with a seed) and constant for the whole fight —
    # repositioning never reshuffles it. Drives whose main phase comes next and
    # the pass-around order in reaction windows. Empty == the authored party order
    # (legacy states / tests built without the field).
    party_order: List[str] = field(default_factory=list)
    tokens: List[TokenState] = field(default_factory=list)
    # The dead on the battlefield (§D9-1): corpses of non-token enemies. Defeated
    # for victory purposes (a STIRRING corpse is not); consumed by `control`,
    # burned by `exile`, fed on by enemy necromancy.
    corpses: List[Corpse] = field(default_factory=list)
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
    # Enemies that have already fired a reaction in the CURRENT reaction window (Design
    # Update 04 §F-3.3: at most one reaction per enemy per window). Reset whenever a
    # fresh window opens; cross-turn reuse is gated separately by per-component cooldowns.
    reacted_window: List[str] = field(default_factory=list)
    pending_break: List[str] = field(default_factory=list)  # channelers owed a break
    pending_choice: Optional["PendingChoice"] = None  # mid-resolution card-move choice
    # Re-entrancy depth for event-triggered channel effects (an on-draw draw, an
    # on-damage hit, …). Capped so trigger-fires-trigger chains always terminate.
    event_depth: int = 0
    # The encounter's optional objective (§D12-1). None == the standard game,
    # byte-identical to an objective-less encounter.
    objective: Optional["Objective"] = None
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
        # The enemies "in play" (Update 03 §E-A): on the battlefield, targetable, and
        # acting. Channel-exiled enemies are alive but out of play (suspended),
        # bounced enemies are alive but "in hand" (off the field, pending redeploy),
        # and reserve-zone enemies (§D12-1) await their wave/reinforcement deploy;
        # all are excluded here. Defeated enemies (graveyard/exile) leave the list.
        return [e for e in self.enemies
                if e.alive and not e.exiled and not e.in_hand and not e.reserve]

    def bounced_enemies(self) -> List[EnemyState]:
        """Roster enemies currently in the in-hand zone (bounced, pending redeploy).
        They keep the encounter live — victory requires every enemy gone for good."""
        return [e for e in self.enemies if e.in_hand]

    def reserve_enemies(self) -> List[EnemyState]:
        """Undeployed wave/reinforcement enemies in the reserve zone (§D12-1):
        off the battlefield, untargetable, not defeated — they block the
        standard victory (the `survive` timer victory overrides)."""
        return [e for e in self.enemies if e.reserve]

    def living_tokens(self) -> List[TokenState]:
        return [t for t in self.tokens if t.alive]

    def corpse(self, cid: str) -> Optional[Corpse]:
        """The corpse with this id, if it still lies on the battlefield (§D9-1)."""
        return next((c for c in self.corpses if c.id == cid), None)

    def stirring_corpses(self) -> List[Corpse]:
        """Corpses under a `rises` trait, not yet risen: NOT defeated (§D9-1.5)."""
        return [c for c in self.corpses if c.stirring > 0]

    def controlled_units(self) -> List[TokenState]:
        """Party-side combatants under a `control` effect (§D9-1.4): dominated
        living enemies (revert set) and raised undead (revert None)."""
        return [t for t in self.tokens if t.controlled_by is not None]
