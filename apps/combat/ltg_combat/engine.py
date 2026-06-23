"""The pure combat engine — the whole contract is two functions.

    legal_actions(state) -> [Action]
        The active player-character's legal choices *right now* (proactive on its
        turn; react/pass during a reaction window; always a pass/end option).

    apply_action(state, action) -> (state', events)
        The resulting state plus the events emitted. Deterministic; no I/O, no
        presentation, no LLM. Between player decision points it auto-runs the
        automatic flow (upkeep, enemy intents/execution, end step) and pauses at
        every player-character reaction window.

Both functions are self-bootstrapping: handed the raw setup state they first run
the automatic prelude (the turn-1 upkeep and intent declaration) until the first
real decision, so a client drives the entire fight through these two alone.

Design seams the brief asks for:
  * Effects DECLARE, the resolver DECIDES — `destroy` on a minion resolves as a
    kill here, not in the card (GDD §11). One handler per primitive in RESOLVERS;
    adding a handler is a localized change.
  * Library order is an explicit input (the scenario supplies it); nothing here
    shuffles or randomises. The engine is fully deterministic.
"""

from __future__ import annotations

import copy
import math
from typing import List, Optional, Tuple

from ltg_core.schema import (
    Card,
    DealDamage,
    Duration,
    Ref,
    TargetMode,
    Timing,
    t_chosen,
)

from .state import (
    Action,
    Channel,
    CharacterState,
    EnemyState,
    Event,
    GameState,
    Intent,
    StackItem,
    TokenState,
)

# Spells castable as the proactive Cast action (sorcery-speed). A Cast turn may
# cast several of these if mana allows (GDD §4.6), so they don't end the turn.
_SORCERY_SPEED = (Timing.sorcery, Timing.channeled)

# Deterministic order generic mana is paid from, when a cost has a generic pip.
_PAY_ORDER = ["W", "U", "B", "R", "G"]


# --------------------------------------------------------------------------- #
# Public contract
# --------------------------------------------------------------------------- #
def legal_actions(state: GameState) -> List[Action]:
    """The legal choices for whoever must decide now. Read-only (works on a copy
    so the bootstrap prelude never mutates the caller's state or emits events)."""
    st = copy.deepcopy(state)
    _advance(st)
    if st.result is not None or st.priority is None:
        return []
    return _legal(st)


def settle(state: GameState) -> GameState:
    """A read-only view: advance the automatic flow to the decision-point the
    engine will present next, and return that display-ready copy. Emits nothing
    and never mutates the caller's state. This is the same prelude `legal_actions`
    runs internally — it lets a UI render exactly the state a decision is about
    (e.g. the post-upkeep hand the menu offers), with no rules in the UI."""
    st = copy.deepcopy(state)
    _advance(st)
    st.log = []  # a view carries no new events
    return st


def apply_action(state: GameState, action: Action) -> Tuple[GameState, List[Event]]:
    """Apply `action`, then run forward to the next player decision.

    Returns the new state and just the events this call produced (the full
    history stays on `state.log`)."""
    st = copy.deepcopy(state)
    start = len(st.log)
    _advance(st)  # ensure we are at a decision (bootstraps the opening prelude)

    legal = {a.key() for a in _legal(st)} if st.priority is not None else set()
    if action.key() not in legal:
        raise ValueError(f"illegal action: {action.kind} by {action.actor_id} "
                         f"(card={action.card_id}, target={action.target_id})")

    _apply(st, action)
    _advance(st)  # auto-run the flow up to the next decision
    return st, st.log[start:]


# --------------------------------------------------------------------------- #
# The driver: advance automatic flow until a player must decide
# --------------------------------------------------------------------------- #
def _advance(st: GameState) -> None:
    """Run every automatic step until a player-character decision is required
    (a main-phase action or a reaction-window react/pass) or the game ends."""
    while True:
        _check_end(st)
        if st.result is not None:
            return

        # A non-empty stack means a reaction window is open: a player must
        # react or pass before the top can resolve. Always pause here.
        if st.stack:
            if st.priority is None:
                st.priority = st.living_party()[0].id
                st.passes = 0
            return

        # Stack empty -> walk the turn structure (GDD §4.2).
        if st.phase == "upkeep":
            _begin_turn(st)
            st.phase = "capacity"
        elif st.phase == "capacity":
            # From turn 2 on, capacity rises +1 and the player locks its colour
            # — BEFORE the draw. A single-colour identity needs no choice (auto).
            char = _next_capacity_choice(st)
            if char is None:
                st.phase = "draw"
            else:
                options = _distinct_identity(char)
                if len(options) <= 1:
                    _lock_capacity(st, char, options[0] if options else "C", auto=True)
                else:
                    st.priority = char.id  # pause for the colour choice
                    return
        elif st.phase == "draw":
            _upkeep_draws(st)
            _fire_recurring(st)  # held channels' upkeep engines fire after the draw
            st.phase = "intents"
        elif st.phase == "intents":
            _declare_intents(st)
            st.phase = "player"
        elif st.phase == "player":
            actor = _next_player(st)
            if actor is None:
                st.phase = "allies"
            else:
                st.priority = actor.id  # this character's main phase — pause
                return
        elif st.phase == "allies":
            token = _next_ally(st)
            if token is None:
                st.phase = "enemy"
            else:
                _execute_ally(st, token)  # autonomous ally attacks (pushes to stack)
        elif st.phase == "enemy":
            enemy = _next_enemy(st)
            if enemy is None:
                st.phase = "end"
            else:
                _execute_intent(st, enemy)  # pushes onto the stack (or fizzles)
        elif st.phase == "end":
            _end_step(st)
            _check_end(st)
            if st.result is not None:
                return
            st.turn += 1
            st.phase = "upkeep"


