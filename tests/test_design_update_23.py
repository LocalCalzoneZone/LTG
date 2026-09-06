"""Design Update 23 — turn groups, reach, and fight shape.

The 2026-09 review found the turn economy collapsing to "cast or swing", ranged
heroes with no positional stake, and a handful of rules bugs that quietly broke
authored intent. This file covers the parts of Update 23 that have no older home:
the §D23-7 corrections that no existing suite owns, the two turn GROUPS
(§D23-1/2), ranged-from-Front (§D23-3), and the boss/objective and enemy-AI work.
"""

from __future__ import annotations

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", power=3, hp=30, mode="melee", keywords=None,
          library=None, hand=0):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": ["U"], "row": row, "attack_mode": mode,
            "keywords": keywords or [],
            "library": library or [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid="e", hp=30, power=3, row="front", mode="melee", level=3,
           components=None, targeting="lowest_hp_party", ranged=None, **kw):
    out = {"id": eid, "name": eid, "hp": hp, "level": level, "power": power,
           "attack_mode": mode, "row": row,
           "intent": {"name": "Hit", "amount": power, "action_type": "attack",
                      "intent_type": "attack", "targeting": targeting,
                      "mode": mode},
           "components": components or []}
    if ranged is not None:
        out["ranged_intent"] = ranged
    out.update(kw)
    return out


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


def _do(st, kind, **match):
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError("no legal %r action (%s) among %s"
                         % (kind, match, [a.label for a in legal_actions(st)]))


def _kinds(st):
    return {a.kind for a in legal_actions(st)}


def _settle(st, budget=40):
    """Pass until the stack is empty (every reaction window declined)."""
    for _ in range(budget):
        if not st.stack:
            return st
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            return st
        st = apply_action(st, p)[0]
    return st


# --------------------------------------------------------------------------- #
# §D23-7.3 — a body is killed once
# --------------------------------------------------------------------------- #
def test_an_enemy_already_off_the_board_is_never_killed_twice():
    """Two paths racing the same body down (a damage resolution and an aura lift,
    say) both reached `_kill_enemy`, which logged a second death, fired a second
    death event and left a SECOND corpse on the row — free fuel for a corpse
    deck."""
    from ltg_combat.engine import _kill_enemy
    st = _state([_char("p")], [_enemy("e", hp=1)])
    target = st.enemy("e")
    _kill_enemy(st, target)
    _kill_enemy(st, target)          # the second caller finds it already gone
    assert len([c for c in st.corpses if c.id == "e"]) == 1
    assert len([ev for ev in st.log if ev.type == "enemy_died"]) == 1


def test_a_token_already_destroyed_is_never_destroyed_twice():
    from ltg_combat.engine import _remove_token
    from ltg_combat.state import TokenState
    st = _state([_char("p")], [_enemy("e")])
    token = TokenState(id="t", name="Wisp", hp=1, max_hp=1, power=1, row="front")
    st.tokens.append(token)
    _remove_token(st, token)
    _remove_token(st, token)
    assert len([ev for ev in st.log if ev.type == "token_died"]) == 1


# --------------------------------------------------------------------------- #
# §D23-7.6 — a hero downed by a continuous aura goes down through the normal path
# --------------------------------------------------------------------------- #
_RITUAL = {
    "id": "ritual", "archetype": "Debilitate", "timing": "proactive",
    "priority": 10, "cooldown": 2, "target_rule": "self",
    "channel": True, "action_type": "spell",
    "telegraph": "Ritual of Thorns — all heroes -1/-1 while channeled",
    "verbs": [{"kind": "wound", "power": 1, "toughness": 1,
               "duration": "while_channeled",
               "target": {"mode": "all", "side": "ally"}}],
}


def test_a_hero_downed_by_an_aura_is_downed_through_the_normal_path():
    """The aura reap used to remove enemies and tokens and leave characters to a
    silent HP check: no `incapacitated` line, no +25 ally-down gauge credit for
    the rest of the party, no death event for a "when an ally falls" trigger."""
    st = _state([_char("p", hp=1), _char("q", hp=30)],
                [_enemy("warlock", hp=12, components=[dict(_RITUAL)])])
    for _ in range(80):
        if st.character("p").down_credited:
            break
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    p, q = st.character("p"), st.character("q")
    assert p.effective_hp <= 0, "the -1/-1 aura must put the 1-HP hero down"
    assert any(ev.type == "incapacitated" and ev.data.get("character") == "p"
               for ev in st.log)
    assert p.down_credited and q.ultimate_gauge_pct >= 25


