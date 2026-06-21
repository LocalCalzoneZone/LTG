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
    Effect,
    Exile,
    Heal,
    LoseLife,
    Prevent,
    Pump,
    Ref,
    Scry,
    Target,
    Timing,
    Wound,
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
@register(r"counter target spell")
def _counter_spell(m, ctx):
    return [CounterIntent()]


@register(r"destroy target (?:creature|permanent|enchantment)")
def _destroy(m, ctx):
    return [Destroy(target=Target.an_enemy)]


@register(r"exile target (?:creature|permanent|enchantment)")
def _exile(m, ctx):
    return [Exile(target=Target.an_enemy)]


@register(r"return target [\w\s]+? to (?:its owner's|their owner's|owner's) hand")
def _bounce(m, ctx):
    return [Bounce(target=Target.an_enemy)]


@register(r"you lose life equal to")
def _lose_life_equal(m, ctx):
    return [LoseLife(amount=Ref(ref="destroyed_target.level"), target=Target.self_)]


@register(r"([+\-−]\d+)/([+\-−]\d+)")
def _stat_change(m, ctx):
    def num(tok: str) -> int:
        return int(tok.replace("−", "-"))

    power, toughness = num(m.group(1)), num(m.group(2))
    if power >= 0 and toughness >= 0:
        return [Pump(power=power, toughness=toughness, target=Target.an_ally)]
    return [
        Wound(power=abs(power), toughness=abs(toughness), target=Target.an_enemy)
    ]


@register(r"prevent .* damage|^fog\b|prevent all combat damage")
def _prevent(m, ctx):
    return [Prevent(amount="all", target=Target.all_allies)]


@register(r"draw (\w+) cards?")
def _draw(m, ctx):
    return [Draw(amount=_word_to_int(m.group(1)))]


@register(r"scry (\w+)")
def _scry(m, ctx):
    return [Scry(amount=_word_to_int(m.group(1)))]


@register(r"deals? (\d+) damage")
def _deal_damage(m, ctx):
    return [DealDamage(amount=int(m.group(1)), target=Target.an_enemy)]


@register(r"gains? (\d+) life|gain (\d+) life")
def _gain_life(m, ctx):
    amt = next(g for g in m.groups() if g)
    return [Heal(amount=int(amt), target=Target.an_ally)]


@register(r"can't attack(?: or block)?")
def _pacify(m, ctx):
    return [Disable(intent_type="attack", target=Target.an_enemy)]


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
            key = (effect.kind, getattr(effect, "target", None))
            if key in seen_kinds:
                continue
            seen_kinds.add(key)
            effects.append(effect)
    return effects


# --------------------------------------------------------------------------- #
# Renderer (effects → LTG-language text)
# --------------------------------------------------------------------------- #
_TARGET_PHRASE = {
    Target.self_: "yourself",
    Target.an_ally: "an ally",
    Target.an_enemy: "an enemy",
    Target.all_enemies: "all enemies",
    Target.all_allies: "all allies",
    Target.a_minion: "a minion",
    Target.the_boss: "the boss",
    Target.an_ally_token: "an ally token",
    Target.an_enemy_intent: "an enemy intent",
}


def _tgt(t: Target) -> str:
    return _TARGET_PHRASE.get(t, t.value)


def _value(v) -> str:
    if isinstance(v, Ref):
        if v.ref.endswith(".level"):
            return "its Level"
        return v.ref
    return str(v)


RENDERERS = {
    "deal_damage": lambda e: f"Deal {e.amount} damage to {_tgt(e.target)}.",
    "heal": lambda e: f"Restore {e.amount} HP to {_tgt(e.target)}.",
    "lose_life": lambda e: (
        f"Lose HP equal to {_value(e.amount)}."
        if e.target == Target.self_
        else f"{_tgt(e.target).capitalize()} loses HP equal to {_value(e.amount)}."
    ),
    "destroy": lambda e: f"Destroy {_tgt(e.target)}.",
    "exile": lambda e: f"Exile {_tgt(e.target)}.",
    "bounce": lambda e: f"Return {_tgt(e.target)} to hand.",
    "counter_intent": lambda e: f"Counter {_tgt(e.target)}.",
    "strip_intent": lambda e: f"Strip {_tgt(e.target)}.",
    "stun": lambda e: f"Stun {_tgt(e.target)} for {e.intents} intent(s).",
    "pump": lambda e: (
        f"{_tgt(e.target).capitalize()} gains +{e.power} damage and "
        f"+{e.toughness} temporary HP this turn."
    ),
    "wound": lambda e: (
        f"{_tgt(e.target).capitalize()} suffers -{e.power} damage and "
        f"-{e.toughness} HP this turn."
    ),
    "counters": lambda e: (
        f"{_tgt(e.target).capitalize()} gains +{e.power}/+{e.toughness} "
        f"for the encounter."
    ),
    "prevent": lambda e: f"Prevent {_value(e.amount)} damage to {_tgt(e.target)}.",
    "protection": lambda e: f"Give {_tgt(e.target)} protection ({e.scope}).",
    "draw": lambda e: f"Draw {e.amount} card(s).",
    "scry": lambda e: f"Scry {e.amount}.",
    "create_token": lambda e: f"Create {e.count} {e.token_id} token(s).",
    "taunt": lambda e: f"Force {_tgt(e.target)} to target you this turn.",
    "disable": lambda e: f"{_tgt(e.target).capitalize()} can't {e.intent_type}.",
    "revive": lambda e: f"Revive {_tgt(e.target)} at {int(e.to_fraction * 100)}% HP.",
}


def render_effects(effects: List[Effect]) -> str:
    """Render a list of effects into a single LTG-language string."""
    parts = []
    for e in effects:
        renderer = RENDERERS.get(e.kind)
        if renderer:
            parts.append(renderer(e))
    return " ".join(parts)


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
    reactive = any(e.kind in ("counter_intent", "strip_intent") for e in effects)
    translated = render_effects(effects)

    return Card(
        id=slugify(source_name),
        name=source_name,
        source_name=source_name,
        rarity=normalize_rarity(scryfall_json.get("rarity", "common")),
        level=int(scryfall_json.get("cmc", 0) or 0),
        type=type_line,
        cost=parse_mana_cost(scryfall_json.get("mana_cost", "")),
        timing=derive_timing(type_line),
        reactive=reactive,
        original_text=oracle_text,
        translated_text=translated,
        effects=effects,
        needs_translation=len(effects) == 0,
    )
