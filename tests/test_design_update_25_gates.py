"""Design Update 25 — the gates that match their prompts (roadmap M4.5–M4.15,
M4.18): enemy pricing, the lockdown floor and the per-encounter caps, the
channeler rule, the validator blind spots, the prompt errata and the
vocabulary taught, the party's tactical facts, the avoid-list and the act
writer naming the merchant stock. No model is called."""

from __future__ import annotations

import copy
import json
import re

import pytest

from ltg_combat.scenario import state_from_dict
from ltg_game_server import content, dialogue, llm, scenario_content as sc

from tests.conftest import gate_clean_pool
from tests.test_design_update_17_towns import (arc_raw, materialization_raw,
                                               town_raw)

TARGETED = {"mode": "chosen", "side": "ally", "targeted": True}


def _hit(n=3):
    return {"kind": "deal_damage", "amount": n, "target": dict(TARGETED)}


def _comp(cid, arch="Burst", verbs=None, **kw):
    return {"id": cid, "archetype": arch, "timing": kw.pop("timing", "proactive"),
            "priority": 30, "cooldown": kw.pop("cooldown", 2), "target_rule": "valuation",
            "telegraph": cid, "verbs": verbs or [_hit()], **kw}


def _foe(eid, comps, **kw):
    return {"id": eid, "name": eid.title(), "hp": kw.pop("hp", 4), "power": kw.pop("power", 1),
            "level": kw.pop("level", 3), "row": kw.pop("row", "front"),
            "attack_mode": kw.pop("attack_mode", "melee"), "components": comps, **kw}


# --------------------------------------------------------------------------- #
# §D25-5 Pricing (M4.8)
# --------------------------------------------------------------------------- #
def test_component_prices_follow_the_tables():
    assert llm.component_cost(_comp("a", "Burst")) == 4
    assert llm.component_cost(_comp("a", "Burst", cooldown=1)) == 6           # ×1.5
    assert llm.component_cost(_comp("a", "Burst", once_per_encounter=True)) == 2
    assert llm.component_cost(_comp("a", "Fortify", channel=True)) == 5       # 4.5 ↑
    assert llm.component_cost(_comp("a", "Punish", timing="reactive")) == 5   # +2 flat
    assert llm.component_cost(_comp("a", "Debilitate",
                                    verbs=[{"kind": "sap", "amount": 1}])) == 5
    assert llm.component_cost(_comp("a", "Burst", timing="reactive",
                                    trigger="on_charge_full", cooldown=0)) == 6  # base +2 only
    assert llm.component_cost(_comp("a", "Enrage")) == 0
    assert llm.component_cost(_comp("a", "Invented")) == llm.UNKNOWN_ARCHETYPE_COST


def test_an_enemys_level_is_the_smallest_budget_that_covers_it():
    # Husk 2/1 = 5, + Burst 4 + Punish reactive 5 = 14 → L2 (B(2) = 15).
    husk = _foe("husk", [_comp("a"), _comp("b", "Punish", timing="reactive")], hp=2)
    assert llm.price_enemy(husk)["cost"] == 14 and llm.price_enemy(husk)["level"] == 2
    husk["keywords"] = ["relentless"]                              # T-91: 3
    assert llm.price_enemy(husk)["cost"] == 17 and llm.price_enemy(husk)["level"] == 3
    boss = _foe("boss", [_comp("a")], hp=40, power=4, is_boss=True)
    # 40 + 12 + 4 = 56 against 2.5 × B(L): L4 (2.5 × 25 = 62.5).
    assert llm.price_enemy(boss)["level"] == 4


def test_the_worked_examples_pass_every_generation_gate_and_build():
    """The prompt's own examples are what the model copies: they must be priced,
    carry the lockdown floor and a channeler, and build in the engine."""
    tail = llm.DEFAULT_INSTRUCTIONS[llm.DEFAULT_INSTRUCTIONS.index("# Three worked examples"):]
    found = 0
    for m in re.finditer(r'^(\{"name".*\})\s*$', tail, re.M):
        raw = json.loads(m.group(1))
        for e in raw["enemies"]:
            assert e["level"] >= llm.price_enemy(e)["level"], (raw["name"], e["id"])
        enc, notes = llm._prepare_encounter(copy.deepcopy(raw), "standard")
        assert notes == [], (raw["name"], notes)
        assert llm._encounter_problems(enc, "standard") == [], raw["name"]
        content._validate_encounter(enc)
        found += 1
    assert found == 3


