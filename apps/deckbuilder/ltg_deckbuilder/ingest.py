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


def build_card(scryfall_json: dict) -> Card:
    """Map a Scryfall card payload onto a Card, best-effort translating it."""
    source_name = scryfall_json["name"]
    oracle_text = scryfall_json.get("oracle_text", "") or ""
    type_line = scryfall_json.get("type_line", "")
    timing = derive_timing(type_line)

    # Modal cards ("Choose one —") become a single Modal effect over their bullets.
    modal = parse_modal(oracle_text)
    if modal is not None:
        translated = render_effects([modal])
        return Card(
            id=slugify(source_name), name=source_name, source_name=source_name,
            rarity=normalize_rarity(scryfall_json.get("rarity", "common")),
            level=int(scryfall_json.get("cmc", 0) or 0), type=type_line,
            cost=parse_mana_cost(scryfall_json.get("mana_cost", "")), timing=timing,
            original_text=oracle_text, translated_text=translated, effects=[modal],
            needs_translation=False,
        )

    effects = translate(oracle_text, {"source": scryfall_json})

    low = oracle_text.lower()
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

    # On channeled (enchantment) cards, a static (untriggered) effect with a
    # duration field is continuous: make it `while_channeled`.
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
        original_text=oracle_text,
        translated_text=translated,
        effects=effects,
        needs_translation=len(effects) == 0,
    )
