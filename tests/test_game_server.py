"""LTG-Game server tests: the seat/hidden-info guarantees the engine does not
provide. Rules themselves are the engine's (covered elsewhere); these check only
the authority/relay layer — seat gating and hidden-hand filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_game_server import content
from ltg_game_server.session import SessionManager

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(autouse=True)
def _isolate_hidden_roster():
    """These tests read the real content dirs, so isolate the picker's hidden-sets:
    start each test with nothing hidden, and restore the developer's own hidden.json /
    encounters_hidden.json afterward (so running the suite never disturbs their curated
    roster)."""
    saved = {p: (p.read_text() if p.exists() else None)
             for p in (content.HIDDEN_FILE, content.ENCOUNTER_HIDDEN_FILE)}
    for p in saved:
        p.unlink(missing_ok=True)
    try:
        yield
    finally:
        for p, original in saved.items():
            if original is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(original)


def _two_char_session():
    state, portraits, _art = content.build_state(["loadout_soren", "loadout_ys"], "builtin_a", seed=7)
    return SessionManager().create(state, portraits=portraits)


def _wound(power, toughness):
    return {"kind": "wound", "power": power, "toughness": toughness,
            "target": {"mode": "chosen", "side": "enemy", "targeted": True},
            "duration": "this_turn"}


def _card(cid, name, timing, cost, effects):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common", "level": 1,
            "type": {"instant": "Instant", "sorcery": "Sorcery"}[timing], "timing": timing,
            "cost": cost, "effects": effects, "validated": True}


def test_setup_options_expose_characters_and_encounters():
    chars = {c["id"] for c in content.list_characters()}
    encs = {e["id"] for e in content.list_encounters()}
    assert {"loadout_soren", "loadout_ys"} <= chars
    assert {"builtin_a", "builtin_c"} <= encs  # the two built-in fights are always offered


def test_hidden_info_only_controlled_hands_are_sent():
    s = _two_char_session()
    s.clients["A"] = None
    s.claim("A", ["soren"])

    snap = s.snapshot_for("A")
    by_id = {c["id"]: c for c in snap["characters"]}
    assert by_id["soren"]["hand"] is not None      # controlled -> visible
    assert by_id["soren"]["controlled"] is True
    assert by_id["ys"]["hand"] is None             # not controlled -> hidden
    assert by_id["ys"]["controlled"] is False
    # But hand_count is public (board truth), just not the card identities.
    assert by_id["ys"]["hand_count"] >= 0


def test_snapshot_carries_keywords_and_counters():
    """Keyword statics reach the client pre-labelled (registry display + gloss)
    and the +1/+1 counter tally rides alongside the folded-in stats."""
    s = _two_char_session()
    s.clients["A"] = None
    s.claim("A", ["soren"])

    char = s.state.party[0]
    char.keywords["flying"] = "encounter"
    char.counters = 2
    enemy = s.state.enemies[0]
    enemy.keywords["lifelink"] = "permanent"

    snap = s.snapshot_for("A")
    c = next(cv for cv in snap["characters"] if cv["id"] == char.id)
    assert c["counters"] == 2
    kw = {k["id"]: k for k in c["keywords"]}
    assert kw["flying"]["name"] == "Flying" and kw["flying"]["gloss"]
    e = next(ev for ev in snap["creatures"] if ev["id"] == enemy.id)
    assert e["counters"] == 0
    assert [k["id"] for k in e["keywords"]] == ["lifelink"]


def test_legal_actions_only_for_the_controlled_priority_holder():
    s = _two_char_session()
    s.clients["A"] = None
    s.clients["B"] = None
    # Turn order is randomized at setup (seeded), so read who actually opens.
    holder = s.snapshot_for("")["priority"]["holder_character_id"]
    other = "ys" if holder == "soren" else "soren"
    s.claim("A", [other])    # A controls the NON-holder
    s.claim("B", [holder])

    # Only B (who controls the opening holder) gets actions.
    assert s.snapshot_for("A")["legal_actions"] == []
    assert len(s.snapshot_for("B")["legal_actions"]) > 0


def test_seat_gating_rejects_action_for_uncontrolled_character():
    s = _two_char_session()
    s.clients["A"] = None
    s.clients["B"] = None
    holder = s.snapshot_for("")["priority"]["holder_character_id"]
    other = "ys" if holder == "soren" else "soren"
    s.claim("A", [other])
    s.claim("B", [holder])

    # Index 0 is the holder's action. A does not control the holder -> rejected.
    with pytest.raises(ValueError, match="do not control"):
        s.apply_index("A", 0)
    # B controls the holder -> the same index applies cleanly.
    s.apply_index("B", 0)


def test_out_of_range_index_rejected():
    s = _two_char_session()
    s.clients["A"] = None
    s.claim("A", ["soren"])
    with pytest.raises(ValueError, match="out of range"):
        s.apply_index("A", 9999)


def test_snapshot_carries_portrait_field():
    s = _two_char_session()
    s.clients["A"] = None
    s.claim("A", ["soren"])
    snap = s.snapshot_for("A")
    assert all("portrait" in c for c in snap["characters"])


def test_import_loadout_roundtrip_and_portrait_flows_to_game():
    raw = content.loadout_for("loadout_soren")
    raw["character"]["name"] = "Portrait Test Zzz"
    raw["character"]["portrait"] = "data:image/png;base64,AAAA"
    meta = content.save_loadout(raw)
    path = content.LOADOUTS_DIR / f"{meta['id']}.json"
    try:
        # Now discoverable as an available character, with its portrait.
        assert any(c["id"] == meta["id"] for c in content.list_characters())
        assert meta["portrait"].startswith("data:image")
        # And the portrait flows through into a built game's session map.
        _state, portraits, _art = content.build_state([meta["id"]], "builtin_a", seed=1)
        assert list(portraits.values())[0].startswith("data:image")
    finally:
        path.unlink(missing_ok=True)


def test_import_rejects_invalid_loadout():
    with pytest.raises(ValueError, match="invalid loadout"):
        content.save_loadout({"not": "a loadout"})


def test_delete_imported_character_removes_its_file():
    raw = content.loadout_for("loadout_soren")
    raw["character"]["name"] = "Deletable Zzz"
    meta = content.save_loadout(raw)
    path = content.LOADOUTS_DIR / f"{meta['id']}.json"
    try:
        assert any(c["id"] == meta["id"] for c in content.list_characters())
        content.delete_loadout(meta["id"])
        assert not path.exists()
        assert not any(c["id"] == meta["id"] for c in content.list_characters())
    finally:
        path.unlink(missing_ok=True)


def test_remove_bundled_example_hides_it_without_deleting_the_file():
    # (hidden state is isolated + restored by the autouse fixture)
    example_path = content.REPO_ROOT / "examples" / "loadout_soren.json"
    assert any(c["id"] == "loadout_soren" for c in content.list_characters())
    content.delete_loadout("loadout_soren")  # hides, does NOT delete the file
    assert example_path.exists(), "bundled example file must be preserved"
    assert not any(c["id"] == "loadout_soren" for c in content.list_characters())
    # It's still resolvable by id (only the picker listing filters it out).
    assert content.loadout_for("loadout_soren") is not None


def test_delete_unknown_character_raises():
    with pytest.raises(ValueError, match="unknown character"):
        content.delete_loadout("no_such_character")


# --------------------------------------------------------------------------- #
# Encounter authoring (create / edit / delete) + keyword build-through
# --------------------------------------------------------------------------- #
def _simple_encounter(name="Test Ambush", hp=4):
    return {"name": name, "enemies": [
        {"name": "Goblin", "hp": hp, "level": 1,
         "intent": {"name": "Stab", "amount": 2, "action_type": "ability",
                    "mode": "melee", "targeting": "lowest_hp"}},
    ]}


def test_bundled_example_encounters_are_offered():
    encs = {e["id"] for e in content.list_encounters()}
    assert {"encounter_warband", "encounter_tricksters", "encounter_skyfangs"} <= encs


def test_save_edit_delete_user_encounter_roundtrip():
    meta = content.save_encounter(_simple_encounter())
    path = content.LOADOUTS_DIR / f"{meta['id']}.json"
    try:
        assert any(e["id"] == meta["id"] for e in content.list_encounters())
        # Edit: bump the goblin's HP and confirm it persists.
        edited = content.encounter_detail(meta["id"])
        edited["enemies"][0]["hp"] = 11
        content.save_encounter(edited, meta["id"])
        assert content.encounter_detail(meta["id"])["enemies"][0]["hp"] == 11
        # Delete a user file: the file is removed and it leaves the picker for good.
        content.delete_encounter(meta["id"])
        assert not path.exists()
        assert not any(e["id"] == meta["id"] for e in content.list_encounters())
    finally:
        path.unlink(missing_ok=True)


def test_delete_builtin_encounter_hides_it_without_a_file():
    # (encounter-hidden state is isolated + restored by the autouse fixture)
    assert any(e["id"] == "builtin_a" for e in content.list_encounters())
    content.delete_encounter("builtin_a")
    assert not any(e["id"] == "builtin_a" for e in content.list_encounters())
    # Still resolvable by id (build path uses it) — only the listing filters it.
    assert content.encounter_for("builtin_a") is not None


def test_editing_a_builtin_writes_an_override_that_shadows_it():
    path = content.LOADOUTS_DIR / "builtin_a.json"
    try:
        content.save_encounter(_simple_encounter(name="Overridden A"), "builtin_a")
        assert path.exists()
        detail = content.encounter_detail("builtin_a")
        assert detail["name"] == "Overridden A"
        assert [e["name"] for e in detail["enemies"]] == ["Goblin"]
    finally:
        path.unlink(missing_ok=True)


def test_save_encounter_rejects_malformed_input():
    for bad in ({"enemies": []},
                {"enemies": [{"hp": 3, "intent": {"name": "x"}}]},        # no name
                {"enemies": [{"name": "N", "hp": 0, "intent": {"name": "x"}}]},  # hp<=0
                {"enemies": [{"name": "N", "hp": 3}]}):                    # no intent
        with pytest.raises(ValueError):
            content.save_encounter(bad)


def test_encounter_keywords_reach_the_engine():
    state, _, _art = content.build_state(["loadout_soren"], "encounter_skyfangs", seed=1)
    by_name = {e.name: e for e in state.enemies}
    assert "flying" in by_name["Wyvern"].keywords
    assert {"flying", "lifelink"} <= set(by_name["Dread Seraph"].keywords)


def test_snapshot_handles_non_damage_component_intent():
    """A component intent whose leading verb isn't damage (Swarm's create_token) must
    serialize without assuming an `amount` — regression for the CreateToken crash."""
    from ltg_game_server.snapshot import build_snapshot

    spec = {
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 2, "hand_size": 0,
                   "identity": ["U"], "library": []}],
        "enemies": [{
            "id": "brood", "name": "Broodmother", "hp": 6, "power": 2, "level": 3,
            "row": "rear", "attack_mode": "melee",
            "components": [{
                "id": "swarm", "archetype": "Swarm", "timing": "proactive",
                "priority": 20, "target_rule": "self", "telegraph": "Spawn Husklings",
                "verbs": [{"kind": "create_token", "token_id": "bat", "count": 2,
                           "hp": 2, "power": 1}],
            }],
        }],
    }
    snap = build_snapshot(state_from_dict(spec), {"p"})  # raised AttributeError before the fix
    brood = next(c for c in snap["creatures"] if c["name"] == "Broodmother")
    assert brood["intent"]["name"] == "Spawn Husklings"
    assert brood["intent"]["amount"] is None            # no damage number for a Swarm
    assert any(it["intent_text"] == "Spawn Husklings" for it in snap["intents"])


def test_multitarget_cast_carries_per_site_targets():
    """Independent multi-target casts (Agony Warp) ship a `targets` tuple per site,
    so the client can drive a per-site picker."""
    agony = _card("agony_warp", "Agony Warp", "instant", {"generic": 0, "colors": {}},
                  [_wound(3, 0), _wound(0, 3)])
    spec = {
        "party": [{"id": "p", "name": "Caster", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["U"], "library": [agony]}],
        "enemies": [
            {"id": "ea", "name": "EnemyA", "hp": 12, "level": 1,
             "intent": {"name": "Hit", "amount": 1, "action_type": "ability", "mode": "melee"}},
            {"id": "eb", "name": "EnemyB", "hp": 12, "level": 1,
             "intent": {"name": "Hit", "amount": 1, "action_type": "ability", "mode": "melee"}},
        ],
    }
    s = SessionManager().create(state_from_dict(spec))
    s.clients["A"] = None
    s.claim("A", ["p"])
    casts = [a for a in s.snapshot_for("A")["legal_actions"]
             if a["kind"] == "cast" and a["card_id"] == "agony_warp"]
    assert casts, "expected Agony Warp casts"
    # Two sites × two enemies == four combinations, each a 2-element targets tuple.
    assert all(len(a["targets"]) == 2 for a in casts)
    combos = sorted(a["targets"] for a in casts)
    assert combos == [["ea", "ea"], ["ea", "eb"], ["eb", "ea"], ["eb", "eb"]]


def test_wounded_creature_hp_shows_effective():
    """A wound (−0/−3, e.g. Agony Warp) lowers temp_mod; the serialized hp.current
    must be EFFECTIVE hp (hp + temp_mod), mirroring current_power — not raw hp.
    Regression: the UI showed base hp, so a wounded creature's HP didn't update."""
    from ltg_game_server.snapshot import build_snapshot

    spec = {
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 2, "hand_size": 0,
                   "identity": ["U"], "library": []}],
        "enemies": [{"id": "brood", "name": "Broodmother", "hp": 4, "power": 2, "level": 3,
                     "intent": {"name": "Hit", "amount": 1, "action_type": "ability",
                                "mode": "melee"}}],
    }
    st = state_from_dict(spec)
    st.enemy("brood").temp_mod = -3                 # a −0/−3 wound has landed
    assert st.enemy("brood").effective_hp == 1

    card = next(c for c in build_snapshot(st, {"p"})["creatures"] if c["id"] == "brood")
    assert card["hp"]["current"] == 1               # effective, not raw hp (4)
    assert card["hp"]["base"] == 4
    assert card["hp"]["modifier"] == -3


def test_counter_target_id_maps_to_a_stack_uid():
    """A counter (Unweave) targets an enemy action on the stack; its target_id is
    "#<uid>" matching a StackRow.uid, which the client uses to make that row clickable."""
    unweave = json.loads((EXAMPLES / "counterspell.json").read_text())
    spec = {
        "party": [{"id": "caster", "name": "Caster", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["U", "U"], "library": [unweave]}],
        "enemies": [{"id": "goblin", "name": "Goblin", "hp": 6, "level": 1,
                     "intent": {"name": "Zap", "amount": 2, "action_type": "ability",
                                "mode": "ranged", "targeting": "lowest_hp_party"}}],
    }
    s = SessionManager().create(state_from_dict(spec))  # deterministic: opening hand == [Unweave]
    s.clients["A"] = None
    s.claim("A", ["caster"])
    end = next(a for a in legal_actions(s.state) if a.kind == "end_turn")
    s.state, _ = apply_action(s.state, end)  # into the enemy phase reaction window

    snap = s.snapshot_for("A")
    counters = [a for a in snap["legal_actions"]
                if a["kind"] == "cast" and (a["target_id"] or "").startswith("#")]
    assert counters, "expected a counter targeting the stacked enemy action"
    stack_uids = {f"#{r['uid']}" for r in snap["stack"]}
    assert all(a["target_id"] in stack_uids for a in counters)


def test_disconnect_releases_seats():
    s = _two_char_session()
    s.clients["A"] = None
    s.claim("A", ["soren", "ys"])
    assert s.controlled_by("A") == {"soren", "ys"}
    s.remove_client("A")
    assert all(owner is None for owner in s.seats.values())
