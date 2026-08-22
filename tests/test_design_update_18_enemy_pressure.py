"""Design Update 18 — Enemy pressure (playtest).

Four rules, all driven by the same session at the table: enemies whose taunts
read as skipped turns (§D18-1), abilities that hit for less than the creature's
own sword (§D18-2/§D18-3), a kit that crowds the basic attack out entirely
(§D18-3), and row assaults that fizzled to Hexproof, named no row, and lit no
ground (§D18-4).
"""

from __future__ import annotations

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.serialize import intent_category, intent_rows, veiled_intent
from ltg_game_server.content import (
    BOSS_ABILITY_BONUS,
    ENEMY_ABILITY_BONUS,
    ROW_ABILITY_BONUS,
    _bump_enemy_power,
    enrage_scale,
)


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", power=2, hp=30, keywords=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 1,
            "identity": ["U"], "row": row, "attack_mode": "melee",
            "keywords": keywords or [],
            "library": [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid="brute", power=5, hp=30, components=None):
    return {"id": eid, "name": eid, "hp": hp, "level": 3, "power": power,
            "attack_mode": "melee", "row": "front",
            "intent": {"name": "Smash", "amount": power, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"},
            "components": components or []}


def _comp(cid, verbs, **kw):
    base = {"id": cid, "timing": "proactive", "priority": 10,
            "target_rule": "valuation", "telegraph": cid, "verbs": verbs}
    base.update(kw)
    return base


def _hero_hit(amount):
    return {"kind": "deal_damage", "amount": amount,
            "target": {"mode": "chosen", "side": "ally", "targeted": True}}


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


def _step(state):
    """One legal no-op-ish action: pass a window, else end a hero's turn."""
    a = next((a for a in legal_actions(state) if a.kind == "pass"), None)
    if a is None:
        a = next((a for a in legal_actions(state) if a.kind == "end_turn"), None)
    return apply_action(state, a)[0] if a is not None else None


def _declare(state):
    """Advance to the FIRST moment the enemy has a declared intent, and stop —
    reading later than that would see the next round's intent instead."""
    for _ in range(80):
        if state.enemies and state.enemies[0].round_intent is not None:
            return state
        nxt = _step(state)
        if nxt is None:
            return state
        state = nxt
    return state



# --------------------------------------------------------------------------- #
# §D18-1 — a taunt never fires alone
# --------------------------------------------------------------------------- #
def test_a_taunt_only_component_gains_a_blow_for_the_enemys_power():
    grab = _comp("challenge", [{"kind": "taunt",
                                "target": {"mode": "chosen", "side": "ally",
                                           "targeted": True}}])
    st = _declare(_state([_char("p")], [_enemy(power=5, components=[grab])]))
    intent = st.enemies[0].round_intent
    assert intent is not None and intent.name == "challenge"
    kinds = [e.kind for e in intent.effects]
    # The bite is prepended, aimed at the same body the taunt drags.
    assert kinds == ["deal_damage", "taunt"]
    assert intent.effects[0].amount == 5           # the enemy's CURRENT Power
    assert intent.effects[0].target == intent.effects[1].target


def test_a_taunt_that_already_bites_is_left_alone():
    grab = _comp("challenge", [_hero_hit(4),
                               {"kind": "taunt",
                                "target": {"mode": "chosen", "side": "ally",
                                           "targeted": True}}])
    st = _declare(_state([_char("p")], [_enemy(power=5, components=[grab])]))
    intent = st.enemies[0].round_intent
    assert [e.kind for e in intent.effects] == ["deal_damage", "taunt"]
    assert intent.effects[0].amount == 4           # the author's number stands


def test_the_generation_gate_rejects_a_bare_taunt():
    from ltg_game_server.llm import _taunt_problems
    bare = {"enemies": [{"name": "Zealot", "components": [
        {"id": "challenge", "verbs": [{"kind": "taunt"}]}]}]}
    assert any("taunts but deals no damage" in p for p in _taunt_problems(bare))
    paired = {"enemies": [{"name": "Zealot", "components": [
        {"id": "challenge", "verbs": [{"kind": "deal_damage", "amount": 5},
                                      {"kind": "taunt"}]}]}]}
    assert _taunt_problems(paired) == []


# --------------------------------------------------------------------------- #
# §D18-3 — the sword competes with the kit
# --------------------------------------------------------------------------- #
def test_a_component_weaker_than_the_sword_is_passed_over():
    """The playtest complaint: a high-Power enemy spending every turn on a
    'combat ability' that bypasses its own Power and hits for less."""
    weak = _comp("poke", [_hero_hit(3)], cooldown=1)
    st = _declare(_state([_char("p")], [_enemy(power=5, components=[weak])]))
    intent = st.enemies[0].round_intent
    assert intent.name == "Smash" and intent.attack_power == 5   # the sword landed


def test_a_component_that_beats_the_sword_still_fires():
    strong = _comp("cleave", [_hero_hit(9)], cooldown=1)
    st = _declare(_state([_char("p")], [_enemy(power=5, components=[strong])]))
    assert st.enemies[0].round_intent.name == "cleave"


def test_a_rider_is_never_suppressed_however_small_the_hit():
    """Only a PURE damage rule competes with the sword — 'deal 2 and stun' is a
    different kind of turn and always keeps its slot."""
    mixed = _comp("daze", [_hero_hit(2),
                           {"kind": "stun",
                            "target": {"mode": "chosen", "side": "ally",
                                       "targeted": True}}], cooldown=1)
    st = _declare(_state([_char("p")], [_enemy(power=5, components=[mixed])]))
    assert st.enemies[0].round_intent.name == "daze"


def test_the_cadence_forces_a_swing_after_two_quiet_rounds():
    """A kit of short-cooldown non-damage rules used to crowd the sword out
    forever — the enemy never swung and its Power was dead weight."""
    pump = _comp("stoke", [{"kind": "counters", "power": 1, "toughness": 1,
                            "target": {"mode": "self"}}], cooldown=1, priority=5)
    st = _state([_char("p", hp=200)], [_enemy(power=5, components=[pump])])
    by_turn = {}
    for _ in range(400):
        e = st.enemies[0] if st.enemies else None
        if e is not None and e.round_intent is not None:
            by_turn.setdefault(st.turn, e.round_intent.name)
        nxt = _step(st)
        if nxt is None:
            break
        st = nxt
    names = [by_turn[t] for t in sorted(by_turn)]
    assert len(names) >= 6, names
    # Never three non-attack intents in a row.
    assert "Smash" in names
    runs = 0
    for n in names:
        runs = 0 if n == "Smash" else runs + 1
        assert runs <= 2, names


# --------------------------------------------------------------------------- #
# §D18-4 — a row shape aims at ground, not a name
# --------------------------------------------------------------------------- #
def _scoped_row_comp(scope="row"):
    return _comp("sweep", [{"kind": "deal_damage", "amount": 6,
                            "target": {"mode": "chosen", "side": "ally",
                                       "targeted": True, "scope": scope}}],
                 action_type="attack")


def test_a_scoped_row_shape_becomes_a_positional_intent():
    st = _declare(_state([_char("a", row="front"), _char("b", row="front")],
                         [_enemy(components=[_scoped_row_comp()])]))
    intent = st.enemies[0].round_intent
    assert intent.name == "sweep"
    assert intent.target_id is None and intent.target_row == "front"
    # Every hostile verb now reads occupancy live — untargeted ground.
    assert all(not e.target.targeted for e in intent.effects)
    assert intent_category(intent) == "row assault"


def test_a_row_assault_no_longer_fizzles_against_hexproof():
    """The pick used to be a TARGETED effect, so Hexproof on it cancelled the
    whole area — and with an all-hexproof row the rule was skipped outright."""
    st = _state([_char("a", row="front", hp=30, keywords=["hexproof"]),
                 _char("b", row="front", hp=30, keywords=["hexproof"])],
                [_enemy(components=[_scoped_row_comp()])])
    st = _declare(st)
    assert st.enemies[0].round_intent.target_row == "front"
    for _ in range(120):
        if st.character("a").hp < 30:
            break
        nxt = _step(st)
        if nxt is None:
            break
        st = nxt
    assert st.character("a").hp < 30 and st.character("b").hp < 30


def test_a_blast_lights_its_whole_footprint_and_names_it():
    st = _declare(_state([_char("a", row="mid")],
                         [_enemy(components=[_scoped_row_comp("blast")])]))
    e = st.enemies[0]
    entry = veiled_intent(st, e)
    assert set(entry["target_rows"]) == {"front", "mid", "rear"}
    assert entry["target_row"] == "mid"          # the primary is first
    assert "front" in entry["line"] and "rear" in entry["line"]


def test_the_telegraph_names_the_row_it_is_coming_for():
    st = _declare(_state([_char("a", row="front")],
                         [_enemy(components=[_scoped_row_comp()])]))
    entry = veiled_intent(st, st.enemies[0])
    assert "a row of your party" not in entry["line"]
    assert "your front row" in entry["line"]


def test_a_component_that_needs_its_own_pick_is_not_converted():
    """A rule that also exiles a corpse still runs down the ordinary path —
    discarding its target would silently drop half the ability."""
    comp = _comp("corpse_burst",
                 [{"kind": "exile", "target": {"mode": "chosen", "side": "enemy",
                                               "state": "corpse", "targeted": True}},
                  {"kind": "deal_damage", "amount": 3,
                   "target": {"mode": "all", "side": "ally", "rows": ["front"]}}],
                 target_rule="corpse")
    st = _state([_char("a", row="front")], [_enemy(components=[comp])])
    from ltg_combat.engine import _row_shape_footprint
    assert _row_shape_footprint(st, st.enemies[0], st.enemies[0].components[0]) is None


def test_intent_rows_reads_a_hand_authored_footprint_back_off_the_verbs():
    """Legacy content that scoped its verbs without a component `target_row`
    still names its ground instead of the anonymous 'a row of your party'."""
    from ltg_combat.state import Intent
    from ltg_core.schema import DealDamage, t_row
    intent = Intent(name="Sweep", action_type="attack", target_id=None,
                    effects=[DealDamage(amount=3, target=t_row("ally", "rear"))])
    assert intent_rows(intent) == ["rear"]


# --------------------------------------------------------------------------- #
# §D18-2 — the balance register carries the abilities too
# --------------------------------------------------------------------------- #
def test_the_register_lifts_hostile_ability_damage_with_power():
    scen = {"enemies": [_enemy(power=1, components=[_comp("burn", [_hero_hit(4)])])]}
    out = _bump_enemy_power(scen, party_size=1)
    e = out["enemies"][0]
    assert e["power"] == 3                                   # 1 + ENEMY_POWER_BONUS
    assert e["components"][0]["verbs"][0]["amount"] == 4 + ENEMY_ABILITY_BONUS


def test_a_row_shape_gets_the_dodgeable_premium():
    row = _comp("sweep", [{"kind": "deal_damage", "amount": 4,
                           "target": {"mode": "all", "side": "ally",
                                      "rows": ["front"]}}])
    out = _bump_enemy_power({"enemies": [_enemy(components=[row])]}, party_size=1)
    amount = out["enemies"][0]["components"][0]["verbs"][0]["amount"]
    assert amount == 4 + ENEMY_ABILITY_BONUS + ROW_ABILITY_BONUS


def test_heals_and_self_pumps_are_left_alone():
    mend = _comp("mend", [{"kind": "heal", "amount": 5,
                           "target": {"mode": "chosen", "side": "enemy",
                                      "targeted": True}}])
    out = _bump_enemy_power({"enemies": [_enemy(components=[mend])]}, party_size=1)
    assert out["enemies"][0]["components"][0]["verbs"][0]["amount"] == 5


def test_a_boss_gets_the_boss_bonus_on_its_abilities():
    boss = _enemy(power=3, components=[_comp("breath", [_hero_hit(7)])])
    boss["is_boss"] = True
    out = _bump_enemy_power({"enemies": [boss]}, party_size=1)
    assert out["enemies"][0]["components"][0]["verbs"][0]["amount"] == 7 + BOSS_ABILITY_BONUS


@pytest.mark.parametrize("size,power,tough,burn", [
    (1, 2, 2, 3),     # solo: the authored climax, untouched
    (2, 4, 3, 5),
    (4, 8, 5, 8),     # a four-hero party meets a fury built for four
])
def test_a_boss_enrage_scales_with_the_party_it_erupts_against(size, power, tough, burn):
    """§D18-2: the authored magnitudes are per-enemy-level and never saw party
    size — so the climax of a four-hero fight was the same '+2/+2 and a small
    burn' a solo hero met, against four times the damage and four times the
    actions."""
    fury = {"id": "fury", "archetype": "Enrage", "priority": 5, "target_rule": "self",
            "telegraph": "FURY", "verbs": [
                {"kind": "counters", "power": 2, "toughness": 2,
                 "target": {"mode": "self"}},
                {"kind": "deal_damage", "amount": 3,
                 "target": {"mode": "all", "side": "ally"}}]}
    boss = _enemy(components=[fury])
    boss["is_boss"] = True
    verbs = _bump_enemy_power({"enemies": [boss]}, size)["enemies"][0]["components"][0]["verbs"]
    assert (verbs[0]["power"], verbs[0]["toughness"]) == (power, tough)
    assert verbs[1]["amount"] == burn
    # The Enrage takes the party-size scale INSTEAD of the flat ability bonus,
    # never both.
    assert verbs[1]["amount"] != 3 + BOSS_ABILITY_BONUS or size == 1


def test_enrage_lethality_outruns_padding():
    """Fury should hit much harder, not merely last much longer."""
    for n in (2, 3, 4):
        lethal, pad = enrage_scale(n)
        assert lethal > pad > 1.0
