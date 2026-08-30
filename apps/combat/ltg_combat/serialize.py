"""Turn engine values into JSON the cockpit front end renders — presentation only.

This module owns ZERO rules. It reads a `GameState` and the `legal_actions` the
engine reported and arranges them for display: stat lines, mana-by-colour, the
stack, and a two-click action menu. Every action in the menu is one the engine
already offered (referenced by its index in the legal list); the grouping is pure
layout. It also emits a raw, recursive dump of every entity for the inspector.
"""

from __future__ import annotations

import dataclasses
import math
from collections import Counter
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ltg_core.schema import Card, Timing
from ltg_core.translation import channel_break_clause, render_effects
from .state import Action, GameState

_WUBRG = ["W", "U", "B", "R", "G"]
_COLOR_NAME = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}


# --------------------------------------------------------------------------- #
# Recursive JSON dump (the inspector's "raw underlying state")
# --------------------------------------------------------------------------- #
def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / pydantic models / enums into JSON."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #
def cost_pips(card: Card) -> str:
    pips = ""
    if getattr(card.cost, "x", False):
        pips += "{X}"  # an {X} cost — the cast chooses X (engine offers one per value)
    if card.cost.generic:
        pips += "{" + str(card.cost.generic) + "}"
    counts = {c.value: n for c, n in card.cost.colors.items()}
    for color in _WUBRG:
        pips += ("{" + color + "}") * counts.get(color, 0)
    return pips or "{0}"


def card_dict(card: Card) -> Dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "cost": cost_pips(card),
        "timing": card.timing.value,
        "rarity": card.rarity.value,
        "level": card.level,
        "type": card.type,
        "text": card_text(card),
        # Card art, when the card carries any: today only a consumable (it
        # inherits its item's art — §D17-4.4). "" leaves the sigil placeholder.
        "image": card.image or "",
    }


def card_text(card: Card) -> str:
    """The rules text a card FACE shows. Authored/translated text wins; a card
    with neither (a consumable minted from an item — §D17-4.4 — has effects but
    no prose) renders its effects, so every card in hand reads as a full card."""
    text = card.translated_text or card.original_text or ""
    if text:
        return text
    try:
        return render_effects(list(card.effects), dict(card.targets),
                              channeled=card.timing == Timing.channeled)
    except Exception:  # never let a display render break a snapshot
        return ""


def _pip_str(colors: List[str]) -> str:
    counts = Counter(colors)
    return "".join(("{" + c + "}") * counts[c] for c in _WUBRG if counts[c]) or "{0}"


def _channel_countdown(state: GameState, ch) -> Optional[int]:
    """Upkeeps until the channel's soonest `after_turns` trigger fires (§D22-4)
    — the visible count that goes down each Upkeep. None when no countdown is
    pending (no after_turns effects, or every one has already fired)."""
    elapsed = state.turn - getattr(ch, "started_turn", state.turn)
    pending = [t.after_turns - elapsed
               for t in (getattr(e, "trigger", None) for e in ch.effects)
               if getattr(t, "after_turns", None) is not None
               and t.after_turns - elapsed > 0]
    return min(pending) if pending else None


# --------------------------------------------------------------------------- #
# Veiled intents (Design Update 08 §D8-1): the category is DERIVED
# deterministically from the declared intent — verbs, action_type, target
# descriptor — never authored. The engine emits category + target; the template
# line below is presentation (freely rewordable without touching the engine).
# --------------------------------------------------------------------------- #
_HOSTILE_KINDS = {"deal_damage", "lose_life", "destroy", "exile", "bounce", "stun",
                  "taunt", "wound", "sap", "poison", "fight", "strip_intent",
                  "break_channel",
                  # Enemies only ever use the HOSTILE action modifiers (Hamstring,
                  # Drain Ult, stripping reach), so one on an intent is hostile —
                  # without this it would classify as "support" to the player.
                  "modify_action",
                  "remove_keyword", "counter"}

# The lockdown family: hostile verbs that take away what a hero can DO rather
# than chewing through HP. They read as their own category ("interference") so a
# Hamstring or a Silence never wears the same word as a sword swing — the player
# needs to know which kind of trouble is coming, since the answers differ.
_CONTROL_KINDS = {"stun", "taunt", "strip_intent", "remove_keyword", "counter",
                  "sap", "modify_action", "prevent", "move_card", "break_channel"}

# Side-sensitive verbs: hostile only when they reach the PARTY. An enemy's
# `prevent` is usually a Ward on itself (support); aimed at a hero it is a
# Silence or a Pacifism. A `move_card` means nothing unless it hits a hand.
_SIDE_SENSITIVE_HOSTILE = {"prevent", "move_card"}


def _aims_at_party(effect) -> bool:
    desc = getattr(effect, "target", None)
    side = getattr(desc, "side", None)
    return getattr(side, "value", side) in ("ally", "any")


def _hostile_verb(effect) -> bool:
    """Does this verb harm the party? (Read from the ENEMY's authoring frame,
    where side "ally" means the hero side.)"""
    kind = getattr(effect, "kind", None)
    if kind in _SIDE_SENSITIVE_HOSTILE:
        return _aims_at_party(effect)
    return kind in _HOSTILE_KINDS