# --------------------------------------------------------------------------- #
# §D25-6 Lockdown, caps, the channeler (M4.9, M4.10)
# --------------------------------------------------------------------------- #
def test_lockdown_pieces_are_counted_per_body_and_the_budget_is_a_floor():
    pool = gate_clean_pool()
    assert llm._lockdown_problems(pool, "standard") == []
    thin = copy.deepcopy(pool)
    thin["layouts"]["4"] = [i for i in thin["layouts"]["4"] if i != "gc_chanter"] + ["gc_warden"]
    assert llm._lockdown_problems(thin, "standard") == []     # brute ×2 + hexer + growth
    assert llm._lockdown_problems(thin, "hard") == []         # 4 of 4
    thin["layouts"]["4"] = [i for i in thin["layouts"]["4"] if i != "gc_growth"] + ["gc_leech"]
    [hard] = llm._lockdown_problems(thin, "hard")             # hard wants one more
    assert hard.startswith('layouts["4"] fields 3 lockdown piece(s) — this size needs 4')
    stripped = copy.deepcopy(pool)
    for e in stripped["enemies"]:
        for c in e["components"]:
            c["verbs"] = [v for v in c["verbs"] if v["kind"] not in ("stun", "taunt")] or [_hit()]
    problems = llm._lockdown_problems(stripped, "standard")
    assert [p.split(" ")[0] for p in problems] == ['layouts["2"]', 'layouts["3"]', 'layouts["4"]']


@pytest.mark.parametrize("verb", [
    {"kind": "stun", "target": TARGETED},
    {"kind": "prevent", "parameter": "cast", "target": TARGETED},
    {"kind": "move_card", "count": 1, "source": "hand", "destination": "graveyard",
     "target": TARGETED},
    {"kind": "sap", "amount": 1, "target": TARGETED},
    {"kind": "modify_action", "action": "skill", "modifier": "lock_skill", "target": TARGETED},
    {"kind": "modify_action", "action": "ultimate", "modifier": "drain_ultimate", "amount": 10,
     "target": TARGETED},
    {"kind": "modify_action", "action": "attack", "modifier": "make_melee", "target": TARGETED},
    {"kind": "conditional", "condition": {"kind": "self_hp", "percent": 50},
     "effects": [{"kind": "stun", "target": TARGETED}]},
])
def test_every_turn_attack_is_a_lockdown_piece(verb):
    assert llm._is_lockdown_piece(_foe("x", [_comp("a", "Debilitate", verbs=[verb])]))


def test_one_of_each_scarce_kind_per_pool():
    discard = {"kind": "move_card", "count": 1, "source": "hand", "destination": "graveyard",
               "target": TARGETED}
    silence = {"kind": "prevent", "parameter": "cast", "target": TARGETED}
    pool = {"enemies": [
        _foe("thief", [_comp("a", "Debilitate", verbs=[discard])]),
        _foe("hag", [_comp("a", "Debilitate", verbs=[silence])]),
        _foe("adder", [_comp("a", "Debilitate", verbs=[{"kind": "poison", "amount": 1,
                                                         "target": TARGETED}])]),
        _foe("rat", [_comp("a")], keywords=["infect"]),
        _foe("rat2", [_comp("a")], keywords=["infect"]),
        _foe("boss", [_comp("contempt", "Counter", timing="reactive", trigger="on_ultimate_cast",
                            verbs=[{"kind": "counter", "filter": "action"}],
                            once_per_encounter=True)], is_boss=True),
        _foe("warder", [_comp("hush", "Counter", timing="reactive", trigger="on_spell_cast",
                              verbs=[{"kind": "counter", "filter": "spell"}])]),
    ]}
    problems = llm._cap_problems(pool)
    assert any("resource attacker" in p and "Thief" in p and "Hag" in p for p in problems)
    assert any("infect creature" in p for p in problems)
    assert not any("poisoner" in p for p in problems)          # only one
    # The boss's Tyrant's Contempt is T-70's business: one counter piece, one ult answer.
    assert not any("counter piece" in p or "gauge-punisher" in p for p in problems)


