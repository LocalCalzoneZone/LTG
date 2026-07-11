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
  * Library order is an explicit input (the scenario supplies it). The engine is
    deterministic by default; if the scenario is built with a seed (`state.rng_seed`)
    the only randomness is the opening shuffle and any in-game `shuffle` effect, both
    keyed to that seed so a seeded fight still replays identically.
"""

from __future__ import annotations

import copy
import itertools
import math
import random
from typing import List, Optional, Tuple

from ltg_core.schema import (
    Card,
    DealDamage,
    Duration,
    EventTrigger,
    Ref,
    TargetMode,
    Timing,
    slot_name,
    t_chosen,
)

from .state import (
    Action,
    Affliction,
    Channel,
    CharacterState,
    Component,
    EnemyChannel,
    EnemyState,
    Event,
    GameState,
    Intent,
    PendingChoice,
    PreventTag,
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

        # A mid-resolution card-move choice pauses everything until it is made.
        if st.pending_choice is not None:
            st.priority = st.pending_choice.chooser_id
            return

        # A non-empty stack means a reaction window is open: a player must
        # react or pass before the top can resolve. Always pause here. Priority None
        # marks a FRESH window (a new/changed stack top), so the per-window reaction
        # tracker resets here — this is the single canonical window-open point.
        if st.stack:
            if st.priority is None:
                # Seed the window: priority starts with the CASTER of the action
                # now on top (a player about to answer their own pending spell hits
                # Pass first), then moves through the party in turn order. An
                # enemy-sourced top starts at the top of the fixed turn order.
                # (Player pushes seed the caster directly — _open_window; this
                # path covers enemy pushes and mid-window re-seeds after a nested
                # item resolved.)
                src = st.character(st.stack[-1].source_id)
                st.priority = src.id if src is not None and src.alive \
                    else _party_ordered(st)[0].id
                st.passes = 0
                st.reacted_window = []
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
            _tick_afflictions(st)  # poison/regen ticks (D8-2.3): after mana+draw,
            _fire_recurring(st)    # before the recurring channel effects
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


def _party_ordered(st: GameState) -> List[CharacterState]:
    """The living party in TURN ORDER — the fixed initiative rolled at encounter
    setup (state.party_order), NOT the row-based R-6 order: repositioning never
    reshuffles whose turn comes next. States built without the field (legacy
    saves / hand-rolled tests) fall back to the authored party order."""
    order = st.party_order or [c.id for c in st.party]
    idx = {cid: i for i, cid in enumerate(order)}
    return sorted(st.living_party(), key=lambda c: idx.get(c.id, len(idx)))


def _next_player(st: GameState) -> Optional[CharacterState]:
    """The next living character (turn order) that hasn't ended its turn.
    Incapacitated PCs are skipped (alive == effective_hp > 0)."""
    for c in _party_ordered(st):
        if not c.turn_ended:
            return c
    return None


def _next_enemy(st: GameState) -> Optional[EnemyState]:
    """The next living enemy (canonical order) that hasn't executed its intent."""
    for e in _ordered(st.living_enemies()):
        if e.id not in st.acted_enemies:
            return e
    return None


def _next_ally(st: GameState) -> Optional[TokenState]:
    """The next living ally token (canonical order) that hasn't acted this turn."""
    for t in _ordered(st.living_tokens()):
        if t.id not in st.acted_tokens:
            return t
    return None


# --------------------------------------------------------------------------- #
# Turn-structure steps (GDD §4.2)
# --------------------------------------------------------------------------- #
def _begin_turn(st: GameState) -> None:
    """Open the turn: reset enemy/ally action tracking and the capacity flag, and
    apply any deferred ramp (capacity scheduled to arrive this turn)."""
    st.acted_enemies = []
    st.acted_tokens = []
    st.reacted_window = []  # no window open at turn start
    if st.turn == 1 and len(st.party) > 1:
        # Announce the initiative rolled at setup (fixed for the whole encounter).
        names = " → ".join(c.name for c in _party_ordered(st))
        _log(st, "turn_order", f"Turn order: {names}.",
             order=[c.id for c in _party_ordered(st)])
    _log(st, "turn_start", f"— Turn {st.turn} —", turn=st.turn)
    for c in st.party:
        c.capacity_chosen = False
        c.committed = c.row  # Update 02 §M-B.5: begin the turn committed to where you stand
    for e in st.enemies:
        e.committed = e.row  # enemies use the same position model (§F-2)
    for pending in list(st.pending_ramp):
        char = st.character(pending["char"])
        if char is not None:
            for _ in range(int(pending.get("amount", 1))):
                char.mana_colors.append(pending["color"])
            _log(st, "ramp", f"{char.name} gains deferred +{pending.get('amount', 1)} "
                 f"{pending['color']} capacity (capacity {char.capacity}).",
                 character=char.id, color=pending["color"], capacity=char.capacity)
            _fire_capacity_increase(st, char)
    st.pending_ramp = []


def _next_capacity_choice(st: GameState) -> Optional[CharacterState]:
    """The next living character that still owes this turn's +1 capacity colour
    (only from turn 2 onward; no increase on turn 1)."""
    if st.turn < 2:
        return None
    for c in _party_ordered(st):
        if not c.capacity_chosen:
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
    _fire_capacity_increase(st, char)


def _fire_capacity_increase(st: GameState, char: CharacterState) -> None:
    """Recurring `capacity_increase` channel effects (landfall) fire whenever this
    holder's mana capacity rises — the +1/turn lock and any ramp (GDD §8)."""
    for ch in list(char.channels):
        fired = [e for e in ch.card.effects
                 if getattr(e, "trigger", None) == "capacity_increase"]
        if fired:
            _fire_channel_effects(st, char, "party", ch, fired)


def _fire_channel_effects(st: GameState, holder, side: str, ch, fired) -> None:
    """Push a channel's just-fired triggered effects (event / upkeep /
    capacity_increase) onto the stack as ONE triggered ability — MTG-style,
    every trigger uses the stack: a reaction window opens on it (a "triggered"/
    "ability" counter answers it) and it resolves like any stack action. The
    holder picks a triggered modal's mode and any owed chosen target as it is
    pushed (_raise_next_trigger_pick); a trigger fired mid-resolution waits on
    the stack until the current resolution finishes, exactly like MTG."""
    card = getattr(ch, "card", None)
    name = getattr(card, "name", None) or getattr(ch, "name", "channel")
    item = _push(st, StackItem(kind="triggered", source_id=holder.id, source_side=side,
                               label=f"{name} — trigger", effects=list(fired),
                               target_id=ch.target_id, card=card,
                               x=getattr(ch, "x", 0)))
    if side == "party":
        item.needs_mode = any(getattr(e, "kind", None) == "modal" for e in fired)
        item.needs_target = _trigger_pick_effect(item) is not None
    st.priority = None  # fresh window — re-seeded by _advance
    st.passes = 0
    _log(st, "channel_trigger",
         f"{name}'s trigger goes on the stack.", source=holder.id, label=name)
    _raise_next_trigger_pick(st)


def _event_who_matches(who: str, holder, holder_side: str,
                       channel_target_id: Optional[str], actor) -> bool:
    """Whether `actor`'s event counts for an EventTrigger, relative to the channel's
    holder: you = the holder · target = the channel's chosen target · ally = anyone
    on the holder's side (including the holder) · enemy = anyone opposing · any."""
    aid = getattr(actor, "id", None)
    if who == "you":
        return aid == holder.id
    if who == "target":
        return channel_target_id is not None and aid == channel_target_id
    actor_side = "enemy" if isinstance(actor, EnemyState) else "party"
    if who == "ally":
        return actor_side == holder_side
    if who == "enemy":
        return actor_side != holder_side
    return True  # "any"


def _matching_event_effects(effects, event: str, holder, holder_side: str,
                            channel_target_id: Optional[str], actor,
                            spell_timing: Optional[str]) -> List:
    out = []
    for e in effects:
        t = getattr(e, "trigger", None)
        if not isinstance(t, EventTrigger) or t.event != event:
            continue
        if not _event_who_matches(t.who, holder, holder_side, channel_target_id, actor):
            continue
        if (t.spell_type is not None
                and getattr(t.spell_type, "value", t.spell_type) != spell_timing):
            continue
        out.append(e)
    return out


def _fire_event(st: GameState, event: str, actor,
                spell_timing: Optional[str] = None) -> None:
    """Event-triggered channel effects: whenever a combatant attacks, is dealt
    damage, gains life, casts a spell, or draws a card, every held channel with a
    matching EventTrigger fires its effect(s) immediately (like an upkeep tick).
    `event_depth` caps trigger-fires-trigger chains (an on-draw draw, an on-damage
    hit) so they always terminate instead of recursing forever."""
    if actor is None or st.event_depth >= 8:
        return
    # Watch ALL party members' channels, not just living ones: a just-downed
    # holder still holds theirs (the break is pending), so a "when you fall"
    # death trigger gets its death rattle. Long-downed characters hold none.
    party_watch = [(h, ch) for h in st.party for ch in list(h.channels)]
    enemy_watch = [(e, ch) for e in st.living_enemies() for ch in list(e.channels)]
    if not party_watch and not enemy_watch:
        return
    st.event_depth += 1
    try:
        for holder, ch in party_watch:
            if ch not in holder.channels:  # broken by an earlier trigger this event
                continue
            fired = _matching_event_effects(ch.card.effects, event, holder, "party",
                                            ch.target_id, actor, spell_timing)
            if not fired:
                continue
            _fire_channel_effects(st, holder, "party", ch, fired)
        for holder, ch in enemy_watch:
            if ch not in holder.channels:
                continue
            fired = _matching_event_effects(ch.effects, event, holder, "enemy",
                                            ch.target_id, actor, spell_timing)
            if not fired:
                continue
            item = StackItem(kind="ability", source_id=holder.id, source_side="enemy",
                             label=f"{ch.name} — trigger", effects=[],
                             target_id=ch.target_id)
            for eff in fired:
                _resolve_effect(st, item, eff,
                                {"party_size": len(st.party), "caster_obj": holder})
    finally:
        st.event_depth -= 1


def _upkeep_draws(st: GameState) -> None:
    """After capacity is set: mana refreshes (channels keep their reserve out of
    the pool), each character draws 1, and per-round uses / turn flags reset."""
    for c in st.living_party():
        c.pool = _refreshed_pool(c)  # every unreserved locked colour spendable
        _draw(st, c, 1)
        c.used_attack = c.used_defend = c.used_mitigate = False
        c.acted_mode = None
        c.turn_ended = False
        c.taunted_to = None  # enemy taunt is a this-turn bind (§F-3)
        c.spells_cast_turn = 0  # `spells_cast` conditions count per turn
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
    each holder's turn, in hold order (GDD §8) — party channels first, then
    enemy channels (the ritual ticks players must decide to interrupt)."""
    for holder in st.living_party():
        for ch in list(holder.channels):
            fired = [e for e in ch.card.effects
                     if getattr(e, "trigger", None) == "upkeep"]
            if fired:
                _fire_channel_effects(st, holder, "party", ch, fired)
    for e in _ordered(st.living_enemies()):
        for ch in list(e.channels):
            fired = [eff for eff in ch.effects
                     if getattr(eff, "trigger", None) == "upkeep"]
            if fired:
                _fire_channel_effects(st, e, "enemy", ch, fired)


def _declare_intents(st: GameState) -> None:
    """The Intents step (R-4/R-5): every enemy AND every ally token declares its
    telegraphed intent against the current state, in the canonical order. Allies
    use the same deterministic heuristic as enemies, applied on the party's side."""
    _redeploy_bounced(st)  # bounced enemies return at the start of their next turn (§E-C)
    for e in _ordered(st.living_enemies()):
        _declare_enemy_intent(st, e)
    for t in _ordered(st.living_tokens()):
        _declare_ally_intent(st, t)


def _redeploy_bounced(st: GameState) -> None:
    """Update 03 §E-C redeploy: every in-hand (bounced) enemy moves `in hand → in
    play` at the start of the Intents step, re-entering at its original row (its
    `row` is preserved across the bounce). It then declares a fresh intent in the
    normal pass below. Net: it lost exactly the one action cycle it was bounced on."""
    for e in st.enemies:
        if e.in_hand:
            e.in_hand = False
            _log(st, "redeploy",
                 f"{e.name} redeploys to the battlefield ({e.row} row).",
                 enemy=e.id, row=e.row)


def _declare_enemy_intent(st: GameState, e: EnemyState) -> None:
    """The proactive pass (Design Update 04 §F-7.1): evaluate the enemy's merged
    priority list first-match-wins — the top proactive component whose condition holds,
    cooldown is ready, and target exists declares this turn's intent. The list always
    terminates in the default Attack (priority 90), so a non-stunned enemy that can
    still act always produces an intent. An enemy with no components goes straight to
    the default attack (legacy behaviour, unchanged)."""
    # Reset this round's intents-window line (D8-1.5); every path below re-sets it.
    e.round_intent = None
    e.round_intent_status = "none"
    e.round_intent_reveal = ""
    if e.stunned > 0:  # stun: skip this intent, spend one charge (R-11)
        e.stunned -= 1
        e.intent = None
        e.round_intent_status = "stunned"
        _log(st, "stunned", f"{e.name} is stunned and skips its intent ({e.stunned} left).",
             enemy=e.id, intents=e.stunned)
        return
    for comp in _proactive_rules(e):
        intent = _try_declare_component(st, e, comp)
        if intent is not None:
            e.intent = intent
            e.round_intent = intent
            e.round_intent_status = "declared"
            tgt = st.combatant(intent.target_id)
            _log(st, "intent_declared",
                 f"{e.name} declares {intent.name}" + (f" → {tgt.name}" if tgt else "") + ".",
                 enemy=e.id, intent=intent.name, target=intent.target_id,
                 component=comp.id, archetype=comp.archetype)
            return
    _declare_default_attack(st, e)


def _declare_default_attack(st: GameState, e: EnemyState) -> None:
    """The terminal priority-90 rule: the basic attack. Pacified (`prevent attack`) or
    with no reachable target, the enemy declares nothing (Move-toward-reach is added in
    §F-7.3)."""
    tmpl = e.intent_template
    if tmpl.get("intent_type", "attack") == "attack" and _prevented_action(e, "attack"):
        e.intent = None
        _log(st, "pacified", f"{e.name} can't attack and declares nothing.", enemy=e.id)
        return
    target, mode, amount, name = _choose_enemy_attack(st, e)
    if target is None:
        dest = _move_toward_reach(st, e)  # §F-7.3: step toward reach instead of idling
        if dest is not None:
            e.intent = _move_intent("Advance", dest, None)
            e.round_intent = e.intent
            e.round_intent_status = "declared"
            _log(st, "intent_declared", f"{e.name} advances toward {dest} (no target in reach).",
                 enemy=e.id, intent="Advance", destination=dest)
            return
        e.intent = None
        _log(st, "no_target", f"{e.name} has no reachable target and declares nothing.",
             enemy=e.id)
        return
    e.attack_mode = mode  # the chosen attack carries onto the stack (R-1) and the panel
    effects = [DealDamage(amount=amount, target=t_chosen("ally", targeted=True))]
    # An attack-type intent lands on the stack as an `attack` (so combat_damage
    # prevention and ability/attack counters answer it — R-1/R-11).
    kind = "attack" if tmpl.get("intent_type", "attack") == "attack" else tmpl.get("action_type", "ability")
    # Base (pre-bonus) Power of the chosen attack, so a wound/anthem landing after
    # declaration re-blunts/boosts the swing when it executes (see Intent.attack_damage).
    src_tmpl = tmpl if mode == tmpl.get("mode", "melee") else e.ranged_template
    base = int(src_tmpl.get("amount", 0))
    e.intent = Intent(name=name, action_type=kind, effects=effects, target_id=target.id,
                      attack_power=base)
    e.round_intent = e.intent
    e.round_intent_status = "declared"
    _log(st, "intent_declared",
         f"{e.name} declares {name} ({mode} {amount} dmg) → {target.name}.",
         enemy=e.id, intent=name, amount=amount, target=target.id, mode=mode)


# --------------------------------------------------------------------------- #
# Components: the merged priority list (Design Update 04 §F-3 / §F-7)
# --------------------------------------------------------------------------- #
def _proactive_rules(e: EnemyState) -> List[Component]:
    """The enemy's proactive components in evaluation order: priority ascending, ties
    broken by authoring order (§F-7.1). `sorted` is stable, so a priority-only key keeps
    authoring order within a band."""
    return sorted([c for c in e.components if c.timing == "proactive"],
                  key=lambda c: c.priority)


def _cooldown_ready(st: GameState, e: EnemyState, comp: Component) -> bool:
    """A component is off cooldown once the current turn reaches its next-usable turn
    (0 by default → always ready). once_per_encounter parks the value out of reach."""
    return st.turn >= e.cooldowns.get(comp.id, 0)


def _start_cooldown(st: GameState, e: EnemyState, comp_id: str) -> None:
    """Consume a fired component's cooldown (§F-3.1): it is next usable `cooldown` whole
    turns from now (min 1 so a fire always costs a turn); once_per_encounter never returns."""
    comp = next((c for c in e.components if c.id == comp_id), None)
    if comp is None:
        return
    e.cooldowns[comp_id] = 10 ** 9 if comp.once_per_encounter else st.turn + max(1, comp.cooldown)


def _cmp(lhs: float, op: str, rhs: float) -> bool:
    return {"<": lhs < rhs, "<=": lhs <= rhs, ">": lhs > rhs,
            ">=": lhs >= rhs, "==": lhs == rhs, "!=": lhs != rhs}.get(op, False)


def _condition_met(st: GameState, e: EnemyState, cond: dict) -> bool:
    """Evaluate a component's optional eligibility gate (§F-3): self-HP fraction, the
    turn number, this enemy's ally count, or raw self-HP. An unknown kind fails closed."""
    kind = cond.get("kind")
    op = cond.get("op", ">=")
    val = cond.get("value", 0)
    if kind == "self_hp_pct":
        lhs = 100.0 * e.effective_hp / e.max_hp if e.max_hp else 0.0
    elif kind == "self_hp":
        lhs = e.effective_hp
    elif kind == "turn":
        lhs = st.turn
    elif kind == "ally_count":
        lhs = len([o for o in st.living_enemies() if o.id != e.id])
    elif kind == "hero_count":
        # Living (up) heroes — desperation/cleave gates that read the party's size.
        lhs = len(st.living_party())
    elif kind == "hero_channeling":
        # Heroes currently holding a channel — arm the ritual-breaker only when
        # there is a ritual to break.
        lhs = len([c for c in st.living_party() if c.channels])
    elif kind == "self_channeling":
        # This enemy's own held channels — e.g. defend-the-ritual behaviour.
        lhs = len(e.channels)
    else:
        return False
    return _cmp(lhs, op, val)


def _component_eligible(st: GameState, e: EnemyState, comp: Component) -> bool:
    if not _cooldown_ready(st, e, comp):
        return False
    if comp.condition is not None and not _condition_met(st, e, comp.condition):
        return False
    # Boss phase gate (§F-9): a pre_enrage rule retires when the boss enrages; a
    # post_enrage rule sleeps until then. Ignored on non-bosses (never enraged).
    if comp.phase == "pre_enrage" and e.enraged:
        return False
    if comp.phase == "post_enrage" and not e.enraged:
        return False
    # A channel-component sleeps while its channel holds — one instance at a time;
    # after a break, its cooldown gates the re-channel.
    if comp.channel and any(ch.component_id == comp.id for ch in e.channels):
        return False
    return True


def _component_target(st: GameState, e: EnemyState, comp: Component):
    """Resolve a component's `target_rule` to a concrete combatant (§F-3 / §F-7.2), or
    None when it wants a target it can't find (so the rule is skipped, first-match-wins).

    Frame note: an enemy's "ally" is another enemy; a player-directed rule uses the
    reachability-aware valuation pick (refined further in §F-7.2)."""
    rule = comp.target_rule
    if rule == "self":
        return e
    if rule == "lowest_hp_ally":
        cands = [o for o in st.living_enemies() if o.id != e.id]
        # A support rule whose verbs only heal skips allies at full HP — the healer
        # falls through to its next rule (usually the attack) instead of wasting the
        # mend. Buff/keyword support still lands on healthy allies.
        if cands and all(getattr(v, "kind", None) == "heal" for v in comp.verbs) and comp.verbs:
            cands = [o for o in cands if o.effective_hp < o.max_hp]
        return _lowest_hp(cands)
    if rule == "wounded_ally":
        # Strictly-wounded support: the most-hurt fellow enemy, or nobody (skip the
        # rule) when the warband is untouched.
        return _lowest_hp([o for o in st.living_enemies()
                           if o.id != e.id and o.effective_hp < o.max_hp])
    if rule == "channeling_player":
        return _lowest_hp([c for c in st.living_party() if c.channels])
    if rule == "highest_threat":
        # The assassin's read: the hardest-hitting reachable hero (ties: casters
        # and ranged before melee, then the most wounded).
        cands = [c for c in _reachable_targets(e, st.living_party())
                 if not _has_kw(c, "hexproof")]
        cands = _filter_control_targets(comp, cands)
        if not cands:
            return None
        return sorted(cands, key=lambda c: (-c.current_power, _role_rank(c),
                                            c.effective_hp, _row_rank(c.row), c.name))[0]
    if rule == "valuation":
        return _valuation_target(st, e, comp)
    return st.combatant(rule)  # a fixed combatant id


def _component_damage(comp: Component) -> int:
    """The constant `deal_damage` a component's verbs would deal (0 if it deals none) —
    what the valuation reads to judge 'finishable' and 'channel-breakable'."""
    total = 0
    for eff in comp.verbs:
        if getattr(eff, "kind", None) == "deal_damage":
            amt = getattr(eff, "amount", 0)
            if isinstance(amt, int):
                total += amt
    return total


def _role_rank(c) -> int:
    """Role value for valuation step 3 (§F-7.2): actively-casting/support first, then
    ranged, then melee."""
    if getattr(c, "channels", None):
        return 0
    return 1 if getattr(c, "attack_mode", "melee") == "ranged" else 2


def _swarm_at_cap(st: GameState, e: EnemyState, comp: Component) -> bool:
    """A Swarm component is a no-op once the creator already has 2 living tokens (§F-4
    T-27) — skip it so the enemy does something useful instead."""
    if not any(getattr(v, "kind", None) == "create_token" for v in comp.verbs):
        return False
    return len([o for o in st.living_enemies() if o.created_by == e.id]) >= 2


def _filter_control_targets(comp: Component, cands: List) -> List:
    """Don't waste control (§F-7.2 refinement): a stun rule skips heroes already
    stunned and a taunt rule skips heroes already taunted, so the debilitator
    spreads its locks across the party instead of stacking one victim. Emptying
    the list makes the rule skip (first-match-wins moves on) — the enemy does
    something useful instead."""
    kinds = {getattr(v, "kind", None) for v in comp.verbs}
    if "stun" in kinds:
        cands = [c for c in cands if getattr(c, "stunned", 0) <= 0]
    if "taunt" in kinds:
        cands = [c for c in cands if getattr(c, "taunted_to", None) is None]
    return cands


def _valuation_target(st: GameState, e: EnemyState, comp: Component):
    """The target-valuation brain (§F-7.2). Candidates are the reachable, non-hexproof
    players; then ranked, first-match-wins:

      1. Finishable — effective HP ≤ this hit's damage; take the highest such (biggest kill).
      2. Channel-breakable — channeling and this hit ≥ 25% of its max HP (GDD §8).
      3/4. Role value (caster/support > ranged > melee), then lowest effective HP.
      5. Deterministic tiebreak — row order (front > mid > rear), then name.

    This is what makes an archer snipe the exposed channeler and a brute finish the
    wounded frontliner with no per-enemy scripting."""
    dmg = _component_damage(comp)
    cands = [c for c in _reachable_targets(e, st.living_party()) if not _has_kw(c, "hexproof")]
    cands = _filter_control_targets(comp, cands)
    return _rank_valuation(cands, dmg)


