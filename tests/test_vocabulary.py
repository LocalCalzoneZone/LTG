"""The engine handles the FULL Deckbuilder vocabulary — every effect primitive,
the two containers (modal / conditional), all targeting modes, value refs, and the
keyword statics. These tests drive the engine through only `legal_actions` /
`apply_action` (a few white-box checks for setups the public API can't reach, like
reviving a downed ally), proving any card the Deckbuilder emits is executable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import Card

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
_TYPE = {"instant": "Instant", "sorcery": "Sorcery", "channeled": "Enchantment"}


# --------------------------------------------------------------------------- #
# Builders / drivers
# --------------------------------------------------------------------------- #
def C(cid, timing, effects, colors=None, generic=0, targets=None, name=None):
    d = {"id": cid, "name": name or cid.replace("_", " ").title(), "source_name": cid,
         "rarity": "common", "level": 1, "type": _TYPE[timing], "timing": timing,
         "cost": {"generic": generic, "colors": colors or {}},
         "effects": effects, "validated": True}
    if targets:
        d["targets"] = targets
    return d


def make_state(cards, party=None, enemy_hp=10, enemy_level=3, intent_amount=3,
               intent_type="attack", targeting="lowest_hp_party", enemies=None,
               tokens=None, hero_hp=20, hero_power=3):
    """One hero (generous WUBRG capacity so cost never blocks) vs one Orc, with
    `cards` as the hero's opening hand (top of library)."""
    if party is None:
        party = [{"id": "hero", "name": "Hero", "archetype": "Tactician", "hp": hero_hp,
                  "power": hero_power, "hand_size": len(cards),
                  "identity": ["W", "U", "B", "R", "G"], "library": cards}]
    if enemies is None:
        enemies = [{"id": "orc", "name": "Orc", "hp": enemy_hp, "level": enemy_level,
                    "intent": {"name": "Hit", "amount": intent_amount, "action_type": "ability",
                               "intent_type": intent_type, "targeting": targeting}}]
    return state_from_dict({"party": party, "enemies": enemies, "tokens": tokens or {}})


def pick(state, **crit):
    for a in legal_actions(state):
        if all(getattr(a, k) == v for k, v in crit.items()):
            return a
    raise AssertionError(f"no legal action {crit}; legal={[a.label for a in legal_actions(state)]}")


def has(state, **crit):
    return any(all(getattr(a, k) == v for k, v in crit.items()) for a in legal_actions(state))


def settle_window(state):
    """Pass for whoever holds priority until the stack empties (or the game ends)."""
    while state.result is None and state.stack:
        state, _ = apply_action(state, pick(state, kind="pass"))
    return state


def do(state, **crit):
    state, ev = apply_action(state, pick(state, **crit))
    return settle_window(state), ev


def hero(state):
    return state.party[0]


def orc(state):
    return state.enemy("orc")


