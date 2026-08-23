"""Adventure runs — the three-phase session layer (Design Update 10).

The combat engine is untouched: every phase is an ordinary encounter to it. This
module owns everything the adventure adds around the engine — the phase sequence,
the carry-over rules at a phase boundary (§D10-2), the adventure-local level-up
and its validation (§D10-3), and composing the next phase's `GameState` through
the exact `compose_spec`/`state_from_dict` path a standalone encounter takes.

An `AdventureRun` rides its `Session`; a session without one behaves byte-
identically to today (the regression spine of §D10-7).
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Optional

from ltg_core.schema import (
    BASELINE_CARDS,
    BASELINE_HP,
    BASELINE_MANA,
    Character,
    LEVEL_THRESHOLDS,
    LEVEL_UP_POINTS,
    MAX_LEVEL,
    PHASE_GRANTS,
    MAX_POWER_BOUGHT,
    PRICE_STATS,
    creation_points,
    level_band,
    level_for_points,
    points_to_next_level,
    price_list,
)
from ltg_combat.state import GameState

from . import content

# Rebalance Register (Update 10 §D10-8)
HP_FLOOR_PCT = 25          # T-59: phase-start HP floor, max(current, ceil(25% max))
GAUGE_CARRY = 0.5          # T-58: ultimate-gauge carry across phases (floored)
POINTS_PER_LEVEL = LEVEL_UP_POINTS  # T-57: a level-up's worth (the sheet's unit)


def phase_grant(phase_index: int) -> int:
    """Points a character earns for winning the phase at ``phase_index``
    (0-based): +10 / +20 / +30 (T-57). A longer adventure than the grant table
    keeps paying the last step."""
    i = max(0, int(phase_index))
    return PHASE_GRANTS[i] if i < len(PHASE_GRANTS) else PHASE_GRANTS[-1]


def _points(char: Character) -> int:
    """The build's spend on the T-79 curve (legacy builds included — their odd
    baselines price consistently, only the deltas matter here)."""
    return creation_points(char.hp, char.mana_capacity, char.starting_cards,
                           char.power_bought, char.keyword)


def _heroic_ids(char) -> set:
    """The ids of a character's SHEET abilities — the authored Skill and Ultimate
    (D8-3). They are never library cards, so nothing that walks the deck across a
    phase boundary may pick them up."""
    return {a.id for a in (char.skill, char.ultimate) if a is not None}


def price_table() -> Dict[str, Any]:
    """The points-buy prices, shipped to the level-up screen so the client
    renders costs without knowing any rules. Update 17 §D17-2.2: prices are
    the escalating T-79 curve — ``curve[stat][n-1]`` is the price of the nth
    purchase of that stat counted from baseline (an HP step is one +2 pair)."""
    return {
        "curve": {stat: price_list(stat) for stat in PRICE_STATS},
        "baseline": {"hp": BASELINE_HP, "mana": BASELINE_MANA, "cards": BASELINE_CARDS},
        "power_cap_per_level": MAX_POWER_BOUGHT,   # T-60: bought Power ≤ 2 × level
        "level_thresholds": list(LEVEL_THRESHOLDS),  # T-78 (index = level)
        "max_level": MAX_LEVEL,
    }


def validate_level_up(old_raw: Dict[str, Any], patch: Dict[str, Any],
                      new_level: int, available: int,
                      earned_points: Optional[int] = None) -> "tuple[Dict[str, Any], int]":
    """Validate one character's level-up (§D10-3.1) and price it.

    ``old_raw`` is the entering character dict (the loadout's ``character``);
    ``patch`` the client's proposed build fields (hp, starting_mana,
    starting_cards, power_bought); ``available`` the spendable points (the
    bankable pool, which phase grants have already been paid into);
    ``new_level`` the derived level the build now
    holds (T-78) and ``earned_points`` its cumulative grants (both written to
    the run copy). Returns ``(new_character_dict, points_spent)`` or
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
    if earned_points is not None:
        new_raw["earned_points"] = int(earned_points)
    try:
        # The schema enforces the rest: HP parity and the T-60 Power cap
        # (2 × derived level). Spend is limited against ``available`` below.
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
    """The adventure-specific state riding one session: phase sequencing, the
    per-character adventure-local builds, the carry snapshot, and the level-up
    gate. All mutation happens under the session's lock (the app layer's)."""

    def __init__(self, adventure_id: str,
                 detail: Optional[Dict[str, Any]] = None) -> None:
        """``detail`` (optional) is a FROZEN adventure detail — a run's
        content-store copy (Update 17 §D17-3.3) — used instead of the live
        registry so a loaded save replays the exact adventure it pointed at."""
        if detail is None:
            detail = content.adventure_detail(adventure_id)
        if detail is None:
            raise ValueError(f"unknown adventure: {adventure_id}")
        self.adventure_id = adventure_id
        self.detail: Dict[str, Any] = copy.deepcopy(detail)
        # Update 17: the RUN's difficulty. A pre-generated adventure was written
        # at its own (stamped) difficulty; at play the enemy HP is rescaled by
        # the ratio so the scenario's chosen difficulty applies to every act.
        self.difficulty: Optional[str] = None
        self.name: str = detail["name"]
        self.flavor: str = detail["flavor"]
        # [{encounter_id, narration, name}] in phase order.
        self.phases: List[Dict[str, Any]] = [
            {"encounter_id": a["encounter_id"], "narration": a["narration"],
             "name": a["name"]}
            for a in detail["phases"]
        ]
        self.phase_index = 0
        self.complete = False
        # Filled by start(): the picked roster ids, the run's loadouts (deep
        # copies — the adventure-local builds live in loadouts[i]["character"]
        # and never touch the saved profiles), and the live party ids.
        self.character_ids: List[str] = []
        self.loadouts: List[Dict[str, Any]] = []
        self.live_ids: List[str] = []
        self.banked: Dict[str, int] = {}      # live id -> unspent points pool
        # live id -> cumulative level-up points GRANTED (Update 17 §D17-2.1);
        # the character's level is derived from it (T-78).
        self.earned: Dict[str, int] = {}
        # live id -> cumulative points SPENT at level-up screens (§D17-2.3);
        # the character's level is derived from THIS (T-78) — banked points
        # are potential, not level.
        self.spent: Dict[str, int] = {}
        # The level-up gate (None outside a phase boundary):
        # live id -> {"confirmed": bool, "spent": int, "heal": int}. Every
        # boundary opens one — spending is optional, confirming with an
        # unchanged build simply presses on.
        self.level_up: Optional[Dict[str, Dict[str, Any]]] = None
        self.gate_final: bool = False   # the terminal (act-end) gate, no phase follows
        self.carry: Dict[str, Dict[str, Any]] = {}
        # Whether a terminal screen opens after the FINAL phase. A scenario act
        # opens it behind the spoils (`open_final_gate`); a lone adventure ends.
        self.final_screen: bool = False
        # Phase indices whose points have been paid out (grants are once each).
        self.granted_phases: set = set()

    # -- phase composition ------------------------------------------------------ #
    def _scenario(self, phase_index: int) -> Dict[str, Any]:
        """The frozen encounter behind a phase (the detail embeds each phase's
        full encounter), in the build path's shape — enemy HP rescaled from the
        adventure's stamped difficulty to the run's (see `difficulty`)."""
        scen = content.scenario_from_detail(self.detail["phases"][phase_index])
        made_at = str(self.detail.get("difficulty") or "standard")
        content.apply_boss_difficulty(scen, self.difficulty or made_at)
        if self.difficulty and self.difficulty != made_at:
            from .llm import ENEMY_HP_MULT
            mult = ENEMY_HP_MULT.get(self.difficulty, 1.2) / ENEMY_HP_MULT.get(made_at, 1.2)
            if abs(mult - 1.0) > 1e-9:
                def bump(v: Any) -> Any:
                    try:
                        return max(1, -(-int(v) * mult // 1))
                    except (TypeError, ValueError):
                        return v
                for e in scen.get("enemies", []):
                    if isinstance(e, dict) and "hp" in e:
                        e["hp"] = int(bump(e["hp"]))
                for t in (scen.get("tokens") or {}).values():
                    if isinstance(t, dict) and "hp" in t:
                        t["hp"] = int(bump(t["hp"]))
        return scen

    def start(self, character_ids: List[str], seed: Optional[int] = None,
              loadouts: Optional[List[Dict[str, Any]]] = None
              ) -> "tuple[GameState, Dict[str, str], Dict[str, Any], str]":
        """Build Phase I from the base (saved) loadouts — or from ``loadouts``
        supplied directly (a run's frozen party copies). Returns
        ``(state, portraits, art, phase_encounter_id)``."""
        self.character_ids = list(character_ids)
        self.loadouts = (copy.deepcopy(loadouts) if loadouts is not None
                         else content.loadouts_for(character_ids))  # deep copies
        eid = self.phases[0]["encounter_id"]
        state, portraits, art = content.build_state_from_loadouts(
            self.loadouts, eid, seed=seed, scenario=self._scenario(0))
        self.live_ids = [c.id for c in state.party]
        # The unspent pool opens with whatever creation left over (§D10-3:
        # points are "added to the character's unspent pool").
        for live_id, lo in zip(self.live_ids, self.loadouts):
            try:
                char = Character.model_validate(lo["character"])
                self.banked[live_id] = max(0, char.points_remaining) if not char.legacy else 0
                self.earned[live_id] = int(char.earned_points)
                self.spent[live_id] = int(char.spent_points)
            except Exception:
                self.banked[live_id] = 0
                self.earned[live_id] = 0
                self.spent[live_id] = 0
        return state, portraits, art, eid

    def current_phase(self) -> Dict[str, Any]:
        return self.phases[self.phase_index]

    def is_final_phase(self) -> bool:
        return self.phase_index >= len(self.phases) - 1

    # -- the phase boundary ------------------------------------------------------ #
    def on_state_change(self, state: GameState) -> None:
        """Called after every engine state change: pays the phase's points the
        moment it is won, opens the boundary gate on a non-final phase, and
        marks the run complete when the finale is."""
        if state.result != "victory":
            return
        self._grant_phase_points()
        if self.is_final_phase():
            self.complete = True
            return
        if self.level_up is None:
            self._open_gate(state)

    def suppresses_result(self, result: Optional[str]) -> bool:
        """A non-final phase victory is a PHASE boundary, not a game over — the
        client sees the boundary gate instead. The finale's victory is held back
        too while a terminal (act-end) level-up screen is still open. Defeat
        passes through untouched."""
        return result == "victory" and (not self.complete or self.level_up is not None)

    # -- points (earned by winning, spent at a screen) --------------------------- #
    def _grant_phase_points(self) -> None:
        """Winning a phase pays its grant (+10 / +20 / +30, T-57) into every
        character's bankable pool. Spending it — and so the level (T-78) — is
        the player's call at the next screen."""
        i = self.phase_index
        if i in self.granted_phases:
            return
        self.granted_phases.add(i)
        grant = phase_grant(i)
        for live_id in self.live_ids:
            self.banked[live_id] = self.banked.get(live_id, 0) + grant
            self.earned[live_id] = self.earned.get(live_id, 0) + grant

    def open_final_gate(self) -> bool:
        """Open the TERMINAL level-up screen — the one a scenario act queues
        behind its spoils (§D17-2.3). Returns False when this run's policy has
        no terminal screen (a lone adventure, or the closing act of a Standard
        scenario, where the points are earned but the run ends)."""
        if not self.final_screen or not self.complete or self.level_up is not None:
            return False
        self.gate_final = True
        self.level_up = {live_id: {"confirmed": False, "spent": 0, "heal": 0}
                         for live_id in self.live_ids}
        return True

    @property
    def is_final_gate(self) -> bool:
        """True while the terminal gate is open: confirming it composes no next
        phase — the act wraps up instead."""
        return self.level_up is not None and self.gate_final

    def _open_gate(self, state: GameState) -> None:
        """Snapshot the carry state (§D10-2) and open the level-up gate (§D10-3)."""
        self.carry = {}
        for c in state.party:
            # Everything shuffles up together at the boundary — hand, library,
            # graveyard, and the cards of silently-dropped channels — and the
            # next phase opens on a FRESH hand of starting-cards (first-playtest
            # amendment: carrying the literal hand let cards accumulate).
            # A held channel whose card is the character's SHEET content — a
            # channeled Skill or Ultimate (D8-3) — is not a library card and
            # must not be folded in: doing so dealt the Skill into the next
            # phase's hand as a real deck card, one more copy per boundary.
            cards = (list(c.hand) + list(c.library) + list(c.graveyard)
                     + [ch.card for ch in c.channels
                        if ch.card.id not in _heroic_ids(c)])
            self.carry[c.id] = {
                "hp": c.hp,  # temp mods are encounter-duration; they clear
                "cards": copy.deepcopy(cards),
                "exile": copy.deepcopy(c.exile),
                "gauge": c.ultimate_gauge,
            }
        self.gate_final = False
        self.level_up = {
            live_id: {"confirmed": False, "spent": 0, "heal": 0}
            for live_id in self.live_ids
        }

    def derived_level(self, live_id: Optional[str] = None) -> int:
        """A character's level: derived from the points they have SPENT (T-78,
        §D17-2.3). ``live_id`` None = the party's first character."""
        lid = live_id if live_id is not None else (self.live_ids[0] if self.live_ids else None)
        return level_for_points(self.spent.get(lid, 0) if lid is not None else 0)

    def confirm_level_up(self, live_id: str, build: Dict[str, Any]) -> None:
        """Validate + apply one character's build at the open gate, banking the
        remainder. The points were paid when the phases were won, so this spends
        against the pool rather than granting into it. Raises ValueError on an
        invalid delta or a closed gate."""
        if self.level_up is None:
            raise ValueError("no level-up is pending")
        entry = self.level_up.get(live_id)
        if entry is None:
            raise ValueError(f"unknown character: {live_id}")
        if entry["confirmed"]:
            raise ValueError(f"{live_id} has already confirmed this level-up")
        slot = self.live_ids.index(live_id)
        old_raw = self.loadouts[slot]["character"]
        available = self.banked.get(live_id, 0)
        earned = self.earned.get(live_id, 0)
        spent_before = self.spent.get(live_id, 0)
        # The level is a function of the spend, and the Power cap (T-60) is a
        # function of the level — so price the build first at the highest level
        # the pool could reach, then hold it to the level it actually buys.
        ceiling = level_for_points(spent_before + available)
        new_raw, spent = validate_level_up(old_raw, build or {}, ceiling, available,
                                           earned_points=earned)
        new_level = level_for_points(spent_before + spent)
        if new_level != ceiling:
            new_raw, spent = validate_level_up(old_raw, build or {}, new_level, available,
                                               earned_points=earned)
        new_raw["spent_points"] = spent_before + spent
        heal = int(new_raw["hp"]) - int(old_raw.get("hp", new_raw["hp"]))
        self.loadouts[slot]["character"] = new_raw
        self.banked[live_id] = available - spent
        self.spent[live_id] = spent_before + spent
        entry.update(confirmed=True, spent=spent, heal=heal)

    def all_confirmed(self) -> bool:
        return (self.level_up is not None
                and all(e["confirmed"] for e in self.level_up.values()))

    def advance(self, seed: Optional[int] = None
                ) -> "tuple[GameState, Dict[str, str], Dict[str, Any], str]":
        """Compose the next phase: leveled builds through the standard build path,
        then the §D10-2 carry rules applied on top. Returns
        ``(state, portraits, art, phase_encounter_id)``."""
        if not self.all_confirmed():
            raise ValueError("not every character has confirmed the level-up")
        heals = {lid: e["heal"] for lid, e in (self.level_up or {}).items()}
        self.phase_index += 1
        self.level_up = None
        self.gate_final = False
        eid = self.phases[self.phase_index]["encounter_id"]
        state, portraits, art = content.build_state_from_loadouts(
            self.loadouts, eid, seed=seed, scenario=self._scenario(self.phase_index))
        rng = random.Random(seed)
        for c in state.party:
            cy = self.carry.get(c.id)
            if cy is None:
                continue
            # HP: carry, heal by the bought max (+2 max is +2 current), then the
            # phase-start floor — one rule for everyone (T-59). The incapacitated
            # stand back up at the floor; the barely-alive are lifted to it.
            floor = -(-c.max_hp * HP_FLOOR_PCT // 100)  # ceil(25% of max)
            c.hp = min(c.max_hp, max(cy["hp"] + heals.get(c.id, 0), floor))
            # Belt consumables and granted cards (Update 17): the freshly
            # composed hand dealt them above the draw; keep the ones not yet
            # used (a used consumable sits in exile with its item id) and put
            # them back above the reshuffled hand.
            used = {k.consumable_id for k in cy["exile"] if getattr(k, "consumable_id", None)}
            extras = [k for k in c.hand
                      if (getattr(k, "consumable_id", None) and k.consumable_id not in used)
                      or getattr(k, "granted_by", None)]
            # Shuffle up completely — hand, library, graveyard as one pool —
            # and draw a fresh hand of starting-cards. Exile is forever.
            # Consumables and granted abilities are re-dealt above (they are gear,
            # not deck); the Skill/Ultimate are sheet content and never deck at
            # all — the filter also scrubs copies an older save folded in.
            heroic = _heroic_ids(c)
            cards = [k for k in cy["cards"]
                     if not getattr(k, "consumable_id", None)
                     and not getattr(k, "granted_by", None)
                     and k.id not in heroic]
            rng.shuffle(cards)
            c.hand = extras + cards[:c.hand_size]
            c.library = cards[c.hand_size:]
            c.graveyard = []
            c.exile = list(cy["exile"])
            # Ultimate gauge carries at 50%, floored (T-58).
            c.ultimate_gauge = int(cy["gauge"] * GAUGE_CARRY)
        self.carry = {}
        return state, portraits, art, eid

    # -- run saves (Update 17 §D17-3) ------------------------------------------ #
    def boundary_snapshot(self) -> Dict[str, Any]:
        """The JSON-safe party/progress block a run save holds at a save point:
        the run copies of the characters (leveled builds), the unspent and
        earned pools, and — at a phase boundary — the §D10-2 carry plus the
        level-up heals so the next phase composes IDENTICALLY on reload.
        Called at adventure start (no carry), when the level-up gate closes
        (before `advance`), and at adventure end."""
        heals = ({lid: int(e.get("heal", 0)) for lid, e in self.level_up.items()}
                 if self.level_up is not None else {})
        carry = {
            lid: {
                "hp": cy["hp"],
                "cards": [c.model_dump(mode="json") for c in cy["cards"]],
                "exile": [c.model_dump(mode="json") for c in cy["exile"]],
                "gauge": cy["gauge"],
            }
            for lid, cy in self.carry.items()
        }
        return {
            "character_ids": list(self.character_ids),
            "live_ids": list(self.live_ids),
            "loadouts": copy.deepcopy(self.loadouts),
            "banked": dict(self.banked),
            "earned": dict(self.earned),
            "spent": dict(self.spent),
            "carry": carry,
            "heals": heals,
            # Which phases have already paid their grant (§D17-2.3) — so a
            # reload never pays a phase twice, and never skips one.
            "granted_phases": sorted(self.granted_phases),
            # At adventure start: 0 (Phase I about to begin). At a boundary: the
            # index of the phase just won (the next composes on restore). At the
            # end: the finale's index with `complete` set.
            "phase_index": self.phase_index,
            "complete": self.complete,
        }

    def restore(self, block: Dict[str, Any], seed: Optional[int] = None
                ) -> "tuple[GameState, Dict[str, str], Dict[str, Any], str]":
        """Rebuild the composed phase-start state from a `boundary_snapshot`
        block: adventure start replays `start`; a phase boundary replays
        `advance` (carry + heals applied) with the saved seed. Returns the same
        tuple those do."""
        from ltg_core.schema import Card as _Card
        self.character_ids = list(block.get("character_ids", []))
        self.banked = {k: int(v) for k, v in (block.get("banked") or {}).items()}
        self.earned = {k: int(v) for k, v in (block.get("earned") or {}).items()}
        # A save from before §D17-2.3 recorded no spending: credit the earned
        # total (the old scheme spent as it granted), so the level holds.
        self.spent = {k: int(v) for k, v in (block.get("spent") or self.earned).items()}
        self.complete = bool(block.get("complete"))
        phase_index = int(block.get("phase_index", 0))
        carry = block.get("carry") or {}
        granted = block.get("granted_phases")
        if granted is not None:
            self.granted_phases = {int(i) for i in granted}
        elif self.complete:                       # a save from before the ledger
            self.granted_phases = set(range(len(self.phases)))
        elif carry:
            self.granted_phases = set(range(phase_index + 1))
        else:
            self.granted_phases = set()
        if not carry:  # adventure start (or end): no boundary carry recorded
            out = self.start(self.character_ids, seed=seed,
                             loadouts=block.get("loadouts") or [])
            self.phase_index = phase_index
            # start() re-derives banked/earned from the loadouts; a save's
            # recorded pools win (they include this run's history).
            if block.get("banked"):
                self.banked = {k: int(v) for k, v in block["banked"].items()}
            if block.get("earned"):
                self.earned = {k: int(v) for k, v in block["earned"].items()}
            self.spent = {k: int(v) for k, v in (block.get("spent") or self.earned).items()}
            return out
        self.loadouts = copy.deepcopy(block.get("loadouts") or [])
        self.live_ids = list(block.get("live_ids") or [])
        self.carry = {
            lid: {
                "hp": int(cy["hp"]),
                "cards": [_Card.model_validate(c) for c in cy.get("cards", [])],
                "exile": [_Card.model_validate(c) for c in cy.get("exile", [])],
                "gauge": int(cy.get("gauge", 0)),
            }
            for lid, cy in carry.items()
        }
        heals = {k: int(v) for k, v in (block.get("heals") or {}).items()}
        # Re-open a fully-confirmed gate so `advance` finds its heals and the
        # boundary bookkeeping is byte-identical to the live path.
        self.level_up = {lid: {"confirmed": True, "spent": 0, "heal": heals.get(lid, 0)}
                         for lid in self.live_ids}
        # A boundary save records the phase just WON; `advance` composes the next.
        self.phase_index = phase_index
        return self.advance(seed=seed)

    # -- snapshot -------------------------------------------------------------- #
    def snapshot_block(self, state: GameState,
                       controlled_ids: "set[str]") -> Dict[str, Any]:
        """The per-client adventure block riding the state snapshot. The
        level-up gate is per-seat: your own characters carry their entering
        build and points; everyone else is just a confirmed/waiting light."""
        phase = self.current_phase()
        block: Dict[str, Any] = {
            "id": self.adventure_id,
            "name": self.name,
            "flavor": self.flavor,
            "phase": self.phase_index + 1,
            "phases_total": len(self.phases),
            "phase_name": phase["name"],
            "narration": phase["narration"],
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
                    # Progression readout (T-78, §D17-2.3): the level follows
                    # the points SPENT; the pool is what this screen may spend.
                    spent_now = self.spent.get(live_id, 0)
                    floor, ceiling = level_band(spent_now)
                    row["earned_points"] = self.earned.get(live_id, 0)
                    row["spent_points"] = spent_now
                    row["level"] = level_for_points(spent_now)
                    row["points_to_next_level"] = points_to_next_level(spent_now)
                    row["level_floor"] = floor
                    row["level_ceiling"] = ceiling
                    row["available"] = self.banked.get(live_id, 0)
                chars.append(row)
            block["level_up"] = {
                "final": self.gate_final,        # the act-end screen, behind the spoils
                "level": self.derived_level(),
                "points_per_level": POINTS_PER_LEVEL,
                "phase_grant": phase_grant(self.phase_index),
                "prices": price_table(),
                "characters": chars,
            }
        return block