def _rank_valuation(cands: List, dmg: int):
    """The §F-7.2 ranking applied to an already-reachable candidate list and a known hit
    size — shared by valuation components and the default attack (whose damage is Power)."""
    if not cands:
        return None
    if dmg > 0:
        finishable = [c for c in cands if c.effective_hp <= dmg]
        if finishable:  # highest effective HP among the kills, then the deterministic tiebreak
            return sorted(finishable, key=lambda c: (-c.effective_hp, _row_rank(c.row), c.name))[0]
        breakers = [c for c in cands if getattr(c, "channels", None)
                    and dmg >= _break_threshold(c)]
        if breakers:
            return sorted(breakers, key=lambda c: (_row_rank(c.row), c.name))[0]
    return sorted(cands, key=lambda c: (_role_rank(c), c.effective_hp, _row_rank(c.row), c.name))[0]


def _try_declare_component(st: GameState, e: EnemyState, comp: Component) -> Optional[Intent]:
    """Build this component's intent if it is eligible and has a target; else None (the
    priority pass moves on). Movement/repositioning rules are declared in §F-7.3."""
    if not _component_eligible(st, e, comp):
        return None
    if comp.move_home:  # an Evasive/repositioning rule declares a Move (§F-7.3)
        dest = _reposition_row(st, e, comp)
        if dest is None or dest == e.committed:
            return None  # already where it wants to be — skip to the next rule
        return _move_intent(comp.telegraph or "Reposition", dest, comp.id)
    if _swarm_at_cap(st, e, comp):
        return None  # already at the per-creator token cap — skip (attack instead, §F-4)
    target = _component_target(st, e, comp)
    if comp.target_rule != "self" and target is None:
        return None  # wanted a target it can't reach — skip to the next rule
    name = comp.telegraph or comp.archetype or "Ability"
    # A "spell"-classed component stacks as a spell (GDD taxonomy): thematic —
    # enemies have no cards — but mechanically real: spell counters answer it.
    kind = "spell" if comp.action_type == "spell" else "ability"
    return Intent(name=name, action_type=kind, effects=list(comp.verbs),
                  target_id=(target.id if target is not None else None),
                  source_component=comp.id)


# --------------------------------------------------------------------------- #
# Enemy movement (Design Update 04 §F-7.3; position model per §F-2 / Update 02)
# --------------------------------------------------------------------------- #
def _move_intent(name: str, dest: str, comp_id: Optional[str]) -> Intent:
    """A Move intent: no stack action, no reaction window — it queues a destination row
    that resolves at End step. Its "target" is the row, carried on `move_to`."""
    return Intent(name=name, action_type="ability", effects=[], target_id=None,
                  kind="move", move_to=dest, source_component=comp_id)


def _reposition_row(st: GameState, e: EnemyState, comp: Component) -> Optional[str]:
    """Where a repositioning rule sends the enemy — its home row (Evasive retreats to
    the safe row it lives on, §F-2/§F-8 Bloodbat). Returns None if already home."""
    return e.home_row if e.home_row != e.committed else None


def _move_toward_reach(st: GameState, e: EnemyState) -> Optional[str]:
    """The row a stranded enemy steps to when nothing is reachable (§F-7.3): toward the
    front-most row a living player occupies, one step at a time is unnecessary here —
    it commits to that row and the reach check re-runs next turn. None if no players."""
    party = st.living_party()
    if not party:
        return None
    front = min(_row_rank(c.row) for c in party)
    dest = next((r for r, rank in _ROW_RANK.items() if rank == front), "front")
    return dest if dest != e.committed else None


def _attack_amount(e: EnemyState, tmpl: dict) -> int:
    """An attack's damage from its template, blunted by any wound on the enemy (R-7).
    Never negative."""
    return max(0, int(tmpl.get("amount", 0)) + e.power_bonus)


def _choose_enemy_attack(st: GameState, e: EnemyState):
    """Pick this enemy's target AND attack for the turn (the R-1 heuristics).

    Returns (target, mode, amount, name), or (None, …) when nothing is reachable.
    An enemy's *primary* attack is its `intent_template` (melee or ranged). A
    melee-primary enemy may also carry a weaker `ranged_template`, used ONLY as a
    fallback when melee can't reach the character the rule wants:

      * "front_lowest_hp" (Skitterling): claw the lowest-HP character on the
        front-most reachable row; spit (ranged) only if melee reaches no one.
      * "lowest_hp" (Brute): hunt the globally lowest-HP character; smash it in melee
        if it stands in reach, else hurl (ranged) at it.
      * a fixed character id (e.g. §C's Maul → "mira"): aim there if reachable.
      * "lowest_hp_party" (default): the classic lowest-HP reachable target.

    Reach is computed per mode without mutating the enemy. Hexproof does NOT
    shelter a hero from basic attacks — it wards targeted spells/abilities only
    (Update 06), so the pools here are purely reach-based."""
    party = st.living_party()
    tmpl = e.intent_template
    primary_mode = tmpl.get("mode", "melee")
    primary = list(_reachable_targets(e, party, mode=primary_mode))
    primary_amount, primary_name = _attack_amount(e, tmpl), tmpl["name"]
    # The weaker ranged attack is a fallback only a melee-primary enemy can have.
    has_fallback = bool(e.ranged_template) and primary_mode == "melee"
    fallback = (list(_reachable_targets(e, party, mode="ranged"))
                if has_fallback else [])
    fb_amount = _attack_amount(e, e.ranged_template) if has_fallback else 0
    fb_name = e.ranged_template.get("name", primary_name) if has_fallback else primary_name
    none = (None, None, 0, None)

    def aim(target):
        """Resolve a chosen target: the primary attack when in reach, else the ranged
        fallback, else (unreachable) nothing."""
        if target is None:
            return none
        if target in primary:
            return target, primary_mode, primary_amount, primary_name
        if has_fallback and target in fallback:
            return target, "ranged", fb_amount, fb_name
        return none

    # Taunt overrides target selection and lands regardless of reach/row (R-11); the
    # mode still falls back to ranged when the primary attack can't reach the target.
    if e.taunted_by is not None:
        forced = st.character(e.taunted_by)
        if forced is not None and forced.alive:
            if forced in primary or not has_fallback:
                return forced, primary_mode, primary_amount, primary_name
            return forced, "ranged", fb_amount, fb_name

    rule = tmpl.get("targeting", "lowest_hp_party")

    if rule == "lowest_hp":  # the Brute: always the globally lowest-HP character
        return aim(_lowest_hp(fallback if has_fallback else primary))

    if rule == "valuation":  # §F-7.2 default-attack brain (finishable / channel-break / role)
        pool = primary if primary else (fallback if has_fallback else [])
        dmg = primary_amount if primary else fb_amount
        return aim(_rank_valuation(pool, dmg))

    if rule not in ("lowest_hp_party", "front_lowest_hp"):  # a fixed character id
        cand = st.character(rule)
        if cand is not None and cand.alive:
            chosen = aim(cand)
            if chosen[0] is not None:
                return chosen
        # fixed target unreachable -> fall through to the default lowest-HP behaviour

    # Default / "front_lowest_hp" (the Skitterling): the lowest-HP character on the
    # front-most reachable row; only fall back to ranged when the primary reaches no one.
    if primary:
        return _lowest_hp(primary), primary_mode, primary_amount, primary_name
    if has_fallback and fallback:
        return _lowest_hp(fallback), "ranged", fb_amount, fb_name
    return none


def _declare_ally_intent(st: GameState, token: TokenState) -> None:
    """An ally token telegraphs its attack on the lowest-effective-HP reachable
    enemy (executed in the Ally step) — the enemy heuristic on the party side."""
    reachable = _reachable_targets(token, st.living_enemies())
    target = _lowest_hp(reachable)
    if target is None:
        token.intent = None
        return
    effects = [DealDamage(amount=token.current_power, target=t_chosen("enemy", targeted=True))]
    token.intent = Intent(name=f"{token.name}'s attack", action_type="attack",
                          effects=effects, target_id=target.id)
    _log(st, "ally_intent", f"{token.name} intends to attack {target.name} "
         f"(Power {token.current_power}).", token=token.id, target=target.id)


def _execute_intent(st: GameState, enemy: EnemyState) -> None:
    """Move a declared intent onto the stack as an action (GDD §5.2). A component
    intent starts that component's cooldown as it executes (§F-3.1)."""
    st.acted_enemies.append(enemy.id)
    intent = enemy.intent
    if intent is None:
        return
    if intent.source_component is not None:
        _start_cooldown(st, enemy, intent.source_component)
    if intent.kind == "move":  # a Move queues a destination row, resolved at End step
        enemy.pending_voluntary = intent.move_to
        enemy.intent = None
        enemy.round_intent_status = "executed"
        _log(st, "enemy_move",
             f"{enemy.name} will move to {intent.move_to} (resolves at End step).",
             enemy=enemy.id, destination=intent.move_to)
        return
    if intent.target_id is None:
        enemy.intent = None
        enemy.round_intent_status = "fizzled"
        return
    # Re-check target legality as the intent ENTERS the stack: a target that left play
    # or was incapacitated since this was telegraphed makes the swing fizzle now rather
    # than reach the stack (it is also re-checked at resolution, R-12). Hexproof does
    # NOT fizzle an attack — it wards spells/abilities, not the sword (Update 06).
    target = st.combatant(intent.target_id)
    if target is None or not _legal_target(target):
        _log(st, "fizzle", f"{enemy.name}'s {intent.name} fizzles — no legal target.",
             enemy=enemy.id, label=intent.name)
        enemy.intent = None
        enemy.round_intent_status = "fizzled"
        return
    # Carry the base attack Power so the damage is recomputed from the enemy's CURRENT
    # power when it RESOLVES — a wound (e.g. Agony Warp −3/−0) applied after declaration,
    # or while the swing sits on the stack, must reduce what lands (R-7).
    # A channel-component's intent starts an EnemyChannel when it RESOLVES —
    # marked here so counters can still kill it on the stack first (§8).
    src_comp = next((c for c in enemy.components
                     if c.id == intent.source_component), None)
    _push(st, StackItem(kind=intent.action_type, source_id=enemy.id,
                        source_side="enemy", label=intent.name,
                        effects=intent.effects, target_id=intent.target_id,
                        attack_mode=enemy.attack_mode, attack_power=intent.attack_power,
                        starts_channel=bool(src_comp is not None and src_comp.channel),
                        component_id=intent.source_component))
    enemy.intent = None
    enemy.round_intent_status = "executed"  # the stack is honest — its line strikes (D8-1.5)
    st.priority = None  # open a fresh reaction window (party order, set in _advance)
    st.passes = 0
    _log(st, "intent_execute", f"{enemy.name} executes {intent.name}.",
         enemy=enemy.id, label=intent.name)
    if intent.action_type == "attack":
        _fire_event(st, "attack", enemy)  # attack triggers fire at declaration


def _execute_ally(st: GameState, token: TokenState) -> None:
    """Execute the ally token's telegraphed intent (R-5), opening a reaction window
    like any other attack. If its target is gone, re-pick the lowest-HP reachable
    enemy so the ally still acts."""
    st.acted_tokens.append(token.id)
    intent = token.intent
    target = st.enemy(intent.target_id) if intent is not None else None
    if target is None or not target.alive:
        target = _lowest_hp(_reachable_targets(token, st.living_enemies()))
    token.intent = None
    if target is None:
        return
    # `attack_power` makes the damage re-read the token's CURRENT Power at
    # resolution (R-7) — the amount here is only the declared/telegraphed figure.
    effects = [DealDamage(amount=token.current_power, target=t_chosen("enemy", targeted=True))]
    _push(st, StackItem(kind="attack", source_id=token.id, source_side="party",
                        label=f"{token.name}'s attack", effects=effects,
                        target_id=target.id, attack_mode=token.attack_mode,
                        attack_power=token.power))
    st.priority = None
    st.passes = 0
    _log(st, "ally_attack", f"{token.name} attacks {target.name} (Power {token.current_power}).",
         token=token.id, target=target.id, power=token.current_power)
    _fire_event(st, "attack", token)  # attack triggers fire at declaration


def _end_step(st: GameState) -> None:
    """End-of-turn expiry (R-7): `temp_mod` (pump/wound) → 0, prevention/taunt drop,
    turn-scoped keywords lapse. Sustained channel auras are then re-applied (they
    live in the temp layers, which just reset). Finally re-check lethality on the
    refreshed effective_hp: a creature ≤ 0 dies, a PC recovers if back above 0."""
    for c in st.party:
        c.temp_mod = c.power_bonus = c.prevent_pool = 0
        c.prevent_tags = []
        # Update 02 §M-B.5: the body catches up — a queued voluntary move wins, else
        # wherever forced commitments left `committed`. Then clear the voluntary slot.
        c.row = c.pending_voluntary if c.pending_voluntary is not None else c.committed
        c.pending_voluntary = None
        _expire_keywords(c)
    for e in st.enemies:
        e.temp_mod = e.prevent_pool = e.power_bonus = 0
        e.prevent_tags = []
        e.taunted_by = None
        # The body catches up to a queued Move (§F-7.3 / Update 02 §M-B.5), else stays
        # where it committed. Then clear the voluntary slot.
        e.row = e.pending_voluntary if e.pending_voluntary is not None else e.committed
        e.pending_voluntary = None
        _expire_keywords(e)
    for t in st.tokens:
        t.temp_mod = t.power_bonus = t.prevent_pool = 0
        t.prevent_tags = []
        _expire_keywords(t)
    _reapply_channel_stats(st)
    _reap_dead(st)
    _log(st, "end_step", "End step: temporary effects expire.")


def _reap_dead(st: GameState) -> None:
    """Remove any creature/token now at effective_hp ≤ 0; note an incap-break for a
    channeling PC that ended the turn down (a PC recovered above 0 needs nothing)."""
    for e in list(st.enemies):
        if e.effective_hp <= 0:
            _kill_enemy(st, e)
    for t in list(st.tokens):
        if t.effective_hp <= 0:
            _remove_token(st, t)
    for c in st.party:
        if c.effective_hp <= 0 and c.channels:
            _note_break(st, c, "incapacitated")
    _process_breaks(st)


def _expire_keywords(combatant) -> None:
    """Drop granted keywords whose duration ends with the turn (encounter /
    permanent / while_channeled persist; the channel break lifts the last)."""
    for kw, dur in list(combatant.keywords.items()):
        if dur in ("this_turn", "end_of_turn"):  # end_of_turn: legacy alias of this_turn
            del combatant.keywords[kw]


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
        "mitigate": _do_mitigate,
        "move": _do_move,
        "choose_mana": _do_choose_mana,
        "choose_card": _do_choose_card,
        "choose_scry": _do_choose_scry,
        "choose_target": _do_choose_target,
        "choose_mode": _do_choose_mode,
        "drop_channels": _do_drop_channels,
        "use_skill": _do_use_skill,
        "use_ultimate": _do_use_ultimate,
    }[action.kind]
    handler(st, action)


def _do_choose_mana(st: GameState, action: Action) -> None:
    """Lock the colour of this turn's +1 capacity slot (start of turn, pre-draw)."""
    char = st.character(action.actor_id)
    _lock_capacity(st, char, action.color, auto=False)
    st.priority = None


def _do_choose_scry(st: GameState, action: Action) -> None:
    """Apply one pick of a scry: send the chosen revealed card to the top or bottom
    of the library. `target_id` is the destination ('top' | 'bottom'). When every
    revealed card has been placed, rebuild the library and resume the spell."""
    pc = st.pending_choice
    char = st.character(pc.chooser_id)
    card = pc.candidates[action.choice]
    pc.candidates = [c for c in pc.candidates if c is not card]
    pile = pc.bottom if action.target_id == "bottom" else pc.top
    pile.append(card)
    _log(st, "scry_place",
         f"{char.name} puts {card.name} on the {'bottom' if action.target_id == 'bottom' else 'top'} "
         f"of their library.", character=char.id, card=card.id,
         destination=("library_bottom" if action.target_id == "bottom" else "library_top"))
    if pc.candidates:
        return  # still placing the rest of the revealed cards
    # Every revealed card is placed: the kept-on-top cards (pick order, first chosen
    # drawn first), then the untouched rest, then the bottomed cards.
    char.library = list(pc.top) + char.library[pc.looked:] + list(pc.bottom)
    item, remaining = pc.item, pc.remaining
    st.pending_choice = None
    _log(st, "scry_done",
         f"{char.name} reorders the top of their library (kept {len(pc.top)} on top, "
         f"{len(pc.bottom)} on the bottom).", character=char.id,
         top=[c.id for c in pc.top], bottom=[c.id for c in pc.bottom])
    _resolve_effect_list(st, item, remaining, _new_ctx(st, item))
    if st.pending_choice is None:
        _process_breaks(st)
        st.priority = None


def _do_choose_card(st: GameState, action: Action) -> None:
    """Apply one pick of a mid-resolution card-move choice. Moves the chosen card,
    then either keeps prompting (more to move) or resumes the rest of the spell."""
    pc = st.pending_choice
    char = st.character(pc.chooser_id)
    card = pc.candidates[action.choice]
    _place_card(st, char, pc.effect, card)
    pc.candidates = [c for c in pc.candidates if c is not card]
    pc.need -= 1
    if pc.need > 0 and pc.candidates:
        return  # still choosing — pending_choice stays (picked card removed)
    # This move is done: shuffle if asked, then resume the item's remaining effects
    # (which may itself raise the next choice).
    item, eff, remaining = pc.item, pc.effect, pc.remaining
    st.pending_choice = None
    _move_shuffle(st, char, eff)
    _resolve_effect_list(st, item, remaining, _new_ctx(st, item))
    if st.pending_choice is None:
        _process_breaks(st)
        st.priority = None


def _do_pass(st: GameState, action: Action) -> None:
    """Pass priority in the open reaction window (§F-7.4). When every living PC has
    passed in succession: first offer the enemy side a reaction to the stack top
    (pre-resolution triggers); if one fires the window reopens and the top does NOT
    resolve. Otherwise the top resolves, and the effects it produced are offered to
    the enemy side as post-resolution triggers (on_hit / on_ally_hit / on_ally_death)."""
    actor = st.character(action.actor_id)
    suffix = " (auto)" if getattr(action, "auto", False) else ""
    _log(st, "pass", f"{actor.name} passes{suffix}.", character=actor.id,
         auto=bool(getattr(action, "auto", False)))
    st.passes += 1
    if st.passes >= len(st.living_party()):
        if _offer_reactions(st, _pre_trigger_ctx(st)):
            return  # an enemy answered the top; the reopened window is the party's
        start = len(st.log)
        item = _resolve_top(st)
        _process_breaks(st)  # a breaking hit just resolved? end channels, release mana
        st.passes = 0
        st.priority = None   # next item (or close) — re-seeded by _advance
        _offer_reactions(st, _post_trigger_ctx(st, item, st.log[start:]))
    else:
        st.priority = _next_priority_after(st, actor.id)


# --------------------------------------------------------------------------- #
# Enemy reactions (Design Update 04 §F-3.2 / §F-7.4): trigger-typed, one per enemy
# per window, cross-turn reuse gated by per-component cooldowns.
# --------------------------------------------------------------------------- #
def _reactive_rules(e: EnemyState) -> List[Component]:
    """The enemy's reactive components in evaluation order (priority ascending, ties by
    authoring order)."""
    return sorted([c for c in e.components if c.timing == "reactive"],
                  key=lambda c: c.priority)


def _pre_trigger_ctx(st: GameState) -> dict:
    """The trigger context for reactions evaluated BEFORE the stack top resolves: the
    item under answer is the current top (a player play or an enemy action)."""
    return {"phase": "pre", "stack_top": st.stack[-1] if st.stack else None,
            "hits": [], "deaths": [], "attacker": None}


def _post_trigger_ctx(st: GameState, item: Optional[StackItem], events: List[Event]) -> dict:
    """The trigger context for reactions evaluated AFTER a resolution: which combatants
    took damage (`hits`), which enemies died (`deaths`), and who dealt it (`attacker` =
    the resolved item's source), read from the events the resolution emitted."""
    hits = [ev.data.get("target") for ev in events if ev.type == "damage"]
    deaths = [ev.data.get("enemy") for ev in events if ev.type == "enemy_died"]
    downs = [ev.data.get("character") for ev in events if ev.type == "incapacitated"]
    heals = [ev.data.get("target") for ev in events
             if ev.type in ("heal", "wound_mend")]
    return {"phase": "post", "stack_top": None, "hits": hits, "deaths": deaths,
            "downs": downs, "heals": heals,
            "attacker": item.source_id if item is not None else None}


def _offer_reactions(st: GameState, ctx: dict) -> bool:
    """Offer the enemy side its reaction to `ctx` (§F-7.4 step 3). Across all in-play
    enemies (canonical R-6 order) that have not yet reacted this window, gather the
    single top-priority eligible reactive rule whose trigger matches; the highest-
    priority one across the side fires, pushing a new stack action and reopening the
    party's window. One reaction per call — the caller returns to player priority.

    Termination: firing consumes both the per-window slot (`reacted_window`) and the
    component's cooldown (≥1 turn), so the eligible set strictly shrinks."""
    best = None  # (priority, order_index, enemy, component)
    for order, e in enumerate(_ordered(st.living_enemies())):
        if e.id in st.reacted_window:
            continue
        for comp in _reactive_rules(e):
            if not _component_eligible(st, e, comp):
                continue
            if not _trigger_matches(st, e, comp, ctx):
                continue
            cand = (comp.priority, order, e, comp)
            if best is None or cand[:2] < best[:2]:
                best = cand
            break  # one candidate per enemy (its top-priority matching rule)
    if best is None:
        return False
    _, _, e, comp = best
    _fire_reaction(st, e, comp, ctx)
    return True


def _trigger_matches(st: GameState, e: EnemyState, comp: Component, ctx: dict) -> bool:
    """Whether `comp`'s trigger fires for this context (§F-3.2). Pre-resolution triggers
    read the stack top; post-resolution triggers read what the resolution did."""
    trig = comp.trigger
    top = ctx.get("stack_top")
    if ctx["phase"] == "pre":
        if trig == "on_spell_cast":
            return top is not None and top.source_side == "party" and top.kind == "spell"
        if trig == "on_attack":
            # A hero's attack sits on the stack — a duellist's window: parry it
            # (counter, filter "attack"), shield the victim, or riposte first.
            return top is not None and top.source_side == "party" and top.kind == "attack"
        if trig == "on_targeted":
            return top is not None and top.source_side == "party" and top.target_id == e.id
        if trig == "on_incoming_lethal":
            return top is not None and _would_be_lethal(st, top, e)
        return False
    # post-resolution
    hits, deaths = ctx.get("hits", []), ctx.get("deaths", [])
    if trig == "on_hit":
        return e.id in hits
    if trig == "on_ally_hit":
        return any(h != e.id and st.enemy(h) is not None for h in hits)
    if trig == "on_ally_death":
        return any(d != e.id for d in deaths)
    if trig == "on_enrage":
        # §F-9 enrage: fires in the first reaction window after its boss crossed the
        # 25% threshold (the crossing set `enraged` in _after_damage). Once-per-
        # encounter bookkeeping (forced at load) keeps this a single firing.
        return e.is_boss and e.enraged
    if trig == "on_hero_downed":
        # A hero was incapacitated by this resolution — the pack surges.
        return bool(ctx.get("downs"))
    if trig == "on_hero_healed":
        # A hero regained HP (or closed a wound) this resolution — punish the medic.
        return any(st.character(h) is not None for h in ctx.get("heals", []))
    if isinstance(trig, str) and trig.startswith("on_self_below_"):
        # `on_self_below_40`: this enemy was hit this resolution and now sits below
        # the named percentage of max HP — a minion-grade "bloodied" moment (the
        # generalised enrage). Reads the hit list so it fires on the crossing
        # resolution; give it once_per_encounter (or a cooldown) to keep it a moment.
        try:
            pct = int(trig.rsplit("_", 1)[1])
        except ValueError:
            return False
        return (e.id in hits and e.alive
                and e.effective_hp * 100 < pct * e.max_hp)
    if isinstance(trig, str) and trig.startswith("on_ally_below_"):
        # `on_ally_below_50` (§F-3.2): an ally was hit this resolution and now sits
        # below the named percentage of its max HP. Reads the hit list (not the whole
        # board) so the trigger fires on the crossing event, not every window after.
        try:
            pct = int(trig.rsplit("_", 1)[1])
        except ValueError:
            return False
        for hid in hits:
            ally = st.enemy(hid)
            if (ally is not None and ally.id != e.id and ally.alive
                    and ally.effective_hp * 100 < pct * ally.max_hp):
                return True
        return False
    return False