def test_standard_and_hard_pools_need_a_channeler():
    pool = gate_clean_pool()
    assert llm._channeler_problems(pool, "standard") == []
    for e in pool["enemies"]:
        for c in e["components"]:
            c.pop("channel", None)
    assert llm._channeler_problems(pool, "hard")
    assert llm._channeler_problems(pool, "easy") == []


def test_the_adventure_parameters_print_the_lockdown_floor_per_phase():
    party = {"size": 4, "avg_level": 3.0,
             "members": [{"name": f"h{i}", "level": 3, "colors": ["U"]} for i in range(4)]}
    block = llm._adventure_request_block(party, "standard", "", base_level=3)
    phase_lines = block.split("- PHASE 2", 1)[1].split("- PHASE 3", 1)[0]
    assert 'layouts["4"]' in phase_lines and "lockdown at least 3 pieces" in phase_lines


def test_the_same_reaction_on_the_whole_pool_is_a_monoculture():
    save = _comp("save", "Fortify", timing="reactive", trigger="on_incoming_lethal",
                 verbs=[{"kind": "heal", "amount": 4, "target": {"mode": "self"}}])
    pool = {"enemies": [_foe(f"e{i}", [_comp(f"k{i}", arch), dict(save)],
                             row=row, attack_mode=mode)
                        for i, (arch, row, mode) in enumerate(
                            [("Burst", "front", "melee"), ("Debilitate", "mid", "ranged"),
                             ("Escalate", "rear", "ranged"), ("Drain", "front", "melee")])]}
    problems = llm._sameness_problems(pool)
    assert any("carry the same reaction" in p for p in problems)
    pool["enemies"] = pool["enemies"][:2]
    assert not any("carry the same reaction" in p for p in llm._sameness_problems(pool))


# --------------------------------------------------------------------------- #
# Validator blind spots (M4.11)
# --------------------------------------------------------------------------- #
def _town_and_outline():
    town = sc.validate_town(town_raw())
    return town, sc.validate_arc(arc_raw(), town)["acts"][0]


def test_an_act_written_after_a_defeat_needs_the_bloodied_branch():
    town, outline = _town_and_outline()
    m = materialization_raw()
    sc.validate_materialization(copy.deepcopy(m), town, outline, defeated=True)   # has it
    for node in m["dialogues"]["sister_aud"]["nodes"].values():
        node["choices"] = [c for c in node["choices"]
                           if "defeated_once" not in (c.get("requires") or [])]
    sc.validate_materialization(copy.deepcopy(m), town, outline)                  # not required
    with pytest.raises(ValueError, match="returns beaten"):
        sc.validate_materialization(m, town, outline, defeated=True)


def test_paraphrased_quest_themes_are_one_ride():
    assert sc.theme_overlap("clear the drowned crypt under the chapel",
                            "descend into the drowned crypt beneath the chapel") >= \
        sc.THEME_OVERLAP_MAX
    assert sc.theme_overlap("storm the raiders' camp in the hills",
                            "take the fence who buys from the raiders") < sc.THEME_OVERLAP_MAX
    town, outline = _town_and_outline()
    m = materialization_raw()
    m["quests"][1]["adventure_theme"] = "boarded from the reed-shore: the sunken watchtower"
    m["quests"][0]["adventure_theme"] = "the sunken watchtower, boarded from the reed-shore"
    with pytest.raises(ValueError, match="share an adventure_theme"):
        sc.validate_materialization(m, town, outline)


def test_gates_match_their_prompts():
    assert llm.BOSS_ENRAGE_ROUNDS == (3, 5)
    assert dialogue.MAX_DEPTH == 8 and "never more than 8" in llm.ACT_INSTRUCTIONS
    assert sc.MAX_CAST == 3 and "0–3 NPCs" in llm.ARC_INSTRUCTIONS
    boss = _foe("b", [_comp("a")], is_boss=True, enrage_round=6, neglect=1)
    assert llm._boss_pressure_problems({"enemies": [boss]})


def _spec(comp, **enemy):
    return {"party": [{"id": "p", "name": "p", "hp": 20, "power": 2, "hand_size": 0,
                       "identity": ["U"], "row": "front", "attack_mode": "melee",
                       "library": []}],
            "enemies": [{"id": "ogre", "name": "Ogre", "hp": 10, "level": 3, "power": 2,
                         "components": [comp], **enemy}]}


