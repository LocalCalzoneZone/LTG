"""Design Update 20 — the town as an RPG (playtest).

Four workstreams from one session: dialogue presuming knowledge nobody had
shared (§D20-1), scenarios that could bring nothing of their own to a town
(§D20-2 cast & places), quest options that were the same ride by two roads
(§D20-3), and the pre-generated Act I adventure that quietly made the choice
for you (§D20-3, town-only pre-generation).
"""

from __future__ import annotations

import copy

import pytest

from ltg_game_server import content, scenario_content as sc
from ltg_game_server.dialogue import (Conversation, check_flag_consistency,
                                      validate_dialogue)
from ltg_game_server.scenario import ScenarioRun

from tests.test_design_update_17_towns import (
    _isolate_dirs,      # noqa: F401 (autouse fixture)
    arc_raw,
    materialization_raw,
    questgiver_tree,
    town_raw,
)


def _tree(choices_root, extra_nodes=None):
    nodes = {"r": {"speaker": "npc", "text": "Well?", "choices": choices_root}}
    nodes.update(extra_nodes or {})
    return {"root": "r", "nodes": nodes}


# --------------------------------------------------------------------------- #
# §D20-1 — knowledge gating
# --------------------------------------------------------------------------- #
def test_an_unreachable_gate_is_rejected():
    """The playtest bug in reverse: 'What of the orc attack?' gated on a flag
    NOTHING can set is a door with no key — the repair loop gets told."""
    trees = {"smith": validate_dialogue(_tree([
        {"label": "What of the orc attack?", "requires": ["knows_orc_attack"]},
        {"label": "Farewell."}]))}
    problems = check_flag_consistency(trees)
    assert problems and "knows_orc_attack" in problems[0]
    assert "set_flag" in problems[0]                       # repair-friendly


def test_a_gate_its_own_act_can_open_is_clean():
    trees = {
        "reeve": validate_dialogue(_tree([
            {"label": "You look troubled.", "next": "tell"},
            {"label": "Farewell."}],
            {"tell": {"speaker": "npc",
                      "text": "Orcs mass at the ford — a day out, no more.",
                      "choices": [{"label": "We hear you.",
                                   "effects": [{"kind": "set_flag",
                                                "flag": "knows_orc_attack"}]}]}})),
        "smith": validate_dialogue(_tree([
            {"label": "What of the orc attack?", "requires": ["knows_orc_attack"]},
            {"label": "Farewell."}])),
    }
    assert check_flag_consistency(trees) == []


def test_standing_prior_act_and_item_flags_need_no_setter():
    trees = {"smith": validate_dialogue(_tree([
        {"label": "We came back bloodied.", "requires": ["defeated_once"]},
        {"label": "About the seal you gave us.", "requires": ["item_guild_seal"]},
        {"label": "The mine, again.", "requires": ["knows_mine"]},
        {"label": "Farewell."}]))}
    # knows_mine was set in an EARLIER act — the run's flags carry across.
    assert check_flag_consistency(trees, flags_known={"knows_mine"}) == []
    assert check_flag_consistency(trees) != []


def test_the_materialization_gate_covers_trees_and_topics():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = materialization_raw()
    # A gated act topic whose flag nothing sets: rejected with the flag named.
    m["topics"]["bram_toll"] = [{"ask": "About the drowned garrison…",
                                 "reply": "Bad iron down there.",
                                 "requires": ["knows_garrison"]}]
    with pytest.raises(ValueError, match="knows_garrison"):
        sc.validate_materialization(m, town, arc["acts"][0])
    # The same materialization passes once the questgiver can teach it…
    m2 = copy.deepcopy(m)
    m2["dialogues"]["sister_aud"]["nodes"]["more"]["choices"][0]["effects"].append(
        {"kind": "set_flag", "flag": "knows_garrison"})
    out = sc.validate_materialization(m2, town, arc["acts"][0])
    assert out["topics"]["bram_toll"][0]["requires"] == ["knows_garrison"]
    # …or when the run already knows it from an earlier act.
    sc.validate_materialization(m, town, arc["acts"][0], flags_known={"knows_garrison"})


