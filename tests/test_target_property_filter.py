"""Playtest bug (2026-08-23): "Deal 3 damage to everyone that is an undead" — the
third clause of Turin's Consecrate — never fired.

It is authored as a `target_property` conditional wrapping an `all`-target
`deal_damage`. The condition read the card's single chosen pick, and Consecrate
targets nothing (heal all · consume all corpses · damage all undead), so
`item.target_id` was None, the gate was false, and the branch was skipped whole —
while the heal and the corpse sweep beside it landed normally.

With no pick to read, a property condition now FILTERS each nested effect's own
target set creature by creature. A card that DOES name a target keeps the gate."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict

ALL_ANY = {"mode": "all", "side": "any"}
ALL_ENEMY = {"mode": "all", "side": "enemy"}
CHOSEN_ENEMY = {"mode": "chosen", "side": "enemy", "targeted": True}


def _card(effects, cid="spell", cost=None):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 2,
            "type": "Sorcery", "timing": "sorcery",
            "cost": cost or {"generic": 0, "colors": {"W": 1}},
            "effects": effects, "validated": True}


def _undead_purge(target=None):
    """The Consecrate shape: a type condition over an untargeted mass effect."""
    return _card([{"kind": "conditional",
                   "condition": {"kind": "target_property", "property": "type",
                                 "type": "undead", "compare": "exactly"},
                   "effects": [{"kind": "deal_damage", "amount": 3,
                                "target": target or ALL_ANY}]}])


def _enemy(eid, types=None, hp=12, row="front"):
    return {"id": eid, "name": eid, "hp": hp, "level": 2, "row": row,
            "types": types or [],
            "intent": {"name": "Hit", "amount": 1, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _state(card, enemies, hero_types=None, hp=30):
    st = state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 40, "power": 3, "hand_size": 1,
                   "identity": ["W", "W"], "row": "front", "attack_mode": "melee",
                   "types": hero_types or ["human"], "library": [dict(card)]}],
        "enemies": enemies})
    st.character("p").hp = hp
    return settle(st)


def _cast(st, **m):
    a = next(x for x in legal_actions(st)
             if x.kind == "cast" and all(getattr(x, k) == v for k, v in m.items()))
    st = apply_action(st, a)[0]
    while True:
        picks = [x for x in legal_actions(st) if x.kind.startswith("choose")]
        if not picks:
            break
        st = apply_action(st, picks[0])[0]
    return apply_action(st, next(x for x in legal_actions(st) if x.kind == "pass"))[0]


# --------------------------------------------------------------------------- #
# The reported bug
# --------------------------------------------------------------------------- #
def test_damage_everyone_that_is_undead_hits_every_undead():
    st = _cast(_state(_undead_purge(),
                      [_enemy("ghoul", ["undead"]), _enemy("wight", ["undead"])]))
    assert st.enemy("ghoul").hp == 9 and st.enemy("wight").hp == 9


def test_it_passes_over_everyone_who_is_not_undead():
    st = _cast(_state(_undead_purge(),
                      [_enemy("ghoul", ["undead"]), _enemy("bandit", ["human"])]))
    assert st.enemy("ghoul").hp == 9
    assert st.enemy("bandit").hp == 12
    assert st.character("p").hp == 30            # side "any" — the human hero is spared


def test_an_undead_hero_is_caught_by_a_side_any_purge():
    """The filter reads the creature, not the side: side "any" means everyone."""
    st = _cast(_state(_undead_purge(), [_enemy("bandit", ["human"])],
                      hero_types=["undead"]))
    assert st.character("p").hp == 27
    assert st.enemy("bandit").hp == 12


def test_no_undead_on_the_board_means_nothing_happens():
    st = _cast(_state(_undead_purge(), [_enemy("bandit", ["human"])]))
    assert st.enemy("bandit").hp == 12 and st.character("p").hp == 30


def test_the_whole_consecrate_lands_all_three_clauses():
    """End to end on the real card shape: heal all · consume all corpses · burn
    the undead. The heal and the sweep always worked; the burn is the fix."""
    card = _card([
        {"kind": "heal", "amount": 2, "target": {"mode": "all", "side": "ally"}},
        {"kind": "consume_corpse", "target": {"mode": "all", "side": "enemy",
                                              "state": "corpse"}},
        {"kind": "conditional",
         "condition": {"kind": "target_property", "property": "type",
                       "type": "undead", "compare": "exactly"},
         "effects": [{"kind": "deal_damage", "amount": 3, "target": ALL_ANY}]},
    ], cost={"generic": 0, "colors": {"W": 2}})
    st = _state(card, [_enemy("ghoul", ["undead"]), _enemy("bandit", ["human"])])
    st = _cast(st)
    assert st.character("p").hp == 32            # heal all allies
    assert not st.corpses                        # corpse sweep (none to take here)
    assert st.enemy("ghoul").hp == 9             # …and the undead burn
    assert st.enemy("bandit").hp == 12


def test_other_properties_filter_the_same_way():
    """Not just types: a level / row / keyword condition filters per creature too."""
    card = _card([{"kind": "conditional",
                   "condition": {"kind": "target_property", "property": "row",
                                 "row": "rear"},
                   "effects": [{"kind": "deal_damage", "amount": 4,
                                "target": ALL_ENEMY}]}])
    st = _cast(_state(card, [_enemy("front_guard", row="front"),
                             _enemy("archer", row="rear")]))
    assert st.enemy("front_guard").hp == 12
    assert st.enemy("archer").hp == 8


# --------------------------------------------------------------------------- #
# The regression guards: a card that names a target keeps the gate
# --------------------------------------------------------------------------- #
def test_a_card_with_a_chosen_pick_still_gates_on_that_pick():
    """"Deal 2 to a chosen enemy; if it is undead, deal 3 to all enemies." The
    condition must read the PICK, exactly as authored — not filter the sweep."""
    card = _card([
        {"kind": "deal_damage", "amount": 2, "target": CHOSEN_ENEMY},
        {"kind": "conditional",
         "condition": {"kind": "target_property", "property": "type",
                       "type": "undead", "compare": "exactly"},
         "effects": [{"kind": "deal_damage", "amount": 3, "target": ALL_ENEMY}]},
    ], cost={"generic": 0, "colors": {"W": 2}})
    board = [_enemy("ghoul", ["undead"]), _enemy("bandit", ["human"])]
    # Pick the undead: the gate opens and EVERY enemy takes the 3, human included.
    st = _cast(_state(card, [dict(e) for e in board]), target_id="ghoul")
    assert st.enemy("ghoul").hp == 7             # 2 + 3
    assert st.enemy("bandit").hp == 9            # 3 — the gate is not a filter
    # Pick the human: the gate stays shut and nobody takes the sweep.
    st = _cast(_state(card, [dict(e) for e in board]), target_id="bandit")
    assert st.enemy("bandit").hp == 10           # just the 2
    assert st.enemy("ghoul").hp == 12


def test_an_is_dead_condition_still_reads_the_corpse_pick():
    """§D9-1.3 is a gate on the pick, never a per-creature filter."""
    card = _card([{"kind": "conditional",
                   "condition": {"kind": "target_property", "property": "is_dead"},
                   "effects": [{"kind": "heal", "amount": 4,
                                "target": {"mode": "self"}}]}])
    st = _cast(_state(card, [_enemy("bandit", ["human"])]))
    assert st.character("p").hp == 30             # no pick, no corpse — no heal


def test_a_pick_nested_inside_the_conditional_still_gates():
    """Alder's shipped "Shadowy Blade" — *Destroy a target in the rear row.* The
    chosen pick lives INSIDE the conditional, so the card names a target even
    though nothing above the conditional does. It must stay a gate: the destroy
    lands only when the creature the player picked really is in the rear."""
    card = _card([{"kind": "conditional",
                   "condition": {"kind": "target_property", "property": "row",
                                 "row": "rear"},
                   "effects": [{"kind": "destroy",
                                "target": {"mode": "chosen", "side": "any",
                                           "targeted": True}}]}],
                 cost={"generic": 0, "colors": {"W": 2}})
    board = [_enemy("thug", row="front"), _enemy("archer", row="rear")]
    st = _cast(_state(card, [dict(e) for e in board]), target_id="archer")
    assert sorted(e.id for e in st.living_enemies()) == ["thug"]
    st = _cast(_state(card, [dict(e) for e in board]), target_id="thug")
    assert sorted(e.id for e in st.living_enemies()) == ["archer", "thug"]
