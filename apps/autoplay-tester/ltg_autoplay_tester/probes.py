"""Probes and verdicts (§D13-1, §D13-3.1) — the paired-ablation spine.

Every probe answers one question about one subject by A/B runs on IDENTICAL
seeds over a gauntlet: variant A and B share each seed's shuffle and
initiative, so the per-pair win difference is read with most run-to-run
variance removed. The measuring stick is the launch harness (`greedy-1.0.0`,
`balanced` spend); a verdict stamps gauntlet hash + policy version and is
comparable only within them.

The Tester never edits content: a verdict is a report with one recommended
lever, and the "apply" path is the Deckbuilder's own edit flow.
"""

from __future__ import annotations

import copy
import datetime
import math
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from ltg_combat.autoplay import make_policy, run_adventure, run_one
from ltg_combat.autoplay.report import FOOTER, aggregate
from ltg_combat.autoplay.runner import prepare_scenario
from ltg_combat.scenario import _slug, compose_spec

# --------------------------------------------------------------------------- #
# Register values (proposed §D13-5)
# --------------------------------------------------------------------------- #
# T-73: the neutral filler the ablation spine substitutes — colourless cost so
# it is castable in any identity; level 1 so it is never level-gated (which
# slightly flatters dead high-level cards; documented approximation).
FILLER_CARD: Dict[str, Any] = {
    "id": "filler_practice_swing", "name": "Practice Swing",
    "source_name": "Practice Swing", "rarity": "common", "level": 1,
    "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 1},
    "effects": [{"kind": "deal_damage", "amount": 2,
                 "target": {"mode": "chosen", "side": "enemy",
                            "targeted": True}}],
    "validated": True,
}

# T-74: flag bands on the paired win-rate delta (percentage points), CALIBRATED
# TO THE PRESSURE-LADDER INSTRUMENT UNDER greedy-1.2.0 / baseline-2 (reference
# deck: normal cards +1.7 ± 1.9 pp). OVER at +4 pp = the card is carrying —
# note that a deck's legitimate best cards can flag too; the lever ladder is
# what separates "strong card, priceable" from "broken effect". The z-vs-deck
# read is ADVISORY context, not a gate: near the win-rate ceiling every delta
# compresses and z under-fires (see the ceiling warning below). Recalibrate on
# every policy-version bump.
OVER_PP = 4.0
UNDER_PP = -4.0
OVER_Z = 2.0          # advisory: SDs above the deck's own distribution

# Ceiling/floor compression: when the as-is variant wins more than CEILING (or
# fewer than FLOOR) of its cells, breaking points sit outside the ladder and
# paired deltas are squashed — the verdict carries a saturation warning.
CEILING = 0.85
FLOOR = 0.15

# T-75: ultimate dependence — share of wins routed through casting it.
ULT_DEPENDENCE = 0.60

# The PRESSURE LADDER: every cell runs at each of these enemy HP+Power
# multipliers. The engine is deterministic and the policies are fixed, so at
# any one pressure a cell sits hard against 0% or 100% and seeds barely move
# it; the ladder instead measures each fight's BREAKING POINT — the multiplier
# where victory tips to defeat — at 0.1 resolution. A card's contribution then
# registers as a threshold shift (rungs crossed), which is exactly what "how
# much harder a fight can this card win" means. ×1.0 is the game as shipped;
# the other rungs are instruments, not content. Seeds stay few by design: the
# variance lives across rungs, not shuffles.
# 0.5–2.2: the top rungs exist so STRONG decks still break inside the
# instrument — a breaking point above the ladder reads as ceiling compression
# and hides card deltas (observed when greedy-1.2.0 lifted the reference deck
# past ×1.6). Widen again if a deck ever wins > ~85% of a probe's cells.
PRESSURE_LADDER = tuple(round(0.5 + 0.1 * i, 1) for i in range(18))  # 0.5–2.2

# T-76: presets. `quick` is the bench default (a screening read); `thorough`
# is the bar for a verdict you'd act on and adds the leave-one-out deck sweep.
PRESETS: Dict[str, Dict[str, Any]] = {
    "quick": {"seeds": 8, "difficulties": ["standard"], "sizes": [1, 2],
              "pressures": PRESSURE_LADDER, "loo_sweep": False},
    "thorough": {"seeds": 24, "difficulties": ["standard"],
                 "sizes": [1, 2], "pressures": PRESSURE_LADDER,
                 "loo_sweep": True},
}

# Verdicts about these effect kinds carry the COMBO-BLIND stamp: the greedy
# stick never sequences them, so it can convict but never acquit (§D13-1.1).
COMBO_KINDS = frozenset({"amplify", "double_next", "copy_spell", "stance"})

POLICY = "greedy"
SPEND = "balanced"


