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

from ltg_core.schema import Card
from ltg_core.translation import channel_break_clause
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
        "text": card.translated_text or card.original_text or "",
    }


def _pip_str(colors: List[str]) -> str:
    counts = Counter(colors)
    return "".join(("{" + c + "}") * counts[c] for c in _WUBRG if counts[c]) or "{0}"


# --------------------------------------------------------------------------- #
# Veiled intents (Design Update 08 §D8-1): the category is DERIVED
# deterministically from the declared intent — verbs, action_type, target
# descriptor — never authored. The engine emits category + target; the template
# line below is presentation (freely rewordable without touching the engine).
# --------------------------------------------------------------------------- #
_HOSTILE_KINDS = {"deal_damage", "lose_life", "destroy", "exile", "bounce", "stun",
                  "taunt", "wound", "poison", "fight", "strip_intent",
                  "remove_keyword", "counter"}


def intent_category(intent) -> str:
    """One of the closed set: threat / spellcraft / row assault / party assault /
    gathering / support / summon / manoeuvre (§D8-1.2). Multi-verb intents
    classify by their first hostile verb; a `charge` verb anywhere classifies as
    gathering (the windup dominates the fiction). Row-scoped shapes (§D9-3.2 —
    a `rows` filter or a row/blast `scope`) read as a row assault."""
    if intent is None:
        return "threat"
    if getattr(intent, "kind", "action") == "move":
        return "manoeuvre"
    kinds = [getattr(e, "kind", None) for e in intent.effects]
    if "charge" in kinds:
        return "gathering"
    if intent.action_type == "spell":
        return "spellcraft"
    if "create_token" in kinds:
        return "summon"
    first_hostile = next((e for e in intent.effects
                          if getattr(e, "kind", None) in _HOSTILE_KINDS), None)
    if first_hostile is not None:
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
    line = _veiled_line(enemy, category, target_id, target_name, status, slot)
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


def _veiled_line(enemy, category: str, target_id, target_name,
                 status: str, slot: int = 1) -> str:
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
        if target_id is not None:
            return f"{name} begins casting a spell at {tname}."
        return f"{name} begins casting a spell."
    if category == "party assault":
        return f"{name} prepares an assault on your whole party."
    if category == "row assault":
        return f"{name} prepares an assault on a row of your party."
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


def _status_tags(char) -> List[str]:
    tags = []
    if getattr(char, "temp_mod", 0):
        tags.append(f"{'+' if char.temp_mod >= 0 else ''}{char.temp_mod} temp HP")
    if char.prevent_pool:
        tags.append(f"reduce {char.prevent_pool}")
    for tag in getattr(char, "prevent_tags", []):
        span = "next " if tag.uses is not None else ""
        tags.append(f"prevent {span}{tag.parameter}")
    if getattr(char, "power_bonus", 0):
        tags.append(f"{'+' if char.power_bonus >= 0 else ''}{char.power_bonus} Power")
    if getattr(char, "protection", 0):
        tags.append(f"protection ×{char.protection}")
    if getattr(char, "poison_counters", 0):
        tags.append(f"poison ×{char.poison_counters}")
    if getattr(char, "regen_counters", 0):
        tags.append(f"regen ×{char.regen_counters}")
    if getattr(char, "poison_effects", None):
        tags.append("poisoned")
    if getattr(char, "regen_effects", None):
        tags.append("regenerating")
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


def _mitigate_value(char) -> int:
    """X = ceil(current Power / 2) — the per-hit Mitigate reduction (Update 02 §M-A.2)."""
    return math.ceil(max(0, char.current_power) / 2)


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
        "committed": char.committed,
        "pending_voluntary": char.pending_voluntary,
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
            "break_text": channel_break_clause(ch.card.effects, ch.card.targets),
        } for ch in char.channels],
        "hand": [card_dict(c) for c in char.hand],
        "library": [card_dict(c) for c in char.library],
        "stance": _stance_block(char),
        "evergreen": _evergreen_block(char),
        # Heroic actions (D8-3): the once-per-encounter Skill/Ultimate and the
        # public 0–100 ultimate gauge.
        "skill": _heroic_block(char.skill, char.skill_used),
        "ultimate": _heroic_block(char.ultimate, char.ultimate_used),
        "ultimate_gauge": getattr(char, "ultimate_gauge", 0),
        "poison_counters": getattr(char, "poison_counters", 0),
        "regen_counters": getattr(char, "regen_counters", 0),
        "poisoned": bool(getattr(char, "poison_effects", None)),
        "regenerating": bool(getattr(char, "regen_effects", None)),
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
                                  "Gain temporary HP — a buffer that fades at end of turn."),
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
        }
    intent2 = None
    if enemy.intent2 is not None:  # boss fury (§D9-4): the second declared intent
        intent2 = {
            "name": enemy.intent2.name,
            "amount": enemy.intent2.attack_damage(enemy.power_bonus),
            "target_id": enemy.intent2.target_id,
            "target_name": _name_of(state, enemy.intent2.target_id),
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
        "prevent_tags": [f"{'next ' if t.uses is not None else ''}{t.parameter}"
                         for t in enemy.prevent_tags],
        "protection": enemy.protection,
        "stunned": enemy.stunned,
        "power_bonus": enemy.power_bonus,
        "keywords": list(enemy.keywords.keys()),
        "intent": intent,
        "intent2": intent2,
        # The `rises` trait is PUBLIC (§D9-1.5): the veil hides intents, not bodies.
        "rises": getattr(enemy, "rises", None),
        "poison_counters": getattr(enemy, "poison_counters", 0),
        "regen_counters": getattr(enemy, "regen_counters", 0),
        "poisoned": bool(getattr(enemy, "poison_effects", None)),
        "regenerating": bool(getattr(enemy, "regen_effects", None)),
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
def action_mode(kind: str, attack_mode: Optional[str]) -> Optional[str]:
    """The classification tag shown beside an action (stack row / banner / intent),
    in the engine's own vocabulary: **spell | attack | ability** (GDD taxonomy).

    Melee/ranged qualifies ATTACKS ONLY — "melee attack" / "ranged attack". An
    ability always reads "ability", even when its owner is a ranged creature: the
    old behaviour let an enemy ability wear its owner's reach ("Life Leech (ranged)"),
    which read as an attack and hid why combat-damage prevention didn't stop it.
    The tag names the item's damage lane, so what answers it is legible at a glance."""
    if kind == "spell":
        return "spell"
    if kind == "attack":
        reach = attack_mode if attack_mode in ("melee", "ranged") else "melee"
        return f"{reach} attack"
    if kind in ("ability", "activated", "triggered"):
        return "ability"
    return None


def _stack_list(state: GameState) -> List[Dict[str, Any]]:
    out = []
    for i, item in enumerate(reversed(state.stack)):  # top first
        out.append({
            "label": item.label,
            "kind": item.kind,
            "mode": action_mode(item.kind, item.attack_mode),
            "source_id": item.source_id,
            "source_name": _name_of(state, item.source_id),
            "source_side": item.source_side,
            "target_id": item.target_id,
            "target_name": _name_of(state, item.target_id),
            "reserved_pips": _pip_str(item.reserved),
            # The full card behind the action (a cast / a card-carried trigger),
            # so the UI can show it on hover; None for attacks & enemy components.
            "card": card_dict(item.card) if item.card is not None else None,
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
              if a.kind in ("defend", "pass", "end_turn", "drop_channels",
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