def test_target_rules_and_triggers_are_checked_at_load():
    state_from_dict(_spec(_comp("a", target_rule="hero_class:cleric")))
    state_from_dict(_spec(_comp("a", target_rule="ogre")))                 # a fixed id
    state_from_dict(_spec(_comp("a", timing="reactive", trigger="on_ally_below_40")))
    with pytest.raises(ValueError, match="unknown target_rule 'lowest_hp_aly'"):
        state_from_dict(_spec(_comp("a", target_rule="lowest_hp_aly")))
    with pytest.raises(ValueError, match="grudge against an unknown class"):
        state_from_dict(_spec(_comp("a", target_rule="hero_class:paladin")))
    with pytest.raises(ValueError, match="unknown trigger 'on_ally_hurt'"):
        state_from_dict(_spec(_comp("a", timing="reactive", trigger="on_ally_hurt")))
    with pytest.raises(ValueError, match="unknown trigger"):
        state_from_dict(_spec(_comp("a", timing="reactive", trigger="on_self_below_150")))


# --------------------------------------------------------------------------- #
# Prompt errata and the vocabulary taught (M4.7, M4.12, M4.13, M4.18)
# --------------------------------------------------------------------------- #
def test_the_bodyguard_redirect_turns_the_blow_onto_itself_before_it_lands():
    D = llm.DEFAULT_INSTRUCTIONS
    assert '{"kind": "redirect", "new_target": {"mode": "self"}}' in D
    teach = D[D.index("- `redirect` — a BODYGUARD"):D.index("- `fight` — a DUELLIST")]
    assert '"on_attack"' in teach and 'NEVER "on_ally_hit"' in teach
    # The engine agrees: an enemy redirect aimed at "self" lands on the redirector.
    from ltg_core.schema import Redirect
    assert Redirect.model_validate({"kind": "redirect",
                                    "new_target": {"mode": "self"}}).new_target.mode.value == "self"


def test_the_conditional_example_uses_the_effect_condition_vocabulary():
    from ltg_core.schema import Conditional
    D = llm.DEFAULT_INSTRUCTIONS
    start = D.index('{"kind": "conditional", "condition"')
    text = D[start:D.index("}]}", start) + 3]
    Conditional.model_validate(json.loads(text))          # the schema accepts the example
    assert "self_hp_pct" not in text


def test_single_target_magnitude_reads_l_plus_2_everywhere():
    assert "single target = L+1" not in llm.DEFAULT_INSTRUCTIONS
    assert "single target = L+2" in llm.DEFAULT_INSTRUCTIONS


def test_grudges_relentless_composite_moves_and_countdown_rites_are_taught():
    D = llm.DEFAULT_INSTRUCTIONS
    schema_line = [ln for ln in D.splitlines() if '"target_rule":' in ln and "|" in ln][0]
    assert '"hero_class:<class>"' in schema_line and '"hero_type:<type>"' in schema_line
    assert "GRUDGE" in D and "relentless (3/3)" in D
    assert '"direction": "to_front", "target": {"mode":' in D and "HIT-AND-FADE" in D
    assert '"trigger": {"after_turns": 3}' in D and '"channel_drop"' in D
    assert "The game PRICES every enemy" in D


def test_standalone_encounters_learn_objectives():
    E = llm.ENCOUNTER_EXTENSION
    assert "AT MOST ONE objective" in E
    for kind in ("SURVIVE", "WAVES", "RACE", "DEADLINE"):
        assert kind in E
    assert "Phase III" not in E.split("The four kinds")[0]


# --------------------------------------------------------------------------- #
# §D25-7 The party's tactical facts (M4.6)
# --------------------------------------------------------------------------- #
def test_the_enemy_designer_sees_the_heroes_tactical_facts_and_nothing_private():
    lo = content.loadouts_for(["loadout_soren"])[0]
    ch = lo["character"]
    ch.update(keyword="reach", types=["human"], classes=["cleric"], row="mid",
              attack_mode="ranged", lore="SECRET LORE", brief={"concept": "a lamp-priest",
                                                               "wants": "SECRET WANT"},
              skill={"name": "Lantern Ward", "translated_text": "Prevent 3 damage."})
    party = llm.party_summary_from_loadouts([lo], deeds=[["slew the eel", "lost a boot",
                                                          "saved Aud", "found the key"]])
    roster = llm._roster_text(party)
    for needle in ("ranged, mid row", "keyword reach", "tags human, cleric",
                   "Skill: Lantern Ward (Prevent 3 damage.)", "a lamp-priest",
                   "lately: lost a boot / saved Aud / found the key"):
        assert needle in roster, needle
    assert "SECRET" not in roster and "slew the eel" not in roster
    block = llm._request_block(party, "standard", "")
    assert "tags human, cleric" in block