def _would_be_lethal(st: GameState, item: StackItem, e: EnemyState) -> bool:
    """Whether resolving `item` would drop `e` to ≤0 effective HP — the total of its
    constant `deal_damage` aimed at `e`. (Dynamic/prevented damage isn't modelled here;
    the common targeted spell/attack is.)"""
    if item.target_id != e.id:
        return False
    total = 0
    for eff in item.effects:
        if getattr(eff, "kind", None) == "deal_damage":
            amt = getattr(eff, "amount", 0)
            if isinstance(amt, int):
                total += amt
    return total >= e.effective_hp


def _reaction_target(st: GameState, e: EnemyState, comp: Component, ctx: dict):
    """Resolve a reaction's target. `trigger_source` is the player who caused the
    trigger — the caster/attacker (the stack top's source pre-resolution, the resolved
    item's source post-resolution); other rules resolve as for a proactive component."""
    if comp.target_rule == "trigger_source":
        src = ctx["stack_top"].source_id if ctx.get("stack_top") else ctx.get("attacker")
        return st.combatant(src)
    return _component_target(st, e, comp)


def _reaction_counters_stack(comp: Component) -> bool:
    """A reaction whose verbs include `counter` answers the STACK TOP itself (an
    enemy counterspell, §F-3.2): its target is the action under answer, not a
    combatant."""
    return any(getattr(v, "kind", None) == "counter" for v in comp.verbs)


def _fire_reaction(st: GameState, e: EnemyState, comp: Component, ctx: dict) -> None:
    """Push an enemy reaction onto the stack and reopen the party's window. Consumes
    the per-window slot and starts the component's cooldown."""
    if _reaction_counters_stack(comp):
        # An enemy counterspell aims at the stack action that tripped the trigger
        # (pre-resolution only — there is nothing to counter post-resolution). The
        # "#uid" form is the same handle a player's counter uses, and the counter
        # itself sits on the stack first: the party can counter the counter.
        top = ctx.get("stack_top")
        if top is None:
            return
        target, tid = None, f"#{top.uid}"
    else:
        target = _reaction_target(st, e, comp, ctx)
        tid = target.id if target is not None else None
    _start_cooldown(st, e, comp.id)
    st.reacted_window.append(e.id)
    label = comp.telegraph or comp.archetype or "Reaction"
    # A reaction is a TRIGGERED ability in the GDD taxonomy (Retaliate) — so a
    # "triggered"/"ability" counter answers it while "spell" doesn't — unless
    # the component is spell-classed (an arcane riposte counters as a spell).
    kind = "spell" if comp.action_type == "spell" else "triggered"
    _push(st, StackItem(kind=kind, source_id=e.id, source_side="enemy",
                        label=label, effects=list(comp.verbs), target_id=tid))
    st.priority = None   # reopen the window; party order re-seeded by _advance
    st.passes = 0
    _log(st, "enemy_react", f"{e.name} reacts with {label}.",
         enemy=e.id, label=label, target=tid, trigger=comp.trigger)


def _do_end_turn(st: GameState, action: Action) -> None:
    actor = st.character(action.actor_id)
    if actor.stunned > 0:  # a stunned turn ends — one stack of the stun is spent
        actor.stunned -= 1
        _log(st, "stun_spent", f"{actor.name} shakes off the stun "
             f"({actor.stunned} turn(s) remain).", character=actor.id)
    actor.turn_ended = True
    st.priority = None
    suffix = " (auto)" if getattr(action, "auto", False) else ""
    _log(st, "end_turn", f"{actor.name} ends their turn{suffix}.", character=actor.id,
         auto=bool(getattr(action, "auto", False)))


def _do_attack(st: GameState, action: Action) -> None:
    """The free basic attack (the proactive Attack): deal damage = Power."""
    actor = st.character(action.actor_id)
    if actor.acted_mode is None:
        _gain_gauge(st, actor, 2)  # taking your proactive action (D8-3.3)
    actor.acted_mode = "attack"
    actor.used_attack = True
    if actor.attack_mode == "melee":  # Update 02 §M-B.3: stepping up commits you to Front
        actor.committed = "front"
    hits = 2 if _has_kw(actor, "double_strike") else 1  # double strike: strikes twice
    effects = [DealDamage(amount=actor.current_power, target=t_chosen("enemy", targeted=True))
               for _ in range(hits)]
    # attack_power = base Power so resolution recomputes damage from the actor's CURRENT
    # power (a reaction-window pump/wound changes what lands — R-7).
    # A First Strike swing made into an open window reacts (stacks above, resolves first);
    # the normal main-phase attack opens a fresh window at party order.
    reactive = bool(st.stack)
    _push(st, StackItem(kind="attack", source_id=actor.id, source_side="party",
                        label="Basic Attack", effects=effects, target_id=action.target_id,
                        attack_mode=actor.attack_mode, attack_power=actor.power))
    _open_window(st, actor.id, reactive=reactive)
    tgt = st.combatant(action.target_id)
    _log(st, "attack_declared",
         f"{actor.name} attacks {tgt.name} ({actor.attack_mode} Power {actor.current_power}).",
         character=actor.id, target=action.target_id, power=actor.current_power,
         mode=actor.attack_mode)
    # On-attack channel triggers fire at DECLARATION (MTG: attack triggers go on
    # the stack above the swing and resolve before its damage). A stacked trigger
    # (chosen target) lands on top; an inline one resolves before the window opens.
    _fire_event(st, "attack", actor)


def _do_cast(st: GameState, action: Action) -> None:
    """Cast a spell. Sorcery-speed spells (sorceries/channeled) are the proactive
    Cast — a Cast turn may cast several if mana allows; instants are free."""
    actor = st.character(action.actor_id)
    card = _card_in_hand(actor, action.card_id)
    reactive = bool(st.stack)  # a cast made inside an open window stacks above
    x = max(0, int(action.x or 0))
    paid = _pay(actor, card, action.mana, x=x)
    actor.hand.remove(card)
    actor.graveyard.append(card)  # the card goes to the graveyard at once (R-9)
    if card.timing in _SORCERY_SPEED and not reactive:
        if actor.acted_mode is None:
            _gain_gauge(st, actor, 2)  # taking your proactive action (D8-3.3)
        actor.acted_mode = "cast"  # choosing Cast; further sorcery-speed casts ok
    # +1 gauge per point of mana spent (generic + coloured; X counts; a channel
    # charges its reserved cost once, at cast) — D8-3.3.
    _gain_gauge(st, actor, len(paid))
    reserved = list(paid) if card.timing == Timing.channeled else []
    _push(st, StackItem(kind="spell", source_id=actor.id, source_side="party",
                        label=card.name, effects=list(card.effects),
                        target_id=action.target_id, targets=action.targets,
                        card_id=card.id,
                        card=card, reserved=reserved, mode=action.mode, x=x,
                        cast_mode="reaction" if reactive else "action"))
    _open_window(st, actor.id, reactive=reactive)
    tgt = st.combatant(action.target_id)
    _log(st, "cast", f"{actor.name} casts {card.name}"
         + (f" on {tgt.name}" if tgt else "") + f". Mana: {_mana_str(actor.pool)}.",
         character=actor.id, card=card.id, target=action.target_id)
    # `spells_cast` conditions count this cast; on-cast channel triggers fire now
    # (at cast, MTG-style — even if the spell is later countered).
    actor.spells_cast_turn += 1
    _fire_event(st, "spell_cast", actor, spell_timing=card.timing.value)


def _do_defend(st: GameState, action: Action) -> None:
    """The free defensive action: gain temporary HP — a positive `temp_mod` buffer
    that raises effective_hp and expires at End (R-7). (Magnitude is a placeholder
    until gear/flavour set it.)"""
    actor = st.character(action.actor_id)
    if actor.acted_mode is None:
        _gain_gauge(st, actor, 2)  # the action itself (D8-3.3)
    actor.acted_mode = "defend"
    actor.used_defend = True
    actor.temp_mod += _DEFEND_TEMP_HP
    # …plus +1 per point of temp HP granted as the source: Defend now earns +5
    # total — turtling charges your finisher, at the price of tempo (D8-3.3).
    _gain_gauge(st, actor, _DEFEND_TEMP_HP)
    st.priority = None
    _log(st, "defend", f"{actor.name} defends (+{_DEFEND_TEMP_HP} temp HP).",
         character=actor.id, temp_mod=actor.temp_mod)


def _mitigate_value(combatant) -> int:
    """X = ceil(current Power / 2) (Update 02 §M-A.2) — read at resolution, never 0
    for a Power-1 character."""
    return math.ceil(max(0, combatant.current_power) / 2)


def _do_move(st: GameState, action: Action) -> None:
    """The voluntary Move: queue a destination row (Update 02 §M-B.4). It writes the
    `pending_voluntary` slot only — it grants no reach and the body relocates at End
    step. Costs the proactive action unless the mover has haste (then it is free)."""
    actor = st.character(action.actor_id)
    actor.pending_voluntary = action.target_id  # the chosen destination row
    if not _has_kw(actor, "haste"):
        if actor.acted_mode is None:
            _gain_gauge(st, actor, 2)  # taking your proactive action (D8-3.3)
        actor.acted_mode = "move"
    st.priority = None
    _log(st, "move", f"{actor.name} will move to {action.target_id} (resolves at End step).",
         character=actor.id, destination=action.target_id)


def _do_mitigate(st: GameState, action: Action) -> None:
    """The free, once-per-turn defensive reaction (Update 02 §M-A): record the
    declared Mitigate on the answered attack (applied per hit at resolution). In ally
    mode it forces the mitigator's committed position onto the protected ally's row."""
    actor = st.character(action.actor_id)
    actor.used_mitigate = True
    top = st.stack[-1]
    top.mitigate_by = actor.id
    top.mitigate_for = action.target_id
    if action.target_id != actor.id:  # ally mode: interceding pulls you off position (§M-A.6)
        ally = st.character(action.target_id)
        if ally is not None:
            actor.committed = ally.row
        _log(st, "mitigate", f"{actor.name} mitigates for {ally.name if ally else action.target_id} "
             f"(X={_mitigate_value(actor)}, moves to {actor.committed}).", character=actor.id,
             target=action.target_id, value=_mitigate_value(actor))
    else:
        _log(st, "mitigate", f"{actor.name} mitigates (X={_mitigate_value(actor)}).",
             character=actor.id, value=_mitigate_value(actor))
    _do_pass(st, Action(kind="pass", actor_id=actor.id))


def _apply_mitigation(st: GameState, item: StackItem, target, amount: int):
    """Apply a declared Mitigate to one attack hit (Update 02 §M-A.3). Returns the
    (possibly redirected) target and the post-mitigation amount. Only the hits aimed
    at the protected character are affected; X is read now (Power can have shifted)."""
    if item.mitigate_by is None or target is None or _tid(target) != item.mitigate_for:
        return target, amount
    mitigator = st.character(item.mitigate_by)
    if mitigator is None:
        return target, amount
    x = _mitigate_value(mitigator)
    landing = mitigator if item.mitigate_for != item.mitigate_by else target  # ally → redirect
    return landing, max(0, amount - x)


def _do_drop_channels(st: GameState, action: Action) -> None:
    """Voluntary drop (a free action): end one named channel (`card_id`) or, when no
    card is named, all droppable channels at once. Only channels started on an earlier
    turn are droppable (a same-turn channel can't be cancelled)."""
    actor = st.character(action.actor_id)
    droppable = _voluntarily_droppable(st, actor)
    if action.card_id is not None:
        channel = next((ch for ch in droppable if ch.card.id == action.card_id), None)
        if channel is None:
            return
        _log(st, "drop_channels", f"{actor.name} drops {channel.card.name}.", character=actor.id)
        _end_channels(st, actor, [channel], reason="voluntary")
        return
    if not droppable:
        return
    _log(st, "drop_channels", f"{actor.name} drops concentration.", character=actor.id)
    _end_channels(st, actor, droppable, reason="voluntary")


def _do_use_skill(st: GameState, action: Action) -> None:
    """The authored once-per-encounter Skill (D8-3.1): instant speed, free of the
    proactive action, castable in any window an instant fits. It lands on the
    stack as an ACTIVATED ability — a spell-filter counter cannot answer it; an
    ability/action-filter counter can. May carry a mana cost, paid normally."""
    actor = st.character(action.actor_id)
    card = actor.skill
    reactive = bool(st.stack)
    x = max(0, int(action.x or 0))
    _pay(actor, card, action.mana, x=x)
    actor.skill_used = True
    _push(st, StackItem(kind="activated", source_id=actor.id, source_side="party",
                        label=f"{card.name} (Skill)", effects=list(card.effects),
                        target_id=action.target_id, targets=action.targets,
                        card=card, mode=action.mode, x=x,
                        cast_mode="reaction" if reactive else "action"))
    _open_window(st, actor.id, reactive=reactive)
    tgt = st.combatant(action.target_id)
    _log(st, "skill", f"{actor.name} uses their Skill — {card.name}"
         + (f" on {tgt.name}" if tgt else "") + ".",
         character=actor.id, card=card.id, target=action.target_id)
    _gain_gauge(st, actor, 5)  # using your Skill charges the gauge (D8-3.3)


def _do_use_ultimate(st: GameState, action: Action) -> None:
    """The authored once-per-encounter Ultimate (D8-3.2): an action (sorcery
    speed, consumes the proactive action), castable only on a full gauge, never
    costs mana — the gauge is the cost, spent to 0 as it is cast. An activated
    ability on the stack: a Negate does not stop a limit break."""
    actor = st.character(action.actor_id)
    card = actor.ultimate
    actor.ultimate_used = True
    actor.ultimate_gauge = 0
    actor.acted_mode = "ultimate"
    _push(st, StackItem(kind="activated", source_id=actor.id, source_side="party",
                        label=f"{card.name} (Ultimate)", effects=list(card.effects),
                        target_id=action.target_id, targets=action.targets,
                        card=card, mode=action.mode, cast_mode="action"))
    _open_window(st, actor.id, reactive=False)
    tgt = st.combatant(action.target_id)
    _log(st, "ultimate", f"{actor.name} unleashes their Ultimate — {card.name}"
         + (f" on {tgt.name}" if tgt else "") + "!",
         character=actor.id, card=card.id, target=action.target_id)


_DEFEND_TEMP_HP = 3   # placeholder; GDD leaves Defend's amount to gear/flavour


def _push(st: GameState, item: StackItem) -> StackItem:
    """Push an item onto the stack, stamping it with a unique id so a counter can
    name the exact action it answers."""
    st.stack_seq += 1
    item.uid = st.stack_seq
    st.stack.append(item)
    return item


def _open_window(st: GameState, actor_id: str, reactive: bool) -> None:
    """After a player adds to the stack, seed the reaction window: the CASTER
    speaks first (they may respond to their own action — they hit Pass first),
    then priority moves through the rest of the party in turn order. A proactive
    add opens a FRESH window, so the per-window reaction tracker resets here;
    a reactive add is a response inside the existing window."""
    st.passes = 0
    if not reactive:
        st.reacted_window = []
    st.priority = actor_id if st.character(actor_id) is not None else None


def _next_priority_after(st: GameState, actor_id: str) -> str:
    ids = [c.id for c in _party_ordered(st)]  # the fixed turn order
    if actor_id in ids:
        return ids[(ids.index(actor_id) + 1) % len(ids)]
    return ids[0]


# --------------------------------------------------------------------------- #
# Resolving the stack
# --------------------------------------------------------------------------- #
def _resolve_top(st: GameState) -> StackItem:
    """Resolve and return the popped top item (the caller reads it to build the
    post-resolution reaction context — §F-7.4)."""
    item = st.stack.pop()
    _log(st, "resolve", f"{item.label} resolves.", label=item.label, source=item.source_id)
    # A channeled card CAST doesn't run its effects once — it becomes a held
    # channel. Only the cast (kind "spell") starts it: a pushed triggered ability
    # (kind "triggered") carries the same card purely for slot descriptors and
    # labels, and resolves its effects normally.
    if item.card is not None and item.card.timing == Timing.channeled and item.kind == "spell":
        _start_channel(st, item)
        return item
    # An enemy channel-component's intent likewise becomes a held channel (§8).
    if item.starts_channel:
        _start_enemy_channel(st, item)
        return item
    ctx = _new_ctx(st, item)
    _resolve_effect_list(st, item, item.effects, ctx)
    return item


def _cost_total(card: Optional[Card], x: int = 0) -> int:
    """A card's converted casting cost: generic + colour pips + the X paid."""
    if card is None:
        return int(x or 0)
    return card.cost.generic + sum(card.cost.colors.values()) + max(0, int(x or 0))


def _channel_ctx(st: GameState, holder, ch) -> dict:
    """The resolution context for a held channel's triggered effects: capacity plus
    the `x`/`casting_cost` the card was cast with (enemy channels have no card),
    and the party size for `party_size` refs."""
    card = getattr(ch, "card", None)
    x = getattr(ch, "x", 0)
    return {"capacity": getattr(holder, "capacity", 0), "x": x,
            "casting_cost": _cost_total(card, x), "party_size": len(st.party),
            "caster_obj": holder}


def _new_ctx(st: GameState, item: StackItem) -> dict:
    """A fresh per-resolution context: mana capacity for `mana_capacity` values,
    the cast's X / casting cost, and the per-site target bindings for an
    independent multi-target card."""
    ctx: dict = {}
    src = st.character(item.source_id)
    ctx["capacity"] = src.capacity if src is not None else 0
    ctx["x"] = item.x
    ctx["casting_cost"] = _cost_total(item.card, item.x)
    ctx["party_size"] = len(st.party)
    ctx["caster_obj"] = st.combatant(item.source_id)
    if item.targets:
        top = item.effects
        modal = next((e for e in item.effects
                      if e.kind == "modal" and getattr(e, "trigger", None) is None), None)
        if modal is not None:
            top = _effects_of_mode(item, modal)
        ctx["site_target"] = {key: tid for (key, *_), tid
                              in zip(_target_sites(top, item.card), item.targets)}
    return ctx


def _resolve_effect_list(st: GameState, item: StackItem, effects, ctx: dict) -> None:
    """Resolve a stack item's top-level effects in order. When a top-level
    move_card needs the player to pick which cards move (more legal candidates than
    it moves), pause: record a PendingChoice with the not-yet-resolved effects and
    return. `_do_choose_card` performs the move and resumes here. Effects nested in
    a conditional/modal keep auto-picking (handled inside `_resolve_effect`).

    The pauses apply regardless of the effect's `trigger`: everything routed
    through this list is a stack-style resolution (a cast, a channel_break /
    channel_start firing), where the player must get their pick — a break-trigger
    scry pauses exactly like a sorcery's. Upkeep/event ticks resolve effects
    directly via `_resolve_effect` and stay non-interactive."""
    for i, effect in enumerate(effects):
        kind = getattr(effect, "kind", None)
        # A TRIGGERED modal firing in this list (channel_start) has had no cast-time
        # mode pick — pause for it; _do_choose_mode resolves the pick and resumes.
        if (kind == "modal" and getattr(effect, "trigger", None) is not None
                and item.mode is None):
            char = st.character(item.source_id)
            options = _modal_pick_options(effect)
            if char is not None and len(options) > 1:
                st.pending_choice = PendingChoice(
                    kind="mode", chooser_id=char.id, effect=effect, candidates=[],
                    need=1, remaining=list(effects[i + 1:]), item=item,
                    resolve_now=True)
                return
        if kind == "move_card":
            char = st.character(item.source_id)
            if char is not None:
                cands = _move_candidates(char, effect, ctx)
                if len(cands) > effect.count:  # a genuine "which cards?" choice
                    st.pending_choice = PendingChoice(
                        chooser_id=char.id, effect=effect, candidates=cands,
                        need=effect.count, remaining=list(effects[i + 1:]), item=item)
                    return
        # A top-level scry pauses for the player to order the revealed top cards
        # (top/bottom, and the order on top). Nested scry (modal/conditional) keeps
        # the non-interactive reveal in `_resolve_effect`.
        if kind == "scry" and _raise_scry_choice(st, item, effect, ctx, i, effects):
            return
        _resolve_effect(st, item, effect, ctx)


def _effects_of_mode(item: StackItem, modal_effect) -> List:
    """The chosen mode(s)' effects for a modal card (picked at cast).

    A single-choice modal ("choose one") stores the mode INDEX. A multi-choice
    modal ("choose two" / "choose one or more" — `choose`>1 or `or_more`) stores a
    BITMASK over mode indices; its effects are the chosen modes' effects
    concatenated in mode order — the same order `_mode_specs` enumerates, so the
    per-site target zip in `_new_ctx` stays aligned."""
    if _modal_is_multi(modal_effect):
        mask = item.mode if item.mode is not None else 0
        idxs = [i for i in range(len(modal_effect.modes)) if (mask >> i) & 1] or [0]
        return [e for i in idxs for e in modal_effect.modes[i].effects]
    idx = item.mode if item.mode is not None else 0
    idx = max(0, min(idx, len(modal_effect.modes) - 1))
    return list(modal_effect.modes[idx].effects)


def _modal_is_multi(modal_effect) -> bool:
    """True for a multi-select modal (Cryptic Command's "choose two"): the mode an
    action/stack-item carries is then a bitmask of mode indices, not an index."""
    return ((getattr(modal_effect, "choose", 1) or 1) > 1
            or bool(getattr(modal_effect, "or_more", False)))


# --------------------------------------------------------------------------- #
# Channels: hold, continuous effects, break/release (GDD §8)
# --------------------------------------------------------------------------- #
def _is_continuous(effect) -> bool:
    return (getattr(effect, "trigger", None) is None
            and getattr(effect, "duration", None) == Duration.while_channeled)


def _start_channel(st: GameState, item: StackItem) -> None:
    """Hold a resolved channeled card on its caster: reserve its mana and apply
    its continuous effects. Recurring effects are armed (they fire at upkeep);
    `channel_start` effects (the ETB analogue) fire once, now."""
    holder = st.character(item.source_id)
    channel = Channel(card=item.card, holder_id=holder.id,
                      reserved=list(item.reserved), target_id=item.target_id,
                      started_turn=st.turn, x=item.x)
    holder.channels.append(channel)
    _log(st, "channel_start",
         f"{holder.name} channels {item.card.name} (reserves {_mana_str(channel.reserved)}).",
         character=holder.id, card=item.card.id, reserved=list(channel.reserved))
    for effect in item.card.effects:
        if _is_continuous(effect):
            _apply_continuous(st, channel, effect)
    # channel_start effects resolve as a list so an interactive scry/move_card
    # pauses for the player's pick (same as any stack resolution).
    starts = [e for e in item.card.effects
              if getattr(e, "trigger", None) == "channel_start"]
    if starts:
        _resolve_effect_list(st, item, starts, _channel_ctx(st, holder, channel))
    # State-based check: a wound aura that drops a creature to ≤0 effective HP kills it
    # now (GDD §8: a −X/−X that empties toughness is lethal). The death sticks — the
    # channel keeps holding, its target simply gone, until the caster drops it. Losing
    # an aura's target is NOT a break cause (only a ≥25% hit, incapacitation, or a
    # voluntary drop is), so the caster's other channels are untouched.
    _reap_aura_kills(st)


