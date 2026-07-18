"""Design Update 10 — Adventures: the three-act run.

Covers the adventure layers around the untouched combat engine: the content
object and its validation (§D10-4), the carry-over rules (§D10-2), the
adventure-local level-up (§D10-3), and the session's act transitions (§D10-6.3
server side). Single-encounter play staying byte-identical is asserted by the
whole rest of the suite continuing to pass.
"""

from __future__ import annotations

import copy
import json

import pytest

from ltg_core.schema import Character
from ltg_game_server import content
from ltg_game_server.adventure import AdventureRun, validate_level_up
from ltg_game_server.session import SessionManager


# --------------------------------------------------------------------------- #
# Fixtures: a small valid adventure written straight through save_adventure
# --------------------------------------------------------------------------- #
def _enemy(eid, name, level, hp=4, boss=False):
    e = {"id": eid, "name": name, "hp": hp, "level": level, "row": "front",
         "attack_mode": "melee", "power": 1,
         "description": f"A {name.lower()} of the test faction."}
    if boss:
        e["is_boss"] = True
    return e


def _act(name, enemies, boss_id=None, narration="You arrive. The test begins."):
    ids = [e["id"] for e in enemies if not e.get("is_boss")]
    filler = ids[0]
    layouts = {}
    for size in range(1, 5):
        roster = [filler] * (2 * size)
        if boss_id:
            roster[0] = boss_id
        layouts[str(size)] = roster
    return {"name": name, "scene": f"The {name} scene, painted in test grey.",
            "enemies": enemies, "layouts": layouts, "narration": narration}


def _adventure():
    return {
        "name": "Test Keep",
        "flavor": "Three rooms, one tyrant.",
        "acts": [
            _act("The Gate", [_enemy("guard", "Guard", 1)]),
            _act("The Courtyard", [_enemy("knight", "Knight", 2)]),
            _act("The Throne Room",
                 [_enemy("footman", "Footman", 1),
                  _enemy("tyrant", "Tyrant", 4, hp=20, boss=True)],
                 boss_id="tyrant"),
        ],
    }


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    """Keep every saved adventure/act/hidden file out of the developer's real
    loadouts dir state: remember what exists, delete anything new afterwards."""
    before = {p.name for p in content.LOADOUTS_DIR.glob("*.json")} \
        if content.LOADOUTS_DIR.is_dir() else set()
    saved_hidden = {p: (p.read_text() if p.exists() else None)
                    for p in (content.HIDDEN_FILE, content.ENCOUNTER_HIDDEN_FILE,
                              content.ADVENTURE_HIDDEN_FILE)}
    try:
        yield
    finally:
        if content.LOADOUTS_DIR.is_dir():
            for p in content.LOADOUTS_DIR.glob("*.json"):
                if p.name not in before:
                    p.unlink(missing_ok=True)
        for p, original in saved_hidden.items():
            if original is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(original)


# --------------------------------------------------------------------------- #
# §D10-4 — the adventure content object
# --------------------------------------------------------------------------- #
def test_save_adventure_persists_wrapper_and_act_files():
    meta = content.save_adventure(_adventure())
    aid = meta["id"]
    assert meta["name"] == "Test Keep"
    assert meta["act_names"] == ["The Gate", "The Courtyard", "The Throne Room"]
    # The wrapper and the three act encounter files exist.
    assert (content.LOADOUTS_DIR / f"{aid}.json").exists()
    for n in (1, 2, 3):
        assert (content.LOADOUTS_DIR / f"{aid}__act{n}.json").exists()
    detail = content.adventure_detail(aid)
    assert [a["narration"] for a in detail["acts"]] != ["", "", ""]
    assert detail["acts"][2]["enemies"][1]["is_boss"] is True


def test_act_encounters_hidden_from_the_encounter_list():
    aid = content.save_adventure(_adventure())["id"]
    listed = {e["id"] for e in content.list_encounters()}
    for n in (1, 2, 3):
        assert content.act_encounter_id(aid, n) not in listed
    # …but they resolve as encounters (editor / art / game-build path).
    assert content.encounter_detail(content.act_encounter_id(aid, 1)) is not None
    # And the adventure is listed.
    assert aid in {a["id"] for a in content.list_adventures()}


