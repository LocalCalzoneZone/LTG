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

import re
from typing import Any, Dict, List, Optional, Set

from ltg_combat.engine import _ordered, cast_target_labels, legal_actions, settle
from ltg_combat.serialize import (
    _character_dict,
    _corpse_dict,
    _enemy_dict,
    _stack_list,
    _token_dict,
    card_dict,
    doom_clock,
    objective_block,
    objective_outcome_line,
    phase_label,
    serialize_actions,
    veiled_intent,
    veiled_intents,
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
                        portrait: str = "", description: str = "") -> Dict[str, Any]:
    cd = _character_dict(view, char)  # reuse the cockpit's stat/mana/channel accessors
    is_holder = holder_id == char.id
    pending_capacity = is_holder and kind == "mana_choice"
    snap: Dict[str, Any] = {
        "id": cd["id"],
        "name": cd["name"],
        "archetype": cd["archetype"],
        "portrait": portrait,  # loadout art (data URL / image URL), "" if none
        "description": description,  # the loadout's character blurb ("" if none)
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
        # Typed counters (D8-2) — public information on both sides.
        "poison_counters": cd["poison_counters"],
        "regen_counters": cd["regen_counters"],
        "poisoned": cd["poisoned"],
        "regenerating": cd["regenerating"],
        # Heroic actions (D8-3): the gauge and used-flags are public; the
        # Skill/Ultimate card faces ship only to the controlling client (below).
        "ultimate_gauge": cd["ultimate_gauge"],
        "skill": cd["skill"] if controlled else (
            {"used": cd["skill"]["used"]} if cd["skill"] else None),
        "ultimate": cd["ultimate"] if controlled else (
            {"used": cd["ultimate"]["used"]} if cd["ultimate"] else None),
        "evergreen": cd["evergreen"],  # flavour-named Basic Attack/Defend/Mitigate (D8-3.4)
        # The active stance (§D9-2), or None: which main abilities are rewired.
        "stance": cd["stance"],
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


def _art_base_id(entity_id: str, art: Dict[str, Any]) -> str:
    """The pool/token-def id behind a live combatant, for art lookup.

    Setup-time enemies (layout clones included) are in the session's ``base_of``
    map. Anything spawned MID-GAME is a token — the engine names spawns
    ``<token_def_id>_<seq>`` — so an unmapped id resolves by stripping the
    numeric suffix back to its definition's key."""
    mapped = art.get("base_of", {}).get(entity_id)
    return mapped if mapped else re.sub(r"_\d+$", "", entity_id)


def _creature_snapshot(view: GameState, enemy,
                       art: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ed = _enemy_dict(view, enemy)
    # Generated art is keyed by POOL enemy id ("wolf"); a layout clone ("wolf_2")
    # or a mid-game token spawn ("huskling_3") resolves back to its base design,
    # so duplicates share one image.
    art = art or {}
    base_id = _art_base_id(enemy.id, art)
    return {
        "id": ed["id"],
        "name": ed["name"],
        # For art generation/removal calls the client makes about this creature.
        "base_id": base_id,
        # Generated portrait URL ("" until one exists — the card shows its sigil).
        "image": art.get("enemies", {}).get(base_id, ""),
        # The enemy's art-direction prose (physical appearance) for the inspect view.
        "description": art.get("descriptions", {}).get(base_id, ""),
        "row": ed["row"],
        "level": ed["level"],
        "power": _power_block(enemy.current_power, enemy.power, enemy.power_bonus),
        # Effective hp (hp + temp_mod) so a wound (e.g. Agony Warp −0/−3) shows.
        "hp": _power_block(enemy.effective_hp, ed["max_hp"], ed["temp_mod"]),
        "attack_mode": ed["attack_mode"],
        "keywords": _keyword_list(enemy),
        "counters": getattr(enemy, "counters", 0),
        # Typed counters + the public charge gauge (D8-2): counts are public on
        # both sides; what the charge FEEDS stays hidden until it fires.
        "poison_counters": ed["poison_counters"],
        "regen_counters": ed["regen_counters"],
        "poisoned": ed["poisoned"],
        "regenerating": ed["regenerating"],
        "charge": ed["charge"],
        "charge_threshold": ed["charge_threshold"],
        # VEILED intent (D8-1): category + locked target only — the full text,
        # amounts and keywords stay server-side until the action hits the stack.
        "intent": veiled_intent(view, enemy),
        # Every declared line (two for an enraged boss, §D9-4).
        "intents": veiled_intents(view, enemy),
        # The `rises` trait is public (§D9-1.5) — the stirring state, not the veil.
        "rises": getattr(enemy, "rises", None),
        # The doom-clock badge (§D12-1.5): rounds left on a live race clock,
        # for the marked enemy only — None everywhere else.
        "doom_clock": doom_clock(view, enemy),
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


def _token_snapshot(view: GameState, token,
                    art: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    td = _token_dict(view, token)
    art = art or {}
    base_id = _art_base_id(token.id, art)
    return {
        "id": td["id"],
        "name": td["name"],
        "base_id": base_id,
        "image": art.get("enemies", {}).get(base_id, ""),
        "description": art.get("descriptions", {}).get(base_id, ""),
        "row": td["row"],
        "power": _power_block(token.current_power, token.power, token.power_bonus),
        "hp": _power_block(token.effective_hp, token.max_hp, token.temp_mod),
        "keywords": _keyword_list(token),
        "counters": getattr(token, "counters", 0),
        "poison_counters": getattr(token, "poison_counters", 0),
        "regen_counters": getattr(token, "regen_counters", 0),
        "is_channeling": False,
        # Control chip (§D9-1.4): dominated enemy / raised undead, holder, and
        # remaining rounds (None == the encounter).
        "controlled_by": td["controlled_by"],
        "control_left": td["control_left"],
        "control_kind": td["control_kind"],
    }


def _intents(view: GameState) -> List[Dict[str, Any]]:
    """The veiled intents list (D8-1.4): a server contract, not a UI courtesy.
    One line per living enemy for the current round, in enemy board order — only
    `{enemy_id, category, target, line}` plus the window's status/reveal fields.
    Never the intent's name, verbs, or amounts (the cockpit's serializer keeps
    the full data; this seat-filtered snapshot is what players receive)."""
    out: List[Dict[str, Any]] = []
    for e in _ordered(view.living_enemies()):
        out.extend(veiled_intents(view, e))  # two lines for an enraged boss (§D9-4)
    return out


# --------------------------------------------------------------------------- #
# Full snapshot
# --------------------------------------------------------------------------- #
def build_snapshot(stored: GameState, controlled_ids: Set[str],
                   portraits: Optional[Dict[str, str]] = None,
                   art: Optional[Dict[str, Any]] = None,
                   encounter_id: str = "") -> Dict[str, Any]:
    """A full state snapshot filtered for a client that controls `controlled_ids`.

    `stored` is the authoritative (un-settled) state; we render `settle(stored)` and
    compute `legal_actions(stored)` exactly as the cockpit does — the engine runs the
    automatic prelude so the client sees the state a decision is about. `portraits`
    maps character id -> art (the engine drops it), merged into each character;
    `art` carries the encounter's generated images (scene backdrop + per-pool-enemy
    portraits, see session.py) and `encounter_id` lets the client aim art
    generation calls at the right encounter.
    """
    portraits = portraits or {}
    art = art or {}
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
                            portraits.get(c.id, ""),
                            art.get("char_descriptions", {}).get(c.id, ""))
        for c in view.party
    ]
    creatures = [_creature_snapshot(view, e, art) for e in view.living_enemies()]
    tokens = [_token_snapshot(view, t, art) for t in view.living_tokens()]
    # Corpse markers (§D9-1.7): small and dim on their rows; a stirring corpse
    # pulses. Public information — the veil hides intents, not bodies.
    corpses = [_corpse_dict(c) for c in view.corpses]

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

    # `seq` is the entry's absolute position in the engine log, so a client can
    # tell which entries are NEW since its last snapshot (the combat-FX layer
    # keys its one-shot effects off exactly that).
    visible = [(i, e) for i, e in enumerate(stored.log)
               if e.type not in HIDDEN_LOG_TYPES]
    log = [
        {"seq": i, "type": e.type, "msg": e.msg, "data": e.data, "card": _log_card(e)}
        for i, e in reversed(visible[-LOG_TAIL:])  # newest-first tail
    ]

    return {
        "turn": view.turn,
        "phase": view.phase,
        "phase_label": phase_label(view),
        # Art plumbing: the generated battle backdrop ("" until one exists) and
        # the encounter to aim in-game generate/remove calls at.
        "scene_image": art.get("scene", ""),
        "encounter_id": encounter_id,
        "priority": {"holder_character_id": holder_id, "kind": kind},
        "characters": characters,
        "creatures": creatures,
        "tokens": tokens,
        "corpses": corpses,
        "stack": stack,
        # The objective banner (§D12-1.5): fully public, pinned as the first
        # line of the intents window. None for a standard encounter.
        "objective": objective_block(view),
        "intents": _intents(view),
        "pending_choice": pending_cards,
        "log": log,
        "legal_actions": legal_payload,   # for the controlled holder only
        "result": view.result,
        "game_over": ({"result": view.result,
                       "objective_line": objective_outcome_line(view)}
                      if view.result is not None else None),
    }
