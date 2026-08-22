"""Items — the base catalogue, the procedural vocabulary, and the gear helpers
(Design Update 17 §D17-4).

- **Catalogue**: the hand-curated balance floor under ``content/equipment/``
  (tracked; the Equipment tab writes new items to ``loadouts/equipment/``).
- **Procedural gear** = template × affix: templates are catalogue entries;
  affix tables carry mechanical riders (a keyword, a stat, a small granted
  ability) each with a points cost and a level_min. Mechanics are picked from
  tables IN CODE; names come from fragment tables (an LLM naming pass is a
  later polish). Nothing generated is ever off-vocabulary or off-budget.
- **Rollers**: boss drops (higher rarity, may roll banned-keyword affixes) and
  merchant stock (common/uncommon only, capped below the drop tier).
- **Gear helpers**: the run copy's ``gear`` block — slots, belt, inventory,
  capacity (T-80), equip/unequip/discard, worn points (T-81), pricing (T-86).
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ltg_core.schema import (
    BANNED_CREATION_KEYWORDS, BELT_SIZE, BUY_MULT, INVENTORY_CONSUMABLES,
    INVENTORY_GEAR, LEVEL_UP_POINTS, SELL_MULT, Item,
)
from ltg_core.translation import render_effects

from . import content

CATALOGUE_DIR = content.CONTENT_DIR / "equipment"
USER_ITEMS_DIR = content.LOADOUTS_DIR / "equipment"
ITEM_HIDDEN_FILE = content.LOADOUTS_DIR / "items_hidden.json"

RARITY_ORDER = ("common", "uncommon", "rare", "mythic")
# Phase III boss drops are NOT rolled off this catalogue — they are forged from
# the scenario's own lexicon (``loot.forge_drops``, T-83 / §D17-4.5). What lives
# here is the balance floor and the shelf merchants stock from.


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #
def _load_items(d: Path, source: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        raw = content._load_json(p)
        if raw is None or raw.get("kind") not in (None, "item"):
            continue
        raw = dict(raw)
        raw.pop("kind", None)
        try:
            item = Item.model_validate(raw)
        except Exception:
            continue
        out[item.id] = {"item": item, "source": source, "path": p}
    return out


def _registry() -> Dict[str, Dict[str, Any]]:
    reg = _load_items(CATALOGUE_DIR, "catalogue")
    reg.update(_load_items(USER_ITEMS_DIR, "user"))  # a user item shadows the catalogue's
    return reg


def _hidden() -> set:
    return content._read_id_set(ITEM_HIDDEN_FILE)


def item_meta(item: Item, source: str = "catalogue") -> Dict[str, Any]:
    return {
        "id": item.id, "name": item.name, "slot": item.slot, "rarity": item.rarity,
        "level_min": item.level_min, "points_price": item.points_price,
        "flavor": item.flavor, "art_url": item.art_url, "source": source,
        "summary": summarize(item), "description": describe(item),
    }


def _consumable_text(item: Item) -> str:
    """The consumable's effects in LTG card language ("Restore 3 HP to an
    ally."), falling back to the bare verb list only if rendering fails."""
    try:
        text = render_effects(list(item.effects), dict(item.targets))
    except Exception:
        text = ""
    return text or ", ".join(e.kind.replace("_", " ") for e in item.effects)


def summarize(item: Item) -> str:
    """One line of mechanics for lists and cards."""
    parts: List[str] = []
    for st in item.statics:
        if st.kind == "attack_mode":
            parts.append(f"{st.mode.value if st.mode else ''} weapon")
        elif st.kind == "power_bonus":
            parts.append(f"+{st.amount} Power")
        elif st.kind == "keyword":
            parts.append(str(st.keyword).replace("_", " "))
        elif st.kind == "stat":
            label = {"hp": "HP", "mana": "mana", "cards": "starting card"}[st.stat or "hp"]
            parts.append(f"+{st.amount} {label}{'s' if st.stat == 'cards' and st.amount != 1 else ''}")
        elif st.kind == "ability" and st.card:
            parts.append(f"grants {st.card.name}")
    if item.slot == "consumable":
        timing = item.consumable.timing if item.consumable else "instant"
        parts.append(f"{timing}: {_consumable_text(item)}")
    return " · ".join(parts)


