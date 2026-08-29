"""The autoplay runner (§D12-3.4) — deterministic fights, measured.

``run_one(spec, policy, seed)`` plays one composed encounter spec to completion
through only ``legal_actions`` / ``apply_action`` and returns a plain-dict
RunRecord. The invariant: identical ``(spec, policy version, seed)`` yields an
identical record — asserted by a test that runs the same fight twice. Every
record carries the full repro key ``(spec hash, policy version, seed)``:
because the engine is deterministic, the repro IS the key.

A round cap of 50 (T-71) flags non-terminating fights as anomalies rather than
hanging; an action cap backstops pathological in-turn loops the same way.

``run_adventure`` replicates the game server's phase carry-over and level-up
rules (§D10-2/3) locally — the session layer is not imported. The magnitudes
mirror the Rebalance Register: T-57 (30 points per level), T-58 (gauge carries
at 50%, floored), T-59 (phase-start HP floor at 25% of max).
"""

from __future__ import annotations

import copy
import hashlib
import re
import json
import random
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from ltg_core.schema import Character, PHASE_GRANTS, level_for_points

from ..engine import apply_action, legal_actions
from ..scenario import compose_spec, scale_encounter, state_from_dict
from ..state import GameState
from .policies import Policy

ROUND_CAP = 50        # T-71: rounds before a fight is flagged non-terminating
ACTION_CAP = 20000    # backstop for in-turn loops (same anomaly treatment)

# T-58 / T-59 (§D10-2), replicated from the session layer by design.
GAUGE_CARRY = 0.5
HP_FLOOR_PCT = 25

# The balance register (T-64 Power, §D18-2 abilities + enrage), replicated from
# the game server's content layer (ltg_combat must not depend on it). Keep in
# sync with ltg_game_server.content.ENEMY_POWER_BONUS / BOSS_POWER_BONUS /
# ENEMY_ABILITY_BONUS / BOSS_ABILITY_BONUS / ROW_ABILITY_BONUS / enrage_scale;
# --raw-power disables the whole register, which is exactly the retroactive
# before/after diff.
ENEMY_POWER_BONUS = 2
BOSS_POWER_BONUS = 4
ENEMY_ABILITY_BONUS = 2
BOSS_ABILITY_BONUS = 4
ROW_ABILITY_BONUS = 2
_HOSTILE_DAMAGE_VERBS = ("deal_damage", "lose_life")

# Difficulty at RUN time: content is treated as authored at "standard", so
# "standard" is the identity and the other difficulties apply the generation
# HP-multiplier RATIO (mirrors ltg_game_server.llm.ENEMY_HP_MULT).
ENEMY_HP_MULT = {"easy": 1.0, "standard": 1.2, "hard": 1.5}


def spec_hash(spec: Dict[str, Any]) -> str:
    """A stable short hash of the composed spec — one third of the repro key."""
    blob = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _policy_rng(h: str, policy: Policy, seed: int) -> random.Random:
    # String seeding is stable across processes and runs (no PYTHONHASHSEED).
    return random.Random(f"{h}:{policy.version}:{seed}")


# --------------------------------------------------------------------------- #
# Content preparation (the same shaping the server's build path applies)
# --------------------------------------------------------------------------- #
def _scale_difficulty(scenario: Dict[str, Any], difficulty: str) -> None:
    """Enemy/token HP × the difficulty ratio, in place ("standard" = identity)."""
    mult = ENEMY_HP_MULT.get(difficulty, 1.2) / ENEMY_HP_MULT["standard"]
    if abs(mult - 1.0) < 1e-9:
        return

    def bump(v: Any) -> Any:
        try:
            return max(1, ceil(int(v) * mult))
        except (TypeError, ValueError):
            return v

    for e in scenario.get("enemies", []):
        if isinstance(e, dict) and "hp" in e:
            e["hp"] = bump(e["hp"])
    for t in (scenario.get("tokens") or {}).values():
        if isinstance(t, dict) and "hp" in t:
            t["hp"] = bump(t["hp"])


