"""Forged loot — what an act's boss actually drops (Design Update 17 §D17-4.5).

The catalogue under ``content/equipment/`` is the shelf VENDORS sell from. A
boss's spoils are never taken off that shelf: they are **forged** from a
**lexicon** — a set of verbiage (forms, materials, epithets, "of the …"
phrases, flavour lines, art details) drawn for the scenario **when the scenario
is made** — crossed with the mechanical chassis and the affix table in code.

- The **lexicon** is frozen onto the arc (``arc["loot_lexicon"]``), so it
  survives saves, reloads and pre-generated scenario files, and so every
  scenario's spoils sound like that scenario. Everquest's next arc draws a new
  one. It is picked in CODE from theme word-banks matched against the town and
  arc text — no LLM call sits between a boss dying and its loot (§D17-4.5).
- The **mechanics** come from the same tables merchant rolls use: a chassis
  (attack mode, a Power step, a stat rider) plus 1–2 affixes from
  ``items.AFFIXES``, each points-costed. Nothing forged is off-vocabulary or
  off-budget; only the words are new.

Everything here is deterministic given a seed: the same scenario forges the
same spoils on a reload.
"""

from __future__ import annotations

import random
import zlib
from typing import Any, Dict, List, Optional, Tuple

from ltg_core.schema import Item

from .items import AFFIXES, RARITY_ORDER, _rarity_at_least

# T-83: what a Phase III boss drops.
DROP_GEAR_PER_PARTY = 1          # (party size + 1) gear
DROP_CONSUMABLES_PER_MEMBER = 2  # (party size × 2) consumables