def intent_category(intent) -> str:
    """One of the closed set: threat / spellcraft / interference / row assault /
    party assault / gathering / support / summon / manoeuvre (§D8-1.2). Multi-verb
    intents classify by their first hostile verb; a `charge` verb anywhere
    classifies as gathering (the windup dominates the fiction). Row-scoped shapes
    (§D9-3.2 — a `rows` filter or a row/blast `scope`) read as a row assault, and
    lockdown verbs read as interference whatever their shape."""
    if intent is None:
        return "threat"
    if getattr(intent, "kind", "action") == "move":
        return "manoeuvre"
    if getattr(intent, "target_row", None):
        return "row assault"    # §L-5 positional intent: aimed at a row outright
    kinds = [getattr(e, "kind", None) for e in intent.effects]
    if "charge" in kinds:
        return "gathering"
    if intent.action_type == "spell":
        return "spellcraft"
    if "create_token" in kinds:
        return "summon"
    first_hostile = next((e for e in intent.effects if _hostile_verb(e)), None)
    if first_hostile is not None:
        # Lockdown classifies as INTERFERENCE whatever its shape — a party-wide
        # Hamstring is not an "assault", and calling it one would send the player
        # reaching for the wrong answer. A mixed intent still reads by its FIRST
        # hostile verb, so "deal 5 and stun" stays a threat: the damage dominates.
        if getattr(first_hostile, "kind", None) in _CONTROL_KINDS:
            return "interference"
        desc = getattr(first_hostile, "target", None)
        mode = getattr(desc, "mode", None)
        mode = getattr(mode, "value", mode)
        side = getattr(desc, "side", None)
        side = getattr(side, "value", side)
        scoped = getattr(desc, "rows", None) or getattr(desc, "scope", None)
        if scoped and (mode == "chosen" or side in ("ally", "any")):
            return "row assault"    # §D9-3.2: a row or blast shape on the party
        if mode == "all" and side in ("ally", "any"):
            return "party assault"  # hostile mode:all on the hero side
        return "threat"
    if intent.effects:
        return "support"
    return "threat"


def _veiled_entry(state: GameState, enemy, intent, status: str, reveal: str,
                  slot: int) -> Optional[Dict[str, Any]]:
    if intent is None and status not in ("stunned",):
        return None
    category = intent_category(intent) if intent is not None else "none"
    target_id = intent.target_id if intent is not None else None
    target_name = _name_of(state, target_id)
    rows = intent_rows(intent)
    target_row = (getattr(intent, "target_row", None) if intent is not None else None) \
        or (rows[0] if rows else None)
    line = _veiled_line(enemy, category, target_id, target_name, status, slot,
                        target_row=target_row, rows=rows)
    return {
        "enemy_id": enemy.id,
        "creature_id": enemy.id,          # legacy key the client already reads
        "creature_name": enemy.name,
        "category": category,
        "target_id": target_id,
        "target_name": target_name,
        "line": line,
        "status": status,                 # declared|stripped|stunned|executed|fizzled
        "reveal": reveal,
        "slot": slot,                     # 1, or 2 for a boss-fury second intent (§D9-4)
        # A positional intent's row (§L-5): aimed at ground, not a name — the
        # client renders the row highlight from this (target_id stays None).
        "target_row": target_row,
        # The full footprint (§D18-4): one row for a row shape, three for a
        # blast — every row the client should light, not just the primary.
        "target_rows": rows,
    }


def veiled_intent(state: GameState, enemy) -> Optional[Dict[str, Any]]:
    """The §D8-1.1 pre-stack information contract for one enemy: exactly a
    category and a locked target — never names, verbs, magnitudes, or whether it
    is a channel. `status`/`reveal` drive the intents window (§D8-1.5): a
    stripped line is struck and annotated with what it would have been."""
    intent = enemy.round_intent if enemy.round_intent is not None else enemy.intent
    status = getattr(enemy, "round_intent_status", "declared" if intent else "none")
    return _veiled_entry(state, enemy, intent, status,
                         getattr(enemy, "round_intent_reveal", ""), 1)


def veiled_intents(state: GameState, enemy) -> List[Dict[str, Any]]:
    """Every veiled line this enemy declared this round — two for an enraged
    boss (§D9-4: fury is twice as loud), one otherwise."""
    out = []
    first = veiled_intent(state, enemy)
    if first is not None:
        out.append(first)
    intent2 = (enemy.round_intent2 if enemy.round_intent2 is not None
               else enemy.intent2)
    second = _veiled_entry(state, enemy, intent2,
                           getattr(enemy, "round_intent2_status", "none"),
                           getattr(enemy, "round_intent2_reveal", ""), 2)
    if second is not None:
        out.append(second)
    return out


def intent_rows(intent) -> List[str]:
    """The GROUND a positional / row-shaped intent covers (§D18-4).

    Works on an Intent (the telegraph) and on a StackItem (the same blow once it
    is on the stack) alike — both carry `target_row` and the verbs.

    `target_row` when the engine declared one (every enemy row shape does now),
    otherwise read straight back off the verbs — so a hand-authored or legacy
    `rows` footprint still names its row instead of the old anonymous "a row of
    your party", which told the party to move without telling them where from."""
    if intent is None:
        return []
    rows: List[str] = []
    for eff in getattr(intent, "effects", []) or []:
        desc = getattr(eff, "target", None)
        side = getattr(getattr(desc, "side", None), "value", getattr(desc, "side", None))
        if side not in ("ally", "any"):
            continue                      # a self/own-side rider marks no ground
        for r in (getattr(desc, "rows", None) or []):
            name = getattr(r, "value", r)
            if name not in rows:
                rows.append(name)
    primary = getattr(intent, "target_row", None)
    if primary and primary not in rows:
        rows.insert(0, primary)
    elif primary:
        rows.remove(primary)
        rows.insert(0, primary)
    return rows


def _rows_phrase(rows: List[str]) -> str:
    """"your front row" / "your front and mid rows" — the blast footprint reads
    as the several rows it actually covers."""
    if len(rows) == 1:
        return f"your {rows[0]} row"
    return "your " + ", ".join(rows[:-1]) + f" and {rows[-1]} rows"


