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
    """Two ways to take the same trouble, an out, and a bloodied-return branch."""
    return {
        "root": "greet",
        "nodes": {
            "greet": {"speaker": "npc", "text": "Boats go out and do not come back.",
                      "choices": [
                          {"label": "Tell us more.", "next": "more"},
                          {"label": "We'll walk the causeway at first light.", "next": "go",
                           "effects": [{"kind": "grant_quest", "quest": "the_lantern_goes_out"},
                                       {"kind": "unlock_adventure"}]},
                          {"label": "We'll go around by boat, after dark.", "next": "go",
                           "effects": [{"kind": "grant_quest", "quest": "the_shore_road"},
                                       {"kind": "unlock_adventure"}]},
                          {"label": "Let us get back to you.",
                           "effects": [{"kind": "defer_quest"}]},
                          {"label": "We came back bloodied.", "next": "bloodied",
                           "requires": ["defeated_once"]},
                      ]},
            "more": {"speaker": "npc", "text": "The old watchtower lights at night.",
                     "choices": [{"label": "We'll look.", "next": "go",
                                  "effects": [{"kind": "grant_quest", "quest": "the_lantern_goes_out"},
                                              {"kind": "unlock_adventure"}]},
                                 {"label": "Later — we've business first.",
                                  "effects": [{"kind": "defer_quest"}]}]},
            "bloodied": {"speaker": "npc", "text": "Then you know what waits. Will you go again?",
                         "choices": [{"label": "Again.", "next": "go",
                                      "effects": [{"kind": "grant_quest", "quest": "the_lantern_goes_out"},
                                                  {"kind": "unlock_adventure"}]},
                                     {"label": "Give us a day.",
                                      "effects": [{"kind": "defer_quest"}]}]},
            "go": {"speaker": "npc", "text": "Take this for the road.",
                   "choices": [{"label": "Farewell.", "effects": [{"kind": "give_gold", "amount": 10},
                                                                   {"kind": "set_flag", "flag": "aud_blessed"}]}]},
        },
    }