def test_a_gated_topic_appears_only_once_the_party_learns():
    """End to end through the run: the flavour-tree topic is hidden until the
    knowledge flag is set, then askable."""
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = materialization_raw()
    m["dialogues"]["sister_aud"]["nodes"]["more"]["choices"][0]["effects"].append(
        {"kind": "set_flag", "flag": "knows_garrison"})
    m["topics"]["bram_toll"] = [{"ask": "About the drowned garrison…",
                                 "reply": "Bad iron down there.",
                                 "requires": ["knows_garrison"]}]
    run = ScenarioRun(town, arc, ["c"], [{"character": {"name": "Hero"}}], {})
    run.arrive(sc.validate_materialization(m, town, arc["acts"][0]))
    run.visit("tolls_forge")
    run.talk("bram_toll")
    labels = [c["label"] for c in run.conversation.visible_choices(run.flags)]
    assert "About the drowned garrison…" not in labels     # nobody has told them
    run.flags["knows_garrison"] = True
    run.talk("bram_toll")
    labels = [c["label"] for c in run.conversation.visible_choices(run.flags)]
    assert "About the drowned garrison…" in labels


# --------------------------------------------------------------------------- #
# §D20-2 — the scenario's own cast and places
# --------------------------------------------------------------------------- #
def _arc_with_cast():
    raw = arc_raw()
    raw["places"] = [{
        "name": "The Wrecked Barge", "function": "flavor",
        "description": "A river barge broken on the strand.",
        "interior_scene": "A tilted hold, water to the ankles, cargo nets swaying.",
        "exterior_scene": "A black hull heeled over on the mud.",
        "acts": [1, 2],
    }]
    raw["cast"] = [
        {"name": "Serel of the Ninth Lamp", "role": "wandering lamplighter",
         "persona": "Serel is warm and unhurried, and pays for stories in oil.",
         "portrait_desc": "A smiling traveller hung with brass lamps.",
         "location": "the_wrecked_barge",
         "secret": "Serel is the Reed-King's herald and is mapping the town's lights."},
        {"name": "Widow Casque", "role": "grieving petitioner",
         "persona": "She wants her son's body back from the lake.",
         "portrait_desc": "A grey woman in wet mourning crepe.",
         "location": "the_salt_shrine", "acts": [2]},
    ]
    return raw


def test_arc_cast_and_places_validate_and_ride_the_arc():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(_arc_with_cast(), town)
    assert [p["id"] for p in arc["places"]] == ["the_wrecked_barge"]
    serel, casque = arc["cast"]
    assert serel["location"] == "the_wrecked_barge" and serel["secret"]
    assert casque["acts"] == [2]
    # A cast member standing nowhere real is refused.
    bad = _arc_with_cast()
    bad["cast"][0]["location"] = "the_moon"
    with pytest.raises(ValueError, match="the_moon"):
        sc.validate_arc(bad, town)


def test_a_cast_member_may_give_the_quests():
    raw = _arc_with_cast()
    raw["acts"][0]["questgiver_npc"] = "serel_of_the_ninth_lamp"
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(raw, town)
    assert arc["acts"][0]["questgiver_npc"] == "serel_of_the_ninth_lamp"
    # …but not in an act they are not in town for.
    bad = _arc_with_cast()
    bad["acts"][0]["questgiver_npc"] = "widow_casque"      # acts: [2]
    with pytest.raises(ValueError, match="not in town that act"):
        sc.validate_arc(bad, town)


def test_town_for_act_merges_per_act_and_is_idempotent():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(_arc_with_cast(), town)
    act1 = sc.town_for_act(town, arc, 0)
    ids = {l["id"] for l in act1["locations"]}
    assert "the_wrecked_barge" in ids
    barge = sc.find_location(act1, "the_wrecked_barge")
    assert barge["_scenario"] and barge["scene"] == barge["interior_scene"]
    assert sc.find_npc(act1, "serel_of_the_ninth_lamp") is not None
    assert sc.find_npc(act1, "widow_casque") is None       # she comes in Act II
    # Idempotent: composing an already-composed town changes nothing.
    again = sc.town_for_act(act1, arc, 0)
    assert {l["id"] for l in again["locations"]} == ids
    assert len(sc.find_location(again, "the_salt_shrine")["npcs"]) == 2
    # Act II: the widow arrives; Act III: barge and Serel are gone.
    act2 = sc.town_for_act(town, arc, 1)
    assert sc.find_npc(act2, "widow_casque") is not None
    act3 = sc.town_for_act(town, arc, 2)
    assert sc.find_location(act3, "the_wrecked_barge") is None
    assert sc.find_npc(act3, "serel_of_the_ninth_lamp") is None  # his barge left with him
    # The base town was never mutated.
    assert sc.find_location(town, "the_wrecked_barge") is None