# --------------------------------------------------------------------------- #
# §D25-8 The avoid-list (M4.5)
# --------------------------------------------------------------------------- #
def test_the_town_and_arc_writers_are_told_what_is_taken():
    taken = {"towns": ["Karzum", "Millhaven"], "npcs": ["Hilde Brask"], "villains": ["Morvane"]}
    block = llm._avoid_block(taken)
    for name in ("Karzum", "Millhaven", "Hilde Brask", "Morvane", "Hedda", "Rook"):
        assert name in block
    assert "ALREADY TAKEN" in llm.town_prompt("", {}, None, taken)
    town = sc.validate_town(town_raw())
    party = {"size": 1, "avg_level": 1, "members": [{"name": "A", "level": 1, "colors": []}]}
    assert "Morvane" in llm.arc_prompt(town, party, "standard", taken=taken)


def test_the_avoid_list_is_capped():
    taken = {"towns": [f"Town{i}" for i in range(80)], "npcs": [f"Npc{i}" for i in range(80)],
             "villains": []}
    block = llm._avoid_block(taken)
    assert "Town59" in block and "Town60" not in block and "Npc0" not in block


def test_a_villain_wearing_a_taken_name_is_sent_back(monkeypatch):
    monkeypatch.setattr(llm, "avoid_names",
                        lambda: {"towns": [], "npcs": [], "villains": ["Morvane"]})
    replies = []

    def fake_chat_json(system, user, attempts, fix, what, task="scenarios"):
        raw = arc_raw()
        raw["villain"] = "Morvane, the Drowned Abbot"
        with pytest.raises(ValueError, match='reuses "Morvane"'):
            fix(raw)
        raw["villain"] = "Rook of the Salt Road"
        with pytest.raises(ValueError, match='reuses "Rook"'):
            fix(raw)
        raw["villain"] = "Abbess Carrow, keeper of the weir"
        replies.append(fix(raw))
        return replies[-1]

    monkeypatch.setattr(llm, "_scenario_chat", fake_chat_json)
    town = sc.validate_town(town_raw())
    party = {"size": 1, "avg_level": 1, "members": [{"name": "A", "level": 1, "colors": []}]}
    assert llm.generate_arc(town, party, "standard")["villain"].startswith("Abbess Carrow")


def test_a_new_town_may_not_take_an_existing_name(monkeypatch):
    monkeypatch.setattr(llm, "avoid_names",
                        lambda: {"towns": ["Hollowmere"], "npcs": [], "villains": []})

    def fake(system, user, attempts, fix, what, task="scenarios"):
        with pytest.raises(ValueError, match="already a town"):
            fix({**town_raw(), "world_entry": {}})
        raise ValueError("stop")

    monkeypatch.setattr(llm, "_scenario_chat", fake)
    with pytest.raises(ValueError, match="stop"):
        llm.generate_town(world_ctx={"known_towns": []})


# --------------------------------------------------------------------------- #
# §D25-9 The act writer names the stock (M4.15)
# --------------------------------------------------------------------------- #
def test_the_act_writer_names_the_rolled_stock_and_nothing_else():
    stock = {"the_forge": [{"id": "it1", "name": "Iron Sword", "slot": "primary",
                            "rarity": "common", "power": 1, "price": 20},
                           {"id": "it2", "name": "Oak Shield", "slot": "secondary",
                            "rarity": "uncommon", "price": 30}]}
    named = sc.name_stock(stock, {
        "it1": {"name": "Bram's Causeway Blade", "flavor": "Stamped with a heron.",
                "price": 1, "power": 9},
        "it2": {"name": "x"},                                   # too short: dropped
        "ghost": {"name": "Nothing Here"}})
    blade, shield = named["the_forge"]
    assert blade["name"] == "Bram's Causeway Blade" and blade["flavor"] == "Stamped with a heron."
    assert blade["price"] == 20 and blade["power"] == 1          # stats never move
    assert shield["name"] == "Oak Shield"
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    prompt = llm.act_prompt(town, arc, 0, {"members": [], "flags": {}}, stock=stock)
    assert "MERCHANTS' STOCK" in prompt and "[it1] Iron Sword" in prompt
    m = materialization_raw()
    m["stock_names"] = {"it2": {"name": "Reed-Weave Buckler"}}
    out = sc.validate_materialization(m, town, arc["acts"][0], stock=stock)
    assert out["stock"]["the_forge"][1]["name"] == "Reed-Weave Buckler"
    assert "stock_names" in llm.ACT_INSTRUCTIONS