# --------------------------------------------------------------------------- #
# Loadout variant builders
# --------------------------------------------------------------------------- #
def character_id_of(loadout: Dict[str, Any]) -> str:
    return _slug(str(loadout.get("character", {}).get("name", "")))


def _find_card(loadout: Dict[str, Any], card_id: str) -> Dict[str, Any]:
    for c in loadout.get("cards", []):
        if c.get("id") == card_id:
            return c
    raise ValueError(f"card '{card_id}' is not in this loadout's deck")


def ablate_card(loadout: Dict[str, Any], card_id: str) -> Dict[str, Any]:
    """The deck with `card_id` replaced by the T-73 filler."""
    out = copy.deepcopy(loadout)
    for i, c in enumerate(out.get("cards", [])):
        if c.get("id") == card_id:
            out["cards"][i] = copy.deepcopy(FILLER_CARD)
            return out
    raise ValueError(f"card '{card_id}' is not in this loadout's deck")


def _largest_amount_effect(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    best = None
    for e in card.get("effects", []):
        if (e.get("kind") in ("deal_damage", "heal")
                and isinstance(e.get("amount"), int) and e["amount"] > 1):
            if best is None or e["amount"] > best["amount"]:
                best = e
    return best


def lever_variants(loadout: Dict[str, Any],
                   card_id: str) -> List[Tuple[str, Dict[str, Any]]]:
    """The §D13-1.2 lever ladder, in order: cost +1 → cost +2 →
    instant→sorcery (instants only) → largest magnitude −1 (when it exists)."""
    card = _find_card(loadout, card_id)
    out: List[Tuple[str, Dict[str, Any]]] = []

    def variant(label: str, mutate: Callable[[Dict[str, Any]], None]) -> None:
        lo = copy.deepcopy(loadout)
        c = _find_card(lo, card_id)
        mutate(c)
        out.append((label, lo))

    def bump_cost(c: Dict[str, Any], n: int) -> None:
        cost = c.setdefault("cost", {})
        cost["generic"] = int(cost.get("generic", 0)) + n

    variant("cost +1 generic", lambda c: bump_cost(c, 1))
    variant("cost +2 generic", lambda c: bump_cost(c, 2))
    if card.get("timing") == "instant":
        def to_sorcery(c: Dict[str, Any]) -> None:
            c["timing"] = "sorcery"
        variant("instant → sorcery", to_sorcery)
    if _largest_amount_effect(card) is not None:
        def dec(c: Dict[str, Any]) -> None:
            e = _largest_amount_effect(c)
            e["amount"] -= 1
        variant("magnitude −1", dec)
    return out


def remove_heroic(loadout: Dict[str, Any], slot: str) -> Dict[str, Any]:
    if slot not in ("skill", "ultimate"):
        raise ValueError("slot must be 'skill' or 'ultimate'")
    out = copy.deepcopy(loadout)
    out.setdefault("character", {})[slot] = None
    return out


def _card_is_combo(card: Dict[str, Any]) -> bool:
    def kinds(effects):
        for e in effects or []:
            yield e.get("kind")
            for m in e.get("modes", []) or []:
                yield from kinds(m.get("effects"))
            yield from kinds(e.get("effects"))
    return bool(set(kinds(card.get("effects"))) & COMBO_KINDS)


# --------------------------------------------------------------------------- #
# The batch runner (paired cells, fanned across processes)
# --------------------------------------------------------------------------- #
def _run_task(task: Dict[str, Any]) -> Dict[str, Any]:
    policy = make_policy(task["policy"], task["spend"])
    if task["mode"] == "adventure":
        return run_adventure(task["adventure"], task["loadouts"], policy,
                             task["seed"], difficulty=task["difficulty"],
                             label=task["label"])
    return run_one(task["spec"], policy, task["seed"],
                   difficulty=task["difficulty"], label=task["label"])


def _apply_pressure(enc: Dict[str, Any], mult: float) -> Dict[str, Any]:
    """The pressure dial: enemy HP, Power, and attack-template amounts × mult
    (ceil, floor 1). ×1.0 returns the encounter untouched."""
    if abs(mult - 1.0) < 1e-9:
        return enc
    out = copy.deepcopy(enc)

    def bump(v):
        try:
            return max(1, math.ceil(int(v) * mult))
        except (TypeError, ValueError):
            return v

    for e in out.get("enemies", []):
        if not isinstance(e, dict):
            continue
        if "hp" in e:
            e["hp"] = bump(e["hp"])
        if "power" in e:
            e["power"] = bump(e["power"])
        for key in ("intent", "ranged_intent"):
            tmpl = e.get(key)
            if isinstance(tmpl, dict) and isinstance(tmpl.get("amount"), int):
                tmpl["amount"] = bump(tmpl["amount"])
    for t in (out.get("tokens") or {}).values():
        if isinstance(t, dict) and "hp" in t:
            t["hp"] = bump(t["hp"])
    return out


def _cell_tasks(loadouts: List[Dict[str, Any]], gauntlet: Dict[str, Any],
                preset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The (encounter × size × difficulty × pressure × seed) grid for one
    variant's party. Sizes above the party's roster clamp out; every task
    carries a `pair_key` identical across variants so records pair up."""
    tasks = []
    pressures = preset.get("pressures", (1.0,))
    for enc in gauntlet["encounters"]:
        for size in preset["sizes"]:
            if size > len(loadouts):
                continue
            party = loadouts[:size]
            for difficulty in preset["difficulties"]:
                for mult in pressures:
                    scenario = prepare_scenario(_apply_pressure(enc, mult),
                                                size, difficulty)
                    spec = compose_spec(party, scenario)
                    label = (difficulty if abs(mult - 1.0) < 1e-9
                             else f"{difficulty}@{mult:g}")
                    for seed in range(preset["seeds"]):
                        tasks.append({
                            "mode": "spec", "spec": spec, "seed": seed,
                            "difficulty": label,
                            "label": enc.get("name", ""),
                            "policy": POLICY, "spend": SPEND,
                            "pair_key": (enc.get("_file", enc.get("name", "")),
                                         size, difficulty, mult, seed),
                        })
    return tasks


def _run_batch(tasks: List[Dict[str, Any]], jobs: int = 1,
               progress: Optional[Callable[[int], None]] = None
               ) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for i, rec in enumerate(pool.map(_run_task, tasks, chunksize=8)):
                records.append(rec)
                if progress:
                    progress(i + 1)
    else:
        for i, task in enumerate(tasks):
            records.append(_run_task(task))
            if progress:
                progress(i + 1)
    for task, rec in zip(tasks, records):
        rec["pair_key"] = list(task["pair_key"])
    return records


# --------------------------------------------------------------------------- #
# Paired statistics
# --------------------------------------------------------------------------- #
def paired_stats(records_a: List[Dict[str, Any]],
                 records_b: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Win-rate delta A−B over pairs sharing a `pair_key`, in percentage
    points, with the paired standard error and 95% CI."""
    b_by_key = {tuple(r["pair_key"]): r for r in records_b}
    n = a_wins = b_wins = d10 = d01 = 0
    for ra in records_a:
        rb = b_by_key.get(tuple(ra["pair_key"]))
        if rb is None:
            continue
        n += 1
        aw = 1 if ra.get("result") == "victory" else 0
        bw = 1 if rb.get("result") == "victory" else 0
        a_wins += aw
        b_wins += bw
        if aw and not bw:
            d10 += 1
        elif bw and not aw:
            d01 += 1
    if n == 0:
        return {"n": 0, "delta_pp": 0.0, "se_pp": 0.0, "ci95_pp": 0.0,
                "win_a": 0.0, "win_b": 0.0, "discordant": [0, 0]}
    delta = (a_wins - b_wins) / n
    var = max(0.0, (d10 + d01) / n - delta * delta)
    se = math.sqrt(var / n)
    return {
        "n": n,
        "win_a": round(a_wins / n, 4),
        "win_b": round(b_wins / n, 4),
        "delta_pp": round(delta * 100, 2),
        "se_pp": round(se * 100, 2),
        "ci95_pp": round(1.96 * se * 100, 2),
        "discordant": [d10, d01],
    }


def _in_band(delta_pp: float) -> bool:
    return UNDER_PP <= delta_pp <= OVER_PP


# --------------------------------------------------------------------------- #
# Screening (free metrics from one variant's records)
# --------------------------------------------------------------------------- #
def screening_table(records: List[Dict[str, Any]], character_id: str,
                    loadout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-card cast-vs-held split over the as-is records — cheap, confounded,
    and only a ranking signal for which cards deserve the expensive probe."""
    names = {c["id"]: c.get("name", c["id"]) for c in loadout.get("cards", [])}
    stats: Dict[str, Dict[str, int]] = {
        cid: {"seen": 0, "cast": 0, "win_cast": 0, "win_held": 0, "held": 0}
        for cid in names}
    for rec in records:
        m = (rec.get("characters") or {}).get(character_id)
        if not m:
            continue
        win = rec.get("result") == "victory"
        for card_id, (drawn, cast) in (m.get("card_events") or {}).items():
            s = stats.get(card_id)
            if s is None:
                continue
            if drawn > 0 or cast > 0:
                s["seen"] += 1
            if cast > 0:
                s["cast"] += 1
                s["win_cast"] += 1 if win else 0
            elif drawn > 0:
                s["held"] += 1
                s["win_held"] += 1 if win else 0
    out = []
    for card_id, s in stats.items():
        wr_cast = s["win_cast"] / s["cast"] if s["cast"] else None
        wr_held = s["win_held"] / s["held"] if s["held"] else None
        out.append({
            "card_id": card_id, "name": names[card_id],
            "games_seen": s["seen"], "games_cast": s["cast"],
            "win_when_cast": round(wr_cast, 4) if wr_cast is not None else None,
            "win_when_held": round(wr_held, 4) if wr_held is not None else None,
            "cast_vs_held_pp": (round((wr_cast - wr_held) * 100, 1)
                                if wr_cast is not None and wr_held is not None
                                else None),
        })
    out.sort(key=lambda r: -(r["cast_vs_held_pp"] or -999))
    return out


# --------------------------------------------------------------------------- #
# The probes
# --------------------------------------------------------------------------- #
def probe_party(loadout: Dict[str, Any],
                gauntlet: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The subject plus the gauntlet's vanilla Training Ally (falling back to
    the sparring partner) — so size-2 cells exist and ally-directed support
    value has the SAME plain body to land on for every subject."""
    ally = gauntlet.get("training_ally") or gauntlet.get("sparring_partner")
    return [loadout] + ([ally] if ally else [])


def _base_verdict(kind: str, subject: Dict[str, Any], preset_name: str,
                  preset: Dict[str, Any], gauntlet: Dict[str, Any]) -> Dict[str, Any]:
    policy = make_policy(POLICY, SPEND)
    return {
        "kind": kind,
        "subject": subject,
        "preset": preset_name,
        "screening_only": not preset["loo_sweep"],
        "gauntlet": {"id": gauntlet["id"], "hash": gauntlet["hash"],
                     "name": gauntlet["name"]},
        "policy_version": policy.version,
        "spend_plan": SPEND,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "footer": FOOTER,
    }


def probe_card(loadout: Dict[str, Any], card_id: str,
               gauntlet: Dict[str, Any], preset_name: str = "quick",
               jobs: int = 1,
               progress: Optional[Callable[[int, int, str], None]] = None
               ) -> Dict[str, Any]:
    """The §D13-1.2 card probe: ablation vs the filler, the deck-context sweep
    (thorough), and the lever ladder for OVER cards."""
    preset = PRESETS[preset_name]
    cid = character_id_of(loadout)
    card = _find_card(loadout, card_id)
    combo_blind = _card_is_combo(card)

    variants: List[Tuple[str, Dict[str, Any]]] = [
        ("as-is", loadout), ("ablated", ablate_card(loadout, card_id))]
    loo_ids: List[str] = []
    if preset["loo_sweep"]:
        for other in loadout.get("cards", []):
            if other["id"] != card_id and other["id"] not in loo_ids:
                loo_ids.append(other["id"])
                variants.append((f"loo:{other['id']}",
                                 ablate_card(loadout, other["id"])))

    cell_count = len(_cell_tasks(probe_party(loadout, gauntlet), gauntlet,
                                 preset))
    total = cell_count * (len(variants) + 4)  # ladder headroom for the bar
    done = [0]

    def _prog(label):
        def cb(i):
            if progress:
                progress(done[0] + i, total, label)
        return cb

    runs: Dict[str, List[Dict[str, Any]]] = {}
    for label, lo in variants:
        tasks = _cell_tasks(probe_party(lo, gauntlet), gauntlet, preset)
        runs[label] = _run_batch(tasks, jobs, _prog(label))
        done[0] += len(tasks)

    marginal = paired_stats(runs["as-is"], runs["ablated"])

    # Deck context (thorough): the distribution every card's marginal sits in.
    deck_marginals: Dict[str, float] = {}
    z = None
    if preset["loo_sweep"]:
        for other_id in loo_ids:
            deck_marginals[other_id] = paired_stats(
                runs["as-is"], runs[f"loo:{other_id}"])["delta_pp"]
        pool = list(deck_marginals.values())
        if len(pool) >= 3:
            mean = sum(pool) / len(pool)
            sd = math.sqrt(sum((x - mean) ** 2 for x in pool) / len(pool))
            z = (marginal["delta_pp"] - mean) / sd if sd > 0 else None

    # The honest-verdict guard: a card the stick never actually CAST in the
    # as-is runs was not measured — its marginal is the filler-displacement
    # constant, not the card. No measurement without exercise.
    screening = screening_table(runs["as-is"], cid, loadout)
    subject_row = next((s for s in screening if s["card_id"] == card_id), None)
    exercised = bool(subject_row and subject_row["games_cast"] > 0)

    over = exercised and marginal["delta_pp"] > OVER_PP
    under = exercised and marginal["delta_pp"] < UNDER_PP
    flag = ("NOT_EXERCISED" if not exercised
            else "OVER" if over else "UNDER" if under else "IN_BAND")
    saturated = (marginal["win_a"] > CEILING or marginal["win_a"] < FLOOR)

    # The lever ladder (OVER only): each rung vs the SAME ablated baseline.
    ladder: List[Dict[str, Any]] = []
    recommendation = None
    if over:
        for lever, lo in lever_variants(loadout, card_id):
            tasks = _cell_tasks(probe_party(lo, gauntlet), gauntlet, preset)
            recs = _run_batch(tasks, jobs, _prog(lever))
            done[0] += len(tasks)
            stats = paired_stats(recs, runs["ablated"])
            rung = {"lever": lever, **stats,
                    "in_band": _in_band(stats["delta_pp"])}
            ladder.append(rung)
            if rung["in_band"] and recommendation is None:
                recommendation = (
                    f"{card['name']} at its printed cost: "
                    f"{marginal['delta_pp']:+.1f} pp over filler. "
                    f"With {lever}: {stats['delta_pp']:+.1f} pp — in band. "
                    f"Recommend {lever}.")
        if recommendation is None:
            recommendation = (
                f"{card['name']} stays {ladder[-1]['delta_pp']:+.1f} pp over "
                "filler even after every lever — the effect itself is the "
                "problem; redesign rather than reprice.")
    elif not exercised:
        recommendation = (
            f"NOT EXERCISED — the {POLICY} stick cast {card['name']} in zero "
            "of its games, so this probe measured the filler swap, not the "
            "card. No verdict"
            + (" (COMBO-BLIND: its effects are outside the stick's "
               "vocabulary)." if combo_blind else
               " — if this card is castable, the policy's vocabulary is the "
               "gap; report it."))
    elif under:
        recommendation = (
            f"{card['name']} reads {marginal['delta_pp']:+.1f} pp vs filler — "
            + ("COMBO-BLIND: the greedy stick cannot sequence this card; "
               "treat the number as a floor, not a verdict."
               if combo_blind else
               "consider cost −1 or magnitude +1 (rerun after the change)."))
    else:
        recommendation = (f"{card['name']} sits in band "
                          f"({marginal['delta_pp']:+.1f} pp vs filler). "
                          "No change recommended.")

    verdict = _base_verdict(
        "card", {"character_id": cid, "card_id": card_id,
                 "card_name": card.get("name", card_id)},
        preset_name, preset, gauntlet)
    if saturated:
        recommendation += (
            f" SATURATION WARNING: the deck wins {marginal['win_a']:.0%} of "
            "these cells — breaking points sit at the edge of the pressure "
            "ladder and every delta is compressed; treat magnitudes here as "
            "floors, and consider a harder gauntlet for this deck.")
    verdict.update({
        "flag": flag,
        "combo_blind": combo_blind,
        "exercised": exercised,
        "saturated": saturated,
        "marginal": marginal,
        "z_vs_deck": round(z, 2) if z is not None else None,
        "deck_marginals": {k: round(v, 2) for k, v in deck_marginals.items()},
        "ladder": ladder,
        "recommendation": recommendation,
        "screening": screening,
        "cells": aggregate(runs["as-is"])["cells"],
    })
    return verdict


def probe_heroic(loadout: Dict[str, Any], slot: str,
                 gauntlet: Dict[str, Any], preset_name: str = "quick",
                 jobs: int = 1,
                 progress: Optional[Callable[[int, int, str], None]] = None
                 ) -> Dict[str, Any]:
    """The §D13-1.3 heroic probe: with vs without the Skill/Ultimate, plus the
    T-75 dependence read for ultimates."""
    preset = PRESETS[preset_name]
    cid = character_id_of(loadout)
    heroic = (loadout.get("character") or {}).get(slot)
    if not heroic:
        raise ValueError(f"{cid} has no {slot} to probe")
    combo_blind = _card_is_combo(heroic)

    tasks_a = _cell_tasks(probe_party(loadout, gauntlet), gauntlet, preset)
    total = len(tasks_a) * 2
    done = [0]

    def _prog(label):
        def cb(i):
            if progress:
                progress(done[0] + i, total, label)
        return cb

    runs_a = _run_batch(tasks_a, jobs, _prog("as-is"))
    done[0] += len(tasks_a)
    without = remove_heroic(loadout, slot)
    runs_b = _run_batch(_cell_tasks(probe_party(without, gauntlet), gauntlet,
                                    preset),
                        jobs, _prog(f"without {slot}"))
    marginal = paired_stats(runs_a, runs_b)

    dependence = None
    if slot == "ultimate":
        wins = [r for r in runs_a if r.get("result") == "victory"]
        through = [r for r in wins
                   if (r.get("characters") or {}).get(cid, {})
                   .get("ultimate_round") is not None]
        dependence = round(len(through) / len(wins), 4) if wins else None
        exercised = any((r.get("characters") or {}).get(cid, {})
                        .get("ultimate_round") is not None for r in runs_a)
    else:  # skill casts land in card_events under the skill card's id
        exercised = any(
            (r.get("characters") or {}).get(cid, {})
            .get("card_events", {}).get(heroic.get("id"), [0, 0])[1] > 0
            for r in runs_a)

    over = exercised and marginal["delta_pp"] > OVER_PP
    dependent = dependence is not None and dependence > ULT_DEPENDENCE
    flag = ("NOT_EXERCISED" if not exercised
            else "OVER" if (over or dependent)
            else "UNDER" if marginal["delta_pp"] < UNDER_PP else "IN_BAND")
    name = heroic.get("name", slot)
    if not exercised:
        recommendation = (
            f"NOT EXERCISED — the {POLICY} stick never "
            + ("cast the ultimate (the gauge never filled, or no window "
               "offered it)" if slot == "ultimate" else "used the Skill")
            + f" in {marginal['n']} games, so this probe measured nothing. "
              "No verdict.")
    elif over:
        recommendation = (
            f"{name} carries {marginal['delta_pp']:+.1f} pp — "
            + ("trim the largest magnitude by 1 or cut an effect (the gauge "
               "is the cost; there is no price to raise)." if slot == "ultimate"
               else "raise its mana cost by 1 and rerun."))
    elif dependent:
        recommendation = (
            f"{name} is in band overall but {dependence:.0%} of wins route "
            f"through casting it (> {ULT_DEPENDENCE:.0%}, T-75) — the build "
            "only wins through its limit break; rebalance the deck around it "
            "or trim the ultimate.")
    elif flag == "UNDER":
        recommendation = (f"{name} reads {marginal['delta_pp']:+.1f} pp — "
                          + ("COMBO-BLIND; treat as a floor."
                             if combo_blind else "consider a magnitude bump."))
    else:
        recommendation = (f"{name} sits in band "
                          f"({marginal['delta_pp']:+.1f} pp). No change.")

    verdict = _base_verdict(
        slot, {"character_id": cid, "card_id": heroic.get("id"),
               "card_name": name},
        preset_name, preset, gauntlet)
    verdict.update({
        "flag": flag,
        "combo_blind": combo_blind,
        "exercised": exercised,
        "marginal": marginal,
        "ultimate_dependence": dependence,
        "ladder": [],
        "recommendation": recommendation,
        "cells": aggregate(runs_a)["cells"],
    })
    return verdict


def probe_character(loadout: Dict[str, Any],
                    roster: List[Dict[str, Any]],
                    gauntlet: Dict[str, Any], preset_name: str = "quick",
                    jobs: int = 1,
                    progress: Optional[Callable[[int, int, str], None]] = None
                    ) -> Dict[str, Any]:
    """The §D13-1.4 character probe (support-fair form): every roster member
    runs the IDENTICAL solo + duo cells beside the gauntlet's vanilla Training
    Ally, so ally-directed kits have the same plain body to support; an
    ally-pair baseline (two vanillas) anchors what a character ADDS over a
    warm body. Heroics are isolated with-vs-without on the same paired cells;
    the spend-plan audit runs across a pressure ladder of the adventure."""
    preset = PRESETS[preset_name]
    cid = character_id_of(loadout)
    char = loadout.get("character") or {}
    deck_size = len(loadout.get("cards", []))
    ally = gauntlet.get("training_ally") or gauntlet.get("sparring_partner")

    others = [lo for lo in roster if character_id_of(lo) != cid]
    heroic_slots = [s for s in ("skill", "ultimate") if char.get(s)]
    cell_count = len(_cell_tasks(probe_party(loadout, gauntlet), gauntlet,
                                 preset))
    audit_pressures = (0.6, 0.8, 1.0, 1.2)
    audit_seeds = max(3, preset["seeds"] // 8)
    n_batches = (1 + len(others) + (1 if ally else 0) + len(heroic_slots))
    total = cell_count * n_batches + (
        audit_seeds * len(audit_pressures) * 4 if gauntlet.get("adventure") else 0)
    done = [0]

    def _prog(label):
        def cb(i):
            if progress:
                progress(done[0] + i, total, label)
        return cb

    def _win_rate(records, size=None):
        pool = [r for r in records if size is None or r.get("size") == size]
        if not pool:
            return None
        return sum(1 for r in pool if r["result"] == "victory") / len(pool)

    # Roster standings: everyone runs the identical solo+duo cells.
    subject_runs = _run_batch(
        _cell_tasks(probe_party(loadout, gauntlet), gauntlet, preset),
        jobs, _prog(cid))
    done[0] += cell_count
    roster_runs: Dict[str, List[Dict[str, Any]]] = {cid: subject_runs}
    for other in others:
        oid = character_id_of(other)
        roster_runs[oid] = _run_batch(
            _cell_tasks(probe_party(other, gauntlet), gauntlet, preset),
            jobs, _prog(oid))
        done[0] += cell_count
    roster_rates = {k: round(_win_rate(recs), 4)
                    for k, recs in roster_runs.items()}
    roster_solo = {k: (round(_win_rate(recs, 1), 4)
                       if _win_rate(recs, 1) is not None else None)
                   for k, recs in roster_runs.items()}
    roster_duo = {k: (round(_win_rate(recs, 2), 4)
                      if _win_rate(recs, 2) is not None else None)
                  for k, recs in roster_runs.items()}

    # The ally-pair floor: two vanillas on the same cells — what "just a warm
    # body" achieves. A character's CONTRIBUTION is their rate minus this.
    ally_baseline = None
    if ally:
        pair_runs = _run_batch(
            _cell_tasks([ally, ally], gauntlet, preset), jobs,
            _prog("ally pair"))
        done[0] += len(pair_runs)
        ally_baseline = round(_win_rate(pair_runs) or 0.0, 4)

    below = sum(1 for k, v in roster_rates.items()
                if k != cid and v < roster_rates[cid])
    ties = sum(1 for k, v in roster_rates.items()
               if k != cid and abs(v - roster_rates[cid]) < 1e-9)
    percentile = (round(100 * (below + 0.5 * ties) / (len(roster_rates) - 1))
                  if len(roster_rates) > 1 else None)

    # The heroics, ISOLATED: with-vs-without on the same paired cells.
    heroics: Dict[str, Any] = {}
    for slot in heroic_slots:
        heroic = char[slot]
        without = remove_heroic(loadout, slot)
        recs = _run_batch(
            _cell_tasks(probe_party(without, gauntlet), gauntlet, preset),
            jobs, _prog(f"without {slot}"))
        done[0] += cell_count
        stats = paired_stats(subject_runs, recs)
        if slot == "ultimate":
            casts = sum(1 for r in subject_runs
                        if (r.get("characters") or {}).get(cid, {})
                        .get("ultimate_round") is not None)
            wins = [r for r in subject_runs if r.get("result") == "victory"]
            through = [r for r in wins
                       if (r.get("characters") or {}).get(cid, {})
                       .get("ultimate_round") is not None]
            dependence = (round(len(through) / len(wins), 4) if wins else None)
        else:
            casts = sum(1 for r in subject_runs
                        if (r.get("characters") or {}).get(cid, {})
                        .get("card_events", {}).get(heroic.get("id"),
                                                    [0, 0])[1] > 0)
            dependence = None
        heroics[slot] = {
            "name": heroic.get("name", slot),
            "marginal": stats,
            "games_cast": casts,
            "games": len(subject_runs),
            "dependence": dependence,
            "exercised": casts > 0,
        }

    # Attribution: where the games went, split solo vs duo, WITH denominators.
    def _attr(records, size):
        keys = ("damage_dealt", "healing_done", "mana_granted", "mana_wasted",
                "cards_cast", "dead_in_hand")
        totals = {k: 0 for k in keys}
        n = 0
        for r in records:
            if r.get("size") != size:
                continue
            m = (r.get("characters") or {}).get(cid)
            if m:
                n += 1
                for k in keys:
                    totals[k] += m.get(k, 0)
        return ({k: round(v / n, 2) for k, v in totals.items()} if n else None)

    # The spend-plan audit, across a pressure ladder of the adventure.
    spend_audit = None
    spend_audit_meta = None
    if gauntlet.get("adventure"):
        spend_audit = {}
        for plan in ("balanced", "greedy-hp", "greedy-power", "greedy-mana"):
            policy = make_policy(POLICY, plan)
            wins = runs = 0
            for mult in audit_pressures:
                adv = {
                    "name": gauntlet["adventure"].get("name", "adventure"),
                    "acts": [_apply_pressure(a, mult)
                             for a in gauntlet["adventure"]["acts"]],
                }
                for seed in range(audit_seeds):
                    rec = run_adventure(adv, [loadout], policy, seed)
                    runs += 1
                    wins += 1 if rec["result"] == "victory" else 0
                    done[0] += 1
                    if progress:
                        progress(done[0], total, f"spend:{plan}@{mult:g}")
            spend_audit[plan] = round(wins / max(1, runs), 4)
        rates = list(spend_audit.values())
        spend_audit_meta = {
            "pressures": list(audit_pressures),
            "runs_per_plan": audit_seeds * len(audit_pressures),
            "no_signal": (max(rates) - min(rates) < 0.08
                          or max(rates) < 0.05 or min(rates) > 0.95),
        }

    rates_sorted = sorted(roster_rates.items(), key=lambda kv: -kv[1])
    spread = (max(roster_rates.values()) - min(roster_rates.values())
              if roster_rates else 0)
    outlier_high = percentile is not None and percentile >= 90 and spread > 0.10
    outlier_low = percentile is not None and percentile <= 10 and spread > 0.10
    flag = "OVER" if outlier_high else ("UNDER" if outlier_low else "IN_BAND")

    # The recommendation, in plain words with the character's own numbers.
    attr_solo = _attr(subject_runs, 1)
    attr_duo = _attr(subject_runs, 2)
    attr = attr_solo or attr_duo or {}
    solo_screening = screening_table(subject_runs, cid, loadout)
    never_cast = [s["name"] for s in solo_screening if s["games_cast"] == 0]
    granted = (attr.get("mana_granted") or 1)
    waste_share = (attr.get("mana_wasted") or 0) / granted
    dead_share = (attr.get("dead_in_hand") or 0) / max(1, deck_size)
    castability_problem = waste_share >= 0.4 or dead_share >= 0.6
    win_pct = f"{roster_rates[cid]:.0%}"
    contribution = (round(roster_rates[cid] - ally_baseline, 4)
                    if ally_baseline is not None else None)
    parts = []
    if flag == "OVER":
        parts.append(
            f"{cid} tops the roster ({win_pct} across identical solo+duo "
            f"cells, {percentile}th percentile). Before touching the stat "
            "line, probe the top screening cards — a character is usually "
            "carried by one or two of them.")
    elif flag == "UNDER":
        parts.append(
            f"{cid} finished last on the shared cells ({win_pct} vs "
            f"{rates_sorted[0][0]}'s {rates_sorted[0][1]:.0%}).")
        if contribution is not None:
            parts.append(
                f"Beside the vanilla Training Ally, {cid} "
                + (f"adds {contribution:+.0%} over the two-vanilla baseline "
                   f"({ally_baseline:.0%})."
                   if contribution > 0 else
                   f"adds NOTHING over the two-vanilla baseline "
                   f"({ally_baseline:.0%} with two warm bodies vs "
                   f"{roster_rates[cid]:.0%} with {cid} in the pair).")
                )
        if castability_problem:
            parts.append(
                f"The games say WHY: {cid} left "
                f"{attr.get('dead_in_hand', 0):.0f} of {deck_size} cards "
                f"unplayed and wasted {attr.get('mana_wasted', 0):.0f} of "
                f"{attr.get('mana_granted', 0):.0f} mana per game — the kit "
                "is not getting CAST, so buffing card numbers would change "
                "nothing. Look at costs and card types first.")
        else:
            parts.append(
                "Resource use looks normal (mana and cards are being spent), "
                "so the kit is being played and still losing — magnitudes are "
                "a fair lever here.")
    else:
        parts.append(f"{cid} is inside the roster's band ({win_pct}, "
                     f"{percentile}th percentile). No change needed.")
    if never_cast:
        parts.append(
            f"CAVEAT: the {POLICY} stick never plays {len(never_cast)} of the "
            f"{deck_size} cards ({', '.join(never_cast[:4])}"
            + ("…" if len(never_cast) > 4 else "") + ") — their value is "
            "INVISIBLE to this probe; part of any low reading is the bot's "
            "vocabulary, not the character.")
    if spend_audit_meta and spend_audit_meta["no_signal"]:
        parts.append("The spend audit produced no signal on this gauntlet "
                     "(rates saturated/flat) — ignore that table.")
    elif spend_audit:
        ordered = sorted(spend_audit.items(), key=lambda kv: -kv[1])
        if ordered[0][1] - ordered[-1][1] > 0.15:
            parts.append(
                f"Spend audit: {ordered[0][0]} dominates ({ordered[0][1]:.0%} "
                f"vs {ordered[-1][1]:.0%} for {ordered[-1][0]}) — that "
                "implicates the points-buy price table, not this character.")
    recommendation = " ".join(parts)

    verdict = _base_verdict("character", {"character_id": cid},
                            preset_name, preset, gauntlet)
    verdict.update({
        "flag": flag,
        "combo_blind": any(_card_is_combo(c) for c in loadout.get("cards", [])),
        "roster_rates": {k: v for k, v in rates_sorted},
        "roster_solo": roster_solo,
        "roster_duo": roster_duo,
        "ally_baseline": ally_baseline,
        "contribution": contribution,
        "percentile": percentile,
        "heroics": heroics,
        "attribution": {"solo": attr_solo, "duo": attr_duo},
        "deck_size": deck_size,
        "spend_audit": spend_audit,
        "spend_audit_meta": spend_audit_meta,
        "ladder": [],
        "recommendation": recommendation,
        "screening": solo_screening,
        "cells": aggregate(subject_runs)["cells"],
        "duo_cells": None,
    })
    return verdict