def _veiled_line(enemy, category: str, target_id, target_name,
                 status: str, slot: int = 1, target_row=None, rows=None) -> str:
    """The generic template line (§D8-1.2). Presentation only."""
    name = enemy.name
    if status == "stunned":
        if slot == 2:
            return f"{name}'s fury is dulled — the stun suppresses one intent."
        return f"{name} reels — it has no intent."
    tname = target_name or "your party"
    if category == "threat":
        return f"{name} threatens {tname}."
    if category == "spellcraft":
        if rows:  # a positional spell names its ground (§L-5 / §D18-4)
            return f"{name} begins casting a spell at {_rows_phrase(rows)}."
        if target_id == enemy.id:   # a self-buff read as "…casting a spell at itself"
            return f"{name} begins working a spell on itself."
        if target_id is not None:
            return f"{name} begins casting a spell at {tname}."
        return f"{name} begins casting a spell."
    if category == "party assault":
        return f"{name} prepares an assault on your whole party."
    if category == "row assault":
        if rows:  # §L-5 / §D18-4: the telegraph IS the floor circle — name the ground
            return f"{name} prepares an assault on {_rows_phrase(rows)}."
        return f"{name} prepares an assault on a row of your party."
    if category == "interference":
        if target_id is None:
            return f"{name} moves to foil your party."
        return f"{name} moves to foil {tname}."
    if category == "gathering":
        return f"{name} gathers its power."
    if category == "support":
        if target_id is None or target_id == enemy.id:
            return f"{name} steels itself."
        return f"{name} turns its attention to {tname}."
    if category == "summon":
        return f"{name} calls for reinforcements."
    if category == "manoeuvre":
        return f"{name} shifts its footing."
    return f"{name} bides its time."


# --------------------------------------------------------------------------- #
# Combatants
# --------------------------------------------------------------------------- #
def _mana_by_color(char) -> List[Dict[str, Any]]:
    """Per-colour available / capacity / reserved — reserved shown distinctly."""
    avail = Counter(char.pool)
    cap = Counter(char.mana_colors)
    reserved = Counter(char.reserved)
    out = []
    for color in _WUBRG:
        if cap.get(color) or reserved.get(color):
            out.append({
                "color": color,
                "available": avail.get(color, 0),
                "capacity": cap.get(color, 0),
                "reserved": reserved.get(color, 0),
            })
    return out


def _lane_text(parameter: str, combat_kind: str = "all") -> str:
    """A damage lane + its combat qualifier as a status-tag word: `combat_damage`
    with combat_kind melee → "melee combat_damage"; everything else is the lane."""
    if parameter == "combat_damage" and combat_kind in ("melee", "ranged"):
        return f"{combat_kind} {parameter}"
    return parameter


# Short status-line words for the durational action modifiers (the two instant
# ones never ride a character, so they never appear here).
_ACTION_MOD_TAG = {
    "make_ranged": "attack: ranged", "make_melee": "attack: melee",
    "switch_mode": "attack: reach switched",
    "defend_as_reaction": "defend: reaction", "defend_double": "defend: ×2",
    "mitigate_again": "mitigate: unlimited", "mitigate_full": "mitigate: full Power",
    "lock_skill": "hamstrung (no Skill)",
}


def _status_tags(char) -> List[str]:
    tags = []
    if getattr(char, "temp_mod", 0):
        tags.append(f"{'+' if char.temp_mod >= 0 else ''}{char.temp_mod} temp HP")
    if char.prevent_pool:
        tags.append(f"reduce {char.prevent_pool}")
    if getattr(char, "capacity_mod", 0):
        tags.append(f"{char.capacity_mod} mana capacity")   # `sap` (always negative)
    for mod in _action_mods(char):
        tags.append(_ACTION_MOD_TAG.get(mod, mod.replace("_", " ")))
    for tag in getattr(char, "prevent_tags", []):
        # The ACTION shields read as their condition, not as "prevent <x>":
        # "silenced" and "pacified" are what the player is actually looking for.
        if tag.parameter == "cast":
            tags.append("silenced")
            continue
        if tag.parameter == "attack":
            tags.append("pacified")
            continue
        span = "next " if tag.uses is not None else ""
        tags.append(f"prevent {span}{_lane_text(tag.parameter, getattr(tag, 'combat_kind', 'all'))}")
    for tag in getattr(char, "amplify_tags", []):
        boost = (f"×{tag.multiplier}" if tag.multiplier > 1 else "") + \
                (f"+{tag.bonus}" if tag.bonus else "")
        what = {"heal": "heal"}.get(
            tag.event, _lane_text(tag.event, getattr(tag, "combat_kind", "all")).replace("_", " "))
        tags.append(f"next {what} {boost}")
    for filt in getattr(char, "double_next", []):
        tags.append(f"next {filt} ×2 resolve")
    if getattr(char, "power_bonus", 0):
        tags.append(f"{'+' if char.power_bonus >= 0 else ''}{char.power_bonus} Power")
    for ptag in getattr(char, "protection_tags", []):
        tags.append(f"protection ({_lane_text(ptag.parameter, ptag.combat_kind)})")
    if getattr(char, "poison_counters", 0):
        tags.append(f"poison ×{char.poison_counters}")
    if getattr(char, "regen_counters", 0):
        tags.append(f"regen ×{char.regen_counters}")
    if getattr(char, "charge", 0):
        tags.append(f"charge ×{char.charge}")
    for kw in getattr(char, "keywords", {}):
        tags.append(f"⚜ {kw}")
    if getattr(char, "acted_mode", None) and char.alive and not char.turn_ended:
        tags.append(char.acted_mode)
    if getattr(char, "turn_ended", False):
        tags.append("turn done")
    if not char.alive:
        tags.append("incapacitated")
    return tags