def _retell_numbers(comp, swaps, pt_swaps=()):
    """Mirror of ltg_game_server.content._retell_numbers (§D18-2): the telegraph
    tells the lifted numbers, so the Tester's transcripts read like live play."""
    text = str(comp.get("telegraph") or "")
    if not text:
        return
    for (op, ot), (np_, nt) in pt_swaps:
        text = re.sub(rf"\+{op}/\+{ot}\b", f"+{np_}/+{nt}", text)
    untouched = {v["amount"] for v in comp.get("verbs") or []
                 if isinstance(v, dict) and isinstance(v.get("amount"), int)
                 and v.get("kind") not in _HOSTILE_DAMAGE_VERBS}
    for old, new in swaps:
        if old == new:
            continue
        if old in untouched:
            # Ambiguous within this component (the same number sits on a heal /
            # stun the register left alone) — swap only where the prose marks it
            # as the damage: "deal(s) 4", "4 damage", "for 4".
            text = re.sub(rf"((?:\bdeals?|\bfor)\s+){old}\b", rf"\g<1>{new}", text)
            text = re.sub(rf"\b{old}(\s+damage\b)", rf"{new}\g<1>", text)
            continue
        text = re.sub(rf"\b{old}\b", str(new), text)
    comp["telegraph"] = text


def _hostile_target(verb: Dict[str, Any]) -> bool:
    """Enemy authoring frame: side "ally" is the party."""
    t = verb.get("target")
    return isinstance(t, dict) and t.get("side") in ("ally", "any")


def _row_shaped(verb: Dict[str, Any]) -> bool:
    t = verb.get("target")
    return isinstance(t, dict) and bool(t.get("rows") or t.get("scope") in ("row", "blast"))


def enrage_scale(party_size: int) -> "tuple[float, float]":
    """§D18-2 (lethality, padding) — see ltg_game_server.content.enrage_scale."""
    n = max(1, int(party_size))
    return float(n), 1.0 + (n - 1) / 2.0


def _bump_enemy_power(scenario: Dict[str, Any], party_size: int = 1) -> None:
    """The balance register in place: +2 Power every enemy, +4 a boss (chassis
    Power and attack-type intent template amounts), the same bump on hostile
    component damage (+ROW_ABILITY_BONUS on a dodgeable row/blast shape), and a
    boss's Enrage scaled by party size (§D18-2)."""
    lethal, pad = enrage_scale(party_size)
    for e in scenario.get("enemies", []):
        if not isinstance(e, dict):
            continue
        boss = bool(e.get("is_boss"))
        bump = BOSS_POWER_BONUS if boss else ENEMY_POWER_BONUS
        ability = BOSS_ABILITY_BONUS if boss else ENEMY_ABILITY_BONUS
        base = e.get("power", e.get("intent", {}).get("amount", 0))
        try:
            e["power"] = int(base) + bump
        except (TypeError, ValueError):
            e["power"] = bump
        for key in ("intent", "ranged_intent"):
            tmpl = e.get(key)
            if (isinstance(tmpl, dict) and isinstance(tmpl.get("amount"), int)
                    and tmpl.get("intent_type", "attack") == "attack"):
                tmpl["amount"] += bump
        for comp in e.get("components") or []:
            if not isinstance(comp, dict):
                continue
            if comp.get("archetype") == "Enrage":
                swaps, pt_swaps = [], []
                for verb in comp.get("verbs") or []:
                    if not isinstance(verb, dict):
                        continue
                    kind = verb.get("kind")
                    if kind in ("counters", "pump"):
                        op, ot = verb.get("power"), verb.get("toughness")
                        for field, factor in (("power", lethal), ("toughness", pad),
                                              ("hp", pad)):
                            if isinstance(verb.get(field), int):
                                verb[field] = ceil(verb[field] * factor)
                        if isinstance(op, int) and isinstance(ot, int):
                            pt_swaps.append(((op, ot), (verb["power"], verb["toughness"])))
                    elif kind in ("deal_damage", "lose_life", "heal"):
                        if isinstance(verb.get("amount"), int):
                            swaps.append((verb["amount"], ceil(verb["amount"] * pad)))
                            verb["amount"] = ceil(verb["amount"] * pad)
                    elif kind == "create_token" and isinstance(verb.get("count"), int):
                        verb["count"] += max(0, int(party_size) - 1)
                _retell_numbers(comp, swaps, pt_swaps)
                continue
            row_comp = bool(comp.get("target_row"))
            swaps = []
            for verb in comp.get("verbs") or []:
                if (not isinstance(verb, dict)
                        or verb.get("kind") not in _HOSTILE_DAMAGE_VERBS
                        or not isinstance(verb.get("amount"), int)):
                    continue
                if not (_hostile_target(verb) or row_comp):
                    continue
                extra = ROW_ABILITY_BONUS if (row_comp or _row_shaped(verb)) else 0
                swaps.append((verb["amount"], verb["amount"] + ability + extra))
                verb["amount"] += ability + extra
            _retell_numbers(comp, swaps)


