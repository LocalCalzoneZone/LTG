"""Translation registry + effects→text renderer + Scryfall→Card builder.

Deterministic and manual: where a rule recognizes oracle text it fills `effects`
and renders `translated_text`; otherwise the card is left blank and flagged
`needs_translation` for the user to author by hand. No LLM here.

To add a translation mapping:
    @register(r"counter target spell")
    def _(m, ctx):
        return [CounterIntent()]
That single registration call is the whole change.

To add text for a new effect primitive: add one entry to RENDERERS.
"""

from __future__ import annotations

import re
from typing import Callable, List, Tuple

from .schema import (
    Bounce,
    Card,
    CounterIntent,
    Cost,
    DealDamage,
    Destroy,
    Draw,
    Disable,
    Duration,
    Effect,
    Exile,
    Heal,
    LoseLife,
    Prevent,
    Pump,
    Ref,
    Scry,
    Side,
    TargetDescriptor,
    TargetMode,
    Timing,
    Wound,
    slot_name,
    t_all,
    t_chosen,
    t_self,
)

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
Builder = Callable[[re.Match, dict], List[Effect]]
_REGISTRY: List[Tuple[re.Pattern, Builder]] = []


def register(pattern: str) -> Callable[[Builder], Builder]:
    """Register a regex → effect-builder rule. One call == one mapping."""

    compiled = re.compile(pattern, re.IGNORECASE)

    def wrap(fn: Builder) -> Builder:
        _REGISTRY.append((compiled, fn))
        return fn

    return wrap


# --- Seed mappings (the clear, deterministic ones) ------------------------- #
# Targets are descriptors. `targeted=True` whenever the matched phrasing uses the
# word "target" (per the targeting-model brief); friendly/either targets still
# carry it so the engine can honour hexproof/shroud later.
@register(r"counter target spell")
def _counter_spell(m, ctx):
    return [CounterIntent(target=t_chosen("enemy", targeted=True))]


@register(r"destroy target (?:creature|permanent|enchantment)")
def _destroy(m, ctx):
    return [Destroy(target=t_chosen("any", targeted=True))]


@register(r"exile target (?:creature|permanent|enchantment)")
def _exile(m, ctx):
    return [Exile(target=t_chosen("any", targeted=True))]


@register(r"return target [\w\s]+? to (?:its owner's|their owner's|owner's) hand")
def _bounce(m, ctx):
    return [Bounce(target=t_chosen("any", targeted=True))]


@register(r"draws? (\w+) cards?")
def _draw(m, ctx):
    return [Draw(amount=_word_to_int(m.group(1)), target=t_self())]


@register(r"lose life equal to")
def _lose_life_equal(m, ctx):
    return [LoseLife(amount=Ref(ref="destroyed_target.level"), target=t_self())]


@register(r"loses? (\w+) life")
def _lose_life_amount(m, ctx):
    return [LoseLife(amount=_word_to_int(m.group(1)), target=t_self())]


@register(r"target creature gets ([+\-−]\d+)/([+\-−]\d+)|([+\-−]\d+)/([+\-−]\d+)")
def _stat_change(m, ctx):
    def num(tok: str) -> int:
        return int(tok.replace("−", "-"))

    groups = [g for g in m.groups() if g is not None]
    power, toughness = num(groups[0]), num(groups[1])
    # "target creature gets" is targeted and either-side; bare +X/+X likewise.
    if power >= 0 and toughness >= 0:
        return [Pump(power=power, toughness=toughness, target=t_chosen("any", targeted=True))]
    return [Wound(power=abs(power), toughness=abs(toughness), target=t_chosen("any", targeted=True))]


@register(r"prevent .* damage|^fog\b|prevent all combat damage")
def _prevent(m, ctx):
    return [Prevent(amount="all", target=t_all("ally"))]


@register(r"scry (\w+)")
def _scry(m, ctx):
    return [Scry(amount=_word_to_int(m.group(1)), target=t_self())]


