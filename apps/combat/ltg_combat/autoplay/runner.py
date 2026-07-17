"""The autoplay runner (§D12-3.4) — deterministic fights, measured.

``run_one(spec, policy, seed)`` plays one composed encounter spec to completion
through only ``legal_actions`` / ``apply_action`` and returns a plain-dict
RunRecord. The invariant: identical ``(spec, policy version, seed)`` yields an
identical record — asserted by a test that runs the same fight twice. Every
record carries the full repro key ``(spec hash, policy version, seed)``:
because the engine is deterministic, the repro IS the key.

A round cap of 50 (T-71) flags non-terminating fights as anomalies rather than
hanging; an action cap backstops pathological in-turn loops the same way.

``run_adventure`` replicates the game server's act carry-over and level-up
rules (§D10-2/3) locally — the session layer is not imported. The magnitudes
mirror the Rebalance Register: T-57 (30 points per level), T-58 (gauge carries
at 50%, floored), T-59 (act-start HP floor at 25% of max).
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from ltg_core.schema import Character, LEVEL_UP_POINTS

from ..engine import apply_action, legal_actions
from ..scenario import compose_spec, scale_encounter, state_from_dict
from ..state import GameState
from .policies import Policy

ROUND_CAP = 50        # T-71: rounds before a fight is flagged non-terminating
ACTION_CAP = 20000    # backstop for in-turn loops (same anomaly treatment)

# T-58 / T-59 (§D10-2), replicated from the session layer by design.
GAUGE_CARRY = 0.5
HP_FLOOR_PCT = 25

# The balance-register Power bump (T-64), replicated from the game server's
# content layer (ltg_combat must not depend on it). Keep in sync with
# ltg_game_server.content.ENEMY_POWER_BONUS / BOSS_POWER_BONUS; --raw-power
# disables it, which is exactly the retroactive T-64 before/after diff.
ENEMY_POWER_BONUS = 2
BOSS_POWER_BONUS = 4

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


def _bump_enemy_power(scenario: Dict[str, Any]) -> None:
    """T-64 in place: +2 Power every enemy, +4 a boss — chassis Power and
    attack-type intent template amounts (melee + ranged fallback)."""
    for e in scenario.get("enemies", []):
        if not isinstance(e, dict):
            continue
        bump = BOSS_POWER_BONUS if e.get("is_boss") else ENEMY_POWER_BONUS
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


def prepare_scenario(content: Dict[str, Any], party_size: int,
                     difficulty: str = "standard",
                     power_bump: bool = True) -> Dict[str, Any]:
    """One act/encounter shaped exactly as the server's build path shapes it:
    difficulty HP ratio → per-size layout resolution (objectives included) →
    the T-64 Power bump."""
    scenario = copy.deepcopy(content)
    _scale_difficulty(scenario, difficulty)
    scenario = scale_encounter(scenario, party_size)
    if power_bump:
        _bump_enemy_power(scenario)
    return scenario


# --------------------------------------------------------------------------- #
# The drive loop
# --------------------------------------------------------------------------- #
def _drive(st: GameState, policy: Policy, rng: random.Random,
           round_cap: int) -> Tuple[GameState, Optional[str]]:
    """Play to completion. Returns (final state, anomaly or None)."""
    actions = 0
    while st.result is None:
        if st.turn > round_cap:
            return st, "round_cap"
        acts = legal_actions(st)
        if not acts:
            return st, "no_actions"
        act = policy.choose(st, acts, rng)
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
            "card_events": {}}


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
        elif ev.type == "channel_end":
            cid = d.get("character")
            if cid in chars:
                chars[cid]["channels_ended"] += 1
            elif d.get("enemy"):
                enemy_channels_broken += 1
        elif ev.type == "enemy_died":
            eid = d.get("enemy")
            if eid:
                enemies.setdefault(eid, {})["died_round"] = turn
    for c in st.party:
        m = chars[c.id]
        m["dead_in_hand"] = len(c.hand) + len(c.library)
        m["mana_wasted"] = max(0, m["mana_granted"] - m["mana_spent"])
        m["end_hp"] = c.hp
        m["alive"] = c.alive
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
    st, anomaly = _drive(st, policy, rng, round_cap)
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
    return record


# --------------------------------------------------------------------------- #
# run_adventure — the three-act run, session rules replicated (§D10-2/3)
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
    """Play an adventure (a dict with inline ``acts``: complete encounter
    objects) through the §D10-2/3 boundary rules: full-pool shuffle-up + fresh
    hand, HP floor, 50% gauge carry, and a 30-point level-up spent by the
    policy's spend plan. Returns one RunRecord with per-act snapshots."""
    acts = adventure.get("acts") or []
    if not acts:
        raise ValueError("adventure has no acts")
    loadouts = copy.deepcopy(loadouts)
    h = spec_hash({"adventure": adventure, "party": [
        lo.get("character", {}).get("name", "") for lo in loadouts]})
    rng = _policy_rng(h, policy, seed)
    banked: Dict[str, int] = {}
    carry: Optional[Dict[str, Dict[str, Any]]] = None
    heals: Dict[str, int] = {}
    act_records: List[Dict[str, Any]] = []
    result, anomaly, rounds_total = None, None, 0
    party_label = ""

    for i, act in enumerate(acts):
        scenario = prepare_scenario(act, len(loadouts), difficulty, power_bump)
        spec = compose_spec(loadouts, scenario)
        party_label = "+".join(p["id"] for p in spec["party"])
        st = state_from_dict(spec, seed=seed * 1000003 + i)
        if carry is not None:
            _apply_carry(st, carry, heals,
                         random.Random(f"{h}:{seed}:carry:{i}"))
        entering = {c.id: c.hp for c in st.party}
        st, act_anomaly = _drive(st, policy, rng, round_cap)
        rec = {"act": i + 1, "name": act.get("name", f"Act {i + 1}"),
               "result": st.result or "anomaly", "anomaly": act_anomaly,
               "rounds": st.turn, "entering_hp": entering,
               "spend_plan": policy.spend_plan,
               "banked": dict(banked)}
        rec.update(_collect_metrics(st, spec))
        act_records.append(rec)
        rounds_total += st.turn
        if act_anomaly is not None:
            result, anomaly = "anomaly", act_anomaly
            break
        if st.result != "victory":
            result = st.result
            break
        if i == len(acts) - 1:
            result = "victory"
            break

        # The act boundary (§D10-3): level up through the policy's spend plan.
        carry = _carry_snapshot(st)
        heals = {}
        live_ids = [c.id for c in st.party]
        for slot, lo in enumerate(loadouts):
            live_id = live_ids[slot] if slot < len(live_ids) else None
            old = dict(lo.get("character", {}))
            new_level = i + 2
            available = banked.get(live_id, 0) + LEVEL_UP_POINTS
            candidate = {**old, "level": new_level}
            new_char, spent = policy.spend_level_up(candidate, available)
            try:
                Character.model_validate(new_char)
            except Exception:
                # An invalid spend keeps the entering build (level bump only);
                # the points bank instead — the run keeps its determinism.
                new_char, spent = candidate, 0
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
        "acts": act_records,
        "characters": act_records[-1]["characters"] if act_records else {},
        "objective": next((r["objective"] for r in act_records
                           if r.get("objective")), None),
    }