def _next_player(st: GameState) -> Optional[CharacterState]:
    """The next living character (party order) that has not ended its turn."""
    for c in st.party:
        if c.alive and not c.turn_ended:
            return c
    return None


def _next_enemy(st: GameState) -> Optional[EnemyState]:
    """The next living enemy that has not yet executed its intent this turn."""
    for e in st.enemies:
        if e.alive and e.id not in st.acted_enemies:
            return e
    return None


def _next_ally(st: GameState) -> Optional[TokenState]:
    """The next living ally token that has not yet acted this turn."""
    for t in st.tokens:
        if t.alive and t.id not in st.acted_tokens:
            return t
    return None


# --------------------------------------------------------------------------- #
# Turn-structure steps (GDD §4.2)
# --------------------------------------------------------------------------- #
def _begin_turn(st: GameState) -> None:
    """Open the turn: reset enemy/ally action tracking and the capacity flag."""
    st.acted_enemies = []
    st.acted_tokens = []
    _log(st, "turn_start", f"— Turn {st.turn} —", turn=st.turn)
    for c in st.party:
        c.capacity_chosen = False


def _next_capacity_choice(st: GameState) -> Optional[CharacterState]:
    """The next living character that still owes this turn's +1 capacity colour
    (only from turn 2 onward; no increase on turn 1)."""
    if st.turn < 2:
        return None
    for c in st.party:
        if c.alive and not c.capacity_chosen:
            return c
    return None


def _distinct_identity(char: CharacterState) -> List[str]:
    """The colour options for a capacity lock: the character's identity, deduped
    in order (≤3 distinct by construction)."""
    seen: List[str] = []
    for c in char.identity:
        if c not in seen:
            seen.append(c)
    return seen


def _lock_capacity(st: GameState, char: CharacterState, color: str, auto: bool) -> None:
    """Add the +1 colour-locked capacity slot the player (or, for a single-colour
    identity, the engine) chose."""
    char.mana_colors.append(color)
    char.capacity_chosen = True
    how = "auto-locks" if auto else "locks"
    _log(st, "capacity_locked",
         f"{char.name} {how} +1 mana capacity as {color} (capacity {char.capacity}).",
         character=char.id, color=color, capacity=char.capacity, auto=auto)


def _upkeep_draws(st: GameState) -> None:
    """After capacity is set: mana refreshes (channels keep their reserve out of
    the pool), each character draws 1, and per-round uses / turn flags reset."""
    for c in st.living_party():
        c.pool = _refreshed_pool(c)  # every unreserved locked colour spendable
        _draw(st, c, 1)
        c.used_attack = c.used_defend = c.used_parry = False
        c.acted_mode = None
        c.turn_ended = False
        _log(st, "mana_refresh",
             f"{c.name} mana refreshes to {_mana_str(c.pool)} (capacity {c.capacity}, "
             f"reserved {len(c.reserved)}).",
             character=c.id, capacity=c.capacity, pool=list(c.pool),
             reserved=list(c.reserved))


def _refreshed_pool(char: CharacterState) -> List[str]:
    """Capacity minus the colours held channels reserve (reservation doesn't
    refresh; the rest of capacity curves up around it — GDD §4.4, §8)."""
    pool = list(char.mana_colors)
    for color in char.reserved:
        if color in pool:
            pool.remove(color)
    return pool


def _fire_recurring(st: GameState) -> None:
    """Recurring channel effects (`trigger: upkeep`) fire once at the start of
    each holder's turn, in hold order (GDD §8)."""
    for holder in st.living_party():
        for ch in list(holder.channels):
            item = StackItem(kind="ability", source_id=holder.id, source_side="party",
                             label=ch.card.name, effects=[], target_id=ch.target_id,
                             card=ch.card)
            for effect in ch.card.effects:
                if getattr(effect, "trigger", None) == "upkeep":
                    _resolve_effect(st, item, effect, {})


def _declare_intents(st: GameState) -> None:
    """Each enemy declares its telegraphed intent against the current state. A
    disabled intent type (e.g. a `disable`-attack aura) declares nothing."""
    for e in st.living_enemies():
        tmpl = e.intent_template
        itype = tmpl.get("intent_type", "attack")
        if itype in e.disabled_intent_types:
            e.intent = None
            _log(st, "intent_disabled", f"{e.name} is disabled and declares no {itype}.",
                 enemy=e.id, intent_type=itype)
            continue
        target = _intent_target(st, tmpl)
        effects = [DealDamage(amount=tmpl["amount"], target=t_chosen("enemy", targeted=True))]
        e.intent = Intent(name=tmpl["name"], action_type=tmpl.get("action_type", "ability"),
                          effects=effects, target_id=target.id if target else None)
        tname = st.character(e.intent.target_id).name if e.intent.target_id else "—"
        _log(st, "intent_declared",
             f"{e.name} declares {tmpl['name']} ({tmpl['amount']} dmg) → {tname}.",
             enemy=e.id, intent=tmpl["name"], amount=tmpl["amount"], target=e.intent.target_id)