def test_adventure_validation_rules():
    # Not three acts.
    bad = _adventure()
    bad["acts"] = bad["acts"][:2]
    with pytest.raises(ValueError, match="exactly 3 acts"):
        content.save_adventure(bad)
    # No boss in Act III.
    bad = _adventure()
    bad["acts"][2] = _act("Finale", [_enemy("footman", "Footman", 1)])
    with pytest.raises(ValueError, match="exactly one boss"):
        content.save_adventure(bad)
    # A mini-boss must sit strictly below the finale boss's level.
    bad = _adventure()
    bad["acts"][0] = _act("The Gate",
                          [_enemy("guard", "Guard", 1),
                           _enemy("warden", "Warden", 4, boss=True)],
                          boss_id="warden")
    with pytest.raises(ValueError, match="strictly"):
        content.save_adventure(bad)
    # No enemy anywhere may out-level the finale boss.
    bad = _adventure()
    bad["acts"][1] = _act("The Courtyard", [_enemy("giant", "Giant", 9)])
    with pytest.raises(ValueError, match="highest-level"):
        content.save_adventure(bad)
    # Missing narration.
    bad = _adventure()
    bad["acts"][0]["narration"] = "  "
    with pytest.raises(ValueError, match="narration"):
        content.save_adventure(bad)
    # Missing layouts (acts are held to the generated-encounter bar).
    bad = _adventure()
    del bad["acts"][0]["layouts"]
    with pytest.raises(ValueError, match="layouts"):
        content.save_adventure(bad)


def test_editing_an_act_reruns_adventure_validation():
    aid = content.save_adventure(_adventure())["id"]
    act1_id = content.act_encounter_id(aid, 1)
    act1 = content.encounter_detail(act1_id)
    # Sneak a second boss ABOVE the finale's level into Act I via the ordinary
    # encounter save path: the adventure gate must reject it before persisting.
    act1["enemies"].append(_enemy("usurper", "Usurper", 9, boss=True))
    for roster in act1["layouts"].values():
        roster[0] = "usurper"
    with pytest.raises(ValueError, match="strictly"):
        content.save_encounter(act1, act1_id)
    # The on-disk act is untouched.
    fresh = content.encounter_detail(act1_id)
    assert [e["id"] for e in fresh["enemies"]] == ["guard"]


def test_delete_adventure_removes_act_files():
    aid = content.save_adventure(_adventure())["id"]
    content.delete_adventure(aid)
    assert content.adventure_detail(aid) is None
    for n in (1, 2, 3):
        assert not (content.LOADOUTS_DIR / f"{aid}__act{n}.json").exists()


# --------------------------------------------------------------------------- #
# §D10-3 — the level-up
# --------------------------------------------------------------------------- #
def _fresh_char():
    return {
        "name": "Testa", "colors": ["U", "B"], "starting_mana": ["U", "B"],
        "hp": 12, "starting_cards": 2, "power_bought": 1,
        "attack_mode": "ranged", "level": 1,
    }


def test_level_up_spends_and_banks():
    old = _fresh_char()
    # +2 HP (5) and +1 card (15) = 20 of the 30: bank 10.
    new, spent = validate_level_up(
        old, {"hp": 14, "starting_cards": 3}, new_level=2, available=30)
    assert spent == 20
    assert new["level"] == 2 and new["hp"] == 14 and new["starting_cards"] == 3
    # Confirming without spending is legal (banking).
    new, spent = validate_level_up(old, {}, new_level=2, available=30)
    assert spent == 0 and new["level"] == 2


def test_level_up_locks_previous_purchases():
    old = _fresh_char()
    with pytest.raises(ValueError, match="locked"):
        validate_level_up(old, {"hp": 10}, 2, 30)
    with pytest.raises(ValueError, match="locked"):
        validate_level_up(old, {"starting_cards": 1}, 2, 30)
    with pytest.raises(ValueError, match="locked"):
        validate_level_up(old, {"power_bought": 0}, 2, 30)
    # Existing mana slots are immutable; new slots must fit the identity.
    with pytest.raises(ValueError, match="locked"):
        validate_level_up(old, {"starting_mana": ["B", "U"]}, 2, 30)
    with pytest.raises(ValueError, match="identity"):
        validate_level_up(old, {"starting_mana": ["U", "B", "G"]}, 2, 30)
    # In-identity capacity is legal (15 points).
    new, spent = validate_level_up(old, {"starting_mana": ["U", "B", "B"]}, 2, 30)
    assert spent == 15 and new["starting_mana"] == ["U", "B", "B"]