# --------------------------------------------------------------------------- #
# The verbiage — theme word-banks
# --------------------------------------------------------------------------- #
# Each theme: `keys` are matched against the town + arc text to pick the
# scenario's voice; the rest is the raw vocabulary a lexicon is drawn from.
#   materials — noun-adjuncts ("Bell-Metal Falchion")
#   epithets  — adjectives ("Salt-Bitten Falchion")
#   suffixes  — the "of the …" tail ("… of the Drowned Choir")
#   details   — one clause of art description
#   flavor    — the single flavour line an item carries
THEMES: Dict[str, Dict[str, Any]] = {
    "salt": {
        "keys": ("sea", "salt", "tide", "ship", "sail", "harbour", "harbor", "fish",
                 "drown", "gull", "brine", "wreck", "coast", "dock", "boat", "net"),
        "materials": ["Saltglass", "Whalebone", "Sailcloth", "Tide-Iron", "Coral", "Driftwood"],
        "epithets": ["Salt-Bitten", "Drowned", "Tide-Worn", "Barnacled", "Storm-Struck", "Deepwater"],
        "suffixes": ["the Drowned Choir", "the Long Tide", "Hollow Water", "the Last Sail",
                     "Salt and Iron"],
        "details": ["crusted white along every seam", "green with old weed", "still smelling of brine"],
        "flavor": ["It came up in a net. Nobody claimed it.",
                   "The salt has been eating it for years and has not finished.",
                   "Cold, and it stays cold.",
                   "Somebody went under holding this."],
    },
    "marsh": {
        "keys": ("marsh", "reed", "fen", "bog", "mire", "mud", "frog", "willow", "mist",
                 "swamp", "eel", "heron", "peat"),
        "materials": ["Reedwork", "Peat-Iron", "Bogwood", "Willow", "Eelskin", "Fen-Glass"],
        "epithets": ["Mire-Sunk", "Reed-Bound", "Fen-Cold", "Silt-Grey", "Marsh-Kept", "Sodden"],
        "suffixes": ["the Reed-King", "the Standing Water", "Nine Willows", "the Low Fen",
                     "the Heron's Watch"],
        "details": ["stained black to the grip by peat", "wound in split reed",
                    "furred with dried silt"],
        "flavor": ["The bog kept it and the bog gave it back.",
                   "It came out of the peat looking newer than it went in.",
                   "Something was buried with this. Not it.",
                   "It smells faintly of standing water."],
    },
    "ash": {
        "keys": ("fire", "ash", "ember", "cinder", "burn", "smoke", "kiln", "scorch",
                 "flame", "pyre", "char", "furnace"),
        "materials": ["Cinder-Iron", "Kilnglass", "Charwood", "Ember-Brass", "Slag", "Pyre-Bone"],
        "epithets": ["Fire-Blacked", "Ember-Lit", "Scorched", "Kiln-Hard", "Smoke-Cured", "Ashen"],
        "suffixes": ["Ashen Vows", "the Long Burning", "the Banked Fire", "the Kiln Road",
                     "Seven Chimneys"],
        "details": ["blacked along one face", "still gritty with ash",
                    "warm long after it should be cold"],
        "flavor": ["It came out of the fire keener than it went in.",
                   "Everything it touched that day burned.",
                   "The heat never entirely left it.",
                   "Held too long, it starts to smell of smoke."],
    },
    "bone": {
        "keys": ("bone", "grave", "barrow", "tomb", "dead", "crypt", "ghost", "corpse",
                 "plague", "shroud", "mourn", "wight", "cairn"),
        "materials": ["Gravebone", "Shroudcloth", "Barrow-Iron", "Toothglass", "Ashwood", "Cerecloth"],
        "epithets": ["Barrow-Cold", "Grave-Kept", "Shrouded", "Unmourned", "Bone-Set", "Pale"],
        "suffixes": ["the Old Watch", "the Quiet Ground", "Nine Cairns", "the Last Lantern",
                     "the Unburied"],
        "details": ["yellowed like old bone", "wrapped at the grip in grey cerecloth",
                    "cut with small unreadable names"],
        "flavor": ["It was buried once. It did not stay.",
                   "Whoever owned it is still owed something.",
                   "It is cold in a way that has nothing to do with weather.",
                   "It has outlasted four owners."],
    },
    "iron": {
        "keys": ("iron", "forge", "mine", "quarry", "smith", "chain", "rust", "anvil",
                 "ore", "hammer", "mill", "forgework"),
        "materials": ["Black Iron", "Anvil-Steel", "Chainwork", "Pig-Lead", "Rivet-Brass", "Slagsteel"],
        "epithets": ["Hammer-Set", "Rust-Marked", "Cold-Forged", "Rivet-Bound", "Anvil-True", "Pitted"],
        "suffixes": ["the Deep Seam", "the Cold Anvil", "the Blackworks", "Bell-Metal",
                     "the Ninth Forge"],
        "details": ["hammer marks still standing proud on it", "banded twice in riveted strap",
                    "rust bloomed and scrubbed back a dozen times"],
        "flavor": ["Somebody good made this, and nobody remembers them.",
                   "Honest weight, honestly balanced.",
                   "It has been rehafted three times.",
                   "It rings when you set it down."],
    },
    "frost": {
        "keys": ("frost", "ice", "snow", "winter", "cold", "rime", "glacier", "hoar",
                 "freeze", "sleet", "north"),
        "materials": ["Rimeglass", "Hoar-Silver", "Frostbone", "Ice-Lacquer", "Winterwood", "Pale Tin"],
        "epithets": ["Rime-Furred", "Winter-Kept", "Frost-Bitten", "Hoar-White", "Snow-Blind", "Numbing"],
        "suffixes": ["the Long Night", "the White Pass", "the Standing Cold", "Nine Winters",
                     "the Frozen March"],
        "details": ["furred with frost even indoors", "so cold it sticks to a bare hand",
                    "beaded with meltwater that never dries"],
        "flavor": ["It takes the warmth out of the room.",
                   "Snow does not settle on it. It settles under it.",
                   "The cold in it is patient.",
                   "It was found standing upright in a drift."],
    },
    "green": {
        "keys": ("wood", "forest", "root", "thorn", "briar", "grove", "harvest", "orchard",
                 "green", "vine", "field", "seed", "hedge"),
        "materials": ["Heartwood", "Thornsilver", "Briarbrass", "Greenhorn", "Rootbone", "Orchard-Ash"],
        "epithets": ["Root-Wound", "Briar-Cut", "Green-Bound", "Sap-Dark", "Thorn-Set", "Overgrown"],
        "suffixes": ["the Old Grove", "the Turning Year", "Nine Furrows", "the Green Vow",
                     "the Hollow Oak"],
        "details": ["a live green shoot pushing from one seam", "bound at the grip in braided withy",
                    "smelling of cut sap"],
        "flavor": ["It has been growing quietly the whole time.",
                   "Left in the ground a season, it would take root.",
                   "The wood in it is still alive enough to argue.",
                   "It was cut from something older than the town."],
    },
    "bell": {
        "keys": ("bell", "choir", "chime", "hymn", "shrine", "chapel", "saint", "vow",
                 "psalm", "prayer", "reliquary", "priest", "temple"),
        "materials": ["Bell-Metal", "Votive Brass", "Psalm-Silver", "Reliquary Gold", "Chime-Tin",
                      "Censer-Bronze"],
        "epithets": ["Vow-Kept", "Consecrated", "Chime-Struck", "Hymn-Bound", "Blessed", "Tolling"],
        "suffixes": ["the Bell Choir", "the Ninth Vow", "the Silent Hour", "the Broken Psalm",
                     "the Standing Saint"],
        "details": ["cut with a line of worn liturgy", "hung with a single small votive bell",
                    "polished bright at every place a thumb rests"],
        "flavor": ["It hums when a bell rings anywhere near.",
                   "It was promised to a saint who never collected.",
                   "Somebody swore something on this.",
                   "It sounds a clear note when it is struck."],
    },
    "war": {
        "keys": ("war", "raid", "orc", "tithe", "banner", "siege", "captain", "soldier",
                 "muster", "warband", "blood", "levy", "garrison"),
        "materials": ["Banner-Steel", "Muster-Iron", "Warhide", "Levy-Brass", "Shield-Oak", "Spoil-Silver"],
        "epithets": ["Blood-Paid", "Muster-Marked", "War-Kept", "Banner-Torn", "Tithe-Taken", "Veteran"],
        "suffixes": ["the Broken Muster", "the Tithe-Taker", "the Last Levy", "Nine Banners",
                     "the Red Field"],
        "details": ["a cut banner-scrap still knotted to it", "notched along one edge and never dressed",
                    "somebody's company mark burned into the grip"],
        "flavor": ["It was issued, not bought.",
                   "It has been surrendered twice and taken back three times.",
                   "The last hand on this did not let go willingly.",
                   "Marked with a company that no longer musters."],
    },
    "storm": {
        "keys": ("storm", "wind", "thunder", "gale", "lightning", "rain", "squall", "sky",
                 "cloud", "weather", "tempest"),
        "materials": ["Stormglass", "Levin-Brass", "Skyiron", "Rain-Silver", "Gale-Horn", "Thunderwood"],
        "epithets": ["Levin-Struck", "Gale-Torn", "Rain-Wet", "Sky-Split", "Thunder-Marked", "Restless"],
        "suffixes": ["the Long Squall", "the Turning Sky", "Nine Thunders", "the Grey Weather",
                     "the Loud Night"],
        "details": ["fern-shaped burn scars branching across it", "never quite dry to the touch",
                    "faintly charged — the hair on your arm lifts"],
        "flavor": ["Lightning found it once and remembers where.",
                   "It gets restless before weather.",
                   "You can hear it well before you see it.",
                   "It was picked up out of a burned field."],
    },
}

