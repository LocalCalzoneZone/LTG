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
  quest re-offered; Hardcore: the run dies); Act III complete → the scenario
  ends and the campaign may continue through the interlude (Update 24).

Progression (levels, points, gold, flags) is persistent within the run and
never touches the saved profiles. The combat engine is untouched.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Callable, Dict, List, Optional

from ltg_core.schema import (LEVEL_THRESHOLDS, LEVEL_UP_POINTS, MAX_LEVEL, PHASE_GRANTS,
                             level_band, level_for_points, level_progress,
                             points_to_next_level)

from . import content, items, llm, loot, scenario_content as sc, world
from .adventure import AdventureRun, HP_FLOOR_PCT
from .dialogue import MAX_CHOICES, Conversation

# T-85: gold is earned at the POINTS rate, per character — a phase that pays
# +20 points pays 20 gold, so an act is worth 60 of each (§D17-2.3).
GOLD_PER_POINT = 1
GOLD_PER_LEVEL_UP = LEVEL_UP_POINTS * GOLD_PER_POINT
# Purse a character rides into a scenario with — enough that the first town
# visit is a real shop trip rather than window-shopping until Act I pays out.
STARTING_GOLD = 15
STANDING_FLAGS = ("defeated_once", "quest_accepted", "act_1_complete",
                  "act_2_complete", "act_3_complete")
# A party that said "let us get back to you" is asked again the next time they
# walk up to that NPC (§D17-5.4); the flag is per-NPC and lasts the act.
DEFERRED_PREFIX = "deferred_"
DEFAULT_REASK = "Well — have you had time to consider what I asked?"
DEFAULT_DEFER_LABEL = "Not yet — we have business to see to first."
# The questgiver answers (§D17-5.4, playtest amendment): an accept or a defer
# that would otherwise END the conversation cold gets a closing line from the
# NPC first. The act may author these per NPC ("accepted" / "declined"
# maps); these are the fallbacks.
DEFAULT_ACCEPT_REPLY = ("Then it is settled. Go carefully — and come back and "
                        "tell me how it went.")
DEFAULT_DEFER_REPLY = "As you like. You know where to find me when you have decided."
# One quest at a time: once the party has accepted an offer this act, every
# other accept choice in town turns into a refusal in the party's voice, and
# the NPC answers it (the act may author "committed" per NPC). The same
# questgiver's own re-offer reads as a reminder of the word already given.
DEFAULT_COMMITTED_LABEL = "We are already sworn to another task — we cannot take this on."
DEFAULT_COMMITTED_REPLY = ("Then I will not press you. See your business through; "
                           "the trouble will keep, though I wish it would not.")
DEFAULT_SWORN_LABEL = "We have given you our word. We are seeing to it."
DEFAULT_SWORN_REPLY = "Then I will keep you no longer. Go — and come back whole."
FAREWELL_LABEL = "Farewell."
# Update 24 §D24-7.5: the chronicle's kinds — engine-written, append-only,
# campaign-scoped per hero. `stance` is reserved for a later update's party
# lines; the kind exists so the schema does not change when they arrive.
CHRONICLE_KINDS = ("fell", "slew", "refused", "accepted", "spent", "bought", "met",
                   "stance", "levelled", "scarred")
# What the WRITERS see of a chronicle: the ten most recent lines (plus one
# summary line per past scenario, from the ledger).
CHRONICLE_RECENT = 10
# The day counter (§D24-10): +1 per ride-out; the interlude and the chosen
# hook add their own days.
DAYS_PER_RIDE_OUT = 1
# The custom fourth card on the rest screen covers this much road when the
# player writes their own premise.
CUSTOM_HOOK_DAYS = 7
HOOK_KINDS = ("stay", "neighbour", "new")


def _knows_prose(flag: str) -> str:
    """`knows_orc_camp` → "the orc camp" — what was learned, as prose."""
    body = flag[len("knows_"):].replace("_", " ").strip()
    return f"the {body}" if body else flag


def _boss_name(detail: Optional[Dict[str, Any]]) -> str:
    """The Phase III boss's name, off a frozen adventure detail."""
    for phase in reversed((detail or {}).get("phases") or []):
        enc = phase.get("encounter") or phase
        for e in enc.get("enemies") or []:
            if isinstance(e, dict) and e.get("is_boss"):
                return str(e.get("name") or e.get("id") or "")
    return ""


def _spent_points_of(ch: Dict[str, Any]) -> int:
    """A character dict's cumulative level-up spending — with the same
    migration the schema applies: a copy saved before §D17-2.3 is credited the
    earned total (the old scheme spent as it granted), or else what its stamped
    level implies."""
    if "spent_points" in ch:
        return int(ch.get("spent_points") or 0)
    earned = int(ch.get("earned_points", 0) or 0)
    level = int(ch.get("level", 1) or 1)
    return earned if earned > 0 else LEVEL_THRESHOLDS[max(1, min(level, MAX_LEVEL))]


