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
    PendingChoice,
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
        # react or pass before the top can resolve. Always pause here.
        if st.stack:
            if st.priority is None:
                st.priority = _ordered(st.living_party())[0].id  # canonical order (R-6)
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
    """The next living character (canonical order R-6) that hasn't ended its turn.
    Incapacitated PCs are skipped (alive == effective_hp > 0)."""
    for c in _ordered(st.living_party()):
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
    _log(st, "turn_start", f"— Turn {st.turn} —", turn=st.turn)
    for c in st.party:
        c.capacity_chosen = False
        c.committed = c.row  # Update 02 §M-B.5: begin the turn committed to where you stand
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
    _fire_capacity_increase(st, char)


def _fire_capacity_increase(st: GameState, char: CharacterState) -> None:
    """Recurring `capacity_increase` channel effects (landfall) fire whenever this
    holder's mana capacity rises — the +1/turn lock and any ramp (GDD §8)."""
    for ch in list(char.channels):
        item = StackItem(kind="ability", source_id=char.id, source_side="party",
                         label=ch.card.name, effects=[], target_id=ch.target_id, card=ch.card)
        ctx = {"capacity": char.capacity}
        for effect in ch.card.effects:
            if getattr(effect, "trigger", None) == "capacity_increase":
                _resolve_effect(st, item, effect, ctx)


def _upkeep_draws(st: GameState) -> None:
    """After capacity is set: mana refreshes (channels keep their reserve out of
    the pool), each character draws 1, and per-round uses / turn flags reset."""
    for c in st.living_party():
        c.pool = _refreshed_pool(c)  # every unreserved locked colour spendable
        _draw(st, c, 1)
        c.used_attack = c.used_defend = c.used_mitigate = False
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
    """The Intents step (R-4/R-5): every enemy AND every ally token declares its
    telegraphed intent against the current state, in the canonical order. Allies
    use the same deterministic heuristic as enemies, applied on the party's side."""
    for e in _ordered(st.living_enemies()):
        _declare_enemy_intent(st, e)
    for t in _ordered(st.living_tokens()):
        _declare_ally_intent(st, t)


