"""The scenario run — the campaign layer (Design Update 17 §D17-1, §D17-5,
§D17-6, §D17-7).

A `ScenarioRun` rides one `Session` for the whole campaign: a **town** + an
**arc** (villain, stakes, three act outlines) + **three acts** played in
order, each act = one town visit + one adventure. It owns everything the
scenario adds around the adventure layer:

- the town screen state (map / location / conversation), walked with the
  dialogue runtime and its closed hook set;
- the act materialization (quest, dialogue trees, arrival paragraph),
  generated on arrival — under the town-entry splash — and frozen into the
  run's content store;
- Quest Accept → auto-save → the adventure generation job (`jobs.py`),
  reflected on the greyed Start Adventure button;
- Start Adventure → an `AdventureRun` composed from the run's party copies;
  adventure end / defeat → back to town (Normal: `defeated_once`, the same
  quest re-offered; Hardcore: the run dies); Act III complete → Standard ends,
  Everquest generates a new arc for the same town.

Progression (levels, points, gold, flags) is persistent within the run and
never touches the saved profiles. The combat engine is untouched.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Callable, Dict, List, Optional

from ltg_core.schema import LEVEL_UP_POINTS, level_for_points, points_to_next_level

from . import content, llm, scenario_content as sc
from .adventure import AdventureRun, HP_FLOOR_PCT
from .dialogue import Conversation

# T-85: gold earned per phase level-up, per character (= points).
GOLD_PER_LEVEL_UP = 30
STANDING_FLAGS = ("defeated_once", "quest_accepted", "act_1_complete",
                  "act_2_complete", "act_3_complete")


class ScenarioRun:
    """All mutation happens under the session's lock (the app layer's)."""

    def __init__(self, town: Dict[str, Any], arc: Dict[str, Any],
                 character_ids: List[str], loadouts: List[Dict[str, Any]],
                 options: Optional[Dict[str, Any]] = None,
                 town_id: str = "", scenario_id: str = "") -> None:
        self.town_id = town_id or town.get("id", "")
        self.town: Dict[str, Any] = copy.deepcopy(town)
        self.town.pop("id", None)
        self.arc: Dict[str, Any] = copy.deepcopy(arc)
        self.scenario_id = scenario_id           # the pre-generated scenario, if any
        opts = {"difficulty": "standard", "hardcore": False, "everquest": False}
        opts.update({k: v for k, v in (options or {}).items() if k in opts})
        self.options = opts
        # Party (run copies; the profiles never see any of this).
        self.character_ids = list(character_ids)
        self.loadouts: List[Dict[str, Any]] = copy.deepcopy(loadouts)
        self.banked: Dict[str, int] = {cid: 0 for cid in character_ids}
        self.earned: Dict[str, int] = {cid: 0 for cid in character_ids}
        self.gold: Dict[str, int] = {cid: 0 for cid in character_ids}
        # Current HP carried between adventure and town (None == full).
        self.hp: Dict[str, Optional[int]] = {cid: None for cid in character_ids}
        for cid, lo in zip(self.character_ids, self.loadouts):
            ch = lo.get("character", {}) or {}
            self.earned[cid] = int(ch.get("earned_points", 0) or 0)
        # Progression
        self.scenario_number = 1
        self.act_index = 0
        self.mode = "town"                      # town | adventure | complete
        self.location_id: Optional[str] = None  # None == the town map
        self.conversation: Optional[Conversation] = None
        self.flags: Dict[str, bool] = {}
        self.act: Optional[Dict[str, Any]] = None   # this act's materialization
        self.act_ref: Optional[str] = None
        self.materializing = False
        self.materialize_error: Optional[str] = None
        self.quest: Dict[str, Any] = {"status": "none", "title": "", "text": "", "direct_to": None}
        self.adventure_unlocked = False          # write-once per act (§D17-5.4)
        self.adventure_id: Optional[str] = None  # this act's adventure (content id)
        self.adventure_ref: Optional[str] = None # its frozen detail's hash
        self.adventure_detail: Optional[Dict[str, Any]] = None
        self.adventure_job: Dict[str, Any] = {"state": "idle", "progress": [0, 0],
                                              "adventure_ref": None, "error": None}
        self.adventure: Optional[AdventureRun] = None
        self.previous_arcs: List[Dict[str, Any]] = []
        self.completed_acts: List[Dict[str, Any]] = []
        self.act_summaries: List[str] = []
        self.splash: Optional[Dict[str, Any]] = None  # the pending entry splash
        self.dead = False
        # Pluggable generators (tests swap them; the app uses llm.*).
        self.materializer: Callable[..., Dict[str, Any]] = llm.generate_act
        self.arc_generator: Callable[..., Dict[str, Any]] = llm.generate_arc

    # -- helpers ------------------------------------------------------------ #
    @property
    def outline(self) -> Dict[str, Any]:
        return self.arc["acts"][self.act_index]

    def slot_of(self, cid: str) -> int:
        return self.character_ids.index(cid)

    def levels(self) -> List[int]:
        return [level_for_points(self.earned.get(cid, 0)) for cid in self.character_ids]

    def effective_level(self) -> int:
        """T-81: derived level + floor(worn points ÷ 30). Gear arrives in Phase 2;
        until then the derived level (party average, floored, min 1)."""
        lv = self.levels()
        return max(1, int(sum(lv) / max(1, len(lv))))

    def party_state(self) -> Dict[str, Any]:
        members = []
        for cid, lo, lvl in zip(self.character_ids, self.loadouts, self.levels()):
            ch = lo.get("character", {}) or {}
            members.append({"id": cid, "name": ch.get("name", cid), "level": lvl,
                            "gold": self.gold.get(cid, 0)})
        return {"members": members, "flags": dict(self.flags),
                "gold": {m["name"]: m["gold"] for m in members}}

    def _sync_levels_into_loadouts(self) -> None:
        for cid, lo in zip(self.character_ids, self.loadouts):
            ch = lo.setdefault("character", {})
            ch["earned_points"] = int(self.earned.get(cid, 0))
            ch["level"] = level_for_points(ch["earned_points"])

    # -- arrival & materialization (§D17-6.2) ------------------------------ #
    def arrive(self, materialization: Optional[Dict[str, Any]] = None) -> None:
        """Begin the act in town: reset the act's per-visit state and either
        take a supplied materialization (a pre-generated Act I, or a reload) or
        mark the act as needing one (`materialize` then runs off-thread)."""
        self.mode = "town"
        self.location_id = None
        self.conversation = None
        self.adventure = None
        self.adventure_unlocked = False
        self.adventure_id = None
        self.adventure_ref = None
        self.adventure_detail = None
        self.adventure_job = {"state": "idle", "progress": [0, 0],
                              "adventure_ref": None, "error": None}
        self.quest = {"status": "none", "title": "", "text": "", "direct_to": None}
        self.flags.pop("quest_accepted", None)
        self.act = None
        self.act_ref = None
        self.materialize_error = None
        if materialization is not None:
            self._take_materialization(materialization)
        else:
            self.materializing = True
        self.splash = {"kind": "town", "title": self.town["name"],
                       "subtitle": f"Act {self.act_index + 1} — {self.outline['title']}",
                       "text": (self.act or {}).get("arrival", "")}

    def _take_materialization(self, m: Dict[str, Any]) -> None:
        self.act = copy.deepcopy(m)
        self.materializing = False
        self.materialize_error = None
        self.quest = {"status": "offered", "title": m["quest"]["title"],
                      "text": m["quest"]["text"], "direct_to": None}
        if self.splash and self.splash.get("kind") == "town":
            self.splash["text"] = m.get("arrival", "")

    def materialize(self) -> Dict[str, Any]:
        """Generate this act's town portion (blocking; the app runs it in a
        thread under the entry splash). Returns the materialization."""
        prev = self.act_summaries[-1] if self.act_summaries else ""
        try:
            m = self.materializer(self.town, self.arc, self.act_index,
                                  self.party_state(), prev)
        except ValueError as exc:
            self.materializing = False
            self.materialize_error = str(exc)
            raise
        self._take_materialization(m)
        return m

    # -- town movement (§D17-5.2) ------------------------------------------- #
    def visit(self, location_id: str) -> None:
        loc = sc.find_location(self.town, location_id)
        if loc is None:
            raise ValueError("no such location")
        self.location_id = location_id
        self.conversation = None
        line = ""
        if self.act:
            for npc in loc.get("npcs") or []:
                line = self.act.get("flavor", {}).get(npc["id"], "") or line
        self.splash = {"kind": "location", "title": loc["name"],
                       "subtitle": loc.get("function", "").replace("_", " "),
                       "text": line or loc.get("description", "")}

    def leave(self) -> None:
        self.location_id = None
        self.conversation = None
        self.splash = None

    def clear_splash(self) -> None:
        self.splash = None

    # -- dialogue (§D17-5.4) ------------------------------------------------ #
    def talk(self, npc_id: str) -> None:
        found = sc.find_npc(self.town, npc_id)
        if found is None:
            raise ValueError("no such NPC")
        loc, npc = found
        if self.location_id != loc["id"]:
            raise ValueError("you are not at that location")
        tree = (self.act or {}).get("dialogues", {}).get(npc_id)
        if tree is None:
            # No authored tree this act: a one-line greeting from the flavour
            # map (or the persona's first sentence) — a leaf conversation.
            line = (self.act or {}).get("flavor", {}).get(npc_id) or npc.get("persona", "").split(". ")[0] + "."
            tree = {"root": "r", "nodes": {"r": {"speaker": "npc", "text": line,
                                                 "choices": [{"label": "Farewell.", "next": None,
                                                              "requires": [], "effects": []}]}}}
        self.conversation = Conversation(npc_id, tree)

    def attribute(self, character_id: str) -> None:
        if self.conversation is None:
            raise ValueError("no conversation")
        if character_id not in self.character_ids:
            raise ValueError("unknown character")
        self.conversation.attributed = character_id

    def choice_is_party_wide(self, index: int) -> bool:
        if self.conversation is None:
            raise ValueError("no conversation")
        for ch in self.conversation.visible_choices(self.flags):
            if ch["index"] == index:
                return bool(ch["party_wide"])
        raise ValueError("that choice is not available")

    def choice_label(self, index: int) -> str:
        if self.conversation is None:
            return ""
        node = self.conversation.node or {}
        try:
            return node["choices"][index]["label"]
        except (KeyError, IndexError):
            return ""

    def choose(self, index: int) -> List[Dict[str, Any]]:
        """Take a choice; fire its hooks against the run state; return the
        hooks fired (the session decides which fired a save / a job)."""
        if self.conversation is None:
            raise ValueError("no conversation")
        hooks = self.conversation.choose(index, self.flags)
        fired: List[Dict[str, Any]] = []
        for h in hooks:
            self._apply_hook(h)
            fired.append(h)
        if self.conversation.over:
            self.conversation = None
        return fired

    def end_conversation(self) -> None:
        self.conversation = None

    def _apply_hook(self, h: Dict[str, Any]) -> None:
        kind = h["kind"]
        if kind == "set_flag":
            self.flags[h["flag"]] = bool(h.get("value", True))
        elif kind == "grant_quest":
            if self.quest.get("status") in ("none", "offered"):
                self.quest["status"] = "accepted"
            self.flags["quest_accepted"] = True
        elif kind == "advance_quest":
            if self.quest.get("status") == "accepted":
                self.quest["status"] = "advanced"
        elif kind == "unlock_adventure":
            self.adventure_unlocked = True   # write-once per act; the session starts the job
        elif kind == "give_gold":
            for cid in self.character_ids:
                self.gold[cid] = self.gold.get(cid, 0) + int(h.get("amount", 0))
        elif kind == "give_item":
            self.flags[f"item_{h.get('item')}"] = True  # Phase 2 lands the item itself
        elif kind == "rest":
            self.rest()
        elif kind == "open_shop":
            self.flags["_shop_open"] = True    # Phase 2: the shop modal (stub now)
        elif kind == "direct_to":
            self.quest["direct_to"] = {"npc": h.get("npc"), "location": h.get("location")}

    def rest(self) -> None:
        """The inn: full restore (HP; the adventure resets the rest)."""
        for cid in self.character_ids:
            self.hp[cid] = None

    # -- the adventure (§D17-6.3 / §D17-6.4) -------------------------------- #
    def adventure_context(self) -> Dict[str, Any]:
        outline = self.outline
        return {
            "arc_context": {"title": self.arc["title"], "villain": self.arc["villain"],
                            "stakes": self.arc["stakes"], "act": dict(outline),
                            "act_number": self.act_index + 1,
                            "acts_total": len(self.arc["acts"])},
            "town_context": {"name": self.town["name"],
                             "region_flavor": self.town.get("region_flavor", ""),
                             "npcs": [n["name"] for l in self.town["locations"] for n in l["npcs"]]},
            "quest_context": {"title": self.quest.get("title", ""),
                              "text": self.quest.get("text", "")},
        }

    def attach_adventure(self, adventure_id: str, detail: Dict[str, Any],
                         ref: Optional[str] = None) -> None:
        self.adventure_id = adventure_id
        self.adventure_detail = copy.deepcopy(detail)
        self.adventure_ref = ref

    @property
    def adventure_ready(self) -> bool:
        return (self.adventure_unlocked and self.adventure_detail is not None
                and self.adventure_job.get("state") in ("ready", "generated", "art_queued"))

    def start_adventure(self, seed: Optional[int] = None) -> "tuple":
        """Compose Phase I from the run's party copies (levels/points/HP carried).
        Returns the AdventureRun's start tuple; the session swaps modes."""
        if not self.adventure_ready or self.adventure_detail is None:
            raise ValueError("the adventure is not ready")
        self._sync_levels_into_loadouts()
        run = AdventureRun(self.adventure_id or "run-adventure", detail=self.adventure_detail)
        state, portraits, art, eid = run.start(self.character_ids, seed=seed,
                                               loadouts=self.loadouts)
        # Pools carry across acts (a lone adventure re-derives them; a run knows).
        for cid, live in zip(self.character_ids, run.live_ids):
            run.banked[live] = int(self.banked.get(cid, 0))
            run.earned[live] = int(self.earned.get(cid, 0))
        # HP carried in from town (None == full).
        for cid, c in zip(self.character_ids, state.party):
            hp = self.hp.get(cid)
            if hp is not None:
                c.hp = min(c.max_hp, max(1, int(hp)))
        self.adventure = run
        self.mode = "adventure"
        self.location_id = None
        self.conversation = None
        self.splash = None
        return state, portraits, art, eid

    def _harvest(self, run: AdventureRun, state: Any) -> None:
        """Pull the leveled builds, pools, gold, and HP back out of a finished
        (or lost) adventure into the run's party."""
        for cid, live, lo in zip(self.character_ids, run.live_ids, run.loadouts):
            slot = self.slot_of(cid)
            self.loadouts[slot] = copy.deepcopy(lo)
            old_earned = self.earned.get(cid, 0)
            self.earned[cid] = int(run.earned.get(live, old_earned))
            self.banked[cid] = int(run.banked.get(live, self.banked.get(cid, 0)))
            # T-85: gold at the points rate — every level-up grant is also gold.
            grants = max(0, self.earned[cid] - old_earned) // LEVEL_UP_POINTS
            self.gold[cid] = self.gold.get(cid, 0) + grants * GOLD_PER_LEVEL_UP
        for cid, c in zip(self.character_ids, getattr(state, "party", []) or []):
            floor = -(-c.max_hp * HP_FLOOR_PCT // 100)
            self.hp[cid] = min(c.max_hp, max(int(c.hp), floor))
        self._sync_levels_into_loadouts()

    def on_adventure_complete(self, state: Any) -> str:
        """The act's adventure is won: harvest, mark the act complete, and move
        to the next act (or end the scenario / roll the next arc). Returns the
        transition: "next_act" | "scenario_complete" | "everquest".
        The caller then calls `arrive()` (after any new arc is generated)."""
        run = self.adventure
        if run is not None:
            self._harvest(run, state)
        n = self.act_index + 1
        self.flags[f"act_{n}_complete"] = True
        self.flags.pop("defeated_once", None)
        self.quest["status"] = "complete"
        self.completed_acts.append({"act": n, "title": self.outline["title"],
                                    "quest": self.quest.get("title", ""),
                                    "adventure": (self.adventure_detail or {}).get("name", "")})
        self.act_summaries.append(
            f'Act {n} "{self.outline["title"]}": the party completed the quest '
            f'"{self.quest.get("title", "")}" — {(self.adventure_detail or {}).get("name", "the adventure")} '
            "was cleared.")
        self.adventure = None
        if n < len(self.arc["acts"]):
            self.act_index = n
            return "next_act"
        if self.options.get("everquest"):
            return "everquest"
        self.mode = "complete"
        return "scenario_complete"

    def begin_next_arc(self, arc: Dict[str, Any]) -> None:
        """Everquest: the previous arc is done; a fresh arc for the same town."""
        self.previous_arcs.append({"title": self.arc["title"], "villain": self.arc["villain"],
                                   "outcome": "defeated"})
        self.arc = copy.deepcopy(arc)
        self.scenario_number += 1
        self.act_index = 0
        for f in ("act_1_complete", "act_2_complete", "act_3_complete"):
            self.flags.pop(f, None)
        self.completed_acts = []
        self.act_summaries.append(f'A new arc begins: "{arc["title"]}" — {arc["villain"]}.')

    def on_adventure_defeat(self, state: Any) -> str:
        """Defeat: Normal returns the party to town with the quest unadvanced
        and `defeated_once` set (the act re-materializes on arrival with a
        defeat-aware tree); Hardcore ends the run. Returns "town" | "dead"."""
        run = self.adventure
        if run is not None:
            self._harvest(run, state)
        self.adventure = None
        if self.options.get("hardcore"):
            self.dead = True
            self.mode = "complete"
            return "dead"
        self.flags["defeated_once"] = True
        return "town"

    # -- quest log (§D17-5.6) ---------------------------------------------- #
    def quest_log(self) -> Dict[str, Any]:
        direct = self.quest.get("direct_to")
        pointer = None
        if direct:
            npc = sc.find_npc(self.town, direct.get("npc") or "")
            loc = sc.find_location(self.town, direct.get("location") or "") or (npc[0] if npc else None)
            pointer = {"npc": npc[1]["name"] if npc else None,
                       "location": loc["name"] if loc else None}
        return {
            "arc_title": self.arc["title"], "villain": self.arc["villain"],
            "stakes": self.arc["stakes"],
            "act_number": self.act_index + 1, "acts_total": len(self.arc["acts"]),
            "act_title": self.outline["title"],
            "quest": dict(self.quest), "direct_to": pointer,
            "completed": list(self.completed_acts),
            "scenario_number": self.scenario_number,
        }

    # -- snapshots (the town screen) ---------------------------------------- #
    def party_block(self) -> List[Dict[str, Any]]:
        out = []
        for cid, lo, lvl in zip(self.character_ids, self.loadouts, self.levels()):
            ch = lo.get("character", {}) or {}
            earned = self.earned.get(cid, 0)
            out.append({
                "id": cid, "name": ch.get("name", cid), "portrait": ch.get("portrait", ""),
                "level": lvl, "earned_points": earned,
                "points_to_next_level": points_to_next_level(earned),
                "banked": self.banked.get(cid, 0), "gold": self.gold.get(cid, 0),
                "hp": self.hp.get(cid), "max_hp": ch.get("hp"),
                "build": {"hp": ch.get("hp"), "starting_mana": list(ch.get("starting_mana", [])),
                          "starting_cards": ch.get("starting_cards"),
                          "power_bought": ch.get("power_bought", 0),
                          "keyword": ch.get("keyword"), "attack_mode": ch.get("attack_mode", "melee"),
                          "colors": list(ch.get("colors", [])), "description": ch.get("description", "")},
                "gear": {"primary": None, "secondary": None, "accessory": None,
                         "belt": [], "inventory": []},  # Phase 2 fills these
            })
        return out

    def town_snapshot(self) -> Dict[str, Any]:
        loc = sc.find_location(self.town, self.location_id) if self.location_id else None
        dialogues = (self.act or {}).get("dialogues", {})
        outline = self.outline
        return {
            "town": {
                "id": self.town_id, "name": self.town["name"],
                "region_flavor": self.town.get("region_flavor", ""),
                "scene": self.town.get("scene", ""), "art_url": self.town.get("art_url", ""),
                "locations": [
                    {"id": l["id"], "name": l["name"], "function": l.get("function", ""),
                     "description": l.get("description", ""), "art_url": l.get("art_url", ""),
                     "scene": l.get("scene", ""),
                     "questgiver": any(n["id"] == outline["questgiver_npc"] for n in l["npcs"]),
                     "has_dialogue": any(n["id"] in dialogues for n in l["npcs"]),
                     "npc_count": len(l["npcs"])}
                    for l in self.town["locations"]
                ],
            },
            "location": None if loc is None else {
                "id": loc["id"], "name": loc["name"], "function": loc.get("function", ""),
                "scene": loc.get("scene", ""), "art_url": loc.get("art_url", ""),
                "description": loc.get("description", ""),
                "npcs": [
                    {"id": n["id"], "name": n["name"], "role": n.get("role", ""),
                     "persona": n.get("persona", ""), "art_url": n.get("art_url", ""),
                     "has_dialogue": n["id"] in dialogues,
                     "questgiver": n["id"] == outline["questgiver_npc"],
                     "merchant": loc.get("function") in ("weaponsmith", "artificer", "apothecary"),
                     "flavor": (self.act or {}).get("flavor", {}).get(n["id"], "")}
                    for n in loc["npcs"]
                ],
            },
            "conversation": (self.conversation.snapshot(self.flags)
                             if self.conversation is not None else None),
            "splash": copy.deepcopy(self.splash),
            "materializing": self.materializing,
            "materialize_error": self.materialize_error,
            "quest_log": self.quest_log(),
            "scenario": {
                "title": self.arc["title"], "villain": self.arc["villain"],
                "act_number": self.act_index + 1, "acts_total": len(self.arc["acts"]),
                "act_title": outline["title"], "scenario_number": self.scenario_number,
                "options": dict(self.options), "mode": self.mode, "dead": self.dead,
                "scenario_id": self.scenario_id,
            },
            "adventure_job": dict(self.adventure_job),
            "adventure_unlocked": self.adventure_unlocked,
            "adventure_ready": self.adventure_ready,
            "adventure_name": (self.adventure_detail or {}).get("name", ""),
            "party": self.party_block(),
            "flags": dict(self.flags),
        }

    # -- save / restore (§D17-3) -------------------------------------------- #
    def snapshot(self) -> Dict[str, Any]:
        """The JSON-safe scenario block a run save holds (content refs only —
        the town/arc/act/adventure bodies live in the content store)."""
        return {
            "town_id": self.town_id, "scenario_id": self.scenario_id,
            "options": dict(self.options),
            "character_ids": list(self.character_ids),
            "banked": dict(self.banked), "earned": dict(self.earned),
            "gold": dict(self.gold), "hp": dict(self.hp),
            "scenario_number": self.scenario_number, "act_index": self.act_index,
            "mode": self.mode, "location_id": self.location_id,
            "flags": dict(self.flags), "quest": copy.deepcopy(self.quest),
            "adventure_unlocked": self.adventure_unlocked,
            "adventure_id": self.adventure_id,
            "adventure_job": dict(self.adventure_job),
            "previous_arcs": copy.deepcopy(self.previous_arcs),
            "completed_acts": copy.deepcopy(self.completed_acts),
            "act_summaries": list(self.act_summaries),
            "dead": self.dead,
            "act_present": self.act is not None,
        }

    def restore(self, block: Dict[str, Any], act: Optional[Dict[str, Any]],
                adventure_detail: Optional[Dict[str, Any]],
                loadouts: List[Dict[str, Any]]) -> None:
        self.character_ids = list(block.get("character_ids", self.character_ids))
        self.loadouts = copy.deepcopy(loadouts)
        self.options.update(block.get("options") or {})
        self.banked = {k: int(v) for k, v in (block.get("banked") or {}).items()}
        self.earned = {k: int(v) for k, v in (block.get("earned") or {}).items()}
        self.gold = {k: int(v) for k, v in (block.get("gold") or {}).items()}
        self.hp = {k: (None if v is None else int(v)) for k, v in (block.get("hp") or {}).items()}
        self.scenario_number = int(block.get("scenario_number", 1))
        self.act_index = int(block.get("act_index", 0))
        self.mode = str(block.get("mode", "town"))
        self.location_id = block.get("location_id")
        self.flags = {k: bool(v) for k, v in (block.get("flags") or {}).items()}
        self.quest = copy.deepcopy(block.get("quest") or self.quest)
        self.adventure_unlocked = bool(block.get("adventure_unlocked"))
        self.adventure_id = block.get("adventure_id")
        self.adventure_job = dict(block.get("adventure_job") or self.adventure_job)
        self.previous_arcs = copy.deepcopy(block.get("previous_arcs") or [])
        self.completed_acts = copy.deepcopy(block.get("completed_acts") or [])
        self.act_summaries = list(block.get("act_summaries") or [])
        self.dead = bool(block.get("dead"))
        self.conversation = None
        self.splash = None
        if act is not None:
            self.act = copy.deepcopy(act)
            self.materializing = False
        else:
            self.act = None
            self.materializing = self.mode == "town"
        if adventure_detail is not None:
            self.adventure_detail = copy.deepcopy(adventure_detail)
        if self.mode == "town" and self.location_id:
            # Reload lands on the location's screen without its splash.
            pass
        self._sync_levels_into_loadouts()

    def reload_town_art(self) -> None:
        fresh = sc.town_detail(self.town_id)
        if fresh:
            fresh.pop("id", None)
            self.town = fresh


# --------------------------------------------------------------------------- #
# Pre-generated scenarios (§D17-6.1): arc + Act I materialized, for a town
# --------------------------------------------------------------------------- #
def _generic_party() -> Dict[str, Any]:
    return {"size": 2, "avg_level": 1.0,
            "members": [{"name": "the first hero", "level": 1, "colors": []},
                        {"name": "the second hero", "level": 1, "colors": []}]}


def pregenerate_scenario(town_id: str, difficulty: str = "standard",
                         note: str = "") -> Dict[str, Any]:
    """Options → Scenarios → Generate: arc for the town, Act I's town portion,
    and Act I's adventure (generated for a generic level-1 party — layouts
    cover parties of 1–4 anyway). Persists the scenario; returns its meta."""
    town = sc.town_detail(town_id)
    if town is None:
        raise ValueError(f"unknown town: {town_id}")
    arc = llm.generate_arc(town, _generic_party(), difficulty, note=note)
    party_state = {"members": [{"name": "the party", "level": 1}], "flags": {}, "gold": {}}
    act1 = llm.generate_act(town, arc, 0, party_state)
    probe = ScenarioRun(town, arc, ["hero_1", "hero_2"],
                        [{"character": {"name": "the first hero", "colors": ["W"], "starting_mana": ["W"]}},
                         {"character": {"name": "the second hero", "colors": ["U"], "starting_mana": ["U"]}}],
                        {"difficulty": difficulty}, town_id=town_id)
    probe.arrive(act1)
    probe.quest["status"] = "accepted"
    context = probe.adventure_context()
    adv_meta = llm.generate_adventure(
        [], difficulty, note=note, loadouts=probe.loadouts, levels=[1, 1],
        base_level=1, context=context, run_only=True)
    return sc.save_scenario({
        "town_id": town_id, "arc": arc, "difficulty": difficulty,
        "act1": {"adventure_id": adv_meta["id"], "materialization": act1},
    })