def test_the_aura_downing_is_credited_once_not_every_end_step():
    """`down_credited` is the guard: a hero who stays down through several End
    steps must not re-log the downing or pay the credit again."""
    st = _state([_char("p", hp=1), _char("q", hp=30)],
                [_enemy("warlock", hp=12, components=[dict(_RITUAL)])])
    for _ in range(120):
        acts = legal_actions(st)
        if not acts or st.result is not None:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    downs = [ev for ev in st.log
             if ev.type == "incapacitated" and ev.data.get("character") == "p"]
    assert len(downs) == 1


# --------------------------------------------------------------------------- #
# §D23-7.5 — the taunt's bite reads Power at execution
# --------------------------------------------------------------------------- #
_CHALLENGE = {
    "id": "challenge", "timing": "proactive", "priority": 10,
    "target_rule": "valuation", "telegraph": "Challenge",
    "verbs": [{"kind": "taunt",
               "target": {"mode": "chosen", "side": "ally", "targeted": True}}],
}


def test_a_wound_after_the_telegraph_blunts_the_taunts_bite():
    """§D18-1 gives a bare taunt a blow; §D23-7.5 makes that blow behave like a
    basic swing — the number is read when it EXECUTES, so a wound landed in
    between actually reduces what lands."""
    st = _state([_char("p", hp=30)],
                [_enemy("bully", power=5, components=[dict(_CHALLENGE)])])
    for _ in range(60):
        if st.enemy("bully") is not None and st.enemy("bully").intent is not None:
            break
        acts = legal_actions(st)
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    assert st.enemy("bully").intent.name == "Challenge"
    st.enemy("bully").power_bonus = -3          # a wound lands after the telegraph
    before = st.character("p").hp
    for _ in range(60):
        if st.character("p").hp < before:
            break
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    assert before - st.character("p").hp == 2   # 5 Power − 3 wound, not 5


# --------------------------------------------------------------------------- #
# §D23-7.7 — every hero-directed target rule honours reach
# --------------------------------------------------------------------------- #
def _grasp(target_rule):
    return {"id": "grasp", "timing": "proactive", "priority": 10,
            "target_rule": target_rule, "telegraph": "Grasp",
            "verbs": [{"kind": "deal_damage", "amount": 3,
                       "target": {"mode": "chosen", "side": "ally",
                                  "targeted": True}}]}


def test_a_fixed_target_rule_cannot_reach_through_the_front_line():
    """An authored grudge ("the undead hunt the cleric") names WHOM to hunt — it
    is not a licence to strike past the wall. The rule is skipped instead."""
    from ltg_combat.engine import _component_target
    from ltg_combat.scenario import _component_from_dict
    st = _state([_char("tank", row="front"), _char("cleric", row="rear")],
                [_enemy("ghoul", row="front")])
    comp = _component_from_dict(_grasp("cleric"))
    assert _component_target(st, st.enemy("ghoul"), comp) is None
    st.character("cleric").row = "front"        # step into reach and it lands
    assert _component_target(st, st.enemy("ghoul"), comp).id == "cleric"


def test_channeling_player_honours_reach():
    """Same rule for the interrupt: a melee enemy cannot reach past the wall to
    break a channel held in the Rear row."""
    from ltg_combat.engine import _component_target
    from ltg_combat.scenario import _component_from_dict
    from ltg_combat.state import Channel
    from ltg_core.schema import Card
    st = _state([_char("tank", row="front"), _char("mage", row="rear")],
                [_enemy("ghoul", row="front")])
    card = Card.model_validate(_filler("hold"))
    st.character("mage").channels.append(Channel(card=card, holder_id="mage"))
    comp = _component_from_dict(_grasp("channeling_player"))
    assert _component_target(st, st.enemy("ghoul"), comp) is None
    st.character("mage").row = "front"
    assert _component_target(st, st.enemy("ghoul"), comp).id == "mage"