def _declare_enemy_intent(st: GameState, e: EnemyState) -> None:
    tmpl = e.intent_template
    if e.stunned > 0:  # stun: skip this intent, spend one charge (R-11)
        e.stunned -= 1
        e.intent = None
        _log(st, "stunned", f"{e.name} is stunned and skips its intent ({e.stunned} left).",
             enemy=e.id, intents=e.stunned)
        return
    target, mode, amount, name = _choose_enemy_attack(st, e)
    if target is None:
        e.intent = None
        _log(st, "no_target", f"{e.name} has no reachable target and declares nothing.",
             enemy=e.id)
        return
    e.attack_mode = mode  # the chosen attack carries onto the stack (R-1) and the panel
    effects = [DealDamage(amount=amount, target=t_chosen("ally", targeted=True))]
    # An attack-type intent lands on the stack as an `attack` (so combat_damage
    # prevention and ability/attack counters answer it — R-1/R-11).
    kind = "attack" if tmpl.get("intent_type", "attack") == "attack" else tmpl.get("action_type", "ability")
    e.intent = Intent(name=name, action_type=kind, effects=effects, target_id=target.id)
    _log(st, "intent_declared",
         f"{e.name} declares {name} ({mode} {amount} dmg) → {target.name}.",
         enemy=e.id, intent=name, amount=amount, target=target.id, mode=mode)


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

    Reach is computed per mode without mutating the enemy; hexproof targets are
    excluded (an enemy's targeted attack can't land on them — GDD §6/§7)."""
    party = st.living_party()
    tmpl = e.intent_template
    primary_mode = tmpl.get("mode", "melee")
    primary = [c for c in _reachable_targets(e, party, mode=primary_mode)
               if not _has_kw(c, "hexproof")]
    primary_amount, primary_name = _attack_amount(e, tmpl), tmpl["name"]
    # The weaker ranged attack is a fallback only a melee-primary enemy can have.
    has_fallback = bool(e.ranged_template) and primary_mode == "melee"
    fallback = ([c for c in _reachable_targets(e, party, mode="ranged")
                 if not _has_kw(c, "hexproof")] if has_fallback else [])
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
        if forced is not None and forced.alive and not _has_kw(forced, "hexproof"):
            if forced in primary or not has_fallback:
                return forced, primary_mode, primary_amount, primary_name
            return forced, "ranged", fb_amount, fb_name

    rule = tmpl.get("targeting", "lowest_hp_party")

    if rule == "lowest_hp":  # the Brute: always the globally lowest-HP character
        return aim(_lowest_hp(fallback if has_fallback else primary))

    if rule not in ("lowest_hp_party", "front_lowest_hp"):  # a fixed character id
        cand = st.character(rule)
        if cand is not None and cand.alive and not _has_kw(cand, "hexproof"):
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
    """Move a declared intent onto the stack as an action (GDD §5.2)."""
    st.acted_enemies.append(enemy.id)
    intent = enemy.intent
    if intent is None or intent.target_id is None:
        return
    _push(st, StackItem(kind=intent.action_type, source_id=enemy.id,
                        source_side="enemy", label=intent.name,
                        effects=intent.effects, target_id=intent.target_id,
                        attack_mode=enemy.attack_mode))
    enemy.intent = None
    st.priority = None  # open a fresh reaction window (party order, set in _advance)
    st.passes = 0
    _log(st, "intent_execute", f"{enemy.name} executes {intent.name}.",
         enemy=enemy.id, label=intent.name)


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
    effects = [DealDamage(amount=token.current_power, target=t_chosen("enemy", targeted=True))]
    _push(st, StackItem(kind="attack", source_id=token.id, source_side="party",
                        label=f"{token.name}'s attack", effects=effects,
                        target_id=target.id, attack_mode=token.attack_mode))
    st.priority = None
    st.passes = 0
    _log(st, "ally_attack", f"{token.name} attacks {target.name} (Power {token.current_power}).",
         token=token.id, target=target.id, power=token.current_power)


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
        if dur in ("end_of_turn", "this_turn"):
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
        "drop_channels": _do_drop_channels,
    }[action.kind]
    handler(st, action)


def _do_choose_mana(st: GameState, action: Action) -> None:
    """Lock the colour of this turn's +1 capacity slot (start of turn, pre-draw)."""
    char = st.character(action.actor_id)
    _lock_capacity(st, char, action.color, auto=False)
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
    if actor.attack_mode == "melee":  # Update 02 §M-B.3: stepping up commits you to Front
        actor.committed = "front"
    hits = 2 if _has_kw(actor, "double_strike") else 1  # double strike: strikes twice
    effects = [DealDamage(amount=actor.current_power, target=t_chosen("enemy", targeted=True))
               for _ in range(hits)]
    _push(st, StackItem(kind="attack", source_id=actor.id, source_side="party",
                        label="Basic Attack", effects=effects, target_id=action.target_id,
                        attack_mode=actor.attack_mode))
    _open_window(st, actor.id, reactive=False)
    tgt = st.combatant(action.target_id)
    _log(st, "attack_declared",
         f"{actor.name} attacks {tgt.name} ({actor.attack_mode} Power {actor.current_power}).",
         character=actor.id, target=action.target_id, power=actor.current_power,
         mode=actor.attack_mode)


def _do_cast(st: GameState, action: Action) -> None:
    """Cast a spell. Sorcery-speed spells (sorceries/channeled) are the proactive
    Cast — a Cast turn may cast several if mana allows; instants are free."""
    actor = st.character(action.actor_id)
    card = _card_in_hand(actor, action.card_id)
    reactive = bool(st.stack)  # a cast made inside an open window stacks above
    paid = _pay(actor, card)
    actor.hand.remove(card)
    actor.graveyard.append(card)  # the card goes to the graveyard at once (R-9)
    if card.timing in _SORCERY_SPEED and not reactive:
        actor.acted_mode = "cast"  # choosing Cast; further sorcery-speed casts ok
    reserved = list(paid) if card.timing == Timing.channeled else []
    _push(st, StackItem(kind="spell", source_id=actor.id, source_side="party",
                        label=card.name, effects=list(card.effects),
                        target_id=action.target_id, targets=action.targets,
                        card_id=card.id,
                        card=card, reserved=reserved, mode=action.mode,
                        cast_mode="reaction" if reactive else "action"))
    _open_window(st, actor.id, reactive=reactive)
    tgt = st.combatant(action.target_id)
    _log(st, "cast", f"{actor.name} casts {card.name}"
         + (f" on {tgt.name}" if tgt else "") + f". Mana: {_mana_str(actor.pool)}.",
         character=actor.id, card=card.id, target=action.target_id)