def _action_mods(char) -> Dict[str, str]:
    return getattr(char, "action_mods", None) or {}


def _mitigate_value(char) -> int:
    """X = ceil(current Power / 2) — the per-hit Mitigate reduction (Update 02
    §M-A.2), or full Power under a `mitigate_full` action modifier."""
    power = max(0, char.current_power)
    if "mitigate_full" in _action_mods(char):
        return power
    return math.ceil(power / 2)


def _defend_value(char) -> int:
    """Defend's temp-HP buffer = BASE Power, doubled by `defend_double` (mirrors
    engine._defend_value; this module states rules for display only, the same way
    _mitigate_value does)."""
    value = max(0, getattr(char, "power", 0))
    return value * 2 if "defend_double" in _action_mods(char) else value


def _has_defender(char) -> bool:
    return "defender" in (getattr(char, "keywords", {}) or {})


def _character_dict(state: GameState, char) -> Dict[str, Any]:
    return {
        "id": char.id,
        "name": char.name,
        "archetype": char.archetype or "character",
        "hp": char.hp,
        "max_hp": char.max_hp,
        "effective_hp": char.effective_hp,
        "alive": char.alive,
        "power": char.current_power,
        "base_power": char.power,
        "power_bonus": char.power_bonus,
        "attack_mode": char.attack_mode,
        "level": char.level,
        "capacity": char.capacity,
        "row": char.row,
        "mitigate_value": _mitigate_value(char),
        "temp_mod": char.temp_mod,
        "prevent_pool": char.prevent_pool,
        "acted_mode": char.acted_mode,
        "turn_ended": char.turn_ended,
        "mana": _mana_by_color(char),
        "reserved_pips": _pip_str(char.reserved),
        "status_tags": _status_tags(char),
        "channels": [{
            "card_id": ch.card.id,
            "card_name": ch.card.name,
            "reserved_pips": _pip_str(ch.reserved),
            "target_id": ch.target_id,
            "target_name": _name_of(state, ch.target_id),
            "text": ch.card.translated_text or "",
            # What ending this channel will fire ("" when it has no break trigger)
            # — the Channels modal shows it as a warning note next to Drop.
            "break_text": channel_break_clause(ch.effects, ch.card.targets),
            # §D22-4: the live after_turns countdown — Upkeeps until the
            # soonest countdown trigger fires (None when the card has none).
            "countdown": _channel_countdown(state, ch),
        } for ch in char.channels],
        "hand": [card_dict(c) for c in char.hand],
        "library": [card_dict(c) for c in char.library],
        "stance": _stance_block(char),
        "evergreen": _evergreen_block(char),
        # Heroic actions (D8-3): the once-per-encounter Skill/Ultimate and the
        # public 0–100 ultimate gauge — served as a PERCENTAGE of the level-
        # scaled charge cost (gauge rework), so the client bar stays /100.
        "skill": _heroic_block(char.skill, char.skill_used),
        "ultimate": _heroic_block(char.ultimate, char.ultimate_used),
        "ultimate_gauge": getattr(char, "ultimate_gauge_pct", 0),
        "poison_counters": getattr(char, "poison_counters", 0),
        "regen_counters": getattr(char, "regen_counters", 0),
        # Charge counters (§D22-1): heroes hold the windup gauge too.
        "charge": getattr(char, "charge", 0),
        "poisoned": getattr(char, "poison_counters", 0) > 0,
        "regenerating": getattr(char, "regen_counters", 0) > 0,
        "raw": to_jsonable(char),
    }


def _heroic_block(card: Optional[Card], used: bool) -> Optional[Dict[str, Any]]:
    """A Skill/Ultimate as the client sees it: the card face + its spent flag."""
    if card is None:
        return None
    return {**card_dict(card), "used": used}


_STANCE_SLOT_NAMES = ("attack", "defend", "mitigate", "move")


def _stance_block(char) -> Optional[Dict[str, Any]]:
    """The holder's active stance (§D9-2), or None: the stance card's name and,
    per main-ability slot, 'unchanged' | 'removed' | the replacement's name —
    what the UI needs to badge the rewired abilities."""
    for ch in getattr(char, "channels", []) or []:
        for e in ch.card.effects:
            if getattr(e, "kind", None) != "stance":
                continue
            slots = {}
            for slot in _STANCE_SLOT_NAMES:
                v = getattr(e, slot)
                slots[slot] = v if isinstance(v, str) else {
                    "name": v.name or "replaced",
                }
            return {"card_id": ch.card.id, "card_name": ch.card.name,
                    "slots": slots}
    return None


def _evergreen_block(char) -> Dict[str, Any]:
    """The three evergreen abilities, wearing their optional authored flavour
    (D8-3.4): the custom display name and one-line text are presentation only."""
    flavor = getattr(char, "ability_flavor", {}) or {}

    def entry(key: str, default_name: str, text: str) -> Dict[str, str]:
        f = flavor.get(key) or {}
        return {"name": f.get("name") or default_name, "text": text,
                "flavor": f.get("text") or ""}

    return {
        "offensive": entry("attack", "Basic Attack",
                           f"Deal {char.attack_mode} damage equal to Power ({char.current_power})."),
        "defensive_action": entry("defend", "Defend",
                                  f"Gain temporary HP equal to base Power "
                                  f"({_defend_value(char)}) — a buffer that fades at "
                                  f"end of turn."
                                  + (" Free (Defender)." if _has_defender(char) else "")),
        "defensive_reaction": entry("mitigate", "Mitigate",
                                    f"Reduce each hit of an incoming attack by ceil(Power/2) = "
                                    f"{_mitigate_value(char)}; or intercept for an adjacent ally."),
    }


