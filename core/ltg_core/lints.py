"""Validation lints — cheap, non-blocking checks shown while editing.

These are advisory warnings over a *structurally valid* card (the Pydantic
schema is the hard validator). Keep every rule in LINT_RULES so the list is easy
to extend. No app, Scryfall or UI concerns here — only the vocabulary.
"""

from __future__ import annotations

from typing import List

from .schema import Duration, Side, TargetMode, Timing, slot_name


def _lint_no_effects(card):
    if not card.effects and len((card.original_text or "").strip()) > 12:
        return ["No effects extracted — translate this card manually."]
    return []


def _lint_draw_scry_side(card):
    # side:enemy is rejected at validation; side:any is merely risky → flag.
    out = []
    for e in card.effects:
        if e.kind in ("draw", "scry"):
            desc = card.resolved_target(e)
            if desc is not None and desc.side == Side.any:
                out.append(f"{e.kind} can target either side — it must resolve to an ally/you.")
    return out


def _lint_exclude_self_on_enemy(card):
    out = []
    descs = list(card.targets.items())
    for e in card.effects:
        t = getattr(e, "target", None)
        if t is not None and not isinstance(t, str):
            descs.append((None, t))
    for name, desc in descs:
        if getattr(desc, "exclude_self", False) and desc.side == Side.enemy:
            where = f"slot {name}" if name else "an effect"
            out.append(f"'exclude_self' on {where} is a no-op (enemy side never includes you).")
    return out


def _lint_counter_timing(card):
    # A counter must be able to respond — i.e. be an instant (instant ⟹ reactive).
    if any(e.kind == "counter" for e in card.effects) and card.timing.value != "instant":
        return ["a counter card should be timing 'instant' so it can respond."]
    return []


def _lint_amounts(card):
    out = []
    for e in card.effects:
        amt = getattr(e, "amount", None)
        if isinstance(amt, int):
            if amt == 0:
                out.append(f"{e.kind}: amount is 0 — did you mean a positive value?")
            elif amt < 0:
                out.append(f"{e.kind}: amount is negative ({amt}).")
        if hasattr(e, "power") and hasattr(e, "toughness") and e.power == 0 and e.toughness == 0:
            out.append(f"{e.kind}: power and toughness are both 0 — no effect.")
    return out


def _lint_slots(card):
    out = []
    declared = set(card.targets.keys())
    referenced = set()
    for e in card.effects:
        # Every target-bearing field counts (fight references two: target + other).
        for attr in ("target", "other"):
            s = slot_name(getattr(e, attr, None))
            if s is not None:
                referenced.add(s)
                if s not in declared:
                    out.append(f"effect references undeclared slot ${s}.")
    for s in sorted(declared - referenced):
        out.append(f"slot {s} is declared but never used.")
    return out


def _lint_channeled_persistence(card):
    # On a channeled card every effect should be continuous or recurring.
    if card.timing != Timing.channeled:
        return []
    out = []
    for e in card.effects:
        continuous = getattr(e, "duration", None) == Duration.while_channeled
        if continuous or e.trigger is not None:
            continue
        # Only effects that carry a `duration` field can be made continuous; the rest
        # (e.g. destroy, bounce, stun) can only persist via a recurring trigger.
        if "duration" in type(e).model_fields:
            out.append(
                f"{e.kind}: on a channeled card, set duration 'while_channeled' "
                f"(continuous) or a trigger (recurring)."
            )
        else:
            out.append(
                f"{e.kind}: on a channeled card, set a trigger (recurring) — "
                f"'{e.kind}' has no continuous (while_channeled) form."
            )
    return out


def _resolved_side(card, target):
    """The Side of a target descriptor or slot ref, or None if not determinable."""
    name = slot_name(target)
    desc = card.targets.get(name) if name is not None else (
        target if not isinstance(target, str) else None)
    return getattr(desc, "side", None)


def _lint_fight_sides(card):
    # A fight pits a creature you control against one you don't — the two targets
    # should sit on opposite sides (GDD §7).
    out = []
    for e in card.effects:
        if getattr(e, "kind", None) != "fight":
            continue
        a = _resolved_side(card, getattr(e, "target", None))
        b = _resolved_side(card, getattr(e, "other", None))
        if a is not None and b is not None and a == b and a != Side.any:
            out.append("fight: the two creatures should be on opposite sides "
                       "(target a creature you control vs one you don't).")
    return out


def _lint_independent_inline_targets(card):
    # Each effect that builds its OWN inline "chosen" target resolves independently
    # — the player picks a creature per effect. Two or more of these on one card is
    # almost always a mis-author: "target creature gets +2/+2 AND gains lifelink"
    # means ONE creature, not two. Shared slots make the intent explicit — link
    # every such effect to the SAME slot ($T1) for one shared target, or to DISTINCT
    # slots ($T1, $T2) when the targets are genuinely meant to differ (e.g. Agony
    # Warp). `fight` is exempt (its two targets are intentionally distinct).
    inline = sum(
        1 for e in card.effects
        if e.kind not in ("modal", "conditional", "fight")
        and (t := getattr(e, "target", None)) is not None
        and not isinstance(t, str)
        and getattr(t, "mode", None) == TargetMode.chosen
        and getattr(t, "targeted", False)
    )
    if inline >= 2:
        return [f"{inline} effects each choose their own target independently — if "
                f"they should hit the SAME creature, link them to one shared slot "
                f"($T1 on each); use distinct slots only when the targets differ."]
    return []


LINT_RULES = [
    _lint_no_effects,
    _lint_draw_scry_side,
    _lint_exclude_self_on_enemy,
    _lint_counter_timing,
    _lint_amounts,
    _lint_slots,
    _lint_channeled_persistence,
    _lint_fight_sides,
    _lint_independent_inline_targets,
]


def lint_card(card) -> List[str]:
    """Run all lint rules over a (structurally valid) card; return warnings."""
    out = []
    for rule in LINT_RULES:
        out.extend(rule(card))
    return out