def _do_defend(st: GameState, action: Action) -> None:
    """The free defensive action: gain temporary HP — a positive `temp_mod` buffer
    that raises effective_hp and expires at End (R-7). (Magnitude is a placeholder
    until gear/flavour set it.)"""
    actor = st.character(action.actor_id)
    actor.acted_mode = "defend"
    actor.used_defend = True
    actor.temp_mod += _DEFEND_TEMP_HP
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
    """Voluntary drop (a free action): end all of the holder's channels at once."""
    actor = st.character(action.actor_id)
    _log(st, "drop_channels", f"{actor.name} drops concentration.", character=actor.id)
    _break_channels(st, actor, reason="voluntary")


_DEFEND_TEMP_HP = 3   # placeholder; GDD leaves Defend's amount to gear/flavour


def _push(st: GameState, item: StackItem) -> StackItem:
    """Push an item onto the stack, stamping it with a unique id so a counter can
    name the exact action it answers."""
    st.stack_seq += 1
    item.uid = st.stack_seq
    st.stack.append(item)
    return item


def _open_window(st: GameState, actor_id: str, reactive: bool) -> None:
    """After a player adds to the stack, seed the reaction window. A proactive
    add restarts priority at party order; a reactive add hands off to the next
    player (round-robin) so the active player isn't asked twice in a row."""
    st.passes = 0
    st.priority = _next_priority_after(st, actor_id) if reactive else None


def _next_priority_after(st: GameState, actor_id: str) -> str:
    ids = [c.id for c in _ordered(st.living_party())]  # canonical priority order (R-6)
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
    ctx = _new_ctx(st, item)
    _resolve_effect_list(st, item, item.effects, ctx)


def _new_ctx(st: GameState, item: StackItem) -> dict:
    """A fresh per-resolution context: mana capacity for `mana_capacity` values and
    the per-site target bindings for an independent multi-target card."""
    ctx: dict = {}
    src = st.character(item.source_id)
    ctx["capacity"] = src.capacity if src is not None else 0
    if item.targets:
        top = item.effects
        modal = next((e for e in item.effects if e.kind == "modal"), None)
        if modal is not None:
            top = _effects_of_mode(item, modal)
        ctx["site_target"] = {key: tid for (key, _side), tid
                              in zip(_target_sites(top, item.card), item.targets)}
    return ctx


def _resolve_effect_list(st: GameState, item: StackItem, effects, ctx: dict) -> None:
    """Resolve a stack item's top-level effects in order. When a top-level
    move_card needs the player to pick which cards move (more legal candidates than
    it moves), pause: record a PendingChoice with the not-yet-resolved effects and
    return. `_do_choose_card` performs the move and resumes here. Effects nested in
    a conditional/modal keep auto-picking (handled inside `_resolve_effect`)."""
    for i, effect in enumerate(effects):
        if getattr(effect, "kind", None) == "move_card" and getattr(effect, "trigger", None) is None:
            char = st.character(item.source_id)
            if char is not None:
                cands = _move_candidates(char, effect, ctx)
                if len(cands) > effect.count:  # a genuine "which cards?" choice
                    st.pending_choice = PendingChoice(
                        chooser_id=char.id, effect=effect, candidates=cands,
                        need=effect.count, remaining=list(effects[i + 1:]), item=item)
                    return
        _resolve_effect(st, item, effect, ctx)


def _effects_of_mode(item: StackItem, modal_effect) -> List:
    """The chosen mode's effects for a modal card (the mode picked at cast)."""
    idx = item.mode if item.mode is not None else 0
    idx = max(0, min(idx, len(modal_effect.modes) - 1))
    return list(modal_effect.modes[idx].effects)


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


