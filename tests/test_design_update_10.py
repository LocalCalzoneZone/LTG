"""Design Update 10 — Adventures: the three-phase run.

Covers the adventure layers around the untouched combat engine: the content
object and its validation (§D10-4), the carry-over rules (§D10-2), the
adventure-local level-up (§D10-3), and the session's phase transitions (§D10-6.3
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


def _phase(name, enemies, boss_id=None, narration="You arrive. The test begins."):
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
        "phases": [
            _phase("The Gate", [_enemy("guard", "Guard", 1)]),
            _phase("The Courtyard", [_enemy("knight", "Knight", 2)]),
            _phase("The Throne Room",
                 [_enemy("footman", "Footman", 1),
                  _enemy("tyrant", "Tyrant", 4, hp=20, boss=True)],
                 boss_id="tyrant"),
        ],
    }


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    """Keep every saved adventure/phase/hidden file out of the developer's real
    content + loadouts state: remember what exists, delete anything new after."""
    dirs = [content.CONTENT_DIR, content.LOADOUTS_DIR]
    before = {d: ({p.name for p in d.glob("*.json")} if d.is_dir() else set())
              for d in dirs}
    saved_hidden = {p: (p.read_text() if p.exists() else None)
                    for p in (content.HIDDEN_FILE, content.ENCOUNTER_HIDDEN_FILE,
                              content.ADVENTURE_HIDDEN_FILE)}
    try:
        yield
    finally:
        for d in dirs:
            if d.is_dir():
                for p in d.glob("*.json"):
                    if p.name not in before[d]:
                        p.unlink(missing_ok=True)
        for p, original in saved_hidden.items():
            if original is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(original)


# --------------------------------------------------------------------------- #
# §D10-4 — the adventure content object
# --------------------------------------------------------------------------- #
def test_save_adventure_persists_wrapper_and_phase_files():
    meta = content.save_adventure(_adventure())
    aid = meta["id"]
    assert meta["name"] == "Test Keep"
    assert meta["phase_names"] == ["The Gate", "The Courtyard", "The Throne Room"]
    # The wrapper and the three phase encounter files exist.
    assert (content.CONTENT_DIR / f"{aid}.json").exists()
    for n in (1, 2, 3):
        assert (content.CONTENT_DIR / f"{aid}__phase{n}.json").exists()
    detail = content.adventure_detail(aid)
    assert [a["narration"] for a in detail["phases"]] != ["", "", ""]
    assert detail["phases"][2]["enemies"][1]["is_boss"] is True


def test_phase_encounters_hidden_from_the_encounter_list():
    aid = content.save_adventure(_adventure())["id"]
    listed = {e["id"] for e in content.list_encounters()}
    for n in (1, 2, 3):
        assert content.phase_encounter_id(aid, n) not in listed
    # …but they resolve as encounters (editor / art / game-build path).
    assert content.encounter_detail(content.phase_encounter_id(aid, 1)) is not None
    # And the adventure is listed.
    assert aid in {a["id"] for a in content.list_adventures()}


def test_adventure_validation_rules():
    # Not three phases.
    bad = _adventure()
    bad["phases"] = bad["phases"][:2]
    with pytest.raises(ValueError, match="exactly 3 phases"):
        content.save_adventure(bad)
    # No boss in Phase III.
    bad = _adventure()
    bad["phases"][2] = _phase("Finale", [_enemy("footman", "Footman", 1)])
    with pytest.raises(ValueError, match="exactly one boss"):
        content.save_adventure(bad)
    # A mini-boss must sit strictly below the finale boss's level.
    bad = _adventure()
    bad["phases"][0] = _phase("The Gate",
                          [_enemy("guard", "Guard", 1),
                           _enemy("warden", "Warden", 4, boss=True)],
                          boss_id="warden")
    with pytest.raises(ValueError, match="strictly"):
        content.save_adventure(bad)
    # No enemy anywhere may out-level the finale boss.
    bad = _adventure()
    bad["phases"][1] = _phase("The Courtyard", [_enemy("giant", "Giant", 9)])
    with pytest.raises(ValueError, match="highest-level"):
        content.save_adventure(bad)
    # Missing narration.
    bad = _adventure()
    bad["phases"][0]["narration"] = "  "
    with pytest.raises(ValueError, match="narration"):
        content.save_adventure(bad)
    # Missing layouts (phases are held to the generated-encounter bar).
    bad = _adventure()
    del bad["phases"][0]["layouts"]
    with pytest.raises(ValueError, match="layouts"):
        content.save_adventure(bad)


def test_editing_an_phase_reruns_adventure_validation():
    aid = content.save_adventure(_adventure())["id"]
    act1_id = content.phase_encounter_id(aid, 1)
    act1 = content.encounter_detail(act1_id)
    # Sneak a second boss ABOVE the finale's level into Phase I via the ordinary
    # encounter save path: the adventure gate must reject it before persisting.
    act1["enemies"].append(_enemy("usurper", "Usurper", 9, boss=True))
    for roster in act1["layouts"].values():
        roster[0] = "usurper"
    with pytest.raises(ValueError, match="strictly"):
        content.save_encounter(act1, act1_id)
    # The on-disk phase is untouched.
    fresh = content.encounter_detail(act1_id)
    assert [e["id"] for e in fresh["enemies"]] == ["guard"]


def test_delete_adventure_removes_phase_files():
    aid = content.save_adventure(_adventure())["id"]
    content.delete_adventure(aid)
    assert content.adventure_detail(aid) is None
    for n in (1, 2, 3):
        assert not (content.CONTENT_DIR / f"{aid}__phase{n}.json").exists()


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
    # Level 2 allows +4 bought (T-60): +3 more over the entering +1 — on the
    # T-79 curve the 2nd/3rd/4th Power purchases cost 10+15+20 = 45 pts.
    new, spent = validate_level_up(old, {"power_bought": 4}, 2, 45)
    assert spent == 45 and new["power_bought"] == 4
    with pytest.raises(ValueError, match="Power cap"):
        validate_level_up(old, {"power_bought": 5}, 2, 90)


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
    """A level-3 build spending 70+60 validates (T-57 budget, T-60 cap). On the
    T-79 curve: 6 HP pairs 4+4+5+5+6+6 = 30, +2 mana 15+15 = 30, +2 cards 30,
    +4 Power 10+10+15+20 = 55 → 145 against a 130 budget: ADVISORY over by 15
    (Update 17 §D17-2.2), never a validation error."""
    c = Character.model_validate({
        **_fresh_char(), "level": 3,
        "hp": 20, "starting_cards": 3, "power_bought": 4,
        "starting_mana": ["U", "B", "U"],
    })
    assert c.points_budget == 130          # 70 + the 60 a level-3 build has earned (T-78)
    assert c.points_spent == 145
    assert c.points_over == 15
    # Recorded earnings raise the budget (a run copy mid-adventure 3, still L5).
    c2 = Character.model_validate({**_fresh_char(), "level": 5, "earned_points": 180})
    assert c2.points_budget == 250


# --------------------------------------------------------------------------- #
# §D10-2 / §D10-6.3 — the run: carry-over and phase transitions
# --------------------------------------------------------------------------- #
def _start_run():
    aid = content.save_adventure(_adventure())["id"]
    run = AdventureRun(aid)
    state, portraits, art, eid = run.start(["loadout_soren", "loadout_ys"], seed=11)
    return run, state, eid


def test_run_starts_on_phase_one():
    run, state, eid = _start_run()
    assert run.phase_index == 0 and eid.endswith("__phase1")
    assert [e.name for e in state.enemies] == ["Guard", "Guard 2", "Guard 3", "Guard 4"]
    assert run.suppresses_result("victory") is True
    assert run.suppresses_result("defeat") is False


def test_carry_over_across_the_phase_boundary():
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
    assert eid.endswith("__phase2") and run.phase_index == 1

    s2 = new_state.character(soren.id)
    y2 = new_state.character(ys.id)
    # HP floor (T-59): max(current, ceil(25% of max)); Soren 3 → 7 (25/4 ceil).
    assert s2.hp == 7
    # Ys: incapacitated (−2) +2 bought healing → 0, lifted to ceil(17/4) = 5.
    assert y2.max_hp == 17 and y2.hp == 5
    # Gauge carries at 50%, floored (T-58).
    assert s2.ultimate_gauge == 50 and y2.ultimate_gauge == 22
    # Full reshuffle at the boundary: hand + library + graveyard become one
    # pool, and the phase opens on a FRESH hand of starting-cards.
    assert len(s2.hand) + len(s2.library) == 6
    assert s2.graveyard == [] and y2.graveyard == []
    assert len(y2.hand) + len(y2.library) == ys_cards
    assert len(s2.hand) == s2.hand_size
    assert len(y2.hand) == y2.hand_size
    # Skill/Ultimate uses reset; mana pool reset to base.
    assert not s2.skill_used and not s2.ultimate_used
    assert s2.pool == []
    # Phase II fields its own roster.
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


def test_final_phase_victory_completes_the_run():
    run, state, _eid = _start_run()
    run.phase_index = 2  # jump to the finale
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
    # The phase boundary is not a game over…
    assert session.public_result() is None
    snap = session.snapshot_for("A")
    assert snap["result"] is None and snap["game_over"] is None
    # …and the snapshot carries the per-seat level-up gate.
    adv = snap["adventure"]
    assert adv["phase"] == 1 and adv["phases_total"] == 3
    lu = adv["level_up"]
    assert lu["level"] == 1                     # nothing spent yet (§D17-2.3)
    rows = {r["id"]: r for r in lu["characters"]}
    # Phase I pays +10 (T-57): the pool is what is spendable at the screen.
    assert "build" in rows["soren"] and rows["soren"]["available"] == 10
    assert rows["soren"]["earned_points"] == 10 and rows["soren"]["spent_points"] == 0
    assert "build" not in rows["ys"]  # another seat: confirmed/waiting light only

    # Seat gating: A cannot confirm for a character it does not control.
    with pytest.raises(ValueError, match="control"):
        session.confirm_level_up("A", "ys", {})
    session.confirm_level_up("A", "soren", {})
    session.claim("A", ["ys"])
    session.confirm_level_up("A", "ys", {})
    # The last confirmation advanced the phase.
    assert run.phase_index == 1
    assert session.encounter_id.endswith("__phase2")
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


def test_a_held_library_channel_carries_exactly_once():
    """Playtest bug (2026-08-23): a channeled LIBRARY card held at victory was
    doubled in the next phase's deck. The engine moves a cast card to the
    graveyard at once (R-9) and the channel only references it — so folding
    `ch.card` into the carry on top of the graveyard dealt a second copy."""
    from ltg_combat.state import Channel

    aid = content.save_adventure(_adventure())["id"]
    run = AdventureRun(aid)
    state, _portraits, _art, _eid = run.start(["loadout_soren", "loadout_ys"], seed=11)
    soren = state.party[0]
    deck_size = len(soren.hand) + len(soren.library) + len(soren.graveyard)
    # Cast (the card lands in the graveyard) and hold it as a channel.
    card = soren.hand[0]
    soren.hand.remove(card)
    soren.graveyard.append(card)
    soren.channels = [Channel(card=card, holder_id=soren.id)]
    state.result = "victory"
    run.on_state_change(state)
    carried = run.carry[soren.id]["cards"]
    assert len(carried) == deck_size
    assert [c.id for c in carried].count(card.id) == [c.id for c in soren.hand + soren.library + soren.graveyard].count(card.id)

    run.confirm_level_up(soren.id, {})
    run.confirm_level_up(state.party[1].id, {})
    new_state, _p, _a, _eid2 = run.advance(seed=12)
    s2 = new_state.character(soren.id)
    assert len(s2.hand) + len(s2.library) + len(s2.graveyard) == deck_size


def test_a_held_skill_channel_never_joins_the_deck():
    """Playtest bug: a character holding a CHANNELED Skill at the phase boundary
    had its card folded into the carried deck — the Skill was then dealt into the
    next phase's hand as a real card, one more copy per boundary. Sheet content
    (Skill / Ultimate) is not deck, and never carries."""
    from ltg_combat.state import Channel

    skill = {"id": "skill_resonate", "name": "Resonate", "source_name": "Skill",
             "type": "Skill", "rarity": "common", "level": 1,
             "cost": {"generic": 0, "colors": {}, "x": False},
             "timing": "channeled", "original_text": "",
             "translated_text": "While channeled: nothing in particular.",
             "effects": [], "needs_translation": False}
    loadouts = copy.deepcopy(content.loadouts_for(["loadout_soren", "loadout_ys"]))
    loadouts[0]["character"]["skill"] = skill

    aid = content.save_adventure(_adventure())["id"]
    run = AdventureRun(aid)
    state, _portraits, _art, _eid = run.start(
        ["loadout_soren", "loadout_ys"], seed=11, loadouts=loadouts)
    soren = state.party[0]
    assert soren.skill is not None and soren.skill.id == "skill_resonate"
    deck_size = len(soren.hand) + len(soren.library) + len(soren.graveyard)

    # Win the phase while the Skill's channel is still held.
    soren.channels = [Channel(card=soren.skill, holder_id=soren.id)]
    state.result = "victory"
    run.on_state_change(state)
    assert "Resonate" not in [c.name for c in run.carry[soren.id]["cards"]]

    run.confirm_level_up(soren.id, {})
    run.confirm_level_up(state.party[1].id, {})
    new_state, _p, _a, _eid2 = run.advance(seed=12)
    s2 = new_state.character(soren.id)
    assert "Resonate" not in [c.name for c in s2.hand + s2.library + s2.graveyard]
    assert len(s2.hand) + len(s2.library) == deck_size
    # It is still on the sheet, and its once-per-encounter use has reset.
    assert s2.skill is not None and s2.skill.name == "Resonate" and not s2.skill_used


def test_an_art_refresh_keeps_the_party_panel_clips():
    """Playtest bug (2026-08-23): `Session.set_art` (the mid-game art refresh —
    a generation landing, the art queue finishing a phase's scene) rebuilt the
    bundle keeping only `base_of` and `char_descriptions`, so every hero's
    panel-animation bundle vanished from the snapshot and no clip played for
    the rest of the session."""
    loadouts = copy.deepcopy(content.loadouts_for(["loadout_soren", "loadout_ys"]))
    loadouts[0]["character"]["animations"] = [
        {"id": "anim_swing", "trigger": "attack", "file": "/art/anims/swing.webm",
         "speed": 1.0, "impact_s": 0.6, "duration_s": 2.0}]
    state, portraits, art = content.build_state_from_loadouts(loadouts, "builtin_a", seed=7)
    session = SessionManager().create(state, portraits=portraits, art=art)
    session.clients["A"] = None
    soren = state.party[0]
    before = next(c for c in session.snapshot_for("A")["characters"] if c["id"] == soren.id)
    assert before["anims"] and before["anims"]["animations"][0]["id"] == "anim_swing"
    session.set_art(content.encounter_art("builtin_a"))
    after = next(c for c in session.snapshot_for("A")["characters"] if c["id"] == soren.id)
    assert after["anims"] == before["anims"]
    assert after["description"] == before["description"]


# --------------------------------------------------------------------------- #
# The phase-narration floor (beta playtest 2026-08-30): a caption is not a scene
# --------------------------------------------------------------------------- #
def test_generation_rejects_thin_narration():
    from ltg_game_server import llm
    assert llm._narration_problems("") and "missing" in llm._narration_problems("")[0]
    thin = "You push through the splintered gate into the courtyard."
    [p] = llm._narration_problems(thin)
    assert "too thin" in p and "road in" in p
    full = ("You begin up the wooded path toward the foothills, and for a few "
            "hours the only sound is your own boots on the stones. " * 12)
    assert llm._narration_problems(full) == []


def test_prompt_teaches_the_story_beat():
    from ltg_game_server import llm
    D = llm.ADVENTURE_EXTENSION
    for needle in ("2 to 4 PARAGRAPHS", "THE ROAD IN", "THE DISCOVERY",
                   "THE REASON", "A VOICE, when it earns it",
                   "AFTERMATH of the previous fight",
                   "We got company!"):
        assert needle in D, needle
