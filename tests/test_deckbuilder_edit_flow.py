"""The Options → Characters → Edit flow, deckbuilder side: /api/loadout/{name}
falls back to bundled examples (read-only), and /api/loadout/update-game writes
the engine-ready loadout (validated cards only) over the ORIGINAL character file
— even when the character was renamed — so the game updates in place."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ltg_deckbuilder import app as db_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_app, "LOADOUT_DIR", tmp_path)
    return TestClient(db_app.app)


def _loadout(name="Testa", validated=True):
    return {
        "ltg_version": "0.1",
        "character": {"name": name, "colors": ["U"], "starting_mana": ["U"],
                      "level": 1},
        "cards": [{
            "id": "opt", "name": "Opt", "source_name": "Opt", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 1, "target": {"mode": "self"}}],
            "validated": validated,
        }],
    }


def test_load_falls_back_to_examples(client):
    # loadout_mira lives only in repo /examples — the edit flow must still open it.
    res = client.get("/api/loadout/loadout_mira")
    assert res.status_code == 200
    assert res.json()["character"]["name"]


def test_load_unknown_is_404(client):
    assert client.get("/api/loadout/no_such_character").status_code == 404


def test_update_game_writes_original_id_even_after_rename(client, tmp_path):
    # Editing game character "old_hero", renamed to "Shinyname" in the builder:
    # the file must stay old_hero.json (the game id), with the new name inside.
    res = client.post("/api/loadout/update-game",
                      json={"name": "old_hero", "loadout": _loadout(name="Shinyname")})
    assert res.status_code == 200
    body = res.json()
    assert body["updated"] == "old_hero" and body["exported_count"] == 1
    on_disk = json.loads((tmp_path / "old_hero.json").read_text())
    assert on_disk["character"]["name"] == "Shinyname"
    assert on_disk["character"]["stats"]          # engine-ready: resolved stats
    assert all(c["validated"] for c in on_disk["cards"])


def test_update_game_omits_unvalidated_cards(client, tmp_path):
    lo = _loadout()
    lo["cards"].append({**lo["cards"][0], "id": "draft", "name": "Draft",
                        "validated": False})
    res = client.post("/api/loadout/update-game", json={"name": "hero", "loadout": lo})
    assert res.status_code == 200
    body = res.json()
    assert body["exported_count"] == 1
    assert [o["name"] for o in body["omitted"]] == ["Draft"]
    on_disk = json.loads((tmp_path / "hero.json").read_text())
    assert [c["id"] for c in on_disk["cards"]] == ["opt"]


def test_update_game_refuses_empty(client):
    res = client.post("/api/loadout/update-game",
                      json={"name": "hero", "loadout": _loadout(validated=False)})
    assert res.status_code == 422
