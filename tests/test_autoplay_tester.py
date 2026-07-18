"""Design Update 13 — the Autoplay Tester: gauntlets, probes, verdicts.

Headless coverage of the playtest lab: the frozen baseline gauntlet loads and
every fixture builds/plays at every size; the paired-ablation spine is
deterministic and statistically sane; a deliberately broken card flags OVER
and runs the lever ladder; heroic and character probes work; the enemy-schema
attribution reads the generation vocabulary; quarantine/promotion respects the
game's picker."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import ltg_autoplay_tester.probes as probes
from ltg_autoplay_tester import enemy_analysis, gauntlets
from ltg_combat.autoplay import make_policy, run_one
from ltg_combat.autoplay.runner import prepare_scenario
from ltg_combat.scenario import compose_spec, state_from_dict

REPO = Path(__file__).resolve().parents[1]

# A tiny preset so the suite stays fast: few seeds, a short ladder.
probes.PRESETS["test-tiny"] = {
    "seeds": 4, "difficulties": ["standard"], "sizes": [1],
    "pressures": (0.8, 1.2, 1.6), "loo_sweep": False,
}
# The sensitivity preset: one synthetic fixture under a FINE ladder, so a
# card's threshold shift registers cleanly (the real presets use the same
# instrument at 0.1 resolution over the full baseline).
probes.PRESETS["test-fine"] = {
    "seeds": 2, "difficulties": ["standard"], "sizes": [1],
    "pressures": tuple(round(0.6 + 0.1 * i, 1) for i in range(15)),
    "loo_sweep": False,
}


def _synthetic_gauntlet():
    """One plain duel whose breaking point sits inside the test ladder."""
    fx = {"name": "Probe Target", "_file": "probe_target.json",
          "enemies": [{"id": "golem", "name": "Golem", "hp": 10, "level": 2,
                       "power": 2, "row": "front", "attack_mode": "melee"}]}
    return {"id": "synthetic", "name": "synthetic", "hash": "synthetic",
            "frozen": False, "generated": False, "encounters": [fx],
            "adventure": None, "sparring_partner": None}


@pytest.fixture(scope="module")
def baseline():
    return gauntlets.load_gauntlet("baseline-1")


@pytest.fixture(scope="module")
def soren():
    return json.loads(
        (REPO / "apps/deckbuilder/loadouts/soren.json").read_text())


_CH_ENEMY = {"mode": "chosen", "side": "enemy", "targeted": True}


def _test_card(cid, name, timing, cost, effects):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": 1, "type": "Sorcery" if timing == "sorcery" else "Instant",
            "timing": timing, "cost": cost, "effects": effects,
            "validated": True}


def _probe_deck(soren, subject_card):
    """A compact 4-card deck around the subject, so every seed actually draws
    it (a 20-card library buries a card in most short duels — draw dilution is
    real play, but the sensitivity TEST wants the card on camera)."""
    lo = copy.deepcopy(soren)
    lo["character"]["name"] = "Probe Dummy"
    lo["cards"] = [subject_card,
                   _test_card("jab", "Jab", "sorcery", {"generic": 1},
                              [{"kind": "deal_damage", "amount": 2,
                                "target": _CH_ENEMY}]),
                   _test_card("mend2", "Mend", "instant", {"colors": {"W": 1}},
                              [{"kind": "heal", "amount": 3,
                                "target": {"mode": "self"}}]),
                   _test_card("jab2", "Second Jab", "sorcery", {"generic": 1},
                              [{"kind": "deal_damage", "amount": 2,
                                "target": _CH_ENEMY}])]
    return lo


def _broken_deck(soren):
    """A compact deck around one blatantly overpowered card."""
    return _probe_deck(soren, _test_card(
        "sunder_test", "Sunder", "instant", {"colors": {"W": 1}},
        [{"kind": "deal_damage", "amount": 9, "target": _CH_ENEMY}]))


def _small(gauntlet, n=2):
    return {**gauntlet, "encounters": gauntlet["encounters"][:n]}


# ========================================================================== #
# §D13-2 — the baseline gauntlet
# ========================================================================== #
def test_baseline_gauntlet_loads_and_hashes(baseline):
    assert len(baseline["encounters"]) == 8
    assert baseline["frozen"] is True
    assert baseline["adventure"] and len(baseline["adventure"]["acts"]) == 3
    assert baseline["sparring_partner"]["character"]["name"] == "Sparring Partner"
    # The hash is stable across loads and part of every verdict's context.
    again = gauntlets.load_gauntlet("baseline-1")
    assert again["hash"] == baseline["hash"]
    assert baseline["id"] in {g["id"] for g in gauntlets.list_gauntlets()}
    assert gauntlets.baseline_gauntlet_id() == "baseline-2"


def test_every_fixture_builds_and_plays_at_every_size(baseline, soren):
    partner = baseline["sparring_partner"]
    p = make_policy("greedy")
    for enc in baseline["encounters"]:
        for size in (1, 2, 3, 4):
            party = ([soren] + [partner] * 3)[:size]
            spec = compose_spec(party, prepare_scenario(enc, size))
            state_from_dict(spec)  # the engine gate
        rec = run_one(compose_spec([soren], prepare_scenario(enc, 1)),
                      p, seed=0)
        assert rec["result"] in ("victory", "defeat")


def test_objective_fixtures_carry_their_objectives(baseline):
    by_file = {e["_file"]: e for e in baseline["encounters"]}
    assert by_file["07_last_palisade.json"]["objective"]["kind"] == "survive"
    assert by_file["08_summoning_circle.json"]["objective"]["kind"] == "race"


def test_promotion_is_the_only_exit_from_quarantine(tmp_path, monkeypatch):
    # A fabricated generated gauntlet in a temp dir: it never appears in the
    # game's registry until promoted through the normal gate.
    from ltg_game_server import content
    gdir = tmp_path / "gen-test"
    gdir.mkdir()
    enc = {"name": "ZZ Promotion Probe", "enemies": [
        {"id": "wisp", "name": "Wisp", "hp": 3, "level": 1, "power": 1}]}
    (gdir / "01_probe.json").write_text(json.dumps(enc))
    (gdir / "manifest.json").write_text(json.dumps({
        "name": "gen-test", "generated": True, "encounters": ["01_probe.json"]}))
    monkeypatch.setattr(gauntlets, "GAUNTLET_DIR", tmp_path)
    listed = {g["id"] for g in gauntlets.list_gauntlets()}
    assert "gen-test" in listed
    assert "zz_promotion_probe" not in {e["id"] for e in content.list_encounters()}
    try:
        meta = gauntlets.promote_encounter("gen-test", "01_probe.json")
        assert meta["id"] in {e["id"] for e in content.list_encounters()}
    finally:
        content.delete_encounter("zz_promotion_probe")
        hidden = content._enc_hidden()
        hidden.discard("zz_promotion_probe")
        content._set_enc_hidden(hidden)


# ========================================================================== #
# §D13-1.1 — the paired spine
# ========================================================================== #
def test_paired_stats_math():
    def rec(key, win):
        return {"pair_key": key, "result": "victory" if win else "defeat"}
    a = [rec([1], True), rec([2], True), rec([3], False), rec([4], True)]
    b = [rec([1], True), rec([2], False), rec([3], False), rec([4], False)]
    s = probes.paired_stats(a, b)
    assert s["n"] == 4
    assert s["delta_pp"] == 50.0            # A wins 3/4, B wins 1/4
    assert s["discordant"] == [2, 0]
    assert s["se_pp"] > 0


def test_variant_builders(soren):
    card_id = soren["cards"][1]["id"]        # an instant
    abl = probes.ablate_card(soren, card_id)
    ids = [c["id"] for c in abl["cards"]]
    assert card_id not in ids and "filler_practice_swing" in ids
    assert len(abl["cards"]) == len(soren["cards"])

    levers = dict(probes.lever_variants(soren, card_id))
    assert "cost +1 generic" in levers and "cost +2 generic" in levers
    assert "instant → sorcery" in levers      # the card is an instant
    plus1 = next(c for c in levers["cost +1 generic"]["cards"]
                 if c["id"] == card_id)
    base = next(c for c in soren["cards"] if c["id"] == card_id)
    assert plus1["cost"].get("generic", 0) == base["cost"].get("generic", 0) + 1
    sorc = next(c for c in levers["instant → sorcery"]["cards"]
                if c["id"] == card_id)
    assert sorc["timing"] == "sorcery"

    with pytest.raises(ValueError):
        probes.ablate_card(soren, "not_a_card")


def test_combo_blind_detection(soren):
    combo_card = {"effects": [{"kind": "amplify", "event": "any_damage",
                               "multiplier": 2}]}
    assert probes._card_is_combo(combo_card)
    assert not probes._card_is_combo({"effects": [
        {"kind": "deal_damage", "amount": 2}]})


# ========================================================================== #
# §D13-1.2 — the card probe
# ========================================================================== #
def test_card_probe_flags_the_broken_card_and_is_deterministic(soren):
    lo = _broken_deck(soren)
    g = _synthetic_gauntlet()
    v1 = probes.probe_card(lo, "sunder_test", g, "test-fine")
    v2 = probes.probe_card(lo, "sunder_test", g, "test-fine")
    for key in ("flag", "marginal", "ladder", "screening", "cells"):
        assert v1[key] == v2[key]
    # A 9-damage 1-mana nuke shifts the duel's breaking point several rungs.
    assert v1["flag"] == "OVER"
    assert v1["marginal"]["delta_pp"] > probes.OVER_PP
    assert v1["policy_version"] == "greedy-1.2.0"
    assert v1["screening_only"] is True      # quick-tier preset
    assert [r["lever"] for r in v1["ladder"]][:2] == [
        "cost +1 generic", "cost +2 generic"]
    assert v1["recommendation"]


def test_card_probe_fair_card_reads_in_band(soren):
    # The control: a card identical to the filler (different id) — its
    # ablation swaps like for like, so the marginal is exactly zero.
    fair = dict(probes.FILLER_CARD, id="fair_copy", name="Fair Copy",
                source_name="Fair Copy")
    lo = _probe_deck(soren, fair)
    v = probes.probe_card(lo, "fair_copy", _synthetic_gauntlet(), "test-fine")
    assert v["flag"] in ("IN_BAND", "UNDER")
    assert abs(v["marginal"]["delta_pp"]) < 1e-9
    assert v["ladder"] == []
    # Screening covers the whole deck.
    assert len(v["screening"]) == len(lo["cards"])


# ========================================================================== #
# §D13-1.3 — the heroic probe
# ========================================================================== #
def test_heroic_probe_ultimate(baseline, soren):
    if not soren["character"].get("ultimate"):
        pytest.skip("reference loadout has no ultimate")
    v = probes.probe_heroic(soren, "ultimate", _small(baseline, 2), "test-tiny")
    assert v["kind"] == "ultimate"
    assert v["ultimate_dependence"] is None or 0 <= v["ultimate_dependence"] <= 1
    assert v["recommendation"]
    without = probes.remove_heroic(soren, "ultimate")
    assert without["character"]["ultimate"] is None
    with pytest.raises(ValueError):
        probes.probe_heroic(without, "ultimate", _small(baseline, 2), "test-tiny")


# ========================================================================== #
# §D13-1.4 — the character probe
# ========================================================================== #
def test_character_probe_percentile_heroics_and_spend_audit(baseline, soren):
    g = _small(baseline, 2)
    g["adventure"] = baseline["adventure"]
    roster = [soren, baseline["sparring_partner"]]
    v = probes.probe_character(soren, roster, g, "test-tiny")
    assert v["kind"] == "character"
    assert set(v["roster_rates"]) == {"soren", "sparring_partner"}
    assert v["percentile"] is not None
    # Attribution carries denominators so waste reads as a share.
    solo = v["attribution"]["solo"]
    assert {"damage_dealt", "mana_granted", "mana_wasted", "cards_cast",
            "dead_in_hand"} <= set(solo)
    assert v["deck_size"] == len(soren["cards"])
    # The heroics are ISOLATED inside the character run: with-vs-without
    # paired marginals plus usage counts.
    assert set(v["heroics"]) <= {"skill", "ultimate"}
    for h in v["heroics"].values():
        assert {"marginal", "games_cast", "games", "exercised"} <= set(h)
        assert h["marginal"]["n"] > 0
    # The spend audit runs across a pressure ladder and self-reports when it
    # produced no signal.
    assert set(v["spend_audit"]) == {"balanced", "greedy-hp", "greedy-power",
                                     "greedy-mana"}
    assert isinstance(v["spend_audit_meta"]["no_signal"], bool)
    # The support-fair standings: solo/duo splits + the two-ally floor.
    assert set(v["roster_solo"]) == set(v["roster_rates"])
    assert "ally_baseline" in v and "contribution" in v
    # Never-cast cards are named in the recommendation's caveat.
    if any(s["games_cast"] == 0 for s in v["screening"]):
        assert "never plays" in v["recommendation"]


# ========================================================================== #
# §D13-3.2 — enemy-schema attribution
# ========================================================================== #
def test_encounter_features_read_the_vocabulary(baseline):
    by_file = {e["_file"]: e for e in baseline["encounters"]}
    feats = enemy_analysis.encounter_features(by_file["02_mendicant_shrine.json"])
    assert "archetype:fortify" in feats and "archetype:punish" in feats
    assert "pattern:reactive" in feats
    feats = enemy_analysis.encounter_features(by_file["03_bonefire_rite.json"])
    assert "pattern:channel" in feats and "pattern:aoe" in feats
    feats = enemy_analysis.encounter_features(by_file["06_rusted_sentinel.json"])
    assert "pattern:boss" in feats
    feats = enemy_analysis.encounter_features(by_file["07_last_palisade.json"])
    assert "pattern:objective" in feats


def test_enemy_schema_analysis_flags_a_lopsided_feature():
    encounters = [
        {"name": f"With {i}", "enemies": [
            {"id": "x", "name": "X", "hp": 4, "level": 1, "power": 1,
             "components": [{"id": "d", "archetype": "Drain",
                             "verbs": [{"kind": "deal_damage", "amount": 2,
                                        "target": {"mode": "chosen",
                                                   "side": "ally",
                                                   "targeted": True}}]}]}]}
        for i in range(2)
    ] + [{"name": f"Without {i}", "enemies": [
        {"id": "y", "name": "Y", "hp": 4, "level": 1, "power": 1}]}
        for i in range(2)]

    def recs(name, wins, n=10):
        return [{"content": name, "result": "victory" if i < wins else "defeat",
                 "rounds": 5} for i in range(n)]
    records = (recs("With 0", 2) + recs("With 1", 3)
               + recs("Without 0", 9) + recs("Without 1", 8))
    features = enemy_analysis.analyze_records(records, encounters)
    drain = next(f for f in features if f["feature"] == "archetype:drain")
    assert drain["flagged"] and drain["delta_win_pp"] < -10
    assert "underpriced" in drain["proposal"]
    assert "Drain base cost" in drain["lever"]


def test_enemy_schema_probe_runs(baseline, soren):
    v = enemy_analysis.probe_enemy_schema([soren], _small(baseline, 3),
                                          "test-tiny")
    assert v["kind"] == "enemy_schema"
    assert v["features"]                      # something was attributed
    assert v["flag"] in ("FLAGS", "IN_BAND")
    assert v["gauntlet"]["hash"] == baseline["hash"]


# ========================================================================== #
# §D13-4 — the app surface
# ========================================================================== #
def test_api_surface_smoke():
    from fastapi.testclient import TestClient
    from ltg_autoplay_tester.app import app
    client = TestClient(app)

    roster = client.get("/api/roster").json()["characters"]
    assert roster and {"id", "name", "cards", "last_verdict"} <= set(roster[0])

    g = client.get("/api/gauntlets").json()
    assert g["baseline"] == "baseline-2"
    detail = client.get("/api/gauntlets/baseline-2").json()
    assert len(detail["encounters"]) == 8 and detail["has_partner"]

    est = client.post("/api/probes/estimate", json={
        "kind": "card", "gauntlet_id": "baseline-2", "preset": "quick",
        "character_id": roster[0]["id"],
        "card_id": roster[0]["cards"][0]["id"]}).json()
    assert est["games"] > 0 and est["est_minutes"] >= 0

    url = client.get(f"/api/deckbuilder-url/{roster[0]['id']}").json()["url"]
    assert url.endswith(f"?edit={roster[0]['id']}")

    # Bad submissions are rejected with human messages.
    assert client.post("/api/probes", json={
        "kind": "card", "gauntlet_id": "baseline-1",
        "character_id": roster[0]["id"], "card_id": "nope"}).status_code == 404
    assert client.post("/api/probes", json={
        "kind": "sideways", "gauntlet_id": "baseline-1"}).status_code == 400

    # The static frontend serves at /.
    assert "Autoplay Tester" in client.get("/").text
