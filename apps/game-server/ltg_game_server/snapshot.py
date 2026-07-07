"""The seat-filtered state snapshot (engine → one client). Presentation only.

Reuses ``ltg_combat.serialize`` for the heavy lifting (stat lines, mana-by-colour,
stack rows, action serialization) and adds exactly the thin, non-rules reshaping the
brief's §3.3 contract asks for that the engine doesn't store natively (see
INTERFACE_NOTES §3–§4): the ``power``/``hp`` nesting, the derived ``priority.kind``,
the per-character ``pending_capacity_choice`` / ``is_active_focusable`` flags, hidden-
info filtering of hands + legal actions, and the newest-first log tail.

Every legal action carries its engine index; the client submits that index and the
server re-validates it against the live ``legal_actions`` — the client builds no rules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ltg_combat.engine import cast_target_labels, legal_actions, settle
from ltg_combat.serialize import (
    _character_dict,
    _enemy_dict,
    _name_of,
    _stack_list,
    _token_dict,
    action_mode,
    card_dict,
    phase_label,
    serialize_actions,
)
from ltg_combat.state import Action, GameState
from ltg_core.schema import KEYWORDS

LOG_TAIL = 60  # how many recent log entries to ship (newest-first)

# Enemy intents are hidden from the player-facing log: the engine still declares
# them (they drive targeting, stun, strip, etc.), we just don't surface the
# telegraph in the log feed.
HIDDEN_LOG_TYPES = {"intent_declared"}


# --------------------------------------------------------------------------- #
# priority.kind — derived (INTERFACE_NOTES §2)
# --------------------------------------------------------------------------- #
def priority_kind(view: GameState) -> Optional[str]:
    """Which decision the engine is waiting on, mirroring `_legal`'s dispatch."""
    if view.priority is None:
        return None
    if view.pending_choice is not None:
        return "card_choice"
    if view.stack:
        return "reaction"
    if view.phase == "capacity":
        return "mana_choice"
    return "main_action"


# --------------------------------------------------------------------------- #
# Per-entity reshaping
# --------------------------------------------------------------------------- #
def _power_block(cur: int, base: int, modifier: int) -> Dict[str, int]:
    return {"current": cur, "base": base, "modifier": modifier}


def _keyword_list(obj) -> List[Dict[str, str]]:
    """Active keyword statics with their registry display name + gloss, so the
    client can render an icon and a tooltip without knowing any rules."""
    out = []
    for kw in getattr(obj, "keywords", {}):
        info = KEYWORDS.get(kw, {})
        out.append({
            "id": kw,
            "name": info.get("display", kw.replace("_", " ").title()),
            "gloss": info.get("gloss", ""),
        })
    return out


def _mana_block(char_dict: Dict[str, Any], raw_char, pending_capacity: bool) -> Dict[str, Any]:
    """Reshape serialize's per-colour list into the brief's mana widget contract."""
    return {
        "identity_colors": list(getattr(raw_char, "identity", [])),
        "by_color": [
            {
                "color": m["color"],
                "pool": m["available"],
                "capacity": m["capacity"],
                "channel_occupied": m["reserved"],
            }
            for m in char_dict["mana"]
        ],
        "pending_capacity_choice": pending_capacity,
    }