def test_level_up_keyword_is_creation_only():
    old = _fresh_char()
    # Keywords cannot be bought at a level-up — creation only.
    with pytest.raises(ValueError, match="character creation only"):
        validate_level_up(old, {"keyword": "reach"}, 2, 30)
    # A creation keyword rides along untouched…
    owned = {**old, "keyword": "reach"}
    new, spent = validate_level_up(owned, {"keyword": "reach"}, 2, 30)
    assert new["keyword"] == "reach" and spent == 0
    new, spent = validate_level_up(owned, {}, 2, 30)
    assert new["keyword"] == "reach" and spent == 0
    # …but changing or dropping it never validates.
    with pytest.raises(ValueError, match="character creation only"):
        validate_level_up(owned, {"keyword": "flying"}, 2, 30)
    with pytest.raises(ValueError, match="character creation only"):
        validate_level_up(owned, {"keyword": None}, 2, 30)


def test_level_up_power_cap_scales_with_level():
    old = _fresh_char()
    # Level 2 allows +4 bought (T-60): +3 more over the entering +1 = 30 pts.
    new, spent = validate_level_up(old, {"power_bought": 4}, 2, 30)
    assert spent == 30 and new["power_bought"] == 4
    with pytest.raises(ValueError, match="Power cap"):
        validate_level_up(old, {"power_bought": 5}, 2, 60)


def test_level_up_budget_is_the_available_pool():
    old = _fresh_char()
    # 35 points of buys against 30 available: rejected.
    with pytest.raises(ValueError, match="available"):
        validate_level_up(old, {"hp": 16, "starting_cards": 3, "power_bought": 2}, 2, 30)
    # The same build passes with banked points on top.
    _new, spent = validate_level_up(
        old, {"hp": 16, "starting_cards": 3, "power_bought": 2}, 2, available=40)
    assert spent == 35


def test_leveled_build_passes_schema_validation():
    """A level-3 build spending 70+60 validates (T-57 budget, T-60 cap)."""
    c = Character.model_validate({
        **_fresh_char(), "level": 3,
        "hp": 20, "starting_cards": 3, "power_bought": 4,
        "starting_mana": ["U", "B", "U"],
    })
    assert c.points_budget == 130
    assert c.points_spent == 130


# --------------------------------------------------------------------------- #
# §D10-2 / §D10-6.3 — the run: carry-over and act transitions
# --------------------------------------------------------------------------- #
def _start_run():
    aid = content.save_adventure(_adventure())["id"]
    run = AdventureRun(aid)
    state, portraits, art, eid = run.start(["loadout_soren", "loadout_ys"], seed=11)
    return run, state, eid


def test_run_starts_on_act_one():
    run, state, eid = _start_run()
    assert run.act_index == 0 and eid.endswith("__act1")
    assert [e.name for e in state.enemies] == ["Guard", "Guard 2", "Guard 3", "Guard 4"]
    assert run.suppresses_result("victory") is True
    assert run.suppresses_result("defeat") is False