def _intent_target(st: GameState, tmpl: dict) -> Optional[CharacterState]:
    """Resolve an intent's target rule: the lowest-HP party member (default), or
    a fixed character id (e.g. Maul goes for the caster, ignoring tokens)."""
    rule = tmpl.get("targeting", "lowest_hp_party")
    if rule == "lowest_hp_party":
        return _lowest_hp_party(st)
    return st.character(rule)


def _execute_intent(st: GameState, enemy: EnemyState) -> None:
    """Move a declared intent onto the stack as an action (GDD §5.2)."""
    st.acted_enemies.append(enemy.id)
    intent = enemy.intent
    if intent is None or intent.target_id is None:
        return
    st.stack.append(StackItem(kind=intent.action_type, source_id=enemy.id,
                              source_side="enemy", label=intent.name,
                              effects=intent.effects, target_id=intent.target_id))
    enemy.intent = None
    st.priority = None  # open a fresh reaction window (party order, set in _advance)
    st.passes = 0
    _log(st, "intent_execute", f"{enemy.name} executes {intent.name}.",
         enemy=enemy.id, label=intent.name)


def _execute_ally(st: GameState, token: TokenState) -> None:
    """An autonomous ally token attacks the lowest-HP enemy (ties by enemy order),
    opening a reaction window like any other attack."""
    st.acted_tokens.append(token.id)
    target = _lowest_hp_enemy(st)
    if target is None:
        return
    effects = [DealDamage(amount=token.power, target=t_chosen("enemy", targeted=True))]
    st.stack.append(StackItem(kind="attack", source_id=token.id, source_side="party",
                              label=f"{token.name}'s attack", effects=effects,
                              target_id=target.id))
    st.priority = None
    st.passes = 0
    _log(st, "ally_attack", f"{token.name} attacks {target.name} (Power {token.power}).",
         token=token.id, target=target.id, power=token.power)


def _end_step(st: GameState) -> None:
    """End-of-turn effects expire (temporary HP/pumps/prevention fade)."""
    for c in st.party:
        c.temp_hp = 0
        c.power_bonus = 0
        c.prevent_pool = 0
    for e in st.enemies:
        e.temp_hp = 0
        e.prevent_pool = 0
    for t in st.tokens:
        t.temp_hp = 0
        t.prevent_pool = 0
    _log(st, "end_step", "End step: temporary effects expire.")


# --------------------------------------------------------------------------- #
# Applying a chosen action
# --------------------------------------------------------------------------- #
def _apply(st: GameState, action: Action) -> None:
    handler = {
        "pass": _do_pass,
        "end_turn": _do_end_turn,
        "attack": _do_attack,
        "cast": _do_cast,
        "defend": _do_defend,
        "parry": _do_parry,
        "choose_mana": _do_choose_mana,
        "drop_channels": _do_drop_channels,
    }[action.kind]
    handler(st, action)


def _do_choose_mana(st: GameState, action: Action) -> None:
    """Lock the colour of this turn's +1 capacity slot (start of turn, pre-draw)."""
    char = st.character(action.actor_id)
    _lock_capacity(st, char, action.color, auto=False)
    st.priority = None


def _do_pass(st: GameState, action: Action) -> None:
    """Pass priority in the open reaction window. When every living PC has passed
    in succession, the top of the stack resolves (LIFO)."""
    actor = st.character(action.actor_id)
    _log(st, "pass", f"{actor.name} passes.", character=actor.id)
    st.passes += 1
    if st.passes >= len(st.living_party()):
        _resolve_top(st)
        _process_breaks(st)  # a breaking hit just resolved? end channels, release mana
        st.passes = 0
        st.priority = None  # next item (or close) — re-seeded by _advance
    else:
        st.priority = _next_priority_after(st, actor.id)


def _do_end_turn(st: GameState, action: Action) -> None:
    actor = st.character(action.actor_id)
    actor.turn_ended = True
    st.priority = None
    _log(st, "end_turn", f"{actor.name} ends their turn.", character=actor.id)


def _do_attack(st: GameState, action: Action) -> None:
    """The free basic attack (the proactive Attack): deal damage = Power."""
    actor = st.character(action.actor_id)
    actor.acted_mode = "attack"
    actor.used_attack = True
    effects = [DealDamage(amount=actor.current_power, target=t_chosen("enemy", targeted=True))]
    st.stack.append(StackItem(kind="attack", source_id=actor.id, source_side="party",
                              label="Basic Attack", effects=effects, target_id=action.target_id))
    _open_window(st, actor.id, reactive=False)
    tgt = st.combatant(action.target_id)
    _log(st, "attack_declared",
         f"{actor.name} attacks {tgt.name} (Power {actor.current_power}).",
         character=actor.id, target=action.target_id, power=actor.current_power)


