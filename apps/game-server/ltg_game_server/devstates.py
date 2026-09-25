"""Jump-to campaign states (roadmap M3.1): fabricate a campaign run at any
point of the loop, in seconds, for nothing.

Seeing the interlude once used to cost nine fights and six generations. This
module builds the run the honest way: it drives the real `ScenarioRun` and
`Session` code through every verb a player would use (accept the quest, ride
out, win or lose each phase, level up, take the spoils, continue), writes the
ordinary saves on the way, and stops at the state asked for. The result is a
normal run in ``saves/``: open it from Load Game (Continue opens the newest
save, which is the target). Everything after the load is ordinary play —
live generation, under whatever the playtest profile and the tape say.

**States** (``STATES``):

- ``act``: arrived in town for Act N (``act``), no quest taken yet.
- ``ready``: Act N with a quest accepted and its adventure ready to ride out.
- ``defeat``: Act N's adventure lost once — back in town, ``defeated_once`` set.
- ``between``: Act III's boss down, spoils taken: the scenario-end menu, with
  the interlude already planned and a ledger entry written.
- ``interlude``: Continue pressed — in the post-victory town, the hooks
  foreshadowed, rest at the inn to choose the road.
- ``scenario2``: the "stay" hook taken — Act I of the campaign's second
  scenario, whose writers read a one-scenario ledger.

**Writers.** ``stub`` (the default) needs no key and spends nothing: the arc,
each act's town portion and the interlude are stand-ins built from the real
town (every NPC answers, the prose says it is a stand-in), and each act's
adventure is taken from the library, never written. With the library empty
(it was purged for regeneration on 2026-09-25), each act rides a stand-in
adventure strung from the bundled `examples/` encounters, its last phase's
strongest enemy made the boss. ``llm`` calls the real
writers instead (the playtest profile and the tape apply, as in play).

**Fights.** ``instant`` marks each phase won (or lost) outright. ``autopilot``
lets the autoplay policy play every fight for real, so the chronicle and the
ledger record who actually fell; a lost fight counts as a defeat and is
retried (up to ``AUTOPILOT_TRIES`` times, then won outright).

Level-ups spend through the autoplay policy's balanced plan, and every spoil
goes to a hero in turn, so the party arrives levelled and geared the way a
player might have left it.

CLI::

    .venv/bin/python -m ltg_game_server.devstates interlude --town karzum
    .venv/bin/python -m ltg_game_server.devstates ready --act 2 --party soren,ys --fights autopilot
"""

from __future__ import annotations

import argparse
import copy
import random
import sys
from typing import Any, Callable, Dict, List, Optional

from ltg_core.schema import level_for_points

from . import autopilot as _autopilot
from . import content, jobs, llm, scenario_content as sc, world
from .runs import RunManager
from .scenario import ScenarioRun, opening_party_state
from .session import Session, SessionManager

STATES = ("act", "ready", "defeat", "between", "interlude", "scenario2")
WRITERS = ("stub", "llm")
FIGHTS = ("instant", "autopilot")
AUTOPILOT_TRIES = 3
_CLIENT = "playtest"
_STANDIN = "(Playtest stand-in: no model wrote this.)"