# --------------------------------------------------------------------------- #
# The forms — the shapes the words hang on, each with its mechanical chassis
# --------------------------------------------------------------------------- #
# weapon forms carry the attack mode; consumable forms carry a `family` so a
# healing draught is never named "Powder" and a firepot is never a "Salve".
MELEE_FORMS: List[Tuple[str, str, str]] = [
    ("falchion", "Falchion", "a broad single-edged falchion with a knuckle-bow guard"),
    ("glaive", "Glaive", "a long glaive on an ash haft, the blade swept and heavy"),
    ("warpick", "Warpick", "a short warpick with a beaked head and a rear hammer"),
    ("cleaver", "Cleaver", "a rectangular cleaver thick along the spine"),
    ("maul", "Maul", "a two-handed maul with a banded head"),
    ("spear", "Spear", "a leaf-bladed spear with a collar of bound cord"),
    ("sabre", "Sabre", "a curved sabre with a shell guard and a wire-wound grip"),
    ("flail", "Flail", "a short flail — a chained head on a stubby handle"),
    ("boarding_axe", "Boarding Axe", "a one-handed boarding axe with a spike opposite the blade"),
    ("longknife", "Longknife", "a long single-edged knife almost the length of a forearm"),
    ("poleaxe", "Poleaxe", "a poleaxe with an axe head, a top spike, and a shod butt"),
    ("greatblade", "Greatblade", "a two-handed blade with a long ricasso and a ring guard"),
]
RANGED_FORMS: List[Tuple[str, str, str]] = [
    ("longbow", "Longbow", "a tall longbow, the belly bound in sinew"),
    ("recurve", "Recurve", "a short recurve bow of laminated horn"),
    ("sling", "Sling", "a braided sling with a deep shot-pouch"),
    ("crossbow", "Crossbow", "a stocky crossbow with an iron prod and a stirrup"),
    ("arbalest", "Arbalest", "a heavy arbalest with a crank windlass on its stock"),
    ("harpoon", "Harpoon", "a barbed harpoon trailing a coil of line"),
    ("javelins", "Javelins", "a sheaf of short javelins in a shoulder quiver"),
    ("dartcase", "Dartcase", "a stiffened case of feathered throwing darts"),
    ("hookshot", "Hook-Bow", "a small bow rigged to throw a weighted grapple"),
    ("boarsling", "Boar-Sling", "a staff sling with a long throwing arm"),
]
ACCESSORY_FORMS: List[Tuple[str, str, str]] = [
    ("ring", "Ring", "a heavy signet ring, the device on it worn shallow"),
    ("torc", "Torc", "an open neck-torc twisted from three strands"),
    ("amulet", "Amulet", "a flat amulet on a knotted cord"),
    ("brooch", "Brooch", "a ring-brooch with a long pin, worn at the shoulder"),
    ("bracer", "Bracer", "a narrow forearm bracer buckled over a linen wrap"),
    ("circlet", "Circlet", "a thin circlet, plain except at the brow"),
    ("mantle", "Mantle", "a short shoulder mantle clasped at the throat"),
    ("chain", "Chain", "a long looped chain worn twice around the neck"),
    ("girdle", "Girdle", "a wide belt-girdle with a heavy tongued buckle"),
    ("seal", "Seal", "a pierced seal-matrix hung from a wire hook"),
    ("charm", "Charm", "a small bound charm, worn smooth by handling"),
    ("gauntlet", "Gauntlet", "a single articulated gauntlet, left hand"),
]
# family: restorative (heals, wards) · volatile (damage, poison) · subtle
# (cards, intents, keywords)
CONSUMABLE_FORMS: List[Tuple[str, str, str, str]] = [
    ("draught", "Draught", "restorative", "a stoppered clay flask, the contents cloudy"),
    ("tonic", "Tonic", "restorative", "a narrow glass vial sealed with wax"),
    ("salve", "Salve", "restorative", "a shallow tin of thick salve, lid half turned"),
    ("poultice", "Poultice", "restorative", "a pad of mashed herbs bound in sailcloth"),
    ("cordial", "Cordial", "restorative", "a squat bottle of dark syrup, corked tight"),
    ("firepot", "Firepot", "volatile", "a fist-sized clay pot with a soaked rag in its neck"),
    ("oil", "Oil", "volatile", "a slim black vial of heavy oil"),
    ("powder", "Powder", "volatile", "a twist of waxed paper holding a grey powder"),
    ("flask", "Flask", "volatile", "a fat glass flask, its stopper sealed in lead foil"),
    ("resin", "Resin", "volatile", "a knob of hard amber resin wrapped in cord"),
    ("philtre", "Philtre", "subtle", "a thin-necked philtre bottle, barely a mouthful in it"),
    ("incense", "Incense", "subtle", "a short cone of pressed incense in a paper sleeve"),
    ("ash", "Ash", "subtle", "a pinch of fine pale ash in a folded leaf"),
    ("water", "Water", "subtle", "a leather costrel of perfectly still water"),
    ("tincture", "Tincture", "subtle", "a dropper bottle of tincture, the glass smoked brown"),
]