def _enemy_dict(state: GameState, enemy) -> Dict[str, Any]:
    intent = None
    if enemy.intent is not None:
        intent = {
            "name": enemy.intent.name,
            "amount": enemy.intent.attack_damage(enemy.power_bonus),
            "target_id": enemy.intent.target_id,
            "target_name": _name_of(state, enemy.intent.target_id),
            "target_row": enemy.intent.target_row,  # §L-5 positional aim
        }
    intent2 = None
    if enemy.intent2 is not None:  # boss fury (§D9-4): the second declared intent
        intent2 = {
            "name": enemy.intent2.name,
            "amount": enemy.intent2.attack_damage(enemy.power_bonus),
            "target_id": enemy.intent2.target_id,
            "target_name": _name_of(state, enemy.intent2.target_id),
            "target_row": enemy.intent2.target_row,  # §L-5 positional aim
        }
    return {
        "id": enemy.id,
        "name": enemy.name,
        "hp": enemy.hp,
        "max_hp": enemy.max_hp,
        "effective_hp": enemy.effective_hp,
        "level": enemy.level,
        "row": enemy.row,
        "attack_mode": enemy.attack_mode,
        "alive": enemy.alive,
        "in_hand": enemy.in_hand,   # bounced: off the battlefield, pending redeploy (Update 03)
        "zone": "in_hand" if enemy.in_hand else ("exile" if enemy.exiled else "in_play"),
        "temp_mod": enemy.temp_mod,
        "prevent_pool": enemy.prevent_pool,
        "prevent_tags": [f"{'next ' if t.uses is not None else ''}"
                         f"{_lane_text(t.parameter, getattr(t, 'combat_kind', 'all'))}"
                         for t in enemy.prevent_tags],
        # A count (what the clients render as "protection ×N") plus the lanes.
        "protection": len(enemy.protection_tags),
        "protection_tags": [_lane_text(t.parameter, t.combat_kind)
                            for t in enemy.protection_tags],
        "stunned": enemy.stunned,
        "power_bonus": enemy.power_bonus,
        "keywords": list(enemy.keywords.keys()),
        "intent": intent,
        "intent2": intent2,
        # The `rises` trait is PUBLIC (§D9-1.5): the veil hides intents, not bodies.
        "rises": getattr(enemy, "rises", None),
        "poison_counters": getattr(enemy, "poison_counters", 0),
        "regen_counters": getattr(enemy, "regen_counters", 0),
        "poisoned": getattr(enemy, "poison_counters", 0) > 0,
        "regenerating": getattr(enemy, "regen_counters", 0) > 0,
        # The charge gauge (D8-2.4): count and threshold pips are public; the
        # triggered component's content is not (the cockpit's raw dump has it).
        "charge": getattr(enemy, "charge", 0),
        "charge_threshold": _enemy_charge_threshold(enemy),
        "raw": to_jsonable(enemy),
    }


def _enemy_charge_threshold(enemy) -> Optional[int]:
    thresholds = [c.charge_threshold for c in getattr(enemy, "components", [])
                  if getattr(c, "trigger", None) == "on_charge_full"
                  and getattr(c, "charge_threshold", None)]
    return min(thresholds) if thresholds else None


def _token_dict(state: GameState, token) -> Dict[str, Any]:
    controlled_by = getattr(token, "controlled_by", None)
    return {
        "id": token.id,
        "name": token.name,
        "hp": token.hp,
        "max_hp": token.max_hp,
        "power": token.power,
        "row": token.row,
        "alive": token.alive,
        "poison_counters": getattr(token, "poison_counters", 0),
        "regen_counters": getattr(token, "regen_counters", 0),
        # Control chip (§D9-1.4): who holds it, rounds remaining (None ==
        # encounter), and the flavour — a dominated living enemy vs raised undead.
        "controlled_by": controlled_by,
        "control_left": getattr(token, "control_left", None),
        "control_kind": (None if controlled_by is None else
                         ("dominated" if getattr(token, "revert", None) is not None
                          else "undead")),
        "raw": to_jsonable(token),
    }


def _corpse_dict(corpse) -> Dict[str, Any]:
    """A corpse marker (§D9-1.7): small and dim on its row — information, not
    spectacle. `stirring` > 0 drives the subtle pulse and the chronicle line."""
    return {
        "id": corpse.id,
        "name": corpse.name,
        "row": corpse.row,
        "level": corpse.level,
        "power": corpse.power,
        "max_hp": corpse.max_hp,
        "stirring": corpse.stirring,
        "is_boss": corpse.is_boss,
    }


def _name_of(state: GameState, cid: Optional[str]) -> Optional[str]:
    if cid is None:
        return None
    if isinstance(cid, str) and cid.endswith("::2"):  # second-intent handle (§D9-4)
        base = _name_of(state, cid[:-3])
        return f"{base} — second intent" if base else cid
    c = state.combatant(cid)
    if c is not None:
        return c.name
    corpse = state.corpse(cid)
    return f"{corpse.name} (corpse)" if corpse is not None else cid


