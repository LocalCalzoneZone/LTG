"""The anti-sameness gate on LLM generation: an encounter pool must not fight as
one enemy. Duplicate kits, a warband whose every aggressor reads the same
``target_rule`` (so it snipes the same hero all fight), too few distinct
archetypes, or a single silhouette (one row, one reach) are all rejected by
``llm._sameness_problems`` inside the generation repair loop.

The prompt already taught every one of these rules in prose; the gate exists
because a cheaper/faster model drops prose rules that a stronger one honours,
and nothing else catches the miss — four identical bodies all sniping the same
hero is legal JSON that clears every engine gate. Calibration: run against the
33 shipped encounters this flags 4 (the genuinely thin pools), so it accepts
authored content as the quality bar.
"""

from __future__ import annotations

import json

from ltg_game_server import llm


def _comp(cid, archetype, rule="valuation", kind="deal_damage", timing="proactive",
          trigger=None, mode="chosen"):
    target = ({"mode": "self"} if mode == "self"
              else {"mode": mode, "side": "ally", "targeted": True})
    # `counters` is +power/+toughness, not an `amount`; `stun` takes neither.
    if kind == "counters":
        verb = {"kind": kind, "power": 1, "toughness": 1, "target": target}
    elif kind == "stun":
        verb = {"kind": kind, "target": target}
    else:
        verb = {"kind": kind, "amount": 3, "target": target}
    comp = {"id": cid, "archetype": archetype, "timing": timing, "priority": 30,
            "cooldown": 2, "target_rule": rule, "telegraph": f"{cid} — do it",
            "verbs": [verb]}
    if trigger:
        comp["trigger"] = trigger
    return comp


def _enemy(eid, comps, row="front", mode="melee"):
    return {"id": eid, "name": eid.title(), "hp": 8, "power": 2, "level": 2,
            "row": row, "attack_mode": mode, "description": "A shape in the dark.",
            "types": ["horror"], "classes": ["rogue"],           # §D21 gate
            "components": comps}


def _pool(*enemies):
    return {"name": "Sameness Test", "scene": "A hall.", "enemies": list(enemies)}


# A varied, healthy four-body pool: four archetypes, three rows, both reaches,
# and three different reads on who to hit.
def _good_pool():
    return _pool(
        _enemy("brute", [_comp("smash", "Burst"),
                         _comp("spite", "Punish", "trigger_source",
                               timing="reactive", trigger="on_hit")]),
        _enemy("hexer", [_comp("hush", "Debilitate", "highest_threat", kind="stun"),
                         _comp("jeer", "Burst", "valuation")], row="mid", mode="ranged"),
        _enemy("medic", [_comp("mend", "Fortify", "lowest_hp_ally", kind="heal"),
                         _comp("spit", "Burst", "valuation")], row="rear", mode="ranged"),
        _enemy("growth", [_comp("coil", "Escalate", "self", kind="counters", mode="self"),
                          _comp("lash", "Burst", "channeling_player")], row="mid", mode="ranged"),
    )


def test_a_varied_pool_passes_clean():
    assert llm._sameness_problems(_good_pool()) == []


def test_a_pool_of_one_enemy_is_exempt():
    solo = _pool(_enemy("boss", [_comp("a", "Burst"), _comp("b", "Enrage")]))
    assert llm._sameness_problems(solo) == []


# --------------------------------------------------------------------------- #
# 1. Duplicate kits — one enemy under several names
# --------------------------------------------------------------------------- #
def test_gate_rejects_two_enemies_sharing_a_kit():
    kit = [_comp("smash", "Burst"), _comp("spite", "Punish", "trigger_source",
                                          timing="reactive", trigger="on_hit")]
    enc = _pool(_enemy("wolf", [dict(c) for c in kit]),
                _enemy("hound", [dict(c) for c in kit], row="mid"),
                _enemy("medic", [_comp("mend", "Fortify", "lowest_hp_ally", kind="heal"),
                                 _comp("spit", "Burst")], row="rear", mode="ranged"))
    problems = llm._sameness_problems(enc)
    assert any("SAME kit" in p and "Wolf" in p and "Hound" in p for p in problems)