def _apply_static(st: GameState, target, effect, sign: int, log_it: bool = True) -> None:
    """Apply (sign +1) or lift (sign −1) one continuous effect on one creature.

    Stat auras (pump/counters add, wound subtracts) ride `power_bonus`/`temp_mod`
    and are re-applied each end step (those layers reset), so reapply passes
    `log_it=False` to stay quiet."""
    k = effect.kind
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
                target.exiled = True
                target.intent = None  # a suspended enemy telegraphs nothing
                if target.id in st.acted_enemies:
                    st.acted_enemies.remove(target.id)
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
        target.power_bonus += sign * polarity * effect.power
        target.temp_mod += sign * polarity * effect.toughness  # re-applied every end step
        if log_it:
            verb = "gains" if sign > 0 else "loses"
            sgn = "-" if polarity < 0 else "+"
            _log(st, "aura", f"{target.name} {verb} {sgn}{effect.power}/{sgn}{effect.toughness} "
                 f"(channel).", target=_tid(target))
    elif log_it:
        _log(st, "unhandled", f"(continuous '{k}' not modelled this milestone)", kind=k)


def _apply_continuous(st: GameState, channel: Channel, effect) -> None:
    for target in _continuous_targets(st, channel, effect):
        _apply_static(st, target, effect, +1)


def _remove_continuous(st: GameState, channel: Channel, effect) -> None:
    for target in _continuous_targets(st, channel, effect):
        _apply_static(st, target, effect, -1)