def _do_cast(st: GameState, action: Action) -> None:
    """Cast a spell. Sorcery-speed spells (sorceries/channeled) are the proactive
    Cast — a Cast turn may cast several if mana allows; instants are free."""
    actor = st.character(action.actor_id)
    card = _card_in_hand(actor, action.card_id)
    reactive = bool(st.stack)  # a cast made inside an open window stacks above
    paid = _pay(actor, card)
    actor.hand.remove(card)
    if card.timing in _SORCERY_SPEED:
        actor.acted_mode = "cast"  # choosing Cast; further sorcery-speed casts ok
    reserved = list(paid) if card.timing == Timing.channeled else []
    st.stack.append(StackItem(kind="spell", source_id=actor.id, source_side="party",
                              label=card.name, effects=list(card.effects),
                              target_id=action.target_id, card_id=card.id,
                              card=card, reserved=reserved))
    _open_window(st, actor.id, reactive=reactive)
    tgt = st.combatant(action.target_id)
    _log(st, "cast", f"{actor.name} casts {card.name}"
         + (f" on {tgt.name}" if tgt else "") + f". Mana: {_mana_str(actor.pool)}.",
         character=actor.id, card=card.id, target=action.target_id)


def _do_defend(st: GameState, action: Action) -> None:
    """The free defensive action: gain temporary HP. (Magnitude is a placeholder
    until gear/flavour set it; the scenario does not exercise Defend.)"""
    actor = st.character(action.actor_id)
    actor.acted_mode = "defend"
    actor.used_defend = True
    actor.temp_hp += _DEFEND_TEMP_HP
    st.priority = None
    _log(st, "defend", f"{actor.name} defends (+{_DEFEND_TEMP_HP} temp HP).",
         character=actor.id, temp_hp=actor.temp_hp)


def _do_parry(st: GameState, action: Action) -> None:
    """The free defensive reaction: reduce the incoming hit by the character's
    Parry value. Reduction lowers the hit's size (so it can keep a hit under a
    channel-break threshold)."""
    actor = st.character(action.actor_id)
    actor.used_parry = True
    actor.prevent_pool += actor.parry_reduce
    # Parry does not add to the stack; it buffs the defender, then passes.
    _log(st, "parry", f"{actor.name} parries (reduces the incoming hit by {actor.parry_reduce}).",
         character=actor.id)
    _do_pass(st, Action(kind="pass", actor_id=actor.id))


def _do_drop_channels(st: GameState, action: Action) -> None:
    """Voluntary drop (a free action): end all of the holder's channels at once."""
    actor = st.character(action.actor_id)
    _log(st, "drop_channels", f"{actor.name} drops concentration.", character=actor.id)
    _break_channels(st, actor, reason="voluntary")


_DEFEND_TEMP_HP = 3   # placeholder; GDD leaves Defend's amount to gear/flavour


def _open_window(st: GameState, actor_id: str, reactive: bool) -> None:
    """After a player adds to the stack, seed the reaction window. A proactive
    add restarts priority at party order; a reactive add hands off to the next
    player (round-robin) so the active player isn't asked twice in a row."""
    st.passes = 0
    st.priority = _next_priority_after(st, actor_id) if reactive else None


def _next_priority_after(st: GameState, actor_id: str) -> str:
    living = st.living_party()
    ids = [c.id for c in living]
    if actor_id in ids:
        return ids[(ids.index(actor_id) + 1) % len(ids)]
    return ids[0]


# --------------------------------------------------------------------------- #
# Resolving the stack
# --------------------------------------------------------------------------- #
def _resolve_top(st: GameState) -> None:
    item = st.stack.pop()
    _log(st, "resolve", f"{item.label} resolves.", label=item.label, source=item.source_id)
    # A channeled card doesn't run its effects once — it becomes a held channel.
    if item.card is not None and item.card.timing == Timing.channeled:
        _start_channel(st, item)
        return
    ctx: dict = {}  # dynamic references gathered during this resolution
    for effect in item.effects:
        _resolve_effect(st, item, effect, ctx)


# --------------------------------------------------------------------------- #
# Channels: hold, continuous effects, break/release (GDD §8)
# --------------------------------------------------------------------------- #
def _is_continuous(effect) -> bool:
    return (getattr(effect, "trigger", None) is None
            and getattr(effect, "duration", None) == Duration.while_channeled)


def _start_channel(st: GameState, item: StackItem) -> None:
    """Hold a resolved channeled card on its caster: reserve its mana and apply
    its continuous effects. Recurring effects are armed (they fire at upkeep)."""
    holder = st.character(item.source_id)
    channel = Channel(card=item.card, holder_id=holder.id,
                      reserved=list(item.reserved), target_id=item.target_id)
    holder.channels.append(channel)
    _log(st, "channel_start",
         f"{holder.name} channels {item.card.name} (reserves {_mana_str(channel.reserved)}).",
         character=holder.id, card=item.card.id, reserved=list(channel.reserved))
    for effect in item.card.effects:
        if _is_continuous(effect):
            _apply_continuous(st, channel, effect)
    # An aura whose target is already gone ends at once (Layer 1 -> break).
    if channel.target_id is not None and _aura_target_lost(st, channel):
        _note_break(st, holder, "aura_loss")