def test_duplicate_kit_message_points_at_layouts_for_extra_bodies():
    """Repeating a body is legal — via ``layouts``, which the engine clones. The
    repair text must say so, or the model 'fixes' a clone by deleting it and
    breaks the outnumbering minimums instead."""
    kit = [_comp("smash", "Burst"), _comp("gore", "Escalate", "self",
                                          kind="counters", mode="self")]
    enc = _pool(_enemy("wolf", [dict(c) for c in kit]),
                _enemy("hound", [dict(c) for c in kit]))
    assert any('"layouts"' in p for p in llm._sameness_problems(enc))


def test_different_damage_numbers_do_not_rescue_a_shared_kit():
    """Same archetype, same timing, same verb shape — a different `amount` is a
    costume, not a design."""
    a = _comp("smash", "Burst")
    b = _comp("smash", "Burst")
    b["verbs"][0]["amount"] = 9
    enc = _pool(_enemy("wolf", [a, _comp("x", "Punish", timing="reactive",
                                         trigger="on_hit")]),
                _enemy("hound", [b, _comp("x", "Punish", timing="reactive",
                                          trigger="on_hit")]))
    assert any("SAME kit" in p for p in llm._sameness_problems(enc))


# --------------------------------------------------------------------------- #
# 2. Every aggressor reading the same target_rule
# --------------------------------------------------------------------------- #
def test_gate_rejects_an_all_valuation_warband():
    enc = _pool(
        _enemy("a", [_comp("hit", "Burst"), _comp("bite", "Swarm")]),
        _enemy("b", [_comp("cut", "Debilitate"), _comp("mend", "Fortify",
                                                       "lowest_hp_ally", kind="heal")],
               row="mid", mode="ranged"),
        _enemy("c", [_comp("stab", "Escalate"), _comp("jab", "Punish")], row="rear"),
    )
    problems = llm._sameness_problems(enc)
    assert any('target_rule "valuation"' in p for p in problems)
    # and it names the alternatives the engine actually supports
    assert any("highest_threat" in p and "channeling_player" in p for p in problems)


def test_one_different_read_satisfies_the_target_rule_check():
    enc = _pool(
        _enemy("a", [_comp("hit", "Burst"), _comp("bite", "Swarm")]),
        _enemy("b", [_comp("cut", "Debilitate", "highest_threat"),
                     _comp("mend", "Fortify", "lowest_hp_ally", kind="heal")],
               row="mid", mode="ranged"),
        _enemy("c", [_comp("stab", "Escalate"), _comp("jab", "Punish")], row="rear"),
    )
    assert not any("target_rule" in p for p in llm._sameness_problems(enc))


def test_support_rules_are_not_counted_as_aggressors():
    """A pool of healers all reading lowest_hp_ally is not the failure this
    check is about — only hero-aimed components count."""
    heal = lambda i: _enemy(f"m{i}", [_comp("mend", "Fortify", "lowest_hp_ally",
                                            kind="heal"),
                                      _comp(f"s{i}", "Burst", "highest_threat")],
                            row="rear", mode="ranged")
    enc = _pool(heal(1), heal(2))
    assert not any("target_rule" in p for p in llm._sameness_problems(enc))


# --------------------------------------------------------------------------- #
# 3. Too few distinct archetypes
# --------------------------------------------------------------------------- #
def test_gate_requires_four_distinct_archetypes_in_a_full_pool():
    enc = _pool(
        _enemy("a", [_comp("x", "Burst"), _comp("y", "Punish", "trigger_source",
                                                timing="reactive", trigger="on_hit")]),
        _enemy("b", [_comp("x", "Burst", "highest_threat"),
                     _comp("z", "Punish", timing="reactive", trigger="on_ally_hit")],
               row="mid", mode="ranged"),
        _enemy("c", [_comp("q", "Burst", "channeling_player"),
                     _comp("r", "Punish", timing="reactive", trigger="on_spell_cast")],
               row="rear", mode="ranged"),
        _enemy("d", [_comp("s", "Burst", "primed_hero"),
                     _comp("t", "Punish", timing="reactive", trigger="on_hit")],
               row="mid"),
    )
    problems = llm._sameness_problems(enc)
    assert any("distinct component archetype" in p and "at least 4" in p
               for p in problems)


