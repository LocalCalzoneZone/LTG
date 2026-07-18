"""The §D14 enemy kit floor on LLM generation (playtest-driven): every enemy
needs at least TWO components, and no enemy may be a 'punching bag' — a
proactive self-pump ready every turn locks out the basic attack forever, so the
enemy stacks counters it never spends (the Hollow Bell Foundry playtest bug).
Enforced by ``llm._design_problems`` inside the generation repair loop; the
prompt teaches the same rules and its gold examples must obey them."""

from __future__ import annotations

import json

from ltg_game_server import content, llm

_SCENE = "A collapsing star-observatory: brass orreries spin over a cracked dome."


def _jab(amount=3):
    return {"id": "jab", "archetype": "Burst", "timing": "proactive",
            "priority": 30, "cooldown": 2, "target_rule": "valuation",
            "telegraph": f"Jab — deal {amount}",
            "verbs": [{"kind": "deal_damage", "amount": amount,
                       "target": {"mode": "chosen", "side": "ally",
                                  "targeted": True}}]}


def _riposte():
    return {"id": "riposte", "archetype": "Punish", "timing": "reactive",
            "trigger": "on_hit", "cooldown": 2, "priority": 25,
            "target_rule": "trigger_source", "telegraph": "Riposte — deal 2",
            "verbs": [{"kind": "deal_damage", "amount": 2,
                       "target": {"mode": "chosen", "side": "ally",
                                  "targeted": True}}]}


def _pump(cooldown=1, mode="self", **extra):
    comp = {"id": "stoke", "archetype": "Escalate", "timing": "proactive",
            "priority": 40, "cooldown": cooldown, "target_rule": "self",
            "telegraph": "Stoke — +1/+1, permanently",
            "verbs": [{"kind": "counters", "power": 1, "toughness": 1,
                       "target": {"mode": mode}}]}
    if mode != "self":
        comp["verbs"][0]["target"] = {"mode": "chosen", "side": "enemy",
                                      "targeted": True}
        comp["target_rule"] = "lowest_hp_ally"
    comp.update(extra)
    return comp


def _enemy(eid, components):
    return {"id": eid, "name": eid.replace("_", " ").title(), "hp": 8,
            "power": 2, "level": 2, "row": "front", "attack_mode": "melee",
            "flavor": "does things", "description": "A brass automaton.",
            "components": components}


def _encounter(enemies):
    ids = [e["id"] for e in enemies]
    fill = (ids * 8)[:8]
    return {"name": "Kit Floor Test Zzz", "scene": _SCENE, "enemies": enemies,
            "layouts": {"1": fill[:2], "2": fill[:4], "3": fill[:6], "4": fill},
            "tokens": {}}


# --------------------------------------------------------------------------- #
# The gate itself
# --------------------------------------------------------------------------- #
def test_gate_rejects_enemies_below_two_components():
    enc = _encounter([_enemy("bare", []), _enemy("one_trick", [_jab()])])
    problems = llm._design_problems(enc)
    assert len(problems) == 2
    assert "Bare has 0 component(s)" in problems[0]
    assert "at least 2" in problems[0]
    assert "One Trick has 1 component(s)" in problems[1]


def test_gate_rejects_the_every_turn_self_pump():
    """The Hollow Bell bug: a cooldown-1 self-pump fires every turn, so the
    enemy never attacks — even a second (reactive) component doesn't save it."""
    enc = _encounter([_enemy("bag", [_pump(cooldown=1), _riposte()])])
    problems = llm._design_problems(enc)
    assert len(problems) == 1
    assert "punching bag" in problems[0]
    assert "'stoke'" in problems[0]
    # An absent cooldown means the same thing (ready every turn).
    bagless = _pump()
    bagless.pop("cooldown")
    assert llm._design_problems(_encounter([_enemy("bag", [bagless, _riposte()])]))