def _aura_target_lost(st: GameState, channel: Channel) -> bool:
    """True if this channel targets a creature that is no longer a legal target."""
    if channel.target_id is None:
        return False
    needs_target = any(getattr(e, "target", None) is not None and _is_continuous(e)
                       for e in channel.card.effects)
    if not needs_target:
        return False
    tgt = st.combatant(channel.target_id)
    return tgt is None or not getattr(tgt, "alive", False)


def _apply_continuous(st: GameState, channel: Channel, effect) -> None:
    """Apply a `while_channeled` effect when the channel starts."""
    if effect.kind == "disable":
        enemy = st.enemy(channel.target_id)
        if enemy is not None:
            enemy.disabled_intent_types.append(effect.intent_type)
            # Strip a matching intent already declared this turn.
            if (enemy.intent is not None
                    and enemy.intent_template.get("intent_type", "attack") == effect.intent_type):
                enemy.intent = None
            _log(st, "disable_apply",
                 f"{enemy.name} can't {effect.intent_type} while {channel.card.name} holds.",
                 enemy=enemy.id, intent_type=effect.intent_type)
    # Other continuous shapes (anthems/auras) plug in here — localized additions.


def _remove_continuous(st: GameState, channel: Channel, effect) -> None:
    """Lift a `while_channeled` effect when the channel ends."""
    if effect.kind == "disable":
        enemy = st.enemy(channel.target_id)
        if enemy is not None and effect.intent_type in enemy.disabled_intent_types:
            enemy.disabled_intent_types.remove(effect.intent_type)
            _log(st, "disable_lift", f"{enemy.name} is no longer disabled.",
                 enemy=enemy.id, intent_type=effect.intent_type)


def _note_break(st: GameState, char: CharacterState, reason: str) -> None:
    if char.channels and char.id not in st.pending_break:
        st.pending_break.append(char.id)


def _break_threshold(char: CharacterState) -> int:
    """A hit of ≥25% of max HP breaks concentration (round up)."""
    return math.ceil(char.max_hp / 4)


def _process_breaks(st: GameState) -> None:
    """After a resolution, end the channels of any channeler owed a break."""
    for cid in list(st.pending_break):
        st.pending_break.remove(cid)
        char = st.character(cid)
        if char is not None and char.channels:
            _break_channels(st, char, reason="break")


def _break_channels(st: GameState, char: CharacterState, reason: str) -> None:
    """End ALL of a character's channels at once (all-or-nothing): lift continuous
    effects, spend the cards, and release all reserved mana into the pool as a
    respondable stack trigger (GDD §8)."""
    if not char.channels:
        return
    released: List[str] = []
    for channel in char.channels:
        for effect in channel.card.effects:
            if _is_continuous(effect):
                _remove_continuous(st, channel, effect)
        released.extend(channel.reserved)
        _log(st, "channel_end", f"{channel.card.name} ends and is spent.",
             character=char.id, card=channel.card.id, reason=reason)
    char.channels = []
    # Release the reserved mana immediately so it can fund a reaction this window,
    # and put a respondable trigger on the stack (GDD §8).
    char.pool.extend(released)
    st.stack.append(StackItem(kind="ability", source_id=char.id, source_side="party",
                              label="Mana Release", effects=[], target_id=None))
    st.priority = None
    st.passes = 0
    _log(st, "mana_released",
         f"{char.name}'s channels break ({reason}); {_mana_str(released)} released "
         f"(pool now {_mana_str(char.pool)}).",
         character=char.id, released=list(released), reason=reason)


def _resolve_effect(st: GameState, item: StackItem, effect, ctx: dict) -> None:
    handler = RESOLVERS.get(effect.kind)
    if handler is None:
        # Out of scope for this milestone — declared by the schema but not yet
        # given a runtime. Surfaced, never silently dropped.
        _log(st, "unhandled", f"(effect '{effect.kind}' not implemented this milestone)",
             kind=effect.kind)
        return
    target = _resolve_target(st, item, effect)
    # Targeted effects re-check legality at resolution and fizzle (GDD §5.3).
    if _is_targeted(effect) and (target is None or not _legal_target(target)):
        _log(st, "fizzle", f"{item.label}'s {effect.kind} fizzles (no legal target).",
             kind=effect.kind)
        return
    handler(st, item, effect, target, ctx)


def _resolve_target(st: GameState, item: StackItem, effect):
    """The combatant an effect lands on: `self` -> the source, otherwise the
    item's single chosen target."""
    desc = getattr(effect, "target", None)
    if desc is not None and not isinstance(desc, str) and desc.mode == TargetMode.self_:
        return st.combatant(item.source_id)
    return st.combatant(item.target_id)


def _is_targeted(effect) -> bool:
    desc = getattr(effect, "target", None)
    return bool(getattr(desc, "targeted", False))


