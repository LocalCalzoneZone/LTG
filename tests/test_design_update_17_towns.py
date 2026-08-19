"""Design Update 17 §D17-5.1 / §D17-5.4 / §D17-6 — towns, arcs, act
materializations, dialogue trees, and the generators (LLM mocked)."""

from __future__ import annotations

import json

import pytest

from ltg_game_server import content, dialogue, llm, scenario_content as sc


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _npc(name, role="keeper"):
    return {"name": name, "role": role,
            "persona": f"{name} is weathered and watchful, and wants the road kept open.",
            "portrait_desc": f"A lined face, grey braid, {role}'s apron."}


def town_raw(name="Hollowmere"):
    return {
        "name": name,
        "region_flavor": "A fen-edge town where the causeway meets the salt marsh.",
        "scene": "Slate roofs over a black lake; lanterns on the causeway; reeds bending.",
        "locations": [
            {"name": "The Drowned Lantern", "function": "inn",
             "scene": "A low taproom, peat fire, nets drying from the beams.",
             "description": "Rest, and the only warm bed for forty miles.",
             "npcs": [_npc("Marra Quill", "innkeeper")]},
            {"name": "Tolls' Forge", "function": "weaponsmith",
             "scene": "A soot-black smithy open to the causeway.",
             "description": "Blades and bows.", "npcs": [_npc("Bram Toll", "smith")]},
            {"name": "The Brass Eye", "function": "artificer",
             "scene": "Shelves of lenses and clockwork under a green lamp.",
             "description": "Trinkets and charms.", "npcs": [_npc("Ysolde Vane", "artificer")]},
            {"name": "Reedwife's", "function": "apothecary",
             "scene": "Bundles of marsh herbs, jars of black tincture.",
             "description": "Potions.", "npcs": [_npc("Old Hesk", "herbalist")]},
            {"name": "The Salt Shrine", "function": "shrine",
             "scene": "A stone shrine half-sunk in the reeds, candles guttering.",
             "description": "Where the town prays against the lake.",
             "npcs": [_npc("Sister Aud", "priestess"), _npc("Corwen", "veteran")]},
        ],
    }


def arc_raw():
    return {
        "title": "The Siege of Hollowmere",
        "villain": "The Reed-King, a drowned lord who wants his causeway back.",
        "stakes": "The causeway floods and the town drowns.",
        "acts": [
            {"title": "The Lantern Goes Out", "hook": "Boats vanish on the black lake.",
             "questgiver_npc": "sister_aud", "handoff": "corwen",
             "adventure_theme": "the sunken watchtower and its drowned garrison",
             "tone_notes": "cold, wet, patient dread"},
            {"title": "The Reed-Choir", "hook": "The reeds sing at night; sleepers walk into the water.",
             "questgiver_npc": "corwen", "handoff": None,
             "adventure_theme": "the reed-choir's mound", "tone_notes": "hypnotic"},
            {"title": "The Reed-King Rises", "hook": "The lake climbs the causeway.",
             "questgiver_npc": "sister_aud", "handoff": None,
             "adventure_theme": "the Reed-King's drowned hall", "tone_notes": "final, roaring"},
        ],
    }


def questgiver_tree():
    return {
        "root": "greet",
        "nodes": {
            "greet": {"speaker": "npc", "text": "Boats go out and do not come back.",
                      "choices": [
                          {"label": "Tell us more.", "next": "more"},
                          {"label": "We'll go.", "next": "go",
                           "effects": [{"kind": "grant_quest"}, {"kind": "unlock_adventure"}]},
                          {"label": "We came back bloodied.", "next": "bloodied",
                           "requires": ["defeated_once"]},
                          {"label": "Not today."},
                      ]},
            "more": {"speaker": "npc", "text": "The old watchtower lights at night.",
                     "choices": [{"label": "We'll look.", "next": "go",
                                  "effects": [{"kind": "grant_quest"}, {"kind": "unlock_adventure"}]},
                                 {"label": "Later."}]},
            "bloodied": {"speaker": "npc", "text": "Then you know what waits. Will you go again?",
                         "choices": [{"label": "Again.", "next": "go",
                                      "effects": [{"kind": "grant_quest"}, {"kind": "unlock_adventure"}]},
                                     {"label": "No."}]},
            "go": {"speaker": "npc", "text": "Take this for the road.",
                   "choices": [{"label": "Farewell.", "effects": [{"kind": "give_gold", "amount": 10},
                                                                   {"kind": "set_flag", "flag": "aud_blessed"}]}]},
        },
    }


