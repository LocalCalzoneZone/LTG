"""Validation lints — cheap, non-blocking checks shown while editing.

These are advisory warnings over a *structurally valid* card (the Pydantic
schema is the hard validator). Keep every rule in LINT_RULES so the list is easy
to extend. No app, Scryfall or UI concerns here — only the vocabulary.
"""

from __future__ import annotations

from typing import List

from .schema import Duration, Side, Timing, slot_name


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
        s = slot_name(getattr(e, "target", None))
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
        if not continuous and e.trigger is None:
            out.append(
                f"{e.kind}: on a channeled card, set duration 'while_channeled' "
                f"(continuous) or a trigger (recurring)."
            )
    return out


LINT_RULES = [
    _lint_no_effects,
    _lint_draw_scry_side,
    _lint_exclude_self_on_enemy,
    _lint_counter_timing,
    _lint_amounts,
    _lint_slots,
    _lint_channeled_persistence,
]


def lint_card(card) -> List[str]:
    """Run all lint rules over a (structurally valid) card; return warnings."""
    out = []
    for rule in LINT_RULES:
        out.extend(rule(card))
    return out
