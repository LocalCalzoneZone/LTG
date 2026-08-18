"""greedy-1.3.0 — the honest-cast pass, and the castability telemetry.

§G13-1 Live-effect reads: a `cast_mode: reaction` conditional is not
main-phase damage; a reaction-ONLY damage card is spent INTO enemy windows
(rule 2d) instead of being cast proactively into a guaranteed whiff.
§G13-2 Untargeted support: mode:all/self pumps and heals pass the pre-swing
and sink guards (the 1.2.x guards demanded a target id, so every untargeted
card was silently unplayable — 0 casts across thousands of games).
§G13-3 Idle channel swap (rule 7a): at the two-channel cap, a pure
trigger-engine channel that has never fired after two full rounds is dropped
for a channel waiting in hand. Continuous auras are never dropped.
§G13-4 Runner telemetry: every RunRecord carries card_flow (hand/offered/
cast_rules per card), decision_rules, condition_whiffs, and channel_stats —
and stays deterministic for the repro key.
§G13-5 Tester aggregation: card_autopsy and channel_economy turn a dead
card's bare 0 into a NAMED cause (never-castable / declined / whiffing).
§G14-1 (greedy-1.4.0) Mana literacy: the capacity colour lock follows the
deck's pip deficit, not the option order — first-option locking banked
identity[0] every turn, leaving a two-colour kit's off-colour half
structurally uncastable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/autoplay-tester"))

from ltg_autoplay_tester.probes import card_autopsy, channel_economy  # noqa: E402
from ltg_combat.autoplay import make_policy, run_one  # noqa: E402
from ltg_combat.autoplay.policies import (  # noqa: E402
    _constant_damage,
    _sink_ranks,
    iter_live_effects,
)
from ltg_core.schema import Card  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_CH_ENEMY = {"mode": "chosen", "side": "enemy", "targeted": True}
_ALL_ALLY = {"mode": "all", "side": "ally", "targeted": False}


def _card(cid, name, timing, cost, effects):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": 1, "type": "Sorcery" if timing == "sorcery" else "Instant",
            "timing": timing, "cost": cost, "effects": effects,
            "validated": True}


def _hero(library, hp=60, power=1, hand_size=3, cid="hero"):
    return {"id": cid, "name": cid.title(), "hp": hp, "power": power,
            "hand_size": hand_size, "identity": ["W"], "row": "front",
            "attack_mode": "melee", "library": library}


def _enemy(eid="brute", hp=24, amount=1):
    return {"id": eid, "name": eid.title(), "hp": hp, "level": 1,
            "intent": {"name": "Hit", "amount": amount,
                       "action_type": "ability", "intent_type": "attack",
                       "targeting": "lowest_hp_party", "mode": "melee"}}


# The reaction-only ping — cutting_cadence's shape: its ENTIRE effect is
# gated on cast_mode: reaction; cast proactively it resolves to nothing.
PING = _card("ping", "Ping", "instant", {"generic": 0, "colors": {"W": 1}}, [
    {"kind": "conditional",
     "condition": {"kind": "cast_mode", "mode": "reaction"},
     "effects": [{"kind": "deal_damage", "amount": 3, "target": _CH_ENEMY}]}])

# The untargeted rally — rallying_refrain's shape: party-wide pump + heal,
# no target id anywhere.
RALLY = _card("rally", "Rally", "instant", {"generic": 0, "colors": {"W": 1}}, [
    {"kind": "pump", "power": 1, "toughness": 1, "target": _ALL_ALLY,
     "duration": "this_turn"},
    {"kind": "heal", "amount": 2, "target": _ALL_ALLY}])

# A conditional that can never hold on this kit: the hero stands in front,
# the damage wants the rear row — every cast whiffs (`condition_false`).
MAYBE = _card("maybe_bolt", "Maybe Bolt", "sorcery", {"generic": 1}, [
    {"kind": "conditional",
     "condition": {"kind": "caster_property", "property": "row",
                   "row": "rear"},
     "effects": [{"kind": "deal_damage", "amount": 4, "target": _CH_ENEMY}]}])

# A card the ladder has no rule for: pure recursion, no sinkable kind.
TUTOR = _card("tutor", "Tutor", "instant", {"generic": 0, "colors": {"W": 1}}, [
    {"kind": "move_card", "count": 1, "source": "graveyard",
     "destination": "hand", "filter_type": "channeled",
     "filter_level_compare": "any", "filter_level": 1,
     "shuffle_after": False, "target": {"mode": "self"}}])

# Off-identity cost (the hero is mono-W): a cast can never be offered.
LOCKED = _card("locked", "Locked", "instant", {"generic": 0,
                                              "colors": {"B": 1}}, [
    {"kind": "deal_damage", "amount": 2, "target": _CH_ENEMY}])


def _idle_engine(cid):
    """A trigger-engine channel that can never fire here: it waits on
    life_gain and the deck holds no heals."""
    return _card(cid, cid.title(), "channeled", {"generic": 0,
                                                 "colors": {"W": 1}}, [
        {"trigger": {"event": "life_gain", "who": "you"},
         "kind": "counters", "power": 1, "toughness": 1,
         "target": {"mode": "self"}}])


def _spec(library, **hero_kw):
    return {"name": "g13", "party": [_hero(library, **hero_kw)],
            "enemies": [_enemy()]}


# ========================================================================== #
# §G13-1 — live-effect reads and the reaction-only ping
# ========================================================================== #
def test_live_effects_skip_dead_cast_mode_branches():
    card = Card.model_validate(PING)
    assert _constant_damage(card, "action") == 0
    assert _constant_damage(card, "reaction") == 3
    # The dead branch is invisible to the sink classifier too — no kinds leak.
    assert _sink_ranks(card, "action") == []
    kinds = {getattr(e, "kind", None)
             for e in iter_live_effects(card.effects, "reaction")}
    assert "deal_damage" in kinds


def test_reaction_only_ping_is_spent_into_windows_not_whiffed():
    rec = run_one(_spec([dict(PING)] * 3), make_policy("greedy"), seed=2)
    m = rec["characters"]["hero"]
    drawn, cast = m["card_events"].get("ping", [0, 0])
    assert cast > 0, "the ping never got cast at all"
    # Every cast landed in a window (rule 2d) — none whiffed its condition.
    assert m["condition_whiffs"].get("ping", 0) == 0
    assert any(r.startswith("2d-") for r in m["decision_rules"])
    assert set(m["card_flow"]["ping"]["cast_rules"]) == {"2d-reaction-ping"}


# ========================================================================== #
# §G13-2 — untargeted support passes the guards
# ========================================================================== #
def test_untargeted_pump_heal_card_is_playable():
    rec = run_one(_spec([dict(RALLY)] * 3), make_policy("greedy"), seed=2)
    m = rec["characters"]["hero"]
    assert m["card_events"].get("rally", [0, 0])[1] > 0
    rules = set(m["card_flow"]["rally"]["cast_rules"])
    assert rules <= {"8-prime-swing", "11-sink"} and rules


# ========================================================================== #
# §G13-3 — the idle-channel swap
# ========================================================================== #
def test_idle_trigger_engine_is_dropped_for_a_waiting_channel():
    library = [_idle_engine("engine_a"), _idle_engine("engine_b"),
               _idle_engine("engine_c")]
    rec = run_one(_spec(library), make_policy("greedy"), seed=2)
    m = rec["characters"]["hero"]
    stats = m["channel_stats"]
    # All three engines got their turn on the battlefield…
    assert sorted(stats) == ["engine_a", "engine_b", "engine_c"]
    # …which requires at least one voluntary drop at the two-channel cap.
    assert sum(cs["drops"] for cs in stats.values()) >= 1
    assert "7a-drop-idle-channel" in m["decision_rules"]
    # Nothing ever fired — that is exactly why they were droppable.
    assert all(cs["triggers"] == 0 for cs in stats.values())


# ========================================================================== #
# §G13-4 — runner telemetry, deterministic
# ========================================================================== #
def test_telemetry_fields_and_determinism():
    library = [dict(PING), dict(RALLY), dict(MAYBE), dict(TUTOR), dict(LOCKED)]
    p = make_policy("greedy")
    rec = run_one(_spec(list(library), hand_size=5), p, seed=5)
    assert rec == run_one(_spec(list(library), hand_size=5),
                          make_policy("greedy"), seed=5)
    m = rec["characters"]["hero"]
    # Castability: LOCKED is off-identity — held, never offered.
    flow = m["card_flow"]
    assert flow["locked"]["hand"] > 0 and flow["locked"]["offered"] == 0
    # TUTOR is affordable — offered, and (no ladder rule wants it) never cast.
    assert flow["tutor"]["offered"] > 0
    assert m["card_events"].get("tutor", [0, 0])[1] == 0
    # MAYBE reads as 4 damage optimistically, casts, and whiffs every time.
    maybe_casts = m["card_events"].get("maybe_bolt", [0, 0])[1]
    assert maybe_casts > 0
    assert m["condition_whiffs"].get("maybe_bolt", 0) == maybe_casts
    # Every decision the policy made is attributed to a rule.
    assert sum(m["decision_rules"].values()) > 0


# ========================================================================== #
# §G14-1 — the capacity colour lock follows the deck
# ========================================================================== #
def test_capacity_lock_follows_the_deck_not_the_option_order():
    # A GG-costed instant under a ["W", "G"] identity: first-option locking
    # banks W every turn, so the pool never holds two G and the card is dead
    # forever. The deficit lock banks G and the card plays (as a sink, after
    # the attack — an instant, because a sorcery competes with rule 10 for
    # the one proactive action).
    gg = _card("verdant_surge", "Verdant Surge", "instant",
               {"generic": 0, "colors": {"G": 2}},
               [{"kind": "counters", "power": 2, "toughness": 2,
                 "target": {"mode": "self"}}])
    hero = _hero([dict(gg)] * 3)
    hero["identity"] = ["W", "G"]
    spec = {"name": "g14", "party": [hero], "enemies": [_enemy()]}
    rec = run_one(spec, make_policy("greedy"), seed=2)
    m = rec["characters"]["hero"]
    assert m["card_flow"]["verdant_surge"]["offered"] > 0
    assert m["card_events"].get("verdant_surge", [0, 0])[1] > 0
    assert "forced-mana" in m["decision_rules"]


# ========================================================================== #
# §G13-5 — the Tester's autopsy and channel economy
# ========================================================================== #
def test_card_autopsy_names_the_causes():
    library = [dict(PING), dict(RALLY), dict(MAYBE), dict(TUTOR), dict(LOCKED)]
    loadout = {"cards": list(library)}
    p = make_policy("greedy")
    records = [run_one(_spec(list(library), hand_size=5), p, seed=s)
               for s in range(6)]
    rows = {r["card_id"]: r for r in card_autopsy(records, "hero", loadout)}
    assert rows["locked"]["status"] == "never-castable"
    assert rows["tutor"]["status"] == "declined"
    assert rows["maybe_bolt"]["status"] == "whiffing"
    assert rows["ping"]["status"] == "ok"
    assert rows["ping"]["cast_rules"]  # names the rules that played it
    # The sort surfaces the pathologies first.
    ordered = [r["card_id"] for r in card_autopsy(records, "hero", loadout)]
    assert ordered.index("locked") < ordered.index("ping")


def test_channel_economy_reads_the_idle_engine():
    library = [_idle_engine("engine_a"), _idle_engine("engine_b"),
               _idle_engine("engine_c")]
    loadout = {"cards": list(library)}
    p = make_policy("greedy")
    records = [run_one(_spec(list(library)), p, seed=s) for s in range(4)]
    rows = {r["card_id"]: r for r in channel_economy(records, "hero", loadout)}
    assert set(rows) == {"engine_a", "engine_b", "engine_c"}
    for r in rows.values():
        assert r["trigger_engine"] is True
        if r["starts"]:
            assert r["triggers_per_start"] == 0
            assert r["reserved_manaturns_per_game"] is not None
