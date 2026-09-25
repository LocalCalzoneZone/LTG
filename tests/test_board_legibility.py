"""Roadmap M2 (legibility): the snapshot fields the board reads to explain
itself. The client renders; these pin what the server ships."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict
from ltg_game_server.snapshot import build_snapshot


def _filler(cid):
    return {"id": cid, "name": f"Card {cid}", "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "effects": [{"kind": "draw", "amount": 0}]}


def _state(**enemy):
    party = [{"id": h, "name": h.title(), "hp": 20, "power": 2, "hand_size": 1,
              "identity": ["U"], "row": "front", "attack_mode": "melee",
              "library": [_filler(f"{h}{i}") for i in range(5)]} for h in ("ann", "bo")]
    foe = {"id": "brute", "name": "Brute", "hp": 20, "level": 2, "power": 2, **enemy}
    return settle(state_from_dict({"party": party, "enemies": [foe]}, seed=1))


def _play(st, steps=40):
    for _ in range(steps):
        acts = legal_actions(st)
        if not acts:
            break
        st = apply_action(st, next((a for a in acts if a.kind in ("pass", "end_turn")),
                                   acts[0]))[0]
    return st


# --- M2.1 · the Chronicle ---------------------------------------------------- #

def test_the_log_tail_is_oldest_first_so_the_newest_line_is_last():
    st = _play(_state())
    seqs = [row["seq"] for row in build_snapshot(st, {"ann", "bo"})["log"]]
    assert len(seqs) > 3
    assert seqs == sorted(seqs)
    assert seqs[-1] == max(i for i, e in enumerate(st.log) if e.type != "intent_declared")


# --- M2.7 · why a hand card is dimmed -------------------------------------- #

def _example_fights():
    import json
    from pathlib import Path

    from ltg_combat.scenario import state_from_loadouts
    ex = Path(__file__).resolve().parent.parent / "examples"
    load = lambda n: json.loads((ex / n).read_text())  # noqa: E731
    yield state_from_loadouts([load("loadout_soren.json"), load("loadout_ys.json")],
                              load("encounter_a.json"))
    yield state_from_loadouts([load("loadout_mira.json")], load("encounter_c.json"))


def test_a_card_has_a_reason_exactly_when_it_cannot_be_cast():
    """The chip never lies: across seeded random play, a hand card carries no
    reason iff the priority holder is offered a cast of it."""
    import random

    from ltg_combat.engine import unplayable_reason
    checked = 0
    for n, st in enumerate(_example_fights()):
        st = settle(st)
        rng = random.Random(f"m2.7:{n}")
        for _ in range(160):
            acts = legal_actions(st)
            if not acts or st.result:
                break
            if st.pending_choice is None and not st.settle and st.phase != "capacity":
                cast = {a.card_id for a in acts if a.kind == "cast"}
                for c in st.party:
                    for card in c.hand:
                        why = unplayable_reason(st, c.id, card)
                        if c.id == st.priority and c.alive:
                            assert (why is None) == (card.id in cast), (card.name, why)
                            checked += 1
                        else:
                            assert why in ("waiting", "downed")
            st = apply_action(st, rng.choice(acts))[0]
    assert checked > 50


def test_the_hand_ships_its_reasons():
    st = _state()
    snap = build_snapshot(st, {"ann", "bo"})
    for ch in snap["characters"]:
        assert all("unplayable_reason" in card for card in ch["hand"])
    idle = next(ch for ch in snap["characters"] if ch["id"] != st.priority)
    assert {card["unplayable_reason"] for card in idle["hand"]} == {"waiting"}


# --- M2.13 · the veiled classifier -------------------------------------------- #

def _intent(*effects):
    from ltg_combat.state import Intent
    return Intent(name="X", action_type="ability", effects=list(effects), target_id="ann")


def test_a_shove_on_a_hero_is_interference_and_corpse_work_is_summon():
    from ltg_combat.serialize import intent_category
    from ltg_core.schema import ConsumeCorpse, Control, DealDamage, Move
    at = lambda side: {"mode": "chosen", "side": side}  # noqa: E731
    assert intent_category(_intent(Move(target=at("ally")))) == "interference"
    assert intent_category(_intent(Control(target=at("any")))) == "summon"
    assert intent_category(_intent(ConsumeCorpse(target=at("any")))) == "summon"
    # A hostile payload on the same intent still names the danger.
    assert intent_category(_intent(DealDamage(amount=3, target=at("ally")),
                                   ConsumeCorpse(target=at("any")))) == "threat"


# --- M2.8 / M2.9 / M2.12 / M2.13 · what the cards and banner carry ----------- #

def test_cards_wear_their_lockdown_as_chips():
    from ltg_combat.serialize import status_chips
    from ltg_combat.state import PreventTag
    st = _state()
    ann, brute = st.character("ann"), st.enemy("brute")
    ann.prevent_tags.append(PreventTag(parameter="cast"))
    ann.capacity_mod = -1
    ann.taunted_to = "brute"
    brute.stunned = 1
    labels = [c["label"] for c in status_chips(st, ann)]
    assert labels[:3] == ["silenced", "sapped −1", "taunted"]
    assert all(c["tone"] == "bane" for c in status_chips(st, ann)[:3])
    assert "Brute" in status_chips(st, ann)[2]["tip"]
    assert [c["label"] for c in status_chips(st, brute)] == ["stunned"]
    snap = build_snapshot(st, {"ann", "bo"})
    hero = next(c for c in snap["characters"] if c["id"] == "ann")
    assert hero["mana"]["sapped"] == 1
    assert [c["label"] for c in hero["status_chips"]][:1] == ["silenced"]
    assert next(c for c in snap["creatures"])["status_chips"][0]["label"] == "stunned"


def test_the_boss_card_carries_its_fury_and_its_neglect():
    st = _state(is_boss=True, neglect=2)
    boss = build_snapshot(st, {"ann", "bo"})["creatures"][0]
    assert boss["enraged"] is False
    assert boss["neglect"] == {"amount": 2, "hurt": False}
    assert boss["guarded_by"] == []
    st.enemy("brute").enraged = True
    assert build_snapshot(st, {"ann", "bo"})["creatures"][0]["enraged"] is True


def test_the_banner_previews_the_next_arrival_and_names_the_guards():
    from ltg_combat.serialize import objective_block
    from ltg_combat.state import Objective
    st = _state()
    st.objective = Objective(kind="race", turns=5, target_id="brute", guards=["brute"])
    # (a body guarding itself is nonsense, but the shield reads the same)
    assert build_snapshot(st, {"ann"})["creatures"][0]["guarded_by"] == ["Brute"]
    st.objective = Objective(kind="survive", turns=5, reinforcements=[
        {"turn": st.turn + 1, "ids": ["brute", "brute"], "arrived": False}])
    assert objective_block(st)["next_arrival"] == {"when": "next round", "line": "2 Brute"}
    st.objective.reinforcements[0]["arrived"] = True
    assert objective_block(st)["next_arrival"] is None


# --- M2.17 · the aiming preview --------------------------------------------- #

def _attack_on(st, target):
    return next(a for a in legal_actions(st) if a.kind == "attack" and a.target_id == target)


def test_the_attack_preview_runs_the_real_damage_rules():
    from ltg_combat.engine import attack_preview
    from ltg_combat.state import PreventTag
    st = settle(_state(hp=3))
    act = _attack_on(st, "brute")
    assert attack_preview(st, act) == {"damage": 2, "soaked": 0, "prevented": 0,
                                       "kills": False, "breaks": False}
    st.enemy("brute").hp = 2
    assert attack_preview(st, act)["kills"] is True
    st.enemy("brute").temp_mod = 1
    p = attack_preview(st, act)
    assert (p["damage"], p["soaked"], p["kills"]) == (1, 1, False)
    st.enemy("brute").prevent_tags.append(PreventTag(parameter="combat_damage"))
    assert attack_preview(st, act)["prevented"] == 1
    # Read-only: the real state is untouched.
    assert st.enemy("brute").hp == 2 and st.enemy("brute").prevent_tags


def test_the_snapshot_ships_the_preview_line():
    st = settle(_state())
    rows = [a for a in build_snapshot(st, {"ann", "bo"})["legal_actions"] if a["kind"] == "attack"]
    assert rows and rows[0]["preview"] == "→ 2"


# --- M2.19 · damage names its mode ------------------------------------------ #

def test_a_damage_event_carries_its_mode():
    st = settle(_state())
    st = apply_action(st, _attack_on(st, "brute"))[0]
    for _ in range(10):
        if any(e.type == "damage" for e in st.log):
            break
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    hit = next(e for e in st.log if e.type == "damage" and e.data["target"] == "brute")
    assert hit.data["mode"] == "melee attack"