def _start_enemy_channel(st: GameState, item: StackItem) -> None:
    """Hold a resolved enemy channel-component (§8, enemy side): apply its
    continuous verbs, fire its one-shot verbs once, and arm its `upkeep` verbs.
    The channel then persists until broken — one ≥25%-max-HP hit, or the
    channeler's death / bounce / suspension (see _break_enemy_channels)."""
    enemy = st.enemy(item.source_id)
    if enemy is None or not enemy.alive:
        return
    ch = EnemyChannel(component_id=item.component_id or "", name=item.label,
                      effects=list(item.effects), holder_id=enemy.id,
                      target_id=item.target_id, started_turn=st.turn)
    enemy.channels.append(ch)
    _log(st, "channel_start",
         f"{enemy.name} begins channeling {item.label} — break it with one hit of "
         f"≥{_break_threshold(enemy)} damage, or remove the channeler.",
         enemy=enemy.id, component=ch.component_id, label=item.label,
         threshold=_break_threshold(enemy))
    for effect in ch.effects:
        if _is_continuous(effect):
            for target in _enemy_channel_targets(st, ch, effect):
                _apply_static(st, target, effect, +1, holder_id=enemy.id)
    # One-shot verbs (not continuous, not recurring) and explicit `channel_start`
    # verbs fire once as it starts.
    once = [e for e in ch.effects
            if not _is_continuous(e)
            and getattr(e, "trigger", None) in (None, "channel_start")]
    if once:
        _resolve_effect_list(st, item, once, _new_ctx(st, item))
    _reap_aura_kills(st)


def _enemy_channel_targets(st: GameState, ch: EnemyChannel, effect) -> List:
    """The creature(s) an enemy channel's continuous effect covers. Verb-target
    convention matches one-shot enemy verbs: `self` = the channeler, `all`+side
    resolves from the card-authoring perspective ("ally" = the party), `chosen` =
    the single target picked when the intent declared."""
    desc = getattr(effect, "target", None)
    mode = getattr(desc, "mode", None) if not isinstance(desc, str) else None
    if mode == TargetMode.self_:
        holder = st.enemy(ch.holder_id)
        return [holder] if holder is not None else []
    if mode == TargetMode.all:
        side = desc.side.value if getattr(desc, "side", None) is not None else "ally"
        item = StackItem(kind="ability", source_id=ch.holder_id, source_side="enemy",
                         label=ch.name, effects=[])
        return _creatures_on_side(st, side, item, desc)
    tgt = st.combatant(ch.target_id)
    return [tgt] if tgt is not None else []


def _break_enemy_channels(st: GameState, enemy: EnemyState, reason: str) -> None:
    """End ALL of an enemy's channels (all-or-nothing, like a player break §8):
    lift their continuous effects and log what the party just turned off. A
    `channel_break` verb fires as a respondable stack trigger, same as the party
    side — breaking the ritual can spring its dying sting."""
    if not enemy.channels:
        return
    for ch in list(enemy.channels):
        for effect in ch.effects:
            if _is_continuous(effect):
                for target in _enemy_channel_targets(st, ch, effect):
                    _apply_static(st, target, effect, -1, log_it=False,
                                  holder_id=enemy.id)
        _log(st, "channel_end", f"{enemy.name}'s {ch.name} is broken ({reason}).",
             enemy=enemy.id, component=ch.component_id, label=ch.name, reason=reason)
    ended = list(enemy.channels)
    enemy.channels = []
    for ch in ended:
        _fire_channel_break(st, enemy.id, "enemy", ch.name, ch.effects, ch.target_id)


def _reap_aura_kills(st: GameState) -> None:
    """Remove board creatures a just-applied continuous aura reduced to ≤0 effective
    HP (the non-damage kill path). Enemies/tokens die immediately; a PC wounded to ≤0
    is a temporary downing that resolves at End (R-7), so it is left to `_reap_dead`."""
    for c in list(st.enemies) + list(st.tokens):
        if c.effective_hp <= 0:
            _after_damage(st, c)


def _continuous_targets(st: GameState, channel: Channel, effect) -> List:
    """The creature(s) a channel's continuous effect covers: the holder (self), a
    whole side (anthem 'all'), or the single aura target chosen at cast."""
    desc = getattr(effect, "target", None)
    mode = getattr(desc, "mode", None) if not isinstance(desc, str) else None
    if mode == TargetMode.self_:
        holder = st.character(channel.holder_id)
        return [holder] if holder is not None else []
    if mode == TargetMode.all:
        side = desc.side.value if getattr(desc, "side", None) is not None else "ally"
        if side == "enemy":
            return list(st.living_enemies())
        if side == "any":
            return list(st.living_party()) + list(st.living_tokens()) + list(st.living_enemies())
        return list(st.living_party()) + list(st.living_tokens())
    tgt = st.combatant(channel.target_id)
    return [tgt] if tgt is not None else []


_STAT_CONTINUOUS = ("pump", "counters", "wound")  # auras that ride the temp layers


def _apply_static(st: GameState, target, effect, sign: int, log_it: bool = True,
                  holder_id: Optional[str] = None, x: int = 0) -> None:
    """Apply (sign +1) or lift (sign −1) one continuous effect on one creature.

    Stat auras (pump/counters add, wound subtracts) ride `power_bonus`/`temp_mod`
    and are re-applied each end step (those layers reset), so reapply passes
    `log_it=False` to stay quiet. `holder_id` is the channeler — needed by a
    continuous taunt (e.g. Lure) to know which character enemies are forced onto."""
    k = effect.kind
    if k == "taunt":
        # A continuous taunt (Lure): while channeled, every covered enemy is forced
        # to target the channeler. `taunted_by` resets each end step, so this is
        # re-asserted every turn (see _reapply_channel_stats) — the enemy heuristic
        # (_choose_enemy_attack) reads it when declaring the next intent, and we also
        # redirect any intent already declared this turn (the cast turn).
        if not isinstance(target, EnemyState):
            return
        if sign > 0:
            holder = st.character(holder_id) if holder_id is not None else None
            # A hexproof holder still lures: taunt redirects ATTACKS, and attacks
            # land on hexproof (it wards spells/abilities only — Update 06).
            if holder is not None and holder.alive:
                target.taunted_by = holder_id
                if target.intent is not None:
                    target.intent.target_id = holder_id
                if log_it:
                    _log(st, "taunt", f"{target.name} is lured into targeting {holder.name}.",
                         enemy=target.id, by=holder_id)
        elif holder_id is None or target.taunted_by == holder_id:
            target.taunted_by = None
        return
    if k == "prevent":
        # A channeled `prevent` (e.g. Pacifism's `prevent attack`) rides the target
        # as an "all"-uses shield for as long as the channel holds. It is wiped each
        # End step and re-asserted here (see _reapply_channel_stats), mirroring the
        # stat auras. Removal on break lifts one matching shield.
        param = effect.parameter
        if sign > 0:
            if not any(t.parameter == param for t in target.prevent_tags):
                target.prevent_tags.append(PreventTag(param, None))
            # Pacifying an enemy also cancels any attack intent it already declared.
            if (param in _ACTION_PREVENT and isinstance(target, EnemyState)
                    and target.intent is not None):
                target.intent = None
            if log_it:
                _log(st, "prevent", f"{target.name} — {param} prevented (channel).",
                     target=_tid(target), parameter=param)
        else:
            for t in list(target.prevent_tags):
                if t.parameter == param:
                    target.prevent_tags.remove(t)
                    break
        return
    if k == "grant_keyword":
        for kw in effect.keywords:
            if sign > 0:
                target.keywords[kw] = "while_channeled"
            else:
                target.keywords.pop(kw, None)
        if log_it:
            verb = "gains" if sign > 0 else "loses"
            _log(st, "grant_keyword", f"{target.name} {verb} {', '.join(effect.keywords)} (channel).",
                 target=_tid(target), keywords=list(effect.keywords))
    elif k == "exile":
        # A channeled exile suspends the target while the channel holds (sign +1)
        # and returns it when the channel breaks (sign −1). Spell exile never reaches
        # here — it resolves once through `_r_exile` and removes the enemy for good.
        if isinstance(target, EnemyState):
            if sign > 0:
                if target.is_boss and not target.in_execute_window:
                    if log_it:
                        _log(st, "boss_immune", f"{target.name} shrugs off the exile — "
                             "a boss can't be removed above 25% HP.", enemy=target.id)
                    return
                target.exiled = True
                target.intent = None  # a suspended enemy telegraphs nothing
                _break_enemy_channels(st, target, "channeler suspended")
                if target.id in st.acted_enemies:
                    st.acted_enemies.remove(target.id)
                _purge_stack_from(st, target.id, "exiled")  # its swings go with it
                if log_it:
                    _log(st, "exiled", f"{target.name} is exiled while the channel holds.",
                         target=target.id, level=target.level, channeled=True)
            else:
                target.exiled = False
                if log_it:
                    _log(st, "returns", f"{target.name} returns from exile.", target=target.id)
        elif log_it:
            _log(st, "unhandled",
                 "(channeled exile is only modelled for enemies this milestone)", kind=k)
    elif k in _STAT_CONTINUOUS and hasattr(target, "power_bonus"):
        polarity = -1 if k == "wound" else 1  # wound is a −X/−X aura (R-7)
        # Stat refs (pump X aura, +1 per player) resolve against the holder's
        # current state. x/party_size are constant for a channel's life; a
        # capacity ref can drift between apply and lift within one turn — the
        # temp layers reset every end step, so any drift clears at End.
        holder = st.combatant(holder_id) if holder_id is not None else None
        ctx = {"capacity": getattr(holder, "capacity", 0), "x": x,
               "party_size": len(st.party), "caster_obj": holder,
               "target_obj": target}
        power = _value(effect.power, ctx)
        toughness = _value(effect.toughness, ctx)
        target.power_bonus += sign * polarity * power
        target.temp_mod += sign * polarity * toughness  # re-applied every end step
        if log_it:
            verb = "gains" if sign > 0 else "loses"
            sgn = "-" if polarity < 0 else "+"
            _log(st, "aura", f"{target.name} {verb} {sgn}{power}/{sgn}{toughness} "
                 f"(channel).", target=_tid(target))
    elif log_it:
        _log(st, "unhandled", f"(continuous '{k}' not modelled this milestone)", kind=k)


def _apply_continuous(st: GameState, channel: Channel, effect) -> None:
    for target in _continuous_targets(st, channel, effect):
        _apply_static(st, target, effect, +1, holder_id=channel.holder_id, x=channel.x)


def _remove_continuous(st: GameState, channel: Channel, effect) -> None:
    for target in _continuous_targets(st, channel, effect):
        _apply_static(st, target, effect, -1, holder_id=channel.holder_id, x=channel.x)


# Continuous effects that reset each end step and must be re-asserted every turn:
# the stat auras (temp layers reset) and a taunt (`taunted_by` clears at end step).
_REAPPLIED_CONTINUOUS = (*_STAT_CONTINUOUS, "taunt", "prevent")


def _reapply_channel_stats(st: GameState) -> None:
    """After the end step clears the temp layers (and taunts), re-apply the sustained
    channel effects — stat auras (anthem/debuff) and a continuous taunt (Lure) — so
    they persist across turns. Quiet (log_it=False): the initial cast already logged."""
    for holder in st.living_party():
        for channel in holder.channels:
            for effect in channel.card.effects:
                if _is_continuous(effect) and effect.kind in _REAPPLIED_CONTINUOUS:
                    for target in _continuous_targets(st, channel, effect):
                        _apply_static(st, target, effect, +1, log_it=False,
                                      holder_id=channel.holder_id, x=channel.x)
    # Enemy channels sustain their auras across turns the same way (§8 both ways).
    for e in st.living_enemies():
        for ch in e.channels:
            for effect in ch.effects:
                if _is_continuous(effect) and effect.kind in _REAPPLIED_CONTINUOUS:
                    for target in _enemy_channel_targets(st, ch, effect):
                        _apply_static(st, target, effect, +1, log_it=False,
                                      holder_id=e.id)


def _note_break(st: GameState, char: CharacterState, reason: str) -> None:
    if char.channels and char.id not in st.pending_break:
        st.pending_break.append(char.id)


def _break_threshold(char: CharacterState) -> int:
    """A hit of ≥25% of max HP breaks concentration (round up)."""
    return math.ceil(char.max_hp / 4)


def _process_breaks(st: GameState) -> None:
    """After a resolution, end the channels of any channeler owed a break —
    party characters and enemy channelers alike (§8, both sides of the table)."""
    for cid in list(st.pending_break):
        st.pending_break.remove(cid)
        char = st.character(cid)
        if char is not None and char.channels:
            _break_channels(st, char, reason="break")
            continue
        enemy = st.enemy(cid)
        if enemy is not None and enemy.channels:
            _break_enemy_channels(st, enemy, reason="break")


def _break_channels(st: GameState, char: CharacterState, reason: str) -> None:
    """End ALL of a character's channels at once (all-or-nothing): lift continuous
    effects and release all reserved mana into the pool as a respondable stack
    trigger (GDD §8). Breaks (damage) are always all-or-nothing; a voluntary drop
    may instead end a single channel via `_end_channels`."""
    _end_channels(st, char, list(char.channels), reason)


def _end_channels(st: GameState, char: CharacterState, channels: List[Channel],
                  reason: str) -> None:
    """End the given channels: lift their continuous effects and release their reserved
    mana straight into the pool (GDD §8). The release does NOT use the stack — it just
    happens, so it opens no reaction window. The card is already in the graveyard (R-9) —
    the channel simply ends. `channels` is a subset of the holder's channels (all of them
    for a break; one for a voluntary single drop). Any `channel_break` effects on an
    ending card DO use the stack: each ending channel pushes one respondable triggered
    ability (so a counter can answer it) — see _fire_channel_break."""
    channels = [ch for ch in channels if ch in char.channels]
    if not channels:
        return
    released: List[str] = []
    for channel in channels:
        for effect in channel.card.effects:
            if _is_continuous(effect):
                _remove_continuous(st, channel, effect)
        released.extend(channel.reserved)
        _log(st, "channel_end", f"{channel.card.name}'s channel ends (the card is "
             f"already in the graveyard).", character=char.id, card=channel.card.id, reason=reason)
    char.channels = [ch for ch in char.channels if ch not in channels]
    # The reserved mana returns to the pool immediately — no stack, no trigger.
    char.pool.extend(released)
    _log(st, "mana_released",
         f"{char.name}'s channels break ({reason}); {_mana_str(released)} released "
         f"(pool now {_mana_str(char.pool)}).",
         character=char.id, released=list(released), reason=reason)
    for channel in channels:
        _fire_channel_break(st, char.id, "party", channel.card.name,
                            channel.card.effects, channel.target_id, x=channel.x,
                            card=channel.card)
    _raise_next_trigger_pick(st)


def _fire_channel_break(st: GameState, source_id: str, source_side: str, name: str,
                        effects, target_id: Optional[str], x: int = 0,
                        card=None) -> None:
    """Push an ending channel's `channel_break` effects onto the stack as one
    triggered ability (GDD taxonomy: triggered → reactive), reopening the reaction
    window — the other side may respond (a "triggered"/"ability" counter answers it)
    before it resolves. Fires on ANY end: voluntary drop, breaking hit, or the
    channeler's incapacitation. The item carries the `card` for slot descriptors
    and labels (only a kind-"spell" cast re-starts a channel at resolution).

    A break effect with a chosen target had no cast-time pick (see
    _target_sites); the item is flagged `needs_target` and the holder picks as the
    trigger goes on the stack (`_raise_next_trigger_pick` — the caller invokes it
    after all of a batch's triggers are pushed)."""
    breaks = [e for e in effects if getattr(e, "trigger", None) == "channel_break"]
    if not breaks:
        return
    item = _push(st, StackItem(kind="triggered", source_id=source_id,
                               source_side=source_side, effects=breaks,
                               label=f"{name} — break trigger",
                               target_id=target_id, x=x, card=card))
    if source_side == "party":
        item.needs_mode = any(getattr(e, "kind", None) == "modal" for e in breaks)
        item.needs_target = _trigger_pick_effect(item) is not None
    st.priority = None  # fresh window — re-seeded by _advance
    st.passes = 0
    _log(st, "channel_break_trigger",
         f"{name}'s break trigger goes on the stack.", source=source_id, label=name)


def _trigger_pick_effect(item: StackItem):
    """The first effect of a fired triggered ability that still owes a target
    pick, or None. A DIRECT chosen target always needs the pick; a "$slot" target
    needs it only when nothing bound the slot at cast (`item.target_id` empty —
    a slot shared with an untriggered aura effect was chosen at cast instead)."""
    for e in _pending_trigger_effects(item):
        desc = getattr(e, "target", None)
        if isinstance(desc, str):
            if item.target_id is None:
                return e
        elif getattr(desc, "mode", None) == TargetMode.chosen:
            return e
    return None


def _pending_trigger_effects(item: StackItem):
    """The effects a pushed trigger will actually resolve: a modal expands to its
    chosen mode once `item.mode` is bound (an unchosen modal contributes nothing
    yet — the target scan waits for the mode pick)."""
    out = []
    for e in item.effects:
        if getattr(e, "kind", None) == "modal":
            if item.mode is not None:
                out.extend(_effects_of_mode(item, e))
        else:
            out.append(e)
    return out


def _modal_pick_options(modal):
    """[(mode_key, label)] a trigger-time mode pick offers — one per mode for
    "choose one", one per legal combination (bitmask keys) for "choose N [or
    more]"; mirrors `_mode_specs`' enumeration for casts."""
    labels = [m.label or f"Option {i + 1}" for i, m in enumerate(modal.modes)]
    if not _modal_is_multi(modal):
        return list(enumerate(labels))
    n = len(modal.modes)
    k = min(max(1, getattr(modal, "choose", 1) or 1), n)
    sizes = range(k, n + 1) if getattr(modal, "or_more", False) else (k,)
    return [(sum(1 << i for i in combo), " + ".join(labels[i] for i in combo))
            for size in sizes for combo in itertools.combinations(range(n), size)]


def _raise_next_trigger_pick(st: GameState) -> bool:
    """Raise the next pick a pushed triggered ability still owes — the topmost
    flagged stack item first (it resolves first), its MODE before its TARGET (the
    mode decides which effects resolve, and so which targets are needed). The
    pending choice blocks `_advance` BEFORE the reaction window opens, so every
    trigger on the stack is fully chosen by the time anyone may respond (MTG:
    modes and targets are chosen as the ability is put on the stack). Returns
    True while a pick is pending."""
    if st.pending_choice is not None:
        return True
    for item in reversed(st.stack):
        if not (item.needs_mode or item.needs_target):
            continue
        char = st.character(item.source_id)
        if char is None:  # no chooser — resolve with the defaults / fizzle
            item.needs_mode = item.needs_target = False
            continue
        if item.needs_mode:
            modal = next((e for e in item.effects
                          if getattr(e, "kind", None) == "modal"), None)
            options = _modal_pick_options(modal) if modal is not None else []
            if len(options) > 1:
                st.pending_choice = PendingChoice(
                    kind="mode", chooser_id=char.id, effect=modal, candidates=[],
                    need=1, remaining=[], item=item)
                return True
            # A single legal option binds itself; fall through to the target scan.
            item.mode = options[0][0] if options else None
            item.needs_mode = False
            if _trigger_pick_effect(item) is not None:
                item.needs_target = True
        if item.needs_target:
            effect = _trigger_pick_effect(item)
            # Nothing legal to aim at: resolve untargeted — the effect fizzles
            # rather than soft-locking the game.
            if effect is None or not _effect_target_options(st, effect, item.card):
                item.needs_target = False
                continue
            st.pending_choice = PendingChoice(
                kind="target", chooser_id=char.id, effect=effect, candidates=[],
                need=1, remaining=[], item=item)
            return True
    return False


def _do_choose_mode(st: GameState, action: Action) -> None:
    """Bind the picked mode of a triggered modal. For a channel_break trigger
    (`resolve_now` False) the mode is bound as the ability sits on the stack; any
    chosen-target inside the picked mode then raises its own pick before the
    window opens. For a modal firing right now (channel_start) the chosen mode
    resolves immediately and the rest of the firing resumes."""
    pc = st.pending_choice
    st.pending_choice = None
    item, modal = pc.item, pc.effect
    item.mode = action.mode
    item.needs_mode = False
    label = dict(_modal_pick_options(modal)).get(action.mode, f"mode {action.mode}")
    _log(st, "mode_chosen", f"{item.label}: {label}.",
         source=item.source_id, mode=action.mode, label=label)
    if pc.resolve_now:
        # channel_start: the modal fires now — resolve the chosen mode, then the
        # rest of the interrupted effect list (same resume shape as a card pick).
        ctx = _new_ctx(st, item)
        _resolve_effect(st, item, modal, ctx)
        _resolve_effect_list(st, item, pc.remaining, ctx)
        if st.pending_choice is None:
            _process_breaks(st)
            st.priority = None
        return
    if _trigger_pick_effect(item) is not None:
        item.needs_target = True
    if not _raise_next_trigger_pick(st):
        st.passes = 0
        st.priority = None  # fresh window on the fully-chosen trigger(s)


def _do_choose_target(st: GameState, action: Action) -> None:
    """Bind the picked creature onto a pending triggered ability (channel_break),
    then either raise the next pending pick or open the reaction window on the
    now fully-targeted stack."""
    pc = st.pending_choice
    pc.item.target_id = action.target_id
    pc.item.needs_target = False
    st.pending_choice = None
    tgt = st.combatant(action.target_id)
    _log(st, "target_chosen",
         f"{pc.item.label} targets {tgt.name if tgt is not None else action.target_id}.",
         source=pc.item.source_id, target=action.target_id)
    if not _raise_next_trigger_pick(st):
        st.passes = 0
        st.priority = None  # fresh window on the fully-targeted trigger(s)


# Effects that act on the source or a stack item, not on the resolved `target`
# (a None target is legitimate for them); every other effect needs a target to land on.
_TARGETLESS = frozenset({"counter", "create_token", "ramp", "add_mana", "charge"})


def _resolve_effect(st: GameState, item: StackItem, effect, ctx: dict) -> None:
    # Container effects expand here so resolution composes (no modal-in-modal).
    if effect.kind == "modal":
        for sub in _effects_of_mode(item, effect):
            _resolve_effect(st, item, sub, ctx)
        return
    if effect.kind == "conditional":
        if _condition_holds(st, item, effect, ctx):
            for sub in effect.effects:
                _resolve_effect(st, item, sub, ctx)
        else:
            _log(st, "condition_false",
                 f"{item.label}: condition not met — skipped.", kind="conditional")
        return

    handler = RESOLVERS.get(effect.kind)
    if handler is None:
        # Declared by the schema but with no runtime here (e.g. a combat-structure
        # keyword effect outside this engine's model). Surfaced, never dropped.
        _log(st, "unhandled", f"(effect '{effect.kind}' not implemented this milestone)",
             kind=effect.kind)
        return

    # A `mana_capacity`/"all" value with no runtime meaning here: surface, skip.
    if isinstance(getattr(effect, "amount", None), str) and effect.amount == "all":
        _log(st, "unhandled", f"(value 'all' on {effect.kind} not modelled)", kind=effect.kind)
        return

    # One effect can hit a SET (mode 'all') or a single creature; resolve per target.
    for target in _resolution_targets(st, item, effect, ctx):
        # A per-target effect with no resolved target does nothing — fizzle rather than
        # crash. This covers a card cast with no target whose effect still expects one
        # (e.g. a `chosen`/`targeted:false` prevent that was never given a creature).
        if target is None and effect.kind not in _TARGETLESS:
            _log(st, "fizzle", f"{item.label}'s {effect.kind} fizzles (no target).",
                 kind=effect.kind)
            continue
        if _is_targeted(effect) and (target is None or not _legal_target(target)):
            _log(st, "fizzle", f"{item.label}'s {effect.kind} fizzles (no legal target).",
                 kind=effect.kind)
            continue
        # Hexproof: a TARGETED effect can't land on a hexproof HOSTILE — an enemy's
        # on a character, or a player's on an enemy creature (friendly targeting is
        # fine; untargeted-chosen effects beat hexproof) — GDD §6/§7. BASIC ATTACKS
        # are exempt: hexproof wards off spells and abilities that target, not the
        # sword — an attack action always lands (playtest ruling, Update 06).
        if (item.kind != "attack"
                and _is_targeted(effect) and target is not None and _has_kw(target, "hexproof")
                and ((item.source_side == "enemy" and not isinstance(target, EnemyState))
                     or (item.source_side != "enemy" and isinstance(target, EnemyState)))):
            _log(st, "fizzle", f"{item.label} fizzles — {target.name} has Hexproof.",
                 kind=effect.kind)
            continue
        # target_* value refs read the creature this iteration lands on (each of
        # a mode:all set reads its own stats); caster_obj is set by the ctx builder.
        ctx["target_obj"] = target
        handler(st, item, effect, target, ctx)


