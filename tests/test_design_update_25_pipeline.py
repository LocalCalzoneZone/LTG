"""Design Update 25 — the generation pipeline (roadmap M4.1–M4.4, M4.16).

Transport retry and timeouts, prompt-caching markers, shape faults as repair
turns, coercion, and phased adventures: the outline, one call per phase with
its own repair loop, resume, and the party waiting at a boundary for a phase
still being written. Every model call is mocked.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from ltg_game_server import content, llm
from ltg_game_server.adventure import AdventureRun
from ltg_game_server.session import SessionManager

from tests.conftest import gate_clean_pool


# --------------------------------------------------------------------------- #
# Transport (§D25-1)
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


def _ok(content_="{}"):
    return _Resp({"choices": [{"message": {"content": content_}, "finish_reason": "stop"}]})


@pytest.fixture
def wire(monkeypatch):
    """httpx.post answers from a script; sleeps are recorded, never taken."""
    box = {"script": [], "calls": [], "sleeps": []}

    def post(url, headers=None, json=None, timeout=None):
        box["calls"].append({"payload": json, "timeout": timeout})
        step = box["script"].pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(llm, "_sleep", lambda s: box["sleeps"].append(s))
    return box


def _call(model="openai/gpt-5.6-sol"):
    return llm._live_chat("sk", model, [{"role": "system", "content": "sys"},
                                        {"role": "user", "content": "go"}], 100, 30.0)


def test_a_5xx_is_retried_with_backoff_then_succeeds(wire):
    wire["script"] = [_Resp({"error": "busy"}, 503), _ok('{"a": 1}')]
    assert _call() == '{"a": 1}'
    assert len(wire["calls"]) == 2 and wire["sleeps"] == [llm.RETRY_BASE_S]


def test_a_429_honours_retry_after_up_to_the_cap(wire):
    wire["script"] = [_Resp({}, 429, {"retry-after": "7"}), _Resp({}, 429, {"retry-after": "900"}),
                      _ok()]
    _call()
    assert wire["sleeps"] == [7.0, llm.RETRY_CAP_S]


def test_transport_gives_up_after_its_tries_and_says_so(wire):
    wire["script"] = [_Resp({}, 500)] * llm.TRANSPORT_TRIES
    with pytest.raises(ValueError, match=f"after {llm.TRANSPORT_TRIES} tries"):
        _call()
    assert len(wire["calls"]) == llm.TRANSPORT_TRIES


def test_a_timeout_is_retried_once_only(wire):
    wire["script"] = [httpx.ReadTimeout("slow"), _ok('{"b": 2}')]
    assert _call() == '{"b": 2}'
    wire["script"] = [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slower"), _ok()]
    with pytest.raises(ValueError, match="timed out"):
        _call()


def test_a_401_or_a_400_is_never_retried(wire):
    wire["script"] = [_Resp({}, 401)]
    with pytest.raises(ValueError, match="401"):
        _call()
    wire["script"] = [_Resp({"error": "bad request"}, 400)]
    with pytest.raises(ValueError, match="400"):
        _call()
    assert len(wire["calls"]) == 2


def test_a_provider_error_inside_a_200_is_retried(wire):
    wire["script"] = [_Resp({"error": {"code": 502, "message": "upstream died"}}), _ok('{"c": 3}')]
    assert _call() == '{"c": 3}'


# --------------------------------------------------------------------------- #
# Prompt caching (§D25-2)
# --------------------------------------------------------------------------- #
def test_anthropic_and_google_get_cache_breakpoints_openai_does_not(wire):
    wire["script"] = [_ok(), _ok(), _ok()]
    _call("anthropic/claude-opus-5")
    _call("google/gemini-3.8-flash")
    _call("openai/gpt-5.6-sol")
    for sent in (wire["calls"][0], wire["calls"][1]):
        sys_msg, user_msg = sent["payload"]["messages"]
        assert sys_msg["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert user_msg["content"][0]["text"] == "go"
    assert wire["calls"][2]["payload"]["messages"][0]["content"] == "sys"


def test_only_the_newest_user_turn_is_marked_on_a_repair():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"}, {"role": "user", "content": "u2"}]
    wired = llm._wire_messages("anthropic/claude-opus-5", msgs)
    assert isinstance(wired[0]["content"], list) and isinstance(wired[3]["content"], list)
    assert wired[1]["content"] == "u1" and wired[2]["content"] == "a1"
    assert msgs[0]["content"] == "s"           # the caller's (tape-hashed) copy is untouched


# --------------------------------------------------------------------------- #
# Shape faults and coercion (§D25-1.3–4)
# --------------------------------------------------------------------------- #
def test_a_shape_fault_is_a_repair_turn_not_a_crash():
    replies = iter(['{"x": 1}', '{"x": 2}'])
    seen = []

    def fix(raw):
        if raw["x"] == 1:
            raise TypeError("'str' object has no attribute 'get'")
        return raw

    msgs = [{"role": "user", "content": "go"}]
    out = llm._repair_loop(msgs, lambda m: seen.append(m[-1]["content"]) or next(replies),
                           fix, "thing", 3)
    assert out == {"x": 2}
    assert "unexpected shape" in seen[1]


def test_duplicate_keys_are_rejected_by_name():
    with pytest.raises(ValueError, match='repeats the key "layouts"'):
        llm._extract_json('{"layouts": {}, "name": "x", "layouts": {}}')


def test_coercion_fixes_what_has_one_right_answer():
    enc = {"enemies": [
        {"id": "a", "name": "Archer", "hp": "4", "power": 2, "level": 1, "row": "front",
         "attack_mode": "ranged", "types": ["human", "gnome"], "supertypes": ["archer"],
         "components": [{"id": "x", "archetype": "Burst", "cooldown": 2,
                         "verbs": [{"kind": "deal_damage", "amount": 3}]}]},
        {"id": "b", "name": "Boss", "hp": 20, "power": 3, "level": 9, "row": "front",
         "is_boss": True, "enrage_round": 9, "types": ["giant"], "classes": ["brute"],
         "components": []}]}
    notes = llm._coerce_encounter(enc)
    archer, boss = enc["enemies"]
    assert archer["hp"] == 4 and archer["row"] == "mid"
    assert archer["types"] == ["human"] and archer["classes"] == ["archer"]
    assert "supertypes" not in archer
    # Body 4 + 2×3 + 2 ranged = 12, Burst 4 → 16: level 3 (B(3) = 20), not 1.
    assert archer["level"] == llm.price_enemy(archer)["level"] == 3
    assert boss["enrage_round"] == 5 and boss["neglect"] == content.DEFAULT_BOSS_DIALS["neglect"]
    assert boss["level"] == 9                  # above its price: legal (§F-6)
    assert any("raised" in n for n in notes)


def test_the_encounter_call_has_a_timeout_that_covers_its_ceiling(monkeypatch):
    assert llm.ENCOUNTER_TIMEOUT >= llm.ENCOUNTER_MAX_TOKENS / 75
    assert llm.PHASE_TIMEOUT >= llm.PHASE_MAX_TOKENS / 75
    assert llm.OUTLINE_TIMEOUT >= llm.OUTLINE_MAX_TOKENS / 75
    seen = {}

    def fake_chat(api_key, model, messages, max_tokens=None, timeout=120.0, kind=""):
        seen.update(timeout=timeout, kind=kind)
        return json.dumps(gate_clean_pool(name="Timeout Probe Zzz"))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm, "load_settings", lambda: {**llm._default_settings(), "api_key": "sk"})
    meta = llm.generate_encounter(["loadout_soren", "loadout_ys"], "standard", "")
    (content.CONTENT_DIR / f"{meta['id']}.json").unlink(missing_ok=True)
    assert seen == {"timeout": llm.ENCOUNTER_TIMEOUT, "kind": "encounter"}


# --------------------------------------------------------------------------- #
# Phased adventures (§D25-3, §D25-4)
# --------------------------------------------------------------------------- #
BOSS_LEVEL = 8
_NARRATION = ("You ride out along the causeway while the light goes grey. " * 12).strip()


def _outline(objective_phase=0):
    return {"name": "The Test Keep", "flavor": "Three rooms, one tyrant.",
            "faction": "the Grey Company",
            "boss": {"name": "Test Tyrant", "level": BOSS_LEVEL, "concept": "a cleaving tyrant"},
            "objective_phase": objective_phase,
            "phases": [{"station": f"station {i}", "threat": f"threat {i}", "mini_boss": False,
                        "beats": ["the road in", "the discovery"]} for i in (1, 2, 3)]}


def _boss():
    return {"id": "test_tyrant", "name": "Test Tyrant", "types": ["human"], "classes": ["warlord"],
            "hp": 20, "power": 3, "level": BOSS_LEVEL, "row": "front", "attack_mode": "melee",
            "is_boss": True, "enrage_round": 4, "neglect": 1, "flavor": "The keep's master.",
            "description": "A grey-armoured tyrant with a cleaver the size of a door.",
            "components": [
                {"id": "cleave", "archetype": "Burst", "timing": "proactive", "priority": 30,
                 "cooldown": 2, "target_rule": "self", "telegraph": "Cleave the front",
                 "verbs": [{"kind": "deal_damage", "amount": 8,
                            "target": {"mode": "all", "side": "ally", "rows": ["front"]}}]},
                {"id": "fury", "archetype": "Enrage", "priority": 5, "target_rule": "self",
                 "telegraph": "Fury", "verbs": [{"kind": "counters", "power": 2, "toughness": 2,
                                                  "target": {"mode": "self"}}]}]}


def _phase(n, **extra):
    enc = gate_clean_pool([_boss()] if n == 3 else None, name=f"Station {n} Zzz")
    return json.dumps({"narration": _NARRATION, **enc, **extra})


@pytest.fixture
def isolate():
    """Remove anything the generator writes (wrappers, phase files)."""
    before = {p.name for p in content.CONTENT_DIR.glob("*.json")}
    yield
    for p in content.CONTENT_DIR.glob("*.json"):
        if p.name not in before:
            p.unlink(missing_ok=True)


@pytest.fixture
def model(monkeypatch, isolate):
    """A scripted model: `script[kind]` is a list of replies, taken in order."""
    box = {"script": {}, "calls": []}

    def fake_chat(api_key, model_, messages, max_tokens=None, timeout=120.0, kind=""):
        box["calls"].append({"kind": kind, "user": messages[1]["content"],
                             "last": messages[-1]["content"], "timeout": timeout})
        return box["script"][kind].pop(0)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm, "load_settings", lambda: {**llm._default_settings(), "api_key": "sk"})
    return box


def test_an_adventure_is_an_outline_then_one_call_per_phase(model):
    model["script"] = {"adventure_outline": [json.dumps(_outline())],
                       "adventure_phase": [_phase(1), _phase(2), _phase(3)]}
    landed = []
    meta = llm.generate_adventure(["loadout_soren", "loadout_ys"], "standard",
                                  on_phase=lambda i, aid: landed.append((i, aid)))
    assert [c["kind"] for c in model["calls"]] == ["adventure_outline"] + ["adventure_phase"] * 3
    assert [i for i, _ in landed] == [0, 1, 2] and {a for _, a in landed} == {meta["id"]}
    detail = content.adventure_detail(meta["id"])
    assert len(detail["phases"]) == 3 and not detail.get("partial")
    assert meta["id"] in {a["id"] for a in content.list_adventures()}
    # Each phase call reads the outline; later ones the phases already written.
    phase_calls = [c for c in model["calls"] if c["kind"] == "adventure_phase"]
    assert all("THE ADVENTURE OUTLINE" in c["user"] for c in phase_calls)
    assert "PHASES ALREADY WRITTEN" not in phase_calls[0]["user"]
    assert "Station 1 Zzz" in phase_calls[1]["user"] and "Station 2 Zzz" in phase_calls[2]["user"]
    assert "This is the FINALE" in phase_calls[2]["user"]
    assert all(c["timeout"] == llm.PHASE_TIMEOUT for c in phase_calls)
    # The outline's rolled signatures ride into each phase call.
    assert all("SIGNATURE MECHANIC" in c["user"] for c in phase_calls)


def test_a_bad_phase_is_repaired_alone(model):
    stray = {"kind": "deadline", "turns": 5}
    model["script"] = {"adventure_outline": [json.dumps(_outline())],
                       "adventure_phase": [_phase(1), _phase(2, objective=stray), _phase(2),
                                           _phase(3)]}
    llm.generate_adventure(["loadout_soren", "loadout_ys"], "standard")
    kinds = [c["kind"] for c in model["calls"]]
    assert kinds == ["adventure_outline"] + ["adventure_phase"] * 4
    repair = model["calls"][3]
    assert "That output was rejected: phase 2:" in repair["last"]
    assert "outline puts the adventure's one objective nowhere" in repair["last"]


def test_the_ladder_names_an_enemy_priced_past_the_boss(model):
    outline = _outline()
    outline["boss"]["level"] = 3            # below the fillers' priced levels
    model["script"] = {"adventure_outline": [json.dumps(outline)],
                       "adventure_phase": [_phase(1)] * 3}
    with pytest.raises(ValueError, match="adventure phase 1 generation failed") as err:
        llm.generate_adventure(["loadout_soren", "loadout_ys"], "standard")
    assert "stays BELOW the boss's level 3" in str(err.value)
    assert "cost" in str(err.value)
    # Outside a run a half-written adventure is dropped, not left behind.
    assert not [a for a in content._adventure_registry().values() if a.get("partial")]


def test_a_run_resumes_at_the_first_missing_phase(model):
    model["script"] = {"adventure_outline": [json.dumps(_outline())],
                       "adventure_phase": [_phase(1), _phase(2), "not json", "{}", "[]"]}
    landed = []
    with pytest.raises(ValueError, match="adventure phase 3"):
        llm.generate_adventure(["loadout_soren", "loadout_ys"], "standard", run_only=True,
                               on_phase=lambda i, aid: landed.append(aid))
    aid = landed[0]
    partial = content.adventure_detail(aid)
    assert partial["partial"] and len(partial["phases"]) == 2 and partial["phases_total"] == 3
    assert aid not in {a["id"] for a in content.list_adventures(include_run_only=True)}
    model["calls"].clear()
    model["script"] = {"adventure_phase": [_phase(3)]}
    meta = llm.generate_adventure(["loadout_soren", "loadout_ys"], "standard", run_only=True,
                                  resume={"adventure_id": aid, "outline": partial["outline"]})
    assert meta["id"] == aid and [c["kind"] for c in model["calls"]] == ["adventure_phase"]
    assert "Station 2 Zzz" in model["calls"][0]["user"]   # it read what was written
    assert len(content.adventure_detail(aid)["phases"]) == 3


def test_the_outline_gate_rejects_a_boss_below_the_finale_level():
    fix = llm._outline_fix([1.0, 2.0, 4.0])
    bad = _outline()
    bad["boss"]["level"] = 2
    with pytest.raises(ValueError, match="at least 4"):
        fix(bad)
    ok = fix({**_outline(), "objective_phase": 9})
    assert ok["objective_phase"] == 0                # coerced: none
    assert ok["phases"][2]["mini_boss"] is False


# --------------------------------------------------------------------------- #
# The boundary waits for a phase still being written
# --------------------------------------------------------------------------- #
def _simple_phase(name, enemies, boss_id=None):
    ids = [e["id"] for e in enemies if not e.get("is_boss")]
    layouts = {}
    for size in range(1, 5):
        roster = [ids[0]] * (2 * size)
        if boss_id:
            roster[0] = boss_id
        layouts[str(size)] = roster
    return {"name": name, "scene": f"The {name}.", "enemies": enemies, "layouts": layouts,
            "narration": "You arrive. The test begins."}


def _foe(eid, level, boss=False):
    e = {"id": eid, "name": eid.title(), "hp": 4 if not boss else 20, "level": level,
         "row": "front", "attack_mode": "melee", "power": 1, "description": f"A {eid}."}
    if boss:
        e["is_boss"] = True
    return e


def test_the_party_waits_at_the_boundary_and_rides_on_when_the_phase_lands(isolate):
    wrapper = {"name": "Phased Keep", "flavor": "x", "outline": _outline()}
    aid = content.save_adventure_phase(None, 0, _simple_phase("Gate", [_foe("guard", 1)]), wrapper)
    run = AdventureRun(aid)
    assert run.phases_total == 3 and not run.is_final_phase() and not run.next_phase_ready()
    state, portraits, _art, eid = run.start(["loadout_soren", "loadout_ys"], seed=3)
    session = SessionManager().create(state, portraits=portraits, encounter_id=eid, adventure=run)
    session.clients["A"] = None
    session.claim("A", ["soren", "ys"])
    session.state.result = "victory"
    run.on_state_change(session.state)
    assert run.level_up is not None and session.public_result() is None   # a boundary, not the end
    session.confirm_level_up("A", "soren", {})
    session.confirm_level_up("A", "ys", {})
    # Everyone confirmed, but Phase II does not exist yet: the party waits.
    assert run.awaiting_phase and run.phase_index == 0
    assert session.snapshot_for("A")["adventure"]["awaiting_phase"] is True
    with pytest.raises(ValueError, match="still being written"):
        run.advance()
    # Phase II lands: the run takes it and composes it at once.
    content.save_adventure_phase(aid, 1, _simple_phase("Yard", [_foe("knight", 2)]), wrapper)
    assert session.phase_landed(content.adventure_detail(aid)) is True
    assert run.phase_index == 1 and not run.awaiting_phase
    assert session.encounter_id.endswith("__phase2")
    # A detail that is not an extension of this run is refused.
    other = copy.deepcopy(content.adventure_detail(aid))
    other["phases"] = other["phases"][::-1]
    assert run.add_phase(other) is False
    # Phase III lands while the party is mid-fight: taken, nothing composes.
    content.save_adventure_phase(aid, 2, _simple_phase(
        "Throne", [_foe("footman", 1), _foe("tyrant", 4, boss=True)], boss_id="tyrant"), wrapper)
    assert session.phase_landed(content.adventure_detail(aid)) is False
    assert run.phase_index == 1 and len(run.phases) == 3
    content.finalize_adventure(aid)
    assert not content.adventure_detail(aid).get("partial")


def test_a_partial_adventure_takes_art_writes_on_its_phases(isolate):
    wrapper = {"name": "Painted Keep", "flavor": "x", "outline": _outline()}
    aid = content.save_adventure_phase(None, 0, _simple_phase("Gate", [_foe("guard", 1)]), wrapper)
    eid = content.phase_encounter_id(aid, 1)
    enc = json.loads((content.CONTENT_DIR / f"{eid}.json").read_text())
    enc["scene_image"] = "/art/x.png"
    content.save_encounter(enc, eid)                  # the art writer's path
    assert content.encounter_detail(eid)["scene_image"] == "/art/x.png"


def test_phases_must_land_in_order(isolate):
    wrapper = {"name": "Ordered Keep", "flavor": "x", "outline": _outline()}
    with pytest.raises(ValueError, match="out of order"):
        aid = content.save_adventure_phase(None, 0, _simple_phase("Gate", [_foe("guard", 1)]),
                                           wrapper)
        content.save_adventure_phase(aid, 2, _simple_phase("Gate", [_foe("guard", 1)]), wrapper)


# --------------------------------------------------------------------------- #
# Saves: a newer copy of the same adventure is preferred on load
# --------------------------------------------------------------------------- #
def test_a_save_made_mid_writing_loads_the_fuller_copy(tmp_path):
    from ltg_game_server.runs import RunManager, RunStore
    mgr = RunManager(tmp_path)
    st = RunStore("run_1", tmp_path)
    one = {"id": "adv", "phases": [{"encounter_id": "adv__phase1"}], "phases_total": 3}
    two = {"id": "adv", "phases": [{"encounter_id": "adv__phase1"},
                                    {"encounter_id": "adv__phase2"}], "phases_total": 3}
    alien = {"id": "other", "phases": two["phases"]}
    run = {"adventure_job": {"adventure_ref": st.put(two)}}
    assert mgr._freshest_detail(st, run, one) == (two, True)
    assert mgr._freshest_detail(st, run, two) == (two, False)
    run = {"adventure_job": {"adventure_ref": st.put(alien)}}
    assert mgr._freshest_detail(st, run, one) == (one, False)


# --------------------------------------------------------------------------- #
# The adventure job: ready at Phase I, resumes where it stopped
# --------------------------------------------------------------------------- #
def _phased_generator(fail_after=None, seen=None):
    """A stand-in `generate_adventure`: writes the Update 10 test adventure a
    phase at a time through the real partial-save path, announcing each."""
    from tests.test_design_update_10 import _adventure

    def gen(character_ids, difficulty="standard", note="", on_phase=None, resume=None, **kw):
        if seen is not None:
            seen.append(resume)
        adv = _adventure()
        wrapper = {"name": adv["name"], "flavor": adv["flavor"], "run_only": True,
                   "outline": _outline()}
        aid = (resume or {}).get("adventure_id")
        start = len(content.adventure_detail(aid)["phases"]) if aid else 0
        for i in range(start, 3):
            if fail_after is not None and i >= fail_after:
                raise ValueError("the model wandered off")
            aid = content.save_adventure_phase(aid, i, adv["phases"][i], wrapper)
            if on_phase:
                on_phase(i, aid)
        return content.finalize_adventure(aid)
    return gen


def test_the_job_is_ready_at_phase_one_and_resumes_after_a_failure(tmp_path, isolate):
    from ltg_game_server import jobs
    from ltg_game_server.runs import RunManager
    from tests.test_design_update_17_scenario import _accept_quest, _start

    runs = RunManager(root=tmp_path / "saves")
    session, scen, _run_id = _start(runs)
    seen = []
    session.async_hook = lambda s, kind: (
        jobs.AdventureJobRunner(_phased_generator(fail_after=1, seen=seen)).start(s, None, None)
        if kind == "adventure_job" else s.materialize_act())
    _accept_quest(session)
    job = scen.adventure_job
    # Phase II failed, but Phase I is playable: the job stays ready.
    assert job["state"] == "ready" and scen.adventure_ready
    assert job["phases_ready"] == 1 and job["phases_total"] == 3
    assert job["phase_error"] == "the model wandered off" and not job["writing"]
    assert job["outline"]["boss"]["name"] == "Test Tyrant"
    assert len(scen.adventure_detail["phases"]) == 1
    # Retry resumes at Phase II with the stored outline; nothing is rewritten.
    jobs.AdventureJobRunner(_phased_generator(seen=seen)).start(session, None, None)
    assert seen[-1] == {"adventure_id": job["adventure_id"], "outline": job["outline"]}
    job = scen.adventure_job
    assert job["phases_ready"] == 3 and job["phase_error"] is None
    assert len(scen.adventure_detail["phases"]) == 3
    assert not content.adventure_detail(scen.adventure_id).get("partial")