def _reapply_channel_stats(st: GameState) -> None:
    """After the end step clears the temp layers, re-apply the stat auras held by
    channels (pump/counters/wound) so a sustained anthem or debuff persists."""
    for holder in st.living_party():
        for channel in holder.channels:
            for effect in channel.card.effects:
                if _is_continuous(effect) and effect.kind in _STAT_CONTINUOUS:
                    for target in _continuous_targets(st, channel, effect):
                        _apply_static(st, target, effect, +1, log_it=False)


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
    effects and release all reserved mana into the pool as a respondable stack
    trigger (GDD §8). The card is already in the graveyard (R-9) — the channel
    simply ends."""
    if not char.channels:
        return
    released: List[str] = []
    for channel in char.channels:
        for effect in channel.card.effects:
            if _is_continuous(effect):
                _remove_continuous(st, channel, effect)
        released.extend(channel.reserved)
        _log(st, "channel_end", f"{channel.card.name}'s channel ends (the card is "
             f"already in the graveyard).", character=char.id, card=channel.card.id, reason=reason)
    char.channels = []
    # Release the reserved mana immediately so it can fund a reaction this window,
    # and put a respondable trigger on the stack (GDD §8).
    char.pool.extend(released)
    _push(st, StackItem(kind="ability", source_id=char.id, source_side="party",
                        label="Mana Release", effects=[], target_id=None))
    st.priority = None
    st.passes = 0
    _log(st, "mana_released",
         f"{char.name}'s channels break ({reason}); {_mana_str(released)} released "
         f"(pool now {_mana_str(char.pool)}).",
         character=char.id, released=list(released), reason=reason)


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
        if _is_targeted(effect) and (target is None or not _legal_target(target)):
            _log(st, "fizzle", f"{item.label}'s {effect.kind} fizzles (no legal target).",
                 kind=effect.kind)
            continue
        # Hexproof: an enemy's targeted effect can't land on a hexproof character
        # (friendly targeting is fine) — GDD §6/§7.
        if (_is_targeted(effect) and item.source_side == "enemy"
                and target is not None and _has_kw(target, "hexproof")):
            _log(st, "fizzle", f"{item.label} fizzles — {target.name} has Hexproof.",
                 kind=effect.kind)
            continue
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
    return False


def _resolve_target(st: GameState, item: StackItem, effect):
    """The single combatant an effect lands on (first of the resolution set)."""
    targets = _resolution_targets(st, item, effect)
    return targets[0] if targets else None


def _is_targeted(effect) -> bool:
    desc = getattr(effect, "target", None)
    return bool(getattr(desc, "targeted", False))


def _legal_target(target) -> bool:
    return getattr(target, "alive", False)


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
        raise ValueError(f"unsupported value reference '{amount.ref}'")
    if amount == "all":
        return 0  # guarded earlier; never reached for a real effect
    return int(amount)


# ---- one handler per effect primitive --------------------------------------- #
def _r_deal_damage(st, item, effect, target, ctx):
    amount = _value(effect.amount, ctx)
    if item.kind == "attack":  # Mitigate answers attack-type hits only (Update 02 §M-A.1)
        target, amount = _apply_mitigation(st, item, target, amount)
    _deal_damage(st, target, amount, source=item.label,
                 source_obj=st.combatant(item.source_id), damage_kind=item.kind)


def _r_heal(st, item, effect, target, ctx):
    _heal(st, target, _value(effect.amount, ctx))


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
    # Pump (+X/+X): +X Power and +X temp_mod — a buffer that lifts effective_hp and
    # expires at End (R-7).
    if hasattr(target, "power_bonus"):
        target.power_bonus += effect.power
    target.temp_mod += effect.toughness
    _log(st, "pump", f"{target.name} gets +{effect.power}/+{effect.toughness} "
         f"(eff HP {target.effective_hp}).", target=_tid(target),
         power=effect.power, toughness=effect.toughness)


def _r_draw(st, item, effect, target, ctx):
    _draw(st, target, _value(effect.amount, ctx), ctx)


def _r_scry(st, item, effect, target, ctx):
    # Minimal scry: reveal the top card; default-keep (no reorder). The REPL can
    # surface the card; the scenario never casts a scry, so keep-on-top suffices.
    n = _value(effect.amount, ctx)
    top = [c.name for c in target.library[:n]]
    _log(st, "scry", f"{target.name} scries {n}: {', '.join(top) or '(empty)'}.",
         target=_tid(target), amount=n, revealed=top)


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
    # Create autonomous ally token(s). The effect carries the stats/keywords the
    # card author chose; anything it leaves unset falls back to the scenario's
    # token definition (legacy `tokens` map).
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


def _r_exile(st, item, effect, target, ctx):
    # Exile removes permanently. Minions always (no boss this milestone); a player
    # character/token is removed to 0 (incapacitated / destroyed) — indestructible
    # does NOT save against exile (GDD §7).
    if isinstance(target, EnemyState):
        _log(st, "exiled", f"{target.name} is exiled.", target=target.id, level=target.level)
        ctx["destroyed_target"] = {"level": target.level}
        _kill_enemy(st, target)
    elif isinstance(target, TokenState):
        _remove_token(st, target)
    elif target is not None:
        target.hp = 0
        _after_damage(st, target)


def _r_bounce(st, item, effect, target, ctx):
    # Bounce removes a minion (it re-enters after a reset, later — not modelled, so
    # it leaves the board like a removal). Ally permanents have no hand to return to.
    if isinstance(target, EnemyState):
        _log(st, "bounced", f"{target.name} is returned (removed).", target=target.id)
        _kill_enemy(st, target)
    elif isinstance(target, TokenState):
        _remove_token(st, target)


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
    # Cancel the enemy action this counter named, if it's still on the stack and
    # matches the filter (a filter node matches its descendants — GDD §5.4).
    uid = _parse_uid(item.target_id)
    victim = next((s for s in st.stack if s.uid == uid), None) if uid is not None else None
    if victim is None or victim.source_side != "enemy" or not _filter_matches(effect.filter, victim):
        _log(st, "counter_fizzle", f"{item.label} has nothing to counter.", kind="counter")
        return
    st.stack.remove(victim)
    _log(st, "countered", f"{item.label} cancels {victim.label}.",
         label=victim.label, source=victim.source_id)


def _r_strip_intent(st, item, effect, target, ctx):
    if isinstance(target, EnemyState) and target.intent is not None:
        name = target.intent.name
        target.intent = None
        _log(st, "strip_intent", f"{target.name}'s telegraphed {name} is stripped.",
             enemy=target.id)


def _r_stun(st, item, effect, target, ctx):
    if isinstance(target, EnemyState):
        target.stunned += int(getattr(effect, "intents", 1))
        _log(st, "stun", f"{target.name} is stunned (skips {target.stunned} intent(s)).",
             enemy=target.id, intents=target.stunned)


def _r_wound(st, item, effect, target, ctx):
    # Wound (−X/−X): −X Power and −X to temp_mod (R-7). If that drives effective_hp
    # ≤ 0 it kills/incaps immediately — even through indestructible.
    if hasattr(target, "power_bonus"):
        target.power_bonus -= effect.power
    target.temp_mod -= effect.toughness
    _log(st, "wound", f"{target.name} suffers -{effect.power}/-{effect.toughness} "
         f"(eff HP {target.effective_hp}).", target=_tid(target),
         power=effect.power, toughness=effect.toughness)
    if target.effective_hp <= 0:
        _after_damage(st, target)


def _r_counters(st, item, effect, target, ctx):
    # Persistent +X/+X counters: permanent Power and max HP (not cleared at End).
    if hasattr(target, "power"):
        target.power += effect.power
    target.max_hp += effect.toughness
    target.hp += effect.toughness
    _log(st, "counters", f"{target.name} gains +{effect.power}/+{effect.toughness} "
         f"counters (HP {target.hp}/{target.max_hp}).", target=_tid(target))


def _r_prevent_only(st, item, effect, target, ctx):
    # R-11 prevent: tag the target to nullify the named thing for the duration.
    target.prevent_tags.append(effect.parameter)
    _log(st, "prevent", f"{target.name} will prevent {effect.parameter} this turn.",
         target=_tid(target), parameter=effect.parameter)


def _r_protection(st, item, effect, target, ctx):
    target.protection += 1
    _log(st, "protection", f"{target.name} gains protection ({effect.scope}).",
         target=_tid(target))


def _r_taunt(st, item, effect, target, ctx):
    # Force the targeted enemy to aim at the caster this turn — both its already
    # declared intent and the next one it declares.
    if isinstance(target, EnemyState):
        who = st.character(item.source_id)
        if who is not None and not _has_kw(who, "hexproof"):
            target.taunted_by = item.source_id
            if target.intent is not None:
                target.intent.target_id = item.source_id
            _log(st, "taunt", f"{target.name} is taunted into targeting {who.name}.",
                 enemy=target.id, by=item.source_id)


def _r_revive(st, item, effect, target, ctx):
    # Restore an incapacitated character to a fraction of max HP (R-11).
    if isinstance(target, CharacterState) and target.effective_hp <= 0:
        target.temp_mod = 0
        target.hp = max(1, int(target.max_hp * effect.to_fraction))
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
    return dur.value if dur is not None else "end_of_turn"


# --------------------------------------------------------------------------- #
# Damage / death / draw primitives
# --------------------------------------------------------------------------- #
def _prevent_match(tag: str, damage_kind: str) -> bool:
    """Does a `prevent [parameter]` tag nullify this incoming damage (R-11)?"""
    if tag in ("damage", "all"):
        return True
    if tag == "combat_damage":
        return damage_kind == "attack"
    return tag == damage_kind


def _deal_damage(st: GameState, target, amount: int, source: str = "", source_obj=None,
                 damage_kind: str = "spell") -> None:
    """Damage reduces `hp` directly (R-7). It is answered, in order, by: a matching
    `prevent` tag (nullifies it), `protection` (negates a whole spell/attack), then
    Parry's numeric reduction. Lethality is then checked on effective_hp. Source
    keywords (deathtouch/lifelink) and target indestructible apply here."""
    if target is None or amount <= 0:
        return

    # R-11 prevent: a matching nullifier cancels the hit outright and is consumed.
    for i, tag in enumerate(getattr(target, "prevent_tags", [])):
        if _prevent_match(tag, damage_kind):
            target.prevent_tags.pop(i)
            _log(st, "prevented", f"{source or 'the hit'} on {target.name} is prevented "
                 f"({tag}).", target=_tid(target), parameter=tag)
            return

    # Protection negates the next incoming spell/attack outright (GDD §7).
    if getattr(target, "protection", 0) > 0 and damage_kind in ("attack", "spell", "ability"):
        target.protection -= 1
        _log(st, "protected", f"{target.name}'s protection negates {source or 'the hit'}.",
             target=_tid(target))
        return

    # Parry / numeric prevention reduces the hit before it lands.
    reduced = min(target.prevent_pool, amount)
    target.prevent_pool -= reduced
    amount -= reduced
    if reduced:
        _log(st, "reduced", f"{reduced} damage to {target.name} reduced.",
             target=_tid(target), amount=reduced)
    if amount <= 0:
        return

    # A hit of ≥25% of max HP breaks concentration (the amount that lands, GDD §8).
    if (isinstance(target, CharacterState) and target.channels
            and amount >= _break_threshold(target)):
        _note_break(st, target, "hit")

    # Damage reduces hp directly (R-7). Player hp floors at 0; indestructible floors
    # at 1 (it can't be reduced below 1 HP *by damage*).
    floor = 1 if _has_kw(target, "indestructible") else 0
    dealt = target.hp - max(floor, target.hp - amount)
    target.hp = max(floor, target.hp - amount)
    _log(st, "damage", f"{target.name} takes {dealt} damage (HP {target.hp}, "
         f"eff {target.effective_hp}).", target=_tid(target), amount=dealt,
         hp=target.hp, source=source)

    # Lifelink: the source heals for the damage dealt. Deathtouch: any damage
    # executes a minion outright (GDD §7).
    if source_obj is not None and dealt > 0 and _has_kw(source_obj, "lifelink"):
        _heal(st, source_obj, dealt, reason="lifelink")
    if (source_obj is not None and dealt > 0 and _has_kw(source_obj, "deathtouch")
            and isinstance(target, EnemyState) and target.alive):
        _log(st, "deathtouch", f"{target.name} is executed by deathtouch.", target=target.id)
        target.hp = 0
        target.temp_mod = min(target.temp_mod, 0)
    _after_damage(st, target)


def _heal(st: GameState, target, amount: int, reason: str = "") -> None:
    """Restore HP. A heal fills an outstanding negative `temp_mod` (a wound) first,
    cancelling it toward 0, and only then restores `hp` (never above max) — R-7."""
    if amount <= 0 or target is None:
        return
    if target.temp_mod < 0:  # cancel the wound toward 0 first
        fill = min(-target.temp_mod, amount)
        target.temp_mod += fill
        amount -= fill
        if fill:
            _log(st, "wound_mend", f"{fill} healing to {target.name} closes a wound "
                 f"(temp_mod {target.temp_mod}).", target=_tid(target), amount=fill)
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    if target.hp != before or reason:
        _log(st, "heal", f"{target.name} heals {target.hp - before} (HP {target.hp}).",
             target=_tid(target), amount=target.hp - before, hp=target.hp, reason=reason)


def _after_damage(st: GameState, target) -> None:
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


def _check_end(st: GameState) -> None:
    if st.result is not None:
        return
    if not st.living_enemies():
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
    """The enemies `actor` may basic-attack, honouring its attack mode + rows."""
    return _reachable_targets(actor, st.living_enemies())


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
    the move must be made while legal cards remain)."""
    pc = st.pending_choice
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
    mode = actor.acted_mode
    vig = _has_kw(actor, "vigilance")  # lifts the attack-vs-cast restriction (GDD §7)
    # Attack (basic, once per round): locked out after a Cast unless vigilant.
    if not actor.used_attack and (mode is None or (vig and mode == "cast")):
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
    actions += _drop_actions(actor)
    actions.append(Action("end_turn", actor.id, label="End turn"))
    return actions


