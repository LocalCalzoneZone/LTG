"""The "made at" difficulty flag: generation stamps it (llm.py), the save gate
round-trips it, edits that omit it inherit the stored value, and the pickers'
meta carries it. Display only — never a rules input."""

from __future__ import annotations

import pytest

from ltg_game_server import content


@pytest.fixture
def loadouts(tmp_path, monkeypatch):
    d = tmp_path / "loadouts"
    c = tmp_path / "content"
    monkeypatch.setattr(content, "LOADOUTS_DIR", d)
    monkeypatch.setattr(content, "CONTENT_DIR", c)
    monkeypatch.setattr(content, "_SCAN_DIRS", [c, d])
    monkeypatch.setattr(content, "HIDDEN_FILE", d / "hidden.json")
    monkeypatch.setattr(content, "ENCOUNTER_HIDDEN_FILE", d / "encounters_hidden.json")
    return d


ENC = {
    "name": "Stamped Fight",
    "difficulty": "hard",
    "enemies": [
        {"id": "ghoul", "name": "Ghoul", "hp": 4, "level": 1, "power": 1},
    ],
}


def test_difficulty_persists_and_reaches_meta(loadouts):
    meta = content.save_encounter(dict(ENC))
    assert meta["difficulty"] == "hard"
    assert content.encounter_detail(meta["id"])["difficulty"] == "hard"


def test_difficulty_survives_an_edit_that_omits_it(loadouts):
    eid = content.save_encounter(dict(ENC))["id"]
    edit = {k: v for k, v in ENC.items() if k != "difficulty"}
    edit["name"] = "Stamped Fight (edited)"
    content.save_encounter(edit, eid)
    assert content.encounter_detail(eid)["difficulty"] == "hard"


def test_hand_authored_content_stays_unstamped(loadouts):
    enc = {k: v for k, v in ENC.items() if k != "difficulty"}
    meta = content.save_encounter(dict(enc))
    assert meta["difficulty"] == ""
    assert content.encounter_detail(meta["id"])["difficulty"] == ""