def test_the_run_composes_its_town_and_the_cast_is_talkable():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(_arc_with_cast(), town)
    m = materialization_raw()
    m["flavor"]["serel_of_the_ninth_lamp"] = "Trade you a story for a light?"
    run = ScenarioRun(town, arc, ["c"], [{"character": {"name": "Hero"}}], {})
    run.arrive(sc.validate_materialization(m, sc.town_for_act(town, arc, 0),
                                           arc["acts"][0]))
    snap = run.town_snapshot()
    assert any(l["id"] == "the_wrecked_barge" for l in snap["town"]["locations"])
    run.visit("the_wrecked_barge")
    run.talk("serel_of_the_ninth_lamp")
    node = run.conversation.snapshot(run.flags)
    assert "Trade you a story" in node["text"]
    # The secret never reaches any player-facing surface.
    assert "herald" not in str(snap) and "herald" not in str(node)


def test_cast_art_lands_on_the_arc_and_the_composed_town():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(_arc_with_cast(), town)
    run = ScenarioRun(town, arc, ["c"], [{"character": {"name": "Hero"}}], {})
    run.set_cast_art("cast", "serel_of_the_ninth_lamp", "/art/cast/serel.png")
    run.set_cast_art("place_interior", "the_wrecked_barge", "/art/places/x/int.png")
    assert run.arc["cast"][0]["art_url"] == "/art/cast/serel.png"
    merged = sc.find_npc(run.town, "serel_of_the_ninth_lamp")[1]
    assert merged["art_url"] == "/art/cast/serel.png"
    assert sc.find_location(run.town, "the_wrecked_barge")["interior_art_url"] \
        == "/art/places/x/int.png"


def test_a_new_arc_sends_the_old_cast_home():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(_arc_with_cast(), town)
    run = ScenarioRun(town, arc, ["c"], [{"character": {"name": "Hero"}}], {})
    m = materialization_raw()
    m["flavor"]["serel_of_the_ninth_lamp"] = "A light for the road?"
    run.arrive(sc.validate_materialization(m, sc.town_for_act(town, arc, 0),
                                           arc["acts"][0]))
    assert sc.find_npc(run.town, "serel_of_the_ninth_lamp") is not None
    run.begin_next_arc(sc.validate_arc(arc_raw(), town))    # no cast this time
    run.arrive(sc.validate_materialization(materialization_raw(), town,
                                           run.arc["acts"][0]))
    assert sc.find_npc(run.town, "serel_of_the_ninth_lamp") is None
    assert sc.find_location(run.town, "the_wrecked_barge") is None


def test_scenario_cast_art_items_cover_portraits_and_both_faces():
    from ltg_game_server import art
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(_arc_with_cast(), town)
    painted = []
    items = art.scenario_cast_art_items(arc, town["scene"],
                                        lambda k, i, u: painted.append((k, i, u)))
    labels = [i["label"] for i in items]
    assert any("Serel" in l for l in labels)
    assert any("(interior)" in l for l in labels) and any("(exterior)" in l for l in labels)
    # Already-painted entries queue nothing.
    arc2 = copy.deepcopy(arc)
    for n in arc2["cast"]:
        n["art_url"] = "/x.png"
    for p in arc2["places"]:
        p["interior_art_url"] = p["exterior_art_url"] = "/y.png"
    assert art.scenario_cast_art_items(arc2, "", lambda *a: None) == []


# --------------------------------------------------------------------------- #
# §D20-3 — the quests are real
# --------------------------------------------------------------------------- #
def test_every_quest_option_needs_its_own_distinct_theme():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = materialization_raw()
    m["quests"][1]["adventure_theme"] = ""
    with pytest.raises(ValueError, match="adventure_theme"):
        sc.validate_materialization(m, town, arc["acts"][0])
    m = materialization_raw()
    m["quests"][1]["adventure_theme"] = m["quests"][0]["adventure_theme"].upper()
    with pytest.raises(ValueError, match="share an adventure_theme"):
        sc.validate_materialization(m, town, arc["acts"][0])


def test_a_pregenerated_scenario_may_be_town_only(tmp_path):
    town_meta = sc.save_town(sc.validate_town(town_raw()))
    town = sc.town_detail(town_meta["id"])
    arc = arc_raw()
    m = materialization_raw()
    meta = sc.save_scenario({
        "town_id": town_meta["id"], "arc": arc, "difficulty": "standard",
        "act1": {"adventure_id": "", "quest_id": "",
                 "materialization": sc.validate_materialization(
                     m, town, sc.validate_arc(arc, town)["acts"][0])},
    })
    assert meta["act1_adventure_id"] == ""
    detail = sc.scenario_detail(meta["id"])
    assert detail["act1"]["materialization"]["quests"]
    # …while one WITHOUT the town materialization is refused.
    with pytest.raises(ValueError, match="materialization"):
        sc.save_scenario({"town_id": town_meta["id"], "arc": arc_raw(),
                          "act1": {"adventure_id": ""}})