def prepare_scenario(content: Dict[str, Any], party_size: int,
                     difficulty: str = "standard",
                     power_bump: bool = True) -> Dict[str, Any]:
    """One phase/encounter shaped exactly as the server's build path shapes it:
    difficulty HP ratio → per-size layout resolution (objectives included) →
    the T-64 Power bump."""
    scenario = copy.deepcopy(content)
    _scale_difficulty(scenario, difficulty)
    scenario = scale_encounter(scenario, party_size)
    if power_bump:
        _bump_enemy_power(scenario, party_size)
    return scenario


# --------------------------------------------------------------------------- #
# The drive loop
# --------------------------------------------------------------------------- #

# Decision points that carry player agency — castability is tallied only here,
# never inside forced sub-decision windows (choose_target and friends), where
# an untallied hand would read as "unaffordable".
_AGENCY_KINDS = frozenset({"cast", "attack", "defend", "end_turn", "delay", "pass",
                           "mitigate", "use_skill", "use_ultimate",
                           "stance_ability", "drop_channels", "move"})


def _tally_decision(telemetry: Dict[str, Any], st: GameState,
                    phases: List[Any]) -> None:
    """Per agency decision: for every card in the actor's hand, was a cast of
    it OFFERED (affordable + legal) right now? The castability autopsy (§D13)
    divides dead cards into never-castable vs castable-but-declined on this."""
    kinds = {a.kind for a in phases}
    if not (kinds & _AGENCY_KINDS) or any(k.startswith("choose_") for k in kinds):
        return
    actor_id = phases[0].actor_id
    char = st.character(actor_id)
    if char is None:
        return
    slot = telemetry.setdefault(actor_id, {"rules": {}, "cards": {}})
    offered = {a.card_id for a in phases if a.kind == "cast"}
    for card in char.hand:
        c = slot["cards"].setdefault(card.id, {"hand": 0, "offered": 0,
                                               "cast_rules": {}})
        c["hand"] += 1
        if card.id in offered:
            c["offered"] += 1


def _tally_choice(telemetry: Dict[str, Any], act: Any,
                  rule: Optional[str]) -> None:
    """After the policy chooses: attribute the decision (and a cast's card) to
    the ladder rule that made it (Policy.last_rule)."""
    if rule is None:
        return
    slot = telemetry.setdefault(act.actor_id, {"rules": {}, "cards": {}})
    slot["rules"][rule] = slot["rules"].get(rule, 0) + 1
    if act.kind == "cast" and act.card_id:
        c = slot["cards"].setdefault(act.card_id, {"hand": 0, "offered": 0,
                                                   "cast_rules": {}})
        c["cast_rules"][rule] = c["cast_rules"].get(rule, 0) + 1


def _drive(st: GameState, policy: Policy, rng: random.Random,
           round_cap: int, telemetry: Optional[Dict[str, Any]] = None
           ) -> Tuple[GameState, Optional[str]]:
    """Play to completion. Returns (final state, anomaly or None). `telemetry`
    (when given) receives per-decision castability and rule-attribution
    tallies — collection is read-only and never influences play."""
    actions = 0
    while st.result is None:
        if st.turn > round_cap:
            return st, "round_cap"
        phases = legal_actions(st)
        if not phases:
            return st, "no_actions"
        if telemetry is not None:
            _tally_decision(telemetry, st, phases)
        act = policy.choose(st, phases, rng)
        if telemetry is not None:
            _tally_choice(telemetry, act, getattr(policy, "last_rule", None))
        st, _ = apply_action(st, act)
        actions += 1
        if actions >= ACTION_CAP:
            return st, "action_cap"
    return st, None