def _site_target(item: StackItem, ctx, effect, desc) -> Optional[str]:
    """The target id for an effect's site: its own independent target when the
    effect is a top-level multi-target site (recorded in ctx['site_target']),
    otherwise the primary target_id (conditional-nested effects, single-target
    cards). Slot refs key by slot name; direct descriptors by effect identity."""
    if ctx is not None and "site_target" in ctx:
        key = ("slot", desc[1:]) if isinstance(desc, str) else ("eff", id(effect))
        if key in ctx["site_target"]:
            return ctx["site_target"][key]
    return item.target_id


def _site_id(item: StackItem, ctx, desc, eff_key) -> Optional[str]:
    """Like `_site_target`, but for a secondary target field (e.g. fight's `other`):
    slot refs key by name, an inline descriptor by the caller-supplied `eff_key`
    (so two target fields on the same effect don't collide on id())."""
    if ctx is not None and "site_target" in ctx:
        key = ("slot", desc[1:]) if isinstance(desc, str) else eff_key
        if key in ctx["site_target"]:
            return ctx["site_target"][key]
    return None


def _resolution_targets(st: GameState, item: StackItem, effect, ctx=None) -> List:
    """The combatant(s) an effect lands on. `self` -> the source; `all` -> every
    creature in the side; otherwise the effect's chosen target (its own per-site
    target for independent multi-target cards, else the item's primary target)."""
    desc = getattr(effect, "target", None)
    if isinstance(desc, str) or desc is None:
        return [st.combatant(_site_target(item, ctx, effect, desc))]
    mode = getattr(desc, "mode", None)
    if mode == TargetMode.self_:
        return [st.combatant(item.source_id)]
    if mode == TargetMode.all:
        side = desc.side.value if getattr(desc, "side", None) is not None else "ally"
        return _creatures_on_side(st, side, item, desc)
    return [st.combatant(_site_target(item, ctx, effect, desc))]


def _creatures_on_side(st: GameState, side: str, item: StackItem, desc) -> List:
    """Every living creature on a side (allies include ally tokens)."""
    if side == "enemy":
        return list(st.living_enemies())
    if side == "any":
        return list(st.living_party()) + list(st.living_enemies()) + list(st.living_tokens())
    out = list(st.living_party()) + list(st.living_tokens())  # ally
    if getattr(desc, "exclude_self", False):
        out = [c for c in out if c.id != item.source_id]
    return out


def _condition_holds(st: GameState, item: StackItem, cond_effect, ctx: dict) -> bool:
    """Evaluate a conditional's condition at resolution (GDD §11 containers)."""
    cond = cond_effect.condition
    if cond.kind == "cast_mode":
        return item.cast_mode == cond.mode
    if cond.kind == "caster_property":
        # The caster's own row / keyword / channeling state, read at resolution.
        src = st.combatant(item.source_id)
        if src is None:
            return False
        if cond.property == "row":
            want = cond.row.value if hasattr(cond.row, "value") else cond.row
            return getattr(src, "row", None) == want
        if cond.property == "has_keyword":
            return _has_kw(src, cond.keyword)
        return bool(getattr(src, "channels", []))  # "channeling": holds a channel
    if cond.kind == "self_hp":
        # The caster's CURRENT base HP against a % of max (integer math: no floats).
        src = st.combatant(item.source_id)
        if src is None or getattr(src, "max_hp", 0) <= 0:
            return False
        if cond.compare == "or_more":
            return src.hp * 100 >= cond.percent * src.max_hp
        return src.hp * 100 <= cond.percent * src.max_hp
    if cond.kind == "enemy_count":
        enemies, party = len(st.living_enemies()), len(st.living_party())
        if cond.compare == "more":
            return enemies > party
        if cond.compare == "fewer":
            return enemies < party
        return enemies == party
    if cond.kind == "spells_cast":
        # Spells the caster has cast this turn, counting this one (the counter is
        # bumped at cast, before resolution). Non-characters (enemies) count 0.
        n = getattr(st.character(item.source_id), "spells_cast_turn", 0) or 0
        if cond.compare == "or_more":
            return n >= cond.count
        if cond.compare == "or_less":
            return n <= cond.count
        return n == cond.count
    # target_property: read the main chosen target's property.
    target = st.combatant(item.target_id)
    if cond.property == "has_keyword":
        return target is not None and _has_kw(target, cond.keyword)
    if cond.property == "side":
        want = cond.side.value if hasattr(cond.side, "value") else cond.side
        if target is None:
            return False
        is_ally = isinstance(target, (CharacterState, TokenState))
        return (want == "ally") == is_ally
    if cond.property == "level":
        lvl = getattr(target, "level", None)
        if lvl is None:
            return False
        compare = getattr(cond, "compare", "exactly")
        if compare == "or_more":
            return lvl >= cond.level
        if compare == "or_less":
            return lvl <= cond.level
        return lvl == cond.level
    if cond.property == "row":
        want = cond.row.value if hasattr(cond.row, "value") else cond.row
        return target is not None and getattr(target, "row", None) == want
    return False


def _resolve_target(st: GameState, item: StackItem, effect):
    """The single combatant an effect lands on (first of the resolution set)."""
    targets = _resolution_targets(st, item, effect)
    return targets[0] if targets else None


def _is_targeted(effect) -> bool:
    desc = getattr(effect, "target", None)
    return bool(getattr(desc, "targeted", False))


def _legal_target(target) -> bool:
    # On the battlefield == targetable. A DOWNED character stays on the field
    # (incapacitation is recoverable — R-7) and remains a legal heal/revive
    # target; enemies and tokens leave play at 0 HP so they must be alive, and
    # an off-field enemy — bounced (in hand) or channel-suspended (exiled) —
    # can't be targeted (Update 03 §E-D).
    if isinstance(target, CharacterState):
        return True
    if not getattr(target, "alive", False):
        return False
    if isinstance(target, EnemyState) and (target.in_hand or target.exiled):
        return False
    return True


def _has_kw(combatant, kw: str) -> bool:
    return kw in getattr(combatant, "keywords", {})


def _value(amount, ctx: dict) -> int:
    """Resolve an effect value: a constant, or a dynamic reference filled in
    during resolution (the destroyed target's Level, or the source's mana capacity)."""
    if isinstance(amount, Ref):
        if amount.ref == "destroyed_target.level":
            return int(ctx.get("destroyed_target", {}).get("level", 0))
        if amount.ref == "mana_capacity":
            return int(ctx.get("capacity", 0))
        if amount.ref == "x":
            return int(ctx.get("x", 0) or 0)
        if amount.ref == "casting_cost":
            return int(ctx.get("casting_cost", 0) or 0)
        if amount.ref == "party_size":
            return int(ctx.get("party_size", 0) or 0)
        if amount.ref in ("caster_power", "caster_hp"):
            return _live_stat(ctx.get("caster_obj"), amount.ref.split("_", 1)[1])
        if amount.ref in ("target_power", "target_hp"):
            return _live_stat(ctx.get("target_obj"), amount.ref.split("_", 1)[1])
        raise ValueError(f"unsupported value reference '{amount.ref}'")
    if amount == "all":
        return 0  # guarded earlier; never reached for a real effect
    return int(amount)


def _live_stat(obj, stat: str) -> int:
    """A combatant's live stat for a caster_/target_ value ref, read at the moment
    the effect resolves: `power` = current Power (base + bonuses), `hp` = effective
    HP (temp buffers included). 0 when there is no such combatant."""
    if obj is None:
        return 0
    if stat == "power":
        return max(0, int(getattr(obj, "current_power", 0) or 0))
    return max(0, int(getattr(obj, "effective_hp", 0) or 0))


# ---- one handler per effect primitive --------------------------------------- #
def _r_deal_damage(st, item, effect, target, ctx):
    amount = _value(effect.amount, ctx)
    source_obj = st.combatant(item.source_id)
    if item.kind == "attack":
        # The attacker must still be in play when the swing resolves (R-12): a First
        # Strike reaction that killed it first removes this attack — a dead/removed
        # source deals no combat damage.
        if item.attack_power is not None and source_obj is None:
            _log(st, "fizzle", f"{item.label} fizzles — its attacker is gone.", kind="attack")
            return
        # A basic attack's damage is its source's CURRENT Power, evaluated in full
        # at RESOLUTION (R-7): pumps/wounds AND +1/+1 counters landing after the
        # swing was declared all change what lands. Enemy attack amounts come from
        # their intent TEMPLATE (not a power stat), so only the live bonus layer is
        # re-read on top of the declared base for them.
        if item.attack_power is not None:
            if isinstance(source_obj, EnemyState):
                amount = max(0, item.attack_power + source_obj.power_bonus)
            else:
                amount = max(0, source_obj.current_power)
        # Mitigate answers attack-type hits only (Update 02 §M-A.1)
        target, amount = _apply_mitigation(st, item, target, amount)
    overkill = _deal_damage(st, target, amount, source=item.label,
                            source_obj=source_obj, damage_kind=item.kind)
    # Trample: if the blow felled the target, the excess cleaves onto ONE more creature.
    if (item.kind == "attack" and overkill > 0 and source_obj is not None
            and _has_kw(source_obj, "trample")):
        _trample_cleave(st, source_obj, target, overkill, item.attack_mode, item.label)


def _mode_can_strike(attacker, defender, mode: Optional[str]) -> bool:
    """R-1 legality for a single hit, ignoring the front-row targeting rule: ranged hits
    anything; ground melee can't touch a flyer (unless the attacker has flying/reach).
    So a melee trample can't cleave onto a Flying creature."""
    if (mode or getattr(attacker, "attack_mode", "melee")) == "ranged":
        return True
    akw = getattr(attacker, "keywords", {})
    if "flying" in akw or "reach" in akw:
        return True
    return "flying" not in getattr(defender, "keywords", {})


def _trample_cleave(st: GameState, attacker, primary, excess: int,
                    mode: Optional[str], label: str) -> None:
    """Spill `excess` trample damage onto ONE more creature on the felled target's side:
    the lowest-HP legal target on the primary's row or an adjacent row. It goes through
    that creature's own mitigation (no bypass) and can't land on an illegal target (e.g.
    a Flying creature for a ground-melee swing). No viable target → the excess is lost."""
    if isinstance(primary, EnemyState):
        pool = [c for c in st.living_enemies() if c is not primary]
    else:  # a felled ally (player/token) — an enemy trample cleaves to the party side
        pool = [c for c in (st.living_party() + st.living_tokens()) if c is not primary]
    prow = _row_rank(primary.row)
    pool = [c for c in pool
            if abs(_row_rank(c.row) - prow) <= 1 and _mode_can_strike(attacker, c, mode)]
    if not pool:
        return
    carry = sorted(pool, key=lambda c: (c.effective_hp, _row_rank(c.row), c.name))[0]
    _log(st, "trample", f"{primary.name} falls; {excess} tramples onto {carry.name}.",
         source=getattr(attacker, "id", None), target=_tid(carry), amount=excess)
    # damage_kind="attack" so it stays combat damage; no further cleave (single carry).
    _deal_damage(st, carry, excess, source=f"{label} (trample)",
                 source_obj=attacker, damage_kind="attack")


def _r_heal(st, item, effect, target, ctx):
    _heal(st, target, _value(effect.amount, ctx), source_obj=st.combatant(item.source_id))


def _r_poison(st, item, effect, target, ctx):
    # A poison effect (D8-2.1): counters now, and again at each Upkeep until it
    # concludes (death, any received healing, or its optional turn bound).
    amount = _value(effect.amount, ctx)
    if amount <= 0:
        return
    target.poison_effects.append(Affliction(amount=amount, turns_left=effect.turns,
                                            source_id=item.source_id))
    bound = f" for {effect.turns} turn(s)" if effect.turns else ""
    _log(st, "poison",
         f"{target.name} is poisoned — {amount} counter(s) now and at each "
         f"Upkeep{bound}; any healing cures it.",
         target=_tid(target), amount=amount, turns=effect.turns)
    _place_poison_counters(st, target, amount)


def _r_regen(st, item, effect, target, ctx):
    # The mirror (D8-2.2): counters now and per Upkeep until damage connects
    # (or the turn bound expires). Each placement counts as healing.
    amount = _value(effect.amount, ctx)
    if amount <= 0:
        return
    target.regen_effects.append(Affliction(amount=amount, turns_left=effect.turns,
                                           source_id=item.source_id))
    bound = f" for {effect.turns} turn(s)" if effect.turns else ""
    _log(st, "regen",
         f"{target.name} regenerates — {amount} counter(s) now and at each "
         f"Upkeep{bound}; broken by damage that connects.",
         target=_tid(target), amount=amount, turns=effect.turns)
    _place_regen_counters(st, target, amount, source_id=item.source_id)


def _r_charge(st, item, effect, target, ctx):
    # The windup verb (D8-2.4): enemy-only, always self — fills the visible gauge
    # and detonates the hidden on_charge_full component at its threshold.
    enemy = st.enemy(item.source_id)
    if enemy is None or not enemy.alive:
        return
    gained = max(0, int(effect.amount))
    enemy.charge += gained
    threshold = _charge_threshold(enemy)
    pips = f"{enemy.charge}/{threshold}" if threshold else str(enemy.charge)
    _log(st, "charge", f"{enemy.name} gathers its power — charge {pips}.",
         enemy=enemy.id, charge=enemy.charge, threshold=threshold, gained=gained)
    _check_charge_full(st, enemy)


def _r_lose_life(st, item, effect, target, ctx):
    # Life loss is not damage: prevention and temp HP do not apply (GDD §4.8/§11).
    amount = _value(effect.amount, ctx)
    lost = target.hp - max(0, target.hp - amount)
    target.hp = max(0, target.hp - amount)
    if isinstance(target, CharacterState):
        _gain_gauge(st, target, lost)  # +1 gauge per point of current HP lost (D8-3.3)
    _log(st, "lose_life", f"{target.name} loses {amount} HP (HP {target.hp}).",
         target=_tid(target), amount=amount, hp=target.hp)
    _after_damage(st, target)


def _boss_shrugs_removal(st: GameState, label: str, target) -> bool:
    """§9.4 / §F-9: a boss outside its execute window (>25% max HP) cannot be removed —
    destroy / exile / bounce / deathtouch-execute all fizzle against it. Whittle it
    into the window first. Returns True (and logs) when the removal is denied."""
    if isinstance(target, EnemyState) and target.is_boss and not target.in_execute_window:
        _log(st, "boss_immune",
             f"{target.name} shrugs off {label} — a boss can't be removed above 25% HP "
             f"({target.effective_hp}/{target.max_hp}).", enemy=target.id, label=label)
        return True
    return False


def _r_destroy(st, item, effect, target, ctx):
    # `destroy` DECLARES removal; the resolver DECIDES it means a minion kill.
    if isinstance(target, EnemyState):
        if _boss_shrugs_removal(st, item.label, target):
            return
        ctx["destroyed_target"] = {"level": target.level}
        _log(st, "destroyed", f"{target.name} is destroyed (Level {target.level}).",
             target=target.id, level=target.level)
        _kill_enemy(st, target)


def _r_pump(st, item, effect, target, ctx):
    # Pump (+X/+X): +X Power and +X temp_mod — a buffer that lifts effective_hp and
    # expires at End (R-7). power/toughness may be refs (pump X, +1 per player…).
    power, toughness = _value(effect.power, ctx), _value(effect.toughness, ctx)
    if hasattr(target, "power_bonus"):
        target.power_bonus += power
    target.temp_mod += toughness
    # The toughness half is temp HP granted — the caster's gauge charges +1 per
    # point, like any shielding (D8-3.3).
    if toughness > 0:
        _gain_gauge(st, st.character(item.source_id), toughness)
    _log(st, "pump", f"{target.name} gets +{power}/+{toughness} "
         f"(eff HP {target.effective_hp}).", target=_tid(target),
         power=power, toughness=toughness)


def _r_draw(st, item, effect, target, ctx):
    _draw(st, target, _value(effect.amount, ctx), ctx)


def _raise_scry_choice(st: GameState, item: StackItem, effect, ctx: dict,
                       idx: int, effects) -> bool:
    """Set up the interactive scry: reveal the top N of the chooser's library and
    pause so the player can place each card on top (in a chosen order) or the bottom.
    Returns True if a choice was raised (the caller stops resolving), False to fall
    through to the non-interactive reveal (no library / nothing to look at / a value
    like 'all' that isn't a fixed count)."""
    amt = getattr(effect, "amount", None)
    if isinstance(amt, str):  # 'all' and friends have no fixed reveal count
        return False
    targets = _resolution_targets(st, item, effect, ctx)
    char = targets[0] if targets else None
    if not isinstance(char, CharacterState) or not char.library:
        return False
    n = min(_value(amt, ctx), len(char.library))
    if n <= 0:
        return False
    revealed = list(char.library[:n])
    st.pending_choice = PendingChoice(
        kind="scry", chooser_id=char.id, effect=effect, candidates=revealed,
        need=n, remaining=list(effects[idx + 1:]), item=item, looked=n)
    _log(st, "scry", f"{char.name} scries {n}: {', '.join(c.name for c in revealed)}.",
         target=char.id, amount=n, revealed=[c.name for c in revealed])
    return True


def _r_scry(st, item, effect, target, ctx):
    # Non-interactive fallback (scry nested in a modal/conditional, or no library):
    # reveal the top N and keep them in place. Top-level scry is interactive instead
    # (see `_raise_scry_choice`), letting the player order top/bottom.
    n = _value(effect.amount, ctx)
    top = [c.name for c in target.library[:n]] if target is not None else []
    _log(st, "scry", f"{target.name if target else '?'} scries {n}: {', '.join(top) or '(empty)'}.",
         target=_tid(target) if target is not None else None, amount=n, revealed=top)


def _move_card_matches(card, effect) -> bool:
    """Type/level filter for move_card. A card's LTG type is its `timing`."""
    if effect.filter_type is not None and card.timing.value != effect.filter_type:
        return False
    cmp, want = effect.filter_level_compare, effect.filter_level
    if cmp != "any":  # "any" = no level filter
        if cmp == "or_more" and not card.level >= want:
            return False
        if cmp == "or_less" and not card.level <= want:
            return False
        if cmp == "exactly" and card.level != want:
            return False
    return True


def _move_candidates(char, effect, ctx):
    """Filter-matched cards eligible to move for `effect`, in source order. The
    interactive picker and the deterministic auto path share this."""
    src = effect.source
    if src == "drawn":
        pool = [c for c in ctx.get("drawn_cards", []) if c in char.hand]
    elif src == "library_top":
        pool = list(char.library[: effect.count])
    elif src == "library_bottom":
        pool = list(char.library[-effect.count:]) if effect.count else []
    elif src == "library":              # search anywhere
        pool = list(char.library)
    elif src in ("hand", "graveyard", "exile"):
        pool = list(getattr(char, src))
    else:
        pool = []
    return [c for c in pool if _move_card_matches(c, effect)]


def _place_card(st, char, effect, card, ctx=None):
    """Remove `card` from whichever zone it lives in and place it at the effect's
    destination, logging the move."""
    for zone in (char.hand, char.library, char.graveyard, char.exile):
        if card in zone:
            zone.remove(card)
            break
    if ctx is not None and card in ctx.get("drawn_cards", []):
        ctx["drawn_cards"].remove(card)
    dest_list = {
        "hand": char.hand, "graveyard": char.graveyard, "exile": char.exile,
        "library_top": char.library, "library_bottom": char.library,
        "library_shuffle": char.library,
    }[effect.destination]
    if effect.destination == "library_top":
        dest_list.insert(0, card)
    else:
        dest_list.append(card)
    _log(st, "move_card",
         f"{char.name} moves {card.name} ({effect.source} → {effect.destination}).",
         character=char.id, card=card.id, card_name=card.name,
         source=effect.source, destination=effect.destination)


def _move_shuffle(st, char, effect):
    if effect.shuffle_after or effect.destination == "library_shuffle":
        # A shuffle effect re-randomises the library when the fight was seeded; with
        # no seed (the deterministic default) it stays a logged no-op (order fixed).
        if st.rng_seed is not None:
            st.shuffle_count += 1
            random.Random((st.rng_seed, st.shuffle_count)).shuffle(char.library)
        _log(st, "shuffle", f"{char.name} shuffles their library.", character=char.id)


def _r_move_card(st, item, effect, target, ctx):
    """Move card(s) between this character's zones — the deterministic auto path
    (no genuine choice, or nested in a conditional/modal): take matching cards in
    source order. The interactive prompt is handled by `_resolve_effect_list`."""
    char = target
    chosen = _move_candidates(char, effect, ctx)[: effect.count]
    if not chosen:
        _log(st, "move_card_empty",
             f"{char.name} finds no matching card to move "
             f"({effect.source} → {effect.destination}).",
             character=char.id, source=effect.source, destination=effect.destination)
        return
    for card in chosen:
        _place_card(st, char, effect, card, ctx)
    _move_shuffle(st, char, effect)


def _r_create_token(st, item, effect, target, ctx):
    # An enemy Swarm (§F-4) spawns enemy-side tokens; a card's create_token spawns
    # autonomous ally tokens. Both read the effect's stats, falling back to the
    # scenario's token definition (legacy `tokens` map) for anything unset.
    if item.source_side == "enemy":
        _create_enemy_tokens(st, item, effect)
        return
    tdef = st.token_defs.get(effect.token_id, {})
    hp = int(effect.hp) if getattr(effect, "hp", None) is not None else int(tdef.get("hp", 1))
    power = int(effect.power) if getattr(effect, "power", None) is not None else int(tdef.get("power", 1))
    keywords = ({k: "" for k in effect.keywords} if getattr(effect, "keywords", None)
                else dict(tdef.get("keywords", {})))
    for _ in range(effect.count):
        st.token_seq += 1
        token = TokenState(
            id=f"{effect.token_id}_{st.token_seq}",
            name=tdef.get("name", effect.token_id.replace("_", " ").title()),
            max_hp=hp, hp=hp,
            power=power,
            row=tdef.get("row", "front"),  # tokens default to front; a def may name a row (R-13)
            attack_mode=tdef.get("attack_mode", "melee"),
            keywords=dict(keywords))
        st.tokens.append(token)
        _log(st, "token_created", f"A {token.name} (HP {token.hp}/Power {token.power}) "
             f"joins the party.", token=token.id, token_id=effect.token_id)