def _character_snapshot(view: GameState, char, controlled: bool,
                        holder_id: Optional[str], kind: Optional[str],
                        portrait: str = "") -> Dict[str, Any]:
    cd = _character_dict(view, char)  # reuse the cockpit's stat/mana/channel accessors
    is_holder = holder_id == char.id
    pending_capacity = is_holder and kind == "mana_choice"
    snap: Dict[str, Any] = {
        "id": cd["id"],
        "name": cd["name"],
        "archetype": cd["archetype"],
        "portrait": portrait,  # loadout art (data URL / image URL), "" if none
        "row": cd["row"],
        "power": _power_block(cd["power"], cd["base_power"], cd["power_bonus"]),
        # `current` is the EFFECTIVE hp (hp + temp_mod), mirroring current_power —
        # a wound/pump (temp_mod) must show in the displayed number, not just base.
        "hp": _power_block(char.effective_hp, cd["max_hp"], cd["temp_mod"]),
        "incapacitated": not char.alive,
        "is_channeling": bool(char.channels),
        "channels_summary": cd["channels"],  # id/name/target/text per held channel
        "status_tags": cd["status_tags"],
        "keywords": _keyword_list(char),
        # +1/+1 counters received (their stat change is already inside power/hp).
        "counters": getattr(char, "counters", 0),
        "mitigate_value": cd["mitigate_value"],
        "acted_mode": cd["acted_mode"],
        "turn_ended": cd["turn_ended"],
        "mana": _mana_block(cd, char, pending_capacity),
        # Seat-derived: focusable == you control it and it's up (§4.4 downed is not
        # focus-selectable, but remains a valid heal/revive target).
        "is_active_focusable": controlled and char.alive,
        "controlled": controlled,
        "is_priority_holder": is_holder,
        # Hidden information: hand only for controlled characters.
        "hand": cd["hand"] if controlled else None,
        "hand_count": len(char.hand),
        "library_count": len(char.library),
        "graveyard": [card_dict(c) for c in char.graveyard] if controlled else None,
        "graveyard_count": len(char.graveyard),
        "library": cd["library"] if controlled else None,
    }
    return snap