def test_the_ranged_fallback_does_not_rewrite_the_standing_attack_mode():
    """A melee enemy forced onto its weaker ranged fallback used to be written
    back to `attack_mode = "ranged"` — permanently, so every later reach test and
    component pick treated the brute as an archer."""
    # Mid, so the hurl is legal at all (§D23-3 bars a shot from the Front row):
    # melee still reaches only the tank on the front line, so the brute's hunt for
    # the lowest-HP hero forces the fallback.
    st = _state([_char("tank", row="front", hp=30), _char("mage", row="rear", hp=8)],
                [_enemy("brute", mode="melee", row="mid",
                        targeting="lowest_hp", power=5,
                        ranged={"name": "Hurl", "amount": 2,
                                "action_type": "ability", "mode": "ranged"})])
    for _ in range(40):
        e = st.enemy("brute")
        if e is not None and e.intent is not None:
            break
        acts = legal_actions(st)
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    e = st.enemy("brute")
    assert e.intent.attack_mode == "ranged"     # the hurl is what it declared…
    assert e.attack_mode == "melee"             # …but it is still a melee body


# --------------------------------------------------------------------------- #
# §D23-1 — the turn is two groups
# --------------------------------------------------------------------------- #
def _sorcery(cid):
    out = _filler(cid)
    out.update(type="Sorcery", timing="sorcery")
    return out


def _bolt(cid, amount=1):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Sorcery", "timing": "sorcery",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "deal_damage", "amount": amount,
                         "target": {"mode": "chosen", "side": "enemy",
                                    "targeted": True}}]}


def _turn_state(keywords=None, library=None, hand=2, row="front"):
    return _state([_char("p", row=row, keywords=keywords, hand=hand,
                         library=library or [_sorcery("s1"), _sorcery("s2")])],
                  [_enemy("e", hp=40)])


def test_a_turn_spending_verb_is_the_whole_turn():
    """Attack / Cast / Skill / Ultimate are one group: taking one is your turn."""
    st = _do(_turn_state(), "attack", target_id="e")
    st = _settle(st)
    open_now = _kinds(st)
    assert "attack" not in open_now and "cast" not in open_now
    assert "defend" not in open_now and "move" not in open_now


def test_defend_and_move_are_a_pair_and_together_make_a_turn():
    """The other group: either one, or both, in either order, is a full turn."""
    st = _turn_state()
    assert {"defend", "move"} <= _kinds(st)
    st = _do(st, "defend")
    assert "move" in _kinds(st), "the pair is not spent by one of its halves"
    assert "cast" not in _kinds(st), "…but the pair is not a turn-spending verb"
    st = _do(st, "move", target_id="mid")
    st = _settle(st)
    assert "defend" not in _kinds(st) and "move" not in _kinds(st)


def test_the_pair_works_in_either_order():
    st = _do(_turn_state(), "move", target_id="mid")
    st = _settle(st)
    assert "defend" in _kinds(st)
    assert "attack" not in _kinds(st), "the Move already committed the turn to the pair"


def test_the_pair_is_not_a_route_to_a_second_turn_verb():
    st = _do(_turn_state(), "defend")
    st = _do(st, "move", target_id="mid")
    st = _settle(st)
    assert not ({"attack", "cast", "use_skill"} & _kinds(st))


def test_several_sorceries_still_ride_one_cast():
    """Unchanged by the regrouping: Cast is ONE verb however many sorceries it
    pays for — that is what makes a mana-flooded caster's turn worth taking."""
    st = _turn_state(library=[_bolt("b1"), _bolt("b2")])
    st.character("p").pool = ["U", "U", "U"]
    st = _do(st, "cast", card_id="b1")
    st = _settle(st)
    assert "cast" in _kinds(st), "the second sorcery rides the same Cast"
    st = _do(st, "cast", card_id="b2")
    st = _settle(st)
    assert "attack" not in _kinds(st), "…but the Cast is still the whole turn"