def test_gate_allows_the_correct_escalate_shapes():
    good = [
        _enemy("clock", [_pump(cooldown=2), _riposte()]),        # swings off-turn
        _enemy("avenger", [_pump(cooldown=1, timing="reactive",
                                 trigger="on_ally_death"), _jab()]),
        _enemy("moment", [_pump(cooldown=1, once_per_encounter=True), _jab()]),
        _enemy("herald", [_pump(cooldown=1, mode="chosen"), _riposte()]),  # pumps OTHERS
    ]
    assert llm._design_problems(_encounter(good)) == []


def test_gate_exempts_verbless_evasive_and_enrage():
    evasive = {"id": "flit", "archetype": "Evasive", "timing": "proactive",
               "priority": 20, "move_home": True, "target_rule": "self",
               "telegraph": "Flit"}
    enrage = {"id": "fury", "archetype": "Enrage", "priority": 5,
              "target_rule": "self", "telegraph": "FURY — +2/+2",
              "verbs": [{"kind": "counters", "power": 2, "toughness": 2,
                         "target": {"mode": "self"}}]}
    enc = _encounter([_enemy("slippery", [evasive, _riposte()]),
                      _enemy("boss", [_jab(), enrage])])
    assert llm._design_problems(enc) == []


def test_gate_requires_a_detonation_for_a_charge_gather():
    gather = {"id": "gather", "archetype": "Escalate", "timing": "proactive",
              "priority": 40, "cooldown": 1, "target_rule": "self",
              "telegraph": "Gathering…", "verbs": [{"kind": "charge", "amount": 1}]}
    enc = _encounter([_enemy("fuse", [gather, _riposte()])])
    problems = llm._design_problems(enc)
    assert len(problems) == 1 and "on_charge_full" in problems[0]
    detonation = {"id": "boom", "archetype": "Burst", "timing": "reactive",
                  "trigger": "on_charge_full", "charge_threshold": 2,
                  "priority": 10, "target_rule": "valuation",
                  "telegraph": "Detonate — deal 8",
                  "verbs": [{"kind": "deal_damage", "amount": 8,
                             "target": {"mode": "chosen", "side": "ally",
                                        "targeted": True}}]}
    enc = _encounter([_enemy("fuse", [gather, detonation])])
    assert llm._design_problems(enc) == []


# --------------------------------------------------------------------------- #
# Generation: rejected, fed back, repaired
# --------------------------------------------------------------------------- #
def test_generation_repairs_a_punching_bag(monkeypatch):
    bad = _encounter([_enemy("bag", [_pump(cooldown=1)]),
                      _enemy("pal", [_jab(), _riposte()])])
    good = _encounter([_enemy("bag", [_pump(cooldown=2), _riposte()]),
                       _enemy("pal", [_jab(), _riposte()])])
    good["name"] = "Kit Floor Repaired Zzz"
    replies = [json.dumps(bad), json.dumps(good)]
    calls = []

    def fake_chat(api_key, model, messages):
        calls.append(messages[-1]["content"])
        return replies[len(calls) - 1]

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm, "load_settings",
                        lambda: {**llm._default_settings(), "api_key": "sk"})
    meta = llm.generate_encounter(["soren", "ys"], "standard", "")
    path = content.LOADOUTS_DIR / f"{meta['id']}.json"
    try:
        assert len(calls) == 2                     # rejected, then repaired
        assert "punching bag" in calls[1]          # the error taught the fix
        assert "at least 2" in calls[1]
    finally:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# The prompt teaches the rules, and its gold examples obey them
# --------------------------------------------------------------------------- #
def test_prompt_teaches_the_kit_floor():
    D = llm.DEFAULT_INSTRUCTIONS
    for needle in ("two-component minimum", "AT LEAST TWO components",
                   "punching-bag rule", "cooldown ≥ 2"):
        assert needle in D, needle


def test_prompt_gold_examples_pass_the_gate():
    text = llm.DEFAULT_INSTRUCTIONS
    decoder = json.JSONDecoder()
    examples, idx = [], 0
    while True:
        idx = text.find('\n{"name":"', idx)
        if idx == -1:
            break
        obj, _ = decoder.raw_decode(text[idx + 1:])
        examples.append(obj)
        idx += 10
    assert len(examples) == 3
    for enc in examples:
        assert llm._design_problems(enc) == [], enc["name"]