def describe(item: Item) -> str:
    """The COMPLETE mechanics, one clause per line — the item detail view
    (`summarize` stays the compact one-liner for lists and cards)."""
    lines: List[str] = []
    for st in item.statics:
        if st.kind == "attack_mode":
            lines.append(f"A {st.mode.value if st.mode else ''} weapon.")
        elif st.kind == "power_bonus":
            lines.append(f"+{st.amount} Power while worn.")
        elif st.kind == "keyword":
            lines.append(f"Grants {str(st.keyword).replace('_', ' ')} while worn.")
        elif st.kind == "stat":
            noun = {"hp": "maximum HP", "mana": "mana capacity",
                    "cards": f"starting card{'s' if st.amount != 1 else ''}"}[st.stat or "hp"]
            lines.append(f"+{st.amount} {noun} while worn.")
        elif st.kind == "ability" and st.card:
            try:
                text = (st.card.translated_text or st.card.original_text
                        or render_effects(list(st.card.effects), dict(st.card.targets)))
            except Exception:
                text = ""
            lines.append(f"Grants the card “{st.card.name}” each encounter"
                         + (f": {text}" if text else "."))
    if item.slot == "consumable":
        timing = item.consumable.timing if item.consumable else "instant"
        speed = ("Drink it any time you could react (instant speed)."
                 if timing == "instant"
                 else "Drink it on your own turn, stack empty (sorcery speed).")
        lines.append(_consumable_text(item))
        lines.append(f"{speed} One use — it is consumed when it resolves.")
    return "\n".join(l for l in lines if l)


def list_items() -> List[Dict[str, Any]]:
    hidden = _hidden()
    return [item_meta(e["item"], e["source"]) for iid, e in _registry().items()
            if iid not in hidden]


def get_item(item_id: str) -> Optional[Item]:
    e = _registry().get(item_id)
    return e["item"].model_copy(deep=True) if e else None


def item_detail(item_id: str) -> Optional[Dict[str, Any]]:
    e = _registry().get(item_id)
    if e is None:
        return None
    return {**e["item"].model_dump(mode="json"), "source": e["source"]}


