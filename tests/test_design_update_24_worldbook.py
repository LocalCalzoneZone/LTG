"""Design Update 24 §D24-8.3 / §B.6 — the worldbook: append-only entries with
symmetric neighbours, regions named once, `save_town` writing the entry beside
the town, the town generator's `# WORLD` block, and an idempotent backfill."""

from __future__ import annotations

import json

import pytest

from ltg_game_server import llm, scenario_content as sc, world

from tests.test_design_update_17_towns import _isolate_dirs, town_raw  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def _world_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(world, "WORLD_DIR", tmp_path / "world")


def _entry(town_id, name=None, region="kholdrun_reach", neighbours=None, new_region=None):
    e = {"town_id": town_id, "name": name or town_id.title(),
         "gist": f"{name or town_id.title()} is a town a traveller has heard of.",
         "notable": ["someone", "somewhere"],
         "neighbours": neighbours or [], "added_by": "import"}
    if new_region:
        e["new_region"] = new_region
    else:
        e["region_id"] = region
    return e


def test_append_entry_founds_the_region_and_writes_reverse_edges():
    world.append_entry(_entry("karzum", "Karzum",
                              new_region={"id": "kholdrun_reach", "name": "The Kholdrun Reach",
                                          "gist": "High cold passes."}))
    assert [r["id"] for r in world.regions()] == ["kholdrun_reach"]
    world.append_entry(_entry("nalindor", "Nalindor",
                              neighbours=[{"town_id": "karzum", "how": "three days north by the Greatway"}]))
    # The edge was written on the NEWER town and mirrored onto the older one.
    assert world.entry_for("nalindor")["neighbours"] == [{"town_id": "karzum", "how": "three days north by the Greatway"}]
    assert world.entry_for("karzum")["neighbours"] == [{"town_id": "nalindor", "how": "three days north by the Greatway"}]
    assert [n["town_id"] for n in world.neighbours_of("karzum")] == ["nalindor"]
    assert world.neighbours_of("karzum")[0]["how"].startswith("three days")
    # A region is named once: founding it again keeps the first gist.
    world.append_entry(_entry("azure", "Azure",
                              new_region={"id": "kholdrun_reach", "name": "X", "gist": "Y"}))
    assert world.region_for("kholdrun_reach")["gist"] == "High cold passes."


def test_append_entry_refuses_silent_overwrite_and_unknown_neighbours():
    world.append_entry(_entry("karzum", new_region={"id": "r", "name": "R", "gist": "g"}))
    with pytest.raises(ValueError, match="already has an entry"):
        world.append_entry(_entry("karzum"))
    forced = world.append_entry({**_entry("karzum"), "gist": "Rewritten by hand."}, force=True)
    assert forced["gist"] == "Rewritten by hand." and world.entry_for("karzum")["gist"] == "Rewritten by hand."
    with pytest.raises(ValueError, match="not a town in the worldbook"):
        world.append_entry(_entry("millhaven", neighbours=[{"town_id": "atlantis", "how": "by sea"}]))


def test_validate_entry_needs_a_gist_and_a_region_and_bounds_the_lists():
    with pytest.raises(ValueError, match="gist"):
        world.validate_entry({"town_id": "x", "region_id": "r"})
    with pytest.raises(ValueError, match="region"):
        world.validate_entry({"town_id": "x", "gist": "g"})
    e = world.validate_entry({"town_id": "x", "region_id": "r", "gist": "g " * 400,
                              "notable": [f"n{i}" for i in range(20)],
                              "neighbours": [{"town_id": f"t{i}"} for i in range(10)]})
    assert len(e["gist"].split()) == world.MAX_GIST_WORDS
    assert len(e["notable"]) == world.MAX_NOTABLE and len(e["neighbours"]) == world.MAX_NEIGHBOURS


def test_save_town_writes_the_entry_beside_the_town():
    meta = sc.save_town(town_raw("Bellhollow"),
                        world_entry={"new_region": {"id": "the_fens", "name": "The Fens", "gist": "Wet."},
                                     "gist": "A bell-foundry town on the fen edge.", "notable": ["the foundry"]})
    assert sc.town_detail(meta["id"]) is not None
    entry = world.entry_for("bellhollow")
    assert entry and entry["name"] == "Bellhollow" and entry["region_id"] == "the_fens"
    # Saving the town again (the editor) never rewrites the book's page.
    sc.save_town(town_raw("Bellhollow"), meta["id"],
                 world_entry={"region_id": "the_fens", "gist": "Changed."})
    assert world.entry_for("bellhollow")["gist"] == "A bell-foundry town on the fen edge."
    # The overview flags a town with no page as a warning row, not an error.
    sc.save_town(town_raw("Quietmere"))
    ov = world.overview()
    assert [m["id"] for m in ov["missing"]] == ["quietmere"]
    assert ov["regions"][0]["id"] == "the_fens" and ov["regions"][0]["towns"][0]["town_id"] == "bellhollow"