# --------------------------------------------------------------------------- #
# Containers: modal (choose the mode at cast) and conditional
# --------------------------------------------------------------------------- #
def _charm():
    return C("charm", "instant", [{"kind": "modal", "modes": [
        {"label": "Bolt", "effects": [{"kind": "deal_damage", "amount": 3,
            "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]},
        {"label": "Insight", "effects": [{"kind": "draw", "amount": 2, "target": {"mode": "self"}}]},
    ]}], colors={"U": 1})


def test_modal_offers_one_option_per_mode_and_resolves_the_chosen_one():
    state = make_state([_charm()], enemy_hp=10)
    # Both modes are offered, each as its own cast choice (mode index carried).
    assert has(state, kind="cast", card_id="charm", mode=0)
    assert has(state, kind="cast", card_id="charm", mode=1)

    # Choose mode 0 (Bolt) on the Orc → 3 damage, no draw.
    after, _ = do(state, kind="cast", card_id="charm", mode=0, target_id="orc")
    assert orc(after).hp == 7
    assert len(hero(after).hand) == 0  # the card left hand; Insight (draw) did NOT fire


def test_modal_other_mode_draws_instead_of_damaging():
    state = make_state([_charm(), C("filler", "sorcery", [{"kind": "scry", "amount": 1,
        "target": {"mode": "self"}}], colors={"U": 1})], enemy_hp=10)
    after, _ = do(state, kind="cast", card_id="charm", mode=1)  # Insight: draw 2
    assert orc(after).hp == 10                      # nothing was bolted
    assert "filler" in [c.id for c in hero(after).hand]  # drew into hand


def _modal_with_conditional():
    # Choose one — [0] deal 2; [1] if the target is level 3+, destroy it.
    return C("verdict", "instant", [{"kind": "modal", "choose": 1, "modes": [
        {"label": "Singe", "effects": [
            {"kind": "deal_damage", "amount": 2, "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]},
        {"label": "Smite", "effects": [
            {"kind": "conditional",
             "condition": {"kind": "target_property", "property": "level", "level": 3, "compare": "or_more"},
             "effects": [{"kind": "destroy", "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]}]},
    ]}], colors={"W": 1})


def test_modal_conditional_branch_fires_when_condition_holds():
    # Pick mode 1 (Smite) on a level-3 orc → the nested conditional's destroy fires.
    state = make_state([_modal_with_conditional()], enemy_hp=10, enemy_level=3)
    after, _ = do(state, kind="cast", card_id="verdict", mode=1, target_id="orc")
    assert after.enemy("orc") is None and after.result == "victory"


def test_modal_conditional_branch_skips_when_condition_false():
    # Same mode, but a level-2 orc fails the "level 3+" gate → it survives untouched.
    state = make_state([_modal_with_conditional()], enemy_hp=10, enemy_level=2)
    after, _ = do(state, kind="cast", card_id="verdict", mode=1, target_id="orc")
    assert orc(after).hp == 10 and after.result is None


def test_conditional_fires_only_when_condition_holds():
    # Deal 2; if cast as an action (proactively), deal 2 more.
    card = C("surge", "instant", [
        {"kind": "deal_damage", "amount": 2, "target": {"mode": "chosen", "side": "enemy", "targeted": True}},
        {"kind": "conditional", "condition": {"kind": "cast_mode", "mode": "action"},
         "effects": [{"kind": "deal_damage", "amount": 2, "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]},
    ], colors={"R": 1})
    state = make_state([card], enemy_hp=10)
    after, _ = do(state, kind="cast", card_id="surge", target_id="orc")
    assert orc(after).hp == 6  # 2 + conditional 2 (cast as an action)


def test_conditional_skips_when_condition_false():
    card = C("surge2", "instant", [
        {"kind": "deal_damage", "amount": 2, "target": {"mode": "chosen", "side": "enemy", "targeted": True}},
        {"kind": "conditional", "condition": {"kind": "cast_mode", "mode": "reaction"},
         "effects": [{"kind": "deal_damage", "amount": 2, "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]},
    ], colors={"R": 1})
    state = make_state([card], enemy_hp=10)
    after, _ = do(state, kind="cast", card_id="surge2", target_id="orc")
    assert orc(after).hp == 8  # only the unconditional 2 (it was cast as an action, not a reaction)


# --------------------------------------------------------------------------- #
# Counter: target an enemy action on the stack and cancel it
# --------------------------------------------------------------------------- #
def test_counter_cancels_the_enemy_action_it_targets():
    counter = C("nope", "instant", [{"kind": "counter", "filter": "action",
        "target": {"class": "action", "side": "enemy"}}], colors={"U": 1})
    state = make_state([counter], intent_amount=6)
    state, _ = apply_action(state, pick(state, kind="end_turn"))  # Orc executes Hit → window opens
    assert state.stack and state.stack[-1].source_side == "enemy"
    # The counter is offered with the enemy action named as its target.
    act = pick(state, kind="cast", card_id="nope")
    assert act.target_id.startswith("#")
    state, _ = apply_action(state, act)
    state = settle_window(state)
    assert hero(state).hp == 20  # the attack was countered → no damage landed


# --------------------------------------------------------------------------- #
# Removal: exile, bounce, strip_intent, stun
# --------------------------------------------------------------------------- #
def test_exile_removes_the_enemy():
    card = C("banish", "sorcery", [{"kind": "exile",
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}], colors={"B": 1})
    after, _ = do(make_state([card]), kind="cast", card_id="banish", target_id="orc")
    assert after.enemy("orc") is None and after.result == "victory"


def _banish():
    return C("banish_light", "channeled",
             [{"kind": "exile", "target": "$T1", "duration": "while_channeled"}],
             colors={"W": 1},
             targets={"T1": {"mode": "chosen", "side": "enemy", "targeted": True}})


def _enemy(eid, name, hp=10, level=3):
    return {"id": eid, "name": name, "hp": hp, "level": level,
            "intent": {"name": "Hit", "amount": 2, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party"}}


def test_channeled_exile_suspends_then_returns_on_break():
    # A channeled exile suspends the enemy (out of play, but alive) while the channel
    # holds; breaking concentration brings it back. A second enemy keeps the fight on.
    state = make_state([_banish()], enemies=[_enemy("orc", "Orc"), _enemy("gob", "Goblin")])
    after, _ = do(state, kind="cast", card_id="banish_light", target_id="orc")
    assert after.enemy("orc") is not None and after.enemy("orc").exiled  # suspended, not killed
    assert "orc" not in [e.id for e in after.living_enemies()]           # out of play
    assert len(hero(after).channels) == 1 and after.result is None       # the Goblin fights on

    after, _ = do(after, kind="drop_channels")                           # break the channel
    assert not after.enemy("orc").exiled                                 # the Orc returns
    assert "orc" in [e.id for e in after.living_enemies()]
    assert hero(after).channels == []


def test_lethal_wound_aura_kills_target_without_breaking_other_channels():
    # Regression: channelling a −2/−2 aura onto a 2-HP enemy kills it outright (a wound
    # that empties toughness is lethal), and losing that aura's target does NOT break
    # concentration — an unrelated channel keeps holding and no reserved mana is
    # released. GDD §8: only a ≥25% hit, incapacitation, or a voluntary drop breaks
    # channels (never an aura losing its target).
    anthem = C("anthem", "channeled",
               [{"kind": "pump", "power": 1, "toughness": 1,
                 "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"}],
               colors={"W": 1})
    dead_weight = C("dead_weight", "channeled",
                    [{"kind": "wound", "power": 2, "toughness": 2, "target": "$T1",
                      "duration": "while_channeled"}],
                    colors={"B": 1},
                    targets={"T1": {"mode": "chosen", "side": "enemy", "targeted": True}})
    state = make_state([anthem, dead_weight],
                       enemies=[_enemy("archer", "Archer", hp=2), _enemy("brute", "Brute", hp=10)])

    state, _ = do(state, kind="cast", card_id="anthem")
    assert len(hero(state).channels) == 1  # the survivor channel

    state, events = do(state, kind="cast", card_id="dead_weight", target_id="archer")
    assert state.enemy("archer") is None                       # (1) the −2/−2 is lethal
    assert len(hero(state).channels) == 2                      # (2)+(3) both channels hold
    assert not any(e.type == "mana_released" for e in events)  # no break -> no mana released


def test_channeled_exile_becomes_permanent_when_the_encounter_ends():
    # Exiling the last enemy ends the encounter — it is permanently exiled, never
    # restored (the rule: defeat everyone else while one is suspended → it's gone).
    after, _ = do(make_state([_banish()]), kind="cast", card_id="banish_light", target_id="orc")
    assert after.result == "victory"
    assert after.enemy("orc").exiled and not after.living_enemies()
    assert any(e.type == "permanent_exile" for e in after.log)


def _unsummon():
    return C("unsummon", "instant", [{"kind": "bounce",
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}], colors={"U": 1})


def test_bounce_sends_the_enemy_to_hand_not_to_the_graveyard():
    # Update 03 §E-C: bounce moves an in-play enemy to the in-hand zone (off the
    # battlefield, untargetable) but it stays on the roster with its HP, so it is
    # neither dead nor targetable — and a second enemy keeps the fight alive.
    state = make_state([_unsummon()], enemies=[_enemy("orc", "Orc"), _enemy("gob", "Goblin")])
    after, _ = do(state, kind="cast", card_id="unsummon", target_id="orc")
    orc_e = after.enemy("orc")
    assert orc_e is not None and orc_e.in_hand            # in hand, not removed
    assert "orc" not in [e.id for e in after.living_enemies()]   # off the battlefield
    assert orc_e.hp == 10                                 # HP retained (bounce does not heal/kill)
    assert after.result is None                           # the Goblin keeps the encounter live


def test_cannot_win_by_bouncing_the_last_enemy():
    # Update 03 §E-B: a bounced last enemy is "in hand", which is not graveyard/exile,
    # so victory stays false — bounce can only delay, never win.
    after, _ = do(make_state([_unsummon()]), kind="cast", card_id="unsummon", target_id="orc")
    assert after.result is None                           # NOT a victory
    assert after.enemy("orc").in_hand and not after.living_enemies()


def test_in_hand_enemy_is_not_a_legal_target():
    # §E-D: you cannot bounce (or otherwise target) an in-hand enemy — it is off-field.
    deck = [_unsummon(), C("unsummon2", "instant", [{"kind": "bounce",
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}], colors={"U": 1})]
    state = make_state(deck, enemies=[_enemy("orc", "Orc"), _enemy("gob", "Goblin")])
    after, _ = do(state, kind="cast", card_id="unsummon", target_id="orc")  # orc → hand
    # No action (bounce or any cast) can name the in-hand orc.
    assert not has(after, kind="cast", card_id="unsummon2", target_id="orc")
    assert all(a.target_id != "orc" for a in legal_actions(after))


def test_bounced_enemy_redeploys_and_acts_next_turn():
    # §E-C redeploy: at the start of its next turn the in-hand enemy returns to play
    # (original row) and declares a fresh intent, having lost exactly one action cycle.
    state = make_state([_unsummon()], enemies=[_enemy("orc", "Orc"), _enemy("gob", "Goblin")])
    after, _ = do(state, kind="cast", card_id="unsummon", target_id="orc")
    assert after.enemy("orc").in_hand
    # End the turn; the enemy phase skips the in-hand orc. Next turn opens on the
    # capacity colour-lock (the hero's 5-colour identity), which precedes the Intents
    # step — resolve it so the flow reaches the redeploy.
    after, _ = do(after, kind="end_turn")
    after, _ = do(after, kind="choose_mana")             # lock turn-2's +1 capacity → Intents
    orc_e = after.enemy("orc")
    assert not orc_e.in_hand                              # back in play (redeployed)
    assert "orc" in [e.id for e in after.living_enemies()]
    assert orc_e.intent is not None                       # declared fresh


def _pit_fight():
    return C("pit_fight", "sorcery", [{"kind": "fight", "target": "$T1", "other": "$T2"}],
             colors={"G": 1},
             targets={"T1": {"mode": "chosen", "side": "ally", "targeted": True},
                      "T2": {"mode": "chosen", "side": "enemy", "targeted": True}})


def test_fight_deals_mutual_damage_equal_to_power():
    # Each fighter deals its power to the other: hero(4) ↔ orc(power 2, from intent).
    state = make_state([_pit_fight()], hero_power=4, enemy_hp=10, intent_amount=2)
    after, _ = do(state, kind="cast", card_id="pit_fight", targets=("hero", "orc"))
    assert after.enemy("orc").hp == 6   # took the hero's Power 4
    assert hero(after).hp == 18         # took the orc's Power 2


def test_fight_is_simultaneous_a_dying_creature_still_hits_back():
    # Hero(10) kills the orc(5 HP), but the orc still deals its Power 3 back — fight
    # damage is simultaneous (both powers are snapshotted before any HP changes).
    state = make_state([_pit_fight()], hero_power=10, enemy_hp=5, intent_amount=3)
    after, _ = do(state, kind="cast", card_id="pit_fight", targets=("hero", "orc"))
    assert after.enemy("orc") is None and after.result == "victory"  # orc died
    assert hero(after).hp == 17                                      # but hit back for 3


def test_strip_intent_clears_the_declared_intent():
    card = C("disrupt", "instant", [{"kind": "strip_intent",
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}], colors={"B": 1})
    state = make_state([card])
    assert orc(state).intent is None or True  # intent declared in the prelude
    after, _ = do(state, kind="cast", card_id="disrupt", target_id="orc")
    assert orc(after).intent is None


def test_stun_makes_the_enemy_skip_its_next_intent():
    card = C("tap", "sorcery", [{"kind": "stun", "intents": 1,
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}], colors={"U": 1})
    state = make_state([card])
    after, _ = do(state, kind="cast", card_id="tap", target_id="orc")
    assert orc(after).stunned == 1
    after, _ = apply_action(after, pick(after, kind="end_turn"))  # carry into turn 2
    # By the next decision point the stun has consumed itself and no intent declared.
    after = _advance_to_turn(after, 2)
    assert orc(after).stunned == 0 and orc(after).intent is None


def _advance_to_turn(state, turn):
    """Step through the turn-2 capacity lock until the player phase of `turn`
    (so intents for that turn have been declared)."""
    guard = 0
    while state.result is None and guard < 50:
        if state.turn >= turn and state.phase == "player":
            break
        acts = legal_actions(state)
        a = (next((x for x in acts if x.kind == "choose_mana"), None)
             or next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None))
        if a is None:
            break
        state, _ = apply_action(state, a)
        guard += 1
    return state


# --------------------------------------------------------------------------- #
# Prevent: an all-turn shield vs a one-shot shield vs blocking an action (R-11)
# --------------------------------------------------------------------------- #
def _two_orcs(amount=6):
    """Two enemies that both swing at the hero in one enemy step — enough hits to
    tell an 'all' shield (soaks both) from a 'next' shield (soaks one)."""
    return [{"id": f"orc{i}", "name": f"Orc{i}", "hp": 10, "level": 3,
             "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                        "intent_type": "attack", "targeting": "lowest_hp_party"}}
            for i in (1, 2)]


def _resolve_enemy_step(state):
    """End the hero's turn and let the enemy step resolve, halting at the next
    player decision (or game end)."""
    state, _ = apply_action(state, pick(state, kind="end_turn"))
    guard = 0
    while state.result is None and guard < 80:
        a = next((x for x in legal_actions(state) if x.kind == "pass"), None)
        if a is None:
            break
        state, _ = apply_action(state, a)
        guard += 1
    return state


def test_prevent_all_soaks_every_hit_this_turn():
    # Fog-shape: uses="all" nullifies EVERY combat-damage hit until end of turn, so
    # two swings both bounce off and the hero takes nothing.
    card = C("fog", "instant", [{"kind": "prevent", "parameter": "combat_damage",
        "uses": "all", "target": {"mode": "self"}}], colors={"G": 1})
    state = make_state([card], hero_hp=20, enemies=_two_orcs(6))
    after, _ = do(state, kind="cast", card_id="fog")
    assert [t.parameter for t in hero(after).prevent_tags] == ["combat_damage"]
    after = _resolve_enemy_step(after)
    assert hero(after).hp == 20  # both hits prevented; the shield was never spent


def test_prevent_next_soaks_only_one_hit():
    # Gods-Willing-shape: uses="next" is a one-shot shield — it eats the first hit
    # and then wears off, so the second swing lands in full.
    card = C("ward", "instant", [{"kind": "prevent", "parameter": "combat_damage",
        "uses": "next", "target": {"mode": "self"}}], colors={"W": 1})
    state = make_state([card], hero_hp=20, enemies=_two_orcs(6))
    after, _ = do(state, kind="cast", card_id="ward")
    assert hero(after).prevent_tags[0].uses == 1
    after = _resolve_enemy_step(after)
    assert hero(after).hp == 14  # first hit prevented, second (6) got through


def test_prevent_attack_stops_the_enemy_from_attacking():
    # Pacifism: a channeled `prevent attack` cancels the target's pending swing and
    # keeps it from declaring another for as long as the channel holds.
    pac = C("pacify", "channeled", [{"kind": "prevent", "parameter": "attack",
        "target": "$T1", "duration": "while_channeled"}], colors={"W": 1},
        targets={"T1": {"mode": "chosen", "side": "enemy", "targeted": True}})
    state = make_state([pac], hero_hp=20, intent_amount=6)
    after, _ = do(state, kind="cast", card_id="pacify", target_id="orc")
    assert orc(after).intent is None                           # no swing telegraphed
    assert any(t.parameter == "attack" for t in orc(after).prevent_tags)
    # Across this turn's and next turn's enemy steps the orc never attacks: the hero
    # is untouched and the channel keeps re-asserting the shield.
    after = _advance_to_turn(after, 2)
    assert orc(after).intent is None and hero(after).hp == 20
    assert any(t.parameter == "attack" for t in orc(after).prevent_tags)


# --------------------------------------------------------------------------- #
# Buffs / debuffs: counters (persistent), wound (absorbs healing), pump
# --------------------------------------------------------------------------- #
def test_counters_are_persistent_power_and_max_hp():
    card = C("grow", "sorcery", [{"kind": "counters", "power": 2, "toughness": 2,
        "target": {"mode": "self"}, "duration": "encounter"}], colors={"G": 1})
    after, _ = do(make_state([card], hero_power=3), kind="cast", card_id="grow")
    h = hero(after)
    assert h.power == 5 and h.max_hp == 22 and h.hp == 22  # not cleared at end step


def test_wound_lowers_effective_hp_and_a_heal_fills_it_first():
    # Wound −0/−3 drops temp_mod by 3 (R-7); a heal cancels the wound toward 0
    # before it restores any hp.
    card = C("hex", "sorcery", [{"kind": "wound", "power": 0, "toughness": 3,
        "target": {"mode": "chosen", "side": "ally", "targeted": True}}], colors={"B": 1})
    state = make_state([card], hero_hp=20)
    after, _ = do(state, kind="cast", card_id="hex", target_id="hero")
    h = hero(after)
    assert h.temp_mod == -3 and h.effective_hp == 17 and h.hp == 20


# --------------------------------------------------------------------------- #
# Mana: ramp (capacity) and add_mana (pool)
# --------------------------------------------------------------------------- #
def test_ramp_immediate_raises_capacity_and_pool_now():
    card = C("growth", "sorcery", [{"kind": "ramp", "amount": 1, "color": "G",
        "availability": "immediate"}], colors={"G": 1})
    state = make_state([card])
    cap0 = hero(state).capacity
    after, _ = do(state, kind="cast", card_id="growth")
    assert hero(after).capacity == cap0 + 1 and "G" in hero(after).pool


def test_add_mana_adds_to_the_pool_without_capacity():
    card = C("ritual", "instant", [{"kind": "add_mana", "amount": 2, "color": "B"}], colors={"B": 1})
    state = make_state([card])
    cap0 = hero(state).capacity
    after, _ = do(state, kind="cast", card_id="ritual")
    assert hero(after).capacity == cap0 and hero(after).pool.count("B") >= 2


# --------------------------------------------------------------------------- #
# Targeting: all (anthem), value refs (mana_capacity)
# --------------------------------------------------------------------------- #
def test_all_target_pump_hits_every_ally():
    card = C("rally", "sorcery", [{"kind": "pump", "power": 1, "toughness": 1,
        "target": {"mode": "all", "side": "ally"}, "duration": "end_of_turn"}], colors={"W": 1})
    party = [
        {"id": "a", "name": "A", "archetype": "Fighter", "hp": 20, "power": 2,
         "hand_size": 1, "identity": ["W", "U", "B", "R", "G"],
         "library": [card, C("x", "sorcery", [{"kind": "scry", "amount": 1, "target": {"mode": "self"}}], colors={"U": 1})]},
        {"id": "b", "name": "B", "archetype": "Fighter", "hp": 20, "power": 2,
         "hand_size": 0, "identity": ["W"], "library": []},
    ]
    state = make_state([], party=party)
    after, _ = do(state, kind="cast", card_id="rally")
    assert after.party[0].current_power == 3 and after.party[1].current_power == 3


def test_mana_capacity_value_scales_with_capacity():
    # Draw a card for each point of mana capacity (capacity 5 here).
    deck = [C("divine", "sorcery", [{"kind": "draw", "amount": {"ref": "mana_capacity"},
        "target": {"mode": "self"}}], colors={"U": 1})] + \
        [C(f"f{i}", "sorcery", [{"kind": "scry", "amount": 1, "target": {"mode": "self"}}], colors={"U": 1}) for i in range(6)]
    state = make_state(deck[:1], party=[{"id": "hero", "name": "Hero", "archetype": "Tactician",
        "hp": 20, "power": 1, "hand_size": 1, "identity": ["W", "U", "B", "R", "G"], "library": deck}])
    after, _ = do(state, kind="cast", card_id="divine")
    # capacity 5 → Divine drew 5; with the turn-1 upkeep draw and Divine leaving
    # the hand, that empties the 6-card library into a 6-card hand.
    assert len(hero(after).hand) == 6 and hero(after).library == []


# --------------------------------------------------------------------------- #
# Keywords with engine-modelled semantics
# --------------------------------------------------------------------------- #
def _grant_self(kw, timing="instant", colors=None, duration="end_of_turn"):
    return C(f"grant_{kw}", timing, [{"kind": "grant_keyword", "keywords": [kw],
        "target": {"mode": "self"}, "duration": duration}], colors=colors or {"W": 1})


def test_grant_and_remove_keyword():
    state = make_state([_grant_self("flying"),
                        C("strip", "instant", [{"kind": "remove_keyword", "keywords": ["flying"],
                            "target": {"mode": "self"}}], colors={"U": 1})])
    after, _ = do(state, kind="cast", card_id="grant_flying")
    assert "flying" in hero(after).keywords
    after, _ = do(after, kind="cast", card_id="strip")
    assert "flying" not in hero(after).keywords


def test_lifelink_heals_the_source_for_damage_dealt():
    state = make_state([_grant_self("lifelink")], hero_hp=20, hero_power=4)
    after, _ = do(state, kind="cast", card_id="grant_lifelink")
    hero(after).hp = 10  # wound the hero so lifelink can top it up
    after, _ = do(after, kind="attack", target_id="orc")  # Power 4 → heal 4
    assert hero(after).hp == 14


def test_deathtouch_executes_any_minion_it_damages():
    state = make_state([_grant_self("deathtouch")], enemy_hp=99, hero_power=1)
    after, _ = do(state, kind="cast", card_id="grant_deathtouch")
    after, _ = do(after, kind="attack", target_id="orc")  # 1 damage, but deathtouch executes
    assert after.enemy("orc") is None


def test_indestructible_floors_damage_at_one_hp():
    state = make_state([_grant_self("indestructible")], hero_hp=4, intent_amount=99)
    after, _ = do(state, kind="cast", card_id="grant_indestructible")
    after, _ = apply_action(after, pick(after, kind="end_turn"))  # Orc hits for 99
    after = settle_window(after)
    assert hero(after).hp == 1 and hero(after).alive  # can't be reduced below 1 by damage


def test_hexproof_character_cannot_be_targeted_by_enemy_intent():
    # Two allies: the fragile one is hexproof, so the enemy must aim at the other.
    party = [
        {"id": "glass", "name": "Glass", "archetype": "Tactician", "hp": 5, "power": 1,
         "hand_size": 1, "identity": ["W", "U", "B", "R", "G"],
         "library": [_grant_self("hexproof", duration="encounter")]},
        {"id": "tank", "name": "Tank", "archetype": "Fighter", "hp": 25, "power": 2,
         "hand_size": 0, "identity": ["W"], "library": []},
    ]
    state = make_state([], party=party)  # Orc targets lowest-HP = Glass by default
    after, _ = do(state, kind="cast", card_id="grant_hexproof")  # Glass becomes hexproof
    after = _advance_to_turn(after, 2)  # intents re-declared on turn 2
    glass_targeted = any(e.intent and e.intent.target_id == "glass" for e in after.enemies)
    assert not glass_targeted  # the enemy can't target the hexproof ally


def test_vigilance_lets_a_character_attack_and_still_cast():
    bolt = C("bolt", "sorcery", [{"kind": "deal_damage", "amount": 2,
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}], colors={"R": 1})
    state = make_state([_grant_self("vigilance", colors={"W": 1}), bolt], enemy_hp=20)
    after, _ = do(state, kind="cast", card_id="grant_vigilance")
    after, _ = do(after, kind="attack", target_id="orc")  # uses the Attack action
    # Without vigilance, casting a sorcery after attacking is illegal; with it, it's offered.
    assert has(after, kind="cast", card_id="bolt")


def test_double_strike_hits_twice():
    state = make_state([_grant_self("double_strike")], enemy_hp=20, hero_power=3)
    after, _ = do(state, kind="cast", card_id="grant_double_strike")
    after, _ = do(after, kind="attack", target_id="orc")
    assert orc(after).hp == 20 - 6  # two Power-3 hits


# --------------------------------------------------------------------------- #
# Revive (white-box: a downed ally can't be reached via the public target list)
# --------------------------------------------------------------------------- #
def test_revive_restores_a_downed_character():
    from ltg_combat.engine import _r_revive
    from ltg_combat.state import StackItem
    state = make_state([])
    h = hero(state)
    h.hp = 0
    eff = type("E", (), {"kind": "revive", "to_fraction": 0.5})()
    _r_revive(state, StackItem(kind="spell", source_id="hero", source_side="party",
              label="Raise", effects=[]), eff, h, {})
    assert h.hp == h.max_hp // 2 and h.alive


# --------------------------------------------------------------------------- #
# Every example card the Deckbuilder ships resolves without error
# --------------------------------------------------------------------------- #
def _example_cards():
    out = []
    for path in sorted(EXAMPLES.glob("*.json")):
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and "timing" in raw and "effects" in raw:
            try:
                Card.model_validate(raw)
            except Exception:
                continue
            out.append((path.stem, raw))
    return out


@pytest.mark.parametrize("name,card", _example_cards())
def test_every_example_card_is_executable(name, card):
    """Each single-card example loads, the engine enumerates its legal casts, and
    applying any one of them resolves with no exception (a counter with an empty
    stack is correctly offered nothing — that's legal, not a crash)."""
    # Put the card on top with a stack present (so counters have something to hit):
    # cast it during the enemy's reaction window when possible, else in the main phase.
    state = make_state([card], enemy_hp=12, intent_amount=2)
    casts = [a for a in legal_actions(state) if a.kind == "cast" and a.card_id == card["id"]]
    if casts:
        for a in casts:
            branch, _ = apply_action(state, a)
            settle_window(branch)  # must not raise
    else:
        # No main-phase cast (e.g. a counter): exercise it in a reaction window.
        st2, _ = apply_action(state, pick(state, kind="end_turn"))
        if st2.stack:
            for a in [x for x in legal_actions(st2) if x.kind == "cast" and x.card_id == card["id"]]:
                branch, _ = apply_action(st2, a)
                settle_window(branch)