def _create_enemy_tokens(st: GameState, item: StackItem, effect) -> None:
    """Swarm (§F-4): spawn Husk-chassis enemy tokens for the creator, capped at 2 alive
    per creator (T-27). A spawned token is a full enemy — it holds a row, declares a
    basic melee attack next turn, and must be defeated for victory. It appears after the
    Intents step, so it first acts on the following turn."""
    creator = item.source_id
    tdef = st.token_defs.get(effect.token_id, {})
    hp = int(effect.hp) if getattr(effect, "hp", None) is not None else int(tdef.get("hp", 1))
    power = int(effect.power) if getattr(effect, "power", None) is not None else int(tdef.get("power", 1))
    level = int(tdef.get("level", 1))
    row = tdef.get("row", "front")
    mode = tdef.get("attack_mode", "melee")
    keywords = ({k: "encounter" for k in effect.keywords} if getattr(effect, "keywords", None)
                else _keyword_dict_like(tdef.get("keywords", {})))
    room = 2 - len([e for e in st.living_enemies() if e.created_by == creator])
    for _ in range(max(0, min(effect.count, room))):
        st.token_seq += 1
        tok = EnemyState(
            id=f"{effect.token_id}_{st.token_seq}",
            name=tdef.get("name", effect.token_id.replace("_", " ").title()),
            max_hp=hp, hp=hp, level=level, power=power,
            row=row, committed=row, home_row=row, attack_mode=mode,
            intent_template={"name": "Strike", "amount": power, "action_type": "ability",
                             "intent_type": "attack", "targeting": "lowest_hp_party",
                             "mode": mode},
            created_by=creator, keywords=dict(keywords))
        st.enemies.append(tok)
        _log(st, "token_created",
             f"A {tok.name} (HP {hp}/Power {power}) joins the enemy side.",
             enemy=tok.id, token_id=effect.token_id, created_by=creator)


def _keyword_dict_like(kw) -> dict:
    """A token def's keywords as a {keyword: duration} dict (a list means encounter-long)."""
    if isinstance(kw, dict):
        return dict(kw)
    return {k: "encounter" for k in (kw or [])}


def _r_exile(st, item, effect, target, ctx):
    # Exile removes permanently. Minions always (no boss this milestone); a player
    # character/token is removed to 0 (incapacitated / destroyed) — indestructible
    # does NOT save against exile (GDD §7).
    if isinstance(target, EnemyState):
        if _boss_shrugs_removal(st, item.label, target):
            return
        _log(st, "exiled", f"{target.name} is exiled.", target=target.id, level=target.level)
        ctx["destroyed_target"] = {"level": target.level}
        _kill_enemy(st, target)
    elif isinstance(target, TokenState):
        _remove_token(st, target)
    elif target is not None:
        target.hp = 0
        _after_damage(st, target)


def _r_bounce(st, item, effect, target, ctx):
    # Bounce sends a minion to the in-hand zone (Update 03 §E-C): a tempo tool, not a
    # kill — it leaves the field, loses its next action, and redeploys a turn later.
    # An ally token has no hand to return to, so for it bounce is removal (existing).
    if isinstance(target, EnemyState):
        if _boss_shrugs_removal(st, item.label, target):
            return
        _bounce_enemy(st, target)
    elif isinstance(target, TokenState):
        _remove_token(st, target)


def _bounce_enemy(st: GameState, enemy: EnemyState) -> None:
    """Update 03 §E-C: move an in-play enemy `in play → in hand`. It leaves the
    battlefield (vacates its row, no intent), sheds its temporary modifiers and
    attachments, but RETAINS its HP. It redeploys at the start of its next turn
    (the Intents step). Fires no death triggers — bounce is not death (§E-D)."""
    enemy.in_hand = True
    enemy.intent = None                       # pending intent reset — declares fresh on redeploy
    enemy.pending_voluntary = None            # a queued Move is dropped; it re-enters at its row
    _break_enemy_channels(st, enemy, "channeler bounced")  # off-field = concentration gone
    enemy.committed = enemy.row
    # Shed temporary modifiers (the pump/wound layers would expire at End anyway, R-7).
    enemy.temp_mod = enemy.prevent_pool = enemy.power_bonus = 0
    enemy.prevent_tags = []
    enemy.taunted_by = None
    for kw, dur in list(enemy.keywords.items()):  # temporary granted keywords fall off
        if dur not in ("permanent", "encounter"):
            del enemy.keywords[kw]
    if enemy.id in st.acted_enemies:          # off the field — it takes no action this turn
        st.acted_enemies.remove(enemy.id)
    # A channel aimed at it loses its target and holds inert — an aura losing its target
    # is not a concentration break (GDD §8), so the caster keeps their other channels.
    _log(st, "bounced",
         f"{enemy.name} is bounced to hand (redeploys next turn; HP {enemy.hp} retained).",
         enemy=enemy.id, hp=enemy.hp, row=enemy.row)
    _purge_stack_from(st, enemy.id, "bounced")


def _power_of(c) -> int:
    """A creature's attack power (party/token/enemy all expose current_power)."""
    return max(0, getattr(c, "current_power", 0))


def _r_fight(st, item, effect, target, ctx):
    # `target` is the primary creature (the one you control); resolve the `other`
    # from its own site. Each deals damage equal to its power to the other,
    # SIMULTANEOUSLY — snapshot both powers before any HP changes, so a creature
    # that dies still lands its blow (MTG fight, GDD §7).
    other_id = _site_id(item, ctx, getattr(effect, "other", None), ("eff_other", id(effect)))
    other = st.combatant(other_id)
    if target is None or other is None or not _legal_target(target) or not _legal_target(other):
        _log(st, "fizzle", f"{item.label}'s fight fizzles (a creature is gone).", kind="fight")
        return
    p_target, p_other = _power_of(target), _power_of(other)
    _log(st, "fight", f"{target.name} (Power {p_target}) fights {other.name} (Power {p_other}).",
         target=_tid(target), other=_tid(other), power=p_target, other_power=p_other)
    _deal_damage(st, other, p_target, source=f"{target.name} (fight)",
                 source_obj=target, damage_kind="fight")
    _deal_damage(st, target, p_other, source=f"{other.name} (fight)",
                 source_obj=other, damage_kind="fight")


def _r_counter(st, item, effect, target, ctx):
    # Cancel the hostile action this counter named, if it's still on the stack and
    # matches the filter (a filter node matches its descendants — GDD §5.4). Works
    # from either side: a player counters an enemy action, an enemy counterspell
    # (a reactive component with a counter verb) counters a player's cast. You can
    # never counter your own side's action.
    # The counter's own site binding wins (a multi-mode combo may aim its counter
    # at one thing and its other mode elsewhere); a single-target cast falls back
    # to the item's primary target as before.
    tid = _site_target(item, ctx, effect, getattr(effect, "target", None))
    uid = _parse_uid(tid)
    victim = next((s for s in st.stack if s.uid == uid), None) if uid is not None else None
    if (victim is None or victim.source_side == item.source_side
            or not _filter_matches(effect.filter, victim)):
        _log(st, "counter_fizzle", f"{item.label} has nothing to counter.", kind="counter")
        return
    st.stack.remove(victim)
    _log(st, "countered", f"{item.label} cancels {victim.label}.",
         label=victim.label, source=victim.source_id)


def _intent_reveal(intent: Intent, enemy: EnemyState) -> str:
    """What a stripped intent turns out to have been (D8-1.3): its on-stack name
    plus a short effect summary — paying a card buys the information along with
    the tempo, and teaches the enemy's kit across a fight."""
    if intent.action_type == "attack":
        amt = intent.attack_damage(enemy.power_bonus)
        return f"{intent.name} — deal {amt}" if amt is not None else intent.name
    try:
        from ltg_core.translation import render_effects
        text = render_effects(intent.effects).strip()
    except Exception:
        text = ""
    return f"{intent.name} — {text}" if text else intent.name


def _r_strip_intent(st, item, effect, target, ctx):
    if isinstance(target, EnemyState) and target.intent is not None:
        reveal = _intent_reveal(target.intent, target)
        target.intent = None
        # Stripping an intent reveals it (D8-1.3): the log names what was
        # prevented, and the intents window annotates the struck line.
        target.round_intent_status = "stripped"
        target.round_intent_reveal = reveal
        _log(st, "strip_intent",
             f"{target.name}'s intent is unravelled — it would have been "
             f"*{reveal}*.", enemy=target.id, reveal=reveal)


def _r_stun(st, item, effect, target, ctx):
    if isinstance(target, EnemyState):
        target.stunned += int(getattr(effect, "intents", 1))
        _log(st, "stun", f"{target.name} is stunned (skips {target.stunned} intent(s)).",
             enemy=target.id, intents=target.stunned)
    elif isinstance(target, CharacterState):
        # Enemy Debilitate on a player (§F-3): the character loses their proactive
        # window for the next `intents` turn(s) — only End Turn is offered. Reactions
        # (instants / Mitigate) stay available; stun dazes, it doesn't paralyse.
        target.stunned += int(getattr(effect, "intents", 1))
        _log(st, "stun", f"{target.name} is stunned (loses {target.stunned} turn(s)).",
             character=target.id, intents=target.stunned)


def _r_wound(st, item, effect, target, ctx):
    # Wound (−X/−X): −X Power and −X to temp_mod (R-7). If that drives effective_hp
    # ≤ 0 it kills/incaps immediately — even through indestructible.
    power, toughness = _value(effect.power, ctx), _value(effect.toughness, ctx)
    if hasattr(target, "power_bonus"):
        target.power_bonus -= power
    target.temp_mod -= toughness
    _log(st, "wound", f"{target.name} suffers -{power}/-{toughness} "
         f"(eff HP {target.effective_hp}).", target=_tid(target),
         power=power, toughness=toughness)
    if target.effective_hp <= 0:
        _after_damage(st, target)


def _r_counters(st, item, effect, target, ctx):
    # Persistent +X/+X counters: permanent Power and max HP (not cleared at End).
    power, toughness = _value(effect.power, ctx), _value(effect.toughness, ctx)
    if hasattr(target, "power"):
        target.power += power
    target.max_hp += toughness
    target.hp += toughness
    # Tally the counters themselves so the UI can badge them separately from
    # the (already-applied) stat change.
    target.counters = getattr(target, "counters", 0) + max(power, toughness)
    _log(st, "counters", f"{target.name} gains +{power}/+{toughness} "
         f"counters (HP {target.hp}/{target.max_hp}).", target=_tid(target))


def _r_prevent_only(st, item, effect, target, ctx):
    # R-11 prevent: tag the target to nullify the named thing for the duration.
    # `uses="all"` (None) shields every matching instance until the tag expires;
    # `uses="next"` (1) is a one-shot shield spent by the first matching thing.
    uses = None if getattr(effect, "uses", "all") == "all" else 1
    target.prevent_tags.append(PreventTag(effect.parameter, uses))
    span = "all" if uses is None else "the next"
    _log(st, "prevent", f"{target.name} will prevent {span} {effect.parameter} "
         f"({'this turn' if uses is None else 'once'}).",
         target=_tid(target), parameter=effect.parameter, uses=uses)


def _r_protection(st, item, effect, target, ctx):
    target.protection += 1
    _log(st, "protection", f"{target.name} gains protection ({effect.scope}).",
         target=_tid(target))


def _r_taunt(st, item, effect, target, ctx):
    # Force the targeted enemy to aim at the caster this turn — both its already
    # declared intent and the next one it declares.
    if isinstance(target, EnemyState):
        # A hexproof caster can still taunt: the forced action is an ATTACK, and
        # attacks land on hexproof (it wards spells/abilities only — Update 06).
        who = st.character(item.source_id)
        if who is not None:
            target.taunted_by = item.source_id
            if target.intent is not None:
                target.intent.target_id = item.source_id
            _log(st, "taunt", f"{target.name} is taunted into targeting {who.name}.",
                 enemy=target.id, by=item.source_id)
    elif isinstance(target, CharacterState) and item.source_side == "enemy":
        # Enemy "taunt-us" on a player (§F-3): this character's basic attacks must
        # target the taunting enemy while it lives, until upkeep. Spells are free —
        # the taunt bullies the sword arm, not the mind.
        taunter = st.enemy(item.source_id)
        if taunter is not None:
            target.taunted_to = taunter.id
            _log(st, "taunt", f"{target.name} is taunted — attacks must target "
                 f"{taunter.name}.", character=target.id, by=taunter.id)


def _r_revive(st, item, effect, target, ctx):
    # Restore an incapacitated character to a fraction of max HP (R-11).
    if isinstance(target, CharacterState) and target.effective_hp <= 0:
        target.temp_mod = 0
        target.hp = max(1, int(target.max_hp * effect.to_fraction))
        target.down_credited = False  # a later downing charges gauges anew (D8-3.3)
        _log(st, "revive", f"{target.name} is revived (HP {target.hp}).", character=target.id)


def _r_grant_keyword(st, item, effect, target, ctx):
    dur = _duration_value(effect)
    for kw in effect.keywords:
        target.keywords[kw] = dur
    _log(st, "grant_keyword", f"{target.name} gains {', '.join(effect.keywords)}.",
         target=_tid(target), keywords=list(effect.keywords), duration=dur)


def _r_remove_keyword(st, item, effect, target, ctx):
    if effect.keywords == ["all"]:
        removed = list(target.keywords.keys())
        target.keywords.clear()
    else:
        removed = [k for k in effect.keywords if target.keywords.pop(k, None) is not None]
    _log(st, "remove_keyword", f"{target.name} loses {', '.join(removed) or 'nothing'}.",
         target=_tid(target), keywords=removed)


def _r_ramp(st, item, effect, target, ctx):
    # Raise mana CAPACITY above the natural +1/turn (the lands-equivalent, GDD §4.4).
    char = st.character(item.source_id)
    if char is None:
        return
    color = effect.color if effect.color != "choice" else (char.identity[0] if char.identity else "C")
    if effect.availability == "deferred":
        st.pending_ramp.append({"char": char.id, "color": color, "amount": effect.amount})
        _log(st, "ramp_deferred", f"{char.name} will gain +{effect.amount} {color} capacity next turn.",
             character=char.id, color=color)
        return
    for _ in range(effect.amount):
        char.mana_colors.append(color)
        if effect.availability == "immediate":
            char.pool.append(color)  # usable now
    _log(st, "ramp", f"{char.name} gains +{effect.amount} {color} mana capacity "
         f"(capacity {char.capacity}{', usable now' if effect.availability == 'immediate' else ''}).",
         character=char.id, color=color, capacity=char.capacity)
    _fire_capacity_increase(st, char)


def _r_add_mana(st, item, effect, target, ctx):
    # A ritual: a one-time burst into the CURRENT pool this turn (no capacity).
    char = st.character(item.source_id)
    if char is None:
        return
    color = effect.color if effect.color != "choice" else (char.identity[0] if char.identity else "C")
    for _ in range(effect.amount):
        char.pool.append(color)
    _log(st, "add_mana", f"{char.name} adds {effect.amount} {color} to their pool "
         f"({_mana_str(char.pool)}).", character=char.id, color=color)


RESOLVERS = {
    "deal_damage": _r_deal_damage,
    "heal": _r_heal,
    "lose_life": _r_lose_life,
    "poison": _r_poison,
    "regen": _r_regen,
    "charge": _r_charge,
    "destroy": _r_destroy,
    "exile": _r_exile,
    "bounce": _r_bounce,
    "fight": _r_fight,
    "counter": _r_counter,
    "strip_intent": _r_strip_intent,
    "stun": _r_stun,
    "pump": _r_pump,
    "wound": _r_wound,
    "counters": _r_counters,
    "prevent": _r_prevent_only,
    "protection": _r_protection,
    "draw": _r_draw,
    "scry": _r_scry,
    "move_card": _r_move_card,
    "create_token": _r_create_token,
    "taunt": _r_taunt,
    "revive": _r_revive,
    "grant_keyword": _r_grant_keyword,
    "remove_keyword": _r_remove_keyword,
    "ramp": _r_ramp,
    "add_mana": _r_add_mana,
    # `disable` is applied as a continuous channel effect (see _apply_static); it is
    # never a one-shot, so it is not registered here.
}


def _parse_uid(target_id) -> Optional[int]:
    if isinstance(target_id, str) and target_id.startswith("#"):
        try:
            return int(target_id[1:])
        except ValueError:
            return None
    return None


# A counter filter node matches itself and its descendants (GDD §5.4):
#   action ⊃ {spell, ability ⊃ {attack, activated, triggered}}
_FILTER_MATCHES = {
    "action": {"spell", "ability", "attack", "activated", "triggered"},
    "spell": {"spell"},
    "ability": {"ability", "attack", "activated", "triggered"},
    "attack": {"attack"},
    "activated": {"activated"},
    "triggered": {"triggered"},
}


def _filter_matches(filter_node: str, item: StackItem) -> bool:
    return item.kind in _FILTER_MATCHES.get(filter_node, set())


def _duration_value(effect) -> str:
    dur = getattr(effect, "duration", None)
    return dur.value if dur is not None else "this_turn"


# --------------------------------------------------------------------------- #
# Typed counters: poison / regen / charge (Design Update 08 §D8-2)
# --------------------------------------------------------------------------- #
def _annihilate_typed_counters(st: GameState, target) -> None:
    """A poison counter and a regen counter on the same creature annihilate 1:1 as
    a state-based action (§D8-2.2). The folded stat changes cancel exactly (−0/−1
    against +0/+1), so only the tallies move."""
    n = min(getattr(target, "poison_counters", 0), getattr(target, "regen_counters", 0))
    if n <= 0:
        return
    target.poison_counters -= n
    target.regen_counters -= n
    _log(st, "annihilate",
         f"{n} poison and {n} regen counter(s) on {target.name} annihilate.",
         target=_tid(target), amount=n)


def _place_poison_counters(st: GameState, target, n: int) -> None:
    """Land `n` poison counters: each a persistent −0/−1 (−1 max HP and −1 current
    HP as it lands). Not damage — no prevention, no temp-HP soak, no on-hit
    triggers, never breaks a channel — but lethality is checked as always on
    effective HP: poison kills (§D8-2.1)."""
    if target is None or n <= 0:
        return
    target.poison_counters += n
    target.max_hp = max(0, target.max_hp - n)
    lost = target.hp - max(0, target.hp - n)
    target.hp = max(0, target.hp - n)
    _annihilate_typed_counters(st, target)
    _log(st, "poison_counters",
         f"{target.name} gains {n} poison counter(s) (−0/−{n}; "
         f"HP {target.hp}/{target.max_hp}).",
         target=_tid(target), amount=n, hp=target.hp, max_hp=target.max_hp)
    if isinstance(target, CharacterState):
        _gain_gauge(st, target, lost)  # +1 gauge per point of current HP lost (T-49)
    _after_damage(st, target)


def _place_regen_counters(st: GameState, target, n: int,
                          source_id: Optional[str] = None) -> None:
    """Land `n` regen counters: each a persistent +0/+1. A regen tick counts as
    healing (§D8-2.2): it cures poison, fires life-gain triggers, and credits the
    applier's ultimate gauge as restored HP."""
    if target is None or n <= 0:
        return
    target.regen_counters += n
    target.max_hp += n
    target.hp += n
    _annihilate_typed_counters(st, target)
    _log(st, "regen_counters",
         f"{target.name} gains {n} regen counter(s) (+0/+{n}; "
         f"HP {target.hp}/{target.max_hp}).",
         target=_tid(target), amount=n, hp=target.hp, max_hp=target.max_hp)
    _cure_poison(st, target, reason="regeneration")
    if source_id is not None:
        _gain_gauge(st, st.character(source_id), n)  # +1 per HP restored as source
    _fire_event(st, "life_gain", target)


def _cure_poison(st: GameState, target, reason: str = "healing") -> None:
    """Any received healing ends ALL poison effects on a creature — an antidote is
    an antidote (§D8-2.1). The accumulated counters remain."""
    effects = getattr(target, "poison_effects", None)
    if effects:
        target.poison_effects = []
        _log(st, "poison_cured",
             f"{target.name}'s poison is cured ({reason}) — "
             f"{len(effects)} effect(s) end.",
             target=_tid(target), reason=reason, ended=len(effects))


def _break_regen(st: GameState, target) -> None:
    """Damage that connects (≥1 after mitigation/prevention) concludes every regen
    effect on the victim (§D8-2.2). Counters remain."""
    if getattr(target, "regen_effects", None):
        target.regen_effects = []
        _log(st, "regen_broken", f"{target.name}'s regeneration is broken.",
             target=_tid(target))


def _tick_afflictions(st: GameState) -> None:
    """The Upkeep tick (§D8-2.3): every active poison/regen effect places its
    counters again. State-based, not stack events — no reaction windows open (the
    counters are the drama; the tick is bookkeeping). Order is deterministic:
    party side then enemy side, each in board order; poison before regen on a
    creature. Deaths from a poison tick fire death triggers normally."""
    for c in list(st.party) + _ordered(st.living_tokens()) + _ordered(st.living_enemies()):
        _tick_afflictions_one(st, c)


def _tick_afflictions_one(st: GameState, c) -> None:
    for eff in list(getattr(c, "poison_effects", [])):
        if eff not in c.poison_effects:  # concluded mid-tick (e.g. death)
            continue
        eff.pending = False
        _place_poison_counters(st, c, eff.amount)
        if eff in c.poison_effects and eff.turns_left is not None:
            eff.turns_left -= 1
            if eff.turns_left <= 0:
                c.poison_effects.remove(eff)
                _log(st, "poison_expired",
                     f"The poison on {c.name} runs its course.", target=_tid(c))
    if not getattr(c, "alive", False) and not isinstance(c, CharacterState):
        return  # died to its own poison — nothing left to regenerate
    for eff in list(getattr(c, "regen_effects", [])):
        if eff not in c.regen_effects:
            continue
        _place_regen_counters(st, c, eff.amount, source_id=eff.source_id)
        if eff in c.regen_effects and eff.turns_left is not None:
            eff.turns_left -= 1
            if eff.turns_left <= 0:
                c.regen_effects.remove(eff)
                _log(st, "regen_expired",
                     f"The regeneration on {c.name} fades.", target=_tid(c))


def _charge_threshold(e: EnemyState) -> Optional[int]:
    """The lowest armed on_charge_full threshold — the public pips the party
    watches fill (§D8-2.4). None when the enemy has no charge-triggered ability."""
    thresholds = [c.charge_threshold for c in e.components
                  if c.trigger == "on_charge_full" and c.charge_threshold]
    return min(thresholds) if thresholds else None


def _check_charge_full(st: GameState, e: EnemyState) -> None:
    """§D8-2.4: the moment the enemy's charge reaches a component's threshold, the
    hidden ability fires — immediately, mid-step, going ON THE STACK like any enemy
    reaction, where the party may respond in full view of what it now is. Charge
    resets to 0 as the ability hits the stack (not when it resolves): countering
    the detonation still consumes the charge."""
    for comp in _reactive_rules(e):
        if comp.trigger != "on_charge_full":
            continue
        threshold = comp.charge_threshold or 0
        if threshold <= 0 or e.charge < threshold:
            continue
        if not _component_eligible(st, e, comp):
            continue
        target = _component_target(st, e, comp)
        tid = target.id if target is not None else None
        _start_cooldown(st, e, comp.id)
        e.charge = 0
        label = comp.telegraph or comp.archetype or "Detonation"
        kind = "spell" if comp.action_type == "spell" else "triggered"
        _push(st, StackItem(kind=kind, source_id=e.id, source_side="enemy",
                            label=label, effects=list(comp.verbs), target_id=tid))
        st.priority = None  # fresh window — re-seeded by _advance
        st.passes = 0
        _log(st, "charge_detonate",
             f"{e.name}'s gathered power erupts — {label} goes on the stack.",
             enemy=e.id, label=label, component=comp.id, target=tid)
        return


# --------------------------------------------------------------------------- #
# The ultimate gauge (Design Update 08 §D8-3.3)
# --------------------------------------------------------------------------- #
def _gain_gauge(st: GameState, char, n: int) -> None:
    """Fill a character's public 0–100 ultimate gauge (clamped). Quiet except at
    the moment it fills — the bar is the display; the log marks only the drama.
    The gauge persists through incapacitation (a revived character keeps it)."""
    if n <= 0 or not isinstance(char, CharacterState):
        return
    before = char.ultimate_gauge
    char.ultimate_gauge = min(100, before + n)
    if (before < 100 <= char.ultimate_gauge
            and char.ultimate is not None and not char.ultimate_used):
        _log(st, "gauge_full",
             f"{char.name}'s ultimate gauge is full — "
             f"{char.ultimate.name} is ready.",
             character=char.id, ultimate=char.ultimate.name)