def _legal_react(st: GameState, actor: CharacterState) -> List[Action]:
    """An open reaction window: free instants, Mitigate (self / adjacent ally),
    voluntary drop, or pass."""
    actions: List[Action] = []
    for card in actor.hand:
        if card.timing == Timing.instant and _can_pay(actor, card):
            actions += _cast_actions(st, actor, card)
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
    """One cast Action per (mode × legal target). Modal cards offer one branch per
    mode (the option is chosen here, at cast); a counter offers one option per
    enemy action it could answer; other cards offer one option per legal target.
    The engine enumerates every choice — the UI never invents one."""
    out: List[Action] = []
    for mode_idx, effects, mlabel in _mode_specs(card):
        prefix = f"Cast {card.name}"
        if mlabel:
            prefix += f" — {mlabel}"
        # A card whose effects target independently (≥2 sites, e.g. Agony Warp)
        # offers one cast per COMBINATION of per-site targets. A counter or a
        # single-site card keeps one cast per primary target.
        sites = _target_sites(effects, card)
        if _counter_filter(effects) is None and len(sites) >= 2:
            per_site = [_side_options(st, side) for _key, side in sites]
            for combo in itertools.product(*per_site):
                tids = tuple(tid for tid, _ in combo)
                labels = ", ".join(tl for _, tl in combo)
                out.append(Action("cast", actor.id, card_id=card.id, target_id=tids[0],
                                  targets=tids, mode=mode_idx,
                                  label=prefix + f" on {labels}"))
        else:
            for tid, tlabel in _target_options_for(st, effects, card):
                label = prefix + (f" on {tlabel}" if tlabel else "")
                out.append(Action("cast", actor.id, card_id=card.id, target_id=tid,
                                  mode=mode_idx, label=label))
    return out


