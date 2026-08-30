"""Playtest amendments to §D17-5.4: one quest at a time, and the questgiver
answers an accept / a defer instead of the conversation ending cold."""

from __future__ import annotations

import copy

from ltg_game_server import scenario_content as sc
from ltg_game_server.scenario import (
    DEFAULT_ACCEPT_REPLY, DEFAULT_COMMITTED_LABEL, DEFAULT_COMMITTED_REPLY,
    DEFAULT_DEFER_REPLY, DEFAULT_SWORN_LABEL, ScenarioRun,
)

from tests.test_design_update_17_towns import arc_raw, materialization_raw, town_raw


def _second_giver_tree():
    """A second NPC with their own offer (the other quest option)."""
    return {"root": "r", "nodes": {
        "r": {"speaker": "npc", "text": "I have work, if you want it.",
              "choices": [
                  {"label": "We'll take the shore road.", 
                   "effects": [{"kind": "grant_quest", "quest": "the_shore_road"},
                               {"kind": "unlock_adventure"}]},
                  {"label": "Let us think on it.", "effects": [{"kind": "defer_quest"}]},
                  {"label": "Farewell."},
              ]}}}


def _run(mat=None):
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    m = mat or materialization_raw()
    run = ScenarioRun(town, arc, ["c"], [{"character": {"name": "Hero"}}], {})
    run.arrive(sc.validate_materialization(m, town, arc["acts"][0]))
    return run


def _labels(run):
    return [c["label"] for c in run.conversation.visible_choices(run.flags)]


def _pick(run, label):
    for c in run.conversation.visible_choices(run.flags):
        if c["label"] == label:
            return run.choose(c["index"])
    raise AssertionError(f"no choice {label!r} among {_labels(run)}")


def test_accept_gets_a_closing_line_when_the_tree_would_end():
    m = materialization_raw()
    m["dialogues"]["corwen"] = _second_giver_tree()
    m["accepted"] = {"corwen": "Good. Keep your feet dry out there."}
    run = _run(m)
    run.visit("the_salt_shrine")
    run.talk("corwen")
    fired = _pick(run, "We'll take the shore road.")
    assert {h["kind"] for h in fired} == {"grant_quest", "unlock_adventure"}
    assert run.conversation is not None and not run.conversation.over
    snap = run.conversation.snapshot(run.flags)
    assert snap["speaker"] == "npc" and snap["text"] == "Good. Keep your feet dry out there."
    assert [c["label"] for c in snap["choices"]] == ["Farewell."]
    assert not any(c["party_wide"] for c in snap["choices"])
    # The farewell ends it, firing nothing.
    assert run.choose(snap["choices"][0]["index"]) == []
    assert run.conversation is None
    # The act's own tree was not written into.
    assert set(run.act["dialogues"]["corwen"]["nodes"]) == {"r"}


def test_defer_gets_a_closing_line_and_the_defaults_apply():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    _pick(run, "Let us get back to you.")
    snap = run.conversation.snapshot(run.flags)
    assert snap["text"] == DEFAULT_DEFER_REPLY
    _pick(run, "Farewell.")
    assert run.conversation is None
    assert run.flags.get("deferred_sister_aud")


def test_an_authored_next_node_is_left_alone():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    _pick(run, "We'll walk the causeway at first light.")
    assert run.conversation.node_id == "go"     # the author's own reply
    assert run.conversation.snapshot(run.flags)["text"] == "Take this for the road."


def test_once_sworn_no_other_offer_can_be_accepted():
    m = materialization_raw()
    m["dialogues"]["corwen"] = _second_giver_tree()
    m["committed"] = {"corwen": "Then I'll find other hands."}
    run = _run(m)
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    _pick(run, "We'll walk the causeway at first light.")
    assert run.quest["status"] == "accepted" and run.committed
    run.end_conversation()
    # The other questgiver: the accept and the defer are gone; one refusal stands.
    run.talk("corwen")
    labels = _labels(run)
    assert "We'll take the shore road." not in labels
    assert "Let us think on it." not in labels
    assert set(labels) == {"Farewell.", DEFAULT_COMMITTED_LABEL}
    fired = _pick(run, DEFAULT_COMMITTED_LABEL)
    assert fired == []                           # no second quest, no second job
    assert run.quest["id"] == "the_lantern_goes_out"
    assert run.conversation.snapshot(run.flags)["text"] == "Then I'll find other hands."
    _pick(run, "Farewell.")
    assert run.conversation is None


def test_the_questgiver_you_swore_to_hears_a_reminder_not_a_refusal():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    _pick(run, "We'll walk the causeway at first light.")
    run.end_conversation()
    run.talk("sister_aud")
    labels = _labels(run)
    assert DEFAULT_SWORN_LABEL in labels
    assert DEFAULT_COMMITTED_LABEL not in labels
    assert not any(c["party_wide"] for c in run.conversation.visible_choices(run.flags))
    assert "Tell us more." in labels             # flavour choices survive
    # The same-quest accept deeper in the tree is rewritten too (the
    # narration-beat flavour choice survives, like every flavour choice).
    _pick(run, "Tell us more.")
    assert DEFAULT_SWORN_LABEL in _labels(run)
    assert "We'll look." not in _labels(run)
    assert _pick(run, DEFAULT_SWORN_LABEL) == []


def test_a_beaten_party_may_choose_again():
    run = _run()
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    _pick(run, "We'll walk the causeway at first light.")
    run.end_conversation()
    run.flags["defeated_once"] = True
    assert not run.committed
    run.talk("sister_aud")
    assert "We came back bloodied." in _labels(run)
    _pick(run, "We came back bloodied.")
    assert "Again." in _labels(run)


def test_committed_default_reply_and_the_maps_validate():
    m = materialization_raw()
    m["dialogues"]["corwen"] = _second_giver_tree()
    m["declined"] = {"nobody_here": "dropped", "corwen": "  Suit yourselves.  "}
    out = sc.validate_materialization(
        m, sc.validate_town(town_raw()), sc.validate_arc(arc_raw(), sc.validate_town(town_raw()))["acts"][0])
    assert out["declined"] == {"corwen": "Suit yourselves."}
    assert out["accepted"] == {} and out["committed"] == {}
    run = _run(copy.deepcopy(m))
    run.visit("the_salt_shrine")
    run.talk("sister_aud")
    _pick(run, "We'll walk the causeway at first light.")   # corwen offers the OTHER one
    assert run.conversation.snapshot(run.flags)["text"] == "Take this for the road."
    run.end_conversation()
    run.talk("corwen")
    _pick(run, DEFAULT_COMMITTED_LABEL)
    assert run.conversation.snapshot(run.flags)["text"] == DEFAULT_COMMITTED_REPLY
    assert DEFAULT_ACCEPT_REPLY  # exported
