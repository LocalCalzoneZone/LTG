"""Design Update 24 §D24-6 / §B.4 — instanced mechanics, live identity: on
every load of a campaign each hero's instanced loadout is refreshed from the
character file (deck, skill/ultimate, colours, keyword, description, brief,
portrait, animations), keeps its progression (HP, mana, cards, Power, points,
level, gear), reconciles the starting mana with notices; a missing character
file is a no-op."""

from __future__ import annotations

import copy
import json

import pytest

from ltg_game_server import content
from ltg_game_server.runs import RunManager

from tests.test_design_update_10 import _adventure, _isolate  # noqa: F401 (fixture)
from tests.test_design_update_24_campaign import _dirs, _play_act, _start  # noqa: F401 (fixture)


@pytest.fixture
def runs(tmp_path):
    return RunManager(root=tmp_path / "saves")


def _instance():
    return {"ltg_version": "0.1",
            "character": {"name": "Bort", "description": "old", "portrait": "/art/old.png",
                          "colors": ["R", "U"], "starting_mana": ["R", "U", "U"],
                          "hp": 16, "starting_cards": 3, "power_bought": 2, "keyword": "reach",
                          "attack_mode": "melee", "row": "front",
                          "earned_points": 60, "spent_points": 42, "level": 2,
                          "skill": {"id": "old_skill"}, "ultimate": None,
                          "animations": [{"id": "a1"}], "types": ["dwarf"], "classes": []},
            "cards": [{"name": "Ember Lash"}, {"name": "Shield Wall"}],
            "gear": {"primary": {"id": "sword"}, "belt": []}}


def _live():
    return {"ltg_version": "0.1",
            "character": {"name": "Bort", "description": "new", "portrait": "/art/new.png",
                          "colors": ["R", "G"], "starting_mana": ["R"],
                          "hp": 8, "starting_cards": 1, "power_bought": 0, "keyword": None,
                          "attack_mode": "ranged", "row": "rear",
                          "earned_points": 0, "spent_points": 0, "level": 1,
                          "skill": {"id": "new_skill"}, "ultimate": {"id": "ult"},
                          "animations": [], "types": ["dwarf", "beast"], "classes": ["smith"],
                          "brief": {"concept": "a smith"}, "brief_situation": "broke"},
            "cards": [{"name": "Shield Wall"}, {"name": "Green Fuse"}]}


def test_refresh_instance_replaces_identity_and_keeps_progression():
    inst = _instance()
    notices = content.refresh_instance(inst, _live())
    ch = inst["character"]
    # Replaced from the file.
    assert [c["name"] for c in inst["cards"]] == ["Shield Wall", "Green Fuse"]
    assert ch["skill"] == {"id": "new_skill"} and ch["ultimate"] == {"id": "ult"}
    assert ch["colors"] == ["R", "G"] and ch["keyword"] is None
    assert ch["description"] == "new" and ch["portrait"] == "/art/new.png" and ch["animations"] == []
    assert ch["brief"] == {"concept": "a smith"} and ch["brief_situation"] == "broke"
    assert ch["attack_mode"] == "ranged" and ch["row"] == "rear" and ch["classes"] == ["smith"]
    # Kept from the instance.
    assert ch["hp"] == 16 and ch["starting_cards"] == 3 and ch["power_bought"] == 2
    assert ch["earned_points"] == 60 and ch["spent_points"] == 42 and ch["level"] == 2
    assert inst["gear"] == {"primary": {"id": "sword"}, "belt": []}
    # Reconciled: the U pips became live colours (round-robin R/G), with a notice.
    assert ch["starting_mana"] == ["R", "R", "G"]
    assert any("starting mana was re-rolled" in n for n in notices)
    assert any("lost *Ember Lash*" in n and "gained *Green Fuse*" in n for n in notices)


def test_refresh_instance_is_quiet_when_nothing_changed_and_a_noop_without_a_file():
    inst = _instance()
    same = copy.deepcopy(inst)
    same["character"]["hp"] = 8      # progression on the file is ignored either way
    assert content.refresh_instance(inst, same) == []
    assert inst["character"]["hp"] == 16
    before = copy.deepcopy(inst)
    assert content.refresh_instance(inst, None) == []
    assert inst == before


def test_a_campaign_load_refreshes_every_hero_from_the_character_file(runs, monkeypatch):
    session, scen, run_id = _start(runs)
    _play_act(session)                                    # 60 earned, gear, gold
    gold = dict(scen.gold)
    earned = dict(scen.earned)
    # The character file changes underneath the campaign: a card removed,
    # a colour swapped, a brief written.
    live = content.loadout_for("loadout_soren")
    live["cards"] = live["cards"][1:]
    dropped = content.loadout_for("loadout_soren")["cards"][0]["name"]
    live["character"]["brief"] = {"concept": "a lantern-bearer"}
    live["character"]["description"] = "rewritten in the Deckbuilder"
    monkeypatch.setattr(content, "loadout_for",
                        lambda cid, _live=live: copy.deepcopy(_live) if cid == "loadout_soren" else None)
    save = runs.newest_save(run_id)
    scen2 = runs.load_scenario_save(run_id, save["save_id"])
    soren = scen2.loadouts[0]
    assert len(soren["cards"]) == len(live["cards"])
    assert soren["character"]["brief"] == {"concept": "a lantern-bearer"}
    assert soren["character"]["description"] == "rewritten in the Deckbuilder"
    # Level, gear and purse are the campaign's.
    assert scen2.gold == gold and scen2.earned == earned
    assert soren["character"]["earned_points"] == earned["loadout_soren"]
    assert soren.get("gear") == scen.loadouts[0].get("gear")
    # The notice names the card and rides the town snapshot for the splash.
    assert any(dropped in n for n in scen2.notices)
    assert scen2.town_snapshot()["notices"] == scen2.notices
    scen2.dismiss_notices()
    assert scen2.town_snapshot()["notices"] == []
    # Ys's file is "gone": her instance is untouched, silently.
    assert scen2.loadouts[1]["cards"] == scen.loadouts[1]["cards"]
    # The enemy designer's summary reads the live concept.
    from ltg_game_server import llm
    assert llm.party_summary_from_loadouts(scen2.loadouts)["members"][0]["concept"] == "a lantern-bearer"