def _legal_target(target) -> bool:
    return getattr(target, "alive", False)


def _value(amount, ctx: dict) -> int:
    """Resolve an effect value: a constant, or a dynamic reference filled in
    during resolution (e.g. the destroyed target's Level)."""
    if isinstance(amount, Ref):
        if amount.ref == "destroyed_target.level":
            return int(ctx.get("destroyed_target", {}).get("level", 0))
        raise ValueError(f"unsupported value reference '{amount.ref}'")
    if amount == "all":
        raise ValueError("'all' value not supported this milestone")
    return int(amount)


# ---- one handler per effect primitive (the scenario's set) ----------------- #
def _r_deal_damage(st, item, effect, target, ctx):
    _deal_damage(st, target, _value(effect.amount, ctx), source=item.label)


def _r_heal(st, item, effect, target, ctx):
    amount = _value(effect.amount, ctx)
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    _log(st, "heal", f"{target.name} heals {target.hp - before} (HP {target.hp}).",
         target=_tid(target), amount=target.hp - before, hp=target.hp)


def _r_lose_life(st, item, effect, target, ctx):
    # Life loss is not damage: prevention and temp HP do not apply (GDD §4.8/§11).
    amount = _value(effect.amount, ctx)
    target.hp = max(0, target.hp - amount)
    _log(st, "lose_life", f"{target.name} loses {amount} HP (HP {target.hp}).",
         target=_tid(target), amount=amount, hp=target.hp)
    _after_damage(st, target)


def _r_destroy(st, item, effect, target, ctx):
    # `destroy` DECLARES removal; the resolver DECIDES it means a minion kill.
    if isinstance(target, EnemyState):
        ctx["destroyed_target"] = {"level": target.level}
        _log(st, "destroyed", f"{target.name} is destroyed (Level {target.level}).",
             target=target.id, level=target.level)
        _kill_enemy(st, target)


def _r_pump(st, item, effect, target, ctx):
    target.power_bonus = getattr(target, "power_bonus", 0) + effect.power
    target.temp_hp += effect.toughness  # toughness half = temporary HP buffer
    _log(st, "pump", f"{target.name} gets +{effect.power}/+{effect.toughness} "
         f"(temp HP {target.temp_hp}).", target=_tid(target),
         power=effect.power, toughness=effect.toughness)


def _r_prevent(st, item, effect, target, ctx):
    amount = effect.amount if isinstance(effect.amount, int) else 0
    target.prevent_pool += amount
    _log(st, "prevent", f"{target.name} will prevent the next {amount} damage this turn.",
         target=_tid(target), amount=amount)


def _r_draw(st, item, effect, target, ctx):
    _draw(st, target, _value(effect.amount, ctx))


def _r_scry(st, item, effect, target, ctx):
    # Minimal scry: reveal the top card; default-keep (no reorder). The REPL can
    # surface the card; the scenario never casts a scry, so keep-on-top suffices.
    n = _value(effect.amount, ctx)
    top = [c.name for c in target.library[:n]]
    _log(st, "scry", f"{target.name} scries {n}: {', '.join(top) or '(empty)'}.",
         target=_tid(target), amount=n, revealed=top)


def _r_create_token(st, item, effect, target, ctx):
    # Create autonomous ally token(s) from the scenario's token definition.
    tdef = st.token_defs.get(effect.token_id, {})
    for _ in range(effect.count):
        st.token_seq += 1
        token = TokenState(
            id=f"{effect.token_id}_{st.token_seq}",
            name=tdef.get("name", effect.token_id.replace("_", " ").title()),
            max_hp=int(tdef.get("hp", 1)), hp=int(tdef.get("hp", 1)),
            power=int(tdef.get("power", 1)))
        st.tokens.append(token)
        _log(st, "token_created", f"A {token.name} (HP {token.hp}/Power {token.power}) "
             f"joins the party.", token=token.id, token_id=effect.token_id)


RESOLVERS = {
    "deal_damage": _r_deal_damage,
    "heal": _r_heal,
    "lose_life": _r_lose_life,
    "destroy": _r_destroy,
    "pump": _r_pump,
    "prevent": _r_prevent,
    "draw": _r_draw,
    "scry": _r_scry,
    "create_token": _r_create_token,
}


# --------------------------------------------------------------------------- #
# Damage / death / draw primitives
# --------------------------------------------------------------------------- #
def _deal_damage(st: GameState, target, amount: int, source: str = "") -> None:
    """Damage always lands for its stated amount (GDD §4.3). Defence answers it:
    prevention reduces the hit, then temporary HP absorbs, then HP takes it."""
    prevented = min(target.prevent_pool, amount)
    target.prevent_pool -= prevented
    amount -= prevented
    if prevented:
        _log(st, "prevented", f"{prevented} damage to {target.name} prevented.",
             target=_tid(target), amount=prevented)

    # The "hit size" for a channel break is the amount at the moment it lands —
    # after prevention (which lowers it), but BEFORE temp HP (which only absorbs,
    # so the hit still lands at full size) — GDD §8.
    hit_size = amount
    if (isinstance(target, CharacterState) and target.channels
            and hit_size >= _break_threshold(target)):
        _note_break(st, target, "hit")

    absorbed = min(target.temp_hp, amount)
    target.temp_hp -= absorbed
    amount -= absorbed
    if absorbed:
        _log(st, "absorbed", f"{absorbed} damage to {target.name} absorbed by temp HP.",
             target=_tid(target), amount=absorbed)

    target.hp = max(0, target.hp - amount)
    _log(st, "damage", f"{target.name} takes {amount} damage (HP {target.hp}).",
         target=_tid(target), amount=amount, hp=target.hp, source=source)
    _after_damage(st, target)