@register(r"deals? (\d+) damage")
def _deal_damage(m, ctx):
    return [DealDamage(amount=int(m.group(1)), target=t_chosen("enemy", targeted=True))]


@register(r"gains? (\w+) life")
def _gain_life(m, ctx):
    return [Heal(amount=_word_to_int(m.group(1)), target=t_chosen("ally"))]


@register(r"can't attack(?: or block)?")
def _pacify(m, ctx):
    return [Disable(intent_type="attack", target=t_chosen("enemy", targeted=True))]


def _word_to_int(token: str) -> int:
    words = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    token = token.lower()
    if token.isdigit():
        return int(token)
    return words.get(token, 1)


def translate(oracle_text: str, ctx: dict) -> List[Effect]:
    """Run every registered rule over the text; collect matched effects in order."""
    effects: List[Effect] = []
    seen_kinds = set()
    for pattern, builder in _REGISTRY:
        match = pattern.search(oracle_text or "")
        if not match:
            continue
        for effect in builder(match, ctx):
            key = (effect.kind, repr(getattr(effect, "target", None)))
            if key in seen_kinds:
                continue
            seen_kinds.add(key)
            effects.append(effect)
    return effects


# --------------------------------------------------------------------------- #
# Renderer (effects → LTG-language text)
# --------------------------------------------------------------------------- #
# Noun by side for `chosen` targets; the article/another is added by describe().
_SIDE_NOUN = {Side.ally: "ally", Side.enemy: "enemy", Side.any: "target"}


def describe_target(desc, channeled: bool = False) -> str:
    """Render a TargetDescriptor (or slot-ref string) as a lowercase phrase.

    On channeled cards a `chosen` target is fixed at cast, so it reads as a
    definite "the chosen ally/enemy" rather than the indefinite "an ally".
    """
    if isinstance(desc, str):  # an unresolved "$slot" ref
        return desc
    if desc.mode == TargetMode.self_:
        return "yourself"
    if desc.mode == TargetMode.all:
        noun = {Side.ally: "all allies", Side.enemy: "all enemies", Side.any: "everyone"}[desc.side]
        return ("all other " + noun.split(" ", 1)[1]) if desc.exclude_self and desc.side != Side.enemy else noun
    # chosen
    noun = _SIDE_NOUN[desc.side]
    if channeled:
        return f"the chosen {noun}"
    article = "another" if desc.exclude_self else ("an" if noun[0] in "aeiou" else "a")
    return f"{article} {noun}"


def _is_self(t) -> bool:
    return not isinstance(t, str) and getattr(t, "mode", None) == TargetMode.self_


def _resolve(target, targets):
    """Resolve a target (descriptor or slot ref) to a descriptor, or None."""
    s = slot_name(target)
    if s is not None:
        return (targets or {}).get(s)
    return target if not isinstance(target, str) else None


def _subject(target, targets=None, channeled=False) -> str:
    desc = _resolve(target, targets)
    return describe_target(desc, channeled) if desc is not None else str(target)


def _plural(target, targets=None) -> bool:
    return getattr(_resolve(target, targets), "mode", None) == TargetMode.all


def _tgt(t) -> str:
    return describe_target(t)


def _value(v) -> str:
    if isinstance(v, Ref):
        if v.ref.endswith(".level"):
            return "its Level"
        return v.ref
    return str(v)


def _duration_suffix(e) -> str:
    dur = getattr(e, "duration", None)
    if dur in (Duration.this_turn, Duration.end_of_turn):
        return " this turn"
    if dur == Duration.encounter:
        return " for the encounter"
    return ""  # while_channeled (channeled prefix handles it) or no duration


def _lc_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def _render_lose_life(e) -> str:
    amount_phrase = "HP equal to " + _value(e.amount) if isinstance(e.amount, Ref) else f"{e.amount} HP"
    if _is_self(e.target):
        return f"Lose {amount_phrase}."
    return f"{_tgt(e.target).capitalize()} loses {amount_phrase}."