def _mode_specs(card: Card):
    """[(mode_index, effects, mode_label)] — one entry per modal mode, or a single
    (None, card.effects, "") for a non-modal card."""
    modal = next((e for e in card.effects if e.kind == "modal"), None)
    if modal is not None:
        return [(i, list(m.effects), m.label or f"Option {i + 1}")
                for i, m in enumerate(modal.modes)]
    return [(None, list(card.effects), "")]


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


def _side_options(st: GameState, side):
    """[(creature_id, label)] of the living creatures a target on `side` may pick."""
    if side == "enemy":
        return [(e.id, e.name) for e in st.living_enemies()]
    if side == "ally":
        return [(c.id, c.name) for c in (st.living_party() + st.living_tokens())]
    if side == "any":
        return [(c.id, c.name) for c in
                (st.living_enemies() + st.living_party() + st.living_tokens())]
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
    side = None
    for e in _iter_leaf(effects):
        desc = getattr(e, "target", None)
        if isinstance(desc, str):  # "$T1" slot ref — resolve its side from the card
            sd = card.targets.get(desc[1:]) if card is not None else None
            if sd is not None and getattr(sd, "targeted", False):
                side = sd.side.value if sd.side is not None else "any"
                break
            continue
        if desc is not None and getattr(desc, "targeted", False):
            side = desc.side.value
            break
    return _side_options(st, side)