def _after_damage(st: GameState, target) -> None:
    if target.hp > 0:
        return
    if isinstance(target, EnemyState):
        _kill_enemy(st, target)
    elif isinstance(target, TokenState):
        _remove_token(st, target)
    else:  # a player-character: incapacitated (its channels then break)
        _log(st, "incapacitated", f"{target.name} is incapacitated.", character=target.id)
        _note_break(st, target, "incapacitated")


def _kill_enemy(st: GameState, enemy: EnemyState) -> None:
    """A removed enemy leaves the board and its pending intent is discarded. Any
    channel aimed at it loses its target -> that holder's channels break."""
    if enemy in st.enemies:
        st.enemies.remove(enemy)
    if enemy.id in st.acted_enemies:
        st.acted_enemies.remove(enemy.id)
    if enemy.intent is not None:
        _log(st, "intent_discarded", f"{enemy.name}'s pending intent is discarded.",
             enemy=enemy.id)
    _log(st, "enemy_died", f"{enemy.name} dies.", enemy=enemy.id)
    for holder in st.party:
        if any(ch.target_id == enemy.id for ch in holder.channels):
            _note_break(st, holder, "aura_loss")


def _remove_token(st: GameState, token: TokenState) -> None:
    if token in st.tokens:
        st.tokens.remove(token)
    if token.id in st.acted_tokens:
        st.acted_tokens.remove(token.id)
    _log(st, "token_died", f"{token.name} is destroyed.", token=token.id)


def _draw(st: GameState, char: CharacterState, n: int) -> None:
    for _ in range(n):
        if not char.library:
            _log(st, "draw_empty", f"{char.name} has no cards left to draw.",
                 character=char.id)
            return
        card = char.library.pop(0)
        char.hand.append(card)
        _log(st, "draw", f"{char.name} draws {card.name}.",
             character=char.id, card=card.id, card_name=card.name)


def _check_end(st: GameState) -> None:
    if st.result is not None:
        return
    if not st.living_enemies():
        st.result = "victory"
        _log(st, "win", "All enemies defeated — the party wins.", result="victory")
    elif not st.living_party():
        st.result = "defeat"
        _log(st, "loss", "The party is incapacitated — defeat.", result="defeat")


# --------------------------------------------------------------------------- #
# Legal-action enumeration
# --------------------------------------------------------------------------- #
_COLOR_NAME = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}


def _legal(st: GameState) -> List[Action]:
    actor = st.character(st.priority)
    if actor is None:
        return []
    if st.phase == "capacity" and not st.stack:
        return _legal_capacity(st, actor)
    return _legal_react(st, actor) if st.stack else _legal_main(st, actor)


def _legal_capacity(st: GameState, actor: CharacterState) -> List[Action]:
    """The start-of-turn choice: which colour to lock the +1 capacity as. A
    mandatory choice (you always gain the capacity), so no pass/end here."""
    return [Action("choose_mana", actor.id, color=c,
                   label=f"Lock +1 mana capacity as {_COLOR_NAME.get(c, c)} ({c})")
            for c in _distinct_identity(actor)]


def _legal_main(st: GameState, actor: CharacterState) -> List[Action]:
    """A character's own turn: the proactive mode (Attack XOR Cast XOR Defend) —
    where Cast may cast several sorcery-speed spells — plus free instants, the
    free voluntary drop, and end turn."""
    actions: List[Action] = []
    mode = actor.acted_mode
    if mode is None:
        for e in st.living_enemies():  # Attack (basic) — all front, melee reaches
            actions.append(Action("attack", actor.id, target_id=e.id,
                                  label=f"Attack {e.name} (Power {actor.current_power})"))
        if not actor.used_defend:       # Defend
            actions.append(Action("defend", actor.id,
                                  label=f"Defend (+{_DEFEND_TEMP_HP} temp HP)"))
    if mode in (None, "cast"):          # Cast sorcery-speed spells (sorcery/channeled)
        for card in actor.hand:
            if card.timing in _SORCERY_SPEED and _can_pay(actor, card):
                actions += _cast_actions(st, actor, card)
    for card in actor.hand:            # Free instants (mana-limited, any time)
        if card.timing == Timing.instant and _can_pay(actor, card):
            actions += _cast_actions(st, actor, card)
    actions += _drop_actions(actor)
    actions.append(Action("end_turn", actor.id, label="End turn"))
    return actions


