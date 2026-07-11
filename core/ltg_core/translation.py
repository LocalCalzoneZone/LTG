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

import contextvars
import re
from typing import Callable, List, Tuple

from .schema import (
    AddMana,
    Bounce,
    Control,
    Counter,
    Ramp,
    DealDamage,
    Destroy,
    Draw,
    Duration,
    Effect,
    EventTrigger,
    Exile,
    GrantKeyword,
    Heal,
    KEYWORDS,
    LoseLife,
    RemoveKeyword,
    Prevent,
    Pump,
    Ref,
    STANCE_SLOTS,
    Scry,
    Side,
    TargetDescriptor,
    TargetMode,
    TargetState,
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


@register(r"counter target (?:instant|noncreature) spell")
def _counter_spell_only(m, ctx):
    # Spell-only counters (Negate, Dispel): enemy components flagged
    # `action_type: "spell"` (Fireball, Psionic Lance …) land on the stack as
    # kind "spell" and are exactly what these answer — nothing physical.
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
    return [Prevent(parameter="combat_damage", target=t_all("ally"))]


@register(r"scry (\w+)")
def _scry(m, ctx):
    return [Scry(amount=_word_to_int(m.group(1)), target=t_self())]


@register(r"deals? (\d+) damage")
def _deal_damage(m, ctx):
    return [DealDamage(amount=int(m.group(1)), target=t_chosen("enemy", targeted=True))]


@register(r"gains? (\w+) life")
def _gain_life(m, ctx):
    return [Heal(amount=_word_to_int(m.group(1)), target=t_chosen("ally"))]


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


# --- Control / necromancy (Design Update 09 §D9-1.4) ----------------------- #
@register(r"gain control of (?:target|enchanted|another target) creature")
def _control(m, ctx):
    # Act of Treason → control {turns: 1}; Mind Control → control "encounter".
    turns = 1 if "until end of turn" in m.string.lower() else None
    return [Control(target=t_chosen("enemy", targeted=True), turns=turns)]


@register(r"(?:return|put) target creature card from (?:a|your|an opponent's) graveyard "
          r"(?:to|onto) the battlefield")
def _raise_dead(m, ctx):
    # Raise Dead / Animate Dead / Reanimate → control on a corpse (§D9-1.4).
    target = TargetDescriptor(mode=TargetMode.chosen, side=Side.enemy,
                              targeted=True, state=TargetState.corpse)
    return [Control(target=target)]


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
# The card's shared-target slots for the render in progress. The RENDERERS are
# plain `e -> str` functions, so container effects (modal/conditional) recurse
# through render_effects without a `targets` argument; this context var lets those
# nested renders inherit the outer slot table so "$T1" resolves to its description
# instead of leaking the raw slot ref.
_RENDER_TARGETS = contextvars.ContextVar("ltg_render_targets", default={})


# Noun by side for `chosen` targets; the article/another is added by describe().
_SIDE_NOUN = {Side.ally: "ally", Side.enemy: "enemy", Side.any: "target"}

_ROW_WORD = {"front": "front", "mid": "mid", "rear": "rear"}


def _rows_phrase(rows) -> str:
    names = [_ROW_WORD.get(getattr(r, "value", r), str(r)) for r in rows]
    if len(names) == 1:
        return f"the {names[0]} row"
    return "the " + " or ".join(names) + " rows"


def _scope_suffix(desc) -> str:
    """The splash rider on a chosen target (§D9-3.2)."""
    scope = getattr(desc, "scope", None)
    scope = getattr(scope, "value", scope)
    if scope == "row":
        return " and its whole row"
    if scope == "blast":
        return " and its row plus adjacent rows"
    return ""


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
        out = ("all other " + noun.split(" ", 1)[1]) if desc.exclude_self and desc.side != Side.enemy else noun
        if getattr(desc, "rows", None):
            out += f" in {_rows_phrase(desc.rows)}"
        return out
    # chosen
    noun = _SIDE_NOUN[desc.side]
    state = getattr(desc, "state", None)
    state = getattr(state, "value", state)
    if state == "corpse":
        noun = f"{noun} corpse" if desc.side != Side.any else "corpse"
    elif state == "any":
        noun += " (living or dead)"
    if channeled:
        return f"the chosen {noun}" + _scope_suffix(desc)
    article = "another" if desc.exclude_self else ("an" if noun[0] in "aeiou" else "a")
    return f"{article} {noun}" + _scope_suffix(desc)


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
        if v.ref == "x":
            return "X"
        if v.ref == "party_size":
            return "the party size"
        if v.ref == "caster_power":
            return "your Power"
        if v.ref == "caster_hp":
            return "your current HP"
        if v.ref == "target_power":
            return "its Power"
        if v.ref == "target_hp":
            return "its current HP"
        if v.ref == "casting_cost":
            return "its casting cost"
        if v.ref.endswith(".level"):
            return "its Level"
        return v.ref
    return str(v)


def _is_capacity(v) -> bool:
    """True when a value scales by mana capacity ("for each land you control")."""
    return isinstance(v, Ref) and v.ref == "mana_capacity"


def _duration_suffix(e) -> str:
    dur = getattr(e, "duration", None)
    if dur == Duration.this_turn:
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


def _prevent_phrase(parameter: str) -> str:
    """A `prevent [parameter]` nullification, in player-facing words (R-11)."""
    return {"combat_damage": "combat damage", "damage": "damage",
            "all": "damage", "attack": "attacks"}.get(parameter, parameter.replace("_", " "))


def _render_prevent(e) -> str:
    """A full `prevent` sentence that spells out its span so an "all this turn"
    shield (Fog) never reads the same as a one-shot (Gods Willing) — R-11."""
    if e.parameter in ("attack",):  # an action shield, not damage prevention
        return f"{_tgt(e.target).capitalize()} can't attack."
    phrase = _prevent_phrase(e.parameter)
    if getattr(e, "uses", "all") == "next":
        return f"Prevent the next {phrase} to {_tgt(e.target)}."
    return f"Prevent all {phrase} this turn to {_tgt(e.target)}."


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
    if dur == Duration.this_turn:
        return " until end of turn"
    if dur == Duration.encounter:
        return " for the encounter"
    return ""  # while_channeled — the channeled prefix carries it


# Modal ("Choose one") and conditional ("If …, …") rendering.
def _condition_phrase(cond) -> str:
    if cond.kind == "cast_mode":
        return "cast as an action" if cond.mode == "action" else "cast as a reaction"
    if cond.kind == "caster_property":
        if cond.property == "row":
            row = cond.row.value if hasattr(cond.row, "value") else cond.row
            return f"you are in the {row} row"
        if cond.property == "has_keyword":
            return f"you have {KEYWORDS.get(cond.keyword, {}).get('display', cond.keyword)}"
        return "you are channeling"
    if cond.kind == "self_hp":
        rel = "or less" if getattr(cond, "compare", "or_less") == "or_less" else "or more"
        return f"your HP is {cond.percent}% of your maximum {rel}"
    if cond.kind == "enemy_count":
        return {
            "more": "the enemies outnumber your party",
            "equal": "the enemies and your party are equal in number",
            "fewer": "your party outnumbers the enemies",
        }.get(getattr(cond, "compare", "more"), "the enemies outnumber your party")
    if cond.kind == "spells_cast":
        suffix = {"or_more": " or more", "or_less": " or fewer"}.get(
            getattr(cond, "compare", "or_more"), "")
        noun = "spell" if cond.count == 1 and not suffix else "spells"
        return f"you have cast {_count_word(cond.count)}{suffix} {noun} this turn"
    if cond.property == "has_keyword":
        return f"the target has {KEYWORDS.get(cond.keyword, {}).get('display', cond.keyword)}"
    if cond.property == "side":
        s = cond.side.value if hasattr(cond.side, "value") else cond.side
        return {"ally": "the target is an ally", "enemy": "the target is an enemy"}.get(s, "the target qualifies")
    if cond.property == "level":
        suffix = {"or_more": " or more", "or_less": " or less"}.get(getattr(cond, "compare", "exactly"), "")
        return f"the target is level {cond.level}{suffix}"
    if cond.property == "row":
        row = cond.row.value if hasattr(cond.row, "value") else cond.row
        return f"the target is in the {row} row"
    if cond.property == "is_dead":
        return "the target is dead (a corpse)"
    return "the condition holds"


def _token_phrase(e) -> str:
    """'a 2/3 Wisp ally with flying' / '2 2/3 Wisp allies' — name, stats, keywords.

    Stats are omitted when the effect leaves them to the scenario's token def.
    """
    name = e.token_id.replace("_", " ").title()
    stats = f"{e.power}/{e.hp} " if e.power is not None and e.hp is not None else ""
    kw = f" with {_keyword_phrase(e.keywords)}" if getattr(e, "keywords", None) else ""
    if e.count == 1:
        return f"a {stats}{name} ally{kw}"
    return f"{e.count} {stats}{name} allies{kw}"


_NUM_WORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine"}


def _count_word(n: int) -> str:
    return _NUM_WORD.get(n, str(n))


def _render_modal(e) -> str:
    targets = _RENDER_TARGETS.get()
    parts = []
    for m in e.modes:
        label = f"{m.label}: " if m.label else ""
        parts.append(f"• {label}{render_effects(m.effects, targets)}")
    choose = _count_word(getattr(e, "choose", 1))
    if getattr(e, "or_more", False):
        choose += " or more"
    return f"Choose {choose} — " + " ".join(parts)


# --------------------------------------------------------------------------- #
# move_card rendering — phrase a zone move from source + destination + filter.
_MOVE_DEST_PHRASE = {
    "hand": "into your hand",
    "library_top": "on top of your library",
    "library_bottom": "on the bottom of your library",
    "library_shuffle": "shuffled into your library",
    "graveyard": "into your graveyard",
    "exile": "into exile",
}
_MOVE_TYPE_WORD = {"instant": "instant", "sorcery": "sorcery", "channeled": "channeled"}


def _move_level_suffix(e) -> str:
    if e.filter_level_compare == "any":  # "any level" → no level filter
        return ""
    rel = {"or_more": " or more", "or_less": " or less"}.get(e.filter_level_compare, "")
    return f" of level {e.filter_level}{rel}"


def _move_search_object(e) -> str:
    """The thing a library search looks for, e.g. 'an instant', 'a card of level 2 or more'."""
    t = _MOVE_TYPE_WORD.get(e.filter_type)
    base = {"instant": "an instant", "sorcery": "a sorcery",
            "channeled": "a channeled card"}.get(e.filter_type, "a card")
    return base + _move_level_suffix(e)


def _move_noun(e, n: int) -> str:
    """The card noun for a non-search source, e.g. '1 instant card', '2 cards of level 3 or less'."""
    t = _MOVE_TYPE_WORD.get(e.filter_type)
    noun = f"{t} card" if t else "card"
    if n != 1:
        noun += "s"
    return noun + _move_level_suffix(e)


def _render_move_card(e) -> str:
    n = e.count
    dest = _MOVE_DEST_PHRASE.get(e.destination, "into your hand")
    if e.source == "library":  # search anywhere → tutor
        pronoun = "it" if n == 1 else "them"
        obj = _move_search_object(e) if n == 1 else f"{n} {_move_noun(e, n)}"
        body = f"Search your library for {obj}, put {pronoun} {dest}"
    else:
        place = "top" if e.source == "library_top" else "bottom"
        src = {
            "drawn": f"{n} of the drawn cards",
            "hand": f"{n} {_move_noun(e, n)} from your hand",
            "graveyard": f"{n} {_move_noun(e, n)} from your graveyard",
            "exile": f"{n} {_move_noun(e, n)} from exile",
            "library_top": f"the {place} {n} card{'s' if n != 1 else ''} of your library",
            "library_bottom": f"the {place} {n} card{'s' if n != 1 else ''} of your library",
        }.get(e.source, f"{n} {_move_noun(e, n)}")
        body = f"Put {src} {dest}"
    # 'shuffled into your library' already implies the shuffle; don't say it twice.
    if e.shuffle_after and e.destination != "library_shuffle":
        body += ", then shuffle your library"
    return body + "."


def _target_condition_qualifier(cond) -> str:
    """A noun-phrase qualifier for a target_property condition — the bit that
    attaches to 'a target' so the SAME target is clearly meant (not a new one)."""
    if cond.property == "has_keyword":
        return f"with {KEYWORDS.get(cond.keyword, {}).get('display', cond.keyword).lower()}"
    if cond.property == "level":
        suffix = {"or_more": " or more", "or_less": " or less"}.get(getattr(cond, "compare", "exactly"), "")
        return f"with level {cond.level}{suffix}"
    if cond.property == "side":
        s = cond.side.value if hasattr(cond.side, "value") else cond.side
        return {"ally": "that is an ally", "enemy": "that is an enemy"}.get(s, "that qualifies")
    if cond.property == "row":
        row = cond.row.value if hasattr(cond.row, "value") else cond.row
        return f"in the {row} row"
    return "that qualifies"


def _targets_external(effect) -> bool:
    """True when an effect acts on a chosen/external target (not 'self') — i.e. the
    'a target' that a target_property qualifier can attach to."""
    tgt = getattr(effect, "target", None)
    if tgt is None:
        return False
    if isinstance(tgt, str):  # "$slot" ref — a shared chosen target
        return True
    mode = getattr(tgt, "mode", None)
    mode = mode.value if hasattr(mode, "value") else mode
    return mode != "self"


# target_property conditions with a natural noun-phrase qualifier ("a target
# with flying"). Anything else — is_dead included — reads clearer as the plain
# "If <condition>, <effect>." form, so a player always sees the condition.
_QUALIFIER_PROPERTIES = ("has_keyword", "level", "side", "row")


def _render_conditional(e) -> str:
    inner = render_effects(e.effects, _RENDER_TARGETS.get())
    # A target_property condition qualifies the SAME target the effect already
    # acts on, so phrase it as "<effect> a target with <condition>." rather than
    # "If the target …, <effect> a target." (which reads as two distinct targets).
    # Only when the effect actually has an external target; cast-mode conditions
    # (and target-less effects) keep the "If …" form.
    if (getattr(e.condition, "kind", None) == "target_property"
            and getattr(e.condition, "property", None) in _QUALIFIER_PROPERTIES
            and e.effects and _targets_external(e.effects[-1])):
        body = inner.rstrip().rstrip(".")
        return f"{body} {_target_condition_qualifier(e.condition)}."
    return f"If {_condition_phrase(e.condition)}, {_lc_first(inner)}"


# Power/toughness convention: power → "attack", toughness → "temp HP" (buff) / "HP" (debuff).
def _render_pump(e) -> str:
    verb = "gain" if _plural(e.target) else "gains"
    return f"{_subject(e.target).capitalize()} {verb} +{_value(e.power)} attack and +{_value(e.toughness)} temp HP{_duration_suffix(e)}."


def _render_wound(e) -> str:
    verb = "have" if _plural(e.target) else "has"
    return f"{_subject(e.target).capitalize()} {verb} -{_value(e.power)} attack and -{_value(e.toughness)} HP{_duration_suffix(e)}."


def _render_counters(e) -> str:
    verb = "gain" if _plural(e.target) else "gains"
    return f"{_subject(e.target).capitalize()} {verb} +{_value(e.power)}/+{_value(e.toughness)}{_duration_suffix(e) or ' for the encounter'}."


def _affliction_suffix(e) -> str:
    return f" for {e.turns} turn(s)" if getattr(e, "turns", None) else ""


def _render_poison(e) -> str:
    n = _value(e.amount)
    return (f"Poison {_tgt(e.target)}: {n} −0/−1 counter(s) now and at each "
            f"Upkeep{_affliction_suffix(e)} (any healing cures it).")


def _render_regen(e) -> str:
    n = _value(e.amount)
    return (f"{_tgt(e.target).capitalize()} regenerates: {n} +0/+1 counter(s) now "
            f"and at each Upkeep{_affliction_suffix(e)} (broken by damage).")


def _control_span(e) -> str:
    return f"for {e.turns} turn(s)" if getattr(e, "turns", None) else "for the encounter"


def _render_control(e) -> str:
    desc = _resolve(e.target, _RENDER_TARGETS.get())
    state = getattr(getattr(desc, "state", None), "value", getattr(desc, "state", None))
    if state == "corpse":
        return (f"Raise {_tgt(e.target)}: it rises as an undead ally at half its "
                f"HP {_control_span(e)}, then crumbles.")
    # Control takes the living and the dead alike (§D9-1.4) — say so on the card.
    return (f"Gain control of {_tgt(e.target)} or a corpse {_control_span(e)} — a "
            f"living enemy fights for you; a corpse rises as an undead ally at half HP.")


_MOVE_DIR_PHRASE = {
    "forward": "one row forward", "back": "one row back",
    "to_front": "to the front row", "to_mid": "to the mid row",
    "to_rear": "to the rear row",
}


def _render_move(e) -> str:
    return f"Move {_tgt(e.target)} {_MOVE_DIR_PHRASE.get(e.direction, e.direction)} (immediately)."


_STANCE_LABEL = {"attack": "Attack", "defend": "Defend",
                 "mitigate": "Mitigate", "move": "Move"}


def _render_stance(e) -> str:
    parts = []
    for slot in STANCE_SLOTS:
        v = getattr(e, slot)
        if v == "unchanged":
            continue
        label = _STANCE_LABEL[slot]
        if v == "removed":
            parts.append(f"{label}: removed")
        else:
            body = render_effects(v.effects, _RENDER_TARGETS.get()).rstrip()
            name = v.name or "replaced"
            parts.append(f"{label}: {name} — {body}")
    return "Stance (while channeled) — " + " · ".join(parts)


RENDERERS = {
    "deal_damage": lambda e: (
        f"Deal 1 damage to {_tgt(e.target)} for each point of mana capacity."
        if _is_capacity(e.amount) else f"Deal {_value(e.amount)} damage to {_tgt(e.target)}."
    ),
    "heal": lambda e: (
        f"Restore 1 HP to {_tgt(e.target)} for each point of mana capacity."
        if _is_capacity(e.amount) else f"Restore {_value(e.amount)} HP to {_tgt(e.target)}."
    ),
    "lose_life": lambda e: _render_lose_life(e),
    "poison": _render_poison,
    "regen": _render_regen,
    "charge": lambda e: f"Gather {e.amount} charge.",
    "destroy": lambda e: f"Destroy {_tgt(e.target)}.",
    "exile": lambda e: f"Exile {_tgt(e.target)}.",
    "bounce": lambda e: f"Return {_tgt(e.target)} to hand.",
    "fight": lambda e: f"{_tgt(e.target).capitalize()} fights {_tgt(e.other)}.",
    "counter": lambda e: f"Cancel {_FILTER_PHRASE.get(e.filter, 'an enemy ' + str(e.filter))}.",
    "strip_intent": lambda e: f"Remove {_subject(e.target, None, True)}'s telegraphed intent.",
    "stun": lambda e: f"{_subject(e.target, None, True).capitalize()} skips its next intent.",
    "pump": _render_pump,
    "wound": _render_wound,
    "counters": _render_counters,
    "prevent": _render_prevent,
    "protection": lambda e: f"Give {_tgt(e.target)} protection ({e.scope}).",
    "draw": lambda e: (
        "Draw a card for each point of mana capacity." if _is_capacity(e.amount)
        else f"Draw {_value(e.amount)} card(s)."
    ),
    "scry": lambda e: (
        "Scry 1 for each point of mana capacity." if _is_capacity(e.amount)
        else f"Scry {_value(e.amount)}."
    ),
    "move_card": _render_move_card,
    "create_token": lambda e: f"Create {_token_phrase(e)}.",
    "taunt": lambda e: f"Force {_tgt(e.target)} to target you this turn.",
    "revive": lambda e: f"Revive {_tgt(e.target)} at {int(e.to_fraction * 100)}% HP.",
    "control": _render_control,
    "move": _render_move,
    "stance": _render_stance,
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
    "draw": lambda e: f"draw {_value(e.amount)}",
    "scry": lambda e: f"scry {_value(e.amount)}",
    "heal": lambda e: f"heal {_value(e.amount)}",
    "deal_damage": lambda e: f"take {_value(e.amount)} damage",
    "lose_life": lambda e: (
        f"lose HP equal to {_value(e.amount)}"
        if isinstance(e.amount, Ref)
        else f"lose {e.amount} HP"
    ),
    "pump": lambda e: f"gain +{_value(e.power)}/+{_value(e.toughness)} this turn",
    "wound": lambda e: f"suffer -{_value(e.power)}/-{_value(e.toughness)} this turn",
    "destroy": lambda e: "are destroyed",
    "exile": lambda e: "are exiled",
    "bounce": lambda e: "are returned to hand",
    "stun": lambda e: f"are stunned for {e.intents} intent(s)",
    "grant_keyword": lambda e: f"gain {_keyword_phrase(e.keywords, e.params)}",
    "remove_keyword": lambda e: f"lose {_keyword_phrase(e.keywords, e.params)}",
    # Other targetable effects need subjectless phrases too, or the shared-target
    # ("Choose X: they …") path falls back to the direct renderer and leaks the
    # raw "$slot" reference with the wrong subject.
    "control": lambda e: f"come under your control {_control_span(e)}",
    "move": lambda e: f"are moved {_MOVE_DIR_PHRASE.get(e.direction, e.direction)}",
    "strip_intent": lambda e: "lose their telegraphed intent",
    "taunt": lambda e: "must target you this turn",
    "revive": lambda e: f"are revived at {int(e.to_fraction * 100)}% HP",
    "protection": lambda e: f"gain protection ({e.scope})",
    "counters": lambda e: f"gain +{_value(e.power)}/+{_value(e.toughness)} counters",
    "prevent": lambda e: (
        "can't attack" if e.parameter == "attack"
        else f"have {'the next ' if getattr(e, 'uses', 'all') == 'next' else 'all '}"
             f"{_prevent_phrase(e.parameter)} prevented"),
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
    # Publish the slot table so nested modal/conditional renders inherit it.
    token = _RENDER_TARGETS.set(targets)
    try:
        return _render_effects(effects, targets, channeled)
    finally:
        _RENDER_TARGETS.reset(token)


def _render_effects(effects: List[Effect], targets, channeled: bool) -> str:
    if channeled:
        return _render_channeled(effects, targets)

    handled = set()
    parts = []

    # Fight reads as one sentence over its two targets — never grouped with slots.
    for e in effects:
        if getattr(e, "kind", None) == "fight":
            handled.add(id(e))
            a = _subject(getattr(e, "target", None), targets)
            b = _subject(getattr(e, "other", None), targets)
            parts.append(f"{a.capitalize()} fights {b}.")

    # One sentence per shared-target slot (in first-appearance order).
    seen_slots = []
    for e in effects:
        if id(e) in handled:
            continue
        s = slot_name(getattr(e, "target", None))
        if s and s not in seen_slots:
            seen_slots.append(s)
    for s in seen_slots:
        group = [e for e in effects
                 if id(e) not in handled and slot_name(getattr(e, "target", None)) == s]
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
        return f"{_subject(e.target, targets, True)} {verb} +{_value(e.power)} attack and +{_value(e.toughness)} temp HP"
    if k == "wound":
        verb = "have" if _plural(e.target, targets) else "has"
        return f"{_subject(e.target, targets, True)} {verb} -{_value(e.power)} attack and -{_value(e.toughness)} HP"
    if k == "grant_keyword":
        verb = "have" if _plural(e.target, targets) else "has"
        return f"{_subject(e.target, targets, True)} {verb} {_keyword_phrase(e.keywords, e.params)}"
    if k == "remove_keyword":
        verb = "lose" if _plural(e.target, targets) else "loses"
        return f"{_subject(e.target, targets, True)} {verb} {_keyword_phrase(e.keywords, e.params)}"
    if k == "taunt":
        return f"{_subject(e.target, targets, True)} must target you"
    if k == "prevent":
        if e.parameter == "attack":
            return f"{_subject(e.target, targets, True)} can't attack"
        span = "the next" if getattr(e, "uses", "all") == "next" else "all"
        return (f"prevent {span} {_prevent_phrase(e.parameter)} "
                f"to {_subject(e.target, targets, True)}")
    if k == "protection":
        return f"{_subject(e.target, targets, True)} has protection"
    if k == "stun":
        return f"{_subject(e.target, targets, True)} is stunned"
    if k == "exile":
        return f"exile {_subject(e.target, targets, True)}"
    if k == "fight":
        return (f"{_subject(e.target, targets, True)} fights "
                f"{_subject(getattr(e, 'other', None), targets, True)}")
    return _lc_first(_render_one(e).rstrip("."))


def _upkeep_clause(e, targets) -> str:
    """A recurring (upkeep) effect's body — imperative, lowercase, no period."""
    k = e.kind
    if k == "create_token":
        return f"create {_token_phrase(e)}"
    if k == "lose_life":
        amt = _value(e.amount) if isinstance(e.amount, Ref) else e.amount
        if _is_self(_resolve(e.target, targets) or e.target):
            return f"lose {amt} HP"
        return f"{_subject(e.target, targets, True)} loses {amt} HP"
    if k == "draw":
        return f"draw {_value(e.amount)}"
    if k == "scry":
        return f"scry {_value(e.amount)}"
    if k == "heal":
        return f"restore {_value(e.amount)} HP to {_subject(e.target, targets, True)}"
    if k == "deal_damage":
        return f"deal {_value(e.amount)} damage to {_subject(e.target, targets, True)}"
    return _lc_first(_render_one(e).rstrip("."))


def _event_lead(trig) -> str:
    """The lead-in for an event trigger: 'Whenever <who> <does the event>'."""
    who = {"you": "you", "target": "the target", "ally": "an ally",
           "enemy": "an enemy", "any": "anyone"}.get(trig.who, trig.who)
    you = trig.who == "you"  # second person conjugates differently
    if trig.event == "attack":
        return f"Whenever {who} attack{'' if you else 's'}"
    if trig.event == "damage_taken":
        return f"Whenever {who} {'are' if you else 'is'} dealt damage"
    if trig.event == "life_gain":
        return f"Whenever {who} gain{'' if you else 's'} life"
    if trig.event == "spell_cast":
        st = getattr(trig.spell_type, "value", trig.spell_type)
        obj = {"instant": "an instant", "sorcery": "a sorcery",
               "channeled": "a channeled spell"}.get(st, "a spell")
        return f"Whenever {who} cast{'' if you else 's'} {obj}"
    if trig.event == "death":
        if trig.who == "you":
            return "When you are incapacitated"
        if trig.who == "enemy":
            return "Whenever an enemy dies"
        return f"Whenever {who} dies or is incapacitated"
    return f"Whenever {who} draw{'' if you else 's'} a card"


def _event_key(trig) -> tuple:
    return (trig.event, trig.who, getattr(trig.spell_type, "value", trig.spell_type))


def _render_channeled(effects, targets) -> str:
    parts = []
    # Continuous (untriggered) effects, one sentence each. A stance names its
    # own persistence ("Stance (while channeled) — …"), so it skips the prefix.
    for e in effects:
        if getattr(e, "kind", None) == "stance":
            t = _render_stance(e)
            parts.append(t if t.endswith(".") else t + ".")
        elif getattr(e, "trigger", None) is None:
            parts.append("While channeled: " + _channeled_body(e, targets) + ".")
    # Each recurring trigger groups its effects under its own lead-in.
    for trigger, lead in (
        ("channel_start", "When this channel begins: "),
        ("upkeep", "At the start of every turn while channeled: "),
        ("capacity_increase", "Whenever your mana capacity increases: "),
        ("channel_break", "When this channel ends (dropped or broken): "),
    ):
        group = [e for e in effects if getattr(e, "trigger", None) == trigger]
        if group:
            parts.append(lead + _join_and([_upkeep_clause(e, targets) for e in group]) + ".")
    # Event triggers group by their (event, who, spell type) signature.
    seen: List[tuple] = []
    for e in effects:
        t = getattr(e, "trigger", None)
        if not isinstance(t, EventTrigger) or _event_key(t) in seen:
            continue
        seen.append(_event_key(t))
        group = [x for x in effects
                 if isinstance(getattr(x, "trigger", None), EventTrigger)
                 and _event_key(x.trigger) == _event_key(t)]
        parts.append(_event_lead(t) + " while channeled: "
                     + _join_and([_upkeep_clause(x, targets) for x in group]) + ".")
    return " ".join(parts)


def channel_break_clause(effects, targets=None) -> str:
    """The on-break triggered clause alone ("deal 3 damage to each enemy"), or ""
    when the card has no channel_break effects. The combat UI uses this to annotate
    a held channel with what ending it will do."""
    targets = targets or {}
    token = _RENDER_TARGETS.set(targets)
    try:
        group = [e for e in effects if getattr(e, "trigger", None) == "channel_break"]
        return _join_and([_upkeep_clause(e, targets) for e in group])
    finally:
        _RENDER_TARGETS.reset(token)