def test_the_run_rolls_its_stock_before_the_act_writer_runs():
    from ltg_game_server.scenario import ScenarioRun
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    scen = ScenarioRun(town, arc, ["loadout_soren"], content.loadouts_for(["loadout_soren"]),
                       {}, town_id="hollowmere")
    scen.arrive(None)
    _args, kw = scen.materialize_inputs()
    assert kw["stock"] and all(isinstance(v, list) for v in kw["stock"].values())
    m = sc.validate_materialization(materialization_raw(), scen.town, arc["acts"][0],
                                    stock=kw["stock"])
    scen.take_materialization(m)
    assert scen.act["stock"] == kw["stock"]               # the named roll is what sells


# --------------------------------------------------------------------------- #
# M4.14 Library scenarios read the world
# --------------------------------------------------------------------------- #
def test_a_library_scenario_arc_reads_the_worldbook(monkeypatch):
    from ltg_game_server import scenario as scenario_mod, world
    seen = {}
    monkeypatch.setattr(sc, "town_detail", lambda tid: sc.validate_town(town_raw()))
    monkeypatch.setattr(world, "context_for", lambda tid: {"entry": {"town_id": tid},
                                                           "region": None, "neighbours": []})

    def fake_arc(town, party, difficulty, **kw):
        seen["arc"] = kw.get("world_ctx")
        return sc.validate_arc(arc_raw(), town)

    def fake_act(town, arc, act_index, party_state, **kw):
        seen["act"] = kw.get("world_ctx")
        raise ValueError("stop here")

    monkeypatch.setattr(llm, "generate_arc", fake_arc)
    monkeypatch.setattr(llm, "generate_act", fake_act)
    with pytest.raises(ValueError, match="stop here"):
        scenario_mod.pregenerate_scenario("hollowmere")
    assert seen["arc"]["entry"]["town_id"] == "hollowmere" and seen["act"] is seen["arc"]


# --------------------------------------------------------------------------- #
# M4.17 Generated gauntlets run end to end (mocked)
# --------------------------------------------------------------------------- #
def test_a_generated_gauntlet_is_minted_through_the_real_gate_and_quarantined(
        monkeypatch, tmp_path):
    from ltg_autoplay_tester import gauntlets
    monkeypatch.setattr(gauntlets, "GAUNTLET_DIR", tmp_path / "gauntlets")
    notes = []

    def fake_chat(api_key, model, messages, max_tokens=None, timeout=120.0, kind=""):
        notes.append(messages[1]["content"])
        return json.dumps(gate_clean_pool(name=f"Minted {len(notes)} Zzz"))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm, "load_settings", lambda: {**llm._default_settings(), "api_key": "sk"})
    before = {e["id"] for e in content.list_encounters()}
    summary = gauntlets.generate_gauntlet("M4 Probe", ["loadout_soren", "loadout_ys"], count=2)
    assert summary["generated"] and summary["frozen"] and summary["encounters"] == 2
    assert "(set piece 1 of 2)" in notes[0] and "(set piece 2 of 2)" in notes[1]
    loaded = gauntlets.load_gauntlet(summary["id"])
    assert [e["name"] for e in loaded["encounters"]] == ["Minted 1 Zzz", "Minted 2 Zzz"]
    assert loaded["hash"] == summary["hash"]
    assert {e["id"] for e in content.list_encounters()} == before      # quarantined
    with pytest.raises(ValueError, match="already exists"):
        gauntlets.generate_gauntlet("M4 Probe", ["loadout_soren"], count=1)