def _legal_react(st: GameState, actor: CharacterState) -> List[Action]:
    """An open reaction window: free instants, Parry, voluntary drop, or pass."""
    actions: List[Action] = []
    for card in actor.hand:
        if card.timing == Timing.instant and _can_pay(actor, card):
            actions += _cast_actions(st, actor, card)
    top = st.stack[-1]
    # Parry is self-defence: only the character the incoming hit is aimed at may
    # parry it (an ally cannot parry a blow directed at someone else).
    if (not actor.used_parry and top.source_side == "enemy"
            and top.kind in ("attack", "ability") and top.target_id == actor.id):
        actions.append(Action("parry", actor.id, target_id=actor.id,
                              label=f"Parry (reduce the incoming hit by {actor.parry_reduce})"))
    actions += _drop_actions(actor)
    actions.append(Action("pass", actor.id, label="Pass"))
    return actions


def _drop_actions(actor: CharacterState) -> List[Action]:
    """Voluntary drop is a free action available whenever the holder has priority
    and holds at least one channel (ends ALL of them)."""
    if actor.channels:
        n = len(actor.channels)
        return [Action("drop_channels", actor.id,
                       label=f"Drop concentration (end {n} channel{'s' if n > 1 else ''})")]
    return []


def _cast_actions(st: GameState, actor: CharacterState, card: Card) -> List[Action]:
    """One cast Action per legal target of `card`'s primary targeted effect."""
    verb = "Cast"
    out = []
    for tid in _target_options(st, actor, card):
        tgt = st.combatant(tid) if tid else None
        label = f"{verb} {card.name}" + (f" on {tgt.name}" if tgt else "")
        out.append(Action("cast", actor.id, card_id=card.id, target_id=tid, label=label))
    return out


def _target_options(st: GameState, actor: CharacterState, card: Card) -> List[Optional[str]]:
    """Targets for a card's primary targeted effect. Single-target this milestone:
    a card aims at one enemy, one ally, or nothing (self / untargeted)."""
    side = None
    for effect in card.effects:
        desc = getattr(effect, "target", None)
        if desc is not None and not isinstance(desc, str) and getattr(desc, "targeted", False):
            side = desc.side.value
            break
    if side == "enemy":
        return [e.id for e in st.living_enemies()]
    if side == "ally":
        return [c.id for c in st.living_party()]
    return [None]  # self-only / untargeted


# --------------------------------------------------------------------------- #
# Mana
# --------------------------------------------------------------------------- #
def _can_pay(actor: CharacterState, card: Card) -> bool:
    pool = list(actor.pool)
    for color, n in card.cost.colors.items():
        for _ in range(n):
            if color.value in pool:
                pool.remove(color.value)
            else:
                return False
    return len(pool) >= card.cost.generic


def _pay(actor: CharacterState, card: Card) -> List[str]:
    """Spend the cost from the pool; return the actual colours paid (so a channel
    can reserve exactly those and release them on end)."""
    pool = actor.pool
    paid: List[str] = []
    for color, n in card.cost.colors.items():
        for _ in range(n):
            pool.remove(color.value)
            paid.append(color.value)
    for _ in range(card.cost.generic):
        for c in _PAY_ORDER:  # deterministic: spend generic in WUBRG order
            if c in pool:
                pool.remove(c)
                paid.append(c)
                break
    return paid


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _lowest_hp_party(st: GameState) -> Optional[CharacterState]:
    """The minion targeting heuristic: lowest current HP, ties by party order."""
    living = st.living_party()
    if not living:
        return None
    best = living[0]
    for c in living[1:]:
        if c.hp < best.hp:  # strict < preserves the earlier (party-order) tie-break
            best = c
    return best


def _lowest_hp_enemy(st: GameState) -> Optional[EnemyState]:
    """An ally token's target heuristic: lowest-HP enemy, ties by enemy order."""
    living = st.living_enemies()
    if not living:
        return None
    best = living[0]
    for e in living[1:]:
        if e.hp < best.hp:
            best = e
    return best


def _card_in_hand(actor: CharacterState, card_id: str) -> Card:
    for card in actor.hand:
        if card.id == card_id:
            return card
    raise ValueError(f"{actor.name} has no card '{card_id}' in hand")


def _tid(target) -> Optional[str]:
    return getattr(target, "id", None)


def _mana_str(pool: List[str]) -> str:
    return "[" + ", ".join(pool) + "]" if pool else "(empty)"


def _log(st: GameState, type_: str, msg: str, **data) -> None:
    st.log.append(Event(type=type_, msg=msg, data=data))


# --------------------------------------------------------------------------- #
# Loadout entry (kept from the scaffold; the playable demo is the §A scenario).
# --------------------------------------------------------------------------- #
def run(loadout) -> None:
    """Validate-and-report entry for a bare loadout. A loadout alone is not a
    fight (it has no encounter); the runnable demo is the §A scenario — see
    `python -m ltg_combat harness` and `python -m ltg_combat repl`."""
    char = loadout.character
    print(f"[ltg-combat] loaded '{char.name}' ({char.archetype.value}, "
          f"level {char.level}) with {len(loadout.cards)} card(s); stats={char.stats}")
    print("[ltg-combat] a loadout has no encounter; run the playable demo with "
          "`python -m ltg_combat harness` or `python -m ltg_combat repl`.")