# Power/toughness convention: power → "attack", toughness → "temp HP" (buff) / "HP" (debuff).
def _render_pump(e) -> str:
    verb = "gain" if _plural(e.target) else "gains"
    return f"{_subject(e.target).capitalize()} {verb} +{e.power} attack and +{e.toughness} temp HP{_duration_suffix(e)}."


def _render_wound(e) -> str:
    verb = "have" if _plural(e.target) else "has"
    return f"{_subject(e.target).capitalize()} {verb} -{e.power} attack and -{e.toughness} HP{_duration_suffix(e)}."


def _render_counters(e) -> str:
    verb = "gain" if _plural(e.target) else "gains"
    return f"{_subject(e.target).capitalize()} {verb} +{e.power}/+{e.toughness}{_duration_suffix(e) or ' for the encounter'}."


RENDERERS = {
    "deal_damage": lambda e: f"Deal {e.amount} damage to {_tgt(e.target)}.",
    "heal": lambda e: f"Restore {e.amount} HP to {_tgt(e.target)}.",
    "lose_life": lambda e: _render_lose_life(e),
    "destroy": lambda e: f"Destroy {_tgt(e.target)}.",
    "exile": lambda e: f"Exile {_tgt(e.target)}.",
    "bounce": lambda e: f"Return {_tgt(e.target)} to hand.",
    "counter_intent": lambda e: f"Counter {_tgt(e.target)}.",
    "strip_intent": lambda e: f"Strip {_tgt(e.target)}.",
    "stun": lambda e: f"Stun {_tgt(e.target)} for {e.intents} intent(s).",
    "pump": _render_pump,
    "wound": _render_wound,
    "counters": _render_counters,
    "prevent": lambda e: f"Prevent {_value(e.amount)} damage to {_tgt(e.target)}.",
    "protection": lambda e: f"Give {_tgt(e.target)} protection ({e.scope}).",
    "draw": lambda e: f"Draw {e.amount} card(s).",
    "scry": lambda e: f"Scry {e.amount}.",
    "create_token": lambda e: f"Create {e.count} {e.token_id} token(s).",
    "taunt": lambda e: f"Force {_tgt(e.target)} to target you this turn.",
    "disable": lambda e: f"{_tgt(e.target).capitalize()} can't {e.intent_type}.",
    "revive": lambda e: f"Revive {_tgt(e.target)} at {int(e.to_fraction * 100)}% HP.",
}


def _render_one(e) -> str:
    r = RENDERERS.get(e.kind)
    return r(e) if r else e.kind


# Subjectless verb phrases for shared-target ("Choose X: they …") sentences.
_CLAUSE = {
    "draw": lambda e: f"draw {e.amount}",
    "scry": lambda e: f"scry {e.amount}",
    "heal": lambda e: f"heal {e.amount}",
    "deal_damage": lambda e: f"take {e.amount} damage",
    "lose_life": lambda e: (
        f"lose HP equal to {_value(e.amount)}"
        if isinstance(e.amount, Ref)
        else f"lose {e.amount} HP"
    ),
    "pump": lambda e: f"gain +{e.power}/+{e.toughness} this turn",
    "wound": lambda e: f"suffer -{e.power}/-{e.toughness} this turn",
    "destroy": lambda e: "are destroyed",
    "exile": lambda e: "are exiled",
    "bounce": lambda e: "are returned to hand",
    "stun": lambda e: f"are stunned for {e.intents} intent(s)",
}


def _clause(e) -> str:
    fn = _CLAUSE.get(e.kind)
    if fn:
        return fn(e)
    return RENDERERS.get(e.kind, lambda x: e.kind)(e).rstrip(".").lower()


