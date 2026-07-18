"""Adventure runs — the three-act session layer (Design Update 10).

The combat engine is untouched: every act is an ordinary encounter to it. This
module owns everything the adventure adds around the engine — the act sequence,
the carry-over rules at an act boundary (§D10-2), the adventure-local level-up
and its validation (§D10-3), and composing the next act's `GameState` through
the exact `compose_spec`/`state_from_dict` path a standalone encounter takes.

An `AdventureRun` rides its `Session`; a session without one behaves byte-
identically to today (the regression spine of §D10-7).
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Optional

from ltg_core.schema import (
    COST_CARD,
    COST_HP_STEP,
    COST_MANA,
    COST_POWER,
    Character,
    LEVEL_UP_POINTS,
    MAX_POWER_BOUGHT,
    creation_points,
)
from ltg_combat.state import GameState

from . import content

# Rebalance Register (Update 10 §D10-8)
HP_FLOOR_PCT = 25          # T-59: act-start HP floor, max(current, ceil(25% max))
GAUGE_CARRY = 0.5          # T-58: ultimate-gauge carry across acts (floored)
POINTS_PER_LEVEL = LEVEL_UP_POINTS  # T-57


def _points(char: Character) -> int:
    """The build's spend against the flat price table (legacy builds included —
    their odd baselines price consistently, only the deltas matter here)."""
    return creation_points(char.hp, char.mana_capacity, char.starting_cards,
                           char.power_bought, char.keyword)


def price_table() -> Dict[str, Any]:
    """The points-buy prices, shipped to the level-up screen so the client
    renders costs without knowing any rules."""
    return {
        "hp_step": COST_HP_STEP,        # per +2 HP
        "mana": COST_MANA,              # per +1 mana capacity
        "card": COST_CARD,              # per +1 starting card
        "power": COST_POWER,            # per +1 bought Power
        "power_cap_per_level": MAX_POWER_BOUGHT,   # T-60: bought Power ≤ 2 × level
    }


def validate_level_up(old_raw: Dict[str, Any], patch: Dict[str, Any],
                      new_level: int, available: int) -> "tuple[Dict[str, Any], int]":
    """Validate one character's level-up (§D10-3.1) and price it.

    ``old_raw`` is the entering character dict (the loadout's ``character``);
    ``patch`` the client's proposed build fields (hp, starting_mana,
    starting_cards, power_bought); ``available`` the spendable points
    (banked + the 30 grant). Returns ``(new_character_dict, points_spent)`` or
    raises ValueError with a human message. Everything not in the points-buy
    (colours, attack mode, row, cards, heroics, the keyword — keywords are
    character-creation only) is locked to the old build.
    """
    old = Character.model_validate(old_raw)

    def _int(key: str, fallback: int) -> int:
        v = patch.get(key, fallback)
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")

    hp = _int("hp", old.hp)
    starting_cards = _int("starting_cards", old.starting_cards)
    power_bought = _int("power_bought", old.power_bought)
    mana = patch.get("starting_mana", [c.value for c in old.starting_mana])
    if not isinstance(mana, list):
        raise ValueError("starting_mana must be a list of colours")
    mana = [str(c) for c in mana]
    keyword = patch.get("keyword", old.keyword)
    keyword = str(keyword) if keyword else None
    if keyword != old.keyword:
        raise ValueError("keywords come from character creation only — they "
                         "cannot be bought or changed at level-up")

    # The locked baseline (§D10-3.1): nothing bought earlier can be sold back.
    if hp < old.hp:
        raise ValueError("previous purchases are locked — HP cannot go down")
    if starting_cards < old.starting_cards:
        raise ValueError("previous purchases are locked — starting cards cannot go down")
    if power_bought < old.power_bought:
        raise ValueError("previous purchases are locked — Power cannot go down")
    old_mana = [c.value for c in old.starting_mana]
    if len(mana) < len(old_mana) or mana[:len(old_mana)] != old_mana:
        raise ValueError("existing mana slots are locked — new capacity appends "
                         "to the entering slots")
    identity = {c.value for c in old.colors}
    off_colour = [c for c in mana[len(old_mana):] if c not in identity]
    if off_colour:
        raise ValueError(
            f"new mana capacity must lock within the colour identity "
            f"({'/'.join(sorted(identity))}) — got {', '.join(off_colour)}")

    new_raw = {**old.model_dump(mode="json"),
               "hp": hp, "starting_mana": mana,
               "starting_cards": starting_cards, "power_bought": power_bought,
               "keyword": keyword, "level": new_level}
    try:
        # The schema enforces the rest: HP parity, the T-60 Power cap
        # (2 × level), and the level budget (70 + 30/level).
        new = Character.model_validate(new_raw)
    except Exception as exc:
        raise ValueError(str(exc)) from exc

    spent = _points(new) - _points(old)
    if spent < 0:
        raise ValueError("previous purchases are locked — nothing can be sold back")
    if spent > available:
        raise ValueError(f"that build spends {spent} points but only {available} "
                         "are available")
    return new.model_dump(mode="json"), spent


class AdventureRun:
    """The adventure-specific state riding one session: act sequencing, the
    per-character adventure-local builds, the carry snapshot, and the level-up
    gate. All mutation happens under the session's lock (the app layer's)."""

    def __init__(self, adventure_id: str) -> None:
        detail = content.adventure_detail(adventure_id)
        if detail is None:
            raise ValueError(f"unknown adventure: {adventure_id}")
        self.adventure_id = adventure_id
        self.name: str = detail["name"]
        self.flavor: str = detail["flavor"]
        # [{encounter_id, narration, name}] in act order.
        self.acts: List[Dict[str, Any]] = [
            {"encounter_id": a["encounter_id"], "narration": a["narration"],
             "name": a["name"]}
            for a in detail["acts"]
        ]
        self.act_index = 0
        self.complete = False
        # Filled by start(): the picked roster ids, the run's loadouts (deep
        # copies — the adventure-local builds live in loadouts[i]["character"]
        # and never touch the saved profiles), and the live party ids.
        self.character_ids: List[str] = []
        self.loadouts: List[Dict[str, Any]] = []
        self.live_ids: List[str] = []
        self.banked: Dict[str, int] = {}      # live id -> unspent points pool
        # The level-up gate (None outside an act boundary):
        # live id -> {"confirmed": bool, "spent": int, "heal": int}
        self.level_up: Optional[Dict[str, Dict[str, Any]]] = None
        self.carry: Dict[str, Dict[str, Any]] = {}

    # -- act composition ------------------------------------------------------ #
    def start(self, character_ids: List[str], seed: Optional[int] = None
              ) -> "tuple[GameState, Dict[str, str], Dict[str, Any], str]":
        """Build Act I from the base (saved) loadouts. Returns
        ``(state, portraits, art, act_encounter_id)``."""
        self.character_ids = list(character_ids)
        self.loadouts = content.loadouts_for(character_ids)  # deep copies
        eid = self.acts[0]["encounter_id"]
        state, portraits, art = content.build_state_from_loadouts(
            self.loadouts, eid, seed=seed)
        self.live_ids = [c.id for c in state.party]
        # The unspent pool opens with whatever creation left over (§D10-3:
        # points are "added to the character's unspent pool").
        for live_id, lo in zip(self.live_ids, self.loadouts):
            try:
                char = Character.model_validate(lo["character"])
                self.banked[live_id] = max(0, char.points_remaining) if not char.legacy else 0
            except Exception:
                self.banked[live_id] = 0
        return state, portraits, art, eid

    def current_act(self) -> Dict[str, Any]:
        return self.acts[self.act_index]

    def is_final_act(self) -> bool:
        return self.act_index >= len(self.acts) - 1

    # -- the act boundary ------------------------------------------------------ #
    def on_state_change(self, state: GameState) -> None:
        """Called after every engine state change: opens the level-up gate the
        moment a non-final act is won, and marks the run complete when the
        finale is."""
        if state.result != "victory":
            return
        if self.is_final_act():
            self.complete = True
            return
        if self.level_up is None:
            self._begin_level_up(state)

    def suppresses_result(self, result: Optional[str]) -> bool:
        """A non-final act victory is an ACT boundary, not a game over — the
        client sees the level-up gate instead. Defeat and the finale's victory
        pass through untouched."""
        return result == "victory" and not self.complete

    def _begin_level_up(self, state: GameState) -> None:
        """Snapshot the carry state (§D10-2) and open the gate (§D10-3)."""
        self.carry = {}
        for c in state.party:
            # Everything shuffles up together at the boundary — hand, library,
            # graveyard, and the cards of silently-dropped channels — and the
            # next act opens on a FRESH hand of starting-cards (first-playtest
            # amendment: carrying the literal hand let cards accumulate).
            cards = (list(c.hand) + list(c.library) + list(c.graveyard)
                     + [ch.card for ch in c.channels])
            self.carry[c.id] = {
                "hp": c.hp,  # temp mods are encounter-duration; they clear
                "cards": copy.deepcopy(cards),
                "exile": copy.deepcopy(c.exile),
                "gauge": c.ultimate_gauge,
            }
        self.level_up = {
            live_id: {"confirmed": False, "spent": 0, "heal": 0}
            for live_id in self.live_ids
        }

    def next_level(self) -> int:
        """The level this boundary's level-up reaches (Act I → 2, Act II → 3)."""
        return self.act_index + 2

    def confirm_level_up(self, live_id: str, build: Dict[str, Any]) -> None:
        """Validate + apply one character's level-up; banking the remainder.
        Raises ValueError on an invalid delta or a closed gate."""
        if self.level_up is None:
            raise ValueError("no level-up is pending")
        entry = self.level_up.get(live_id)
        if entry is None:
            raise ValueError(f"unknown character: {live_id}")
        if entry["confirmed"]:
            raise ValueError(f"{live_id} has already confirmed this level-up")
        slot = self.live_ids.index(live_id)
        old_raw = self.loadouts[slot]["character"]
        available = self.banked.get(live_id, 0) + POINTS_PER_LEVEL
        new_raw, spent = validate_level_up(old_raw, build or {},
                                           self.next_level(), available)
        heal = int(new_raw["hp"]) - int(old_raw.get("hp", new_raw["hp"]))
        self.loadouts[slot]["character"] = new_raw
        self.banked[live_id] = available - spent
        entry.update(confirmed=True, spent=spent, heal=heal)

    def all_confirmed(self) -> bool:
        return (self.level_up is not None
                and all(e["confirmed"] for e in self.level_up.values()))

    def advance(self, seed: Optional[int] = None
                ) -> "tuple[GameState, Dict[str, str], Dict[str, Any], str]":
        """Compose the next act: leveled builds through the standard build path,
        then the §D10-2 carry rules applied on top. Returns
        ``(state, portraits, art, act_encounter_id)``."""
        if not self.all_confirmed():
            raise ValueError("not every character has confirmed the level-up")
        heals = {lid: e["heal"] for lid, e in (self.level_up or {}).items()}
        self.act_index += 1
        self.level_up = None
        eid = self.acts[self.act_index]["encounter_id"]
        state, portraits, art = content.build_state_from_loadouts(
            self.loadouts, eid, seed=seed)
        rng = random.Random(seed)
        for c in state.party:
            cy = self.carry.get(c.id)
            if cy is None:
                continue
            # HP: carry, heal by the bought max (+2 max is +2 current), then the
            # act-start floor — one rule for everyone (T-59). The incapacitated
            # stand back up at the floor; the barely-alive are lifted to it.
            floor = -(-c.max_hp * HP_FLOOR_PCT // 100)  # ceil(25% of max)
            c.hp = min(c.max_hp, max(cy["hp"] + heals.get(c.id, 0), floor))
            # Shuffle up completely — hand, library, graveyard as one pool —
            # and draw a fresh hand of starting-cards. Exile is forever.
            cards = list(cy["cards"])
            rng.shuffle(cards)
            c.hand = cards[:c.hand_size]
            c.library = cards[c.hand_size:]
            c.graveyard = []
            c.exile = list(cy["exile"])
            # Ultimate gauge carries at 50%, floored (T-58).
            c.ultimate_gauge = int(cy["gauge"] * GAUGE_CARRY)
        self.carry = {}
        return state, portraits, art, eid

    # -- snapshot -------------------------------------------------------------- #
    def snapshot_block(self, state: GameState,
                       controlled_ids: "set[str]") -> Dict[str, Any]:
        """The per-client adventure block riding the state snapshot. The
        level-up gate is per-seat: your own characters carry their entering
        build and points; everyone else is just a confirmed/waiting light."""
        act = self.current_act()
        block: Dict[str, Any] = {
            "id": self.adventure_id,
            "name": self.name,
            "flavor": self.flavor,
            "act": self.act_index + 1,
            "acts_total": len(self.acts),
            "act_name": act["name"],
            "narration": act["narration"],
            "character_ids": list(self.character_ids),
            "complete": self.complete,
            "level_up": None,
        }
        if self.level_up is not None:
            chars = []
            for live_id, lo in zip(self.live_ids, self.loadouts):
                entry = self.level_up.get(live_id, {})
                row: Dict[str, Any] = {
                    "id": live_id,
                    "name": str(lo.get("character", {}).get("name", live_id)),
                    "confirmed": bool(entry.get("confirmed")),
                }
                if live_id in controlled_ids:
                    raw = lo["character"]
                    try:
                        char = Character.model_validate(raw)
                        spent = _points(char)
                    except Exception:
                        spent = 0
                    row["build"] = {
                        "hp": raw.get("hp"),
                        "starting_mana": list(raw.get("starting_mana", [])),
                        "starting_cards": raw.get("starting_cards"),
                        "power_bought": raw.get("power_bought", 0),
                        "keyword": raw.get("keyword"),
                        "attack_mode": raw.get("attack_mode", "melee"),
                        "colors": list(raw.get("colors", [])),
                        "level": raw.get("level", 1),
                        "portrait": raw.get("portrait", ""),
                    }
                    row["locked"] = spent
                    row["banked"] = self.banked.get(live_id, 0)
                    row["available"] = (self.banked.get(live_id, 0)
                                        + (0 if entry.get("confirmed")
                                           else POINTS_PER_LEVEL))
                chars.append(row)
            block["level_up"] = {
                "next_level": self.next_level(),
                "points_per_level": POINTS_PER_LEVEL,
                "prices": price_table(),
                "characters": chars,
            }
        return block