# --------------------------------------------------------------------------- #
# Stack
# --------------------------------------------------------------------------- #
def action_mode(kind: str, attack_mode: Optional[str],
                combat_ability: bool = False) -> Optional[str]:
    """The classification tag shown beside an action (stack row / banner / intent),
    in the engine's own vocabulary: **spell | attack | ability | combat ability**
    (GDD taxonomy).

    Melee/ranged qualifies ATTACKS ONLY — "melee attack" / "ranged attack". An
    ability always reads "ability", even when its owner is a ranged creature: the
    old behaviour let an enemy ability wear its owner's reach ("Life Leech (ranged)"),
    which read as an attack and hid why combat-damage prevention didn't stop it.
    The tag names the item's damage lane, so what answers it is legible at a glance
    — which is why a DAMAGING ability reads "combat ability" (§M-A.7): it sits in
    the combat lane, so a plain "ability" tag would now hide the very thing the tag
    exists to show."""
    if kind == "spell":
        return "spell"
    if kind == "attack":
        reach = attack_mode if attack_mode in ("melee", "ranged") else "melee"
        return f"{reach} attack"
    if kind in ("ability", "activated", "triggered"):
        return "combat ability" if combat_ability else "ability"
    return None


def _stack_mechanics(state: GameState, item) -> str:
    """The complete mechanical read of a non-card stack action (an enemy
    ability's flavour name means nothing on its own) — the UI shows it on
    hover. Card-backed actions return "" (the hover pops the full card)."""
    if item.card is not None:
        return ""
    parts: List[str] = []
    if item.kind == "attack" and item.attack_power is not None:
        # Recomputed the way resolution will: base Power + the source's CURRENT
        # bonus (R-7) — a wound landing while this sits on the stack changes it.
        src = state.combatant(item.source_id)
        bonus = getattr(src, "power_bonus", 0) if src is not None else 0
        dmg = max(0, item.attack_power + bonus)
        reach = item.attack_mode if item.attack_mode in ("melee", "ranged") else "melee"
        where = (f"every character standing in the {item.target_row} row"
                 if item.target_row else "the target")
        parts.append(f"Deals {dmg} {reach} combat damage to {where}.")
    if item.effects:
        try:
            text = render_effects(list(item.effects))
        except Exception:
            text = ""
        if text:
            if item.target_row:
                text = f"Strikes every character in the {item.target_row} row: {text}"
            parts.append(text)
    if item.starts_channel:
        parts.append("On resolve this begins a channelled effect — counter it "
                     "on the stack to stop the channel from ever starting.")
    if item.combat_ability and item.kind != "attack":
        # §M-A.7: say WHY a raised guard answers an "ability", or the player reads
        # the offer as a bug. The AoE case earns the plainer second sentence.
        parts.append("This ability DEALS DAMAGE, so it counts as combat damage — "
                     "combat-damage shields cover it and on-attack effects see it."
                     + (" Mitigate can answer it."
                        if item.target_id is not None and item.target_row is None
                        else " Its damage is too broad for one character to "
                             "step in front of."))
    return " ".join(parts)


def _stack_list(state: GameState) -> List[Dict[str, Any]]:
    out = []
    for i, item in enumerate(reversed(state.stack)):  # top first
        out.append({
            "label": item.label,
            "kind": item.kind,
            "mode": action_mode(item.kind, item.attack_mode, item.combat_ability),
            "source_id": item.source_id,
            "source_name": _name_of(state, item.source_id),
            "source_side": item.source_side,
            # §M-A.7: an ability-class action that deals damage — the client badges
            # it so "why can I Mitigate this?" answers itself.
            "combat_ability": item.combat_ability,
            "target_id": item.target_id,
            "target_name": _name_of(state, item.target_id),
            "reserved_pips": _pip_str(item.reserved),
            # The full card behind the action (a cast / a card-carried trigger),
            # so the UI can show it on hover; None for attacks & enemy components.
            "card": card_dict(item.card) if item.card is not None else None,
            "mechanics": _stack_mechanics(state, item),
            # §D18-4: the ground this action covers, so the board keeps the row
            # lit from the telegraph all the way through the swing on the stack.
            "target_rows": intent_rows(item),
            "top": i == 0,
            "raw": to_jsonable(item),
        })
    return out


_PHASE_LABEL = {
    "upkeep": "upkeep", "capacity": "start of turn — lock mana", "draw": "upkeep",
    "intents": "enemy intents", "player": "player actions", "allies": "ally actions",
    "enemy": "enemy actions", "end": "end step",
}


def phase_label(state: GameState) -> str:
    if state.result is not None:
        return "game over"
    if state.stack:
        return "reaction window"
    return _PHASE_LABEL.get(state.phase, state.phase)


# --------------------------------------------------------------------------- #
# Encounter objectives (Design Update 12 §D12-1.5) — fully public, no veil
# --------------------------------------------------------------------------- #
def objective_block(state: GameState) -> Optional[Dict[str, Any]]:
    """The objective banner's data: kind, status, and the pinned first line of
    the intents window. None when the encounter carries no objective."""
    obj = state.objective
    if obj is None:
        return None
    remaining = max(0, obj.turns - obj.rounds_done)
    plural = "" if remaining == 1 else "s"
    waves_total = len(obj.waves) + 1
    if obj.kind == "survive":
        line = f"Survive: {remaining} round{plural} remain"
    elif obj.kind == "waves":
        line = f"Wave {obj.wave_index + 1} of {waves_total}"
    elif obj.kind == "deadline":
        line = f"Defeat every enemy — {remaining} round{plural} remain"
    else:  # race
        target = state.enemy(obj.target_id) if obj.target_id else None
        name = target.name if target is not None else "the marked enemy"
        if obj.status == "complete":
            line = "The doom clock is shattered."
        elif obj.status == "failed":
            line = "The clock has run out."
        elif obj.guards and not obj.guards_down:
            standing = sum(1 for g in obj.guards if state.enemy(g) is not None)
            line = (f"Defeat {name} — warded by {standing} guard"
                    f"{'' if standing == 1 else 's'} — "
                    f"{remaining} round{plural} remain")
        else:
            line = f"Defeat {name} — {remaining} round{plural} remain"
    return {
        "kind": obj.kind,
        "status": obj.status,
        "line": line,
        "rounds_remaining": (remaining if obj.kind in ("survive", "race", "deadline")
                             else None),
        "wave": obj.wave_index + 1 if obj.kind == "waves" else None,
        "waves_total": waves_total if obj.kind == "waves" else None,
        "target_id": obj.target_id,
    }