def test_the_town_generator_is_placed_with_a_world_block():
    world.append_entry(_entry("karzum", "Karzum",
                              new_region={"id": "kholdrun_reach", "name": "The Kholdrun Reach",
                                          "gist": "High cold passes."}))
    world.append_entry(_entry("nalindor", "Nalindor", neighbours=[{"town_id": "karzum", "how": "north"}]))
    ctx = world.placement_context("karzum")
    assert ctx["region"]["id"] == "kholdrun_reach"
    assert [n["town_id"] for n in ctx["neighbours"]] == ["karzum", "nalindor"]
    prompt = llm.town_prompt("a mill town", ctx, seed={"name": "Millhaven", "line": "forty windmills"})
    assert "# WORLD" in prompt and "[kholdrun_reach] The Kholdrun Reach" in prompt
    assert "[karzum] Karzum" in prompt and "[nalindor] Nalindor" in prompt
    assert "# THE SEED" in prompt and "Millhaven" in prompt and "forty windmills" in prompt
    # No anchor: the writer is told to found a region.
    empty = llm.town_prompt("", world.placement_context())
    assert "FOUND a new region" in empty
    assert "# WORLD" in llm.TOWN_INSTRUCTIONS or "world_entry" in llm.TOWN_INSTRUCTIONS


def test_generate_town_writes_town_and_entry_in_one_call(monkeypatch):
    world.append_entry(_entry("karzum", "Karzum",
                              new_region={"id": "kholdrun_reach", "name": "The Kholdrun Reach",
                                          "gist": "High cold passes."}))
    reply = {**town_raw("Bellhollow"),
             "world_entry": {"region_id": "kholdrun_reach", "gist": "A bell town.",
                             "notable": ["the foundry"],
                             "neighbours": [{"town_id": "karzum", "how": "two days east"}]}}
    calls = []

    def fake_chat(api_key, model, messages, max_tokens=None, timeout=None):
        calls.append(messages[-1]["content"])
        return json.dumps(reply)

    monkeypatch.setattr(llm, "load_settings", lambda: {**llm._default_settings(), "api_key": "k", "model": "m"})
    monkeypatch.setattr(llm, "_chat", fake_chat)
    meta = llm.generate_town("a bell town", world_ctx=world.placement_context("karzum"))
    assert meta["id"] == "bellhollow" and "# WORLD" in calls[0]
    entry = world.entry_for("bellhollow")
    assert entry["region_id"] == "kholdrun_reach" and entry["added_by"] == "generate_town"
    assert world.entry_for("karzum")["neighbours"] == [{"town_id": "bellhollow", "how": "two days east"}]
    # A reply without the entry is rejected and repaired through the loop.
    bad = {**town_raw("Quietmere")}
    replies = iter([json.dumps(bad), json.dumps({**bad, "world_entry": {"region_id": "kholdrun_reach", "gist": "q"}})])
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: next(replies))
    llm.generate_town("quiet", world_ctx=world.placement_context("karzum"))
    assert world.entry_for("quietmere") is not None


def test_backfill_is_idempotent(monkeypatch):
    from scripts import backfill_worldbook as bf
    sc.save_town(town_raw("Karzum"))
    sc.save_town(town_raw("Nalindor"))
    n_calls = {"n": 0}

    def fake_chat(api_key, model, messages, max_tokens=None, timeout=None):
        n_calls["n"] += 1
        return json.dumps({"world_entry": {
            "new_region": {"id": "r", "name": "R", "gist": "g"},
            "gist": "Backfilled.", "notable": ["x"], "neighbours": []}})

    monkeypatch.setattr(llm, "load_settings", lambda: {**llm._default_settings(), "api_key": "k", "model": "m"})
    monkeypatch.setattr(llm, "_chat", fake_chat)
    bf.backfill(["karzum", "nalindor"])
    assert n_calls["n"] == 2
    assert {e["town_id"] for e in world.list_entries()} == {"karzum", "nalindor"}
    assert world.entry_for("karzum")["added_by"] == "backfill"
    bf.backfill(["karzum", "nalindor"])      # nothing to do the second time
    assert n_calls["n"] == 2