# --------------------------------------------------------------------------- #
# Stand-in writers — valid content built from the real town, no model call
# --------------------------------------------------------------------------- #
def _npcs(town: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every resident, with the function of the place they stand in."""
    out = []
    for loc in town.get("locations") or []:
        for npc in loc.get("npcs") or []:
            out.append({**npc, "_loc": loc["id"], "_fn": loc.get("function", "")})
    return out


def _innkeeper(town: Dict[str, Any]) -> Optional[str]:
    loc = sc.location_of_function(town, "inn")
    npcs = (loc or {}).get("npcs") or []
    return npcs[0]["id"] if npcs else None


def stub_arc(town: Dict[str, Any], *_a: Any, **_kw: Any) -> Dict[str, Any]:
    """Three act outlines whose questgivers are three different residents
    (never the innkeeper, whose tree holds the room)."""
    inn = _innkeeper(town)
    givers = [n for n in _npcs(town) if n["id"] != inn] or _npcs(town)
    name = town.get("name", "the town")
    acts = []
    for i in range(sc.ACT_COUNT):
        giver = givers[i % len(givers)]
        acts.append({"title": f"Act {i + 1} stand-in",
                     "hook": f"Trouble reaches {name}, and {giver['name']} asks for help. {_STANDIN}",
                     "questgiver_npc": giver["id"], "handoff": None,
                     "adventure_theme": f"the stand-in ride of act {i + 1}",
                     "tone_notes": "stand-in"})
    return sc.validate_arc({"title": f"Playtest: the trouble at {name}",
                            "villain": f"A stand-in villain troubling {name}.",
                            "stakes": f"What {name} stands to lose. {_STANDIN}",
                            "acts": acts}, town)


def _flavor_for(town: Dict[str, Any], skip: set) -> Dict[str, str]:
    return {n["id"]: f"{n['name']} nods to you. {_STANDIN}"
            for n in _npcs(town) if n["id"] not in skip}


def _room_tree() -> Dict[str, Any]:
    return {"root": "r", "nodes": {"r": {"speaker": "npc", "text": f"A room for the night? {_STANDIN}",
                                         "choices": [{"label": "Take a room.", "effects": [{"kind": "rest"}]},
                                                     {"label": "Not yet."}]}}}


def stub_act(town: Dict[str, Any], arc: Dict[str, Any], act_index: int,
             party_state: Dict[str, Any], *_a: Any, **_kw: Any) -> Dict[str, Any]:
    """An act's town portion: two quest options at the outline's questgiver,
    a room at the inn, and a line for everyone else."""
    outline = arc["acts"][act_index]
    n = act_index + 1
    quests = [{"id": f"act{n}_road", "title": f"Act {n}: the road",
               "text": f"Take the road out. {_STANDIN}",
               "adventure_theme": f"act {n}, taken by the road"},
              {"id": f"act{n}_river", "title": f"Act {n}: the river",
               "text": f"Take the river instead. {_STANDIN}",
               "adventure_theme": f"act {n}, taken by the river"}]
    giver = outline["questgiver_npc"]
    tree = {"root": "ask", "nodes": {
        "ask": {"speaker": "npc", "text": f"Will you help us? {_STANDIN}",
                "choices": [
                    {"label": "We'll take the road.", "next": "go",
                     "effects": [{"kind": "grant_quest", "quest": quests[0]["id"]},
                                 {"kind": "unlock_adventure"}]},
                    {"label": "We'll take the river.", "next": "go",
                     "effects": [{"kind": "grant_quest", "quest": quests[1]["id"]},
                                 {"kind": "unlock_adventure"}]},
                    {"label": "Let us get back to you.", "effects": [{"kind": "defer_quest"}]}]},
        "go": {"speaker": "npc", "text": "Go carefully.", "choices": [{"label": "Farewell."}]}}}
    dialogues = {giver: tree}
    inn = _innkeeper(town)
    if inn and inn != giver:
        dialogues[inn] = _room_tree()
    beaten = (party_state.get("flags") or {}).get("defeated_once")
    arrival = (f"You limp back into {town.get('name')}." if beaten
               else f"You arrive in {town.get('name')} for act {n}.") + f" {_STANDIN}"
    raw = {"quests": quests, "arrival": arrival, "dialogues": dialogues,
           "flavor": _flavor_for(town, set(dialogues))}
    return sc.validate_materialization(raw, town, outline)


def stub_interlude(town: Dict[str, Any], arc: Dict[str, Any], ledger: Any,
                   party_state: Dict[str, Any], world_ctx: Optional[Dict[str, Any]] = None,
                   *_a: Any, **_kw: Any) -> Dict[str, Any]:
    """The planner's reply: a room at the inn, and three hooks — stay, a
    worldbook neighbour (or a second new town when there is none), and a new
    town — each foreshadowed by a different resident."""
    ctx = world_ctx or {}
    town_id = str(town.get("id") or (ctx.get("entry") or {}).get("town_id") or "")
    inn = _innkeeper(town)
    heralds = [n["id"] for n in _npcs(town) if n["id"] != inn]
    name = town.get("name", "the town")

    def herald(i: int, reply: str) -> List[Dict[str, str]]:
        if i >= len(heralds):
            return []
        return [{"npc_id": heralds[i], "ask": "Any word from the road?", "reply": f"{reply} {_STANDIN}"}]

    neighbours = [nb["town_id"] for nb in ctx.get("neighbours") or [] if nb.get("town_id")]
    hooks = [{"id": "stay", "kind": "stay", "days": 10,
              "narration": f"You stay in {name} a while. {_STANDIN}",
              "bridge": f"Ten days on, trouble finds {name} again.",
              "foreshadow": herald(0, f"Something stirs near {name}.")}]
    if neighbours:
        hooks.append({"id": "neighbour", "kind": "neighbour", "town_id": neighbours[0], "days": 5,
                      "narration": f"You take the road to {neighbours[0]}. {_STANDIN}",
                      "bridge": f"You arrive in {neighbours[0]} with the dust of the road on you.",
                      "foreshadow": herald(1, f"They need hands in {neighbours[0]}.")})
    seeds = [("Playtest Hollow", "a stand-in hamlet a few days off"),
             ("Playtest Ford", "a stand-in river crossing")]
    for sname, line in seeds[:3 - len(hooks)]:
        hooks.append({"id": sname.lower().replace(" ", "_"), "kind": "new", "days": 6,
                      "town_seed": {"name": sname, "line": line, "anchor_town_id": town_id},
                      "narration": f"You set out for {sname}. {_STANDIN}",
                      "bridge": f"You reach {sname} at dusk.",
                      "foreshadow": herald(len(hooks), f"There is a place called {sname}.")})
    dialogues = {inn: _room_tree()} if inn else {}
    raw = {"interlude": {"arrival": f"You return to {name}, the villain beaten. {_STANDIN}",
                         "days": 3, "dialogues": dialogues,
                         "flavor": _flavor_for(town, set(dialogues))},
           "hooks": hooks}
    known = {e["town_id"] for e in world.list_entries()}
    return sc.validate_interlude(raw, town, town_id, world_towns=known or None)


def _library_adventure(pick: Callable[[], str]) -> Callable[..., Dict[str, Any]]:
    """An adventure 'generator' that writes nothing: it hands back a library
    adventure (the run freezes its own copy, as with a generated one)."""
    def gen(*_a: Any, **_kw: Any) -> Dict[str, Any]:
        aid = pick()
        detail = content.adventure_detail(aid)
        if detail is None:
            raise ValueError(f"the library adventure {aid} is missing")
        return {"id": aid, "name": detail.get("name", aid)}
    return gen


def stand_in_adventure(n: int) -> Dict[str, Any]:
    """An adventure detail built from three of the bundled example
    encounters (rotated by ``n``), for when the library has none. Phase III's
    highest-Level enemy is made the boss (the T-88 dials apply at build).
    Nothing is registered or written; the run freezes this copy."""
    # The registry, not the picker: an install may have hidden the examples.
    ids = sorted(eid for eid, e in content._encounter_registry().items()
                 if e.get("source") == "example")
    details = [d for d in (content.encounter_detail(i) for i in ids) if d and d.get("enemies")]
    if not details:
        raise ValueError("no library adventures and no bundled example encounters to stand in")
    phases = []
    for i in range(content.PHASE_COUNT):
        enc = copy.deepcopy(details[(n * content.PHASE_COUNT + i) % len(details)])
        if i == content.PHASE_COUNT - 1:
            enemies = [e for e in enc["enemies"] if isinstance(e, dict)]
            boss = max(enemies, key=lambda e: (int(e.get("level", 1) or 1), int(e.get("hp", 0) or 0)))
            boss["is_boss"] = True
        phases.append({**enc, "narration": f"Phase {i + 1} of a stand-in ride. {_STANDIN}",
                       "encounter_id": enc.get("id", "")})
    return {"id": f"playtest_ride_{n + 1}", "name": f"Stand-in ride {n + 1}",
            "flavor": _STANDIN, "difficulty": "standard", "phases": phases}


# --------------------------------------------------------------------------- #
# The driver — a single seat plays every verb, synchronously
# --------------------------------------------------------------------------- #
class _Builder:
    def __init__(self, session: Session, fights: str, adventure_gen: Callable[..., Any],
                 interlude_gen: Callable[..., Any], rng: random.Random) -> None:
        self.session = session
        self.sc: ScenarioRun = session.scenario  # type: ignore[assignment]
        self.fights = fights
        self.adventure_gen = adventure_gen
        self.interlude_gen = interlude_gen
        self.rng = rng
        self.defeats = 0
        # Set when the stub writers have no library: builds each act's adventure.
        self.stand_in: Optional[Callable[[], Dict[str, Any]]] = None

    # -- the async hook, run inline -------------------------------------- #
    def hook(self, session: Session, kind: str) -> None:
        if kind == "materialize":
            session.materialize_act()
        elif kind == "adventure_job":
            if self.sc.adventure_detail is not None and self.sc.adventure_job.get("state") == "ready":
                return   # as the app does: a re-accept after a defeat rides the same adventure
            runner = jobs.AdventureJobRunner(self.adventure_gen)
            if self.stand_in is not None:
                # No library to ride: attach a stand-in, as a pre-generated
                # Act I is attached (`prepare_pregenerated`), with no registry entry.
                detail = self.stand_in()
                ref = session.run_manager.put_content(session.run_id, detail)
                self.sc.attach_adventure(detail["id"], detail, ref)
                runner.set_state(self.sc, "ready", adventure_ref=ref, error=None,
                                 progress=[len(detail["phases"])] * 2)
                runner.persist(session)
                return
            runner.set_state(self.sc, "pending", error=None)
            runner.generate_sync(session)
        elif kind == "interlude":
            self.sc.interlude_generator = self.interlude_gen
            self.sc.interlude_job = {"state": "pending", "error": None}
            jobs.InterludeJobRunner().generate_sync(session)
        elif kind == "continue":
            from .app import _continue_sync   # the app's own road-ahead path
            _continue_sync(session)

    def verb(self, verb: str, **payload: Any) -> None:
        self.session.town_verb(_CLIENT, verb, payload)

    def _check(self) -> None:
        if self.sc.materialize_error:
            raise ValueError(f"the act writer failed: {self.sc.materialize_error}")
        if self.sc.adventure_job.get("state") == "failed":
            raise ValueError(f"the adventure job failed: {self.sc.adventure_job.get('error')}")

    # -- town ------------------------------------------------------------- #
    def accept_quest(self) -> None:
        """Walk to the act's questgiver and accept the first offer, stepping
        through whatever tree the writer made (an accept may sit a node deep)."""
        self._check()
        sc_ = self.sc
        outline = sc_.outline
        if sc_.location_id is not None:
            self.verb("leave")
        self.verb("visit", location_id=outline["questgiver_location"])
        self.verb("talk", npc_id=outline["questgiver_npc"])
        for _ in range(16):
            conv = sc_.town_snapshot().get("conversation")
            if conv is None:
                self.verb("talk", npc_id=outline["questgiver_npc"])
                continue
            choices = conv.get("choices") or []
            accept = next((c for c in choices if sc_.choice_quest_title(c["index"])), None)
            if accept is not None:
                self.verb("choose", index=accept["index"])
                break
            onward = next((c for c in choices if not c.get("party_wide")), None)
            if onward is None:
                raise ValueError(f"{outline['questgiver_npc']}'s tree offers no way to the quest")
            self.verb("choose", index=onward["index"])
        else:
            raise ValueError("could not find the quest offer in the questgiver's tree")
        if sc_.conversation is not None:
            self.verb("end_talk")
        if sc_.location_id is not None:
            self.verb("leave")
        self._check()
        if not sc_.adventure_ready:
            raise ValueError("the quest was accepted but no adventure is ready")

    def ride_out(self) -> None:
        self.verb("start_adventure")
        for live in list(self.session.adventure.live_ids):  # type: ignore[union-attr]
            self.session.seats[live] = _CLIENT

    # -- the fight -------------------------------------------------------- #
    def _settle(self, result: str) -> None:
        st = self.session.state
        assert st is not None
        st.result = result
        self.session.adventure.on_state_change(st)  # type: ignore[union-attr]
        self.session._run_hooks()

    def _fight(self, want_defeat: bool) -> None:
        if want_defeat:
            self._settle("defeat")
            return
        if self.fights == "instant":
            self._settle("victory")
            return
        seed = self.rng.randrange(2**31)
        made = 0
        while self.session.state is not None and self.session.state.result is None:
            before = self.session.state
            after, n, stop = _autopilot.play_chunk(before, seed, max_actions=500)
            self.session._autopilot_commit(before, after, n)
            made += n
            if stop is not None or made >= _autopilot.ACTION_CAP:
                self._settle("victory")      # an anomaly: call the phase won
                return

    def _level_up(self) -> None:
        """Every seat confirms the open gate, spending through the autoplay
        policy's balanced plan (a build the gate rejects banks instead)."""
        from ltg_combat.autoplay.policies import GreedyPolicy
        adv = self.session.adventure
        assert adv is not None and adv.level_up is not None
        policy = GreedyPolicy()
        for slot, live in enumerate(list(adv.live_ids)):
            if adv.level_up[live]["confirmed"]:
                continue
            old = copy.deepcopy(adv.loadouts[slot]["character"])
            available = int(adv.banked.get(live, 0))
            ceiling = level_for_points(int(adv.spent.get(live, 0)) + available)
            new, _spent = policy.spend_level_up({**old, "level": ceiling}, available)
            build = {k: new.get(k, old.get(k)) for k in
                     ("hp", "starting_mana", "starting_cards", "power_bought")}
            self.session.seats[live] = _CLIENT
            try:
                self.session.confirm_level_up(_CLIENT, live, build)
            except ValueError:
                self.session.confirm_level_up(_CLIENT, live, {})

    def _take_rewards(self) -> None:
        """Hand each spoil to the next hero in turn (discard what will not fit)."""
        rewards = self.sc.rewards
        assert rewards is not None
        heroes = list(self.sc.character_ids)
        for i in range(len(rewards["items"])):
            try:
                self.session.economy_verb(_CLIENT, "reward_assign",
                                          {"index": i, "target": heroes[i % len(heroes)]})
            except ValueError:
                self.session.economy_verb(_CLIENT, "reward_assign", {"index": i, "target": "discard"})
        try:
            self.session.economy_verb(_CLIENT, "reward_accept", {})
        except ValueError:
            for i in range(len(rewards["items"])):
                self.session.economy_verb(_CLIENT, "reward_assign", {"index": i, "target": "discard"})
            self.session.economy_verb(_CLIENT, "reward_accept", {})

    def play_adventure(self, lose: bool = False) -> str:
        """Drive the ridden-out adventure to its end: "town" (won, or lost and
        fled) or "complete" (the scenario is over)."""
        for _ in range(200):
            s, sc_ = self.session, self.sc
            if s.state is None:
                self._check()
                return "complete" if sc_.mode == "complete" else "town"
            adv = s.adventure
            if sc_.defeat_pending:
                self.defeats += 1
                s.economy_verb(_CLIENT, "flee", {})
            elif s.state.result is None:
                self._fight(want_defeat=lose)
            elif sc_.rewards is not None:
                self._take_rewards()
            elif adv is not None and adv.level_up is not None and not adv.all_confirmed():
                self._level_up()
            else:
                raise ValueError(f"the adventure stalled (result {s.state.result}, "
                                 f"wrap-up {sc_.act_wrapup})")
        raise ValueError("the adventure did not finish")

    def play_act(self) -> str:
        """Accept, ride out, and win the act (an autopilot loss is a real
        defeat: flee, re-accept, ride again)."""
        for _ in range(AUTOPILOT_TRIES):
            self.accept_quest()
            self.ride_out()
            before = self.defeats
            out = self.play_adventure()
            if self.defeats == before:
                return out
        self.fights = "instant"               # the policy keeps losing: win it outright
        self.accept_quest()
        self.ride_out()
        return self.play_adventure()


def _default_party() -> List[str]:
    ids = [c["id"] for c in content.list_characters()]
    if not ids:
        raise ValueError("no characters are installed — import one first")
    return ids[:3]


def build(state: str = "interlude", town_id: Optional[str] = None,
          character_ids: Optional[List[str]] = None, act: int = 1,
          difficulty: str = "standard", hardcore: bool = False,
          writers: str = "stub", fights: str = "instant",
          name: str = "", runs: Optional[RunManager] = None,
          seed: Optional[int] = None) -> Dict[str, Any]:
    """Build a campaign run at ``state`` and return ``{run_id, name, save,
    state, defeats}``. See the module docstring for the states and options."""
    if state not in STATES:
        raise ValueError(f"unknown state {state!r} — one of {', '.join(STATES)}")
    if writers not in WRITERS:
        raise ValueError(f"unknown writers {writers!r} — one of {', '.join(WRITERS)}")
    if fights not in FIGHTS:
        raise ValueError(f"unknown fights {fights!r} — one of {', '.join(FIGHTS)}")
    if not 1 <= int(act) <= sc.ACT_COUNT:
        raise ValueError(f"act must be 1–{sc.ACT_COUNT}")
    act = int(act)
    if state == "defeat" and hardcore:
        raise ValueError("a Hardcore defeat ends the run — build the defeat state on Normal")
    rng = random.Random(seed)
    towns = [t["id"] for t in sc.list_towns()]
    town_id = town_id or (towns[0] if towns else "")
    town = sc.town_detail(town_id)
    if town is None:
        raise ValueError(f"no such town: {town_id!r} (have: {', '.join(towns) or 'none'})")
    character_ids = list(character_ids or _default_party())
    loadouts = content.loadouts_for(character_ids)
    library = [a["id"] for a in content.list_adventures()]
    counter = {"n": 0}

    def pick() -> str:
        aid = library[counter["n"] % len(library)]
        counter["n"] += 1
        return aid

    def next_stand_in() -> Dict[str, Any]:
        counter["n"] += 1
        return stand_in_adventure(counter["n"] - 1)

    if writers == "stub":
        arc = stub_arc(town)
    else:
        arc = llm.generate_arc(town, llm.party_summary_from_loadouts(loadouts), difficulty, None, "",
                               party_state=opening_party_state(character_ids, loadouts),
                               world_ctx=world.context_for(town_id))
    scen = ScenarioRun(town, arc, character_ids, loadouts,
                       {"difficulty": difficulty, "hardcore": bool(hardcore)}, town_id=town_id)
    if writers == "stub":
        scen.materializer = stub_act
        scen.arc_generator = stub_arc
        adventure_gen: Callable[..., Any] = _library_adventure(pick)
        interlude_gen: Callable[..., Any] = stub_interlude
    else:
        adventure_gen = llm.generate_adventure
        interlude_gen = llm.generate_interlude
    runs = runs or RunManager()
    label = f"Playtest · {state}" + (f" (Act {act})" if state in ("act", "ready", "defeat") else "")
    meta = runs.create_scenario_run(scen, name=name or f"{label} — {town.get('name', town_id)}")
    session = SessionManager().create(None, name=meta["name"], run_id=meta["run_id"],
                                      run_manager=runs, scenario=scen)
    session.clients = {_CLIENT: object()}   # one player: confirmations resolve at once
    for cid in character_ids:
        session.seats[cid] = _CLIENT
    b = _Builder(session, fights, adventure_gen, interlude_gen, rng)
    if writers == "stub" and not library:
        b.stand_in = next_stand_in
    session.async_hook = b.hook
    session.scenario_enter_town(None)
    session.materialize_act()
    b._check()

    target_acts = act - 1 if state in ("act", "ready", "defeat") else sc.ACT_COUNT
    for _ in range(target_acts):
        b.play_act()
    if state in ("ready", "defeat"):
        b.accept_quest()
        if state == "defeat":
            b.ride_out()
            b.play_adventure(lose=True)
            b._check()
        else:
            session.save_point("town", None, auto=False)   # the ready adventure, saved
    if state in ("interlude", "scenario2"):
        if not session.continue_campaign():
            raise ValueError(f"the interlude was not written: {scen.interlude_job.get('error')}")
    if state == "scenario2":
        hooks = scen.hooks()
        stay = next(i for i, h in enumerate(hooks) if h["kind"] == "stay")
        b.verb("rest_screen")
        b.verb("choose_hook", index=stay)
        b._check()
        if scen.scenario_number != 2:
            raise ValueError("the second scenario did not begin")
    newest = runs.newest_save(meta["run_id"])
    return {"run_id": meta["run_id"], "name": meta["name"], "state": state,
            "save": newest, "defeats": b.defeats, "town_id": town_id,
            "party": character_ids}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m ltg_game_server.devstates",
        description="Fabricate a campaign run at a chosen state (roadmap M3.1). "
                    "Open it from Load Game; Continue opens the newest save.")
    p.add_argument("state", choices=STATES)
    p.add_argument("--town", default=None, help="town id (default: the first town)")
    p.add_argument("--party", default="", help="comma-separated character ids (default: the first three)")
    p.add_argument("--act", type=int, default=1, help="the act, for act / ready / defeat (1–3)")
    p.add_argument("--difficulty", default="standard", choices=list(llm.DIFFICULTY))
    p.add_argument("--hardcore", action="store_true")
    p.add_argument("--writers", default="stub", choices=WRITERS,
                   help="stub: stand-ins, free (default); llm: the real writers")
    p.add_argument("--fights", default="instant", choices=FIGHTS,
                   help="instant: phases won outright (default); autopilot: the policy plays them")
    p.add_argument("--name", default="")
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args(argv)
    party = [x.strip() for x in a.party.split(",") if x.strip()] or None
    try:
        out = build(a.state, a.town, party, a.act, a.difficulty, a.hardcore,
                    a.writers, a.fights, a.name, seed=a.seed)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    save = out["save"] or {}
    print(f"{out['name']}\n  run {out['run_id']} · newest save: {save.get('label', '?')} "
          f"({save.get('kind', '?')})" + (f" · {out['defeats']} defeat(s)" if out["defeats"] else ""))
    print("  Open it in the game: Load Game → the run → Continue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