def doom_clock(state: GameState, enemy) -> Optional[int]:
    """Rounds left on a live race clock, for the marked enemy's badge
    (§D12-1.5) — None for everyone else, and once the clock is resolved."""
    obj = state.objective
    if (obj is None or obj.kind != "race" or obj.status != "active"
            or enemy.id != obj.target_id):
        return None
    return max(0, obj.turns - obj.rounds_done)


def objective_outcome_line(state: GameState) -> Optional[str]:
    """The victory/defeat splash's objective sentence (§D12-1.5), or None when
    the outcome needs no objective framing."""
    obj = state.objective
    if obj is None or state.result is None:
        return None
    if obj.kind == "survive" and state.result == "victory" \
            and obj.rounds_done >= obj.turns:
        return "You held the line — the survivors withdraw."
    if obj.kind == "waves" and state.result == "victory":
        return f"All {len(obj.waves) + 1} waves broken."
    if obj.kind == "race" and state.result == "defeat" and obj.status == "failed":
        return "The doom clock ran out."
    if obj.kind == "deadline" and state.result == "defeat" \
            and obj.rounds_done >= obj.turns:
        return "The clock ran out with enemies still standing."
    if obj.kind == "deadline" and state.result == "victory":
        return "The field cleared with rounds to spare."
    return None


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def serialize_state(view: GameState, log_source: GameState) -> Dict[str, Any]:
    """Serialize a (settled) display view; the event log is read from
    `log_source` (settle() clears the view's log, so the cumulative history is
    pulled from the stored state instead)."""
    return {
        "turn": view.turn,
        "phase": view.phase,
        "phase_label": phase_label(view),
        "result": view.result,
        "priority": view.priority,
        "passes": view.passes,
        "in_window": bool(view.stack),
        "party": [_character_dict(view, c) for c in view.party],
        "tokens": [_token_dict(view, t) for t in view.tokens],
        "enemies": [_enemy_dict(view, e) for e in view.enemies],
        "corpses": [_corpse_dict(c) for c in view.corpses],
        "objective": objective_block(view),
        "stack": _stack_list(view),
        "log": [{"type": e.type, "msg": e.msg, "data": to_jsonable(e.data)}
                for e in log_source.log],
    }


# --------------------------------------------------------------------------- #
# Action menu (two-click targeting) — pure layout over the engine's actions
# --------------------------------------------------------------------------- #
def _target_label(state: GameState, action: Action) -> str:
    tid = action.target_id
    if isinstance(tid, str) and tid.startswith("#"):  # a counter naming a stack action
        item = next((s for s in state.stack if f"#{s.uid}" == tid), None)
        return item.label if item is not None else "the action"
    if isinstance(tid, str) and tid.endswith("::2"):  # a boss-fury second intent (§D9-4)
        tgt = state.combatant(tid[:-3])
        return f"{tgt.name} — second intent" if tgt is not None else "second intent"
    tgt = state.combatant(tid)
    if tgt is None:
        corpse = state.corpse(tid) if tid is not None else None
        if corpse is not None:
            return f"{corpse.name} (corpse)"
        return "self"
    return f"{tgt.name} (HP {tgt.hp}/{tgt.max_hp})"


def _combatant_label(state: GameState, tid: Optional[str]) -> str:
    tgt = state.combatant(tid)
    return f"{tgt.name} (HP {tgt.hp}/{tgt.max_hp})" if tgt is not None else "self"


def _target_tree(state: GameState, group: List[tuple], depth: int) -> List[Dict[str, Any]]:
    """Nested target submenu for an independent multi-target cast: one level per
    target site. `group` is [(index, action)] sharing card/mode; each action's
    `targets` tuple gives this site's pick at `depth`. A leaf (last site) carries
    the action `index`; an inner node carries a further `targets` list."""
    last = depth == len(group[0][1].targets) - 1
    nodes: List[Dict[str, Any]] = []
    seen: List[str] = []
    for j, a in group:
        tid = a.targets[depth]
        if tid in seen:
            continue
        seen.append(tid)
        sub = [(k, b) for k, b in group if b.targets[depth] == tid]
        node = {"label": _combatant_label(state, tid)}
        if last:
            node["index"] = sub[0][0]
        else:
            node["targets"] = _target_tree(state, sub, depth + 1)
        nodes.append(node)
    return nodes