# --------------------------------------------------------------------------- #
# Damage / death / draw primitives
# --------------------------------------------------------------------------- #
# `prevent [parameter]` parameters that forbid an ACTION rather than nullify
# incoming damage. These are checked when the actor tries to act (see
# `_prevented_action`), never in `_deal_damage`, so a `prevent attack` shield
# must not also soak damage of kind "attack".
_ACTION_PREVENT = frozenset({"attack"})


def _prevented_action(combatant, action: str) -> bool:
    """True if a `prevent [action]` shield forbids this actor from taking `action`
    (e.g. Pacifism's `prevent attack` stops a creature attacking, R-11)."""
    return any(t.parameter == action for t in getattr(combatant, "prevent_tags", []))


def _prevent_match(parameter: str, damage_kind: str) -> bool:
    """Does a `prevent [parameter]` tag nullify this incoming damage (R-11)? Action
    shields (e.g. `prevent attack`) block the actor, not damage — they never match."""
    if parameter in _ACTION_PREVENT:
        return False
    if parameter in ("damage", "all"):
        return True
    if parameter == "combat_damage":
        return damage_kind == "attack"
    return parameter == damage_kind


def _deal_damage(st: GameState, target, amount: int, source: str = "", source_obj=None,
                 damage_kind: str = "spell") -> int:
    """Damage is answered, in order, by: a matching `prevent` tag (nullifies it),
    `protection` (negates a whole spell/attack), Parry's numeric reduction, then any
    **positive** temporary HP (the Defend/pump buffer soaks the blow before base HP —
    GDD §4.9 "a buffer that absorbs a blow"); the remainder reduces `hp` directly
    (R-7). Lethality is then checked on effective_hp. Source keywords
    (deathtouch/lifelink) and target indestructible apply here.

    Returns the OVERKILL — damage beyond what the target's HP could absorb — but only
    when the target actually fell (dead / incapacitated). Trample reads it to cleave the
    excess onto one more creature (see `_r_deal_damage`); every other caller ignores it."""
    if target is None or amount <= 0:
        return 0

    # R-11 prevent: a matching shield cancels the hit outright. A one-shot shield
    # (`uses="next"`) is spent by it; an "all" shield (uses=None) keeps standing and
    # nullifies every matching hit until it expires at End step (Fog).
    for tag in list(getattr(target, "prevent_tags", [])):
        if _prevent_match(tag.parameter, damage_kind):
            if tag.uses is not None:
                tag.uses -= 1
                if tag.uses <= 0:
                    target.prevent_tags.remove(tag)
            _log(st, "prevented", f"{source or 'the hit'} on {target.name} is prevented "
                 f"({tag.parameter}).", target=_tid(target), parameter=tag.parameter)
            return 0
    # Shields stood but none matched (e.g. Holy Day's combat_damage vs a Drain's
    # ability damage): say WHY the hit landed, or the player reads it as a bug.
    standing = sorted({t.parameter for t in getattr(target, "prevent_tags", [])
                       if t.parameter not in _ACTION_PREVENT})
    if standing:
        _log(st, "not_prevented",
             f"{source or 'The hit'} is {damage_kind} damage — {target.name}'s "
             f"prevent ({', '.join(standing)}) does not cover it.",
             target=_tid(target), damage_kind=damage_kind, shields=standing)

    # Protection negates the next incoming spell/attack outright (GDD §7).
    if getattr(target, "protection", 0) > 0 and damage_kind in (
            "attack", "spell", "ability", "activated", "triggered"):
        target.protection -= 1
        _log(st, "protected", f"{target.name}'s protection negates {source or 'the hit'}.",
             target=_tid(target))
        return 0

    # Parry / numeric prevention reduces the hit before it lands.
    reduced = min(target.prevent_pool, amount)
    target.prevent_pool -= reduced
    amount -= reduced
    if reduced:
        _log(st, "reduced", f"{reduced} damage to {target.name} reduced.",
             target=_tid(target), amount=reduced)
    if amount <= 0:
        return 0

    # A hit of ≥25% of max HP breaks concentration (the amount that lands — before the
    # temp-HP buffer soaks it: a big blow still rattles the channel, GDD §8).
    # Same rule both ways: an ENEMY channeler hit that hard drops its channel too.
    if (isinstance(target, (CharacterState, EnemyState)) and target.channels
            and amount >= _break_threshold(target) and target.id not in st.pending_break):
        st.pending_break.append(target.id)

    # Shield: positive temporary HP (Defend / a pump's toughness) absorbs the blow
    # before base HP — GDD §4.9 "a buffer that absorbs a blow". A negative temp_mod
    # (a wound) never soaks damage; healing still fills that separately (R-7).
    absorbed = 0
    if target.temp_mod > 0:
        absorbed = min(target.temp_mod, amount)
        target.temp_mod -= absorbed
        amount -= absorbed
        if absorbed:
            _log(st, "absorbed",
                 f"{target.name}'s temp HP absorbs {absorbed} (temp HP {target.temp_mod}).",
                 target=_tid(target), amount=absorbed)

    # The remainder reduces hp directly (R-7). Player hp floors at 0; indestructible
    # floors at 1 (it can't be reduced below 1 HP *by damage*).
    floor = 1 if _has_kw(target, "indestructible") else 0
    overkill = max(0, amount - target.hp)  # damage beyond hp — cleaves past on trample
    dealt = target.hp - max(floor, target.hp - amount)
    target.hp = max(floor, target.hp - amount)
    if dealt > 0 or absorbed == 0:
        _log(st, "damage", f"{target.name} takes {dealt} damage (HP {target.hp}, "
             f"eff {target.effective_hp}).", target=_tid(target), amount=dealt,
             hp=target.hp, source=source)

    # On-damage triggers key off the blow that connected — temp HP soaked plus HP lost
    # (so a shielded hit still feeds lifelink/deathtouch; identical to before when no
    # temp HP was present).
    connected = absorbed + dealt
    # Ultimate-gauge accounting (D8-3.3): the victim charges +1 per point of
    # current HP lost; a character source charges +1 per point of their damage
    # that connects (their attacks/spells/abilities — not their tokens').
    if isinstance(target, CharacterState):
        _gain_gauge(st, target, dealt)
    if isinstance(source_obj, CharacterState):
        _gain_gauge(st, source_obj, connected)
    if connected > 0:
        # Damage that connects breaks regeneration (D8-2.2) and carries infect
        # (D8-2.5): the victim gains a poison effect whose FIRST counter lands at
        # the next Upkeep — a venomed blade wounds now and sickens later.
        _break_regen(st, target)
        if source_obj is not None and _has_kw(source_obj, "infect"):
            target.poison_effects.append(
                Affliction(amount=1, turns_left=None, pending=True,
                           source_id=getattr(source_obj, "id", None)))
            _log(st, "infect",
                 f"{target.name} is infected — the poison sets in at the next Upkeep.",
                 target=_tid(target), source=getattr(source_obj, "id", None))
    if source_obj is not None and connected > 0 and _has_kw(source_obj, "lifelink"):
        _heal(st, source_obj, connected, reason="lifelink", source_obj=source_obj)
    if (source_obj is not None and connected > 0 and _has_kw(source_obj, "deathtouch")
            and isinstance(target, EnemyState) and target.alive
            and not (target.is_boss and not target.in_execute_window)):
        _log(st, "deathtouch", f"{target.name} is executed by deathtouch.", target=target.id)
        target.hp = 0
        target.temp_mod = min(target.temp_mod, 0)
    _after_damage(st, target)
    # On-damage channel triggers key off the blow that connected (soak + HP lost).
    if connected > 0:
        _fire_event(st, "damage_taken", target)
    # Overkill only cleaves when the blow actually felled the target (dead / incapacitated).
    return overkill if target.effective_hp <= 0 else 0


def _heal(st: GameState, target, amount: int, reason: str = "",
          source_obj=None) -> None:
    """Restore HP. A heal fills an outstanding negative `temp_mod` (a wound) first,
    cancelling it toward 0, and only then restores `hp` (never above max) — R-7.
    Any resolved heal — even one that restores 0 HP — cures poison (§D8-2.1).
    `source_obj` is the healer, credited +1 ultimate gauge per point restored
    (overheal beyond max counts 0 — §D8-3.3)."""
    if amount <= 0 or target is None:
        return
    _cure_poison(st, target)  # an antidote is an antidote — even a 0-restore heal
    gained = 0  # wound closed + HP restored — what on-life-gain triggers key off
    if target.temp_mod < 0:  # cancel the wound toward 0 first
        fill = min(-target.temp_mod, amount)
        target.temp_mod += fill
        amount -= fill
        gained += fill
        if fill:
            _log(st, "wound_mend", f"{fill} healing to {target.name} closes a wound "
                 f"(temp_mod {target.temp_mod}).", target=_tid(target), amount=fill)
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    gained += target.hp - before
    if target.hp != before or reason:
        _log(st, "heal", f"{target.name} heals {target.hp - before} (HP {target.hp}).",
             target=_tid(target), amount=target.hp - before, hp=target.hp, reason=reason)
    _gain_gauge(st, source_obj, gained)
    if isinstance(target, CharacterState) and target.effective_hp > 0:
        target.down_credited = False  # back on their feet — a later downing counts anew
    if gained > 0:
        _fire_event(st, "life_gain", target)


def _after_damage(st: GameState, target) -> None:
    # Boss enrage (§F-9): the first time a boss falls to ≤25% max HP it enrages —
    # one-way, checked on every HP change (all damage paths converge here). The flag
    # flips phase gates immediately; the Enrage component itself fires as an
    # `on_enrage` reaction in the next reaction window.
    if (isinstance(target, EnemyState) and target.is_boss and not target.enraged
            and target.alive and target.in_execute_window):
        target.enraged = True
        # Enraging is a hard reset, not just a flag (§F-9 upgraded): the boss shakes
        # off control (stun/taunt drop — fury doesn't sit out a turn) and its ability
        # cooldowns clear (the post-enrage kit opens at full aggression). once_per_
        # encounter firings stay spent — the drama doesn't repeat.
        shaken = target.stunned > 0 or target.taunted_by is not None
        target.stunned = 0
        target.taunted_by = None
        target.cooldowns = {k: v for k, v in target.cooldowns.items() if v >= 10 ** 9}
        _log(st, "enrage", f"{target.name} ENRAGES ({target.effective_hp}/"
             f"{target.max_hp} HP) — the execute window is open"
             + (", control effects are shaken off" if shaken else "")
             + ", and its abilities reset.", enemy=target.id)
    # Lethality is on effective_hp (R-7): hp + temp_mod. A pump buffer can keep a
    # creature alive at hp 0; a wound can kill at hp > 0.
    if target.effective_hp > 0:
        return
    if isinstance(target, EnemyState):
        _kill_enemy(st, target)
    elif isinstance(target, TokenState):
        _remove_token(st, target)
    else:  # a player-character: incapacitated (its channels then break)
        _log(st, "incapacitated", f"{target.name} is incapacitated.", character=target.id)
        # Afflictions conclude when the creature falls (D8-2.1/2.2 "dies"; an
        # incapacitation is the character-side analogue). Counters remain.
        target.poison_effects = []
        target.regen_effects = []
        # +25 ultimate gauge to each OTHER living party member, once per downing
        # (D8-3.3). The flag clears when this character stands back up.
        if not target.down_credited:
            target.down_credited = True
            for other in st.party:
                if other.id != target.id and other.alive:
                    _gain_gauge(st, other, 25)
        _note_break(st, target, "incapacitated")
        _purge_stack_from(st, target.id, "incapacitated")  # its pending spells/attacks drop
        # On-death channel triggers hear an incapacitation too. The downed
        # holder's own channels break right after (pending_break) — so a
        # "when you fall" trigger fires once, as a death rattle.
        _fire_event(st, "death", target)


def _purge_stack_from(st: GameState, source_id: str, reason: str) -> None:
    """Remove every stack item that ORIGINATES from `source_id`. When a creature leaves
    play (killed, bounced, exiled) or a player is incapacitated, the actions it put on
    the stack — its attack, ability, reaction, or spell — go with it and never resolve.
    (Items that merely TARGET the gone source are left to fizzle at resolution instead —
    they may still have other legal targets.)"""
    removed = [it for it in st.stack if it.source_id == source_id]
    if not removed:
        return
    st.stack = [it for it in st.stack if it.source_id != source_id]
    for it in removed:
        _log(st, "stack_removed",
             f"{it.label} leaves the stack — its source is gone ({reason}).",
             source=source_id, label=it.label)


def _kill_enemy(st: GameState, enemy: EnemyState) -> None:
    """A removed enemy leaves the board and its pending intent is discarded. A channel
    aimed at it simply loses its target and holds inert — losing an aura target is not
    a break cause (GDD §8), so the caster keeps concentrating until they drop it."""
    _break_enemy_channels(st, enemy, "channeler died")  # its OWN channels die with it
    if enemy in st.enemies:
        st.enemies.remove(enemy)
    if enemy.id in st.acted_enemies:
        st.acted_enemies.remove(enemy.id)
    if enemy.intent is not None:
        _log(st, "intent_discarded", f"{enemy.name}'s pending intent is discarded.",
             enemy=enemy.id)
    _log(st, "enemy_died", f"{enemy.name} dies.", enemy=enemy.id)
    _purge_stack_from(st, enemy.id, "destroyed")
    # On-death channel triggers fire after the enemy has fully left the board
    # (its own channels are already broken, so it never hears its own death).
    _fire_event(st, "death", enemy)


def _remove_token(st: GameState, token: TokenState) -> None:
    if token in st.tokens:
        st.tokens.remove(token)
    if token.id in st.acted_tokens:
        st.acted_tokens.remove(token.id)
    _log(st, "token_died", f"{token.name} is destroyed.", token=token.id)
    _purge_stack_from(st, token.id, "destroyed")
    _fire_event(st, "death", token)  # an ally token falling counts as a death


def _draw(st: GameState, char: CharacterState, n: int, ctx: dict = None) -> None:
    for _ in range(n):
        if not char.library:
            _log(st, "draw_empty", f"{char.name} has no cards left to draw.",
                 character=char.id)
            return
        card = char.library.pop(0)
        char.hand.append(card)
        # Record the draw so a later move_card with source='drawn' (same resolution)
        # can act on exactly these cards (e.g. "draw 3, put one on top").
        if ctx is not None:
            ctx.setdefault("drawn_cards", []).append(card)
        _log(st, "draw", f"{char.name} draws {card.name}.",
             character=char.id, card=card.id, card_name=card.name)
        _fire_event(st, "card_draw", char)  # one event per card drawn


def _check_end(st: GameState) -> None:
    if st.result is not None:
        return
    # Victory (Update 03 §E-B): every roster enemy must be gone for good — in the
    # graveyard or exile. A bounced enemy is "in hand" (alive, off-field), which keeps
    # the encounter live: you cannot win by bouncing the last enemy; it will redeploy.
    if not st.living_enemies() and not st.bounced_enemies():
        # Any enemy still suspended by a channeled exile is now gone for good — the
        # encounter ends before the channel could break and bring it back (GDD §8).
        for e in st.enemies:
            if e.exiled:
                _log(st, "permanent_exile",
                     f"{e.name} is permanently exiled — the encounter ends with it suspended.",
                     target=e.id)
        st.result = "victory"
        _log(st, "win", "All enemies defeated — the party wins.", result="victory")
    elif not st.living_party():
        st.result = "defeat"
        _log(st, "loss", "The party is incapacitated — defeat.", result="defeat")


# --------------------------------------------------------------------------- #
# Rows, reachability (R-1) and deterministic ordering (R-6)
# --------------------------------------------------------------------------- #
_ROW_RANK = {"front": 0, "mid": 1, "rear": 2}


def _row_rank(row: str) -> int:
    return _ROW_RANK.get(row, 0)


def _ordered(combatants: List) -> List:
    """Canonical resolution / priority order (R-6): row (Front>Mid>Rear), then Level
    (low→high), then name (alphabetical)."""
    return sorted(combatants, key=lambda c: (_row_rank(c.row), getattr(c, "level", 1), c.name))


def _reachable_targets(attacker, defenders: List, mode: Optional[str] = None) -> List:
    """The opposing creatures `attacker` may legally strike, per R-1.

    Ranged hits any row (incl. flyers). Ground melee hits the front-most occupied
    row, and can't touch flyers without reach. A flying melee attacker ignores the
    front-line but is pinned by a defender with reach to rows not behind it.

    `mode` overrides the attacker's own attack mode — the enemy heuristic uses it to
    ask "what could I hit in melee?" vs "…in ranged?" without mutating the enemy."""
    if not defenders:
        return []
    if mode is None:
        mode = getattr(attacker, "attack_mode", "melee")
    akw = getattr(attacker, "keywords", {})
    if mode == "ranged":
        return list(defenders)
    if "flying" in akw:  # flying melee ignores the shield; reach defenders pin it
        reach_rows = [_row_rank(d.row) for d in defenders if "reach" in getattr(d, "keywords", {})]
        if reach_rows:
            limit = min(reach_rows)
            return [d for d in defenders if _row_rank(d.row) <= limit]
        return list(defenders)
    front = min(_row_rank(d.row) for d in defenders)  # front-most occupied row
    cands = [d for d in defenders if _row_rank(d.row) == front]
    if "reach" not in akw:  # ground melee without reach can't hit flyers
        cands = [d for d in cands if "flying" not in getattr(d, "keywords", {})]
    return cands


def _lowest_hp(combatants: List):
    """Lowest effective-HP target, ties broken by the canonical order (R-6)."""
    if not combatants:
        return None
    return min(_ordered(combatants), key=lambda c: c.effective_hp)


def _legal_attack_targets(st: GameState, actor: CharacterState) -> List[EnemyState]:
    """The enemies `actor` may basic-attack, honouring its attack mode + rows — and a
    live enemy taunt (§F-3 "taunt-us"): while the taunter lives and is reachable, it is
    the ONLY legal basic-attack target. An unreachable/dead taunter lifts the bind."""
    reachable = _reachable_targets(actor, st.living_enemies())
    if actor.taunted_to is not None:
        bound = [e for e in reachable if e.id == actor.taunted_to]
        taunter = st.enemy(actor.taunted_to)
        if taunter is None or not taunter.alive:
            actor.taunted_to = None  # taunter gone — the bind dies with it
        elif bound:
            return bound
        # taunter alive but unreachable: attacks fall back to the normal pool
    return reachable


# --------------------------------------------------------------------------- #
# Legal-action enumeration
# --------------------------------------------------------------------------- #
_COLOR_NAME = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}


def _legal(st: GameState) -> List[Action]:
    if st.pending_choice is not None:
        return _legal_choice(st)
    actor = st.character(st.priority)
    if actor is None:
        return []
    if st.phase == "capacity" and not st.stack:
        return _legal_capacity(st, actor)
    return _legal_react(st, actor) if st.stack else _legal_main(st, actor)


# Destination phrasing for a card-move choice's button label.
_MOVE_DEST_LABEL = {
    "hand": "into your hand", "library_top": "on top of your library",
    "library_bottom": "on the bottom of your library",
    "library_shuffle": "into your library", "graveyard": "into your graveyard",
    "exile": "into exile",
}


def _move_choice_label(effect, card) -> str:
    """The button text for picking `card` for a move_card choice — 'Discard X' for
    a hand→graveyard move, otherwise 'Move X <destination>'."""
    if effect.source == "hand" and effect.destination == "graveyard":
        return f"Discard {card.name}"
    return f"Move {card.name} {_MOVE_DEST_LABEL.get(effect.destination, '')}".strip()


def _legal_choice(st: GameState) -> List[Action]:
    """A mandatory mid-resolution card pick: one action per candidate (no pass —
    the choice must be made while cards remain). For a scry each revealed card
    offers two actions (top / bottom). For a trigger-time target pick one action
    per legal creature (the ability is on the stack; it must be aimed)."""
    pc = st.pending_choice
    if pc.kind == "mode":
        return [Action("choose_mode", pc.chooser_id, mode=key,
                       label=f"{pc.item.label}: {label}")
                for key, label in _modal_pick_options(pc.effect)]
    if pc.kind == "target":
        what = _effect_site_label(pc.effect)
        suffix = f" — {what}" if what else ""
        return [Action("choose_target", pc.chooser_id, target_id=tid,
                       label=f"Target {tl}{suffix}")
                for tid, tl in _effect_target_options(st, pc.effect, pc.item.card)]
    if pc.kind == "scry":
        actions: List[Action] = []
        draw_pos = len(pc.top) + 1  # the next 'on top' pick becomes draw position N
        for i, card in enumerate(pc.candidates):
            actions.append(Action("choose_scry", pc.chooser_id, choice=i, target_id="top",
                                  label=f"Put {card.name} on top (draw #{draw_pos})"))
            actions.append(Action("choose_scry", pc.chooser_id, choice=i, target_id="bottom",
                                  label=f"Put {card.name} on the bottom"))
        return actions
    return [Action("choose_card", pc.chooser_id, choice=i,
                   label=_move_choice_label(pc.effect, card))
            for i, card in enumerate(pc.candidates)]


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
    # Stunned (§F-3 enemy Debilitate): the proactive window is denied outright — the
    # only move is to end the turn (which spends one stack of the stun). Reaction
    # windows (instants / Mitigate) are unaffected; see _r_stun.
    if actor.stunned > 0:
        return [Action("end_turn", actor.id, label="Stunned — end turn")]
    mode = actor.acted_mode
    vig = _has_kw(actor, "vigilance")  # lifts the attack-vs-cast restriction (GDD §7)
    # Attack (basic, once per round): locked out after a Cast unless vigilant, and
    # forbidden outright while a `prevent attack` shield (Pacifism) rides the actor.
    if (not actor.used_attack and not _prevented_action(actor, "attack")
            and (mode is None or (vig and mode == "cast"))):
        dbl = " ×2 (double strike)" if _has_kw(actor, "double_strike") else ""
        for e in _legal_attack_targets(st, actor):  # only rows this attack can reach
            actions.append(Action("attack", actor.id, target_id=e.id,
                                  label=f"Attack {e.name} ({actor.attack_mode} "
                                        f"Power {actor.current_power}){dbl}"))
    if mode is None and not actor.used_defend:  # Defend (the defensive action)
        actions.append(Action("defend", actor.id, label=f"Defend (+{_DEFEND_TEMP_HP} temp HP)"))
    # Move (Update 02 §M-B.4): the proactive Move costs the action; haste makes one
    # voluntary move free (offered alongside the normal action). Once per turn.
    if actor.pending_voluntary is None and (mode is None or _has_kw(actor, "haste")):
        free = " (free, haste)" if _has_kw(actor, "haste") else ""
        for row in ("front", "mid", "rear"):
            if row != actor.row:
                actions.append(Action("move", actor.id, target_id=row,
                                      label=f"Move to {row.capitalize()}{free}"))
    # Cast sorcery-speed spells (sorcery/channeled): after an Attack only if vigilant.
    if mode in (None, "cast") or (vig and mode == "attack"):
        for card in actor.hand:
            if card.timing in _SORCERY_SPEED and _can_pay(actor, card):
                actions += _cast_actions(st, actor, card)
    for card in actor.hand:            # Free instants (mana-limited, any time)
        if card.timing == Timing.instant and _can_pay(actor, card):
            actions += _cast_actions(st, actor, card)
    actions += _heroic_actions(st, actor, main_phase=True)  # Skill / Ultimate (D8-3)
    actions += _drop_actions(st, actor)
    actions.append(Action("end_turn", actor.id, label="End turn"))
    return actions