def materialization_raw():
    return {
        "quest": {"title": "The Lantern Goes Out", "text": "Find the boats. Light the tower."},
        "arrival": "You come up the causeway at dusk; the lake is very still.",
        "dialogues": {
            "sister_aud": questgiver_tree(),
            "marra_quill": {"root": "r", "nodes": {"r": {"speaker": "npc", "text": "A room?",
                            "choices": [{"label": "Take a room.", "effects": [{"kind": "rest"}]},
                                        {"label": "Not yet."}]}}},
        },
        "flavor": {"bram_toll": "Steel's honest. Lakes aren't."},
    }


@pytest.fixture(autouse=True)
def _isolate_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TOWNS_DIR", tmp_path / "towns")
    monkeypatch.setattr(sc, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(sc, "TOWN_HIDDEN_FILE", tmp_path / "th.json")
    monkeypatch.setattr(sc, "SCENARIO_HIDDEN_FILE", tmp_path / "sh.json")


# --------------------------------------------------------------------------- #
# Towns
# --------------------------------------------------------------------------- #
def test_town_validation_and_registry():
    meta = sc.save_town(town_raw())
    assert meta["id"] == "hollowmere" and meta["location_count"] == 5 and meta["npc_count"] == 6
    t = sc.town_detail("hollowmere")
    assert [l["function"] for l in t["locations"]] == ["inn", "weaponsmith", "artificer", "apothecary", "shrine"]
    assert sc.find_npc(t, "sister_aud")[1]["name"] == "Sister Aud"
    assert sc.location_of_function(t, "inn")["id"] == "the_drowned_lantern"
    assert [x["id"] for x in sc.list_towns()] == ["hollowmere"]
    # Legacy `scene` loads as the INTERIOR (the backdrop inside); the exterior
    # (the map card) is separate and may be added later.
    inn = t["locations"][0]
    assert inn["interior_scene"] == inn["scene"] and inn["exterior_scene"] == ""
    raw = town_raw()
    raw["locations"][0]["exterior_scene"] = "A low stone inn with a lantern over the door."
    raw["locations"][0]["interior_scene"] = "A peat fire, nets from the beams, a scarred bar."
    del raw["locations"][0]["scene"]
    cleaned = sc.validate_town(raw)
    assert cleaned["locations"][0]["exterior_scene"].startswith("A low stone inn")
    assert cleaned["locations"][0]["scene"] == cleaned["locations"][0]["interior_scene"]
    sc.delete_town("hollowmere")
    assert sc.list_towns() == []


def test_town_validation_rejects_missing_function_and_bad_flavor_count():
    raw = town_raw()
    raw["locations"] = [l for l in raw["locations"] if l["function"] != "apothecary"]
    with pytest.raises(ValueError, match="apothecary"):
        sc.validate_town(raw)
    raw = town_raw()
    raw["locations"] = raw["locations"][:4]  # no flavour location
    with pytest.raises(ValueError, match="flavour"):
        sc.validate_town(raw)
    raw = town_raw()
    raw["locations"][0]["npcs"][0]["portrait_desc"] = ""
    with pytest.raises(ValueError, match="portrait_desc"):
        sc.validate_town(raw)


# --------------------------------------------------------------------------- #
# Arcs and materializations
# --------------------------------------------------------------------------- #
def test_arc_validation_resolves_npcs_and_locations():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    assert arc["acts"][0]["questgiver_location"] == "the_salt_shrine"
    assert arc["acts"][0]["handoff"] == "corwen"
    bad = arc_raw()
    bad["acts"][1]["questgiver_npc"] = "nobody"
    with pytest.raises(ValueError, match="not an NPC"):
        sc.validate_arc(bad, town)


def test_dialogue_validation_closed_hooks_depth_and_refs():
    tree = dialogue.validate_dialogue(questgiver_tree())
    assert tree["root"] == "greet" and len(tree["nodes"]) == 4
    bad = questgiver_tree()
    bad["nodes"]["greet"]["choices"][0]["effects"] = [{"kind": "summon_dragon"}]
    with pytest.raises(ValueError, match="unknown hook"):
        dialogue.validate_dialogue(bad)
    bad = questgiver_tree()
    bad["nodes"]["greet"]["choices"][0]["next"] = "missing"
    with pytest.raises(ValueError, match="missing node"):
        dialogue.validate_dialogue(bad)
    bad = questgiver_tree()
    bad["freeform"] = True
    with pytest.raises(ValueError, match="freeform"):
        dialogue.validate_dialogue(bad)
    loop = {"root": "a", "nodes": {"a": {"text": "x", "choices": [{"label": "b", "next": "b"}]},
                                   "b": {"text": "y", "choices": [{"label": "a", "next": "a"}]}}}
    with pytest.raises(ValueError, match="loops"):
        dialogue.validate_dialogue(loop)


def test_materialization_requires_questgiver_accept_choice():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = sc.validate_materialization(materialization_raw(), town, arc["acts"][0])
    assert m["quest"]["title"] == "The Lantern Goes Out"
    assert set(m["dialogues"]) == {"sister_aud", "marra_quill"}
    assert m["flavor"] == {"bram_toll": "Steel's honest. Lakes aren't."}
    bad = materialization_raw()
    for node in bad["dialogues"]["sister_aud"]["nodes"].values():
        for ch in node["choices"]:
            ch.pop("effects", None)
    with pytest.raises(ValueError, match="Quest Accept"):
        sc.validate_materialization(bad, town, arc["acts"][0])


def test_conversation_walker_filters_on_flags_and_returns_hooks():
    tree = dialogue.validate_dialogue(questgiver_tree())
    conv = dialogue.Conversation("sister_aud", tree)
    vis = conv.visible_choices({})
    assert [c["label"] for c in vis] == ["Tell us more.", "We'll go.", "Not today."]
    assert vis[1]["party_wide"] is True and vis[0]["party_wide"] is False
    vis2 = conv.visible_choices({"defeated_once": True})
    assert "We came back bloodied." in [c["label"] for c in vis2]
    with pytest.raises(ValueError, match="not available"):
        conv.choose(2, {})  # the bloodied branch is hidden without the flag
    hooks = conv.choose(1, {})
    assert [h["kind"] for h in hooks] == ["grant_quest", "unlock_adventure"]
    assert conv.node_id == "go" and not conv.over
    hooks = conv.choose(0, {})
    assert [h["kind"] for h in hooks] == ["give_gold", "set_flag"] and hooks[0]["amount"] == 10
    assert conv.over and conv.snapshot({})["over"] is True


# --------------------------------------------------------------------------- #
# Generators (LLM mocked)
# --------------------------------------------------------------------------- #
@pytest.fixture
def mocked_llm(monkeypatch):
    replies = {}

    def fake_settings():
        return {**llm._default_settings(), "api_key": "k", "model": "m"}

    def fake_chat(api_key, model, messages, max_tokens=None, timeout=None):
        system = messages[0]["content"]
        for key, reply in replies.items():
            if key in system:
                return json.dumps(reply)
        raise AssertionError("no canned reply for this system prompt")

    monkeypatch.setattr(llm, "load_settings", fake_settings)
    monkeypatch.setattr(llm, "_chat", fake_chat)
    return replies


def test_generate_town_arc_and_act(mocked_llm):
    mocked_llm["Design\nONE TOWN"] = town_raw("Bellhollow")
    meta = llm.generate_town("a bell-foundry town")
    assert meta["id"] == "bellhollow"
    town = sc.town_detail("bellhollow")
    mocked_llm["write the ARC of one"] = arc_raw()
    party = {"size": 2, "avg_level": 1, "members": [{"name": "A", "level": 1, "colors": ["U"]}]}
    arc = llm.generate_arc(town, party, "standard")
    assert arc["title"] == "The Siege of Hollowmere"
    mocked_llm["You write the TOWN PORTION"] = materialization_raw()
    m = llm.generate_act(town, arc, 0, {"members": [{"name": "A", "level": 1}], "flags": {}})
    assert "sister_aud" in m["dialogues"]


def test_adventure_context_block_and_base_level():
    party = {"size": 1, "avg_level": 3, "members": [{"name": "Soren", "level": 3, "colors": ["W"]}]}
    block = llm._adventure_request_block(
        party, "standard", "", base_level=3,
        context={"arc_context": {"title": "T", "villain": "V", "stakes": "S",
                                 "act": {"title": "A", "hook": "H", "adventure_theme": "mine"},
                                 "act_number": 3, "acts_total": 3},
                 "town_context": {"name": "Hollowmere", "region_flavor": "fen", "npcs": ["Aud"]},
                 "quest_context": {"title": "Q", "text": "Do it."}})
    assert "PHASE 1 (party level 3)" in block and "PHASE 3 (party level 5)" in block
    assert "SCENARIO CONTEXT" in block and "FINALE" in block and "Hollowmere" in block