def render_effects(effects: List[Effect], targets=None, channeled: bool = False) -> str:
    """Render effects into LTG-language text.

    On `channeled` cards each effect reads as ongoing: continuous effects lead
    with "While channeled: " and upkeep effects with "At the start of each of your
    turns while channeled: ". Otherwise, shared-target slots are grouped into a
    single "Choose X: they …" sentence.
    """
    targets = targets or {}
    if channeled:
        return _render_channeled(effects, targets)

    handled = set()
    parts = []

    # One sentence per shared-target slot (in first-appearance order).
    seen_slots = []
    for e in effects:
        s = slot_name(getattr(e, "target", None))
        if s and s not in seen_slots:
            seen_slots.append(s)
    for s in seen_slots:
        group = [e for e in effects if slot_name(getattr(e, "target", None)) == s]
        for e in group:
            handled.add(id(e))
        slot_type = targets.get(s)
        phrase = _tgt(slot_type) if slot_type is not None else f"${s}"
        clauses = [_clause(e) for e in group]
        parts.append(f"Choose {phrase}: they " + ", then ".join(clauses) + ".")

    # Then the direct-target effects, in order.
    for e in effects:
        if id(e) in handled:
            continue
        renderer = RENDERERS.get(e.kind)
        if renderer:
            parts.append(renderer(e))
    return " ".join(parts)


