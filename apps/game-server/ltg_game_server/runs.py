"""Runs, saves, and the content store (Design Update 17 §D17-3).

A **run** is a party + immutable options + a branching tree of **saves**.
Saves reference generated content; they never regenerate it: everything a
save points at (the frozen adventure, the party's loadouts) is written ONCE
into the run's **content store**, addressed by the SHA-256 of its canonical
JSON, immutable thereafter. A save snapshot is small — party state and
references — so loading an old save restores the exact adventure it pointed
at, forks share what they don't diverge on, and deleting a save deletes only
its snapshot (content is never garbage-collected in v1).

Layout (runtime data — gitignored, never under ``content/``)::

    saves/<run_id>/
      run.json                     # party, options, dates, schema_version
      content/<content_hash>.json  # immutable: adventures, loadouts, (later) arcs/acts
      content/art/…                # reserved: generated art for runs (Phase 1+)
      saves/<save_id>.json         # small snapshots: state + references into content/

Save points in Phase 0 (an adventure run — towns arrive in Phase 1):
adventure start, each phase boundary (after every level-up confirms, before
the next phase composes), and adventure end. Never mid-combat.

Server-side, `RunManager` owns runs and saves; `Session` calls back into it at
save points, and `load_save` rebuilds an `AdventureRun` + composed engine state
from a snapshot (the app layer wraps that in a fresh `Session`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ltg_combat.state import GameState

from . import content, scenario_content as sc
from .adventure import AdventureRun

if False:  # typing only
    from .scenario import ScenarioRun  # noqa: F401

REPO_ROOT = content.REPO_ROOT
SAVES_DIR = REPO_ROOT / "saves"

RUN_SCHEMA_VERSION = 1
SAVE_SCHEMA_VERSION = 1

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Any) -> str:
    """The content address of a JSON-able object: sha256 of its canonical form."""
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _safe_id(value: str, what: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


class RunStore:
    """One run's directory: run.json, the content store, and the saves."""

    def __init__(self, run_id: str, root: Path = SAVES_DIR) -> None:
        self.run_id = _safe_id(run_id, "run id")
        self.dir = root / self.run_id
        self.content_dir = self.dir / "content"
        self.saves_dir = self.dir / "saves"

    # -- run.json ---------------------------------------------------------- #
    @property
    def run_path(self) -> Path:
        return self.dir / "run.json"

    def exists(self) -> bool:
        return self.run_path.is_file()

    def read_run(self) -> Dict[str, Any]:
        return json.loads(self.run_path.read_text(encoding="utf-8"))

    def write_run(self, run: Dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.run_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.run_path)

    # -- content store ------------------------------------------------------ #
    def put(self, obj: Any) -> str:
        """Write ``obj`` into the content store (no-op if present); return its hash."""
        h = content_hash(obj)
        path = self.content_dir / f"{h}.json"
        if not path.exists():
            self.content_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(_canonical(obj), encoding="utf-8")
            tmp.replace(path)
        return h

    def get(self, h: str) -> Any:
        path = self.content_dir / f"{_safe_id(h, 'content hash')}.json"
        if not path.is_file():
            raise KeyError(f"content {h} missing from run {self.run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- saves --------------------------------------------------------------- #
    def list_saves(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self.saves_dir.is_dir():
            return out
        for path in sorted(self.saves_dir.glob("*.json")):
            try:
                snap = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "save_id": path.stem,
                "saved_at": snap.get("saved_at", ""),
                "label": snap.get("label", ""),
                "kind": snap.get("kind", ""),
                "auto": bool(snap.get("auto", True)),
                "schema_version": snap.get("schema_version"),
            })
        out.sort(key=lambda s: (s["saved_at"], s["save_id"]))  # oldest → newest (§D17-3.1)
        return out

    def read_save(self, save_id: str) -> Dict[str, Any]:
        path = self.saves_dir / f"{_safe_id(save_id, 'save id')}.json"
        if not path.is_file():
            raise KeyError(f"no save {save_id} in run {self.run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def write_save(self, snap: Dict[str, Any]) -> str:
        """Persist a snapshot; the id is the timestamp plus a per-run sequence
        number, so two saves in the same millisecond (a fork replayed fast)
        never collide and always list in write order."""
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        stamp = snap["saved_at"].replace(":", "").replace(".", "").replace("-", "")
        seq = len(list(self.saves_dir.glob("*.json"))) + 1
        save_id = f"{stamp}_{seq:04d}"
        while (self.saves_dir / f"{save_id}.json").exists():
            seq += 1
            save_id = f"{stamp}_{seq:04d}"
        snap["seq"] = seq
        path = self.saves_dir / f"{save_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return save_id

    def delete_save(self, save_id: str) -> None:
        path = self.saves_dir / f"{_safe_id(save_id, 'save id')}.json"
        if not path.is_file():
            raise KeyError(f"no save {save_id} in run {self.run_id}")
        path.unlink()

    def delete(self) -> None:
        if self.dir.is_dir():
            shutil.rmtree(self.dir)


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def progression_label(adventure_name: str, kind: str, phase_index: int,
                      phases_total: int, scenario: Optional["ScenarioRun"] = None) -> str:
    """The save row's human label (§D17-3.1):
    ``Hollowmere · Scenario 1 · Act II · Town — the Inn`` /
    ``… · Act II · Adventure, Phase 3``. A plain adventure run has no town."""
    if scenario is not None:
        head = (f"{scenario.town['name']} · Scenario {scenario.scenario_number} · "
                f"Act {_roman(scenario.act_index + 1)}")
        if kind == "act_start":
            return f"{head} · Town — arrival"
        if kind == "quest_accept":
            return f"{head} · Town — quest accepted"
        if kind == "inn":
            return f"{head} · Town — the Inn"
        if kind == "town":
            loc = sc.find_location(scenario.town, scenario.location_id or "")
            return f"{head} · Town — {loc['name'] if loc else 'the square'}"
        if kind == "adventure_start":
            return f"{head} · Adventure, Phase 1"
        if kind == "adventure_end":
            return f"{head} · Adventure complete"
        nxt = min(phase_index + 2, phases_total)
        return f"{head} · Adventure, Phase {nxt}"
    if kind == "adventure_start":
        return f"{adventure_name} · Adventure start"
    if kind == "adventure_end":
        return f"{adventure_name} · Adventure complete"
    # A boundary save records the phase just won; the next is about to begin.
    nxt = min(phase_index + 2, phases_total)
    return f"{adventure_name} · Adventure, Phase {nxt}"


def _roman(n: int) -> str:
    return {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(n, str(n))


class RunManager:
    """Owns the runs under ``saves/``: create, list, save, load, delete."""

    def __init__(self, root: Path = SAVES_DIR) -> None:
        self.root = root

    # -- listing --------------------------------------------------------------- #
    def store(self, run_id: str) -> RunStore:
        st = RunStore(run_id, self.root)
        if not st.exists():
            raise KeyError(f"no such run: {run_id}")
        return st

    def list_runs(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self.root.is_dir():
            return out
        for d in sorted(self.root.iterdir()):
            st = RunStore(d.name, self.root) if _ID_RE.match(d.name) else None
            if st is None or not st.exists():
                continue
            try:
                run = st.read_run()
            except Exception:
                continue
            saves = st.list_saves()
            out.append({**self._run_meta(run), "save_count": len(saves),
                        "latest_label": saves[-1]["label"] if saves else ""})
        out.sort(key=lambda r: r.get("updated_at", ""), reverse=True)  # newest first
        return out

    @staticmethod
    def _run_meta(run: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "run_id": run["run_id"],
            "name": run.get("name", ""),
            "party": run.get("party", []),
            "options": run.get("options", {}),
            "created_at": run.get("created_at", ""),
            "updated_at": run.get("updated_at", ""),
            "dead": bool(run.get("dead", False)),
            "schema_version": run.get("schema_version"),
        }

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        st = self.store(run_id)
        run = st.read_run()
        return {**self._run_meta(run), "saves": st.list_saves()}

    # -- creation -------------------------------------------------------------- #
    def create_adventure_run(self, adventure: AdventureRun,
                             options: Optional[Dict[str, Any]] = None,
                             name: str = "") -> Dict[str, Any]:
        """Create a run around a just-started `AdventureRun` (its frozen detail
        and party loadouts go into the content store) and write its first
        auto-save (adventure start). Returns the run meta."""
        run_id = _new_run_id()
        st = RunStore(run_id, self.root)
        while st.exists():
            run_id = _new_run_id()
            st = RunStore(run_id, self.root)
        opts = {"difficulty": "standard", "hardcore": False, "everquest": False}
        opts.update({k: v for k, v in (options or {}).items() if k in opts})
        party = []
        for cid, lo in zip(adventure.character_ids, adventure.loadouts):
            ch = lo.get("character", {}) or {}
            party.append({"id": cid, "name": str(ch.get("name") or cid),
                          "portrait": str(ch.get("portrait") or "")})
        now = _now()
        run = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "name": name or adventure.name,
            "party": party,
            "options": opts,
            "created_at": now,
            "updated_at": now,
            "dead": False,
            "scenario": {"kind": "adventure",
                         "adventure_id": adventure.adventure_id,
                         "adventure_ref": st.put(adventure.detail)},
        }
        st.write_run(run)
        return self._run_meta(run)

    def create_scenario_run(self, scenario: "ScenarioRun",
                            name: str = "") -> Dict[str, Any]:
        """Create a run around a fresh `ScenarioRun` (town + arc frozen into the
        content store). The first auto-save is the act-start save the session
        writes on arrival."""
        run_id = _new_run_id()
        st = RunStore(run_id, self.root)
        while st.exists():
            run_id = _new_run_id()
            st = RunStore(run_id, self.root)
        party = []
        for cid, lo in zip(scenario.character_ids, scenario.loadouts):
            ch = lo.get("character", {}) or {}
            party.append({"id": cid, "name": str(ch.get("name") or cid),
                          "portrait": str(ch.get("portrait") or "")})
        now = _now()
        run = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "name": name or f"{scenario.arc['title']} — {scenario.town['name']}",
            "party": party,
            "options": dict(scenario.options),
            "created_at": now,
            "updated_at": now,
            "dead": False,
            "scenario": {"kind": "scenario",
                         "town_id": scenario.town_id,
                         "scenario_id": scenario.scenario_id,
                         "town_ref": st.put(scenario.town),
                         "arc_ref": st.put(scenario.arc),
                         "arc_refs": [st.put(scenario.arc)]},
            "adventure_job": dict(scenario.adventure_job),
        }
        st.write_run(run)
        return self._run_meta(run)

    def put_content(self, run_id: str, obj: Any) -> str:
        return self.store(run_id).put(obj)

    def set_job(self, run_id: str, job: Dict[str, Any]) -> None:
        st = self.store(run_id)
        run = st.read_run()
        run["adventure_job"] = dict(job)
        st.write_run(run)

    def set_arc(self, run_id: str, arc: Dict[str, Any]) -> None:
        """Everquest: a new arc for the same town — recorded on the run."""
        st = self.store(run_id)
        run = st.read_run()
        ref = st.put(arc)
        run.setdefault("scenario", {})["arc_ref"] = ref
        run["scenario"].setdefault("arc_refs", []).append(ref)
        st.write_run(run)

    # -- saving ------------------------------------------------------------------ #
    def save(self, run_id: str, adventure: Optional[AdventureRun], kind: str,
             seed: Optional[int], auto: bool = True,
             scenario: Optional["ScenarioRun"] = None) -> Dict[str, Any]:
        """Write a save snapshot for the run at a save point. ``kind`` is
        adventure_start / phase_boundary / adventure_end (adventures) or
        act_start / quest_accept / inn / town (scenarios); ``seed`` is the seed
        the phase about to be played was (or will be) composed with, so the
        reload composes the identical state. Returns the save row."""
        st = self.store(run_id)
        run = st.read_run()
        snap: Dict[str, Any] = {
            "schema_version": SAVE_SCHEMA_VERSION,
            "run_id": run_id,
            "saved_at": _now(),
            "kind": kind,
            "auto": auto,
            "seed": seed,
        }
        phase_index, phases_total, adv_name = 0, 0, ""
        if adventure is not None:
            adventure_ref = st.put(adventure.detail)  # already present; idempotent
            block = adventure.boundary_snapshot()
            # Loadouts are the bulk of a snapshot (portraits ride inside them):
            # content-address each so identical builds across saves share one file.
            loadout_refs = [st.put(lo) for lo in block.pop("loadouts")]
            phase_index, phases_total = block["phase_index"], len(adventure.phases)
            adv_name = adventure.name
            snap["adventure"] = {"adventure_id": adventure.adventure_id,
                                 "ref": adventure_ref,
                                 "phase_index": phase_index,
                                 "phases_total": phases_total,
                                 "complete": block["complete"]}
            snap["party"] = {**block, "loadout_refs": loadout_refs}
        if scenario is not None:
            block = scenario.snapshot()
            block["loadout_refs"] = [st.put(lo) for lo in scenario.loadouts]
            block["arc_ref"] = st.put(scenario.arc)
            block["town_ref"] = st.put(scenario.town)
            block["act_ref"] = st.put(scenario.act) if scenario.act is not None else None
            block["adventure_ref"] = (st.put(scenario.adventure_detail)
                                      if scenario.adventure_detail is not None else None)
            snap["scenario"] = block
        snap["label"] = progression_label(adv_name, kind, phase_index, phases_total,
                                          scenario=scenario)
        save_id = st.write_save(snap)
        run["updated_at"] = snap["saved_at"]
        if scenario is not None:
            run["adventure_job"] = dict(scenario.adventure_job)
            run.setdefault("scenario", {})["arc_ref"] = snap["scenario"]["arc_ref"]
        st.write_run(run)
        return {"save_id": save_id, "saved_at": snap["saved_at"],
                "label": snap["label"], "kind": kind, "auto": auto}

    def mark_dead(self, run_id: str) -> None:
        """Hardcore defeat: the run ends; its saves stay viewable, not
        continuable (§D17-6.4)."""
        st = self.store(run_id)
        run = st.read_run()
        run["dead"] = True
        run["updated_at"] = _now()
        st.write_run(run)

    # -- loading ------------------------------------------------------------------ #
    def load_save(self, run_id: str, save_id: str
                  ) -> Tuple[Dict[str, Any], Optional[AdventureRun], Optional[GameState],
                             Dict[str, str], Dict[str, Any], str]:
        """Rebuild an `AdventureRun` and its composed phase-start state from a
        save. Returns ``(run_meta, adventure, state, portraits, art,
        encounter_id)`` — the app layer wraps these in a Session bound to the
        run, and every later save point appends to the run (a fork when the
        save was not the newest). For a scenario save see `load_scenario_save`
        (this returns Nones for the adventure parts when the save is a town
        save)."""
        st = self.store(run_id)
        run = st.read_run()
        if run.get("dead"):
            raise ValueError("this run is over (Hardcore) — its saves can be viewed, not continued")
        snap = st.read_save(save_id)
        if int(snap.get("schema_version", 0)) > SAVE_SCHEMA_VERSION:
            raise ValueError(f"save schema {snap.get('schema_version')} is newer than this server")
        adv_block = snap.get("adventure")
        if adv_block is None:
            return self._run_meta(run), None, None, {}, {}, ""
        detail = st.get(adv_block["ref"])
        adventure = AdventureRun(adv_block.get("adventure_id") or "run-adventure",
                                 detail=detail)
        party = copy.deepcopy(snap["party"])
        party["loadouts"] = [st.get(h) for h in party.pop("loadout_refs", [])]
        state, portraits, art, encounter_id = adventure.restore(party, seed=snap.get("seed"))
        return self._run_meta(run), adventure, state, portraits, art, encounter_id

    def is_scenario_save(self, run_id: str, save_id: str) -> bool:
        return "scenario" in self.store(run_id).read_save(save_id)

    def load_scenario_save(self, run_id: str, save_id: str) -> "ScenarioRun":
        """Rebuild the `ScenarioRun` from a scenario save (town or adventure
        mode; the adventure part, if any, is rebuilt with `load_save`)."""
        from .scenario import ScenarioRun
        st = self.store(run_id)
        run = st.read_run()
        if run.get("dead"):
            raise ValueError("this run is over (Hardcore) — its saves can be viewed, not continued")
        snap = st.read_save(save_id)
        block = copy.deepcopy(snap["scenario"])
        town = st.get(block["town_ref"])
        arc = st.get(block["arc_ref"])
        loadouts = [st.get(h) for h in block.get("loadout_refs", [])]
        act = st.get(block["act_ref"]) if block.get("act_ref") else None
        adv = st.get(block["adventure_ref"]) if block.get("adventure_ref") else None
        scenario = ScenarioRun(town, arc, block["character_ids"], loadouts,
                               block.get("options"), town_id=block.get("town_id", ""),
                               scenario_id=block.get("scenario_id", ""))
        scenario.restore(block, act, adv, loadouts)
        # Freshen town art (it may have painted since the save).
        scenario.reload_town_art()
        return scenario

    # -- deletion ------------------------------------------------------------------ #
    def delete_save(self, run_id: str, save_id: str) -> None:
        self.store(run_id).delete_save(save_id)

    def delete_run(self, run_id: str) -> None:
        self.store(run_id).delete()