# --------------------------------------------------------------------------- #
# Metrics (§D12-3.4) — read from the structured event log + the end state
# --------------------------------------------------------------------------- #
def _cost_of(card_dict: Dict[str, Any]) -> int:
    cost = card_dict.get("cost") or {}
    return int(cost.get("generic", 0) or 0) + sum(
        int(v) for v in (cost.get("colors") or {}).values())


def _card_costs(spec: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for p in spec.get("party", []):
        costs = {c["id"]: _cost_of(c) for c in p.get("library", [])}
        if p.get("skill"):
            costs[p["skill"]["id"]] = _cost_of(p["skill"])
        out[p["id"]] = costs
    return out


def _zero_char() -> Dict[str, Any]:
    return {"damage_dealt": 0, "damage_taken": 0, "healing_done": 0,
            "healing_received": 0, "cards_cast": 0, "mana_granted": 0,
            "mana_spent": 0, "mana_wasted": 0, "gauge_full_round": None,
            "ultimate_round": None, "channels_started": 0,
            "channels_ended": 0, "dead_in_hand": 0,
            # Per-card {card_id: [times_drawn, times_cast]} — the Tester's
            # cast-vs-held screening reads this (§D13-1.2).
            "card_events": {},
            # Per-card count of `condition_false` resolutions — casts whose
            # conditional skipped (the cast-into-a-whiff read).
            "condition_whiffs": {},
            # Per-card channel economy: starts / triggers fired / turns held /
            # reserved mana × turns held / voluntary drops.
            "channel_stats": {},
            # Filled from drive telemetry (when the runner collects it):
            # decision counts per policy ladder rule, and per-card castability
            # {card_id: {hand, offered, cast_rules}}.
            "decision_rules": {},
            "card_flow": {}}


def _zero_channel() -> Dict[str, int]:
    return {"starts": 0, "triggers": 0, "turns_held": 0,
            "reserved_manaturns": 0, "drops": 0}


def _collect_metrics(st: GameState, spec: Dict[str, Any],
                     opening_hands: Optional[Dict[str, List[str]]] = None
                     ) -> Dict[str, Any]:
    chars: Dict[str, Dict[str, Any]] = {c.id: _zero_char() for c in st.party}
    # Opening hands are dealt silently at setup (no draw events) — fold them
    # into the per-card "drawn" tally so cast-vs-held reads see every card.
    for cid, card_ids in (opening_hands or {}).items():
        if cid in chars:
            for card_id in card_ids:
                chars[cid]["card_events"].setdefault(card_id, [0, 0])[0] += 1
    enemies: Dict[str, Dict[str, Any]] = {}
    costs = _card_costs(spec)
    enemy_channels_broken = 0
    # (character, card) → (start turn, reserved mana) for channels still held —
    # closed out at fight end so turns-held includes the final hold.
    open_channels: Dict[Tuple[str, str], Tuple[int, int]] = {}
    turn = 1
    for ev in st.log:
        d = ev.data
        if ev.type == "turn_start":
            turn = int(d.get("turn", turn))
        elif ev.type == "damage":
            amt = int(d.get("amount", 0) or 0)
            src = d.get("source_id")
            if src in chars:
                chars[src]["damage_dealt"] += amt
            if d.get("target") in chars:
                chars[d["target"]]["damage_taken"] += amt
        elif ev.type in ("heal", "wound_mend"):
            amt = int(d.get("amount", 0) or 0)
            if d.get("source_id") in chars:
                chars[d["source_id"]]["healing_done"] += amt
            if d.get("target") in chars:
                chars[d["target"]]["healing_received"] += amt
        elif ev.type in ("cast", "skill"):
            cid = d.get("character")
            if cid in chars:
                chars[cid]["cards_cast"] += 1
                chars[cid]["mana_spent"] += costs.get(cid, {}).get(d.get("card"), 0)
                if d.get("card"):
                    ev_counts = chars[cid]["card_events"].setdefault(
                        d["card"], [0, 0])
                    ev_counts[1] += 1
        elif ev.type == "draw":
            cid = d.get("character")
            if cid in chars and d.get("card"):
                chars[cid]["card_events"].setdefault(d["card"], [0, 0])[0] += 1
        elif ev.type == "mana_refresh":
            cid = d.get("character")
            if cid in chars:
                chars[cid]["mana_granted"] += len(d.get("pool", []))
        elif ev.type == "gauge_full":
            cid = d.get("character")
            if cid in chars and chars[cid]["gauge_full_round"] is None:
                chars[cid]["gauge_full_round"] = turn
        elif ev.type == "ultimate":
            cid = d.get("character")
            if cid in chars and chars[cid]["ultimate_round"] is None:
                chars[cid]["ultimate_round"] = turn
        elif ev.type == "channel_start":
            cid = d.get("character")
            if cid in chars:
                chars[cid]["channels_started"] += 1
                if d.get("card"):
                    cs = chars[cid]["channel_stats"].setdefault(
                        d["card"], _zero_channel())
                    cs["starts"] += 1
                    open_channels[(cid, d["card"])] = (
                        turn, len(d.get("reserved") or []))
        elif ev.type == "channel_trigger":
            cid = d.get("source")
            if cid in chars and d.get("card"):
                cs = chars[cid]["channel_stats"].setdefault(
                    d["card"], _zero_channel())
                cs["triggers"] += 1
        elif ev.type == "channel_end":
            cid = d.get("character")
            if cid in chars:
                chars[cid]["channels_ended"] += 1
                if d.get("card"):
                    cs = chars[cid]["channel_stats"].setdefault(
                        d["card"], _zero_channel())
                    started, reserved = open_channels.pop(
                        (cid, d["card"]), (turn, 0))
                    held = max(0, turn - started)
                    cs["turns_held"] += held
                    cs["reserved_manaturns"] += reserved * max(1, held)
                    if d.get("reason") == "voluntary":
                        cs["drops"] += 1
            elif d.get("enemy"):
                enemy_channels_broken += 1
        elif ev.type == "condition_false":
            cid = d.get("source")
            if cid in chars and d.get("card"):
                w = chars[cid]["condition_whiffs"]
                w[d["card"]] = w.get(d["card"], 0) + 1
        elif ev.type == "enemy_died":
            eid = d.get("enemy")
            if eid:
                enemies.setdefault(eid, {})["died_round"] = turn
    # Channels still held when the fight ended: count the hold to the end.
    for (cid, card_id), (started, reserved) in open_channels.items():
        cs = chars[cid]["channel_stats"].setdefault(card_id, _zero_channel())
        held = max(0, st.turn - started)
        cs["turns_held"] += held
        cs["reserved_manaturns"] += reserved * max(1, held)
    for c in st.party:
        m = chars[c.id]
        m["dead_in_hand"] = len(c.hand) + len(c.library)
        m["mana_wasted"] = max(0, m["mana_granted"] - m["mana_spent"])
        m["end_hp"] = c.hp
        m["alive"] = c.alive
        # Gauge-rework tuning telemetry: raw pre-clamp income, the level-scaled
        # cost, and income per turn — the archetype charge-rate comparison feed.
        m["gauge_earned"] = c.gauge_earned
        m["gauge_cost"] = c.ultimate_charge_cost
        m["gauge_per_turn"] = round(c.gauge_earned / max(1, st.turn), 2)
    for e in st.enemies:
        enemies.setdefault(e.id, {}).setdefault("died_round", None)
    objective = None
    if st.objective is not None:
        obj = st.objective
        objective = {
            "kind": obj.kind, "status": obj.status,
            "rounds_done": obj.rounds_done, "turns": obj.turns,
            # Rounds to spare (positive) or short (the clock ran out at 0).
            "margin": (obj.turns - obj.rounds_done)
            if obj.kind in ("survive", "race") else None,
            "waves_deployed": obj.wave_index + 1 if obj.kind == "waves" else None,
        }
    return {"characters": chars, "enemies": enemies, "objective": objective,
            "enemy_channels_broken": enemy_channels_broken}


# --------------------------------------------------------------------------- #
# run_one — a single encounter
# --------------------------------------------------------------------------- #
def run_one(spec: Dict[str, Any], policy: Policy, seed: int,
            difficulty: str = "standard", label: str = "",
            party_label: str = "", round_cap: int = ROUND_CAP) -> Dict[str, Any]:
    """Play one COMPOSED spec (party + enemies, already scaled/bumped) to
    completion. Returns the JSONL-ready RunRecord dict."""
    h = spec_hash(spec)
    rng = _policy_rng(h, policy, seed)
    st = state_from_dict(spec, seed=seed)
    opening = {c.id: [card.id for card in c.hand] for c in st.party}
    telemetry: Dict[str, Any] = {}
    st, anomaly = _drive(st, policy, rng, round_cap, telemetry)
    record = {
        "kind": "encounter",
        "content": label or spec.get("name", ""),
        "party": party_label or "+".join(p["id"] for p in spec.get("party", [])),
        "size": len(spec.get("party", [])),
        "difficulty": difficulty,
        "policy": policy.name,
        "policy_version": policy.version,
        "spend_plan": policy.spend_plan,
        "seed": seed,
        "spec_hash": h,
        "result": st.result or "anomaly",
        "anomaly": anomaly,
        "rounds": st.turn,
    }
    record.update(_collect_metrics(st, spec, opening))
    _merge_telemetry(record["characters"], telemetry)
    return record


def _merge_telemetry(chars: Dict[str, Dict[str, Any]],
                     telemetry: Dict[str, Any]) -> None:
    for cid, t in telemetry.items():
        if cid in chars:
            chars[cid]["decision_rules"] = t["rules"]
            chars[cid]["card_flow"] = t["cards"]


# --------------------------------------------------------------------------- #
# run_adventure — the three-phase run, session rules replicated (§D10-2/3)
# --------------------------------------------------------------------------- #
def _carry_snapshot(st: GameState) -> Dict[str, Dict[str, Any]]:
    out = {}
    for c in st.party:
        cards = (list(c.hand) + list(c.library) + list(c.graveyard)
                 + [ch.card for ch in c.channels])
        out[c.id] = {"hp": c.hp, "cards": copy.deepcopy(cards),
                     "exile": copy.deepcopy(c.exile), "gauge": c.ultimate_gauge}
    return out


def _apply_carry(st: GameState, carry: Dict[str, Dict[str, Any]],
                 heals: Dict[str, int], rng: random.Random) -> None:
    for c in st.party:
        cy = carry.get(c.id)
        if cy is None:
            continue
        floor = -(-c.max_hp * HP_FLOOR_PCT // 100)  # ceil (T-59)
        c.hp = min(c.max_hp, max(cy["hp"] + heals.get(c.id, 0), floor))
        cards = list(cy["cards"])
        rng.shuffle(cards)
        c.hand = cards[:c.hand_size]
        c.library = cards[c.hand_size:]
        c.graveyard = []
        c.exile = list(cy["exile"])
        c.ultimate_gauge = int(cy["gauge"] * GAUGE_CARRY)  # floored (T-58)


def run_adventure(adventure: Dict[str, Any], loadouts: List[Dict[str, Any]],
                  policy: Policy, seed: int, difficulty: str = "standard",
                  power_bump: bool = True, label: str = "",
                  round_cap: int = ROUND_CAP) -> Dict[str, Any]:
    """Play an adventure (a dict with inline ``phases``: complete encounter
    objects) through the §D10-2/3 boundary rules: full-pool shuffle-up + fresh
    hand, HP floor, 50% gauge carry, and a 30-point level-up spent by the
    policy's spend plan. Returns one RunRecord with per-phase snapshots."""
    phases = adventure.get("phases") or adventure.get("acts") or []  # "acts": pre-17 alias
    if not phases:
        raise ValueError("adventure has no phases")
    loadouts = copy.deepcopy(loadouts)
    h = spec_hash({"adventure": adventure, "party": [
        lo.get("character", {}).get("name", "") for lo in loadouts]})
    rng = _policy_rng(h, policy, seed)
    banked: Dict[str, int] = {}
    carry: Optional[Dict[str, Dict[str, Any]]] = None
    heals: Dict[str, int] = {}
    phase_records: List[Dict[str, Any]] = []
    result, anomaly, rounds_total = None, None, 0
    party_label = ""

    for i, phase in enumerate(phases):
        scenario = prepare_scenario(phase, len(loadouts), difficulty, power_bump)
        spec = compose_spec(loadouts, scenario)
        party_label = "+".join(p["id"] for p in spec["party"])
        st = state_from_dict(spec, seed=seed * 1000003 + i)
        if carry is not None:
            _apply_carry(st, carry, heals,
                         random.Random(f"{h}:{seed}:carry:{i}"))
        entering = {c.id: c.hp for c in st.party}
        telemetry: Dict[str, Any] = {}
        st, phase_anomaly = _drive(st, policy, rng, round_cap, telemetry)
        rec = {"phase": i + 1, "name": phase.get("name", f"Phase {i + 1}"),
               "result": st.result or "anomaly", "anomaly": phase_anomaly,
               "rounds": st.turn, "entering_hp": entering,
               "spend_plan": policy.spend_plan,
               "banked": dict(banked)}
        rec.update(_collect_metrics(st, spec))
        _merge_telemetry(rec["characters"], telemetry)
        phase_records.append(rec)
        rounds_total += st.turn
        if phase_anomaly is not None:
            result, anomaly = "anomaly", phase_anomaly
            break
        if st.result != "victory":
            result = st.result
            break
        if i == len(phases) - 1:
            result = "victory"
            break

        # The phase boundary (§D10-3): level up through the policy's spend plan.
        carry = _carry_snapshot(st)
        heals = {}
        live_ids = [c.id for c in st.party]
        for slot, lo in enumerate(loadouts):
            live_id = live_ids[slot] if slot < len(live_ids) else None
            old = dict(lo.get("character", {}))
            # Level is derived from cumulative earned points (Update 17 T-78);
            # the phase just won pays its grant (+10 / +20 / +30, §D17-2.3), so
            # a lone adventure still walks 1 → 2 → 3.
            grant = PHASE_GRANTS[i] if i < len(PHASE_GRANTS) else PHASE_GRANTS[-1]
            earned = int(old.get("earned_points", 0)) + grant
            spent_before = int(old.get("spent_points", 0))
            available = banked.get(live_id, 0) + grant
            # The level follows the points SPENT (§D17-2.3); the policy buys
            # against the highest level the pool could reach (its Power cap),
            # and the build is then held to the level it actually bought.
            ceiling = level_for_points(spent_before + available)
            candidate = {**old, "level": ceiling, "earned_points": earned,
                         "spent_points": spent_before}
            new_char, spent = policy.spend_level_up(candidate, available)
            new_char = {**new_char, "level": level_for_points(spent_before + spent),
                        "spent_points": spent_before + spent}
            try:
                Character.model_validate(new_char)
            except Exception:
                # An invalid spend keeps the entering build; the points bank
                # instead — the run keeps its determinism.
                new_char, spent = {**candidate, "level": level_for_points(spent_before)}, 0
                try:
                    Character.model_validate(new_char)
                except Exception:
                    new_char = old
            lo["character"] = new_char
            if live_id is not None:
                banked[live_id] = available - spent
                heals[live_id] = int(new_char.get("hp", old.get("hp", 0))) \
                    - int(old.get("hp", 0))

    return {
        "kind": "adventure",
        "content": label or adventure.get("name", "adventure"),
        "party": party_label,
        "size": len(loadouts),
        "difficulty": difficulty,
        "policy": policy.name,
        "policy_version": policy.version,
        "spend_plan": policy.spend_plan,
        "seed": seed,
        "spec_hash": h,
        "result": result or "anomaly",
        "anomaly": anomaly,
        "rounds": rounds_total,
        "phases": phase_records,
        "characters": phase_records[-1]["characters"] if phase_records else {},
        "objective": next((r["objective"] for r in phase_records
                           if r.get("objective")), None),
        # The leveled builds as they leave the adventure (Update 17: a scenario
        # chains adventures — the next one starts from these; earned_points ride
        # inside them). Not part of the spec hash.
        "final_builds": [copy.deepcopy(lo.get("character", {})) for lo in loadouts],
    }
