"""Design Update 17 §D17-4 / §D17-5.3 / §D17-5.5 — the economy: items and the
catalogue, template × affix rolls, gear composition into the stat block,
consumables as always-in-hand activated-ability cards, rewards, shops,
selling and trading, effective level."""

from __future__ import annotations

import random

import pytest

from ltg_core.schema import BELT_SIZE, INVENTORY_GEAR, Item
from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import compose_spec, state_from_dict
from ltg_game_server import content, items, loot, scenario_content as sc
from ltg_game_server.runs import RunManager
from ltg_game_server.session import SessionManager

from tests.test_design_update_10 import _adventure, _isolate  # noqa: F401
from tests.test_design_update_17_scenario import (_accept_quest, _confirm_act_end_level_up,
                                                   _drive, _fake_materializer,
                                                   _win_adventure)
from tests.test_design_update_17_towns import arc_raw, town_raw
from ltg_game_server.scenario import ScenarioRun


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TOWNS_DIR", tmp_path / "towns")
    monkeypatch.setattr(sc, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(sc, "TOWN_HIDDEN_FILE", tmp_path / "th.json")
    monkeypatch.setattr(sc, "SCENARIO_HIDDEN_FILE", tmp_path / "sh.json")
    monkeypatch.setattr(items, "USER_ITEMS_DIR", tmp_path / "equipment")
    monkeypatch.setattr(items, "ITEM_HIDDEN_FILE", tmp_path / "ih.json")


def test_base_catalogue_ships_t82():
    metas = items.list_items()
    by_slot = {}
    for m in metas:
        by_slot.setdefault(m["slot"], []).append(m)
    # T-82's floor, and then the expanded shelf vendors draw stock from: at
    # least three times the shipped 16, spread across the three slots.
    assert len(by_slot["weapon"]) >= 6 and len(by_slot["accessory"]) >= 4 and len(by_slot["consumable"]) >= 6
    assert len(metas) >= 48
    assert all(len(v) >= 15 for v in by_slot.values())
    # Every catalogue entry is a legal, priced, describable template.
    for m in metas:
        it = items.get_item(m["id"])
        assert it is not None and it.template is None
        assert it.art_desc and it.flavor and items.describe(it)
        assert it.points_price >= 0 and it.level_min >= 1
    keen = items.get_item("keen_falchion")
    assert keen.points_price == 15 and items.summarize(keen) == "melee weapon · +1 Power"
    flask = items.get_item("pilgrims_flask")
    assert flask.statics[0].kind == "ability" and flask.statics[0].card.name == "Pilgrim's Sip"
    draught = items.get_item("marsh_draught")
    card = draught.as_card("soren_")
    assert card.consumable_id == "marsh_draught" and card.timing.value == "sorcery" and card.cost.generic == 0
    # A consumable is played AS a card, so its card FACE must read as one: the
    # item has no authored prose, so the face renders its effects, and it
    # carries the item's art into the card's art frame.
    from ltg_combat.serialize import card_dict
    view = card_dict(card)
    assert view["text"] and view["text"] == items._consumable_text(draught)
    assert view["image"] == draught.art_url


def test_user_item_save_and_delete_shadows_catalogue():
    meta = items.save_item({"name": "Test Charm", "slot": "accessory", "points_price": 12,
                            "statics": [{"kind": "stat", "stat": "hp", "amount": 2}]})
    assert meta["id"] == "test_charm" and meta["source"] == "user"
    assert items.get_item("test_charm").points_price == 12
    with pytest.raises(Exception):
        items.save_item({"name": "Bad", "slot": "accessory", "statics": [{"kind": "power_bonus", "amount": 1}]})
    items.delete_item("test_charm")
    assert items.get_item("test_charm") is None


def test_rolls_stay_on_vocabulary_and_budget():
    rng = random.Random(3)
    for _ in range(40):
        it = items.roll_item(rng, "weapon", tier=5, boss=True)
        assert isinstance(it, Item) and it.template
        # Price = template + affixes (+ premium): never below the template's.
        base = items.get_item(it.template)
        assert it.points_price >= base.points_price
        for a in it.affixes:
            assert any(x["id"] == a for x in items.AFFIXES)
    stock = items.roll_stock("weaponsmith", tier=6, seed=1)
    assert stock and all(x.rarity in ("common", "uncommon") for x in stock)
    assert all(not any(a in ("warded", "venomed", "unbroken", "blighted") for a in x.affixes) for x in stock)
    # A merchant draws COMMON/UNCOMMON templates too — never a rare one relabelled.
    assert all(items.get_item(x.template).rarity in ("common", "uncommon") for x in stock)
    assert items.roll_stock("inn", 3) == []


def test_act_rewards_are_forged_from_the_scenarios_lexicon_not_the_shelf():
    """§D17-4.5: a boss's spoils are pieced together from the verbiage drawn
    when the scenario was made — never picked off the catalogue."""
    town = {"name": "Millhaven", "region_flavor": "a salt harbour town of nets and tide"}
    arc = {"title": "The Black Sail", "villain": "a drowned captain",
           "stakes": "the fishing fleet", "acts": []}
    lex = loot.build_lexicon(town, arc)
    assert lex["theme"] == "salt" and lex["forms"]["melee"] and lex["materials"]
    # Deterministic: the same arc always draws the same words.
    assert loot.build_lexicon(town, arc) == lex

    catalogue = {m["id"] for m in items.list_items()}
    names = {m["name"] for m in items.list_items()}
    drops = loot.forge_drops(2, tier=4, lexicon=lex, seed=7)
    assert len([d for d in drops if d.slot != "consumable"]) == 3      # party + 1
    assert len([d for d in drops if d.slot == "consumable"]) == 4      # party × 2
    for d in drops:
        assert d.template is None and d.id not in catalogue and d.name not in names
        assert d.id.startswith("forged_")
        assert d.flavor and d.art_desc and items.describe(d)
        assert d.points_price > 0
        if d.slot == "consumable":
            assert d.effects and d.as_card("x_").cost.generic == 0
        else:
            assert d.statics
        # On-vocabulary: every affix it took is a table affix (a consumable's
        # is its recipe id), and gear affixes are priced ones.
        for a in d.affixes:
            assert (any(x["id"] == a for x in loot.AFFIXES)
                    or any(r["id"] == a for r in loot.CONSUMABLE_RECIPES))
    # The same seed forges the same spoils (a reload is not a different world).
    assert [d.name for d in loot.forge_drops(2, tier=4, lexicon=lex, seed=7)] == [d.name for d in drops]
    # A different scenario speaks differently.
    other = loot.build_lexicon({"name": "Ashkiln", "region_flavor": "a kiln town of cinder and smoke"},
                               {"title": "The Long Burning", "villain": "a fire-priest",
                                "stakes": "the kilns", "acts": []})
    assert other["theme"] == "ash"
    assert {d.name for d in loot.forge_drops(2, tier=4, lexicon=other, seed=7)} != {d.name for d in drops}
    # Banned-creation keywords arrive HERE and never in stock (§D17-4.1).
    banned = set()
    for s in range(40):
        for d in loot.forge_drops(2, tier=6, lexicon=lex, seed=s):
            banned |= {st.keyword for st in d.statics if st.kind == "keyword"}
    assert banned & {"hexproof", "deathtouch", "indestructible", "infect"}


def test_gear_helpers_capacity_equip_swap():
    lo = {"character": {"name": "X"}}
    sword = items.get_item("keen_falchion").model_dump(mode="json")
    bow = items.get_item("siege_bow").model_dump(mode="json")
    belt_item = items.get_item("quick_salve").model_dump(mode="json")
    items.add_item(lo, sword)
    items.equip(lo, "keen_falchion", "primary")
    assert items.gear_of(lo)["primary"]["id"] == "keen_falchion"
    items.add_item(lo, bow)
    items.equip(lo, "siege_bow", "primary")            # swap: falchion back to inventory
    g = items.gear_of(lo)
    assert g["primary"]["id"] == "siege_bow" and [x["id"] for x in g["inventory"]["gear"]] == ["keen_falchion"]
    with pytest.raises(ValueError, match="accessory"):
        items.equip(lo, "keen_falchion", "accessory")
    for i in range(BELT_SIZE + 2):
        items.add_item(lo, {**belt_item, "id": f"salve_{i}"})
    g = items.gear_of(lo)
    assert len(g["belt"]) == BELT_SIZE and len(g["inventory"]["consumables"]) == 2
    with pytest.raises(ValueError, match="belt is full"):
        items.to_belt(lo, "salve_3")
    items.from_belt(lo, "salve_0")
    items.to_belt(lo, "salve_3")
    assert [x["id"] for x in items.gear_of(lo)["belt"]] == ["salve_1", "salve_2", "salve_3"]
    for i in range(INVENTORY_GEAR):
        try:
            items.add_item(lo, {**bow, "id": f"bow_{i}"})
        except ValueError:
            break
    with pytest.raises(ValueError, match="no room"):
        items.add_item(lo, {**bow, "id": "one_more"})
    assert items.worn_points(lo) == 30 and items.effective_level_bonus(lo) == 1
    items.consume_used(lo, ["salve_1"])
    assert [x["id"] for x in items.gear_of(lo)["belt"]] == ["salve_2", "salve_3"]


def test_compose_folds_gear_and_deals_consumables():
    lo = content.loadout_for("loadout_soren")
    lo["gear"] = items.empty_gear()
    lo["gear"]["primary"] = items.get_item("siege_bow").model_dump(mode="json")        # ranged +1 trample
    lo["gear"]["secondary"] = items.get_item("keen_falchion").model_dump(mode="json")  # mode/power ignored
    lo["gear"]["accessory"] = items.get_item("pilgrims_flask").model_dump(mode="json")  # grants a card
    lo["gear"]["belt"] = [items.get_item("quick_salve").model_dump(mode="json"),
                          items.get_item("hush_powder").model_dump(mode="json")]
    plain = compose_spec([content.loadout_for("loadout_soren")], content.encounter_for("builtin_a"))
    spec = compose_spec([lo], content.encounter_for("builtin_a"))
    p0, p1 = plain["party"][0], spec["party"][0]
    assert p1["attack_mode"] == "ranged"
    # Base power follows the mode (melee 2 → ranged 1) then +1 from the primary.
    assert p1["power"] == p0["power"] - 1 + 1
    assert "trample" in p1["keywords"]
    assert len(p1["opening_extras"]) == 3
    st = state_from_dict(spec, seed=1)
    c = st.party[0]
    extras = [k for k in c.hand if k.consumable_id or k.granted_by]
    assert len(extras) == 3 and len(c.hand) == c.hand_size + 3
    # Drink the salve: no mana, stacks as an ABILITY, the card is exiled.
    st.phase = "player"; st.priority = c.id
    acts = legal_actions(st)
    drink = next((a for a in acts if a.kind == "cast" and a.card_id and "consumable_quick_salve" in a.card_id), None)
    assert drink is not None
    st2, _ = apply_action(st, drink)
    top = st2.stack[-1]
    assert top.kind == "ability" and top.label == "Quick Salve"
    c2 = st2.character(c.id)
    assert any(k.consumable_id == "quick_salve" for k in c2.exile)
    assert not any(k.consumable_id == "quick_salve" for k in c2.hand + c2.graveyard)
    assert any("uses Quick Salve" in e.msg for e in st2.log)


@pytest.fixture
def runs(tmp_path):
    return RunManager(root=tmp_path / "saves")


def _start(runs, options=None):
    town = sc.validate_town(town_raw())
    arc = sc.validate_arc(arc_raw(), town)
    loadouts = content.loadouts_for(["loadout_soren", "loadout_ys"])
    scen = ScenarioRun(town, arc, ["loadout_soren", "loadout_ys"], loadouts,
                       options or {"difficulty": "standard"}, town_id="hollowmere")
    scen.materializer = _fake_materializer
    meta = runs.create_scenario_run(scen, name="Econ")
    session = SessionManager().create(None, run_id=meta["run_id"], run_manager=runs, scenario=scen)
    session.async_hook = lambda s, kind: _drive(s, kind)
    session.scenario_enter_town(None)
    session.materialize_act()
    session.clients["c1"] = object()
    return session, scen, meta["run_id"]


def test_stock_rolls_per_act_and_shop_buy_sell_trade(runs):
    session, scen, run_id = _start(runs)
    stock = scen.act["stock"]
    assert set(stock) >= {"tolls_forge", "the_brass_eye", "reedwife_s"}
    assert all(it["rarity"] in ("common", "uncommon") for loc in stock.values() for it in loc)
    scen.gold["loadout_soren"] = 100
    session.town_verb("c1", "visit", {"location_id": "tolls_forge"})
    snap = session.snapshot_for("c1")
    assert snap["shop"]["function"] == "weaponsmith" and snap["shop"]["stock"]
    first = snap["shop"]["stock"][0]
    session.town_verb("c1", "buy", {"location_id": "tolls_forge", "item_id": first["id"], "character_id": "loadout_soren"})
    assert scen.gold["loadout_soren"] == 100 - first["buy_price"]
    lo = scen.loadouts[0]
    assert items.gear_of(lo)["inventory"]["gear"][0]["id"] == first["id"]
    assert first["id"] not in [x["id"] for x in scen.act["stock"]["tolls_forge"]]
    # Equip it, check the sheet, sell it back at 50%.
    session.town_verb("c1", "equip", {"character_id": "loadout_soren", "item_id": first["id"], "slot": "primary"})
    sheet = session.snapshot_for("c1")["party_sheet"][0]
    assert sheet["gear"]["primary"]["id"] == first["id"] and sheet["worn_points"] == first["points_price"]
    session.town_verb("c1", "sell", {"character_id": "loadout_soren", "item_id": first["id"]})
    assert items.gear_of(scen.loadouts[0])["primary"] is None
    assert scen.gold["loadout_soren"] == 100 - first["buy_price"] + int(first["points_price"] * 0.5)
    # Trade gold to Ys (same client → immediate).
    session.town_verb("c1", "give", {"character_id": "loadout_soren", "to": "loadout_ys", "gold": 10})
    assert scen.gold["loadout_ys"] == 10
    second = scen.act["stock"]["tolls_forge"][0]
    scen.gold["loadout_ys"] = 0
    with pytest.raises(ValueError, match="not enough"):
        session.town_verb("c1", "buy", {"location_id": "tolls_forge", "item_id": second["id"], "character_id": "loadout_ys"})


def test_rewards_gate_after_phase_three(runs):
    session, scen, run_id = _start(runs)
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    _win_adventure(session)
    # The finale is won but the run holds at the Rewards modal: still in the
    # fight's session, victory suppressed, drops rolled (T-83).
    assert scen.rewards is not None and session.state is not None and scen.mode == "adventure"
    assert session.public_result() is None
    snap = session.snapshot_for("c1")
    rv = snap["rewards"]
    gear = [i for i in rv["items"] if i["slot"] != "consumable"]
    cons = [i for i in rv["items"] if i["slot"] == "consumable"]
    assert len(gear) == 3 and len(cons) == 4
    with pytest.raises(ValueError, match="assign every reward"):
        session.economy_verb("c1", "reward_accept", {})
    for i in range(len(rv["items"])):
        target = "loadout_soren" if i % 2 == 0 else "loadout_ys"
        if not rv["room"][str(i)][target]:
            target = "discard"
        session.economy_verb("c1", "reward_assign", {"index": i, "target": target})
    session.economy_verb("c1", "reward_accept", {})   # one client → runs at once
    # The spoils are placed, and the act-end level-up screen is what is queued
    # behind them (§D17-2.3): still in the adventure, victory still suppressed.
    assert scen.rewards is None and scen.act_wrapup == "levelup"
    assert scen.mode == "adventure" and session.public_result() is None
    assert session.adventure is not None and session.adventure.is_final_gate
    lu = session.snapshot_for("c1")["adventure"]["level_up"]
    assert lu["kind"] == "levelup" and lu["final"] is True
    assert _confirm_act_end_level_up(session)
    # Items landed, the finale transitioned, and the party is in town for Act II.
    assert scen.act_wrapup is None and scen.mode == "town" and scen.act_index == 1
    lo = scen.loadouts[0]
    assert items.all_items(lo)
    kinds = [s["kind"] for s in runs.run_detail(run_id)["saves"]]
    assert "rewards" in kinds and kinds[-1] == "act_start"
    # A belt consumable is dealt into the next adventure's opening hand.
    belt = items.gear_of(lo)["belt"]
    if belt:
        _accept_quest(session)
        session.town_verb("c1", "leave", {})
        session.town_verb("c1", "start_adventure", {})
        c = session.state.party[0]
        assert any(k.consumable_id for k in c.hand)


def test_effective_level_reads_worn_points(runs):
    session, scen, run_id = _start(runs)
    lo = scen.loadouts[0]
    items.add_item(lo, items.get_item("siege_bow").model_dump(mode="json"))
    items.equip(lo, "siege_bow", "primary")
    assert items.worn_points(lo) == 30
    # Party of two: (1 + 1) + (1 + 0) → average 1.5 → floor 1; both geared → 2.
    assert scen.effective_level() == 1
    lo2 = scen.loadouts[1]
    items.add_item(lo2, items.get_item("siege_bow").model_dump(mode="json"))
    items.equip(lo2, "siege_bow", "primary")
    assert scen.effective_level() == 2


def test_spoils_are_frozen_on_arrival_and_their_art_can_be_painted_early(runs, tmp_path, monkeypatch):
    """§D17-4.5: the act forges its spoils when the party ARRIVES in town — not
    when the boss falls — so the art queue has the whole act to paint them."""
    from ltg_game_server import art

    session, scen, run_id = _start(runs)
    frozen = scen.act["spoils"]
    assert len(frozen) == 3 + 4                      # (party + 1) gear, (party × 2) consumables
    assert all(r["id"].startswith("forged_") for r in frozen)
    # Boss tier: a step above the tier the act's merchants sell at.
    assert scen.spoils_tier() == scen.act_tier() + 1

    # The spoils art queue paints run art into the loadouts space — never into
    # the tracked catalogue — and writes the URL back onto the frozen act.
    monkeypatch.setattr(art, "SPOILS_ROOT", tmp_path / "art")
    painted = []

    def _fake_paint(prompt, aspect, folder, slot, root=None):
        painted.append(folder)
        d = (root or art.ART_DIR) / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "item-abcd.png").write_bytes(b"x")
        return f"/art/{folder}/item-abcd.png"

    monkeypatch.setattr(art, "paint", _fake_paint)
    queued = art.spoil_art_items(scen.spoils(), scen.set_spoil_art)
    assert len(queued) == len(frozen)
    for q in queued:
        q["paint"]()
    assert all(r["art_url"] for r in scen.act["spoils"])
    assert all(f.startswith("spoils/forged_") for f in painted)
    assert (tmp_path / "art" / "spoils").is_dir()      # run art, not the tracked catalogue

    # A requeue adopts what is on disk instead of repainting it.
    for r in scen.act["spoils"]:
        r.pop("art_url")
    assert art.spoil_art_items(scen.spoils(), scen.set_spoil_art) == []
    assert all(r["art_url"] for r in scen.act["spoils"])

    # The Rewards modal shows exactly those spoils, art and all.
    _accept_quest(session)
    session.town_verb("c1", "leave", {})
    session.town_verb("c1", "start_adventure", {})
    _win_adventure(session)
    rv = session.snapshot_for("c1")["rewards"]
    assert [i["id"] for i in rv["items"]] == [r["id"] for r in frozen]
    assert all(i["art_url"] for i in rv["items"])