def _target_sites(effects, card: Card):
    """Ordered independent target sites for a mode's TOP-LEVEL effects. Each
    top-level chosen+targeted direct descriptor is its own site (an independent
    target — e.g. Agony Warp's two wounds); each distinct slot ref is one shared
    site. conditional/modal/self/all/untargeted contribute none, so a conditional's
    nested effects reuse the primary (first) target. Returns [(key, side)] where
    key is ('slot', name) or ('eff', id(effect)). Used by enumeration AND
    resolution, so site order matches between them."""
    sites = []
    seen_slots = set()

    def add(desc, eff_key, forced=False):
        if isinstance(desc, str):  # "$T1" slot ref — one shared site per slot name
            name = desc[1:]
            if name in seen_slots:
                return
            seen_slots.add(name)
            sd = card.targets.get(name) if card is not None else None
            side = sd.side.value if sd is not None and sd.side is not None else "any"
            sites.append((("slot", name), side))
        elif desc is not None and (forced or (getattr(desc, "targeted", False)
                                   and getattr(desc, "mode", None) == TargetMode.chosen)):
            sites.append((eff_key, desc.side.value))

    for e in effects:
        if e.kind in ("conditional", "modal"):
            continue
        if e.kind == "fight":
            # Fight's two targets are always chosen (even authored inline). Force both
            # sites, keying `other` apart from the primary so each binds independently.
            add(getattr(e, "target", None), ("eff", id(e)), forced=True)
            add(getattr(e, "other", None), ("eff_other", id(e)), forced=True)
            continue
        add(getattr(e, "target", None), ("eff", id(e)))
    return sites


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
