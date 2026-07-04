"""The two Design Update 04 showcase encounters (examples/encounter_*.json) loaded,
paired with a party, and driven far enough to see every new enemy ability fire:
the valuation Drain, on_spell_cast / on_hit reactions, condition-gated Fortify,
Swarm token spawning, the Debilitate wound, and Evasive repositioning."""

from __future__ import annotations

import json
from pathlib import Path

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _encounter(filename):
    return json.loads((EXAMPLES / filename).read_text())


def _fighter(cid="knight", power=6, hp=30):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["G"], "row": "front", "attack_mode": "melee", "library": []}


def _caster(cid="mage"):
    zap = {"id": "zap", "name": "Zap", "source_name": "Zap", "rarity": "common",
           "level": 1, "type": "Instant", "timing": "instant",
           "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "deal_damage", "amount": 1,
                        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]}
    lib = [dict(zap, id=f"zap{i}") for i in range(4)]
    return {"id": cid, "name": cid, "hp": 30, "power": 3, "hand_size": 1,
            "identity": ["U"], "row": "front", "attack_mode": "melee", "library": lib}


def _drive(st, turns, prefer, prefer_turns=None):
    """Advance up to `turns` turns. On each of the active player's main-phase decisions,
    attempt each (kind, kwargs) in `prefer` once per turn (only while turn ≤ prefer_turns);
    otherwise pass/end."""
    prefer_turns = turns if prefer_turns is None else prefer_turns
    cur, done = st.turn, set()
    while st.result is None and st.turn <= turns:
        if st.turn != cur:
            cur, done = st.turn, set()
        acts = legal_actions(st)
        if not acts:
            break
        chosen = None
        if not st.stack and st.turn <= prefer_turns:
            for i, (kind, kw) in enumerate(prefer):
                if i in done:
                    continue
                cand = next((a for a in acts if a.kind == kind
                             and all(getattr(a, k) == v for k, v in kw.items())), None)
                if cand is not None:
                    chosen, _ = cand, done.add(i)
                    break
        if chosen is None:
            chosen = next((a for a in acts if a.kind in ("pass", "end_turn")), acts[0])
        st = apply_action(st, chosen)[0]
    return st


def _types(st):
    return [e.type for e in st.log]


def _intents(st):
    return [e.data.get("intent", "") for e in st.log if e.type == "intent_declared"]


# --------------------------------------------------------------------------- #
# Crimson Coven: valuation Drain, on_spell_cast reaction, Evasive movement.
# --------------------------------------------------------------------------- #
def test_crimson_coven_showcase():
    enc = _encounter("encounter_crimson_coven.json")
    st = state_from_dict({"party": [_caster("mage"), _fighter("knight")],
                          "enemies": enc["enemies"], "tokens": enc.get("tokens", {})})
    st = _drive(st, turns=3, prefer=[("cast", {})])  # cast a spell each turn to bait the curse

    types, intents = _types(st), _intents(st)
    assert "enemy_react" in types                       # the Adept's on_spell_cast Curse fired
    assert "wound" in types                             # …wounding the caster -1/-1
    assert any(i.startswith("Life Drain") for i in intents)   # the Adept declared its Drain
    assert "enemy_move" in types                        # the Bloodbat repositioned (Evasive)


# --------------------------------------------------------------------------- #
# Ironhide's Warband: on_hit Punish, condition Fortify, Swarm, Debilitate wound.
# --------------------------------------------------------------------------- #
def test_ironhide_warband_showcase():
    enc = _encounter("encounter_ironhide_warband.json")
    st = state_from_dict({"party": [_fighter("knight", power=6, hp=40),
                                    _caster("mage")],
                          "enemies": enc["enemies"], "tokens": enc.get("tokens", {})})
    ironhide = next(e["id"] for e in enc["enemies"] if e["name"].startswith("Ironhide"))
    # Strike Ironhide only on turn 1 — enough to bloody it and trip Punish; then let it
    # survive to Fortify on turn 2 (a second hit would kill it before the heal).
    st = _drive(st, turns=4, prefer=[("attack", {"target_id": ironhide})], prefer_turns=1)

    types, intents = _types(st), _intents(st)
    assert "token_created" in types                     # the Broodmother spawned Husklings
    assert any(e.type == "token_created" and e.data.get("created_by")     # …on the enemy side
               for e in st.log)
    assert "enemy_react" in types                       # Ironhide's on_hit Punish answered a melee hit
    assert "heal" in types                              # Fortify healed Ironhide once bloodied
    assert any(i.startswith("Second Wind") for i in intents)   # …the Fortify was declared
    assert "wound" in types                             # the Hexer's Withering Hex chipped a hero


# --------------------------------------------------------------------------- #
# Both files are budget-consistent framework enemies (chassis + components).
# --------------------------------------------------------------------------- #
def test_encounters_load_as_framework_enemies():
    for fn in ("encounter_crimson_coven.json", "encounter_ironhide_warband.json"):
        enc = _encounter(fn)
        st = state_from_dict({"party": [_fighter()], "enemies": enc["enemies"],
                              "tokens": enc.get("tokens", {})})
        assert st.enemies, fn
        # at least one enemy carries components (the framework "mind")
        assert any(e.components for e in st.enemies), fn