def _legal_react(st: GameState, actor: CharacterState) -> List[Action]:
    """An open reaction window: free instants, Mitigate (self / adjacent ally), a
    First Strike basic attack, voluntary drop, or pass."""
    actions: List[Action] = []
    for card in actor.hand:
        if card.timing == Timing.instant and _can_pay(actor, card):
            actions += _cast_actions(st, actor, card)
    # First Strike (R-12): during the ENEMY step only, a character that did NOT spend its
    # basic attack (on its turn or already this enemy step) may swing NOW as a reaction —
    # it is a plain `attack`, not a special one. It stacks above the answered action, so it
    # resolves first and can kill the attacker before its attack lands. `used_attack` gates
    # both "didn't attack on my turn" and "haven't reacted yet"; Pacifism still forbids it.
    # The tactical payoff: you can spend your turn action on Move/Defend/Cast and still hold
    # the swing for the enemy step.
    if (st.phase == "enemy" and _has_kw(actor, "first_strike") and not actor.used_attack
            and not _prevented_action(actor, "attack") and actor.stunned == 0):
        dbl = " ×2 (double strike)" if _has_kw(actor, "double_strike") else ""
        for e in _legal_attack_targets(st, actor):
            actions.append(Action("attack", actor.id, target_id=e.id,
                                  label=f"Attack {e.name} ({actor.attack_mode} "
                                        f"Power {actor.current_power}){dbl}"))
    top = st.stack[-1]
    # Mitigate (Update 02 §M-A): once per turn, answers an enemy attack-type action.
    # Self mode if it targets the actor; ally mode for an ally it targets that is in
    # an adjacent row to the actor's COMMITTED position (§M-A.5, §M-B.2).
    x = _mitigate_value(actor)
    if not actor.used_mitigate and top.source_side == "enemy" and top.kind == "attack":
        if top.target_id == actor.id:
            actions.append(Action("mitigate", actor.id, target_id=actor.id,
                                  label=f"Mitigate self (−{x} per hit)"))
        for ally in st.living_party():
            if (ally.id != actor.id and top.target_id == ally.id
                    and abs(_row_rank(actor.committed) - _row_rank(ally.row)) <= 1):
                actions.append(Action("mitigate", actor.id, target_id=ally.id,
                                      label=f"Mitigate for {ally.name} (−{x} per hit, move to {ally.row})"))
    actions += _heroic_actions(st, actor, main_phase=False)  # Skill reacts (D8-3.1)
    actions += _drop_actions(st, actor)
    actions.append(Action("pass", actor.id, label="Pass"))
    return actions


def _voluntarily_droppable(st: GameState, actor: CharacterState) -> List[Channel]:
    """The holder's channels that may be VOLUNTARILY dropped right now: ALL of them.
    Dropping is instant-speed and free — legal whenever the holder has priority
    (main phase or any reaction window), releasing the reserved mana straight back
    to the pool so it can pay for a different spell in the same window. This
    supersedes the GDD §8 same-turn hold rule (playtest ruling, Update 06): the
    channel's ongoing effect stops the moment it drops, so an early drop forfeits
    value rather than banking it."""
    return list(actor.channels)


def _drop_actions(st: GameState, actor: CharacterState) -> List[Action]:
    """Voluntary drop is a free action for each channel the holder may drop this turn
    (started before this turn). One action per droppable channel (named by `card_id`),
    plus a "drop all" (no card_id) when more than one is droppable."""
    droppable = _voluntarily_droppable(st, actor)
    if not droppable:
        return []
    actions = [Action("drop_channels", actor.id, card_id=ch.card.id,
                      label=f"Drop {ch.card.name}") for ch in droppable]
    if len(droppable) > 1:
        actions.append(Action("drop_channels", actor.id,
                              label=f"Drop concentration (end all {len(droppable)})"))
    return actions


def _heroic_actions(st: GameState, actor: CharacterState,
                    main_phase: bool) -> List[Action]:
    """The once-per-encounter Skill/Ultimate offers (D8-3). The Skill is instant
    speed — offered wherever an instant is (main phase and reaction windows); the
    Ultimate is an action — main phase only, proactive action unspent, and only
    while the gauge is full."""
    out: List[Action] = []
    if actor.skill is not None and not actor.skill_used and _can_pay(actor, actor.skill):
        out += _hero_ability_actions(st, actor, actor.skill, "use_skill", "Skill")
    if (main_phase and actor.ultimate is not None and not actor.ultimate_used
            and actor.ultimate_gauge >= 100 and actor.acted_mode is None):
        out += _hero_ability_actions(st, actor, actor.ultimate, "use_ultimate", "Ultimate")
    return out


def _hero_ability_actions(st: GameState, actor: CharacterState, card: Card,
                          kind: str, tag: str) -> List[Action]:
    """Enumerate a Skill/Ultimate exactly like a cast — one action per
    (mode × target × X) — re-labelled and re-kinded as the heroic action."""
    out = []
    for a in _cast_actions(st, actor, card):
        a.kind = kind
        a.label = a.label.replace(f"Cast {card.name}", f"{tag}: {card.name}", 1)
        out.append(a)
    return out


def _cast_actions(st: GameState, actor: CharacterState, card: Card) -> List[Action]:
    """One cast Action per (mode × legal target). Modal cards offer one branch per
    mode (the option is chosen here, at cast); a counter offers one option per
    enemy action it could answer; other cards offer one option per legal target.
    An {X}-cost card additionally offers one cast per affordable X value.
    The engine enumerates every choice — the UI never invents one."""
    base = _cost_total(card)
    # X options: every value the pool can cover beyond the base cost (the caller
    # already checked _can_pay, so spare >= 0). Non-X cards get the single None.
    x_options = (range(0, len(actor.pool) - base + 1)
                 if getattr(card.cost, "x", False) else (None,))
    return [a for x in x_options for a in _cast_actions_at_x(st, actor, card, x)]


def _cast_actions_at_x(st: GameState, actor: CharacterState, card: Card,
                       x: Optional[int]) -> List[Action]:
    xlabel = f" (X={x})" if x is not None else ""
    out: List[Action] = []
    for mode_idx, effects, mlabel in _mode_specs(card):
        prefix = f"Cast {card.name}"
        if mlabel:
            prefix += f" — {mlabel}"
        # A cast whose effects target independently (≥2 sites — Agony Warp's two
        # wounds, or a multi-mode combo like Cryptic Command's "counter + bounce")
        # offers one cast per COMBINATION of per-site picks. A site with no legal
        # option (a counter with nothing on the stack) makes that mode/combo
        # uncastable — matching "you can't choose a mode you can't target".
        sites = _target_sites(effects, card)
        if len(sites) >= 2:
            per_site = []
            for _key, side, targeted, kind in sites:
                if isinstance(side, str) and side.startswith("stack:"):
                    filt = side[len("stack:"):]
                    opts = [(f"#{s.uid}", s.label) for s in st.stack
                            if s.source_side == "enemy" and _filter_matches(filt, s)]
                else:
                    opts = _side_options(st, side)
                    if targeted:  # hexproof hostiles can't be TARGETED (GDD §7)
                        opts = [(tid, tl) for tid, tl in opts
                                if not _hexproof_hostile(st, tid)]
                    if kind == "revive":  # only a DOWNED ally can be revived
                        opts = _downed_only(st, opts)
                per_site.append(opts)
            if not all(per_site):
                continue  # a required site has no legal pick — combo uncastable
            for combo in itertools.product(*per_site):
                tids = tuple(tid for tid, _ in combo)
                labels = ", ".join(tl for _, tl in combo if tl)
                out.append(Action("cast", actor.id, card_id=card.id, target_id=tids[0],
                                  targets=tids, mode=mode_idx, x=x,
                                  label=prefix + (f" on {labels}" if labels else "") + xlabel))
        else:
            for tid, tlabel in _target_options_for(st, effects, card):
                label = prefix + (f" on {tlabel}" if tlabel else "") + xlabel
                out.append(Action("cast", actor.id, card_id=card.id, target_id=tid,
                                  mode=mode_idx, x=x, label=label))
    return out


def _modal_bullets(card: Card) -> List[str]:
    """Per-mode descriptions parsed from the card's rules text bullets — the same
    'Choose one — • A. • B.' wording shown on the card face — so the mode picker names
    what each option does instead of a bare 'Option N'. [] when there are no bullets."""
    text = card.translated_text or card.original_text or ""
    if "•" not in text:
        return []
    return [seg.strip().rstrip(".").strip() for seg in text.split("•")[1:] if seg.strip()]


def _mode_specs(card: Card):
    """[(mode_key, effects, mode_label)] — one entry per castable mode CHOICE, or a
    single (None, card.effects, "") for a non-modal card.

    "Choose one": one entry per mode; mode_key is the mode index. "Choose two" /
    "choose one or more" (`choose`>1 / `or_more`): one entry per legal COMBINATION
    of modes; mode_key is a bitmask of the chosen indices and the effects are the
    modes' effects concatenated in mode order (`_effects_of_mode` mirrors both)."""
    modal = next((e for e in card.effects
                  if e.kind == "modal" and getattr(e, "trigger", None) is None), None)
    if modal is None:
        return [(None, list(card.effects), "")]
    bullets = _modal_bullets(card)
    labels = [m.label or (bullets[i] if i < len(bullets) else "") or f"Option {i + 1}"
              for i, m in enumerate(modal.modes)]
    if not _modal_is_multi(modal):
        return [(i, list(m.effects), labels[i]) for i, m in enumerate(modal.modes)]
    n = len(modal.modes)
    k = min(max(1, getattr(modal, "choose", 1) or 1), n)
    sizes = range(k, n + 1) if getattr(modal, "or_more", False) else (k,)
    out = []
    for size in sizes:
        for combo in itertools.combinations(range(n), size):
            out.append((sum(1 << i for i in combo),
                        [e for i in combo for e in modal.modes[i].effects],
                        " + ".join(labels[i] for i in combo)))
    return out


def _iter_leaf(effects):
    """Yield effects, descending into conditional branches (so the primary target
    is found even when it lives inside an 'if …' clause). Modal is handled above."""
    for e in effects:
        if e.kind == "conditional":
            yield from _iter_leaf(e.effects)
        elif e.kind != "modal":
            yield e


def _counter_filter(effects) -> Optional[str]:
    for e in _iter_leaf(effects):
        if e.kind == "counter":
            return e.filter
    return None


def _effect_target_options(st: GameState, effect, card=None):
    """[(id, label)] one effect's chosen target may pick, under the usual pick
    rules (`targeted` honours hexproof; revive needs a downed ally). Used for the
    trigger-time target pick of a fired triggered ability. A "$slot" target
    resolves its descriptor through the card's slot table."""
    desc = getattr(effect, "target", None)
    if isinstance(desc, str) and card is not None:
        desc = card.targets.get(desc[1:])
    side = desc.side.value if getattr(desc, "side", None) is not None else "any"
    opts = _side_options(st, side)
    if getattr(desc, "targeted", False):
        opts = [(tid, tl) for tid, tl in opts if not _hexproof_hostile(st, tid)]
    if effect.kind == "revive":
        opts = _downed_only(st, opts)
    return opts


def _hexproof_hostile(st: GameState, tid) -> bool:
    """True when `tid` is a hexproof ENEMY from a player caster's point of view —
    illegal for a TARGETED pick. Friendly targeting is always fine (GDD §6/§7)."""
    e = st.enemy(tid) if tid is not None else None
    return e is not None and _has_kw(e, "hexproof")


def _downed_only(st: GameState, opts):
    """Filter creature options to DOWNED characters — the only legal picks for a
    revive (a standing ally has nothing to come back from)."""
    out = []
    for tid, tl in opts:
        c = st.character(tid) if tid is not None else None
        if c is not None and not c.alive:
            out.append((tid, tl))
    return out


def _side_options(st: GameState, side):
    """[(creature_id, label)] of the creatures a target on `side` may pick.

    Party options include DOWNED characters — incapacitation is recoverable
    (R-7), the body stays on the battlefield, and it must be pickable so heals
    and revives can reach it. Enemies/tokens leave play at 0 HP, so only living
    ones are offered."""
    if side == "enemy":
        return [(e.id, e.name) for e in st.living_enemies()]
    if side == "ally":
        return ([(c.id, c.name) for c in st.party]
                + [(t.id, t.name) for t in st.living_tokens()])
    if side == "any":
        return ([(e.id, e.name) for e in st.living_enemies()]
                + [(c.id, c.name) for c in st.party]
                + [(t.id, t.name) for t in st.living_tokens()])
    return [(None, None)]  # self-only / untargeted / 'all' (no choice to make)


def _target_options_for(st: GameState, effects, card: Card = None):
    """[(target_id, target_label)] for the card's single primary target. A counter
    targets a matching enemy action on the stack; otherwise the first targeted
    effect's side decides the creature options; self/all/untargeted needs none.
    A `$T1` slot ref resolves its side via the card's `targets` map (the form the
    Deckbuilder emits), so single-target slot cards enumerate targets too."""
    filt = _counter_filter(effects)
    if filt is not None:
        return [(f"#{s.uid}", s.label) for s in st.stack
                if s.source_side == "enemy" and _filter_matches(filt, s)]
    side, targeted, kind = None, False, None
    # Triggered effects pick their targets when the trigger fires, not at cast
    # (mirrors the _target_sites exclusion). Nested effects never carry triggers,
    # so filtering the top level before descending is sufficient.
    for e in _iter_leaf([e for e in effects if getattr(e, "trigger", None) is None]):
        desc = getattr(e, "target", None)
        if isinstance(desc, str):  # "$T1" slot ref — resolve its side from the card
            sd = card.targets.get(desc[1:]) if card is not None else None
            if sd is not None:
                side = sd.side.value if sd.side is not None else "any"
                targeted = bool(getattr(sd, "targeted", False))
                kind = e.kind
                break
            continue
        # Any CHOSEN descriptor needs a pick at cast — `targeted` governs
        # interaction rules, not whether a target is chosen. (An untargeted-chosen
        # effect cast without one fizzled at resolution: the Cryptic-bounce bug.)
        if desc is not None and getattr(desc, "mode", None) == TargetMode.chosen:
            side = desc.side.value
            targeted = bool(getattr(desc, "targeted", False))
            kind = e.kind
            break
    opts = _side_options(st, side)
    if targeted:  # a TARGETED pick may not name a hexproof hostile (GDD §7)
        opts = [(tid, tl) for tid, tl in opts if not _hexproof_hostile(st, tid)]
    if kind == "revive":  # only a DOWNED ally can be revived
        opts = _downed_only(st, opts)
    return opts


def _target_sites(effects, card: Card):
    """Ordered independent target sites for a mode's TOP-LEVEL effects. Each
    top-level CHOSEN direct descriptor is its own site (an independent target —
    e.g. Agony Warp's two wounds) whether or not it is `targeted` — `targeted`
    governs interaction rules (hexproof, "target" wording), not whether a pick is
    needed; an untargeted-chosen effect (Cryptic Command's bounce) still needs its
    creature chosen at cast, or it fizzles at resolution. Each distinct slot ref is
    one shared site. A counter is a site whose options are enemy STACK actions
    (side "stack:<filter>"). conditional/modal/self/all contribute none, so a
    conditional's nested effects reuse the primary (first) target. Returns
    [(key, side, targeted, kind)] where key is ('slot', name) or ('eff', id(effect));
    `targeted` carries the descriptor's flag so enumeration can honour hexproof
    (a targeted pick may not offer a hexproof hostile; an untargeted-chosen one
    may — non-targeting effects beat hexproof, GDD §7), and `kind` is the owning
    effect's kind so kind-specific pick rules apply (revive: downed allies only).
    Used by enumeration AND
    resolution, so site order matches between them."""
    sites = []
    seen_slots = set()

    def add(desc, eff_key, kind, forced=False):
        if isinstance(desc, str):  # "$T1" slot ref — one shared site per slot name
            name = desc[1:]
            if name in seen_slots:
                return
            seen_slots.add(name)
            sd = card.targets.get(name) if card is not None else None
            side = sd.side.value if sd is not None and sd.side is not None else "any"
            sites.append((("slot", name), side, bool(getattr(sd, "targeted", False)), kind))
        elif desc is not None and (forced
                                   or getattr(desc, "mode", None) == TargetMode.chosen):
            sites.append((eff_key, desc.side.value,
                          bool(getattr(desc, "targeted", False)), kind))

    for e in effects:
        if e.kind in ("conditional", "modal"):
            continue
        # A TRIGGERED effect's chosen target is NOT a cast-time site: it is
        # picked when the trigger fires (MTG-style — see _raise_next_trigger_pick).
        # A `$slot` still becomes a cast site when an untriggered effect (a
        # continuous aura) shares it — the fired effect then reuses that target.
        if getattr(e, "trigger", None) is not None:
            continue
        if e.kind == "counter":
            # The counter's target is an enemy action on the stack, not a creature.
            sites.append((("eff", id(e)), f"stack:{e.filter}", True, "counter"))
            continue
        if e.kind == "fight":
            # Fight's two targets are always chosen (even authored inline). Force both
            # sites, keying `other` apart from the primary so each binds independently.
            add(getattr(e, "target", None), ("eff", id(e)), "fight", forced=True)
            add(getattr(e, "other", None), ("eff_other", id(e)), "fight", forced=True)
            continue
        add(getattr(e, "target", None), ("eff", id(e)), e.kind)
    return sites


def _effect_site_label(e) -> Optional[str]:
    """A short, human phrase for the effect a target site feeds — shown on the
    targeting popup so a multi-target card names each pick (e.g. Agony Warp's two
    wounds) instead of the ambiguous "target 1 / target 2". None == let the UI use
    its generic fallback."""
    k = e.kind

    def stat(v):  # a Ref power/toughness ("pump X") displays as X
        return v if isinstance(v, int) else "X"

    if k == "wound":
        return f"weaken −{stat(e.power)}/−{stat(e.toughness)}"
    if k == "pump":
        return f"buff +{stat(e.power)}/+{stat(e.toughness)}"
    if k == "counters":
        return f"+{stat(e.power)}/+{stat(e.toughness)} counters"
    if k == "deal_damage":
        return f"deal {e.amount} damage" if isinstance(e.amount, int) else "deal damage"
    if k == "heal":
        return f"heal {e.amount}" if isinstance(e.amount, int) else "heal"
    if k == "grant_keyword":
        return "grant " + ", ".join(e.keywords) if getattr(e, "keywords", None) else "grant keyword"
    if k == "remove_keyword":
        return "remove " + ", ".join(e.keywords) if getattr(e, "keywords", None) else "remove keyword"
    return {
        "destroy": "destroy",
        "exile": "exile",
        "bounce": "return to hand",
        "stun": "stun",
        "counter": "counter",
        "taunt": "taunt",
        "protection": "protect",
        "strip_intent": "strip intent",
        "revive": "revive",
        "lose_life": "drain",
    }.get(k)


def _site_label(key, effects, card: Card) -> Optional[str]:
    """The label for one target site (from `_target_sites`): the effect that site
    feeds, or the first effect sharing its `$slot`."""
    kind, ident = key
    if kind in ("eff", "eff_other"):
        e = next((x for x in effects if id(x) == ident), None)
        if e is None:
            return None
        if e.kind == "fight":
            return "fight" if kind == "eff" else "fight against"
        return _effect_site_label(e)
    if kind == "slot":  # a shared slot — describe it by the first effect that uses it
        for e in effects:
            if slot_name(getattr(e, "target", None)) == ident:
                return _effect_site_label(e)
    return None


def auto_pass_action(state: GameState) -> Optional[Action]:
    """The synthetic action a presentation layer should submit when the current
    priority holder has NO meaningful option (Design Update 08 §D8-4) — or None
    when a real decision exists. Engine-truth, computed from the legal set:

      * reaction window: the set holds nothing beyond `pass`/`drop_channels`,
        and any drop would not make an instant in hand or an unused Skill
        castable (a drop that enables nothing is not a decision);
      * main phase: after the same refinement, only `end_turn` remains.

    A `pending_choice` always waits (choices are never auto-resolved), as does
    the capacity-colour choice. Deterministic: the same state always auto-passes
    the same seats, so scripted scenarios and replay are unaffected. The engine
    itself never submits this — the game server does (the cockpit never will)."""
    st = copy.deepcopy(state)
    _advance(st)
    if st.result is not None or st.priority is None or st.pending_choice is not None:
        return None
    if st.phase == "capacity" and not st.stack:
        return None  # the capacity colour is a mandatory real choice
    actions = _legal(st)
    if not actions:
        return None
    kinds = {a.kind for a in actions}
    actor = st.character(st.priority)
    if "pass" in kinds and not (kinds - {"pass", "drop_channels"}):
        if "drop_channels" in kinds and _drop_enables_play(st, actor):
            return None
        return Action("pass", st.priority, auto=True, label="Pass (auto)")
    if "end_turn" in kinds and not (kinds - {"end_turn", "drop_channels"}):
        if "drop_channels" in kinds and _drop_enables_play(st, actor):
            return None
        return Action("end_turn", st.priority, auto=True, label="End turn (auto)")
    return None


def _drop_enables_play(st: GameState, actor: Optional[CharacterState]) -> bool:
    """Would releasing the reserved channel mana make any instant in hand, or an
    unused Skill, castable (cost ≤ pool + reserved, colours respected)? (§D8-4.1)"""
    if actor is None or not actor.reserved:
        return False
    probe = CharacterState(id=actor.id, name=actor.name, max_hp=1, hp=1,
                           power=0, hand_size=0)
    probe.pool = list(actor.pool) + list(actor.reserved)
    candidates = [c for c in actor.hand if c.timing == Timing.instant]
    if actor.skill is not None and not actor.skill_used:
        candidates.append(actor.skill)
    return any(_can_pay(probe, c) for c in candidates)


def cast_target_labels(state: GameState, action: Action) -> List[Optional[str]]:
    """Per-site effect labels for a cast, aligned with its target sites (so the UI
    names what each pick is for). Empty for non-casts / untargeted casts."""
    if action.kind != "cast":
        return []
    actor = state.character(action.actor_id)
    if actor is None:
        return []
    card = next((c for c in actor.hand if c.id == action.card_id), None)
    if card is None:
        return []
    effects = next((eff for midx, eff, _ in _mode_specs(card) if midx == action.mode), None)
    if effects is None:
        effects = _mode_specs(card)[0][1]
    return [_site_label(key, effects, card)
            for key, *_ in _target_sites(effects, card)]


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


def _pay(actor: CharacterState, card: Card, explicit: Optional[List[str]] = None,
         x: int = 0) -> List[str]:
    """Spend the cost from the pool; return the actual colours paid (so a channel
    can reserve exactly those and release them on end). `x` is the chosen X for
    an {X} cost — paid as that much extra generic mana.

    `explicit` (a player-chosen list of colours) overrides the deterministic WUBRG
    order when the generic portion could be paid multiple ways — it is validated to
    exactly cover the cost and be available before anything is spent."""
    if explicit is not None:
        _validate_payment(actor, card, explicit, x=x)
        for c in explicit:
            actor.pool.remove(c)
        return list(explicit)
    pool = actor.pool
    paid: List[str] = []
    for color, n in card.cost.colors.items():
        for _ in range(n):
            pool.remove(color.value)
            paid.append(color.value)
    for _ in range(card.cost.generic + max(0, int(x or 0))):
        for c in _PAY_ORDER:  # deterministic: spend generic (and X) in WUBRG order
            if c in pool:
                pool.remove(c)
                paid.append(c)
                break
    return paid


def _validate_payment(actor: CharacterState, card: Card, chosen: List[str],
                      x: int = 0) -> None:
    """Reject an explicit mana payment that doesn't exactly settle `card`'s cost.

    The payment must (1) be drawable from the pool, (2) include each coloured pip
    the cost demands, and (3) total exactly coloured + generic (+ chosen X) mana.
    Extra colours beyond the coloured pips count toward the generic portion."""
    from collections import Counter
    have = Counter(actor.pool)
    pay = Counter(chosen)
    for color, n in pay.items():
        if have.get(color, 0) < n:
            raise ValueError(f"{actor.name} cannot pay {n}×{color} (pool lacks it)")
    need_colored = {c.value: n for c, n in card.cost.colors.items()}
    for color, n in need_colored.items():
        if pay.get(color, 0) < n:
            raise ValueError(f"payment is missing {n}×{color} for {card.name}")
    total_needed = sum(need_colored.values()) + card.cost.generic + max(0, int(x or 0))
    if len(chosen) != total_needed:
        raise ValueError(f"payment must total {total_needed} mana for {card.name}, "
                         f"got {len(chosen)}")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
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