def test_small_pools_only_need_one_archetype_per_body():
    """min(4, pool size): two enemies cannot field four archetypes."""
    enc = _pool(_enemy("a", [_comp("x", "Burst"), _comp("y", "Punish")]),
                _enemy("b", [_comp("q", "Fortify", "lowest_hp_ally", kind="heal"),
                             _comp("r", "Debilitate", "highest_threat", kind="stun")],
                       row="rear", mode="ranged"))
    assert not any("distinct component archetype" in p
                   for p in llm._sameness_problems(enc))


# --------------------------------------------------------------------------- #
# 4. One silhouette
# --------------------------------------------------------------------------- #
def test_gate_rejects_a_pool_that_stands_in_one_row():
    enc = _good_pool()
    for e in enc["enemies"]:
        e["row"] = "front"
    assert any('"front" row' in p for p in llm._sameness_problems(enc))


def test_gate_rejects_a_pool_of_one_reach():
    enc = _good_pool()
    for e in enc["enemies"]:
        e["attack_mode"] = "melee"
    assert any('attack_mode "melee"' in p for p in llm._sameness_problems(enc))


# --------------------------------------------------------------------------- #
# Wiring + prompt agreement
# --------------------------------------------------------------------------- #
def test_generation_repairs_a_pool_of_clones(monkeypatch):
    """The gate runs inside the repair loop: a cloned pool is fed back to the
    model with the failure, and the corrected reply persists."""
    from ltg_game_server import content

    from tests.conftest import gate_clean_pool

    def stamp(enc):
        for e in enc["enemies"]:
            e.setdefault("description", "A shape in the dark.")
            e.setdefault("types", ["undead"])
            e.setdefault("classes", ["warrior"])
        return enc

    kit = [_comp("smash", "Burst"), _comp("spite", "Punish", "trigger_source",
                                          timing="reactive", trigger="on_hit")]
    clones = stamp({"name": "Clone Pool Zzz", "scene": "A drowned hall of bells.",
                    "enemies": [_enemy(i, [dict(c) for c in kit]) for i in "abcdefgh"],
                    # Layouts are LEGAL (8 distinct) so the rejection is the
                    # duplicate-kit gate, not the layout floor.
                    "layouts": {"1": list("ab"), "2": list("abcd"),
                                "3": list("abcdef"), "4": list("abcdefgh")},
                    "tokens": {}})
    varied = stamp(gate_clean_pool(name="Varied Pool Zzz"))
    replies = [json.dumps(clones), json.dumps(varied)]
    calls = []

    def fake_chat(api_key, model, messages, **kw):
        calls.append(messages[-1]["content"])
        return replies[len(calls) - 1]

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm, "load_settings",
                        lambda: {**llm._default_settings(), "api_key": "sk"})
    meta = llm.generate_encounter(["soren", "ys"], "standard", "")
    path = content.CONTENT_DIR / f"{meta['id']}.json"
    try:
        assert len(calls) == 2                  # rejected, then repaired
        assert "SAME kit" in calls[1]           # the model was told why
    finally:
        path.unlink(missing_ok=True)


def test_prompt_documents_every_target_rule_the_engine_supports():
    """The JSON schema block is the contract a model actually follows. It used to
    omit highest_threat / wounded_ally while the prose told the model to use
    them — so every component fell back to "valuation" and the whole warband
    ganged one hero."""
    schema_line = [ln for ln in llm.DEFAULT_INSTRUCTIONS.splitlines()
                   if '"target_rule":' in ln and "|" in ln]
    assert len(schema_line) == 1
    for rule in ("valuation", "highest_threat", "primed_hero", "channeling_player",
                 "trigger_source", "self", "lowest_hp_ally", "wounded_ally"):
        assert rule in schema_line[0], rule


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
        assert llm._sameness_problems(enc) == [], enc["name"]