def build_menu(state: GameState, actions: List[Action]) -> List[Dict[str, Any]]:
    """Group the engine's legal actions into menu entries. A direct entry carries
    an `index` into the legal list; a submenu entry carries `targets` (each with
    its own index). Mirrors the text UI's grouping — presentation, no rules."""
    indexed = list(enumerate(actions))
    # A mid-resolution card-move choice replaces the whole menu with its picks.
    card_choices = [(i, a) for i, a in indexed if a.kind == "choose_card"]
    if card_choices:
        pc = state.pending_choice
        prompt = (f"Choose a card to move ({pc.need} more)" if pc is not None
                  else "Choose a card to move")
        return [{"label": prompt, "kind": "prompt"}] + [
            {"label": a.label, "index": i, "kind": "choose_card"} for i, a in card_choices]

    # A scry: place each revealed top card on top (in pick order) or the bottom.
    scry_choices = [(i, a) for i, a in indexed if a.kind == "choose_scry"]
    if scry_choices:
        pc = state.pending_choice
        left = len(pc.candidates) if pc is not None else 0
        prompt = f"Scry — place each revealed card ({left} left)"
        return [{"label": prompt, "kind": "prompt"}] + [
            {"label": a.label, "index": i, "kind": "choose_scry"} for i, a in scry_choices]

    # A trigger-time target pick: aim the triggered ability as it goes on the stack.
    target_choices = [(i, a) for i, a in indexed if a.kind == "choose_target"]
    if target_choices:
        pc = state.pending_choice
        prompt = (f"{pc.item.label} — choose its target" if pc is not None
                  else "Choose a target")
        return [{"label": prompt, "kind": "prompt"}] + [
            {"label": a.label, "index": i, "kind": "choose_target"} for i, a in target_choices]

    # A trigger-time mode pick: a triggered modal chooses its mode as it fires.
    mode_choices = [(i, a) for i, a in indexed if a.kind == "choose_mode"]
    if mode_choices:
        pc = state.pending_choice
        prompt = (f"{pc.item.label} — choose a mode" if pc is not None
                  else "Choose a mode")
        return [{"label": prompt, "kind": "prompt"}] + [
            {"label": a.label, "index": i, "kind": "choose_mode"} for i, a in mode_choices]

    mana = [(i, a) for i, a in indexed if a.kind == "choose_mana"]
    attacks = [(i, a) for i, a in indexed if a.kind == "attack"]
    moves = [(i, a) for i, a in indexed if a.kind == "move"]
    mitigates = [(i, a) for i, a in indexed if a.kind == "mitigate"]
    casts = [(i, a) for i, a in indexed if a.kind == "cast"]
    others = [(i, a) for i, a in indexed
              if a.kind in ("defend", "pass", "end_turn", "delay", "drop_channels",
                            "use_skill", "use_ultimate")]
    stance_abilities = [(i, a) for i, a in indexed if a.kind == "stance_ability"]

    entries: List[Dict[str, Any]] = []
    for i, a in mana:
        entries.append({"label": a.label, "index": i, "kind": a.kind})

    if len(attacks) == 1:
        i, a = attacks[0]
        entries.append({"label": a.label, "index": i, "kind": "attack"})
    elif attacks:
        entries.append({"label": "Attack — choose enemy", "kind": "attack",
                        "targets": [{"label": _target_label(state, a), "index": i}
                                    for i, a in attacks]})

    # Mitigate (self / adjacent ally) and Move (choose row) — each a target submenu.
    if len(mitigates) == 1:
        i, a = mitigates[0]
        entries.append({"label": a.label, "index": i, "kind": "mitigate"})
    elif mitigates:
        entries.append({"label": "Mitigate — choose who", "kind": "mitigate",
                        "targets": [{"label": a.label, "index": i} for i, a in mitigates]})
    if moves:
        entries.append({"label": "Move — choose row", "kind": "move",
                        "targets": [{"label": a.label, "index": i} for i, a in moves]})

    # Stance-replaced abilities (§D9-2): grouped per slot, a submenu when the
    # replacement has multiple legal targets.
    seen_slots: List[str] = []
    for i, a in stance_abilities:
        if a.card_id in seen_slots:
            continue
        seen_slots.append(a.card_id)
        group = [(j, g) for j, g in stance_abilities if g.card_id == a.card_id]
        if len(group) == 1:
            entries.append({"label": a.label, "index": i, "kind": "stance_ability"})
        else:
            base = a.label.split(" on ")[0]
            entries.append({"label": f"{base} — choose target", "kind": "stance_ability",
                            "targets": [{"label": _target_label(state, g), "index": j}
                                        for j, g in group]})

    # Group by (card, modal mode): a modal card offers one entry per mode (chosen
    # at cast), and a multi-target card collapses its targets into a sub-menu.
    seen: List[tuple] = []
    for i, a in casts:
        key = (a.card_id, a.mode)
        if key in seen:
            continue
        seen.append(key)
        group = [(j, g) for j, g in casts if (g.card_id, g.mode) == key]
        card = _hand_card(state, a.actor_id, a.card_id)
        name = card.name if card else a.card_id
        cost = cost_pips(card) if card else ""
        timing = card.timing.value if card else ""
        mode_tag = f" [mode {a.mode + 1}]" if a.mode is not None else ""
        if len(group) == 1:
            j, g = group[0]
            entries.append({"label": g.label, "index": j, "kind": "cast"})
        elif group[0][1].targets:  # independent multi-target: stepwise picker
            entries.append({"label": f"Cast {name} {cost} ({timing}){mode_tag} — choose targets",
                            "kind": "cast",
                            "targets": _target_tree(state, group, 0)})
        else:
            entries.append({"label": f"Cast {name} {cost} ({timing}){mode_tag} — choose target",
                            "kind": "cast",
                            "targets": [{"label": _target_label(state, g), "index": j}
                                        for j, g in group]})

    for i, a in others:
        entries.append({"label": a.label, "index": i, "kind": a.kind})
    return entries


def _hand_card(state: GameState, actor_id: str, card_id: str) -> Optional[Card]:
    actor = state.character(actor_id)
    if actor is None:
        return None
    return next((c for c in actor.hand if c.id == card_id), None)


def serialize_actions(state: GameState, actions: List[Action]) -> List[Dict[str, Any]]:
    """The flat legal list (index-addressable), for reference / debugging."""
    return [{
        "index": i, "kind": a.kind, "actor_id": a.actor_id, "card_id": a.card_id,
        "target_id": a.target_id, "color": a.color, "mode": a.mode, "x": a.x,
        "choice": a.choice, "label": a.label,
    } for i, a in enumerate(actions)]