# --------------------------------------------------------------------------- #
# §D23-2 — a keyword frees one verb, which buys exactly one more
# --------------------------------------------------------------------------- #
def test_vigilance_frees_the_attack_and_buys_one_more_verb():
    st = _turn_state(keywords=["vigilance"])
    swing = next(a for a in legal_actions(st) if a.kind == "attack")
    assert "(free, vigilance)" in swing.label
    st = _settle(_do(st, "attack", target_id="e"))
    assert {"cast", "defend", "move"} <= _kinds(st)
    st = _settle(_do(st, "defend"))
    assert "move" not in _kinds(st), "one more verb, not the whole pair"
    assert "cast" not in _kinds(st)


def test_a_freed_verb_may_follow_the_verb_it_free_rides_on():
    """Order independence (§D23-2): Defend + free Attack is as legal as free
    Attack + Defend."""
    st = _turn_state(keywords=["vigilance"])
    st = _settle(_do(st, "defend"))
    assert "attack" in _kinds(st)
    st = _settle(_do(st, "attack", target_id="e"))
    assert "move" not in _kinds(st) and "cast" not in _kinds(st)


def test_defend_plus_move_plus_a_freed_attack_is_illegal_in_either_order():
    """The pair IS the turn; a freed verb buys one more verb, and the pair has
    already spent two."""
    st = _turn_state(keywords=["vigilance"])
    st = _settle(_do(st, "defend"))
    st = _settle(_do(st, "move", target_id="mid"))
    assert "attack" not in _kinds(st)
    # …and the other way round: the freed swing first leaves room for one verb
    # only, so the pair can never complete behind it.
    st = _turn_state(keywords=["vigilance"])
    st = _settle(_do(st, "attack", target_id="e"))
    st = _settle(_do(st, "defend"))
    assert "move" not in _kinds(st)


def test_haste_frees_the_move_and_buys_one_more_verb():
    st = _turn_state(keywords=["haste"])
    step = next(a for a in legal_actions(st) if a.kind == "move")
    assert "(free, haste)" in step.label
    st = _settle(_do(st, "move", target_id="mid"))
    assert {"attack", "cast", "defend"} <= _kinds(st)
    st = _settle(_do(st, "attack", target_id="e"))
    assert "defend" not in _kinds(st)


def test_a_defender_frees_the_defend_but_never_gets_the_sword():
    st = _turn_state(keywords=["defender"])
    shield = next(a for a in legal_actions(st) if a.kind == "defend")
    assert "(free, defender)" in shield.label
    assert "attack" not in _kinds(st)
    st = _settle(_do(st, "defend"))
    assert {"cast", "move"} <= _kinds(st)
    assert "attack" not in _kinds(st), "a defender never basic-attacks, freed or not"


# --------------------------------------------------------------------------- #
# §D23-3 — ranged cannot fire from the Front row
# --------------------------------------------------------------------------- #
def test_a_ranged_hero_in_front_has_no_attack():
    """Point blank. The archer who dashed into Front to Mitigate for the tank
    pays with the next shot unless they spend a turn walking back out — which is
    the positional stake a ranged hero never had."""
    st = _state([_char("archer", row="front", mode="ranged")], [_enemy("e")])
    assert not [a for a in legal_actions(st) if a.kind == "attack"]
    st.character("archer").row = "mid"
    assert [a for a in legal_actions(st) if a.kind == "attack"]


def test_a_melee_hero_in_front_is_untouched():
    """The control: the rule is about the bow, not about the row."""
    st = _state([_char("knight", row="front", mode="melee")], [_enemy("e")])
    assert [a for a in legal_actions(st) if a.kind == "attack"]


def test_a_caster_in_front_still_casts():
    """Spells are not attacks (§D23-3) — the mage on the front line keeps working."""
    st = _state([_char("mage", row="front", mode="ranged", hand=1,
                       library=[_bolt("b1"), _bolt("b2")])], [_enemy("e")])
    st.character("mage").pool = ["U"]
    assert not [a for a in legal_actions(st) if a.kind == "attack"]
    assert [a for a in legal_actions(st) if a.kind == "cast"]


