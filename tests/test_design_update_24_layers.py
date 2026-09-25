"""Design Update 24 §D24-7 / §B.3 — the character layers: the brief validates
and round-trips through the Deckbuilder save; lore is selected by key match
and gate, capped at two entries and 120 words, and never reaches the arc
writer or the planner; the chronicle is written by the engine (fell / slew /
accepted / refused / met / bought / levelled); the writers' view is bounded
while the sheet's is full; `_party_block` keeps its line budget; the writers
never see `_`-prefixed flags."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ltg_core.schema import Brief, Character, Loadout
from ltg_deckbuilder import app as db_app
from ltg_game_server import content, llm, scenario_content as sc, world
from ltg_game_server.runs import RunManager
from ltg_game_server.scenario import ScenarioRun

from tests.test_design_update_10 import _adventure, _isolate  # noqa: F401 (fixture)
from tests.test_design_update_17_towns import arc_raw, materialization_raw, town_raw
from tests.test_design_update_24_campaign import _dirs, _play_act, _start  # noqa: F401 (fixture)


@pytest.fixture
def runs(tmp_path):
    return RunManager(root=tmp_path / "saves")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_app, "LOADOUT_DIR", tmp_path / "loadouts")
    return TestClient(db_app.app)


def brief_raw():
    return {"concept": "a kettle-priest turned road-warden",
            "appearance": "Broad, soot-marked, a brass ring on a cord.",
            "voice": {"register": "plain, slow, asks before he tells",
                      "samples": ["Hm.", "Say it again, slower.", "That'll do.", "TOO MANY"]},
            "wants": "the Kettle house rebuilt", "wont": "leave a debt unpaid",
            "tell": "counts coins twice", "ties": ["Lasarre — owes her his life", "the Order of the Kettle"]}


# --------------------------------------------------------------------------- #
# The brief (§D24-7.2)
# --------------------------------------------------------------------------- #
def test_the_brief_validates_and_round_trips_through_the_deckbuilder(db):
    ch = Character.model_validate({"name": "Bort", "colors": ["R"], "starting_mana": ["R"],
                                   "brief": brief_raw(), "brief_situation": "low on coin"})
    assert ch.brief.voice.samples == ["Hm.", "Say it again, slower.", "That'll do."]   # ≤ 3
    assert ch.brief.concept.startswith("a kettle") and ch.brief_situation == "low on coin"
    assert Brief().is_empty() and not ch.brief.is_empty()
    # No brief at all is fine — a hero with none plays exactly as today.
    assert Character.model_validate({"name": "Ys", "colors": ["U"], "starting_mana": ["U"]}).brief is None
    lo = {"ltg_version": "0.1", "character": {"name": "Bort", "colors": ["R"], "starting_mana": ["R"],
                                              "brief": brief_raw(), "brief_situation": "low on coin",
                                              "lore": "# The Kettle\nProse.", "combat_lore": "Swings from the shoulder."},
          "cards": []}
    res = db.post("/api/loadout/save", json={"loadout": lo})
    assert res.status_code == 200, res.text
    back = db.get("/api/loadout/bort").json()
    assert back["character"]["lore"] == "# The Kettle\nProse." and back["character"]["combat_lore"] == "Swings from the shoulder."
    assert back["character"]["brief"]["wants"] == "the Kettle house rebuilt"
    assert back["character"]["brief"]["ties"] == ["Lasarre — owes her his life", "the Order of the Kettle"]
    assert back["character"]["brief_situation"] == "low on coin"
    assert Loadout.model_validate(back).character.brief.tell == "counts coins twice"


def test_the_deckbuilder_lists_a_characters_lore_folder(db, tmp_path):
    folder = db_app.LOADOUT_DIR / "lore" / "bort"
    folder.mkdir(parents=True)
    (folder / "kettle.md").write_text("---\ntitle: The Order of the Kettle\nkeys: [kettle, brass ring]\nmode: closed\n---\nProse.\n")
    (folder / "notes.md").write_text("No front matter at all.\n")
    res = db.get("/api/lore/bort")
    assert res.status_code == 200
    body = res.json()
    assert body["folder"].endswith("lore/bort")
    assert [e["slug"] for e in body["entries"]] == ["kettle", "notes"]
    assert body["entries"][0]["title"] == "The Order of the Kettle" and body["entries"][0]["keys"] == ["kettle", "brass ring"]
    assert body["entries"][1]["title"] == "Notes" and body["entries"][1]["words"] == 5
    assert db.get("/api/lore/nobody").json()["entries"] == []


# --------------------------------------------------------------------------- #
# Lore (§D24-7.3)
# --------------------------------------------------------------------------- #
def _lore(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "LORE_DIR", tmp_path / "lore")
    folder = tmp_path / "lore" / "loadout_soren"
    folder.mkdir(parents=True)
    (folder / "kettle.md").write_text(
        "---\ntitle: The Order of the Kettle\nkeys: [salt shrine, priestess, kettle-priests]\nmode: closed\n---\n"
        + ("The Order kept the Salt Shrine before the priestesses did. " * 20) + "\n\nA second paragraph.\n")
    (folder / "reedking.md").write_text(
        "---\ntitle: The Reed-King's Debt\nkeys: [reed-king, causeway, black lake]\n---\nSoren owes the Reed-King a boat.\n")
    (folder / "gated.md").write_text(
        "---\ntitle: The Third Act\nkeys: []\ngate: act >= 3\n---\nOnly late in a story.\n")
    (folder / "met.md").write_text(
        "---\ntitle: Aud's Cousin\nkeys: []\ngate: met:sister_aud\n---\nShe is family.\n")
    (folder / "elsewhere.md").write_text(
        "---\ntitle: The Glass Desert\nkeys: [glass desert, sand-wyrm]\n---\nNothing here touches Hollowmere.\n")
    (folder / "open.md").write_text(
        "---\ntitle: A Seed\nkeys: [causeway]\nmode: open\n---\nSomething the game may resolve one day.\n")
    return folder


def test_select_lore_picks_by_key_match_and_gate_and_caps_the_size(tmp_path, monkeypatch):
    _lore(tmp_path, monkeypatch)
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    entries = content.lore_entries_for("loadout_soren")
    assert len(entries) == 6 and entries[0]["mode"] == "closed" and any(e["mode"] == "open" for e in entries)
    picked = content.select_lore(entries, town, arc, {}, act_index=0)
    titles = [p["title"] for p in picked]
    assert len(picked) == 2                                    # the cap
    assert "The Glass Desert" not in titles and "The Third Act" not in titles and "Aud's Cousin" not in titles
    # Most keys matched first: the Reed-King entry matches three keys, the
    # Kettle two; the open-mode seed (one) is squeezed out by the cap.
    assert titles == ["The Reed-King's Debt", "The Order of the Kettle"]
    assert picked[0]["keys_matched"] == ["reed-king", "causeway", "black lake"]
    assert "A Seed" not in titles
    # A long entry is cut to its first paragraph for the WRITER, never for the player.
    kettle = next(p for p in picked if p["title"] == "The Order of the Kettle")
    assert len(kettle["text"].split()) <= content.LORE_MAX_WORDS and "second paragraph" not in kettle["text"]
    assert "second paragraph" in next(e for e in entries if e["slug"] == "kettle")["text"]
    # Gates open the door: act ≥ 3, met:<npc>.
    late = content.select_lore(entries, town, arc, {"_met_sister_aud": True}, act_index=2, limit=6)
    assert {"The Third Act", "Aud's Cousin"} <= {p["title"] for p in late}
    assert "The Third Act" not in {p["title"] for p in content.select_lore(entries, town, arc, {}, act_index=1, limit=6)}
    # The party-wide selection keeps the cap across heroes and names the hero.
    rows = content.lore_in_play([{"id": "loadout_soren", "name": "Soren"}, {"id": "loadout_ys", "name": "Ys"}],
                                town, arc, {}, 0)
    assert len(rows) == 2 and all(r["hero"] == "Soren" for r in rows)


def test_lore_reaches_the_act_writer_but_never_the_arc_writer_or_planner(tmp_path, monkeypatch):
    _lore(tmp_path, monkeypatch)
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    members = [{"id": "loadout_soren", "name": "Soren", "level": 1, "colors": ["W"],
                "brief": {"concept": "a kettle-priest"}, "situation": "low on coin",
                "chronicle_recent": [], "chronicle_summaries": []}]
    state = {"members": members, "flags": {}, "knows": [], "gold": {}, "day": 3}
    lore = content.lore_in_play(members, town, arc, {}, 0)
    act = llm.act_prompt(town, arc, 0, state, lore=lore)
    assert "# LORE IN PLAY" in act and "The Reed-King's Debt" in act and "Colour a line, never a quest" in act
    assert "# THE PARTY" in act and "a kettle-priest" in act and "Now: low on coin" in act
    party = {"size": 1, "avg_level": 1, "members": [{"name": "Soren", "level": 1, "colors": ["W"]}]}
    arc_user = llm.arc_prompt(town, party, "standard", party_state=state)
    planner = llm.interlude_prompt(town, arc, [], state, None)
    for text in (arc_user, planner):
        assert "LORE" not in text and "Reed-King's Debt" not in text and "Order of the Kettle" not in text
        assert "# THE PARTY" in text


# --------------------------------------------------------------------------- #
# The chronicle (§D24-7.5) and the writers' view
# --------------------------------------------------------------------------- #
def test_chronicle_entries_come_from_play(runs):
    session, scen, run_id = _start(runs)
    # talk → met (once per NPC); grant_quest → accepted + refused.
    _play_act(session)
    kinds = [e["kind"] for e in scen.chronicle_of("loadout_soren")]
    assert "met" in kinds and "accepted" in kinds and "refused" in kinds and "slew" in kinds
    met = [e for e in scen.chronicle_of("loadout_soren") if e["kind"] == "met"]
    assert len(met) == len({e["text"] for e in met})            # once per NPC
    accepted = next(e for e in scen.chronicle_of("loadout_ys") if e["kind"] == "accepted")
    assert accepted == {"scenario": 1, "act": 1, "day": 1, "kind": "accepted", "text": 'Took on "Quest 1".'}
    refused = next(e for e in scen.chronicle_of("loadout_ys") if e["kind"] == "refused")
    assert refused["text"] == 'Turned down "Quest 1, the other way".'
    slew = next(e for e in scen.chronicle_of("loadout_soren") if e["kind"] == "slew")
    assert slew["text"].startswith("Slew ") and slew["act"] == 1 and slew["day"] == 2
    # A purchase.
    session.town_verb("c1", "visit", {"location_id": "tolls_forge"})
    stock = scen.act["stock"].get("tolls_forge") or []
    if stock:
        scen.gold["loadout_soren"] = 10_000
        session.economy_verb("c1", "buy", {"location_id": "tolls_forge", "item_id": stock[0]["id"],
                                           "character_id": "loadout_soren"})
        bought = [e for e in scen.chronicle_of("loadout_soren") if e["kind"] == "bought"]
        assert bought and bought[-1]["text"].startswith("Bought ")
        assert scen.act_logs[1]["items_bought"] and scen.act_logs[1]["gold_spent"]["tolls_forge"] > 0
    # A level-up: spending points until the level rises writes `levelled`.
    scen.spent["loadout_soren"] = 0
    levels_before = scen.levels()
    scen.earned["loadout_soren"] = 60
    scen.spent["loadout_soren"] = 60
    scen._sync_levels_into_loadouts()
    assert scen.levels()[0] > levels_before[0]
    # (the harvest path notes it — exercise it directly)
    scen.chronicle_add("loadout_soren", "levelled", f"Reached level {scen.levels()[0]}.")
    assert scen.chronicle_of("loadout_soren")[-1]["kind"] == "levelled"
    with pytest.raises(ValueError):
        scen.chronicle_add("loadout_soren", "sneezed", "x")


def test_a_fallen_hero_is_chronicled(runs):
    session, scen, run_id = _start(runs)
    from tests.test_design_update_17_scenario import _accept_quest
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    adv = session.adventure
    soren = adv.live_ids[0]
    for _ in range(len(adv.phases)):
        for c in session.state.party:
            if c.id == soren:
                c.hp = 0
        session.state.result = "victory"
        adv.on_state_change(session.state)
        session._run_hooks()
        if adv.complete:
            break
        for live in list(adv.live_ids):
            session.seats[live] = "c1"
            session.confirm_level_up("c1", live, {})
    from tests.test_design_update_17_scenario import _take_rewards
    _take_rewards(session)                     # the harvest writes the act log
    assert scen.act_logs[0]["fallen"] == ["Soren"]
    kinds = [e["kind"] for e in scen.chronicle_of("loadout_soren")]
    assert "fell" in kinds and "slew" not in kinds
    assert "slew" in [e["kind"] for e in scen.chronicle_of("loadout_ys")]


def test_the_writers_view_is_bounded_and_the_sheet_is_full(runs):
    session, scen, run_id = _start(runs)
    for i in range(25):
        scen.chronicle_add("loadout_soren", "met", f"Met person {i}.")
    scen.campaign["ledger"].append({"scenario": 0, "one_liner": "Long ago, a first scenario."})
    view = scen.chronicle_view("loadout_soren")
    assert len(view["recent"]) == 10 and view["recent"][-1]["text"] == "Met person 24."
    assert view["summaries"] == ["Long ago, a first scenario."]
    assert len(scen.chronicle_of("loadout_soren")) == 25
    sheet = scen.party_block()[0]
    assert len(sheet["chronicle"]) == 25 and sheet["situation"] == "low on coin, high on grudge"
    state = scen.party_state()
    assert len(state["members"][0]["chronicle_recent"]) == 10
    assert state["members"][0]["chronicle_summaries"] == ["Long ago, a first scenario."]


def test_party_state_hides_bookkeeping_flags_and_lists_knowledge(runs):
    session, scen, run_id = _start(runs)
    scen.flags.update({"_met_x": True, "_offered_q": True, "_shop_open": True,
                       "knows_orc_camp": True, "aud_blessed": True, "defeated_once": True})
    state = scen.party_state()
    assert state["flags"] == {"aud_blessed": True, "defeated_once": True}
    assert state["knows"] == ["knows_orc_camp"]
    # No brief: the concept defaults from the sheet's one-liner (§D24-7.2).
    assert state["day"] == 1 and state["members"][0]["concept"].startswith("A steadfast")
    town = scen.town
    prompt = llm.act_prompt(town, scen.arc, 0, state)
    assert "_met_x" not in prompt and "_shop_open" not in prompt and "_offered_q" not in prompt
    assert "Flags set: aud_blessed, defeated_once." in prompt
    assert "already knows of: orc camp" in prompt


def test_party_block_keeps_its_line_budget_for_four_heroes():
    members = []
    for i in range(4):
        members.append({"id": f"h{i}", "name": f"Hero {i}", "level": 3, "colors": ["W", "U"],
                        "brief": {**brief_raw(), "ties": [f"tie {j}" for j in range(8)]},
                        "situation": "word " * 80,
                        "chronicle_recent": [{"text": f"Did thing {j}."} for j in range(10)],
                        "chronicle_summaries": ["Scenario one.", "Scenario two."]})
    full = llm._party_block(members, depth="full", chronicle="recent")
    lines = [l for l in full.splitlines() if l.strip()]
    assert len(lines) == 1 + 4 * llm.PARTY_LINES_FULL
    assert "Did thing 9." in full and "Scenario two." in full and 'Says things like: "Hm."' in full
    summary = llm._party_block(members, depth="summary", chronicle="summaries")
    lines = [l for l in summary.splitlines() if l.strip()]
    assert len(lines) == 1 + 4 * llm.PARTY_LINES_SUMMARY
    assert "Did thing 9." not in summary and "Scenario two." in summary
    # The enemy designer sees the concept and nothing else of the layers.
    lo = {"character": {"name": "Bort", "level": 1, "colors": ["R"], "brief": brief_raw(),
                        "brief_situation": "secret"}}
    summary = llm.party_summary_from_loadouts([lo])
    assert summary["members"][0]["concept"] == "a kettle-priest turned road-warden"
    assert "situation" not in summary["members"][0] and "wants" not in str(summary)
    block = llm._request_block(summary, "standard", "")
    assert "kettle-priest" in block and "Kettle house" not in block


def test_the_ledger_block_and_the_world_block_render_for_the_writers(tmp_path, monkeypatch):
    monkeypatch.setattr(world, "WORLD_DIR", tmp_path / "world")
    world.append_entry({"town_id": "karzum", "name": "Karzum", "gist": "A pass-town.", "notable": ["Poppy"],
                        "new_region": {"id": "reach", "name": "The Reach", "gist": "High and cold."}})
    world.append_entry({"town_id": "nalindor", "name": "Nalindor", "gist": "A forest town.", "region_id": "reach",
                        "neighbours": [{"town_id": "karzum", "how": "three days north"}]})
    ctx = world.context_for("karzum")
    block = llm._world_block(ctx, neighbours=True)
    assert "# THE WORLD HERE" in block and "A pass-town." in block and "[nalindor] Nalindor — three days north" in block
    assert "Nalindor" not in llm._world_block(ctx, neighbours=False)
    ledger = [{"scenario": 1, "title": "One", "villain": "V1", "town_name": "Karzum", "outcome": "victory",
               "one_liner": "In Karzum the party defeated V1.",
               "acts": [{"act": 1, "title": "A", "accepted": {"title": "Q"}, "refused": [{"title": "R1"}],
                         "fallen": ["Bort"], "boss": "B", "adventure": "The Adit", "defeats": 0,
                         "met": [], "learned": [], "gold_spent": {}, "items_bought": []}]},
              {"scenario": 2, "title": "Two", "villain": "V2", "town_name": "Nalindor", "outcome": "in progress",
               "one_liner": "…", "acts": [{"act": 1, "title": "B", "accepted": None, "refused": [],
                                           "fallen": [], "boss": "", "adventure": "", "defeats": 2,
                                           "met": ["x"], "learned": ["the mill"], "gold_spent": {}, "items_bought": []}]}]
    text = llm._ledger_block(ledger)
    assert text.splitlines()[1] == '- Scenario 1: In Karzum the party defeated V1. Refused: "R1". Fell: Bort.'
    assert "Scenario 2 (in progress)" in text and "beaten back 2 times" in text and "Learned of: the mill" in text
    assert llm._ledger_block([]) == ""


# --------------------------------------------------------------------------- #
# Lore as a text field (owner's amendment after the first build): paragraphs
# are entries, keys are derived — no front matter anywhere.
# --------------------------------------------------------------------------- #
def test_lore_text_on_the_character_is_split_into_keyed_paragraphs(monkeypatch, tmp_path):
    monkeypatch.setattr(content, "LORE_DIR", tmp_path / "lore")
    text = ("# The Order of the Kettle\n"
            "The Order kept the Salt Shrine before the priestesses did. Sister Aud knows.\n\n"
            "Nothing here touches the world at all.\n\n"
            "# The Glass Desert\nA sand-wyrm took Soren's brother there.\n")
    rows = content.lore_text_entries("loadout_soren", text)
    assert [r["slug"] for r in rows] == ["lore_1_1", "lore_1_2", "lore_2_1"]
    assert rows[0]["title"] == "The Order of the Kettle" and rows[2]["title"] == "The Glass Desert"
    assert "salt shrine" in rows[0]["keys"] and "sister aud" in rows[0]["keys"]
    assert "nothing" not in rows[1]["keys"]                      # a sentence start is grammar
    assert rows[1]["keys"] == ["the order of the kettle", "order", "kettle"]
    # Through the registry: the file's `lore` field is what the writers read.
    live = content.loadout_for("loadout_soren")
    live["character"]["lore"] = text
    monkeypatch.setattr(content, "_character_registry",
                        lambda: {"loadout_soren": {"loadout": live, "meta": {}, "path": tmp_path / "x.json"}})
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    picked = content.select_lore(content.lore_entries_for("loadout_soren"), town, arc, {}, 0)
    assert [p["title"] for p in picked] == ["The Order of the Kettle"]     # the shrine is in town
    assert "Sister Aud" in picked[0]["text"] and "Glass Desert" not in str(picked)
    # The character file's lore / combat text is identity: it follows the file on load.
    inst = {"character": {"name": "Soren", "lore": "old", "combat_lore": "old"}, "cards": []}
    content.refresh_instance(inst, {"character": {"name": "Soren", "lore": text, "combat_lore": "fights like a smith"}, "cards": []})
    assert inst["character"]["combat_lore"] == "fights like a smith" and inst["character"]["lore"] == text


def test_generate_deck_flavour_writes_a_line_per_card(db, monkeypatch):
    from ltg_deckbuilder import flavour
    (db_app.LOADOUT_DIR).mkdir(parents=True, exist_ok=True)
    # A per-task model override (Options → LLM → Card Flavour) wins over the
    # settings' default model; api_key and the winning model ride the call.
    (db_app.LOADOUT_DIR / "llm_settings.json").write_text(json.dumps(
        {"api_key": "k", "model": "m", "task_models": {"flavour": "google/gemini-3.8-flash"}}))
    seen = {}

    def fake_chat(api_key, model, messages):
        seen["prompt"] = messages[-1]["content"]
        seen["api_key"] = api_key
        seen["model"] = model
        return json.dumps({"flavours": {"c1": "A kettle-flame gutters in his palm.", "c2": "He plants his feet.",
                                        "sk": "The ring swings.", "ul": "The forge-roar."}})

    monkeypatch.setattr(flavour, "chat", fake_chat)
    lo = {"ltg_version": "0.1",
          "character": {"name": "Bort", "colors": ["R"], "starting_mana": ["R"],
                        "brief": {"concept": "a kettle-priest"}, "combat_lore": "Fights like a smith.",
                        "skill": {"id": "sk", "name": "Ring Swing", "translated_text": "Deal 2."},
                        "ultimate": {"id": "ul", "name": "Forge-Roar", "translated_text": "Deal 6."}},
          "cards": [{"id": "c1", "name": "Ember Lash", "type": "Instant", "timing": "instant", "translated_text": "Deal 3."},
                    {"id": "c2", "name": "Shield Wall", "type": "Sorcery", "timing": "sorcery", "translated_text": "Defend."}]}
    res = db.post("/api/flavour/generate", json={"loadout": lo})
    assert res.status_code == 200, res.text
    assert res.json()["flavours"] == {"c1": "A kettle-flame gutters in his palm.", "c2": "He plants his feet.",
                                      "sk": "The ring swings.", "ul": "The forge-roar."}
    assert seen["api_key"] == "k" and seen["model"] == "google/gemini-3.8-flash"
    assert "# ABILITIES & COMBAT" in seen["prompt"] and "Fights like a smith." in seen["prompt"]
    assert "[c1] Ember Lash — Instant, instant: Deal 3." in seen["prompt"]
    assert "[ul] Forge-Roar — Ultimate" in seen["prompt"]
    # A reply missing a card is repaired through the loop; an empty deck is refused.
    replies = iter([json.dumps({"flavours": {"c1": "x"}}), json.dumps({"flavours": {"c1": "x", "c2": "y", "sk": "z", "ul": "w"}})])
    monkeypatch.setattr(flavour, "chat", lambda *a: next(replies))
    assert db.post("/api/flavour/generate", json={"loadout": lo}).json()["flavours"]["c2"] == "y"
    assert db.post("/api/flavour/generate", json={"loadout": {"character": {"name": "X"}, "cards": []}}).status_code == 422