class ScenarioRun:
    """All mutation happens under the session's lock (the app layer's)."""

    def __init__(self, town: Dict[str, Any], arc: Dict[str, Any],
                 character_ids: List[str], loadouts: List[Dict[str, Any]],
                 options: Optional[Dict[str, Any]] = None,
                 town_id: str = "", scenario_id: str = "") -> None:
        self.town_id = town_id or town.get("id", "")
        # `base_town` is the town as saved; `town` is the town AS THIS ACT SEES
        # IT — base plus the arc's cast and places present this act (§D20-2).
        # Recomposed at every arrival / arc change / art reload, never mutated
        # in place, so a visitor leaves no trace once their acts are over.
        self.base_town: Dict[str, Any] = copy.deepcopy(town)
        self.base_town.pop("id", None)
        self.arc: Dict[str, Any] = copy.deepcopy(arc)
        self.town: Dict[str, Any] = sc.town_for_act(self.base_town, self.arc, 0)
        # The scenario's loot vocabulary (§D17-4.5): drawn when the scenario is
        # made and frozen onto the arc, so what the bosses drop sounds like THIS
        # scenario and reads the same after a reload. An arc that arrives
        # without one (hand-written, or pre-dating the forge) draws one now.
        loot.lexicon_of(self.arc, self.town)
        self.scenario_id = scenario_id           # the pre-generated scenario, if any
        # The CAMPAIGN (Update 24 §D24-3): the run, extended — one fixed party,
        # one continuity. Everything here survives a scenario's end; it rides
        # run.json and every save snapshot (so a fork keeps its own history).
        self.campaign: Dict[str, Any] = self._fresh_campaign(character_ids, loadouts, self.town_id)
        # Per-act bookkeeping for the current scenario (§D24-8.1): what the
        # ledger entry is assembled from when the scenario closes.
        self.act_logs: List[Dict[str, Any]] = []
        self.scenario_day_start = 1
        # The interlude (§D24-5): the planner's result waiting for Continue,
        # its job state, the rest screen, and the road between scenarios.
        self.pending_interlude: Optional[Dict[str, Any]] = None
        self.interlude_ref: Optional[str] = None
        self.interlude_job: Dict[str, Any] = {"state": "idle", "error": None}
        self.continue_requested = False
        self.rest_screen = False
        self.transit: Optional[Dict[str, Any]] = None
        # Notices for the entry splash (a live-identity refresh, §D24-6).
        self.notices: List[str] = []
        # Update 24 §D24-1: Everquest is retired — difficulty and Normal/Hardcore
        # are the only run options (an old save's `everquest` key is dropped).
        opts = {"difficulty": "standard", "hardcore": False}
        opts.update({k: v for k, v in (options or {}).items() if k in opts})
        self.options = opts
        # Party (run copies; the profiles never see any of this).
        self.character_ids = list(character_ids)
        self.loadouts: List[Dict[str, Any]] = copy.deepcopy(loadouts)
        self.banked: Dict[str, int] = {cid: 0 for cid in character_ids}
        self.earned: Dict[str, int] = {cid: 0 for cid in character_ids}
        # Points SPENT at level-up screens (§D17-2.3): the character's level
        # derives from this, never from what is merely banked.
        self.spent: Dict[str, int] = {cid: 0 for cid in character_ids}
        self.gold: Dict[str, int] = {cid: STARTING_GOLD for cid in character_ids}
        # Current HP carried between adventure and town (None == full).
        self.hp: Dict[str, Optional[int]] = {cid: None for cid in character_ids}
        for cid, lo in zip(self.character_ids, self.loadouts):
            ch = lo.get("character", {}) or {}
            self.earned[cid] = int(ch.get("earned_points", 0) or 0)
            self.spent[cid] = _spent_points_of(ch)
        # Progression
        self.scenario_number = 1
        self.act_index = 0
        self.mode = "town"                      # town | adventure | complete | interlude
        self.location_id: Optional[str] = None  # None == the town map
        self.conversation: Optional[Conversation] = None
        self.flags: Dict[str, bool] = {}
        self.act: Optional[Dict[str, Any]] = None   # this act's materialization
        self.act_ref: Optional[str] = None
        self.materializing = False
        self.materialize_error: Optional[str] = None
        self.quest: Dict[str, Any] = {"status": "none", "title": "", "text": "", "id": "",
                                      "adventure_theme": "", "direct_to": None}
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
        # The Rewards modal after Phase III (§D17-4.5): rolled drops awaiting
        # assignment; None outside that moment.
        self.rewards: Optional[Dict[str, Any]] = None
        # How far the act's WRAP-UP has got (§D17-2.3), persisted so a reload
        # inside it resumes rather than replaying: None (not in it) →
        # "rewards" (the spoils modal) → "levelup" (the act-end level-up screen,
        # queued behind the spoils) → None again once the party rides to town.
        self.act_wrapup: Optional[str] = None
        # The JOURNAL: what the party has learned, in order — the act's intro
        # (the arrival paragraph), the lines townsfolk have told them, the
        # quest they agreed to. Nothing the party hasn't heard appears here.
        self.journal: List[Dict[str, Any]] = []
        # A lost adventure holds on the defeat splash until the party "flees".
        self.defeat_pending = False
        # A per-player shop view is stateless (stock lives on the act); the
        # pending two-party trade offer (§D17-5.3), if any.
        self.trade: Optional[Dict[str, Any]] = None
        # Pluggable generators (tests swap them; the app uses llm.*).
        self.materializer: Callable[..., Dict[str, Any]] = llm.generate_act
        self.arc_generator: Callable[..., Dict[str, Any]] = llm.generate_arc
        self.interlude_generator: Callable[..., Dict[str, Any]] = llm.generate_interlude
        self.town_generator: Callable[..., Dict[str, Any]] = llm.generate_town
        self.town = self._compose_town()

    # -- the campaign (Update 24 §D24-3) ----------------------------------- #
    @staticmethod
    def _fresh_campaign(character_ids: List[str], loadouts: List[Dict[str, Any]],
                        town_id: str) -> Dict[str, Any]:
        heroes: Dict[str, Any] = {}
        for cid, lo in zip(character_ids, loadouts):
            ch = (lo or {}).get("character", {}) or {}
            heroes[cid] = {"situation": str(ch.get("brief_situation") or "").strip(),
                           "chronicle": []}
        return {"ledger": [], "towns_visited": [town_id] if town_id else [],
                "current_town_id": town_id, "town_state": {}, "heroes": heroes,
                "hooks": None, "day": 1}

    @property
    def in_town(self) -> bool:
        return self.mode in ("town", "interlude")

    @property
    def day(self) -> int:
        return int(self.campaign.get("day", 1) or 1)

    def advance_days(self, days: int) -> None:
        self.campaign["day"] = self.day + max(0, int(days or 0))

    def current_town_state(self) -> Dict[str, Any]:
        return self.campaign.setdefault("town_state", {}).setdefault(
            self.town_id, {"flags": {}, "overrides": {}, "met": [], "talked": []})

    def _compose_town(self, act_index: Optional[int] = None) -> Dict[str, Any]:
        """The town as this act sees it: base + the arc's cast/places (§D20-2)
        + the campaign's memory of the place (§D24-8.2)."""
        idx = self.act_index if act_index is None else act_index
        state = (self.campaign.get("town_state") or {}).get(self.town_id)
        return sc.town_for_act(self.base_town, self.arc, idx, town_state=state)

    def _hero(self, cid: str) -> Dict[str, Any]:
        return self.campaign.setdefault("heroes", {}).setdefault(
            cid, {"situation": "", "chronicle": []})

    def hero_name(self, cid: str) -> str:
        try:
            return str(self.loadouts[self.slot_of(cid)].get("character", {}).get("name") or cid)
        except (ValueError, IndexError):
            return cid

    def chronicle_add(self, cid: str, kind: str, text: str) -> None:
        """Append one deed to a hero's chronicle (§D24-7.5): engine-written,
        append-only, campaign-scoped. Duplicate of the last line is dropped."""
        if kind not in CHRONICLE_KINDS:
            raise ValueError(f"unknown chronicle kind: {kind}")
        text = (text or "").strip()
        if not text or cid not in self.character_ids:
            return
        entry = {"scenario": self.scenario_number, "act": self.act_index + 1,
                 "day": self.day, "kind": kind, "text": text}
        rows = self._hero(cid)["chronicle"]
        if rows and rows[-1] == entry:
            return
        rows.append(entry)

    def chronicle_of(self, cid: str) -> List[Dict[str, Any]]:
        return [dict(e) for e in self._hero(cid).get("chronicle") or []]

    def chronicle_view(self, cid: str) -> Dict[str, Any]:
        """What the writers see: the ten most recent lines plus one summary
        line per past scenario (the ledger's one-liner)."""
        rows = self._hero(cid).get("chronicle") or []
        summaries = [e.get("one_liner", "") for e in self.campaign.get("ledger") or []
                     if int(e.get("scenario", 0)) < self.scenario_number and e.get("one_liner")]
        return {"recent": [dict(e) for e in rows[-CHRONICLE_RECENT:]], "summaries": summaries}

    def situation_of(self, cid: str) -> str:
        return str(self._hero(cid).get("situation") or "")

    def set_situation(self, cid: str, text: str) -> None:
        """The rest screen's situation editor (§D24-7.4): the one place a
        player steers characterisation between sessions."""
        if cid not in self.character_ids:
            raise ValueError("unknown character")
        words = (text or "").strip().split()
        self._hero(cid)["situation"] = " ".join(words[:80])

    # -- the ledger (§D24-8.1) --------------------------------------------- #
    def _act_log(self) -> Dict[str, Any]:
        while len(self.act_logs) <= self.act_index:
            n = len(self.act_logs)
            title = self.arc["acts"][n]["title"] if n < len(self.arc.get("acts") or []) else ""
            self.act_logs.append({"act": n + 1, "title": title, "accepted": None, "refused": [],
                                  "adventure": "", "boss": "", "fallen": [], "defeats": 0,
                                  "met": [], "learned": [], "gold_spent": {}, "items_bought": []})
        return self.act_logs[self.act_index]

    def _ledger_entry(self, outcome: str) -> Dict[str, Any]:
        town_name = self.town.get("name", self.town_id)
        villain = self.arc.get("villain", "")
        title = self.arc.get("title", "")
        if outcome == "victory":
            one = f'In {town_name} the party defeated {villain} — "{title}".'
        elif outcome == "in progress":
            one = f'In {town_name} the party is set against {villain} — "{title}".'
        else:
            one = f'In {town_name} the party {outcome} against {villain} — "{title}".'
        fallen = sorted({h for log in self.act_logs for h in log.get("fallen") or []})
        if fallen and outcome == "victory":
            one += f" {', '.join(fallen)} fell along the way."
        return {"scenario": self.scenario_number, "title": title, "villain": villain,
                "town_id": self.town_id, "town_name": town_name, "outcome": outcome,
                "days": max(0, self.day - self.scenario_day_start), "one_liner": one,
                "acts": copy.deepcopy(self.act_logs)}

    def _close_scenario_ledger(self, outcome: str = "victory") -> Dict[str, Any]:
        """Write (or rewrite) this scenario's ledger entry. Idempotent per
        scenario number, so the provisional entry the planner reads at boss
        death and the final one written at the scenario's end agree."""
        entry = self._ledger_entry(outcome)
        ledger = self.campaign.setdefault("ledger", [])
        if ledger and int(ledger[-1].get("scenario", 0)) == self.scenario_number:
            ledger[-1] = entry
        else:
            ledger.append(entry)
        return entry

    def ledger_for_writers(self) -> List[Dict[str, Any]]:
        """The ledger as the writers read it: every closed scenario plus the
        current one in progress (so the act writer of Act II knows Act I)."""
        rows = copy.deepcopy(self.campaign.get("ledger") or [])
        if not rows or int(rows[-1].get("scenario", 0)) != self.scenario_number:
            if self.act_logs:
                rows.append(self._ledger_entry("in progress"))
        return rows

    def world_context(self) -> Dict[str, Any]:
        try:
            return world.context_for(self.town_id)
        except Exception:
            return {"entry": None, "region": None, "neighbours": []}

    # -- helpers ------------------------------------------------------------ #
    @property
    def outline(self) -> Dict[str, Any]:
        return self.arc["acts"][self.act_index]

    def slot_of(self, cid: str) -> int:
        return self.character_ids.index(cid)

    def levels(self) -> List[int]:
        """Character levels — derived from points SPENT (T-78, §D17-2.3)."""
        return [level_for_points(self.spent.get(cid, 0)) for cid in self.character_ids]

    def potential_levels(self) -> List[float]:
        """The level each character's EARNED points reach, as a continuous
        number — what they could be if they spent everything. Encounter
        budgets and item tiers read this, so a bank of unspent points is never
        a way to face weaker enemies."""
        return [level_progress(self.earned.get(cid, 0)) for cid in self.character_ids]

    def effective_level(self) -> int:
        """T-81: potential level + floor(worn points ÷ 30), party average,
        floored. Budgets and tiers read this."""
        lv = [l + items.effective_level_bonus(lo)
              for l, lo in zip(self.potential_levels(), self.loadouts)]
        return max(1, int(sum(lv) / max(1, len(lv))))

    def act_tier(self) -> int:
        """The act's item tier: the party's effective level (drops), the
        merchant stock caps below it (§D17-4.3)."""
        return max(1, self.effective_level())

    def spoils_tier(self) -> int:
        """The boss tier — one above the tier the act's shops sell at, and read
        on ARRIVAL, since the spoils are forged then (the party is a level or so
        stronger by the time they reach Phase III, which is what the +1 buys)."""
        return self.act_tier() + 1

    def party_state(self) -> Dict[str, Any]:
        """What the writers are told about the party (§D24-7.6): per hero the
        brief, the situation, the recent chronicle and the past scenarios'
        summaries; the run's PUBLIC flags (`_`-prefixed bookkeeping never
        reaches a writer — §D24-7.7) with `knows_*` moved to a `knows` list."""
        members = []
        for cid, lo, lvl in zip(self.character_ids, self.loadouts, self.levels()):
            ch = lo.get("character", {}) or {}
            brief = ch.get("brief") if isinstance(ch.get("brief"), dict) else {}
            view = self.chronicle_view(cid)
            members.append({"id": cid, "name": ch.get("name", cid), "level": lvl,
                            "gold": self.gold.get(cid, 0),
                            "colors": list(ch.get("colors") or []),
                            "concept": str(brief.get("concept") or ch.get("description") or ""),
                            "brief": copy.deepcopy(brief),
                            "situation": self.situation_of(cid),
                            "chronicle_recent": view["recent"],
                            "chronicle_summaries": view["summaries"]})
        flags = {k: v for k, v in self.flags.items()
                 if not k.startswith("_") and not k.startswith("knows_")}
        knows = sorted(k for k, v in self.flags.items() if k.startswith("knows_") and v)
        return {"members": members, "flags": flags, "knows": knows,
                "gold": {m["name"]: m["gold"] for m in members}, "day": self.day}

    def _sync_levels_into_loadouts(self) -> None:
        for cid, lo in zip(self.character_ids, self.loadouts):
            ch = lo.setdefault("character", {})
            ch["earned_points"] = int(self.earned.get(cid, 0))
            ch["spent_points"] = int(self.spent.get(cid, 0))
            ch["level"] = level_for_points(ch["spent_points"])

    # -- arrival & materialization (§D17-6.2) ------------------------------ #
    def arrive(self, materialization: Optional[Dict[str, Any]] = None,
               interlude: bool = False) -> None:
        """Begin the act in town: reset the act's per-visit state and either
        take a supplied materialization (a pre-generated Act I, or a reload) or
        mark the act as needing one (`materialize` then runs off-thread).
        ``interlude`` (§D24-5.2): the town after victory — act-shaped, no quest."""
        self.mode = "interlude" if interlude else "town"
        self.transit = None
        self.rest_screen = False
        self.town = self._compose_town()
        self.location_id = None
        self.conversation = None
        self.adventure = None
        self.adventure_unlocked = False
        self.adventure_id = None
        self.adventure_ref = None
        self.adventure_detail = None
        self.adventure_job = {"state": "idle", "progress": [0, 0],
                              "adventure_ref": None, "error": None}
        self.quest = {"status": "none", "title": "", "text": "", "id": "",
                      "adventure_theme": "", "direct_to": None}
        self.flags.pop("quest_accepted", None)
        for flag in [f for f in self.flags if f.startswith(DEFERRED_PREFIX)]:
            self.flags.pop(flag, None)
        self.act = None
        self.act_ref = None
        self.materialize_error = None
        if materialization is not None:
            self._take_materialization(materialization)
        else:
            self.materializing = True
        subtitle = (f"Between scenarios — the Interlude · day {self.day}" if interlude
                    else f"Act {self.act_index + 1} — {self.outline['title']}")
        self.splash = {"kind": "town", "title": self.town["name"],
                       "subtitle": subtitle,
                       "text": (self.act or {}).get("arrival", "")}

    def _take_materialization(self, m: Dict[str, Any]) -> None:
        self.act = copy.deepcopy(m)
        self.materializing = False
        self.materialize_error = None
        self.add_journal("intro", m.get("arrival", ""))
        # Merchant stock (§D17-5.5): rolled in code at the act's tier, fixed
        # for the act, refreshed each act — unless the materialization already
        # carries it (a reload, a pre-generated Act I).
        if not self.act.get("stock"):
            seed = random.randrange(2**31)
            stock: Dict[str, List[Dict[str, Any]]] = {}
            for loc in self.town.get("locations") or []:
                rolled = items.roll_stock(loc.get("function", ""), self.act_tier(),
                                          seed=seed + sum(ord(ch) for ch in loc["id"]))
                if rolled:
                    stock[loc["id"]] = [it.model_dump(mode="json", exclude_none=True) for it in rolled]
            self.act["stock"] = stock
        # The act's SPOILS (§D17-4.5): forged here, on arrival — the same moment
        # the stock is rolled — and frozen onto the act, so the art queue has the
        # whole town visit and the whole ride out to paint them. What the boss
        # drops is settled before the party ever leaves town; only the reveal
        # waits. (Frozen, so a reload shows the same spoils and reuses the art.)
        if not self.act.get("spoils") and self.mode != "interlude":
            self.act["spoils"] = [it.model_dump(mode="json", exclude_none=True)
                                  for it in loot.forge_drops(
                                      len(self.character_ids), self.spoils_tier(),
                                      loot.lexicon_of(self.arc, self.town),
                                      seed=random.randrange(2**31))]
        if self.mode == "interlude":
            # No quest between scenarios: rest is the only exit (§D24-5).
            self.quest = {"status": "none", "id": "", "title": "", "text": "",
                          "adventure_theme": "", "direct_to": None}
            if self.splash and self.splash.get("kind") == "town":
                self.splash["text"] = m.get("arrival", "")
            return
        first = (self.quest_options or [{"id": "", "title": m.get("quest", {}).get("title", ""),
                                         "text": m.get("quest", {}).get("text", ""),
                                         "adventure_theme": ""}])[0]
        # "offered" holds the first option only as a placeholder: which quest the
        # act actually becomes is settled by the accept choice the party takes.
        self.quest = {"status": "offered", "id": first.get("id", ""),
                      "title": first.get("title", ""), "text": first.get("text", ""),
                      "adventure_theme": first.get("adventure_theme", ""), "direct_to": None}
        if self.splash and self.splash.get("kind") == "town":
            self.splash["text"] = m.get("arrival", "")

    def materialize(self) -> Dict[str, Any]:
        """Generate this act's town portion (blocking; the app runs it in a
        thread under the entry splash). Returns the materialization."""
        prev = self.act_summaries[-1] if self.act_summaries else ""
        try:
            m = self.materializer(self.town, self.arc, self.act_index,
                                  self.party_state(), prev,
                                  ledger=self.ledger_for_writers(),
                                  world_ctx=self.world_context())
        except ValueError as exc:
            self.materializing = False
            self.materialize_error = str(exc)
            raise
        self._take_materialization(m)
        self._apply_town_state_delta(m.get("town_state_delta"))
        return m

    def _apply_town_state_delta(self, delta: Optional[Dict[str, Any]]) -> None:
        """A writer's `town_state_delta` (§D24-8.2): one or two location
        overrides tied to what happened, kept on the campaign and composed
        onto the town from now on."""
        if not delta:
            return
        state = self.current_town_state()
        overrides = state.setdefault("overrides", {})
        for loc_id, patch in delta.items():
            if not isinstance(patch, dict):
                continue
            row = overrides.setdefault(loc_id, {})
            for k in ("description", "exterior_scene", "interior_scene"):
                if patch.get(k):
                    row[k] = str(patch[k]).strip()
        self.town = self._compose_town()

    # -- town movement (§D17-5.2) ------------------------------------------- #
    def visit(self, location_id: str) -> None:
        loc = sc.find_location(self.town, location_id)
        if loc is None:
            raise ValueError("no such location")
        self.location_id = location_id
        self.conversation = None
        # The entry splash describes the ROOM the party just walked into — what
        # they see, hear, and smell standing in it (`interior_scene`, the same
        # text the interior art is painted from). It used to borrow an NPC's
        # greeting line from the act's flavour map, which read as a stray snippet
        # of a conversation nobody had started yet; those lines belong to `talk`.
        self.splash = {"kind": "location", "title": loc["name"],
                       "subtitle": loc.get("function", "").replace("_", " "),
                       "text": (loc.get("interior_scene")
                                or loc.get("description", ""))}

    def leave(self) -> None:
        self.location_id = None
        self.conversation = None
        self.splash = None

    def clear_splash(self) -> None:
        self.splash = None

    # -- dialogue (§D17-5.4) ------------------------------------------------ #
    @property
    def quest_options(self) -> List[Dict[str, Any]]:
        """This act's quest offers — what the party may agree to (§D17-5.4)."""
        return list((self.act or {}).get("quests") or [])

    def quest_option(self, quest_id: Optional[str]) -> Optional[Dict[str, Any]]:
        options = self.quest_options
        if not options:
            return None
        return next((q for q in options if q["id"] == quest_id), options[0])

    def talk(self, npc_id: str) -> None:
        found = sc.find_npc(self.town, npc_id)
        if found is None:
            raise ValueError("no such NPC")
        loc, npc = found
        if self.location_id != loc["id"]:
            raise ValueError("you are not at that location")
        tree = (self.act or {}).get("dialogues", {}).get(npc_id)
        if tree is None:
            tree = self._flavor_tree(npc)
        elif (self.flags.get(DEFERRED_PREFIX + npc_id)
              and not self.flags.get("quest_accepted")):
            # "Let us get back to you" — so they do: the NPC opens by asking
            # again, with the same offers still on the table.
            tree = self._reask_tree(npc_id, tree)
        if self.committed:
            tree = self._committed_tree(npc_id, tree)
        self.conversation = Conversation(npc_id, tree)
        self._note_meeting(loc, npc)
        self._note_npc_line()
        self._note_quest_offers()

    @property
    def committed(self) -> bool:
        """The party has taken a quest this act and is still on it: no other
        offer in town may be accepted (one quest at a time — a second accept
        used to fire a second adventure job on top of the first). A party
        beaten and sent back to town (`defeated_once`) is free to re-choose —
        the bloodied-return branches re-offer the quests by design."""
        return bool(self.flags.get("quest_accepted")) and not self.flags.get("defeated_once")

    def _committed_tree(self, npc_id: str, tree: Dict[str, Any]) -> Dict[str, Any]:
        """The already-sworn rewrite: every accept choice (`grant_quest` /
        `unlock_adventure`) becomes ONE refusal per node in the party's voice
        that fires nothing and leads to the NPC's reply; the defer choices
        beside it go (there is nothing left to put off). The questgiver whose
        offer the party took hears a reminder of the word given instead."""
        act = self.act or {}
        nodes = copy.deepcopy(tree["nodes"])
        taken = str(self.quest.get("id") or "")
        reply_id = "committed_reply"
        while reply_id in nodes:
            reply_id = "_" + reply_id
        sworn_id = "sworn_reply"
        while sworn_id in nodes:
            sworn_id = "_" + sworn_id
        used_reply = used_sworn = False
        for node in nodes.values():
            accepts = [ch for ch in node["choices"]
                       if any(h["kind"] in ("grant_quest", "unlock_adventure")
                              for h in ch["effects"])]
            if not accepts:
                continue
            same = any(h["kind"] == "grant_quest"
                       and (self.quest_option(h.get("quest")) or {}).get("id") == taken
                       for ch in accepts for h in ch["effects"])
            kept = [ch for ch in node["choices"]
                    if ch not in accepts
                    and not any(h["kind"] == "defer_quest" for h in ch["effects"])]
            if same:
                used_sworn = True
                kept.append(self._choice(DEFAULT_SWORN_LABEL, sworn_id))
            else:
                used_reply = True
                kept.append(self._choice(DEFAULT_COMMITTED_LABEL, reply_id))
            node["choices"] = kept
        if used_reply:
            nodes[reply_id] = {
                "speaker": "npc",
                "text": act.get("committed", {}).get(npc_id) or DEFAULT_COMMITTED_REPLY,
                "choices": [self._choice(FAREWELL_LABEL)],
            }
        if used_sworn:
            nodes[sworn_id] = {
                "speaker": "npc",
                "text": DEFAULT_SWORN_REPLY,
                "choices": [self._choice(FAREWELL_LABEL)],
            }
        return {"root": tree["root"], "nodes": nodes}

    @staticmethod
    def _choice(label: str, nxt: Optional[str] = None,
                effects: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        return {"label": label, "next": nxt, "requires": [], "effects": effects or []}

    def _flavor_tree(self, npc: Dict[str, Any]) -> Dict[str, Any]:
        """An NPC with no authored tree this act still holds a conversation: a
        greeting, then their TOPICS — the town's scenario-agnostic ones plus
        whatever this act added to them — each as a thing the party can ask
        about (§D17-5.4). Every townsperson is worth walking up to."""
        act = self.act or {}
        greeting = (act.get("flavor", {}).get(npc["id"])
                    or npc.get("persona", "").split(". ")[0] + ".")
        topics = list(act.get("topics", {}).get(npc["id"]) or []) + list(npc.get("topics") or [])
        nodes: Dict[str, Any] = {"r": {"speaker": "npc", "text": greeting, "choices": []}}
        for i, topic in enumerate(topics[:MAX_CHOICES - 1], start=1):
            nid = f"t{i}"
            nodes[nid] = {"speaker": "npc", "text": topic["reply"],
                          "choices": [self._choice("Farewell.")]}
            ask = self._choice(topic["ask"], nid)
            # §D20-1: a gated act topic only becomes askable once the party has
            # LEARNED of the thing (the walker filters on the run's flags).
            ask["requires"] = list(topic.get("requires") or [])
            nodes["r"]["choices"].append(ask)
        nodes["r"]["choices"].append(self._choice("Farewell."))
        return {"root": "r", "nodes": nodes}

    def _reask_tree(self, npc_id: str, tree: Dict[str, Any]) -> Dict[str, Any]:
        """The deferred-answer opening: the same tree with a new root where the
        NPC asks whether the party has thought it over, carrying every accept
        choice they had offered — and the option to put it off again."""
        accepts: List[Dict[str, Any]] = []
        seen: set = set()
        for node in tree["nodes"].values():
            for ch in node["choices"]:
                quests = tuple(sorted(h.get("quest", "") for h in ch["effects"]
                                      if h["kind"] == "grant_quest"))
                if not quests or quests in seen:
                    continue
                seen.add(quests)
                accepts.append(copy.deepcopy(ch))
        if not accepts:
            return tree
        # Ungated offers first: a bloodied-return branch's accept only shows
        # once its flag is set, and the walker filters it either way.
        accepts.sort(key=lambda ch: len(ch["requires"]))
        accepts = accepts[:MAX_CHOICES - 1]
        nodes = copy.deepcopy(tree["nodes"])
        root = "reask"
        while root in nodes:
            root = "_" + root
        nodes[root] = {
            "speaker": "npc",
            "text": (self.act or {}).get("reask", {}).get(npc_id) or DEFAULT_REASK,
            "choices": accepts + [self._choice(DEFAULT_DEFER_LABEL,
                                               effects=[{"kind": "defer_quest"}])],
        }
        return {"root": root, "nodes": nodes}

    def attribute(self, character_id: str) -> None:
        if self.conversation is None:
            raise ValueError("no conversation")
        if character_id not in self.character_ids:
            raise ValueError("unknown character")
        self.conversation.attributed = character_id
        # The transcript's current "party" line was recorded before the
        # attribution — keep it in step.
        lines = self.conversation.lines
        if lines and lines[-1]["speaker"] == "party":
            lines[-1]["attributed"] = character_id

    def choice_is_party_wide(self, index: int) -> bool:
        if self.conversation is None:
            raise ValueError("no conversation")
        for ch in self.conversation.visible_choices(self.flags):
            if ch["index"] == index:
                return bool(ch["party_wide"])
        raise ValueError("that choice is not available")

    def choice_quest_title(self, index: int) -> str:
        """The title of the quest the choice at ``index`` would accept, or ""
        when it accepts nothing — the all-players confirmation names it."""
        if self.conversation is None:
            return ""
        node = self.conversation.node or {}
        try:
            effects = node["choices"][index].get("effects") or []
        except (KeyError, IndexError):
            return ""
        for h in effects:
            if h.get("kind") == "grant_quest":
                option = self.quest_option(h.get("quest"))
                return option["title"] if option else self.quest.get("title", "")
        return ""

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
            # The questgiver answers: an accept / defer that would close the
            # conversation cold gets the NPC's closing line first (authored
            # per NPC in the act's "accepted" / "declined" maps, else the
            # defaults). A choice whose author wrote a `next` node already
            # carries its own reply and is left alone.
            reply = self._closing_reply(self.conversation.npc_id,
                                        {h["kind"] for h in fired})
            if reply:
                self.conversation.interject(reply, FAREWELL_LABEL)
                self._note_npc_line()
            else:
                self.conversation = None
        else:
            self._note_npc_line()
            self._note_quest_offers()
        return fired

    def _closing_reply(self, npc_id: str, kinds: "set[str]") -> str:
        act = self.act or {}
        if "grant_quest" in kinds or "unlock_adventure" in kinds:
            return act.get("accepted", {}).get(npc_id) or DEFAULT_ACCEPT_REPLY
        if "defer_quest" in kinds:
            return act.get("declined", {}).get(npc_id) or DEFAULT_DEFER_REPLY
        return ""

    def end_conversation(self) -> None:
        self.conversation = None

    def _apply_hook(self, h: Dict[str, Any]) -> None:
        kind = h["kind"]
        if kind == "set_flag":
            flag = str(h["flag"])
            self.flags[flag] = bool(h.get("value", True))
            if flag.startswith("knows_") and self.flags[flag]:
                learned = self._act_log()["learned"]
                if _knows_prose(flag) not in learned:
                    learned.append(_knows_prose(flag))
        elif kind == "grant_quest":
            # WHICH offer the party took decides the act — and, with it, what
            # the adventure generator is handed (§D17-5.4).
            option = self.quest_option(h.get("quest"))
            if option is not None:
                self.quest.update({"id": option["id"], "title": option["title"],
                                   "text": option["text"],
                                   "adventure_theme": option.get("adventure_theme", "")})
            if self.quest.get("status") in ("none", "offered"):
                self.quest["status"] = "accepted"
            self.flags["quest_accepted"] = True
            # The ledger and the chronicles (§D24-8.1, §D24-7.5): the offer
            # taken, and every offer left on the table — refused, and remembered.
            log = self._act_log()
            taken = option or {"id": self.quest.get("id", ""), "title": self.quest.get("title", "")}
            log["accepted"] = {"id": taken.get("id", ""), "title": taken.get("title", "")}
            log["refused"] = [{"id": q["id"], "title": q["title"]} for q in self.quest_options
                              if q["id"] != taken.get("id")]
            for cid in self.character_ids:
                self.chronicle_add(cid, "accepted", f'Took on "{taken.get("title", "")}".')
                for q in log["refused"]:
                    self.chronicle_add(cid, "refused", f'Turned down "{q["title"]}".')
            for flag in [f for f in self.flags if f.startswith(DEFERRED_PREFIX)]:
                self.flags.pop(flag, None)
            self.add_journal("quest", f'We took on "{self.quest.get("title", "")}". {self.quest.get("text", "")}')
        elif kind == "defer_quest":
            npc_id = self.conversation.npc_id if self.conversation is not None else ""
            if npc_id:
                self.flags[DEFERRED_PREFIX + npc_id] = True
            found = sc.find_npc(self.town, npc_id)
            if found is not None:
                self.add_journal("event", f"We told {found[1]['name']} we would think on it "
                                          "and come back.")
        elif kind == "advance_quest":
            if self.quest.get("status") == "accepted":
                self.quest["status"] = "advanced"
        elif kind == "unlock_adventure":
            self.adventure_unlocked = True   # write-once per act; the session starts the job
        elif kind == "give_gold":
            for cid in self.character_ids:
                self.gold[cid] = self.gold.get(cid, 0) + int(h.get("amount", 0))
            self.add_journal("event", f"We each pocketed {int(h.get('amount', 0))} gold.")
        elif kind == "give_item":
            self.flags[f"item_{h.get('item')}"] = True  # Phase 2 lands the item itself
        elif kind == "rest":
            if self.mode == "interlude":
                # Between scenarios the inn opens the REST SCREEN (§D24-5.3);
                # nothing heals until a hook is chosen.
                self.rest_screen = True
            else:
                self.rest()
        elif kind == "open_shop":
            self.flags["_shop_open"] = True    # Phase 2: the shop modal (stub now)
        elif kind == "direct_to":
            self.quest["direct_to"] = {"npc": h.get("npc"), "location": h.get("location")}
            npc = sc.find_npc(self.town, h.get("npc") or "")
            loc = sc.find_location(self.town, h.get("location") or "") or (npc[0] if npc else None)
            who = (npc[1]["name"] if npc else "") + (f" at {loc['name']}" if loc else "")
            if who.strip():
                self.add_journal("event", f"We were told to seek {who.strip()}.")

    def rest(self) -> None:
        """The inn: full restore (HP; the adventure resets the rest)."""
        for cid in self.character_ids:
            self.hp[cid] = None

    # -- the journal ------------------------------------------------------- #
    def add_journal(self, kind: str, text: str, speaker: str = "", where: str = "") -> None:
        text = (text or "").strip()
        if not text:
            return
        entry = {"act": self.act_index + 1, "scenario": self.scenario_number,
                 "kind": kind, "text": text, "speaker": speaker, "where": where}
        if self.journal and self.journal[-1] == entry:
            return
        self.journal.append(entry)

    def _note_meeting(self, loc: Dict[str, Any], npc: Dict[str, Any]) -> None:
        """First conversation with an NPC: their card (the persona the player
        saw when they clicked the portrait) goes into the journal. Playtest:
        the card vanishes once the dialogue opens, and the dialogue leans on
        its facts — the splinted arm, the eleven diggers — so a player who
        skimmed it is lost with no way back. The journal is the way back."""
        flag = f"_met_{npc['id']}"
        if self.flags.get(flag):
            return
        self.flags[flag] = True
        log = self._act_log()
        if npc["id"] not in log["met"]:
            log["met"].append(npc["id"])
        state = self.current_town_state()
        if npc["id"] not in state.setdefault("met", []) and not npc.get("_scenario"):
            state["met"].append(npc["id"])
        for cid in self.character_ids:
            self.chronicle_add(cid, "met", f"Met {npc['name']}"
                               + (f", {npc.get('role')}" if npc.get("role") else "")
                               + f", at {loc['name']}.")
        persona = str(npc.get("persona") or "").strip()
        if not persona:
            return
        self.add_journal("met", f"{npc['name']} — {npc.get('role', '')}".rstrip(" —")
                         + f". {persona}", speaker=npc["name"], where=loc["name"])

    def _note_quest_offers(self) -> None:
        """The party is LOOKING at an offer: journal each quest option the
        current node's visible choices would accept, once per option (playtest:
        an offer heard in dialogue and nowhere else is an offer forgotten —
        'Available quest' entries make the choice reviewable before and after)."""
        conv = self.conversation
        if conv is None or conv.node is None:
            return
        found = sc.find_npc(self.town, conv.npc_id)
        loc_name, npc_name = (found[0]["name"], found[1]["name"]) if found else ("", "")
        for ch in conv.node.get("choices", []):
            if not all(self.flags.get(f) for f in ch.get("requires", [])):
                continue
            for h in ch.get("effects", []):
                if h.get("kind") != "grant_quest":
                    continue
                option = self.quest_option(h.get("quest"))
                if option is None or self.flags.get(f"_offered_{option['id']}"):
                    continue
                self.flags[f"_offered_{option['id']}"] = True
                if self.quest.get("status") == "none":
                    self.quest["status"] = "offered"
                text = str(option["text"]).strip()
                # We-voice quest text names its asker itself; append the
                # provenance only when it doesn't, so the entry never reads
                # "…has asked us… (offered by the same man, again)".
                offered_by = (f" (offered by {npc_name} at {loc_name})"
                              if npc_name and npc_name not in text else "")
                self.add_journal(
                    "quest_offered",
                    f'Available quest — "{option["title"]}": {text}' + offered_by)

    def _note_npc_line(self) -> None:
        """Record what the NPC just said (the node the party is looking at)."""
        conv = self.conversation
        if conv is None or conv.node is None:
            return
        found = sc.find_npc(self.town, conv.npc_id)
        if found is None:
            return
        loc, npc = found
        if conv.node.get("speaker") == "npc":
            self.add_journal("heard", conv.node["text"], speaker=npc["name"], where=loc["name"])

    # -- the adventure (§D17-6.3 / §D17-6.4) -------------------------------- #
    def adventure_context(self) -> Dict[str, Any]:
        outline = dict(self.outline)
        # The accepted option may name its own approach ("by boat, after dark")
        # or its own place; it wins over the arc outline's theme.
        if self.quest.get("adventure_theme"):
            outline["adventure_theme"] = self.quest["adventure_theme"]
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

    # -- the level-up schedule (§D17-2.3) ----------------------------------- #
    def is_last_act(self) -> bool:
        return self.act_index >= len(self.arc["acts"]) - 1

    def act_ends_on_screen(self) -> bool:
        """Does this act's boss get a level-up screen behind the spoils? Every
        boundary offers one (§D17-2.3) — the closing act included, now that
        every scenario game is a campaign that may continue (§D24-4): the
        points always have somewhere to go."""
        return True

    def phase_budget_levels(self) -> List[float]:
        """The level each phase of THIS act is budgeted at (T-62, §D17-2.3):
        the party's potential — earned points plus the grants the phases
        before it will have paid (+10, +20) — as a continuous level, plus the
        worn-gear bonus (T-81). Reads what the party COULD be at each phase,
        so a bank of unspent points never makes the fights easier."""
        gear = [items.effective_level_bonus(lo) for lo in self.loadouts]
        out: List[float] = []
        paid = 0
        for i in range(content.PHASE_COUNT):
            lv = [level_progress(self.earned.get(cid, 0) + paid) + g
                  for cid, g in zip(self.character_ids, gear)]
            out.append(max(1.0, sum(lv) / max(1, len(lv))))
            paid += PHASE_GRANTS[i] if i < len(PHASE_GRANTS) else PHASE_GRANTS[-1]
        return out

    def adopt_adventure(self, run: AdventureRun) -> None:
        """Attach a (fresh or restored) AdventureRun and stamp onto it whether
        this act ends on a level-up screen."""
        run.final_screen = self.act_ends_on_screen()
        self.adventure = run
        if self.act_wrapup == "levelup" and run.complete:
            run.open_final_gate()   # a reload inside the act-end screen

    def start_adventure(self, seed: Optional[int] = None) -> "tuple":
        """Compose Phase I from the run's party copies (levels/points/HP carried).
        Returns the AdventureRun's start tuple; the session swaps modes."""
        if not self.adventure_ready or self.adventure_detail is None:
            raise ValueError("the adventure is not ready")
        self._sync_levels_into_loadouts()
        run = AdventureRun(self.adventure_id or "run-adventure", detail=self.adventure_detail)
        run.difficulty = self.options.get("difficulty", "standard")
        state, portraits, art, eid = run.start(self.character_ids, seed=seed,
                                               loadouts=self.loadouts)
        self.add_journal("event", f'We rode out for {self.adventure_detail.get("name", "the road")}.')
        self.advance_days(DAYS_PER_RIDE_OUT)
        self._act_log()["adventure"] = str(self.adventure_detail.get("name") or "")
        # Pools carry across acts (a lone adventure re-derives them; a run knows).
        for cid, live in zip(self.character_ids, run.live_ids):
            run.banked[live] = int(self.banked.get(cid, 0))
            run.earned[live] = int(self.earned.get(cid, 0))
            run.spent[live] = int(self.spent.get(cid, 0))
        # HP carried in from town (None == full).
        for cid, c in zip(self.character_ids, state.party):
            hp = self.hp.get(cid)
            if hp is not None:
                c.hp = min(c.max_hp, max(1, int(hp)))
        self.adopt_adventure(run)
        self.act_wrapup = None
        self.mode = "adventure"
        self.location_id = None
        self.conversation = None
        self.splash = None
        return state, portraits, art, eid

    def _harvest(self, run: AdventureRun, state: Any) -> None:
        """Pull the leveled builds, pools, gold, and HP back out of a finished
        (or lost) adventure into the run's party."""
        party_states = {c.id: c for c in (getattr(state, "party", []) or [])}
        won = getattr(state, "result", None) == "victory" and run.complete
        boss = _boss_name(self.adventure_detail)
        place = (self.adventure_detail or {}).get("name", "the road")
        log = self._act_log()
        levels_before = dict(zip(self.character_ids, self.levels()))
        # HP bought at the act-end level-up heals what it adds (§D10-2), exactly
        # as it would have across a phase boundary — there is no next phase to
        # apply it in, so it lands on the HP the party carries into town.
        heals = {lid: int(e.get("heal", 0)) for lid, e in (run.level_up or {}).items()}
        for cid, live, lo in zip(self.character_ids, run.live_ids, run.loadouts):
            slot = self.slot_of(cid)
            self.loadouts[slot] = copy.deepcopy(lo)
            # Consumables drunk this adventure leave the belt (§D17-4.4).
            cst = party_states.get(live)
            if cst is not None:
                used = [k.consumable_id for k in cst.exile if getattr(k, "consumable_id", None)]
                if used:
                    items.consume_used(self.loadouts[slot], used)
            old_earned = self.earned.get(cid, 0)
            self.earned[cid] = int(run.earned.get(live, old_earned))
            self.banked[cid] = int(run.banked.get(live, self.banked.get(cid, 0)))
            self.spent[cid] = int(run.spent.get(live, self.spent.get(cid, 0)))
            # T-85: gold at the points rate — every point won is a gold piece.
            self.gold[cid] = (self.gold.get(cid, 0)
                              + max(0, self.earned[cid] - old_earned) * GOLD_PER_POINT)
            # The max HP the character now holds (the level-up may have raised it).
            try:
                max_hp = int(self.loadouts[slot]["character"]["hp"])
            except (KeyError, TypeError, ValueError):
                max_hp = int(getattr(cst, "max_hp", 0) or 0)
            live_hp = int(getattr(cst, "hp", max_hp)) + heals.get(live, 0)
            floor = -(-max_hp * HP_FLOOR_PCT // 100)
            self.hp[cid] = min(max_hp, max(live_hp, floor)) if max_hp else None
            # The chronicle (§D24-7.5): who fell, who slew the boss.
            name = self.hero_name(cid)
            fell = cst is not None and int(getattr(cst, "hp", 1)) <= 0
            if fell:
                if name not in log["fallen"]:
                    log["fallen"].append(name)
                self.chronicle_add(cid, "fell", f"Fell at {place}"
                                   + (f" before {boss}" if boss and won else "") + ".")
            if won:
                if boss:
                    log["boss"] = boss
                if not fell:
                    self.chronicle_add(cid, "slew", f"Slew {boss} at {place}." if boss
                                       else f"Cleared {place}.")
        self._sync_levels_into_loadouts()
        for cid, lvl in zip(self.character_ids, self.levels()):
            if lvl > levels_before.get(cid, lvl):
                self.chronicle_add(cid, "levelled", f"Reached level {lvl}.")

    def on_adventure_complete(self, state: Any) -> str:
        """The act's adventure is won: harvest, mark the act complete, and move
        to the next act (or end the scenario). Returns the transition:
        "next_act" | "scenario_complete". The caller then calls `arrive()`
        (or, at the scenario's end, offers the scenario-end menu — §D24-4)."""
        run = self.adventure
        if run is not None:
            self._harvest(run, state)
        n = self.act_index + 1
        self.flags[f"act_{n}_complete"] = True
        self.flags.pop("defeated_once", None)
        self.quest["status"] = "complete"
        self.add_journal("event", f'{(self.adventure_detail or {}).get("name", "The adventure")} is behind us; '
                                  f'"{self.quest.get("title", "")}" is done.')
        self.completed_acts.append({"act": n, "title": self.outline["title"],
                                    "quest": self.quest.get("title", ""),
                                    "adventure": (self.adventure_detail or {}).get("name", "")})
        self.act_summaries.append(
            f'Act {n} "{self.outline["title"]}": the party completed the quest '
            f'"{self.quest.get("title", "")}" — {(self.adventure_detail or {}).get("name", "the adventure")} '
            "was cleared.")
        self.adventure = None
        self.act_wrapup = None
        if n < len(self.arc["acts"]):
            self.act_index = n
            return "next_act"
        self.mode = "complete"
        self._close_scenario_ledger("victory")
        return "scenario_complete"

    def begin_next_scenario(self, arc: Dict[str, Any], town: Optional[Dict[str, Any]] = None,
                            town_id: str = "") -> None:
        """The campaign continues (§D24-5.3): the previous scenario is done; a
        fresh arc — in this town or another. The old arc's cast and places
        leave with it (the recompose on the next arrival drops them)."""
        self._close_scenario_ledger("victory")
        self.previous_arcs.append({"title": self.arc["title"], "villain": self.arc["villain"],
                                   "outcome": "defeated"})
        # The town left keeps what the party did there (§D24-8.2): its custom
        # flags under the campaign's town state; scenario-scoped knowledge and
        # bookkeeping are cleared (§D24-7.7) — the ledger carries them as prose.
        old_state = self.current_town_state()
        for k, v in self.flags.items():
            if (k.startswith("_") or k.startswith("knows_") or k.startswith(DEFERRED_PREFIX)
                    or k.startswith("town:") or k in STANDING_FLAGS):
                continue
            old_state.setdefault("flags", {})[k] = bool(v)
        self.flags = {}
        if town is not None:
            self.base_town = copy.deepcopy(town)
            self.base_town.pop("id", None)
            self.town_id = town_id or town.get("id", "") or self.town_id
        visited = self.campaign.setdefault("towns_visited", [])
        if self.town_id not in visited:
            visited.append(self.town_id)
        self.campaign["current_town_id"] = self.town_id
        new_state = self.current_town_state()
        for k, v in (new_state.get("flags") or {}).items():
            self.flags[f"town:{k}"] = bool(v)
        for npc_id in new_state.get("met") or []:
            self.flags[f"_met_{npc_id}"] = True
        self.arc = copy.deepcopy(arc)
        self.scenario_number += 1
        self.act_index = 0
        self.act_logs = []
        self.scenario_day_start = self.day
        self.mode = "town"
        self.pending_interlude = None
        self.interlude_ref = None
        self.interlude_job = {"state": "idle", "error": None}
        self.continue_requested = False
        self.rest_screen = False
        self.town = self._compose_town()
        loot.lexicon_of(self.arc, self.town)   # a new arc draws new loot verbiage
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
        self.act_wrapup = None
        self.defeat_pending = False
        if self.options.get("hardcore"):
            self.dead = True
            self.mode = "complete"
            return "dead"
        self.flags["defeated_once"] = True
        self._act_log()["defeats"] = int(self._act_log().get("defeats", 0)) + 1
        self.add_journal("event", f'We were beaten at {(self.adventure_detail or {}).get("name", "the road")} '
                                  "and forced to flee back to town.")
        return "town"

    # -- the interlude (Update 24 §D24-5) ---------------------------------- #
    def note_boss_death(self, state: Any) -> None:
        """The closing act's boss just fell (before the spoils and the
        level-up screen): note the boss and who lies fallen on the act log so
        the planner, queued this instant, reads a true ledger (§D24-5.1)."""
        log = self._act_log()
        boss = _boss_name(self.adventure_detail)
        if boss:
            log["boss"] = boss
        if not log.get("adventure"):
            log["adventure"] = str((self.adventure_detail or {}).get("name") or "")
        run = self.adventure
        live_ids = list(run.live_ids) if run is not None else []
        for cid, live in zip(self.character_ids, live_ids):
            cst = next((c for c in (getattr(state, "party", []) or []) if c.id == live), None)
            if cst is not None and int(getattr(cst, "hp", 1)) <= 0:
                name = self.hero_name(cid)
                if name not in log["fallen"]:
                    log["fallen"].append(name)

    def dismiss_notices(self) -> None:
        self.notices = []

    def interlude_town(self) -> Dict[str, Any]:
        """The town the interlude plays in: the closing act's composition (the
        arc's cast is still about) with the campaign's town state applied."""
        return self._compose_town(len(self.arc["acts"]) - 1)

    def generate_interlude(self) -> Dict[str, Any]:
        """The ONE planner call (§D24-5.1), started at boss death (blocking;
        the job runs it off-thread). Reads the ledger, the party, this town as
        the campaign knows it, and the worldbook (this town + neighbours).
        Stores and returns `{interlude, hooks}`."""
        if not self.act_logs or not self.act_logs[-1].get("boss"):
            pass  # the provisional entry still names the villain
        ledger = self.ledger_for_writers()
        if not ledger or int(ledger[-1].get("scenario", 0)) != self.scenario_number:
            ledger.append(self._ledger_entry("victory"))
        else:
            ledger[-1] = self._ledger_entry("victory")
        result = self.interlude_generator(self.interlude_town(), self.arc, ledger,
                                          self.party_state(), self.world_context())
        self.pending_interlude = copy.deepcopy(result)
        self.interlude_job = {"state": "ready", "error": None}
        return result

    def begin_interlude(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Continue Campaign (§D24-5.2): the party arrives in the post-victory
        town with the interlude as the act — dialogue for the cast in the
        light of what happened, shops open, the hooks foreshadowed as topics.
        Rest is the only exit."""
        result = result or self.pending_interlude
        if not result:
            raise ValueError("the interlude has not been written yet")
        self.pending_interlude = copy.deepcopy(result)
        m = result["interlude"]
        self.act_index = len(self.arc["acts"]) - 1
        self._apply_town_state_delta(m.get("town_state_delta"))
        self.advance_days(int(m.get("days", 0) or 0))
        self.campaign["hooks"] = {"hooks": copy.deepcopy(result.get("hooks") or []),
                                  "chosen": None, "note": "", "custom": None}
        self.rewards = None
        self.act_wrapup = None
        self.adventure = None
        self.arrive(m, interlude=True)
        self.materializing = False
        self.act = copy.deepcopy(m)

    def open_rest_screen(self) -> None:
        if self.mode != "interlude":
            raise ValueError("the rest screen belongs to the interlude")
        self.rest_screen = True

    def rest_back(self) -> None:
        """Not yet — back to town; nothing was committed."""
        self.rest_screen = False

    def hooks(self) -> List[Dict[str, Any]]:
        return list((self.campaign.get("hooks") or {}).get("hooks") or [])

    def chosen_hook(self) -> Optional[Dict[str, Any]]:
        """The hook the party chose (proposed or custom), or None."""
        h = self.campaign.get("hooks") or {}
        idx = h.get("chosen")
        if idx is None:
            return None
        if idx < len(h.get("hooks") or []):
            return copy.deepcopy(h["hooks"][idx])
        return copy.deepcopy(h.get("custom"))

    def choose_hook(self, index: int, note: str = "",
                    custom: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """The rest screen's choice (§D24-5.3): one of the three narrated hooks,
        or the fourth card — the player's own stay / travel / somewhere-new
        with a note. Applies the days, heals (the time skip), journals the
        bridge, and records the choice; the app then generates the road
        ahead. Returns the chosen hook."""
        if self.mode != "interlude":
            raise ValueError("there is no road to choose outside the interlude")
        proposed = self.hooks()
        if 0 <= index < len(proposed):
            hook = copy.deepcopy(proposed[index])
            custom_row = None
        elif index == len(proposed) and custom:
            hook = self._custom_hook(custom, note)
            custom_row = hook
        else:
            raise ValueError("no such hook")
        hook["note"] = (note or "").strip()
        self.campaign["hooks"] = {"hooks": proposed, "chosen": index, "note": hook["note"],
                                  "custom": custom_row}
        self.rest()                                  # the interlude rest heals fully
        self.advance_days(int(hook.get("days", 0) or 0))
        bridge = str(hook.get("bridge") or hook.get("narration") or "").strip()
        if bridge:
            self.add_journal("event", bridge)
        self.rest_screen = False
        self.conversation = None
        self.location_id = None
        self.materializing = True
        dest = self._hook_destination_name(hook)
        self.transit = {"title": dest, "narration": str(hook.get("narration") or ""),
                        "kind": hook.get("kind", "stay")}
        self.splash = {"kind": "town", "title": dest,
                       "subtitle": f"Scenario {self.scenario_number + 1} — the road · day {self.day}",
                       "text": str(hook.get("narration") or bridge)}
        return hook

    def _custom_hook(self, custom: Dict[str, Any], note: str) -> Dict[str, Any]:
        kind = str(custom.get("kind") or "stay")
        if kind not in HOOK_KINDS:
            raise ValueError("the fourth card is stay, travel, or somewhere new")
        town_id = str(custom.get("town_id") or "")
        seed = None
        if kind == "neighbour":
            if not town_id or town_id == self.town_id:
                raise ValueError("choose a town to travel to")
            if world.entry_for(town_id) is None and sc.town_detail(town_id) is None:
                raise ValueError(f"unknown town: {town_id}")
        elif kind == "new":
            name = str(custom.get("name") or "").strip()
            if not name:
                raise ValueError("name the new town")
            seed = {"name": name, "line": str(custom.get("line") or "").strip(),
                    "anchor_town_id": self.town_id}
            town_id = ""
        else:
            town_id = self.town_id
        here = self.town.get("name", self.town_id)
        if kind == "stay":
            narration = f"You decide to stay in {here}"
        elif kind == "neighbour":
            dest = (world.entry_for(town_id) or sc.town_detail(town_id) or {}).get("name", town_id)
            narration = f"You decide to travel to {dest}"
        else:
            narration = f"You decide to travel somewhere new — {seed['name']}"
        narration += f", but… {note.strip()}" if note.strip() else "."
        return {"id": "custom", "kind": kind, "town_id": town_id or None, "town_seed": seed,
                "narration": narration, "bridge": narration, "days": CUSTOM_HOOK_DAYS,
                "foreshadow": [], "custom": True}

    def _hook_destination_name(self, hook: Dict[str, Any]) -> str:
        kind = hook.get("kind")
        if kind == "neighbour" and hook.get("town_id"):
            return (world.entry_for(hook["town_id"]) or sc.town_detail(hook["town_id"]) or {}
                    ).get("name", hook["town_id"])
        if kind == "new" and hook.get("town_seed"):
            return str(hook["town_seed"].get("name") or "somewhere new")
        return self.town.get("name", self.town_id)

    def interlude_view(self) -> Optional[Dict[str, Any]]:
        """The client's interlude block: the rest screen's hooks (narration
        only — the bridge is the writers'), the day, each hero's situation."""
        if self.mode != "interlude":
            return None
        h = self.campaign.get("hooks") or {}
        rows = []
        for i, hook in enumerate(h.get("hooks") or []):
            rows.append({"index": i, "id": hook.get("id", f"hook_{i}"), "kind": hook.get("kind", "stay"),
                         "town_id": hook.get("town_id"),
                         "town_name": self._hook_destination_name(hook),
                         "narration": hook.get("narration", ""), "days": int(hook.get("days", 0) or 0)})
        return {"rest_screen": self.rest_screen, "hooks": rows, "day": self.day,
                "chosen": h.get("chosen"), "transit": copy.deepcopy(self.transit),
                "town_name": self.town.get("name", self.town_id), "town_id": self.town_id,
                "situations": {cid: self.situation_of(cid) for cid in self.character_ids}}

    # -- rewards (§D17-4.5) ------------------------------------------------- #
    def open_rewards(self, seed: Optional[int] = None) -> None:
        """Open the Rewards modal on the spoils this act froze when the party
        arrived in town — forged from the scenario's lexicon, never picked off
        the merchants' shelf (§D17-4.5), and painted ahead of time by the
        spoils art queue. An act with none frozen (a save from before the act
        carried them) forges its own here."""
        frozen = (self.act or {}).get("spoils")
        if frozen:
            drops = copy.deepcopy(frozen)
        else:
            drops = [it.model_dump(mode="json", exclude_none=True)
                     for it in loot.forge_drops(len(self.character_ids), self.spoils_tier(),
                                                loot.lexicon_of(self.arc, self.town), seed=seed)]
        self.rewards = {
            "items": drops,
            "assign": {},           # index (str) -> character id | "discard"
            "accepted": False,
        }

    # -- spoils art (painted ahead of the boss, §D17-4.5) -------------------- #
    def spoils(self) -> List[Dict[str, Any]]:
        return list((self.act or {}).get("spoils") or [])

    def set_spoil_art(self, item_id: str, url: str) -> None:
        """A drop's picture landed: onto the frozen act (so the next save keeps
        it) and onto an open Rewards modal (so the card fills in live)."""
        for row in self.spoils():
            if row.get("id") == item_id:
                row["art_url"] = url
        for row in (self.rewards or {}).get("items", []):
            if row.get("id") == item_id:
                row["art_url"] = url

    def set_cast_art(self, kind: str, entry_id: str, url: str) -> None:
        """A cast portrait / arc-place backdrop landed (§D20-2): onto the ARC —
        the run's saves re-put the arc, so it persists — then recompose the town
        so the merged copies show it. ``kind``: cast / place_interior /
        place_exterior."""
        if kind == "cast":
            for npc in self.arc.get("cast") or []:
                if npc.get("id") == entry_id:
                    npc["art_url"] = url
        else:
            field = "interior_art_url" if kind == "place_interior" else "exterior_art_url"
            for pl in self.arc.get("places") or []:
                if pl.get("id") == entry_id:
                    pl[field] = url
        self.town = self._compose_town()

    def assign_reward(self, index: int, target: Optional[str]) -> None:
        if self.rewards is None:
            raise ValueError("no rewards to assign")
        if not 0 <= index < len(self.rewards["items"]):
            raise ValueError("no such reward")
        if target not in (None, "discard") and target not in self.character_ids:
            raise ValueError("unknown character")
        if target and target != "discard":
            # "full" — the dropdown disallows a character whose slots would overflow,
            # counting the other rewards already headed their way.
            lo = copy.deepcopy(self.loadouts[self.slot_of(target)])
            for i_str, who in self.rewards["assign"].items():
                if who == target and int(i_str) != index:
                    try:
                        items.add_item(lo, self.rewards["items"][int(i_str)])
                    except ValueError:
                        pass
            if not items.has_room(lo, self.rewards["items"][index]):
                raise ValueError(f"{lo['character'].get('name', target)} is full")
        if target is None:
            self.rewards["assign"].pop(str(index), None)
        else:
            self.rewards["assign"][str(index)] = target

    def rewards_all_assigned(self) -> bool:
        return (self.rewards is not None
                and all(str(i) in self.rewards["assign"] for i in range(len(self.rewards["items"]))))

    def rewards_room(self) -> Dict[str, Dict[str, bool]]:
        """index -> {character id -> can take it (given the current plan)}."""
        out: Dict[str, Dict[str, bool]] = {}
        if self.rewards is None:
            return out
        for i, item in enumerate(self.rewards["items"]):
            row: Dict[str, bool] = {}
            for cid in self.character_ids:
                lo = copy.deepcopy(self.loadouts[self.slot_of(cid)])
                for j_str, who in self.rewards["assign"].items():
                    if who == cid and int(j_str) != i:
                        try:
                            items.add_item(lo, self.rewards["items"][int(j_str)])
                        except ValueError:
                            pass
                row[cid] = items.has_room(lo, item)
            out[str(i)] = row
        return out

    def accept_rewards(self) -> None:
        """Land the assigned items (discards vanish); the modal closes."""
        if self.rewards is None:
            raise ValueError("no rewards")
        if not self.rewards_all_assigned():
            raise ValueError("assign every reward first (or discard it)")
        for i_str, who in sorted(self.rewards["assign"].items(), key=lambda kv: int(kv[0])):
            if who == "discard":
                continue
            lo = self.loadouts[self.slot_of(who)]
            try:
                items.add_item(lo, self.rewards["items"][int(i_str)])
            except ValueError:
                pass  # overflow at the last moment: the item is lost, not the run
        self.rewards = None

    # -- shops, selling, trading (§D17-5.3 / §D17-5.5) ----------------------- #
    def shop_view(self, location_id: str) -> Dict[str, Any]:
        loc = sc.find_location(self.town, location_id)
        if loc is None:
            raise ValueError("no such location")
        stock = (self.act or {}).get("stock", {}).get(location_id, [])
        rows = []
        for it in stock:
            try:
                item = items.Item.model_validate(it)
            except Exception:
                continue
            rows.append({**it, "buy_price": items.buy_price(item), "summary": items.summarize(item),
                         "description": items.describe(item)})
        return {"location_id": location_id, "name": loc["name"], "function": loc.get("function", ""),
                "stock": rows, "sell_mult": items.SELL_MULT, "buy_mult": items.BUY_MULT}

    def buy(self, location_id: str, item_id: str, character_id: str) -> None:
        if self.location_id != location_id:
            raise ValueError("you are not at that shop")
        stock = (self.act or {}).get("stock", {}).get(location_id, [])
        raw = next((it for it in stock if it.get("id") == item_id), None)
        if raw is None:
            raise ValueError("that item is no longer in stock")
        item = items.Item.model_validate(raw)
        price = items.buy_price(item)
        if character_id not in self.character_ids:
            raise ValueError("unknown character")
        if self.gold.get(character_id, 0) < price:
            raise ValueError(f"not enough gold ({price} needed)")
        lo = self.loadouts[self.slot_of(character_id)]
        items.add_item(lo, raw)     # raises when full
        self.gold[character_id] -= price
        stock.remove(raw)
        log = self._act_log()
        log["gold_spent"][location_id] = int(log["gold_spent"].get(location_id, 0)) + price
        log["items_bought"].append(str(item.name))
        loc = sc.find_location(self.town, location_id) or {}
        self.chronicle_add(character_id, "bought",
                           f"Bought {item.name} for {price} gold at {loc.get('name', location_id)}.")

    def sell(self, character_id: str, item_id: str) -> None:
        if character_id not in self.character_ids:
            raise ValueError("unknown character")
        lo = self.loadouts[self.slot_of(character_id)]
        found = items.find_item(lo, item_id)
        if found is None:
            raise ValueError("no such item")
        item = items.Item.model_validate(found[1])
        items.remove_item(lo, item_id)
        self.gold[character_id] = self.gold.get(character_id, 0) + items.sell_price(item)

    def discard(self, character_id: str, item_id: str) -> None:
        lo = self.loadouts[self.slot_of(character_id)]
        items.remove_item(lo, item_id)

    def give(self, from_id: str, to_id: str, item_id: Optional[str], gold: int) -> None:
        """Trade between characters (town only): an item and/or gold."""
        if from_id == to_id:
            raise ValueError("choose another character")
        if from_id not in self.character_ids or to_id not in self.character_ids:
            raise ValueError("unknown character")
        src = self.loadouts[self.slot_of(from_id)]
        dst = self.loadouts[self.slot_of(to_id)]
        gold = max(0, int(gold or 0))
        if gold > self.gold.get(from_id, 0):
            raise ValueError("not enough gold")
        if item_id:
            found = items.find_item(src, item_id)
            if found is None:
                raise ValueError("no such item")
            if not items.has_room(dst, found[1]):
                raise ValueError("they have no room for it")
            it = items.remove_item(src, item_id)
            items.add_item(dst, it)
        if gold:
            self.gold[from_id] -= gold
            self.gold[to_id] = self.gold.get(to_id, 0) + gold

    # -- quest log (§D17-5.6) ---------------------------------------------- #
    def quest_log(self) -> Dict[str, Any]:
        direct = self.quest.get("direct_to")
        pointer = None
        if direct:
            npc = sc.find_npc(self.town, direct.get("npc") or "")
            loc = sc.find_location(self.town, direct.get("location") or "") or (npc[0] if npc else None)
            pointer = {"npc": npc[1]["name"] if npc else None,
                       "location": loc["name"] if loc else None}
        # The quest's text is shown only once the party has AGREED to it — until
        # then, the journal holds only what the townsfolk have said.
        q = dict(self.quest)
        if q.get("status") in ("none", "offered"):
            q["text"] = ""
            q["title"] = ""
        return {
            "arc_title": self.arc["title"],
            "act_number": self.act_index + 1, "acts_total": len(self.arc["acts"]),
            "act_title": "Between scenarios" if self.mode == "interlude" else self.outline["title"],
            "quest": q, "direct_to": pointer,
            "completed": list(self.completed_acts),
            "scenario_number": self.scenario_number,
            "day": self.day,
            "journal": [dict(e) for e in self.journal],
        }

    # -- snapshots (the town screen) ---------------------------------------- #
    def party_block(self, loadouts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """The party sheet rows. ``loadouts`` overrides the run's copies (in
        adventure mode the live gear is on the AdventureRun's copies)."""
        out = []
        loadouts = loadouts if loadouts is not None else self.loadouts
        for cid, lo, lvl in zip(self.character_ids, loadouts, self.levels()):
            ch = lo.get("character", {}) or {}
            earned = self.earned.get(cid, 0)
            spent = self.spent.get(cid, 0)
            out.append({
                "id": cid, "name": ch.get("name", cid), "portrait": ch.get("portrait", ""),
                "level": lvl, "earned_points": earned, "spent_points": spent,
                # The level follows the points SPENT (§D17-2.3); the band the
                # progress bar fills (T-78) is what this level cost to reach
                # and what the next one costs (None at max level).
                "points_to_next_level": points_to_next_level(spent),
                "level_floor": level_band(spent)[0],
                "level_ceiling": level_band(spent)[1],
                "banked": self.banked.get(cid, 0), "gold": self.gold.get(cid, 0),
                "hp": self.hp.get(cid), "max_hp": ch.get("hp"),
                "build": {"hp": ch.get("hp"), "starting_mana": list(ch.get("starting_mana", [])),
                          "starting_cards": ch.get("starting_cards"),
                          "power_bought": ch.get("power_bought", 0),
                          "keyword": ch.get("keyword"), "attack_mode": ch.get("attack_mode", "melee"),
                          "colors": list(ch.get("colors", [])), "description": ch.get("description", "")},
                "gear": self._gear_view(lo),
                "worn_points": items.worn_points(lo),
                "effective_level": lvl + items.effective_level_bonus(lo),
                # Update 24: the character layers the player owns — the brief,
                # this campaign's situation, and the full chronicle (the Deeds tab).
                "brief": copy.deepcopy(ch.get("brief")) if isinstance(ch.get("brief"), dict) else None,
                "situation": self.situation_of(cid),
                "chronicle": self.chronicle_of(cid),
            })
        return out

    @staticmethod
    def _gear_view(lo: Dict[str, Any]) -> Dict[str, Any]:
        g = items.gear_of(copy.deepcopy(lo))

        def view(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not raw:
                return None
            try:
                it = items.Item.model_validate(raw)
            except Exception:
                return raw
            return {**raw, "summary": items.summarize(it), "description": items.describe(it),
                    "sell_price": items.sell_price(it)}
        return {"primary": view(g["primary"]), "secondary": view(g["secondary"]),
                "accessory": view(g["accessory"]),
                "belt": [view(x) for x in g["belt"]],
                "inventory": {"gear": [view(x) for x in g["inventory"]["gear"]],
                              "consumables": [view(x) for x in g["inventory"]["consumables"]]}}

    def town_snapshot(self) -> Dict[str, Any]:
        """The town screen's state. Note what is NOT here: which location holds
        the questgiver, which NPC has an authored tree. The town wears no
        labels (§D17-5.2) — where the quest is, is something the party learns by
        walking in and asking, and the journal remembers where they were sent."""
        loc = sc.find_location(self.town, self.location_id) if self.location_id else None
        outline = self.outline
        return {
            "town": {
                "id": self.town_id, "name": self.town["name"],
                "region_flavor": self.town.get("region_flavor", ""),
                "scene": self.town.get("scene", ""), "art_url": self.town.get("art_url", ""),
                "locations": [
                    {"id": l["id"], "name": l["name"], "function": l.get("function", ""),
                     "description": l.get("description", ""),
                     # The map card shows the EXTERIOR (frontage); the interior
                     # backdrop rides along for the inspect view.
                     "art_url": l.get("exterior_art_url") or "",
                     "interior_art_url": l.get("interior_art_url") or l.get("art_url", ""),
                     "scene": l.get("exterior_scene") or l.get("interior_scene") or l.get("scene", ""),
                     "npc_count": len(l["npcs"])}
                    for l in self.town["locations"]
                ],
            },
            "location": None if loc is None else {
                "id": loc["id"], "name": loc["name"], "function": loc.get("function", ""),
                # Inside: the INTERIOR is the backdrop.
                "scene": loc.get("interior_scene") or loc.get("scene", ""),
                "art_url": loc.get("interior_art_url") or loc.get("art_url", ""),
                "exterior_art_url": loc.get("exterior_art_url", ""),
                "description": loc.get("description", ""),
                "npcs": [
                    {"id": n["id"], "name": n["name"], "role": n.get("role", ""),
                     "persona": n.get("persona", ""), "art_url": n.get("art_url", ""),
                     # One counter per shop: the other residents only talk.
                     "merchant": (sc.vendor_of(loc) or {}).get("id") == n["id"],
                     "flavor": (self.act or {}).get("flavor", {}).get(n["id"], "")}
                    for n in loc["npcs"]
                ],
            },
            "conversation": (self.conversation.snapshot(self.flags)
                             if self.conversation is not None else None),
            "splash": copy.deepcopy(self.splash),
            "defeat_pending": self.defeat_pending,
            "materializing": self.materializing,
            "materialize_error": self.materialize_error,
            "quest_log": self.quest_log(),
            "scenario": {
                "title": self.arc["title"], "villain": self.arc["villain"],
                "act_number": self.act_index + 1, "acts_total": len(self.arc["acts"]),
                "act_title": ("Between scenarios" if self.mode == "interlude" else outline["title"]),
                "scenario_number": self.scenario_number,
                "options": dict(self.options), "mode": self.mode, "dead": self.dead,
                "scenario_id": self.scenario_id,
                # Update 24: the campaign's clock and the interlude's readiness
                # (the scenario-end menu shows a spinner until the planner is done).
                "day": self.day,
                "interlude_ready": self.interlude_job.get("state") == "ready"
                                   or self.pending_interlude is not None,
                "interlude_state": self.interlude_job.get("state", "idle"),
                "interlude_error": self.interlude_job.get("error"),
            },
            "interlude": self.interlude_view(),
            "notices": list(self.notices),
            "adventure_job": dict(self.adventure_job),
            "adventure_unlocked": self.adventure_unlocked,
            "adventure_ready": self.adventure_ready,
            "adventure_name": (self.adventure_detail or {}).get("name", ""),
            "party": self.party_block(),
            "flags": dict(self.flags),
            "shop": (self.shop_view(self.location_id)
                     if self.location_id and (loc or {}).get("function") in ("weaponsmith", "artificer", "apothecary")
                     else None),
            "trade": copy.deepcopy(self.trade),
        }

    def rewards_view(self) -> Optional[Dict[str, Any]]:
        if self.rewards is None:
            return None
        rows = []
        for it in self.rewards["items"]:
            try:
                item = items.Item.model_validate(it)
                rows.append({**it, "summary": items.summarize(item),
                             "description": items.describe(item)})
            except Exception:
                rows.append(it)
        return {"items": rows, "assign": dict(self.rewards["assign"]),
                "room": self.rewards_room(), "all_assigned": self.rewards_all_assigned(),
                "characters": [{"id": cid, "name": (lo.get("character") or {}).get("name", cid)}
                               for cid, lo in zip(self.character_ids, self.loadouts)]}

    # -- save / restore (§D17-3) -------------------------------------------- #
    def snapshot(self) -> Dict[str, Any]:
        """The JSON-safe scenario block a run save holds (content refs only —
        the town/arc/act/adventure bodies live in the content store)."""
        return {
            "town_id": self.town_id, "scenario_id": self.scenario_id,
            "options": dict(self.options),
            "character_ids": list(self.character_ids),
            "banked": dict(self.banked), "earned": dict(self.earned),
            "spent": dict(self.spent),
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
            "rewards": copy.deepcopy(self.rewards),
            "act_wrapup": self.act_wrapup,
            "journal": copy.deepcopy(self.journal),
            # Update 24: the campaign rides every snapshot (a fork keeps its
            # own history) as well as run.json (the Load list reads it there).
            "campaign": copy.deepcopy(self.campaign),
            "act_logs": copy.deepcopy(self.act_logs),
            "scenario_day_start": self.scenario_day_start,
            "rest_screen": self.rest_screen,
            "interlude_job": dict(self.interlude_job),
        }

    def restore(self, block: Dict[str, Any], act: Optional[Dict[str, Any]],
                adventure_detail: Optional[Dict[str, Any]],
                loadouts: List[Dict[str, Any]]) -> None:
        self.character_ids = list(block.get("character_ids", self.character_ids))
        self.loadouts = copy.deepcopy(loadouts)
        self.options.update(block.get("options") or {})
        self.banked = {k: int(v) for k, v in (block.get("banked") or {}).items()}
        self.earned = {k: int(v) for k, v in (block.get("earned") or {}).items()}
        # A save from before §D17-2.3 recorded no spending: the old scheme spent
        # as it granted, so the earned total is the right credit.
        self.spent = {k: int(v) for k, v in (block.get("spent") or self.earned).items()}
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
        self.rewards = copy.deepcopy(block.get("rewards")) or None
        self.act_wrapup = block.get("act_wrapup")
        self.journal = copy.deepcopy(block.get("journal") or [])
        self.conversation = None
        self.splash = None
        if isinstance(block.get("campaign"), dict):
            fresh = self._fresh_campaign(self.character_ids, self.loadouts, self.town_id)
            self.campaign = {**fresh, **copy.deepcopy(block["campaign"])}
            for cid, row in fresh["heroes"].items():
                self.campaign.setdefault("heroes", {}).setdefault(cid, row)
        self.act_logs = copy.deepcopy(block.get("act_logs") or [])
        self.scenario_day_start = int(block.get("scenario_day_start", 1) or 1)
        self.rest_screen = bool(block.get("rest_screen"))
        self.interlude_job = dict(block.get("interlude_job") or self.interlude_job)
        # The saved act may not be act 0 — recompose the town for it (§D20-2).
        self.town = self._compose_town()
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
            self.base_town = fresh
            self.town = self._compose_town()


# --------------------------------------------------------------------------- #
# Pre-generated scenarios (§D17-6.1): arc + Act I materialized, for a town
# --------------------------------------------------------------------------- #
def _generic_party() -> Dict[str, Any]:
    return {"size": 2, "avg_level": 1.0,
            "members": [{"name": "the first hero", "level": 1, "colors": []},
                        {"name": "the second hero", "level": 1, "colors": []}]}


def pregenerate_scenario(town_id: str, difficulty: str = "standard",
                         note: str = "") -> Dict[str, Any]:
    """Options → Scenarios → Generate: arc for the town + Act I's TOWN portion.
    New Scenario is instant because the town half is ready; the ADVENTURE is
    generated on quest accept, as every act's is (§D20-3) — pre-baking one
    meant the quest options were only real for parties that dodged the baked
    choice. The run's chosen difficulty scales combat at play, so a
    pre-generated scenario carries no difficulty of its own. Persists the
    scenario; returns its meta."""
    difficulty = "standard"
    town = sc.town_detail(town_id)
    if town is None:
        raise ValueError(f"unknown town: {town_id}")
    arc = llm.generate_arc(town, _generic_party(), difficulty, note=note)
    # Draw the scenario's loot verbiage HERE — when the scenario is made — so
    # the spoils of every act are already spoken in its voice (§D17-4.5).
    arc["loot_lexicon"] = loot.build_lexicon(town, arc)
    party_state = {"members": [{"name": "the party", "level": 1}], "flags": {}, "gold": {}}
    act1 = llm.generate_act(town, arc, 0, party_state)
    return sc.save_scenario({
        "town_id": town_id, "arc": arc, "difficulty": difficulty,
        "act1": {"adventure_id": "", "quest_id": "", "materialization": act1},
    })
