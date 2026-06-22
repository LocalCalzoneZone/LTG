"""Translation registry + effects→text renderer — the shared vocabulary.

Two halves of one round-trip: a registry of deterministic text→effect rules
(`register` / `translate`) and a renderer that turns effects back into
LTG-language text (`render_effects`). No LLM, no Scryfall, no app concerns — the
Scryfall→Card ingestion that *uses* this registry lives in the Deckbuilder app.

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
    AddMana,
    Bounce,
    Counter,
    Ramp,
    DealDamage,
    Destroy,
    Draw,
    Disable,
    Duration,
    Effect,
    Exile,
    GrantKeyword,
    Heal,
    KEYWORDS,
    LoseLife,
    RemoveKeyword,
    Prevent,
    Pump,
    Ref,
    Scry,
    Side,
    TargetMode,
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
@register(r"counter target (?:activated|triggered)(?: or (?:activated|triggered))? abilit")
def _counter_ability(m, ctx):
    return [Counter(filter="ability")]


@register(r"counter target noncreature spell")
def _counter_noncreature(m, ctx):
    return [Counter(filter="spell")]


@register(r"counter target spell")
def _counter_spell(m, ctx):
    # LTG's Counterspell answers any enemy action (spell or ability).
    return [Counter(filter="action")]


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


# --- Granting / removing keywords (names match the registry) --------------- #
# MTG keyword phrasing → registry identifier (multi-word forms first).
_KEYWORD_WORDS = {
    "double strike": "double_strike", "first strike": "first_strike",
    "flying": "flying", "trample": "trample", "deathtouch": "deathtouch",
    "lifelink": "lifelink", "vigilance": "vigilance", "reach": "reach",
    "hexproof": "hexproof", "indestructible": "indestructible",
}


def _grant_target(text: str):
    if "creatures you control" in text or "each creature you control" in text:
        return t_all("ally")
    if "a creature you control" in text or "another creature you control" in text:
        return t_chosen("ally")
    if "target" in text:
        return t_chosen("any", targeted=True)
    return t_chosen("ally")


@register(r"\b(?:gains?|have|has)\b\s+(?:flying|trample|double strike|first strike|deathtouch|lifelink|vigilance|reach|hexproof|indestructible)")
def _grant_keyword(m, ctx):
    text = m.string.lower()
    found = [ident for word, ident in _KEYWORD_WORDS.items()
             if re.search(r"\b" + re.escape(word) + r"\b", text)]
    if not found:
        return []
    return [GrantKeyword(keywords=found, target=_grant_target(text))]


@register(r"loses? all abilities")
def _remove_all(m, ctx):
    text = m.string.lower()
    return [RemoveKeyword(keywords=["all"], target=_grant_target(text))]


# --- Lands → mana capacity (the land names are dropped) -------------------- #
_LAND_COLOR = {"forest": "G", "island": "U", "swamp": "B", "plains": "W", "mountain": "R"}


def land_color(text: str) -> str:
    """Colour a land reference maps to; 'choice' for a generic basic land."""
    low = (text or "").lower()
    for name, color in _LAND_COLOR.items():
        if name in low:
            return color
    return "choice"


@register(
    r"search your library for .*?(?:land|forest|island|swamp|plains|mountain)"
    r".*?(?:onto|to) the battlefield"
)
def _ramp(m, ctx):
    text = m.string
    availability = "tapped" if "tapped" in text else "immediate"
    return [Ramp(amount=1, color=land_color(text), availability=availability)]


@register(r"\badd\b\s*((?:\{[^}]+\})+)")
def _add_mana(m, ctx):
    counts: dict = {}
    for token in re.findall(r"\{([^}]+)\}", m.group(1)):
        c = token.upper()
        if c in {"W", "U", "B", "R", "G"}:
            counts[c] = counts.get(c, 0) + 1
    return [AddMana(amount=n, color=c) for c, n in counts.items()]


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
            key = repr(effect.model_dump(mode="json"))
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
        if v.ref == "mana_capacity":
            return "your mana capacity"
        if v.ref.endswith(".level"):
            return "its Level"
        return v.ref
    return str(v)


def _is_capacity(v) -> bool:
    """True when a value scales by mana capacity ("for each land you control")."""
    return isinstance(v, Ref) and v.ref == "mana_capacity"


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
    if _is_capacity(e.amount):
        body = "1 HP for each point of mana capacity"
    elif isinstance(e.amount, Ref):
        body = "HP equal to " + _value(e.amount)
    else:
        body = f"{e.amount} HP"
    if _is_self(e.target):
        return f"Lose {body}."
    return f"{_tgt(e.target).capitalize()} loses {body}."


_COLOR_WORD = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def _capacity_phrase(e) -> str:
    if e.color == "choice":
        return f"{e.amount} mana capacity of your choice"
    return f"{e.amount} {_COLOR_WORD[e.color]} mana capacity"


def _render_ramp(e) -> str:
    phrase = _capacity_phrase(e)
    if e.availability == "immediate":
        return f"Add {phrase} (usable this turn)."
    if e.availability == "deferred":
        return f"At the start of your next turn, add {phrase}."
    return f"Add {phrase} (not usable this turn)."  # tapped


def _render_add_mana(e) -> str:
    colour = "mana of your choice" if e.color == "choice" else f"{_COLOR_WORD[e.color]} mana"
    return f"Add {e.amount} {colour} to your pool this turn."


# Counter filter → player-facing phrase (filter matches a node + its descendants).
_FILTER_PHRASE = {
    "action": "an enemy action (spell or ability)",
    "spell": "an enemy spell",
    "ability": "an enemy ability (including attacks)",
    "triggered": "an enemy triggered ability",
    "attack": "an enemy attack",
    "activated": "an enemy activated ability",
}


# Keyword grant/remove text — display names + glosses come from the registry.
def _keyword_phrase(keywords, params=None) -> str:
    if keywords == ["all"]:
        return "all abilities"
    names = []
    for k in keywords:
        disp = KEYWORDS.get(k, {}).get("display", k)
        if k == "protection" and params and params.get("from"):
            disp += f" from {params['from']}"
        names.append(disp)
    return _join_and(names)


def _grant_duration(e) -> str:
    dur = getattr(e, "duration", None)
    if dur in (Duration.end_of_turn, Duration.this_turn):
        return " until end of turn"
    if dur == Duration.encounter:
        return " for the encounter"
    return ""  # while_channeled — the channeled prefix carries it


# Modal ("Choose one") and conditional ("If …, …") rendering.
def _condition_phrase(cond) -> str:
    if cond.kind == "cast_mode":
        return "cast as an action" if cond.mode == "action" else "cast as a reaction"
    if cond.property == "has_keyword":
        return f"the target has {KEYWORDS.get(cond.keyword, {}).get('display', cond.keyword)}"
    if cond.property == "side":
        s = cond.side.value if hasattr(cond.side, "value") else cond.side
        return {"ally": "the target is an ally", "enemy": "the target is an enemy"}.get(s, "the target qualifies")
    return "the condition holds"


def _render_modal(e) -> str:
    parts = []
    for m in e.modes:
        label = f"{m.label}: " if m.label else ""
        parts.append(f"• {label}{render_effects(m.effects)}")
    return "Choose one — " + " ".join(parts)


def _render_conditional(e) -> str:
    inner = render_effects(e.effects)
    return f"If {_condition_phrase(e.condition)}, {_lc_first(inner)}"


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
    "deal_damage": lambda e: (
        f"Deal 1 damage to {_tgt(e.target)} for each point of mana capacity."
        if _is_capacity(e.amount) else f"Deal {e.amount} damage to {_tgt(e.target)}."
    ),
    "heal": lambda e: (
        f"Restore 1 HP to {_tgt(e.target)} for each point of mana capacity."
        if _is_capacity(e.amount) else f"Restore {e.amount} HP to {_tgt(e.target)}."
    ),
    "lose_life": lambda e: _render_lose_life(e),
    "destroy": lambda e: f"Destroy {_tgt(e.target)}.",
    "exile": lambda e: f"Exile {_tgt(e.target)}.",
    "bounce": lambda e: f"Return {_tgt(e.target)} to hand.",
    "counter": lambda e: f"Cancel {_FILTER_PHRASE.get(e.filter, 'an enemy ' + str(e.filter))}.",
    "strip_intent": lambda e: f"Remove {_subject(e.target, None, True)}'s telegraphed intent.",
    "stun": lambda e: f"{_subject(e.target, None, True).capitalize()} skips its next intent.",
    "pump": _render_pump,
    "wound": _render_wound,
    "counters": _render_counters,
    "prevent": lambda e: f"Prevent {_value(e.amount)} damage to {_tgt(e.target)}.",
    "protection": lambda e: f"Give {_tgt(e.target)} protection ({e.scope}).",
    "draw": lambda e: (
        "Draw a card for each point of mana capacity." if _is_capacity(e.amount)
        else f"Draw {e.amount} card(s)."
    ),
    "scry": lambda e: (
        "Scry 1 for each point of mana capacity." if _is_capacity(e.amount)
        else f"Scry {e.amount}."
    ),
    "create_token": lambda e: f"Create {e.count} {e.token_id} token(s).",
    "taunt": lambda e: f"Force {_tgt(e.target)} to target you this turn.",
    "disable": lambda e: f"{_tgt(e.target).capitalize()} can't {e.intent_type}.",
    "revive": lambda e: f"Revive {_tgt(e.target)} at {int(e.to_fraction * 100)}% HP.",
    "ramp": _render_ramp,
    "add_mana": _render_add_mana,
    "grant_keyword": lambda e: (
        f"{_subject(e.target).capitalize()} {'gain' if _plural(e.target) else 'gains'} "
        f"{_keyword_phrase(e.keywords, e.params)}{_grant_duration(e)}."
    ),
    "remove_keyword": lambda e: (
        f"{_subject(e.target).capitalize()} {'lose' if _plural(e.target) else 'loses'} "
        f"{_keyword_phrase(e.keywords, e.params)}."
    ),
    "modal": _render_modal,
    "conditional": _render_conditional,
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
    "grant_keyword": lambda e: f"gain {_keyword_phrase(e.keywords, e.params)}",
    "remove_keyword": lambda e: f"lose {_keyword_phrase(e.keywords, e.params)}",
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
    if k == "grant_keyword":
        verb = "have" if _plural(e.target, targets) else "has"
        return f"{_subject(e.target, targets, True)} {verb} {_keyword_phrase(e.keywords, e.params)}"
    if k == "remove_keyword":
        verb = "lose" if _plural(e.target, targets) else "loses"
        return f"{_subject(e.target, targets, True)} {verb} {_keyword_phrase(e.keywords, e.params)}"
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
        article = "an" if token[:1].lower() in "aeiou" else "a"
        return f"create {article} {token} ally" if e.count == 1 else f"create {e.count} {token} allies"
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
    # Continuous (untriggered) effects, one sentence each.
    for e in effects:
        if getattr(e, "trigger", None) is None:
            parts.append("While channeled: " + _channeled_body(e, targets) + ".")
    # Each recurring trigger groups its effects under its own lead-in.
    for trigger, lead in (
        ("upkeep", "At the start of every turn while channeled: "),
        ("capacity_increase", "Whenever your mana capacity increases: "),
    ):
        group = [e for e in effects if getattr(e, "trigger", None) == trigger]
        if group:
            parts.append(lead + _join_and([_upkeep_clause(e, targets) for e in group]) + ".")
    return " ".join(parts)
