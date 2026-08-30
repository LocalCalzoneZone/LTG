"""Beta-playtest fixes to town dialogue legibility (2026-08-30):

1. The NPC card follows the party — the persona the player saw on the portrait
   goes into the journal at first conversation, because the dialogue leans on
   its facts (the splinted arm, the eleven diggers) and the card is otherwise
   gone the moment the talk button is pressed.
2. Quest offers are journaled the moment the party SEES them — an "Available
   quest" entry per option, so the choice is reviewable and an offer heard once
   in dialogue is never lost.
3. The narration floor: a generated dialogue tree of 4+ nodes needs narration
   beats (two for the questgiver) — dialogue that only speaks reads as a chat
   log, and every physical fact stays invisible.
"""

from __future__ import annotations

import copy

import pytest

from ltg_game_server import scenario_content as sc
from ltg_game_server.scenario import ScenarioRun
from tests.test_design_update_17_towns import (arc_raw, materialization_raw,
                                               questgiver_tree, town_raw)


def _run(mat=None):
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = mat or materialization_raw()
    run = ScenarioRun(town, arc, ["c"], [{"character": {"name": "Hero"}}], {})
    run.arrive(sc.validate_materialization(m, town, arc["acts"][0]))
    return run


def _entries(run, kind):
    return [e for e in run.journal if e["kind"] == kind]


# --------------------------------------------------------------------------- #
# 1. The card follows the party
# --------------------------------------------------------------------------- #
def test_first_talk_journals_the_persona_card():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    met = _entries(run, "met")
    assert len(met) == 1
    e = met[0]
    assert e["speaker"] == "Sister Aud"
    town = sc.validate_town(town_raw())
    persona = sc.find_npc(town, "sister_aud")[1]["persona"]
    assert persona in e["text"]                     # the card text, verbatim
    assert "Sister Aud" in e["text"]


def test_the_card_is_journaled_once_not_per_conversation():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    run.end_conversation()
    run.talk("sister_aud")
    assert len(_entries(run, "met")) == 1


# --------------------------------------------------------------------------- #
# 2. Offers seen are offers journaled
# --------------------------------------------------------------------------- #
def test_seeing_an_offer_node_journals_each_option():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")                          # the root carries both accepts
    offered = _entries(run, "quest_offered")
    assert len(offered) == 2
    texts = " | ".join(e["text"] for e in offered)
    assert 'Available quest — "The Lantern Goes Out"' in texts
    assert 'Available quest — "The Shore Road"' in texts
    assert "Find the boats. Light the tower." in texts      # the journal text
    assert "Sister Aud" in texts                            # who, and where
    assert run.quest["status"] == "offered"


def test_offers_are_journaled_once_across_visits():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    run.end_conversation()
    run.talk("sister_aud")
    assert len(_entries(run, "quest_offered")) == 2


def test_a_gated_offer_waits_for_its_flag():
    """An offer behind `requires` is journaled only when it becomes VISIBLE."""
    m = materialization_raw()
    tree = m["dialogues"]["sister_aud"]
    for node in tree["nodes"].values():
        for ch in node["choices"]:
            if any(h.get("kind") == "grant_quest"
                   and h.get("quest") == "the_shore_road"
                   for h in ch.get("effects", [])):
                ch["requires"] = ["knows_shore"]
    # make the gate reachable so validation accepts it
    tree["nodes"]["more"]["choices"][0].setdefault("effects", []).append(
        {"kind": "set_flag", "flag": "knows_shore"})
    run = _run(m)
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    texts = " | ".join(e["text"] for e in _entries(run, "quest_offered"))
    assert "The Lantern Goes Out" in texts
    assert "The Shore Road" not in texts            # gated: not yet seen
    run.flags["knows_shore"] = True
    run.end_conversation()
    run.talk("sister_aud")
    texts = " | ".join(e["text"] for e in _entries(run, "quest_offered"))
    assert "The Shore Road" in texts                # visible now — journaled


# --------------------------------------------------------------------------- #
# 3. The narration floor
# --------------------------------------------------------------------------- #
def _mat_with_tree(tree):
    m = materialization_raw()
    m["dialogues"]["sister_aud"] = tree
    return m


def test_a_speech_only_questgiver_tree_is_rejected():
    tree = copy.deepcopy(questgiver_tree())
    for node in tree["nodes"].values():
        if node["speaker"] == "narration":
            node["speaker"] = "npc"
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    with pytest.raises(ValueError, match="narration"):
        sc.validate_materialization(_mat_with_tree(tree), town, arc["acts"][0])


def test_one_beat_is_not_enough_for_the_questgiver():
    tree = copy.deepcopy(questgiver_tree())
    flipped = False
    for node in tree["nodes"].values():
        if node["speaker"] == "narration" and not flipped:
            node["speaker"] = "npc"
            flipped = True
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    with pytest.raises(ValueError, match="at least 2"):
        sc.validate_materialization(_mat_with_tree(tree), town, arc["acts"][0])


def test_small_greeting_trees_may_be_all_voice():
    """The innkeeper's one-node 'A room?' tree carries no beats and passes."""
    run = _run()                                    # materialization_raw validates
    assert run.act is not None


def test_offer_suffix_is_dropped_when_the_text_names_the_asker():
    """We-voice quest text opens with its asker; the runtime must not append
    "(offered by the same person, again)"."""
    m = materialization_raw()
    m["quests"][0]["text"] = ("Sister Aud at the Salt Shrine has asked us to "
                              "find the missing boats and light the tower "
                              "before another crew rows out blind.")
    run = _run(m)
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    entries = _entries(run, "quest_offered")
    lantern = next(e for e in entries if "The Lantern Goes Out" in e["text"])
    assert "has asked us" in lantern["text"]
    assert "(offered by" not in lantern["text"]          # she is already named
    shore = next(e for e in entries if "The Shore Road" in e["text"])
    assert "(offered by Sister Aud" in shore["text"]     # this one still needs it


def test_accept_entry_speaks_in_the_partys_voice():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    for c in run.conversation.visible_choices(run.flags):
        if c["label"] == "We'll walk the causeway at first light.":
            run.choose(c["index"])
            break
    quest = _entries(run, "quest")
    assert quest and quest[-1]["text"].startswith('We took on')


def test_the_prompt_writes_quests_as_the_partys_journal():
    from ltg_game_server import llm
    D = llm.ACT_INSTRUCTIONS
    for needle in ("AS THE PARTY'S OWN JOURNAL ENTRY", 'first person plural ("we", "us")',
                   "a ledger line is not a journal", "Yorrin Dagg"):
        assert needle in D, needle


def test_the_prompt_teaches_the_floor_and_the_standalone_rule():
    from ltg_game_server import llm
    D = llm.ACT_INSTRUCTIONS
    for needle in ("NARRATION IS REQUIRED", "at least TWO narration nodes",
                   "THE DIALOGUE STANDS ALONE", "briefing, not the player's",
                   "like a novel, not a transcript",
                   "treasure-hunters\" is illegal until"):
        assert needle in D, needle
