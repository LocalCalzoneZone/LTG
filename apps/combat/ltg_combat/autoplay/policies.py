"""Autoplay policies (§D12-3.3) — fixed, versioned, scripted heuristics.

The policy interface is two methods:

    choose(state, legal_actions, rng) -> action
    spend_level_up(character, points) -> (character', spent)

Every policy is deterministic given its seed and carries a VERSION string
embedded in every report row: bump the version whenever a heuristic changes,
because the policies are the measuring stick — a moved stick invalidates every
delta read across it. Two policies and four spend plans are the whole launch
surface; resist adding cleverness (cleverness moves the stick).

Known limitation (§D12-7): the launch greedy policy does not sequence
amplify→spike combo lines, so combo-deck win rates read artificially low.
Acceptable for deltas; noted in every report footer.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from ltg_core.schema import (
    COST_HP_STEP,
    COST_MANA,
    COST_POWER,
    MAX_POWER_BOUGHT,
    iter_effects,
)

from ..state import Action, GameState


# --------------------------------------------------------------------------- #
# Shared reads (state-only; no engine internals)
# --------------------------------------------------------------------------- #
def _card_in_hand(state: GameState, actor_id: str, card_id: Optional[str]):
    char = state.character(actor_id)
    if char is None or card_id is None:
        return None
    return next((c for c in char.hand if c.id == card_id), None)


def _constant_damage(card) -> int:
    """The card's constant single-cast damage (int `deal_damage` amounts only;
    refs/X read 0 — the greedy bot undervalues them, deliberately)."""
    total = 0
    for e in iter_effects(card.effects):
        if getattr(e, "kind", None) == "deal_damage" and isinstance(
                getattr(e, "amount", None), int):
            total += e.amount
    return total


def _constant_heal(card) -> int:
    return sum(e.amount for e in iter_effects(card.effects)
               if getattr(e, "kind", None) == "heal"
               and isinstance(getattr(e, "amount", None), int))


def _has_kind(card, kind: str) -> bool:
    return any(getattr(e, "kind", None) == kind for e in iter_effects(card.effects))


def _stance_attack_downgrade(card, current_power: int) -> bool:
    """True when casting this stance would REPLACE the basic attack with a
    weaker swing — the bot must not lobotomise its own damage (a stance's
    reactive value is beyond the stick's vocabulary; convict, never acquit)."""
    for e in iter_effects(card.effects):
        if getattr(e, "kind", None) != "stance":
            continue
        repl = getattr(e, "attack", "unchanged")
        if isinstance(repl, str):
            return repl == "removed"
        dmg = sum(x.amount for x in getattr(repl, "effects", [])
                  if getattr(x, "kind", None) == "deal_damage"
                  and isinstance(getattr(x, "amount", None), int))
        return dmg < current_power
    return False


def _constant_pump_power(card) -> int:
    """Constant positive `pump` power (the pre-swing prime read)."""
    return sum(e.power for e in iter_effects(card.effects)
               if getattr(e, "kind", None) == "pump"
               and isinstance(getattr(e, "power", None), int) and e.power > 0)


# The utility mana-sink order (greedy-1.1.0 rule 9): the first castable kind
# wins. Fixed and dumb by design — an ordering, not an optimiser.
_SINK_ORDER = ("heal", "pump", "wound", "poison", "strip_intent", "draw",
               "scry", "counters", "grant_keyword", "prevent", "protection",
               "regen", "remove_keyword")


def _sink_rank(card) -> Optional[int]:
    kinds = {getattr(e, "kind", None) for e in iter_effects(card.effects)}
    for i, kind in enumerate(_SINK_ORDER):
        if kind in kinds:
            return i
    return None


def _cast_cost(card, x: int = 0) -> int:
    return card.cost.generic + sum(card.cost.colors.values()) + max(0, x)


def _break_threshold(enemy) -> int:
    return -(-enemy.max_hp // 4)  # ceil(max_hp / 4), GDD §8


def _incoming_damage(state: GameState, item) -> Tuple[Optional[str], int]:
    """(victim id, damage) an enemy stack item would land on a party member —
    the constant read only (the same approximation the enemy's own
    on_incoming_lethal uses)."""
    if item.source_side != "enemy" or item.target_id is None:
        return None, 0
    victim = state.character(item.target_id)
    if victim is None:
        return None, 0
    if item.attack_power is not None:
        src = state.enemy(item.source_id)
        bonus = src.power_bonus if src is not None else 0
        return victim.id, max(0, item.attack_power + bonus)
    total = sum(e.amount for e in item.effects
                if getattr(e, "kind", None) == "deal_damage"
                and isinstance(getattr(e, "amount", None), int))
    return victim.id, total


def _enemy_kill_order(state: GameState) -> List[str]:
    """The greedy bot's kill-priority mirror (§D12-3.3 rule 4): the race-marked
    target first, then healers/support, escalators, channelers, then lowest HP."""
    obj = state.objective

    def key(e):
        marked = (obj is not None and obj.kind == "race"
                  and obj.status == "active" and e.id == obj.target_id)
        kinds = {getattr(v, "kind", None)
                 for c in e.components for v in c.verbs}
        support = bool(kinds & {"heal", "counters", "create_token", "control"})
        return (0 if marked else 1,
                0 if support else 1,
                0 if e.channels else 1,
                e.effective_hp, e.name)

    return [e.id for e in sorted(state.living_enemies(), key=key)]


# --------------------------------------------------------------------------- #
# Level-up spend plans (§D12-3.3) — a matrix dimension, not a smart optimiser
# --------------------------------------------------------------------------- #
def _spend(char: Dict[str, Any], points: int, order: List[str]) -> Tuple[Dict[str, Any], int]:
    """Spend `points` on the character dict following `order` (a rotation of
    "hp" / "power" / "mana" purchases; "hp" also serves as the sink). Mirrors
    the §D10-3 price table; the caller has already bumped `level`."""
    out = dict(char)
    left = points
    level = int(out.get("level", 1))
    identity = list(out.get("colors", [])) or ["C"]
    progressed = True
    while progressed and left > 0:
        progressed = False
        for what in order:
            if what == "power" and left >= COST_POWER \
                    and int(out.get("power_bought", 0)) < MAX_POWER_BOUGHT * level:
                out["power_bought"] = int(out.get("power_bought", 0)) + 1
                left -= COST_POWER
                progressed = True
            elif what == "mana" and left >= COST_MANA:
                out["starting_mana"] = list(out.get("starting_mana", [])) + [identity[0]]
                left -= COST_MANA
                progressed = True
            elif what == "hp" and left >= COST_HP_STEP:
                out["hp"] = int(out["hp"]) + 2
                left -= COST_HP_STEP
                progressed = True
            if left <= 0:
                break
    return out, points - left


SPEND_PLANS = {
    "balanced": ["mana", "power", "hp"],
    "greedy-hp": ["hp"],
    "greedy-power": ["power", "hp"],
    "greedy-mana": ["mana", "hp"],
}


# --------------------------------------------------------------------------- #
# Policies
# --------------------------------------------------------------------------- #
class Policy:
    name = "policy"
    version = "policy-0"

    def __init__(self, spend_plan: str = "balanced") -> None:
        if spend_plan not in SPEND_PLANS:
            raise ValueError(f"unknown spend plan: {spend_plan}")
        self.spend_plan = spend_plan

    def choose(self, state: GameState, legal: List[Action],
               rng: random.Random) -> Action:
        raise NotImplementedError

    def spend_level_up(self, character: Dict[str, Any],
                       points: int) -> Tuple[Dict[str, Any], int]:
        return _spend(character, points, SPEND_PLANS[self.spend_plan])


class RandomPolicy(Policy):
    """Uniform over legal actions (seeded). The floor: an encounter random wins
    40% of on hard is broken. Also the soak fuzzer's driver (§D12-3.6)."""

    name = "random"
    version = "random-1.0.0"

    def choose(self, state: GameState, legal: List[Action],
               rng: random.Random) -> Action:
        return legal[rng.randrange(len(legal))]


class GreedyPolicy(Policy):
    """The fixed-priority heuristic — vocabulary-complete for SUPPORT as of 1.2.0.

    The 1.0.0 launch ladder only ever cast constant-damage spells and
    reactive saves; measured against a real deck it played 2 of 20 cards,
    which made per-cell outcomes deterministic and card probes meaningless
    for everything it never touched. 1.1.0 keeps the stick fixed, scripted
    and deterministic, but teaches it the rest of the §11 vocabulary:

      1. win now (attack / damage cast / destroy / damaging Skill)
      2. answer the window: save the doomed → kill the attacker (first
         strike) → counter a big enemy action or a channel start
      3. Ultimate on a full gauge · 3b. the Skill (damage at kill-order;
         a utility Skill fires on round 2)
      4. finish finishable enemies · 5. break channels (damage or removal)
      6. objective duty (survive → Defend; waves → mana discipline)
      7. start a channel early (round ≤ 3)
      8. prime the swing (an instant self-pump before an attack turn)
      9. the better proactive line: multi-cast damage vs the basic attack
     10. attack · 11. the utility mana sink (heal the wounded → wound →
         poison → draw → scry → permanent counters → regen) · 12. Defend.

    1.2.0 (the support pass, driven by a real bard kit the 1.1.x stick
    could not play): channels start on ANY turn while fewer than two are held;
    pumps and one-shot combo primers (amplify/double_next) fire on ALLIES
    ahead of the team's best unspent attack, not only on self; a downed ally
    is revived the moment a revive is castable; window saves trigger on big
    hits (>= 4), not only lethal ones; and the mana sink learns the rest of
    the support verbs (strip_intent, grant_keyword, prevent, protection,
    remove_keyword). Still deliberately blunt — no multi-turn setups, no
    interception, no lookahead. It is the measuring stick, not an opponent;
    bump the version whenever a rule changes."""

    name = "greedy"
    version = "greedy-1.2.0"

    # -- entry ---------------------------------------------------------------- #
    def choose(self, state: GameState, legal: List[Action],
               rng: random.Random) -> Action:
        by_kind: Dict[str, List[Action]] = {}
        for a in legal:
            by_kind.setdefault(a.kind, []).append(a)
        # Forced sub-decisions resolve deterministically: first offered option.
        for kind in ("choose_mana", "choose_card", "choose_scry",
                     "choose_target", "choose_mode"):
            if kind in by_kind:
                return by_kind[kind][0]
        if state.stack:
            return self._react(state, legal, by_kind)
        return self._main(state, legal, by_kind)

    # -- rule 2: the reaction window ------------------------------------------ #
    def _react(self, state: GameState, legal: List[Action],
               by_kind: Dict[str, List[Action]]) -> Action:
        # 2a. Answer incoming lethal: Mitigate, else a heal/prevent save.
        threats = {}
        for item in state.stack:
            vid, dmg = _incoming_damage(state, item)
            if vid is not None and dmg > 0:
                threats[vid] = threats.get(vid, 0) + dmg
        # Save the doomed first; failing that, shield a BIG hit (>= 4).
        doomed = [vid for vid, dmg in threats.items()
                  if (state.character(vid) is not None
                      and state.character(vid).effective_hp <= dmg)]
        big = [vid for vid, dmg in threats.items()
               if dmg >= 4 and vid not in doomed
               and state.character(vid) is not None]
        for victim in (sorted(doomed) + sorted(big))[:1] if (doomed or big) else []:
            for a in by_kind.get("mitigate", []):
                if a.target_id == victim:
                    return a
            for a in by_kind.get("stance_ability", []):
                if a.card_id == "mitigate" and a.target_id in (victim, None):
                    return a
            saves = []  # a heal/prevent aimed at the victim
            for a in by_kind.get("cast", []):
                card = _card_in_hand(state, a.actor_id, a.card_id)
                if card is None or a.target_id != victim:
                    continue
                if _constant_heal(card) > 0 or _has_kind(card, "prevent"):
                    saves.append((_cast_cost(card, a.x or 0), a.card_id, a))
            if saves:
                return sorted(saves, key=lambda s: s[:2])[0][2]
        top = state.stack[-1]
        if top.source_side == "enemy":
            # 2b. Kill the attacker first (the R-12 first-strike window).
            attacker = state.enemy(top.source_id)
            if attacker is not None:
                for a in by_kind.get("attack", []):
                    actor = state.character(a.actor_id)
                    if (a.target_id == attacker.id and actor is not None
                            and actor.current_power >= attacker.effective_hp):
                        return a
            # 2c. Counter a big enemy action or a channel being started.
            _, top_dmg = _incoming_damage(state, top)
            if top_dmg >= 3 or top.starts_channel:
                counters = []
                for a in by_kind.get("cast", []):
                    card = _card_in_hand(state, a.actor_id, a.card_id)
                    if (card is not None and _has_kind(card, "counter")
                            and a.target_id == f"#{top.uid}"):
                        counters.append((_cast_cost(card, a.x or 0),
                                         a.card_id, a))
                if counters:
                    return sorted(counters, key=lambda s: s[:2])[0][2]
        nxt = self._pass_like(by_kind)
        if nxt is not None:
            return nxt
        return legal[0]

    @staticmethod
    def _pass_like(by_kind: Dict[str, List[Action]]) -> Optional[Action]:
        for kind in ("pass", "end_turn"):
            if kind in by_kind:
                return by_kind[kind][0]
        return None

    # -- the main-phase ladder -------------------------------------------------- #
    def _main(self, state: GameState, legal: List[Action],
              by_kind: Dict[str, List[Action]]) -> Action:
        order = _enemy_kill_order(state)
        rank = {eid: i for i, eid in enumerate(order)}
        enemies = {e.id: e for e in state.living_enemies()}
        obj = state.objective
        actor = state.character(legal[0].actor_id) if legal else None
        pool_n = len(actor.pool) if actor is not None else 0

        def removable(eid):
            e = enemies.get(eid)
            return e is not None and (not e.is_boss or e.in_execute_window)

        def kills(eid: Optional[str], dmg: int) -> bool:
            e = enemies.get(eid)
            return e is not None and dmg > 0 and e.effective_hp <= dmg

        attack_dmg = {}
        for a in by_kind.get("attack", []):
            attack_dmg[a.target_id] = actor.current_power if actor else 0
        attack_best = max(attack_dmg.values()) if attack_dmg else 0
        # Stance-replaced main abilities (§D9-2.3) arrive as kind
        # "stance_ability" with card_id = the slot they replace. A held stance
        # must not silence the bot: the replaced Attack plays in the attack
        # slot, the replaced Defend in the defend slot.
        stance_by_slot: Dict[str, List[Action]] = {}
        for a in by_kind.get("stance_ability", []):
            stance_by_slot.setdefault(a.card_id or "", []).append(a)

        # Classify every offered cast once.
        party_ids = {c.id: c for c in state.living_party()}
        cast_dmg, destroys, bounces, channels, sinks = [], [], [], [], []
        pumps, revives = [], []
        for a in by_kind.get("cast", []):
            card = _card_in_hand(state, a.actor_id, a.card_id)
            if card is None:
                continue
            cost = _cast_cost(card, a.x or 0)
            timing = str(getattr(card.timing, "value", card.timing))
            dmg = _constant_damage(card)
            if dmg > 0 and a.target_id in enemies:
                cast_dmg.append((a, dmg, cost))
            if _has_kind(card, "destroy") and a.target_id in enemies:
                destroys.append((a, cost))
            if _has_kind(card, "bounce") and a.target_id in enemies:
                bounces.append((a, cost))
            # Pre-swing primes: instant pumps AND one-shot combo primers
            # (amplify/double_next), aimed at ANY party member with an unspent
            # attack — the support play the 1.1.x stick could not make.
            is_primer = _has_kind(card, "amplify") or _has_kind(card, "double_next")
            if (timing == "instant"
                    and (is_primer or _constant_pump_power(card) > 0)
                    and a.target_id in party_ids
                    and not party_ids[a.target_id].used_attack):
                pumps.append((a, cost,
                              -party_ids[a.target_id].current_power,
                              a.target_id != a.actor_id))
            if timing == "channeled":
                channels.append((a, cost))
            if _has_kind(card, "revive"):
                downed = any(not c.alive for c in state.party)
                if downed:
                    revives.append((a, cost))
            srank = _sink_rank(card)
            if srank is not None:
                sinks.append((a, card, srank, cost))

        # The multi-cast damage line: fill the pool with the most damage-
        # efficient DISTINCT cards and compare the total against one attack.
        per_card = {}
        for a, dmg, cost in cast_dmg:
            cur = per_card.get(a.card_id)
            cand = (dmg, cost, rank.get(a.target_id, 99), a)
            if cur is None or (cand[0], -cand[1], -cand[2]) > (cur[0], -cur[1], -cur[2]):
                per_card[a.card_id] = cand
        fill = sorted(per_card.values(),
                      key=lambda t: (-(t[0] / max(1, t[1])), t[1], t[3].card_id))
        line_total, budget, line_first = 0, pool_n, None
        for dmg, cost, _r, a in fill:
            if cost <= budget:
                budget -= cost
                line_total += dmg
                if line_first is None:
                    line_first = a

        # 1. Win now: lethal on the last enemy / complete the race target.
        last_ids = set()
        if len(enemies) == 1:
            last_ids = set(enemies)
        if obj is not None and obj.kind == "race" and obj.status == "active":
            last_ids.add(obj.target_id)
        finishers = []
        for eid in last_ids:
            if eid in attack_dmg and kills(eid, attack_dmg[eid]):
                finishers.append((0, rank.get(eid, 99),
                                  by_kind_attack(by_kind, eid)))
            for a, dmg, cost in cast_dmg:
                if a.target_id == eid and kills(eid, dmg):
                    finishers.append((1, rank.get(eid, 99), a))
            for a, cost in destroys:
                if a.target_id == eid and removable(eid):
                    finishers.append((2, rank.get(eid, 99), a))
        if finishers:
            return sorted(finishers, key=lambda f: f[:2])[0][2]

        # 2b. Stand a downed ally back up the moment it is possible.
        if revives:
            return sorted(revives, key=lambda t: (t[1], t[0].card_id or ""))[0][0]

        # 3. The Ultimate on a full gauge, when a target exists.
        ults = by_kind.get("use_ultimate", [])
        if ults and enemies:
            return sorted(ults, key=lambda a: rank.get(a.target_id, 99))[0]

        # 3b. The Skill: a damaging Skill fires at the kill-order target; a
        # utility Skill fires on round 2 (deterministically, first option).
        skills = by_kind.get("use_skill", [])
        if skills and actor is not None and actor.skill is not None:
            skill_dmg = _constant_damage(actor.skill)
            if skill_dmg > 0 and enemies:
                aimed = [a for a in skills if a.target_id in enemies]
                if aimed:
                    return sorted(aimed,
                                  key=lambda a: rank.get(a.target_id, 99))[0]
            elif (skill_dmg == 0 and state.turn >= 2
                  and not _stance_attack_downgrade(actor.skill,
                                                   actor.current_power)):
                return sorted(skills, key=lambda a: (a.target_id or "",
                                                     a.label))[0]

        # 4. Finish finishable enemies, kill-priority first (attack, then a
        # damage cast, then removal — destroy kills anything removable).
        finish = []
        for eid, dmg in attack_dmg.items():
            if kills(eid, dmg):
                finish.append((rank.get(eid, 99), 0, by_kind_attack(by_kind, eid)))
        for a, dmg, cost in cast_dmg:
            if kills(a.target_id, dmg):
                finish.append((rank.get(a.target_id, 99), 1, a))
        for a, cost in destroys:
            if removable(a.target_id):
                finish.append((rank.get(a.target_id, 99), 2, a))
        if finish:
            return sorted(finish, key=lambda f: f[:2])[0][2]

        # 5. Break breakable enemy channels: one hit >= 25% max HP, or remove
        # the channeler outright (destroy / bounce both end concentration).
        breaks = []
        for eid, dmg in attack_dmg.items():
            e = enemies.get(eid)
            if e is not None and e.channels and dmg >= _break_threshold(e):
                breaks.append((rank.get(eid, 99), 0, by_kind_attack(by_kind, eid)))
        for a, dmg, cost in cast_dmg:
            e = enemies.get(a.target_id)
            if e is not None and e.channels and dmg >= _break_threshold(e):
                breaks.append((rank.get(a.target_id, 99), 1, a))
        for a, cost in destroys + bounces:
            e = enemies.get(a.target_id)
            if e is not None and e.channels and removable(a.target_id):
                breaks.append((rank.get(a.target_id, 99), 2, a))
        if breaks:
            return sorted(breaks, key=lambda b: b[:2])[0][2]

        # 6. Objective duty: survive -> Defend bias; waves -> mana discipline
        # between waves (hold spells while the field is empty).
        if obj is not None and obj.kind == "survive" and "defend" in by_kind:
            return by_kind["defend"][0]
        if obj is not None and obj.kind == "waves" and not enemies:
            nxt = self._pass_like(by_kind)
            if nxt is not None:
                return nxt

        # 7. Start a channel whenever affordable, holding at most two —
        # a support kit IS its held auras; three-plus locks out the mana base.
        if channels and actor is not None and len(actor.channels) < 2:
            return sorted(channels, key=lambda t: (t[1], t[0].card_id or ""))[0][0]

        # 8. Prime the swing: an instant pump/combo-primer onto the
        # strongest party member whose attack is still unspent (self included),
        # ahead of an attack-shaped turn.
        if pumps and enemies and (attack_dmg or any(not t[3] for t in pumps)):
            return sorted(pumps, key=lambda t: (t[2], t[1],
                                                t[0].card_id or ""))[0][0]

        # 9/10. The better proactive line: the multi-cast damage line when it
        # out-damages the basic attack; otherwise attack (kill-priority).
        if line_first is not None and line_total > attack_best:
            return line_first
        if attack_dmg:
            eid = sorted(attack_dmg, key=lambda i: rank.get(i, 99))[0]
            return by_kind_attack(by_kind, eid)
        if enemies and stance_by_slot.get("attack"):
            return sorted(stance_by_slot["attack"],
                          key=lambda a: (rank.get(a.target_id, 99),
                                         a.target_id or "", a.label))[0]
        if line_first is not None:
            return line_first

        # 11. The utility mana sink, in fixed order (heal the wounded first).
        sink_cands = []
        for a, card, srank, cost in sinks:
            kind = _SINK_ORDER[srank]
            tgt = state.combatant(a.target_id) if a.target_id else None
            if kind == "heal":
                if tgt is None or getattr(tgt, "hp", 0) >= getattr(tgt, "max_hp", 0):
                    continue  # no overhealing
                if a.target_id in enemies:
                    continue
            if kind in ("wound", "poison") and a.target_id not in enemies:
                continue
            order_key = rank.get(a.target_id, 99) if kind in ("wound", "poison") \
                else (0 if a.target_id == a.actor_id else 1)
            sink_cands.append((srank, order_key, cost, a.card_id or "", a))
        if sink_cands:
            return sorted(sink_cands, key=lambda s: s[:4])[0][4]

        # 12. Defend (the stance-replaced form included), else yield the turn.
        if "defend" in by_kind:
            return by_kind["defend"][0]
        if stance_by_slot.get("defend"):
            return sorted(stance_by_slot["defend"],
                          key=lambda a: (a.target_id or "", a.label))[0]
        nxt = self._pass_like(by_kind)
        if nxt is not None:
            return nxt
        return legal[0]


def by_kind_attack(by_kind: Dict[str, List[Action]], target_id: str) -> Action:
    return next(a for a in by_kind["attack"] if a.target_id == target_id)


def make_policy(name: str, spend_plan: str = "balanced") -> Policy:
    policies = {"random": RandomPolicy, "greedy": GreedyPolicy}
    if name not in policies:
        raise ValueError(f"unknown policy: {name} (have: {', '.join(policies)})")
    return policies[name](spend_plan)