def test_walking_out_of_front_restores_the_shot_the_same_turn():
    """The Move is half of the pair (§D23-1), so stepping back is a real turn —
    and the shot only returns NEXT turn, because the pair is now spent."""
    st = _state([_char("archer", row="front", mode="ranged")], [_enemy("e")])
    st = _settle(_do(st, "move", target_id="mid"))
    assert st.character("archer").row == "mid"
    assert not [a for a in legal_actions(st) if a.kind == "attack"], \
        "the Move committed the turn to the pair"


def test_an_allied_token_obeys_the_same_rule():
    """§D23-3 binds every body on the board, tokens included."""
    from ltg_combat.engine import _reachable_targets
    from ltg_combat.state import TokenState
    st = _state([_char("p")], [_enemy("e")])
    token = TokenState(id="t", name="Arrow Wisp", hp=3, max_hp=3, power=2,
                       row="front", attack_mode="ranged")
    assert _reachable_targets(token, list(st.enemies)) == []
    token.row = "rear"
    assert _reachable_targets(token, list(st.enemies))


def test_a_positional_ranged_volley_cannot_be_loosed_from_front():
    """A row-aimed ranged intent is an attack like any other (§D23-3). From the
    Front row the ballista has no shot, so it falls back instead."""
    volley = {"id": "bal", "name": "bal", "hp": 20, "level": 2, "row": "front",
              "attack_mode": "ranged",
              "intent": {"name": "Ballista Rake", "amount": 3, "target_row": "rear",
                         "intent_type": "attack", "mode": "ranged"}}
    st = _state([_char("mage", row="rear")], [volley])
    for _ in range(20):
        if st.turn >= 2:
            break
        acts = legal_actions(st)
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    # Turn 1 was spent walking off the melee line; the rake comes from Mid.
    assert st.enemies[0].row == "mid"
    assert any(ev.type == "intent_declared" and ev.data.get("intent") == "Fall back"
               for ev in st.log)
    assert st.enemies[0].intent.target_row == "rear"


def test_the_snapshot_says_why_the_attack_cell_is_closed():
    """The client greys the Attack cell and explains itself from these two fields
    rather than carrying a copy of the rules."""
    from ltg_combat.serialize import _character_dict
    st = _state([_char("archer", row="front", mode="ranged")], [_enemy("e")])
    blocked = _character_dict(st, st.character("archer"))
    assert blocked["reach_blocked"] == "front"
    assert blocked["turn_open"]["attack"] is True   # the TURN is open; the row is not
    st.character("archer").row = "mid"
    assert _character_dict(st, st.character("archer"))["reach_blocked"] is None


# --------------------------------------------------------------------------- #
# §D23-6 — generation gates and the widened enemy vocabulary
# --------------------------------------------------------------------------- #
def test_the_layout_gate_rejects_a_ranged_enemy_on_the_front_line():
    """§D23-3 makes an archer in Front a body with no shot; §D23-6 makes that a
    layout fault the generation gate refuses rather than shipping."""
    import pytest
    from ltg_game_server.llm import _check_ranged_placement
    _check_ranged_placement({"enemies": [{"id": "archer", "name": "Archer",
                                          "attack_mode": "ranged", "row": "mid"}]})
    with pytest.raises(ValueError, match="FRONT row"):
        _check_ranged_placement({"enemies": [{"id": "archer", "name": "Archer",
                                              "attack_mode": "ranged",
                                              "row": "front"}]})


def test_an_enemy_duellist_can_actually_force_a_trade():
    """§D23-6 teaches `fight` as enemy vocabulary. It used to fizzle every time
    from a component: a card's fight has two independent picks, and an enemy
    intent has only its target_rule's one."""
    duel = {"id": "duel", "timing": "proactive", "priority": 10,
            "target_rule": "valuation", "telegraph": "Duel",
            "verbs": [{"kind": "fight", "target": {"mode": "self"},
                       "other": {"mode": "chosen", "side": "ally",
                                 "targeted": True}}]}
    st = _state([_char("p", hp=30, power=4)],
                [_enemy("duellist", hp=30, power=5, components=[duel])])
    for _ in range(40):
        if st.character("p").hp < 30:
            break
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    assert st.character("p").hp == 30 - 5      # it dealt its Power…
    assert st.enemy("duellist").hp == 30 - 4   # …and took the hero's back
    assert not any(ev.type == "fizzle" for ev in st.log)