# How many of each word the scenario's lexicon keeps: enough that two acts of
# the same scenario rhyme without repeating.
DRAW = {"materials": 8, "epithets": 8, "suffixes": 6, "details": 5, "flavor": 6,
        "melee": 6, "ranged": 5, "accessory": 6, "consumable": 8}

# Name shapes. `E` epithet · `M` material · `F` form · `S` suffix.
GEAR_PATTERNS = ["E F", "M F", "M F of S", "E M F", "F of S", "E F of S"]
CONSUMABLE_PATTERNS = ["M F", "E F", "F of S", "E M F"]
GEAR_ART_JOINS = ["worked in {m}", "banded with {m}", "fitted throughout with {m}",
                  "the whole of it {m}"]


# --------------------------------------------------------------------------- #
# The mechanical chassis (in code — never off-budget)
# --------------------------------------------------------------------------- #
# A weapon's Power step by tier, and what it costs on the level-up points scale.
POWER_BY_TIER = ((1, 0), (2, 1), (4, 1), (6, 2))   # (tier ceiling, +Power)
POWER_POINTS = 15
# An accessory's chassis rider when its affixes did not already give it one.
ACCESSORY_BASES = [
    {"static": {"kind": "stat", "stat": "hp", "amount": 4}, "points": 10, "level_min": 1},
    {"static": {"kind": "stat", "stat": "hp", "amount": 6}, "points": 15, "level_min": 2},
    {"static": {"kind": "stat", "stat": "mana", "amount": 1}, "points": 15, "level_min": 1},
    {"static": {"kind": "stat", "stat": "cards", "amount": 1}, "points": 15, "level_min": 1},
]
ALLY = {"mode": "chosen", "side": "ally", "exclude_self": False, "targeted": False}
ENEMY = {"mode": "chosen", "side": "enemy", "exclude_self": False, "targeted": False}
SELF = {"mode": "self"}