def materialization_raw():
    return {
        "quests": [
            {"id": "the_lantern_goes_out", "title": "The Lantern Goes Out",
             "text": "Find the boats. Light the tower.",
             "adventure_theme": "the sunken watchtower, taken along the causeway"},
            {"id": "the_shore_road", "title": "The Shore Road",
             "text": "Come at the tower from the water, after dark.",
             "adventure_theme": "the sunken watchtower, boarded from the reed-shore at night"},
        ],
        "arrival": "You come up the causeway at dusk; the lake is very still.",
        "dialogues": {
            "sister_aud": questgiver_tree(),
            "marra_quill": {"root": "r", "nodes": {"r": {"speaker": "npc", "text": "A room?",
                            "choices": [{"label": "Take a room.", "effects": [{"kind": "rest"}]},
                                        {"label": "Not yet."}]}}},
        },
        "flavor": {"bram_toll": "Steel's honest. Lakes aren't.",
                   "ysolde_vane": "Mind the lenses — they cost more than you do.",
                   "old_hesk": "Marsh-root for the fever, if you've the coin.",
                   "corwen": "I stood a watch on that causeway once.",
                   "sister_aud": "The lake keeps what it takes."},
        "topics": {"bram_toll": [{"ask": "Heard anything off the water?",
                                  "reply": "Only that the fishers have stopped going out past the reeds."}]},
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


def test_dialogue_accepts_narration_nodes_and_rejects_other_speakers():
    # A narration beat carries the context a line of dialogue would be clumsy
    # holding — it is a valid node, rendered without a nameplate.
    tree = questgiver_tree()
    tree["nodes"]["more"]["speaker"] = "narration"
    cleaned = dialogue.validate_dialogue(tree)
    assert cleaned["nodes"]["more"]["speaker"] == "narration"
    tree["nodes"]["more"]["speaker"] = "chorus"
    with pytest.raises(ValueError, match="npc, party, or narration"):
        dialogue.validate_dialogue(tree)


def test_materialization_offers_several_quests_each_acceptable():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = sc.validate_materialization(materialization_raw(), town, arc["acts"][0])
    assert [q["id"] for q in m["quests"]] == ["the_lantern_goes_out", "the_shore_road"]
    assert m["quest"]["title"] == "The Lantern Goes Out"     # legacy single view
    assert set(m["dialogues"]) == {"sister_aud", "marra_quill"}
    assert m["flavor"]["bram_toll"] == "Steel's honest. Lakes aren't."
    assert m["topics"]["bram_toll"][0]["ask"].startswith("Heard anything")
    # One offer is not a choice.
    bad = materialization_raw()
    bad["quests"] = bad["quests"][:1]
    with pytest.raises(ValueError, match="at least 2"):
        sc.validate_materialization(bad, town, arc["acts"][0])
    # An offer nobody can take.
    bad = materialization_raw()
    bad["quests"].append({"id": "the_third_way", "title": "The Third Way", "text": "Nobody offers this.",
                          "adventure_theme": "the eel-weirs south of the lake, waded at dawn"})
    with pytest.raises(ValueError, match="The Third Way"):
        sc.validate_materialization(bad, town, arc["acts"][0])
    # No acceptance at all.
    bad = materialization_raw()
    for node in bad["dialogues"]["sister_aud"]["nodes"].values():
        for ch in node["choices"]:
            ch.pop("effects", None)
    with pytest.raises(ValueError, match="no one in town offers"):
        sc.validate_materialization(bad, town, arc["acts"][0])


def test_every_offer_carries_a_way_to_defer_and_nobody_is_a_closed_door():
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    bad = materialization_raw()
    bad["dialogues"]["sister_aud"]["nodes"]["greet"]["choices"] = [
        ch for ch in bad["dialogues"]["sister_aud"]["nodes"]["greet"]["choices"]
        if "defer_quest" not in {h["kind"] for h in ch.get("effects", [])}]
    with pytest.raises(ValueError, match="put the answer off"):
        sc.validate_materialization(bad, town, arc["acts"][0])
    # An NPC with no tree, no topic of their own and no line this act.
    bad = materialization_raw()
    bad["flavor"].pop("old_hesk")
    with pytest.raises(ValueError, match="Old Hesk"):
        sc.validate_materialization(bad, town, arc["acts"][0])
    # …unless the town itself gave them something to say.
    raw = town_raw()
    raw["locations"][3]["npcs"][0]["topics"] = [
        {"ask": "What's in the black jars?", "reply": "Marsh-root. Don't touch them."}]
    with_topics = sc.validate_town(raw)
    m = sc.validate_materialization(bad, with_topics, arc["acts"][0])
    assert m["quests"]


def test_one_vendor_per_shop_and_topics_ride_on_the_npc():
    raw = town_raw()
    raw["locations"][1]["npcs"] = [_npc("Bram Toll", "smith"),
                                   {**_npc("Nessa Toll", "apprentice"), "vendor": True,
                                    "topics": [{"ask": "Whose forge is this?",
                                                "reply": "Mine, on the days he lets me sell."}]}]
    town = sc.validate_town(raw)
    forge = town["locations"][1]
    assert [n["vendor"] for n in forge["npcs"]] == [False, True]
    assert sc.vendor_of(forge)["name"] == "Nessa Toll"
    assert forge["npcs"][1]["topics"][0]["reply"].startswith("Mine")
    # Unmarked: the first resident keeps the counter; nobody at the shrine sells.
    raw = town_raw()
    town = sc.validate_town(raw)
    assert sc.vendor_of(town["locations"][1])["name"] == "Bram Toll"
    assert sc.vendor_of(town["locations"][4]) is None
    assert all(not n["vendor"] for n in town["locations"][4]["npcs"])


def test_a_location_takes_more_than_two_residents():
    raw = town_raw()
    raw["locations"][4]["npcs"] = [_npc("Sister Aud", "priestess"), _npc("Corwen", "veteran"),
                                   _npc("Little Pel", "candle-child"), _npc("Hob", "digger")]
    town = sc.validate_town(raw)
    assert len(town["locations"][4]["npcs"]) == 4
    raw["locations"][4]["npcs"].append(_npc("One Too Many", "loiterer"))
    with pytest.raises(ValueError, match="resident NPCs"):
        sc.validate_town(raw)


def test_conversation_walker_filters_on_flags_and_returns_hooks():
    tree = dialogue.validate_dialogue(questgiver_tree())
    conv = dialogue.Conversation("sister_aud", tree)
    vis = conv.visible_choices({})
    assert [c["label"] for c in vis] == [
        "Tell us more.", "We'll walk the causeway at first light.",
        "We'll go around by boat, after dark.", "Let us get back to you."]
    assert vis[1]["party_wide"] is True and vis[0]["party_wide"] is False
    vis2 = conv.visible_choices({"defeated_once": True})
    assert "We came back bloodied." in [c["label"] for c in vis2]
    with pytest.raises(ValueError, match="not available"):
        conv.choose(4, {})  # the bloodied branch is hidden without the flag
    hooks = conv.choose(1, {})
    assert [h["kind"] for h in hooks] == ["grant_quest", "unlock_adventure"]
    assert hooks[0]["quest"] == "the_lantern_goes_out"
    assert conv.node_id == "go" and not conv.over
    hooks = conv.choose(0, {})
    assert [h["kind"] for h in hooks] == ["give_gold", "set_flag"] and hooks[0]["amount"] == 10
    assert conv.over and conv.snapshot({})["over"] is True


def test_conversation_transcript_records_every_line_and_choice():
    """The chat-style transcript (playtest, 2026-08): every node shown plus each
    choice taken reaches the snapshot, so a player who didn't pick — or joined
    the conversation late — still sees the whole exchange."""
    tree = dialogue.validate_dialogue(questgiver_tree())
    conv = dialogue.Conversation("sister_aud", tree)
    root_text = conv.node["text"]
    conv.choose(1, {})
    go_text = conv.node["text"]
    lines = conv.snapshot({})["lines"]
    assert [(l["speaker"], l["text"]) for l in lines] == [
        (tree["nodes"][tree["root"]]["speaker"], root_text),
        ("choice", "We'll walk the causeway at first light."),
        (conv.node["speaker"], go_text),
    ]
    conv.choose(0, {})
    lines = conv.snapshot({})["lines"]
    assert lines[-1]["speaker"] == "choice"   # the tree ended — the final pick closes it
    assert len(lines) == 4


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
    # §D17-2.3: phases budget for the level the party's EARNED points can have
    # reached — a level-3 party (60 earned) is 70 / 90 by Phases II / III, a
    # fraction of a level up, not a level a phase.
    assert "PHASE 1 (party level 3)" in block and "PHASE 3 (party level 4)" in block
    assert "PHASE 3 (party level 5)" not in block
    assert "SCENARIO CONTEXT" in block and "FINALE" in block and "Hollowmere" in block