def test_carry_over_across_the_act_boundary():
    run, state, _eid = _start_run()
    soren = state.party[0]
    ys = state.party[1]

    # Shape the pre-victory state: wounds, spent cards, gauge, an emptied hand.
    soren.hp = 3                      # wounded below the 25% floor of 25 → 7
    soren.graveyard = soren.library[:2]
    soren.library = soren.library[2:]
    soren.ultimate_gauge = 100
    ys.hp = -2                        # incapacitated: stands back up at the floor
    ys.ultimate_gauge = 45
    ys_cards = len(ys.hand) + len(ys.library) + len(ys.graveyard)

    state.result = "victory"
    run.on_state_change(state)
    assert run.level_up is not None and not run.all_confirmed()

    run.confirm_level_up(soren.id, {})           # bank everything
    run.confirm_level_up(ys.id, {"hp": 17})      # +2 HP heals (+2 current)
    new_state, _portraits, _art, eid = run.advance(seed=12)
    assert eid.endswith("__act2") and run.act_index == 1

    s2 = new_state.character(soren.id)
    y2 = new_state.character(ys.id)
    # HP floor (T-59): max(current, ceil(25% of max)); Soren 3 → 7 (25/4 ceil).
    assert s2.hp == 7
    # Ys: incapacitated (−2) +2 bought healing → 0, lifted to ceil(17/4) = 5.
    assert y2.max_hp == 17 and y2.hp == 5
    # Gauge carries at 50%, floored (T-58).
    assert s2.ultimate_gauge == 50 and y2.ultimate_gauge == 22
    # Full reshuffle at the boundary: hand + library + graveyard become one
    # pool, and the act opens on a FRESH hand of starting-cards.
    assert len(s2.hand) + len(s2.library) == 6
    assert s2.graveyard == [] and y2.graveyard == []
    assert len(y2.hand) + len(y2.library) == ys_cards
    assert len(s2.hand) == s2.hand_size
    assert len(y2.hand) == y2.hand_size
    # Skill/Ultimate uses reset; mana pool reset to base.
    assert not s2.skill_used and not s2.ultimate_used
    assert s2.pool == []
    # Act II fields its own roster.
    assert [e.name for e in new_state.enemies][0] == "Knight"


def test_confirm_is_gated_and_double_confirm_rejected():
    run, state, _eid = _start_run()
    state.result = "victory"
    run.on_state_change(state)
    a, b = run.live_ids
    run.confirm_level_up(a, {})
    with pytest.raises(ValueError, match="already confirmed"):
        run.confirm_level_up(a, {})
    with pytest.raises(ValueError, match="confirmed the level-up"):
        run.advance()
    run.confirm_level_up(b, {})
    assert run.all_confirmed()


def test_final_act_victory_completes_the_run():
    run, state, _eid = _start_run()
    run.act_index = 2  # jump to the finale
    state.result = "victory"
    run.on_state_change(state)
    assert run.complete is True
    assert run.level_up is None
    assert run.suppresses_result("victory") is False


def test_session_suppresses_result_and_gates_confirm_by_seat():
    aid = content.save_adventure(_adventure())["id"]
    run = AdventureRun(aid)
    state, portraits, _art, eid = run.start(["loadout_soren", "loadout_ys"], seed=11)
    session = SessionManager().create(state, portraits=portraits,
                                      encounter_id=eid, adventure=run)
    session.clients["A"] = None
    session.claim("A", ["soren"])

    session.state.result = "victory"
    run.on_state_change(session.state)
    # The act boundary is not a game over…
    assert session.public_result() is None
    snap = session.snapshot_for("A")
    assert snap["result"] is None and snap["game_over"] is None
    # …and the snapshot carries the per-seat level-up gate.
    adv = snap["adventure"]
    assert adv["act"] == 1 and adv["acts_total"] == 3
    lu = adv["level_up"]
    assert lu["next_level"] == 2
    rows = {r["id"]: r for r in lu["characters"]}
    assert "build" in rows["soren"] and rows["soren"]["available"] == 30
    assert "build" not in rows["ys"]  # another seat: confirmed/waiting light only

    # Seat gating: A cannot confirm for a character it does not control.
    with pytest.raises(ValueError, match="control"):
        session.confirm_level_up("A", "ys", {})
    session.confirm_level_up("A", "soren", {})
    session.claim("A", ["ys"])
    session.confirm_level_up("A", "ys", {})
    # The last confirmation advanced the act.
    assert run.act_index == 1
    assert session.encounter_id.endswith("__act2")
    assert session.state.result is None
    # A defeat passes through untouched.
    session.state.result = "defeat"
    assert session.public_result() == "defeat"


def test_plain_encounter_sessions_are_unchanged():
    """The regression spine: no adventure ⇒ no adventure block, no suppression."""
    state, portraits, _art = content.build_state(
        ["loadout_soren", "loadout_ys"], "builtin_a", seed=7)
    session = SessionManager().create(state, portraits=portraits)
    session.clients["A"] = None
    snap = session.snapshot_for("A")
    assert "adventure" not in snap
    session.state.result = "victory"
    assert session.public_result() == "victory"
    with pytest.raises(ValueError, match="not an adventure"):
        session.confirm_level_up("A", "soren", {})