def _heal(tier: int) -> List[Dict[str, Any]]:
    return [{"kind": "heal", "amount": min(10, 3 + tier), "target": ALLY}]


def _big_heal(tier: int) -> List[Dict[str, Any]]:
    return [{"kind": "heal", "amount": min(14, 6 + tier), "target": ALLY}]


# Each recipe: how the effects scale with tier, its speed, its price, the form
# family it may be named for, and the level it starts appearing at.
CONSUMABLE_RECIPES: List[Dict[str, Any]] = [
    {"id": "heal", "family": "restorative", "timing": "instant", "level_min": 1,
     "points": lambda t: 8 + 2 * min(t, 4), "effects": _heal},
    {"id": "big_heal", "family": "restorative", "timing": "sorcery", "level_min": 1,
     "points": lambda t: 10 + 2 * min(t, 4), "effects": _big_heal},
    {"id": "regen", "family": "restorative", "timing": "instant", "level_min": 2,
     "points": lambda t: 10 + 2 * min(t, 3),
     "effects": lambda t: [{"kind": "regen", "amount": 2 if t < 4 else 3,
                            "target": ALLY}]},
    {"id": "ward", "family": "restorative", "timing": "instant", "level_min": 1,
     "points": lambda t: 12,
     "effects": lambda t: [{"kind": "prevent", "parameter": "combat_damage", "combat_kind": "all",
                            "uses": "next", "target": ALLY, "duration": "this_turn"}]},
    {"id": "aegis", "family": "restorative", "timing": "instant", "level_min": 3,
     "points": lambda t: 15,
     "effects": lambda t: [{"kind": "protection", "parameter": "all_damage",
                            "combat_kind": "all", "target": ALLY}]},
    {"id": "pump", "family": "restorative", "timing": "instant", "level_min": 1,
     "points": lambda t: 10 + (4 if t >= 4 else 0),
     "effects": lambda t: [{"kind": "pump", "power": 2 if t < 4 else 3,
                            "toughness": 2 if t < 4 else 3, "target": ALLY,
                            "duration": "this_turn"}]},
    {"id": "counters", "family": "restorative", "timing": "sorcery", "level_min": 3,
     "points": lambda t: 15,
     "effects": lambda t: [{"kind": "counters", "power": 1, "toughness": 1, "target": ALLY,
                            "duration": "encounter"}]},
    {"id": "burn", "family": "volatile", "timing": "instant", "level_min": 1,
     "points": lambda t: 10 + 2 * min(t, 4),
     "effects": lambda t: [{"kind": "deal_damage", "amount": min(7, 2 + t), "target": ENEMY}]},
    {"id": "bomb", "family": "volatile", "timing": "sorcery", "level_min": 3,
     "points": lambda t: 14 + 2 * min(t, 5),
     "effects": lambda t: [{"kind": "deal_damage", "amount": min(10, 4 + t), "target": ENEMY}]},
    {"id": "venom", "family": "volatile", "timing": "instant", "level_min": 2,
     "points": lambda t: 12,
     "effects": lambda t: [{"kind": "poison", "amount": 1 if t < 4 else 2, "target": ENEMY}]},
    {"id": "stun", "family": "volatile", "timing": "instant", "level_min": 3,
     "points": lambda t: 15,
     "effects": lambda t: [{"kind": "stun", "intents": 1, "target": ENEMY}]},
    {"id": "strip", "family": "subtle", "timing": "sorcery", "level_min": 1,
     "points": lambda t: 12,
     "effects": lambda t: [{"kind": "strip_intent", "target": ENEMY}]},
    {"id": "draw", "family": "subtle", "timing": "instant", "level_min": 1,
     "points": lambda t: 10,
     "effects": lambda t: [{"kind": "draw", "amount": 1, "target": SELF}]},
    {"id": "scry", "family": "subtle", "timing": "instant", "level_min": 1,
     "points": lambda t: 5,
     "effects": lambda t: [{"kind": "scry", "amount": 2, "target": SELF}]},
    {"id": "wings", "family": "subtle", "timing": "instant", "level_min": 2,
     "points": lambda t: 10,
     "effects": lambda t: [{"kind": "grant_keyword", "keywords": ["flying"], "target": ALLY,
                            "duration": "this_turn"}]},
    {"id": "quickness", "family": "subtle", "timing": "instant", "level_min": 2,
     "points": lambda t: 10,
     "effects": lambda t: [{"kind": "grant_keyword", "keywords": ["first_strike"],
                            "target": ALLY, "duration": "this_turn"}]},
]