# --- Channeled (enchantment) rendering ------------------------------------- #
def _join_and(items: List[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _channeled_body(e, targets) -> str:
    """An ongoing (continuous) effect's body — lowercase subject, no period."""
    k = e.kind
    if k in ("pump", "counters"):
        verb = "gain" if _plural(e.target, targets) else "gains"
        return f"{_subject(e.target, targets, True)} {verb} +{e.power} attack and +{e.toughness} temp HP"
    if k == "wound":
        verb = "have" if _plural(e.target, targets) else "has"
        return f"{_subject(e.target, targets, True)} {verb} -{e.power} attack and -{e.toughness} HP"
    if k == "disable":
        return f"{_subject(e.target, targets, True)} can't {e.intent_type}"
    if k == "taunt":
        return f"{_subject(e.target, targets, True)} must target you"
    if k == "prevent":
        return f"prevent {_value(e.amount)} damage to {_subject(e.target, targets, True)}"
    if k == "protection":
        return f"{_subject(e.target, targets, True)} has protection"
    if k == "stun":
        return f"{_subject(e.target, targets, True)} is stunned"
    return _lc_first(_render_one(e).rstrip("."))


def _upkeep_clause(e, targets) -> str:
    """A recurring (upkeep) effect's body — imperative, lowercase, no period."""
    k = e.kind
    if k == "create_token":
        token = e.token_id.replace("_", " ").title()
        return f"create a {token} ally" if e.count == 1 else f"create {e.count} {token} allies"
    if k == "lose_life":
        amt = _value(e.amount) if isinstance(e.amount, Ref) else e.amount
        if _is_self(_resolve(e.target, targets) or e.target):
            return f"lose {amt} HP"
        return f"{_subject(e.target, targets, True)} loses {amt} HP"
    if k == "draw":
        return f"draw {e.amount}"
    if k == "scry":
        return f"scry {e.amount}"
    if k == "heal":
        return f"restore {e.amount} HP to {_subject(e.target, targets, True)}"
    if k == "deal_damage":
        return f"deal {e.amount} damage to {_subject(e.target, targets, True)}"
    return _lc_first(_render_one(e).rstrip("."))


def _render_channeled(effects, targets) -> str:
    parts = []
    for e in effects:
        if getattr(e, "trigger", None) != "upkeep":
            parts.append("While channeled: " + _channeled_body(e, targets) + ".")
    upkeep = [e for e in effects if getattr(e, "trigger", None) == "upkeep"]
    if upkeep:
        clauses = [_upkeep_clause(e, targets) for e in upkeep]
        parts.append("At the start of each of your turns while channeled: " + _join_and(clauses) + ".")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Validation lints — cheap, non-blocking checks shown while editing.
# Keep every rule in LINT_RULES so the list is easy to extend.
# --------------------------------------------------------------------------- #
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


def _lint_counter_reactive(card):
    if any(e.kind == "counter_intent" for e in card.effects) and not card.reactive:
        return ["counter_intent present but card is not reactive — it likely should be."]
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
        if not continuous and e.trigger != "upkeep":
            out.append(
                f"{e.kind}: on a channeled card, set duration 'while_channeled' "
                f"(continuous) or trigger 'upkeep' (recurring)."
            )
    return out


LINT_RULES = [
    _lint_no_effects,
    _lint_draw_scry_side,
    _lint_exclude_self_on_enemy,
    _lint_counter_reactive,
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


# --------------------------------------------------------------------------- #
# Scryfall → Card
# --------------------------------------------------------------------------- #
_MANA_TOKEN = re.compile(r"\{([^}]+)\}")
_COLOR_LETTERS = {"W", "U", "B", "R", "G"}

# Scryfall has rarities beyond the four LTG cares about (e.g. "special",
# "bonus"). Fold those onto the nearest LTG rarity instead of rejecting the card.
_RARITY_MAP = {
    "common": "common",
    "uncommon": "uncommon",
    "rare": "rare",
    "mythic": "mythic",
    "special": "rare",
    "bonus": "mythic",
}


def normalize_rarity(rarity: str) -> str:
    return _RARITY_MAP.get((rarity or "").lower(), "rare")


# Card types LTG does not accept into a loadout (spells only — no permanents
# that would become board state). Add is rejected if the type line names any.
FORBIDDEN_TYPES = ("Land", "Planeswalker", "Creature", "Artifact")


def forbidden_type(type_line: str) -> str | None:
    """Return the first forbidden type present in the type line, else None."""
    tokens = re.findall(r"[A-Za-z]+", type_line or "")
    for forbidden in FORBIDDEN_TYPES:
        if forbidden in tokens:
            return forbidden
    return None


def parse_mana_cost(mana_cost: str) -> Cost:
    """'{1}{B}' -> Cost(generic=1, colors={B:1}). Hybrids/X ignored for now."""
    generic = 0
    colors: dict = {}
    for token in _MANA_TOKEN.findall(mana_cost or ""):
        if token.isdigit():
            generic += int(token)
        elif token in _COLOR_LETTERS:
            colors[token] = colors.get(token, 0) + 1
    return Cost(generic=generic, colors=colors)


def derive_timing(type_line: str) -> Timing:
    t = (type_line or "").lower()
    if "instant" in t:
        return Timing.instant
    if "enchantment" in t:
        return Timing.channeled
    return Timing.sorcery


def slugify(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def build_card(scryfall_json: dict) -> Card:
    """Map a Scryfall card payload onto a Card, best-effort translating it."""
    source_name = scryfall_json["name"]
    oracle_text = scryfall_json.get("oracle_text", "") or ""
    type_line = scryfall_json.get("type_line", "")

    effects = translate(oracle_text, {"source": scryfall_json})
    timing = derive_timing(type_line)
    reactive = any(e.kind in ("counter_intent", "strip_intent") for e in effects)

    # On channeled (enchantment) cards, a static effect with a duration field is
    # continuous: make it `while_channeled` so it reads and validates as ongoing.
    if timing == Timing.channeled:
        for e in effects:
            if hasattr(e, "duration") and e.trigger is None:
                e.duration = Duration.while_channeled

    translated = render_effects(effects, channeled=(timing == Timing.channeled))

    return Card(
        id=slugify(source_name),
        name=source_name,
        source_name=source_name,
        rarity=normalize_rarity(scryfall_json.get("rarity", "common")),
        level=int(scryfall_json.get("cmc", 0) or 0),
        type=type_line,
        cost=parse_mana_cost(scryfall_json.get("mana_cost", "")),
        timing=timing,
        reactive=reactive,
        original_text=oracle_text,
        translated_text=translated,
        effects=effects,
        needs_translation=len(effects) == 0,
    )
