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
        tags.append(f"prevent {tag}")
    if getattr(char, "power_bonus", 0):
        tags.append(f"{'+' if char.power_bonus >= 0 else ''}{char.power_bonus} Power")
    if getattr(char, "protection", 0):
        tags.append(f"protection ×{char.protection}")
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
        } for ch in char.channels],
        "hand": [card_dict(c) for c in char.hand],
        "library": [card_dict(c) for c in char.library],
        "evergreen": {
            "offensive": {"name": "Basic Attack",
                          "text": f"Deal {char.attack_mode} damage equal to Power ({char.current_power})."},
            "defensive_action": {"name": "Defend",
                                 "text": "Gain temporary HP — a buffer that fades at end of turn."},
            "defensive_reaction": {"name": "Mitigate",
                                   "text": f"Reduce each hit of an incoming attack by ceil(Power/2) = "
                                           f"{_mitigate_value(char)}; or intercept for an adjacent ally."},
        },
        "raw": to_jsonable(char),
    }


def _enemy_dict(state: GameState, enemy) -> Dict[str, Any]:
    intent = None
    if enemy.intent is not None:
        amount = enemy.intent.effects[0].amount if enemy.intent.effects else None
        intent = {
            "name": enemy.intent.name,
            "amount": amount if isinstance(amount, int) else None,
            "target_id": enemy.intent.target_id,
            "target_name": _name_of(state, enemy.intent.target_id),
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
        "temp_mod": enemy.temp_mod,
        "prevent_pool": enemy.prevent_pool,
        "protection": enemy.protection,
        "stunned": enemy.stunned,
        "power_bonus": enemy.power_bonus,
        "keywords": list(enemy.keywords.keys()),
        "intent": intent,
        "raw": to_jsonable(enemy),
    }


def _token_dict(state: GameState, token) -> Dict[str, Any]:
    return {
        "id": token.id,
        "name": token.name,
        "hp": token.hp,
        "max_hp": token.max_hp,
        "power": token.power,
        "row": token.row,
        "alive": token.alive,
        "raw": to_jsonable(token),
    }


def _name_of(state: GameState, cid: Optional[str]) -> Optional[str]:
    if cid is None:
        return None
    c = state.combatant(cid)
    return c.name if c else cid


# --------------------------------------------------------------------------- #
# Stack
# --------------------------------------------------------------------------- #
def _stack_list(state: GameState) -> List[Dict[str, Any]]:
    out = []
    for i, item in enumerate(reversed(state.stack)):  # top first
        out.append({
            "label": item.label,
            "kind": item.kind,
            "source_id": item.source_id,
            "source_name": _name_of(state, item.source_id),
            "source_side": item.source_side,
            "target_id": item.target_id,
            "target_name": _name_of(state, item.target_id),
            "reserved_pips": _pip_str(item.reserved),
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
    tgt = state.combatant(tid)
    if tgt is None:
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

    mana = [(i, a) for i, a in indexed if a.kind == "choose_mana"]
    attacks = [(i, a) for i, a in indexed if a.kind == "attack"]
    moves = [(i, a) for i, a in indexed if a.kind == "move"]
    mitigates = [(i, a) for i, a in indexed if a.kind == "mitigate"]
    casts = [(i, a) for i, a in indexed if a.kind == "cast"]
    others = [(i, a) for i, a in indexed
              if a.kind in ("defend", "pass", "end_turn", "drop_channels")]

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
        "target_id": a.target_id, "color": a.color, "mode": a.mode, "label": a.label,
    } for i, a in enumerate(actions)]