def save_item(raw: Dict[str, Any], item_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate + persist a user item (Options → Equipment → New / edit) under
    ``loadouts/equipment/`` — a catalogue id being edited is shadowed there."""
    raw = dict(raw)
    raw.pop("kind", None)
    raw.pop("source", None)
    if item_id:
        raw["id"] = item_id
    if not raw.get("id"):
        raw["id"] = content._slug(str(raw.get("name") or "item")) or "item"
    item = Item.model_validate(raw)
    USER_ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    (USER_ITEMS_DIR / f"{item.id}.json").write_text(
        json.dumps({"kind": "item", **item.model_dump(mode="json", exclude_none=True)},
                   indent=2, ensure_ascii=False))
    hidden = _hidden()
    if item.id in hidden:
        hidden.discard(item.id)
        content._write_id_set(ITEM_HIDDEN_FILE, hidden)
    return item_meta(item, "user")


def delete_item(item_id: str) -> None:
    e = _registry().get(item_id)
    if e is None:
        raise ValueError(f"unknown item: {item_id}")
    if e["source"] == "user":
        e["path"].unlink(missing_ok=True)
        if item_id not in _registry():
            return
    hidden = _hidden()
    hidden.add(item_id)
    content._write_id_set(ITEM_HIDDEN_FILE, hidden)


def set_item_art(item_id: str, url: str) -> None:
    e = _registry().get(item_id)
    if e is None:
        raise ValueError(f"unknown item: {item_id}")
    item = e["item"].model_copy(deep=True)
    item.art_url = url
    target = e["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"kind": "item", **item.model_dump(mode="json", exclude_none=True)},
                                 indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# The procedural vocabulary — affix tables + name fragments
# --------------------------------------------------------------------------- #
# Each affix: {id, slots (which templates it may ride), rarity_min, level_min,
# points, static}. `banned` affixes (the creation-banned keywords) roll only on
# boss drops (§D17-4.1). Costs sit on the level-up points scale so a rolled
# item's points_price = template price + affix points (+ a scarcity premium).
AFFIXES: List[Dict[str, Any]] = [
    {"id": "sturdy", "name": "Sturdy", "slots": ("weapon", "accessory"), "rarity_min": "common",
     "level_min": 1, "points": 5, "static": {"kind": "stat", "stat": "hp", "amount": 2}},
    {"id": "hale", "name": "of Vigour", "slots": ("weapon", "accessory"), "rarity_min": "uncommon",
     "level_min": 2, "points": 10, "static": {"kind": "stat", "stat": "hp", "amount": 4}},
    {"id": "attuned", "name": "Attuned", "slots": ("accessory",), "rarity_min": "uncommon",
     "level_min": 2, "points": 15, "static": {"kind": "stat", "stat": "mana", "amount": 1}},
    {"id": "clever", "name": "of Wits", "slots": ("accessory",), "rarity_min": "uncommon",
     "level_min": 2, "points": 15, "static": {"kind": "stat", "stat": "cards", "amount": 1}},
    {"id": "keen", "name": "Keen", "slots": ("weapon",), "rarity_min": "uncommon",
     "level_min": 2, "points": 10, "static": {"kind": "power_bonus", "amount": 1}},
    {"id": "reaching", "name": "Reaching", "slots": ("weapon",), "rarity_min": "uncommon",
     "level_min": 1, "points": 5, "static": {"kind": "keyword", "keyword": "reach"}},
    {"id": "trampling", "name": "Trampling", "slots": ("weapon",), "rarity_min": "rare",
     "level_min": 2, "points": 10, "static": {"kind": "keyword", "keyword": "trample"}},
    {"id": "swift", "name": "Swift", "slots": ("weapon", "accessory"), "rarity_min": "rare",
     "level_min": 3, "points": 15, "static": {"kind": "keyword", "keyword": "first_strike"}},
    {"id": "thirsting", "name": "Thirsting", "slots": ("weapon",), "rarity_min": "rare",
     "level_min": 3, "points": 15, "static": {"kind": "keyword", "keyword": "lifelink"}},
    {"id": "watchful", "name": "Watchful", "slots": ("accessory",), "rarity_min": "rare",
     "level_min": 4, "points": 20, "static": {"kind": "keyword", "keyword": "vigilance"}},
    # Creation-banned keywords — rare finds and boss drops, never in stock.
    # Warded (hexproof) is the most expensive rider in the table, above even
    # indestructible (§D19-3): indestructible turns off removal, but the party is
    # whittled down by DAMAGE anyway, whereas hexproof turns off the whole
    # targeted enemy suite — every curse, stun, silence, sap, drain and snipe —
    # for the rest of the encounter, leaving only basic attacks and area shapes.
    # Playtest: worn on one hero it deleted most of an encounter's kit.
    {"id": "warded", "name": "Warded", "slots": ("accessory",), "rarity_min": "mythic",
     "level_min": 6, "points": 40, "banned": True,
     "static": {"kind": "keyword", "keyword": "hexproof"}},
    {"id": "venomed", "name": "Venomed", "slots": ("weapon",), "rarity_min": "rare",
     "level_min": 5, "points": 25, "banned": True,
     "static": {"kind": "keyword", "keyword": "deathtouch"}},
    {"id": "unbroken", "name": "Unbroken", "slots": ("accessory",), "rarity_min": "mythic",
     "level_min": 6, "points": 35, "banned": True,
     "static": {"kind": "keyword", "keyword": "indestructible"}},
    {"id": "blighted", "name": "Blighted", "slots": ("weapon",), "rarity_min": "mythic",
     "level_min": 6, "points": 30, "banned": True,
     "static": {"kind": "keyword", "keyword": "infect"}},
]

# Name fragments: prefixes by affix are the affix names above; these are the
# suffix "of the …" pool for rare+ rolls, and the flavour lines by slot.
SUFFIXES = ["the Causeway", "the Reed-King", "Hollow Water", "the Old Watch", "Ashen Vows",
            "the Drowned Choir", "Salt and Iron", "the Last Lantern", "Bell-Metal", "the Long Night"]
FLAVOR_BY_SLOT = {
    "weapon": ["Someone died holding it. It did not mind.", "Balanced by a hand that knew.",
               "It remembers every neck.", "Cold in the morning, warm by noon."],
    "accessory": ["Small, and it changes everything.", "Worn smooth by older hands.",
                  "It hums when the lake is near.", "A gift, or a debt."],
    "consumable": ["Bitter, brown, and it works.", "Use it before you need it.",
                   "Do not ask what is in it.", "One swallow. Then run."],
}


def _rarity_at_least(r: str, floor: str) -> bool:
    return RARITY_ORDER.index(r) >= RARITY_ORDER.index(floor)


def _next_rarity(r: str) -> str:
    i = min(len(RARITY_ORDER) - 1, RARITY_ORDER.index(r) + 1)
    return RARITY_ORDER[i]


def _catalogue_templates(slot: str) -> List[Item]:
    return [e["item"] for e in _registry().values()
            if e["item"].slot == slot and e["item"].template is None]


def roll_item(rng: random.Random, slot: str, tier: int, boss: bool = False,
              max_rarity: str = "mythic") -> Optional[Item]:
    """Roll one procedural item: a catalogue template of ``slot`` at or below
    ``tier`` (level_min), plus 0–2 affixes chosen in code. This is the MERCHANT
    path — stock rolls cap at ``max_rarity`` (uncommon), in the template they
    draw as well as the affixes they take, and never take banned affixes. (A
    boss's spoils are not rolled here at all: they are forged from the
    scenario's lexicon — see ``loot.forge_drops``.)"""
    templates = [t for t in _catalogue_templates(slot)
                 if t.level_min <= max(1, tier) and _rarity_at_least(max_rarity, t.rarity)]
    if not templates:
        return None
    base = rng.choice(templates).model_copy(deep=True)
    if slot == "consumable":
        item = base
        item.template = base.id
        item.id = f"{base.id}_{rng.randrange(10**6):06d}"
        return item
    # Affix count: stock 0–1, drops 1–2 (bosses lean 2).
    n_affix = (rng.choice([0, 1, 1]) if not boss else rng.choice([1, 2, 2]))
    have_kinds = {(st.kind, st.stat, st.keyword) for st in base.statics}
    pool = [a for a in AFFIXES
            if slot in a["slots"] and a["level_min"] <= tier
            and (boss or not a.get("banned"))
            and _rarity_at_least(max_rarity, a["rarity_min"])
            and (a["static"]["kind"], a["static"].get("stat"), a["static"].get("keyword")) not in have_kinds]
    rng.shuffle(pool)
    chosen: List[Dict[str, Any]] = []
    for a in pool:
        if len(chosen) >= n_affix:
            break
        if any(c["static"]["kind"] == a["static"]["kind"] and c["static"].get("stat") == a["static"].get("stat")
               for c in chosen):
            continue
        chosen.append(a)
    item = base
    item.template = base.id
    item.affixes = [a["id"] for a in chosen]
    rarity = base.rarity
    price = base.points_price
    statics = [st.model_dump(mode="json", exclude_none=True) for st in base.statics]
    for a in chosen:
        statics.append(dict(a["static"]))
        price += int(a["points"])
        if _rarity_at_least(a["rarity_min"], rarity):
            rarity = a["rarity_min"]
    if boss and chosen and rng.random() < 0.5:
        rarity = _next_rarity(rarity)          # scarcity premium: a boss's find
    if not _rarity_at_least(max_rarity, rarity):
        rarity = max_rarity
    premium = {"common": 0, "uncommon": 0, "rare": 5, "mythic": 10}[rarity]
    price += premium
    # Name: prefixes for the first affix, "of …" for a second / a rare find.
    name = base.name
    if chosen:
        first = chosen[0]["name"]
        name = f"{first} {name}" if not first.startswith("of ") else f"{name} {first}"
        if len(chosen) > 1:
            second = chosen[1]["name"]
            name = f"{name} {second}" if second.startswith("of ") else f"{second} {name}"
    if _rarity_at_least(rarity, "rare") and " of " not in name:
        name = f"{name} of {rng.choice(SUFFIXES)}"
    item = Item.model_validate({
        **item.model_dump(mode="json", exclude_none=True),
        "id": f"{base.id}_{rng.randrange(10**6):06d}", "name": name,
        "rarity": rarity, "points_price": price, "statics": statics,
        "level_min": max(base.level_min, max((a["level_min"] for a in chosen), default=1)),
        "flavor": base.flavor if not chosen else rng.choice(FLAVOR_BY_SLOT[slot]),
    })
    return item


def roll_stock(function: str, tier: int, seed: Optional[int] = None) -> List[Item]:
    """Merchant stock (§D17-5.5): common/uncommon only, capped below the drop
    tier for the act; per location function."""
    rng = random.Random(seed)
    slot = {"weaponsmith": "weapon", "artificer": "accessory", "apothecary": "consumable"}.get(function)
    if slot is None:
        return []
    stock_tier = max(1, tier - 1) if tier > 1 else 1
    count = 4 if slot != "consumable" else 6
    out: List[Item] = []
    seen_names: set = set()
    for _ in range(count * 3):
        if len(out) >= count:
            break
        it = roll_item(rng, slot, stock_tier, boss=False, max_rarity="uncommon")
        if it and it.name not in seen_names:
            seen_names.add(it.name)
            out.append(it)
    return out


def buy_price(item: Item) -> int:
    return max(1, int(round(item.points_price * BUY_MULT))) if item.points_price else 1


def sell_price(item: Item) -> int:
    return int(item.points_price * SELL_MULT)


# --------------------------------------------------------------------------- #
# The gear block on a run's character copy (T-80)
# --------------------------------------------------------------------------- #
def empty_gear() -> Dict[str, Any]:
    return {"primary": None, "secondary": None, "accessory": None,
            "belt": [], "inventory": {"gear": [], "consumables": []}}


def gear_of(loadout: Dict[str, Any]) -> Dict[str, Any]:
    g = loadout.get("gear")
    if not isinstance(g, dict):
        g = empty_gear()
        loadout["gear"] = g
    g.setdefault("primary", None)
    g.setdefault("secondary", None)
    g.setdefault("accessory", None)
    g.setdefault("belt", [])
    inv = g.setdefault("inventory", {})
    inv.setdefault("gear", [])
    inv.setdefault("consumables", [])
    return g


def worn_items(loadout: Dict[str, Any]) -> List[Dict[str, Any]]:
    g = gear_of(loadout)
    return [x for x in (g["primary"], g["secondary"], g["accessory"]) if x]


def worn_points(loadout: Dict[str, Any]) -> int:
    """T-81: the points_price of everything worn (belt/inventory don't count)."""
    return sum(int(x.get("points_price", 0)) for x in worn_items(loadout))


def effective_level_bonus(loadout: Dict[str, Any]) -> int:
    return worn_points(loadout) // LEVEL_UP_POINTS


def all_items(loadout: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """(where, item) for every item on the character."""
    g = gear_of(loadout)
    out: List[Tuple[str, Dict[str, Any]]] = []
    for slot in ("primary", "secondary", "accessory"):
        if g[slot]:
            out.append((slot, g[slot]))
    out.extend(("belt", x) for x in g["belt"])
    out.extend(("inventory", x) for x in g["inventory"]["gear"])
    out.extend(("inventory", x) for x in g["inventory"]["consumables"])
    return out


def find_item(loadout: Dict[str, Any], item_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    for where, it in all_items(loadout):
        if it.get("id") == item_id:
            return where, it
    return None


def has_room(loadout: Dict[str, Any], item: Dict[str, Any]) -> bool:
    """Can this item be ADDED (into the belt / inventory) without overflow?"""
    g = gear_of(loadout)
    if item.get("slot") == "consumable":
        return (len(g["belt"]) < BELT_SIZE
                or len(g["inventory"]["consumables"]) < INVENTORY_CONSUMABLES)
    return len(g["inventory"]["gear"]) < INVENTORY_GEAR


def add_item(loadout: Dict[str, Any], item: Dict[str, Any]) -> str:
    """Land an item: a consumable onto the belt (or inventory when the belt is
    full); gear into the inventory. Returns where it went. Raises when full."""
    g = gear_of(loadout)
    item = copy.deepcopy(item)
    if item.get("slot") == "consumable":
        if len(g["belt"]) < BELT_SIZE:
            g["belt"].append(item)
            return "belt"
        if len(g["inventory"]["consumables"]) < INVENTORY_CONSUMABLES:
            g["inventory"]["consumables"].append(item)
            return "inventory"
        raise ValueError("no room for another consumable (belt and inventory full)")
    if len(g["inventory"]["gear"]) < INVENTORY_GEAR:
        g["inventory"]["gear"].append(item)
        return "inventory"
    raise ValueError("no room for more gear (inventory full)")


def remove_item(loadout: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    g = gear_of(loadout)
    for slot in ("primary", "secondary", "accessory"):
        if g[slot] and g[slot].get("id") == item_id:
            it = g[slot]
            g[slot] = None
            return it
    for lst in (g["belt"], g["inventory"]["gear"], g["inventory"]["consumables"]):
        for i, it in enumerate(lst):
            if it.get("id") == item_id:
                return lst.pop(i)
    raise ValueError("no such item on this character")


def equip(loadout: Dict[str, Any], item_id: str, slot: str) -> None:
    """Move an inventory/belt item into a gear slot (primary / secondary /
    accessory), swapping the current occupant back into the inventory (which
    must have room for it). Consumables can't be equipped; a belt slot is
    `to_belt`."""
    g = gear_of(loadout)
    found = find_item(loadout, item_id)
    if found is None:
        raise ValueError("no such item on this character")
    where, item = found
    if slot not in ("primary", "secondary", "accessory"):
        raise ValueError("equip into primary, secondary, or accessory")
    if item.get("slot") == "consumable":
        raise ValueError("consumables ride the belt, not a gear slot")
    if slot == "accessory" and item.get("slot") != "accessory":
        raise ValueError("only an accessory fits the accessory slot")
    if slot in ("primary", "secondary") and item.get("slot") != "weapon":
        raise ValueError("only a weapon fits a weapon slot")
    if where == slot:
        return
    current = g[slot]
    remove_item(loadout, item_id)
    if current is not None:
        if where in ("primary", "secondary", "accessory"):
            g[where] = current  # a straight swap between two worn slots
        elif len(g["inventory"]["gear"]) < INVENTORY_GEAR:
            g["inventory"]["gear"].append(current)
        else:
            # Roll back and refuse: nowhere to put the swapped-out piece.
            if where in ("primary", "secondary", "accessory"):
                g[where] = item
            else:
                g["inventory"]["gear"].append(item)
            raise ValueError("inventory full — discard or sell something first")
    g[slot] = item


def unequip(loadout: Dict[str, Any], slot: str) -> None:
    g = gear_of(loadout)
    if slot in ("primary", "secondary", "accessory"):
        it = g[slot]
        if it is None:
            return
        if len(g["inventory"]["gear"]) >= INVENTORY_GEAR:
            raise ValueError("inventory full — discard or sell something first")
        g[slot] = None
        g["inventory"]["gear"].append(it)
    else:
        raise ValueError("unequip primary, secondary, or accessory")


def to_belt(loadout: Dict[str, Any], item_id: str) -> None:
    g = gear_of(loadout)
    found = find_item(loadout, item_id)
    if found is None or found[1].get("slot") != "consumable":
        raise ValueError("no such consumable")
    if found[0] == "belt":
        return
    if len(g["belt"]) >= BELT_SIZE:
        raise ValueError("the belt is full")
    it = remove_item(loadout, item_id)
    g["belt"].append(it)


def from_belt(loadout: Dict[str, Any], item_id: str) -> None:
    g = gear_of(loadout)
    found = find_item(loadout, item_id)
    if found is None or found[0] != "belt":
        raise ValueError("no such belt item")
    if len(g["inventory"]["consumables"]) >= INVENTORY_CONSUMABLES:
        raise ValueError("the consumable inventory is full")
    it = remove_item(loadout, item_id)
    g["inventory"]["consumables"].append(it)


def consume_used(loadout: Dict[str, Any], used_ids: List[str]) -> None:
    """After an encounter: drop the belt items that were drunk (their cards
    were exiled with `consumable_id`)."""
    g = gear_of(loadout)
    g["belt"] = [x for x in g["belt"] if x.get("id") not in set(used_ids)]