# --------------------------------------------------------------------------- #
# Building the lexicon (once, when the scenario is made)
# --------------------------------------------------------------------------- #
def _stable_seed(*texts: str) -> int:
    return zlib.crc32(" ".join(t for t in texts if t).lower().encode("utf-8")) & 0x7FFFFFFF


def _arc_text(town: Dict[str, Any], arc: Dict[str, Any]) -> str:
    bits = [str(town.get("name", "")), str(town.get("region_flavor", "")), str(town.get("scene", "")),
            str(arc.get("title", "")), str(arc.get("villain", "")), str(arc.get("stakes", ""))]
    for act in arc.get("acts") or []:
        bits += [str(act.get("title", "")), str(act.get("hook", "")),
                 str(act.get("adventure_theme", "")), str(act.get("tone_notes", ""))]
    return " ".join(bits)


def theme_scores(text: str) -> List[Tuple[str, int]]:
    """How loudly each theme's vocabulary is already being spoken by the town
    and the arc — highest first, ties broken by the theme's own name."""
    low = text.lower()
    scored = [(tid, sum(low.count(k) for k in th["keys"])) for tid, th in THEMES.items()]
    return sorted(scored, key=lambda kv: (-kv[1], kv[0]))


def build_lexicon(town: Dict[str, Any], arc: Dict[str, Any],
                  seed: Optional[int] = None) -> Dict[str, Any]:
    """Draw the scenario's loot vocabulary: a primary theme read off the town
    and arc text, a second theme for contrast, and a fixed hand of words and
    forms taken from both. Deterministic — the same arc always draws the same
    lexicon, so a reload is not a different world."""
    text = _arc_text(town, arc)
    rng = random.Random(seed if seed is not None else _stable_seed(text))
    ranked = theme_scores(text)
    primary = ranked[0][0] if ranked[0][1] else rng.choice(sorted(THEMES))
    rest = [tid for tid, _ in ranked if tid != primary]
    second = (rest[0] if ranked[0][1] and len(rest) > 1 and dict(ranked)[rest[0]]
              else rng.choice([t for t in sorted(THEMES) if t != primary]))

    def draw(field: str, n: int) -> List[str]:
        # Two parts primary voice to one part the second theme's.
        a, b = THEMES[primary][field], THEMES[second][field]
        want_b = max(1, n // 3)
        picked = rng.sample(a, min(len(a), n - want_b)) + rng.sample(b, min(len(b), want_b))
        return list(dict.fromkeys(picked))

    def forms(pool: List[Tuple], n: int) -> List[str]:
        return [f[0] for f in rng.sample(pool, min(len(pool), n))]

    return {
        "theme": primary, "second": second,
        "materials": draw("materials", DRAW["materials"]),
        "epithets": draw("epithets", DRAW["epithets"]),
        "suffixes": draw("suffixes", DRAW["suffixes"]),
        "details": draw("details", DRAW["details"]),
        "flavor": draw("flavor", DRAW["flavor"]),
        "forms": {"melee": forms(MELEE_FORMS, DRAW["melee"]),
                  "ranged": forms(RANGED_FORMS, DRAW["ranged"]),
                  "accessory": forms(ACCESSORY_FORMS, DRAW["accessory"]),
                  "consumable": forms(CONSUMABLE_FORMS, DRAW["consumable"])},
    }


def lexicon_of(arc: Dict[str, Any], town: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The arc's frozen lexicon, drawing (and freezing) one if it has none —
    the path an arc written before this system, or by hand, takes."""
    lex = arc.get("loot_lexicon")
    if isinstance(lex, dict) and lex.get("forms"):
        return lex
    lex = build_lexicon(town or {}, arc)
    arc["loot_lexicon"] = lex
    return lex


# --------------------------------------------------------------------------- #
# Forging
# --------------------------------------------------------------------------- #
def _form_table(slot: str, mode: str = "") -> Dict[str, Tuple]:
    pool = {"melee": MELEE_FORMS, "ranged": RANGED_FORMS,
            "accessory": ACCESSORY_FORMS, "consumable": CONSUMABLE_FORMS}[mode or slot]
    return {f[0]: f for f in pool}


def _pick_form(rng: random.Random, lex: Dict[str, Any], key: str,
               family: str = "", avoid: Optional[set] = None) -> Tuple:
    table = _form_table("", key)
    ids = [i for i in (lex.get("forms", {}).get(key) or []) if i in table] or list(table)
    if family:
        matching = [i for i in ids if table[i][2] == family]
        ids = matching or ids
    # One spread of spoils should not be four of the same shape.
    fresh = [i for i in ids if i not in (avoid or ())]
    return table[rng.choice(fresh or ids)]


def _words(lex: Dict[str, Any], field: str, fallback: str) -> List[str]:
    vals = [str(v) for v in (lex.get(field) or []) if str(v).strip()]
    return vals or [fallback]


def _name(rng: random.Random, lex: Dict[str, Any], form_name: str,
          patterns: List[str], want_suffix: bool, material: str) -> str:
    """Assemble the name out of the scenario's verbiage. ``material`` is the
    one the art description also names, so the words agree with the picture."""
    if material.split()[-1].lower() == form_name.split()[-1].lower():
        # "Tide-Iron Tide-Iron", "Deepwater Water" — drop the pattern's M.
        patterns = [p for p in patterns if "M" not in p.split()] or patterns
    pats = [p for p in patterns if ("S" in p.split()) == want_suffix] or patterns
    pat = rng.choice(pats)
    parts = []
    for tok in pat.split():
        if tok == "E":
            parts.append(rng.choice(_words(lex, "epithets", "Worn")))
        elif tok == "M":
            parts.append(material)
        elif tok == "F":
            parts.append(form_name)
        elif tok == "of":
            parts.append("of")
        elif tok == "S":
            parts.append(rng.choice(_words(lex, "suffixes", "the Old Road")))
    return " ".join(parts)


def _art_desc(rng: random.Random, lex: Dict[str, Any], form_art: str,
              material: str, gear: bool) -> str:
    detail = rng.choice(_words(lex, "details", "plainly made and hard used"))
    if gear:
        join = rng.choice(GEAR_ART_JOINS).format(m=material.lower())
        return f"{form_art[0].upper()}{form_art[1:]}, {join}, {detail}."
    return f"{form_art[0].upper()}{form_art[1:]}, {detail}."


def _power_for(tier: int) -> int:
    step = 0
    for ceiling, amount in POWER_BY_TIER:
        if tier >= ceiling:
            step = amount
    return step


def _affix_pool(slot: str, tier: int, boss: bool, have: set) -> List[Dict[str, Any]]:
    return [a for a in AFFIXES
            if slot in a["slots"] and a["level_min"] <= max(1, tier)
            and (boss or not a.get("banned"))
            and (a["static"]["kind"], a["static"].get("stat"),
                 a["static"].get("keyword")) not in have]

def forge_gear(rng: random.Random, slot: str, tier: int, lexicon: Dict[str, Any],
               boss: bool = True, avoid: Optional[set] = None) -> Item:
    """One piece of forged gear: a form out of the scenario's vocabulary, a
    code chassis at the tier, and 1–2 affixes off the shared table. ``avoid``
    holds the form ids already used by this spread of spoils."""
    tier = max(1, int(tier))
    bonus = 0
    if slot == "weapon":
        mode = rng.choice(["melee", "ranged"])
        form_id, form_name, form_art = _pick_form(rng, lexicon, mode, avoid=avoid)
        statics: List[Dict[str, Any]] = [{"kind": "attack_mode", "mode": mode}]
        price = 0
        # A boss's weapon leans a step above the tier's plain Power step.
        # A boss never drops a bare stick: its weapons carry Power at minimum
        # the tier's step, and at least +1.
        bonus = max(1 if boss else 0,
                    _power_for(tier) + (1 if boss and rng.random() < 0.5 else 0))
        if bonus:
            statics.append({"kind": "power_bonus", "amount": bonus})
            price += POWER_POINTS * bonus
    else:
        form_id, form_name, form_art = _pick_form(rng, lexicon, "accessory", avoid=avoid)
        statics, price = [], 0
        # An accessory IS its rider: it always carries a chassis stat, and the
        # affixes ride on top of it.
        base = rng.choice([b for b in ACCESSORY_BASES if b["level_min"] <= tier]
                          or ACCESSORY_BASES[:1])
        statics.append(dict(base["static"]))
        price += int(base["points"])

    have = {(st["kind"], st.get("stat"), st.get("keyword")) for st in statics}
    pool = _affix_pool(slot, tier, boss, have)
    rng.shuffle(pool)
    n_affix = rng.choice([1, 2, 2]) if boss else rng.choice([0, 1, 1])
    chosen: List[Dict[str, Any]] = []
    for a in pool:
        if len(chosen) >= n_affix:
            break
        if any(c["static"]["kind"] == a["static"]["kind"]
               and c["static"].get("stat") == a["static"].get("stat") for c in chosen):
            continue
        chosen.append(a)

    rarity = "common"
    for a in chosen:
        statics.append(dict(a["static"]))
        price += int(a["points"])
        if _rarity_at_least(a["rarity_min"], rarity):
            rarity = a["rarity_min"]
    if bonus >= 2 and not _rarity_at_least(rarity, "uncommon"):
        rarity = "uncommon"
    # A boss's find is scarcer than the sum of its parts.
    if boss and chosen and rng.random() < 0.5:
        rarity = RARITY_ORDER[min(len(RARITY_ORDER) - 1, RARITY_ORDER.index(rarity) + 1)]
    price += {"common": 0, "uncommon": 0, "rare": 5, "mythic": 10}[rarity]

    material = rng.choice(_words(lexicon, "materials", "Iron"))
    name = _name(rng, lexicon, form_name, GEAR_PATTERNS,
                 _rarity_at_least(rarity, "rare"), material)
    return Item.model_validate({
        "id": f"forged_{form_id}_{rng.randrange(10 ** 8):08d}",
        "name": name, "slot": slot, "rarity": rarity,
        "level_min": max(1, min(tier, max((a["level_min"] for a in chosen), default=1))),
        "points_price": price,
        "flavor": rng.choice(_words(lexicon, "flavor", "Found, and kept.")),
        "art_desc": _art_desc(rng, lexicon, form_art, material, gear=True),
        "statics": statics, "affixes": [a["id"] for a in chosen],
    })


def forge_consumable(rng: random.Random, tier: int, lexicon: Dict[str, Any],
                     avoid: Optional[set] = None) -> Item:
    """One forged consumable: a recipe off the code table at the tier, named
    for a vessel out of the scenario's vocabulary. ``avoid`` holds the recipe
    and form ids this spread of spoils has already used."""
    tier = max(1, int(tier))
    pool = [r for r in CONSUMABLE_RECIPES if r["level_min"] <= tier] or CONSUMABLE_RECIPES[:1]
    fresh = [r for r in pool if r["id"] not in (avoid or ())]
    recipe = rng.choice(fresh or pool)
    form_id, form_name, family, form_art = _pick_form(rng, lexicon, "consumable",
                                                      recipe["family"], avoid=avoid)
    price = int(recipe["points"](tier))
    rarity = "common" if price <= 10 else ("uncommon" if price <= 18 else "rare")
    material = rng.choice(_words(lexicon, "materials", "Iron"))
    name = _name(rng, lexicon, form_name, CONSUMABLE_PATTERNS,
                 _rarity_at_least(rarity, "rare"), material)
    return Item.model_validate({
        "id": f"forged_{form_id}_{rng.randrange(10 ** 8):08d}",
        "name": name, "slot": "consumable", "rarity": rarity,
        "level_min": max(1, min(tier, recipe["level_min"])), "points_price": price,
        "flavor": rng.choice(_words(lexicon, "flavor", "Drink it and stop asking.")),
        "art_desc": _art_desc(rng, lexicon, form_art, material, gear=False),
        "effects": recipe["effects"](tier), "targets": {},
        "consumable": {"timing": recipe["timing"]},
        "affixes": [recipe["id"]],
    })


def forge_drops(party_size: int, tier: int, lexicon: Dict[str, Any],
                seed: Optional[int] = None) -> List[Item]:
    """T-83: (party + 1) gear and (party × 2) consumables, forged at the boss
    tier from this scenario's own vocabulary — never off the vendors' shelf.
    One spread never repeats a shape or a recipe while fresh ones remain."""
    rng = random.Random(seed)
    out: List[Item] = []
    used: set = set()          # form ids and recipe ids already spoken for
    party_size = max(1, int(party_size))
    for i in range(party_size + DROP_GEAR_PER_PARTY):
        slot = "weapon" if i % 2 == 0 else "accessory"
        it = forge_gear(rng, slot, tier, lexicon, avoid=used)
        used.add(it.id.split("_")[1])
        out.append(it)
    for _ in range(party_size * DROP_CONSUMABLES_PER_MEMBER):
        it = forge_consumable(rng, tier, lexicon, avoid=used)
        used.update({it.id.split("_")[1], it.affixes[0] if it.affixes else ""})
        out.append(it)
    return out
