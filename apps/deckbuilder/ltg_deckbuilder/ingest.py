"""Scryfall → Card ingestion (Deckbuilder-only).

Maps a Scryfall card payload onto a `core` Card, best-effort translating its
oracle text through `core`'s deterministic translation registry. This is
authoring-tool machinery — it knows Scryfall's JSON shape — so it lives in the
app, not in `core`. The vocabulary it produces (effects, text) is all `core`.

No LLM here: where a rule recognizes oracle text it fills `effects` and renders
`translated_text`; otherwise the card is left blank and flagged
`needs_translation` for the user to author by hand.
"""

from __future__ import annotations

import re

from ltg_core.schema import Cost, Duration, Mode, Modal, Ref, Timing
from ltg_core.schema import Card
from ltg_core.translation import render_effects, translate

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


_CHOOSE_RE = re.compile(r"choose (one|two|three|four)(\s+or more)?", re.IGNORECASE)
_CHOOSE_WORD = {"one": 1, "two": 2, "three": 3, "four": 4}


def parse_modal(oracle_text: str):
    """If the text is a 'Choose one/two/… [or more] —' modal, build a Modal effect
    from its bullets. EVERY bullet must translate — a modal missing modes would
    silently misrepresent the card, so a partial translation returns None and the
    card is flagged `needs_translation` for hand-authoring instead."""
    m = _CHOOSE_RE.search(oracle_text or "")
    if not m:
        return None
    bullets = [b.strip() for b in re.split(r"[•·]\s*", oracle_text)[1:] if b.strip()]
    modes = []
    for b in bullets:
        effs = translate(b, {})
        if not effs:
            return None  # an untranslated bullet — no partial modals
        modes.append(Mode(effects=effs))
    if len(modes) < 2:
        return None
    choose = min(_CHOOSE_WORD[m.group(1).lower()], len(modes))
    return Modal(modes=modes, choose=choose, or_more=bool(m.group(2)))


def translate_rules_text(rules_text: str, timing: Timing, context: dict | None = None):
    """(effects, translated_text, needs_translation) — the MTG-style rules-text
    translation pass, shared by Scryfall ingestion and custom-card import."""
    # Modal cards ("Choose one —") become a single Modal effect over their bullets.
    modal = parse_modal(rules_text)
    if modal is not None:
        return [modal], render_effects([modal]), False

    effects = translate(rules_text, context or {})

    low = (rules_text or "").lower()
    # "for each land you control" → scale the amount by mana capacity.
    if re.search(r"for each (?:basic )?land you control", low):
        for e in effects:
            if isinstance(getattr(e, "amount", None), int):
                e.amount = Ref(ref="mana_capacity")
    # landfall ("whenever a land enters") → a capacity_increase trigger
    # (only on channeled cards, where recurring triggers are legal).
    if timing == Timing.channeled and (
        "landfall" in low or re.search(r"whenever (?:a|another) land .*enters", low)
    ):
        for e in effects:
            e.trigger = "capacity_increase"
    # "when ~ leaves the battlefield / dies / is put into a graveyard" and
    # "sacrifice ~:" abilities → a channel_break trigger: the effect fires (on the
    # stack) when the channel ends, dropped or broken for any reason.
    if timing == Timing.channeled and re.search(
        r"when .* (?:leaves the battlefield|dies|is put into a graveyard)"
        r"|sacrifice [^.:,]*:", low
    ):
        for e in effects:
            e.trigger = "channel_break"

    # On channeled (enchantment) cards, a static (untriggered) effect with a
    # duration field is continuous: make it `while_channeled`.
    if timing == Timing.channeled:
        for e in effects:
            if hasattr(e, "duration") and e.trigger is None:
                e.duration = Duration.while_channeled

    translated = render_effects(effects, channeled=(timing == Timing.channeled))
    return effects, translated, len(effects) == 0


def build_card(scryfall_json: dict) -> Card:
    """Map a Scryfall card payload onto a Card, best-effort translating it."""
    source_name = scryfall_json["name"]
    oracle_text = scryfall_json.get("oracle_text", "") or ""
    type_line = scryfall_json.get("type_line", "")
    timing = derive_timing(type_line)

    effects, translated, needs_translation = translate_rules_text(
        oracle_text, timing, {"source": scryfall_json}
    )

    return Card(
        id=slugify(source_name),
        name=source_name,
        source_name=source_name,
        rarity=normalize_rarity(scryfall_json.get("rarity", "common")),
        level=int(scryfall_json.get("cmc", 0) or 0),
        type=type_line,
        cost=parse_mana_cost(scryfall_json.get("mana_cost", "")),
        timing=timing,
        original_text=oracle_text,
        translated_text=translated,
        effects=effects,
        needs_translation=needs_translation,
    )


# --------------------------------------------------------------------------- #
# Custom-card JSON → Card (see apps/deckbuilder/CUSTOM_CARD_SCHEMA.md)
# --------------------------------------------------------------------------- #
# The three card types custom import accepts, mapped onto LTG timing.
CUSTOM_TYPES = {
    "instant": Timing.instant,
    "sorcery": Timing.sorcery,
    "enchantment": Timing.channeled,
}


def parse_mana_cost_loose(mana_cost) -> Cost:
    """Parse a custom card's mana cost: '{1}{B}' braces, compact '2GG'/'1B',
    a bare int, or empty. Unknown symbols are ignored (same as brace parsing)."""
    if isinstance(mana_cost, int):
        return Cost(generic=max(mana_cost, 0))
    s = str(mana_cost or "").strip()
    if "{" in s:
        return parse_mana_cost(s)
    generic = 0
    colors: dict = {}
    for token in re.findall(r"\d+|[A-Za-z]", s):
        if token.isdigit():
            generic += int(token)
        elif token.upper() in _COLOR_LETTERS:
            c = token.upper()
            colors[c] = colors.get(c, 0) + 1
    return Cost(generic=generic, colors=colors)


def build_custom_card(entry: dict) -> Card:
    """Map one custom-card JSON entry onto a Card, running the same rules-text
    translation pass as Scryfall ingestion. Raises ValueError on a bad entry."""
    if not isinstance(entry, dict):
        raise ValueError("each card must be a JSON object")
    name = str(entry.get("name") or "").strip()
    if not name:
        raise ValueError("missing required field 'name'")

    type_raw = str(entry.get("type") or "").strip().lower()
    timing = CUSTOM_TYPES.get(type_raw)
    if timing is None:
        raise ValueError(
            f"'type' must be one of {', '.join(CUSTOM_TYPES)} (got {entry.get('type')!r})"
        )

    effect_text = str(entry.get("effect") or "").strip()
    if not effect_text:
        raise ValueError("missing required field 'effect'")

    # Both spellings accepted. Flavour is the editor's "how the effect works
    # 'in character'" description (Card.flavor_text) — never rules text.
    flavour = str(entry.get("flavour") or entry.get("flavor") or "").strip()
    cost = parse_mana_cost_loose(entry.get("mana_cost", ""))
    effects, translated, needs_translation = translate_rules_text(effect_text, timing)

    return Card(
        id=slugify(name),
        name=name,
        source_name=name,
        rarity=normalize_rarity(str(entry.get("rarity") or "common")),
        level=cost.generic + sum(cost.colors.values()),  # level = converted cost
        type=type_raw.capitalize(),
        cost=cost,
        timing=timing,
        original_text=effect_text,
        translated_text=translated,
        flavor_text=flavour,
        effects=effects,
        needs_translation=needs_translation,
    )