def _creature_snapshot(view: GameState, enemy) -> Dict[str, Any]:
    ed = _enemy_dict(view, enemy)
    return {
        "id": ed["id"],
        "name": ed["name"],
        "row": ed["row"],
        "level": ed["level"],
        "power": _power_block(enemy.current_power, enemy.power, enemy.power_bonus),
        # Effective hp (hp + temp_mod) so a wound (e.g. Agony Warp −0/−3) shows.
        "hp": _power_block(enemy.effective_hp, ed["max_hp"], ed["temp_mod"]),
        "attack_mode": ed["attack_mode"],
        "keywords": _keyword_list(enemy),
        "counters": getattr(enemy, "counters", 0),
        "intent": ed["intent"],
        # Boss support (§F-9): the flag lights the UI's boss chrome; the execute
        # window tells players the removal immunity has lifted (≤25% max HP).
        "is_boss": bool(enemy.is_boss),
        # Enemy channels (§8): the held effects, named so the player knows what
        # they are turning off — break with one hit of ≥25% max HP or removal.
        "is_channeling": bool(enemy.channels),
        "channels": [{"name": ch.name} for ch in enemy.channels],
        "break_threshold": -(-enemy.max_hp // 4),  # ceil(max_hp / 4)
        "in_execute_window": bool(enemy.is_boss and enemy.in_execute_window),
    }


def _token_snapshot(view: GameState, token) -> Dict[str, Any]:
    td = _token_dict(view, token)
    return {
        "id": td["id"],
        "name": td["name"],
        "row": td["row"],
        "power": _power_block(token.current_power, token.power, token.power_bonus),
        "hp": _power_block(token.effective_hp, token.max_hp, token.temp_mod),
        "keywords": _keyword_list(token),
        "counters": getattr(token, "counters", 0),
        "is_channeling": False,
    }


def _intents(view: GameState) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in view.living_enemies():
        if e.intent is None:
            continue
        amount = e.intent.attack_damage(e.power_bonus)  # live: blunted by any wound
        amt = f" {amount}" if isinstance(amount, int) else ""
        # Reuse the stack's mode logic: an attack intent reads the enemy's reach
        # (melee/ranged), a spell reads "spell", a component ability reads nothing.
        mode = action_mode(e.intent.action_type, e.attack_mode)
        out.append({
            "creature_id": e.id,
            "creature_name": e.name,
            "intent_text": f"{e.intent.name}{amt}",
            "mode": mode,
            "target_id": e.intent.target_id,
            "target_name": _name_of(view, e.intent.target_id),
        })
    return out


# --------------------------------------------------------------------------- #
# Full snapshot
# --------------------------------------------------------------------------- #
def build_snapshot(stored: GameState, controlled_ids: Set[str],
                   portraits: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A full state snapshot filtered for a client that controls `controlled_ids`.

    `stored` is the authoritative (un-settled) state; we render `settle(stored)` and
    compute `legal_actions(stored)` exactly as the cockpit does — the engine runs the
    automatic prelude so the client sees the state a decision is about. `portraits`
    maps character id -> art (the engine drops it), merged into each character.
    """
    portraits = portraits or {}
    view = settle(stored)
    actions: List[Action] = legal_actions(stored)
    holder_id = actions[0].actor_id if actions else view.priority
    kind = priority_kind(view)

    # Seat-filtered legal actions: only ship them if this client controls the holder.
    legal_payload: List[Dict[str, Any]] = []
    if holder_id in controlled_ids and actions:
        legal_payload = serialize_actions(view, actions)
        # serialize_actions omits the per-site `targets` tuple (independent multi-
        # target casts, e.g. Agony Warp). Add it so the client can drive a per-site
        # picker. Order/index align (both derive from the same `actions`).
        for entry, act in zip(legal_payload, actions):
            entry["targets"] = list(act.targets)
            # Per-site effect labels so the targeting popup names each pick (e.g.
            # Agony Warp's two wounds) rather than "target 1 / target 2".
            entry["target_labels"] = cast_target_labels(view, act)

    # A pending card pick's candidates, as FULL cards (cost/text/type), so the
    # client can show the whole card instead of a name list. Hidden-information
    # gated exactly like hands: only the chooser's client receives them.
    pending_cards = None
    pc = view.pending_choice
    if (pc is not None and pc.kind in ("move", "scry")
            and pc.chooser_id in controlled_ids):
        pending_cards = {
            "kind": pc.kind,
            "chooser_id": pc.chooser_id,
            "candidates": [card_dict(c) for c in pc.candidates],
        }

    characters = [
        _character_snapshot(view, c, c.id in controlled_ids, holder_id, kind,
                            portraits.get(c.id, ""))
        for c in view.party
    ]
    creatures = [_creature_snapshot(view, e) for e in view.living_enemies()]
    tokens = [_token_snapshot(view, t) for t in view.living_tokens()]

    # top-first; client renders bottom = resolves last. Slim off the raw dump and
    # surface `uid` so a counter's `#<uid>` target maps to a clickable stack row.
    stack = [
        {
            "label": r["label"], "kind": r["kind"], "mode": r["mode"],
            "source_id": r["source_id"], "source_name": r["source_name"],
            "source_side": r["source_side"], "target_id": r["target_id"],
            "target_name": r["target_name"], "reserved_pips": r["reserved_pips"],
            "card": r["card"], "top": r["top"], "uid": r["raw"].get("uid"),
        }
        for r in _stack_list(view)
    ]
    # Resolve the card a log line references (data["card"] id) to the full card,
    # scanning every party zone / held channel / stack item — so the client can
    # show the whole card on hover. Names in the log are already public; this
    # attaches the matching text at the same disclosure level.
    card_index = {}
    for c in view.party:
        for zone in (c.hand, c.library, c.graveyard, c.exile):
            for card in zone:
                card_index[card.id] = card
        for ch in c.channels:
            card_index[ch.card.id] = ch.card
    for item in view.stack:
        if item.card is not None:
            card_index[item.card.id] = item.card

    def _log_card(e):
        cid = e.data.get("card")
        return card_dict(card_index[cid]) if cid in card_index else None

    visible = [e for e in stored.log if e.type not in HIDDEN_LOG_TYPES]
    log = [
        {"type": e.type, "msg": e.msg, "data": e.data, "card": _log_card(e)}
        for e in reversed(visible[-LOG_TAIL:])  # newest-first tail
    ]

    return {
        "turn": view.turn,
        "phase": view.phase,
        "phase_label": phase_label(view),
        "priority": {"holder_character_id": holder_id, "kind": kind},
        "characters": characters,
        "creatures": creatures,
        "tokens": tokens,
        "stack": stack,
        "intents": _intents(view),
        "pending_choice": pending_cards,
        "log": log,
        "legal_actions": legal_payload,   # for the controlled holder only
        "result": view.result,
        "game_over": {"result": view.result} if view.result is not None else None,
    }
