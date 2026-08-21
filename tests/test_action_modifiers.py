"""Action modifiers (`modify_action`): change what an evergreen ACTION *is* for a
duration, rather than moving HP or stats.

Each modifier belongs to exactly one action and the pair is validated at
authoring. Seven modifiers ride the character in `action_mods` and expire like a
granted keyword; the two resource ones (`refresh_skill`, `charge_ultimate`)
resolve once and ignore duration.
"""

from __future__ import annotations

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import ACTION_MODIFIERS, ModifyAction, t_chosen, t_self


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _mod_card(cid, action, modifier, amount=0, duration="this_turn"):
    """An instant that applies one action modifier to its caster."""
    eff = {"kind": "modify_action", "action": action, "modifier": modifier,
           "duration": duration, "target": {"mode": "self"}}
    if amount:
        eff["amount"] = amount
    out = _filler(cid)
    out["effects"] = [eff]
    return out


def _char(cid, power=2, hp=30, row="front", attack_mode="melee",
          library=None, hand=1, keywords=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": ["U"], "row": row, "attack_mode": attack_mode,
            "keywords": keywords or [],
            "library": library or [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid="e", hp=30, row="front", mode="melee", amount=2):
    return {"id": eid, "name": eid, "hp": hp, "level": 2, "power": 2,
            "row": row, "attack_mode": mode,
            "intent": {"name": "Bash", "amount": amount, "action_type": "attack",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": mode}}


def _state(party, enemies=None):
    return state_from_dict({"party": party, "enemies": enemies or [_enemy()]})


def _do(st, **kw):
    a = next(a for a in legal_actions(st)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(st, a)[0]


def _kinds(st, kind, actor=None):
    return [a for a in legal_actions(st)
            if a.kind == kind and (actor is None or a.actor_id == actor)]


def _resolve_stack(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def _cast_mod(st, cid):
    """Cast a self-targeting modifier card and let it resolve."""
    return _resolve_stack(_do(st, kind="cast", card_id=cid))


def _to_enemy_window(st):
    while True:
        acts = legal_actions(st)
        if st.stack and any(a.kind == "pass" for a in acts):
            return st
        nxt = next((a for a in acts if a.kind == "end_turn"), None) or acts[0]
        st = apply_action(st, nxt)[0]


def _end_turn(st):
    """Run to the next player phase, so the End step has expired this_turn mods."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        st = apply_action(st, next((a for a in acts if a.kind in ("pass", "end_turn")),
                                   acts[0]))[0]
    return st


# --------------------------------------------------------------------------- #
# The action/modifier pairing is validated at authoring
# --------------------------------------------------------------------------- #
def test_a_mismatched_action_and_modifier_is_rejected():
    with pytest.raises(ValueError, match="does not belong to action"):
        ModifyAction(action="attack", modifier="mitigate_full", target=t_self())


def test_the_error_names_the_action_the_modifier_belongs_to():
    with pytest.raises(ValueError, match="it modifies 'defend'"):
        ModifyAction(action="skill", modifier="defend_double", target=t_self())


def test_charge_ultimate_needs_an_amount():
    with pytest.raises(ValueError, match="positive `amount`"):
        ModifyAction(action="ultimate", modifier="charge_ultimate", target=t_self())


def test_every_registered_pair_constructs():
    """The registry is the source of truth the editor renders — every pair in it
    must actually be buildable."""
    for action, mods in ACTION_MODIFIERS.items():
        for mod in mods:
            amount = 5 if action == "ultimate" else 0   # the gauge pair needs one
            assert ModifyAction(action=action, modifier=mod, amount=amount,
                                target=t_self()).modifier == mod


def test_modify_action_reaches_the_authoring_dropdown():
    from ltg_core.schema import effect_specs
    assert "modify_action" in effect_specs()


# --------------------------------------------------------------------------- #
# Attack: reach
# --------------------------------------------------------------------------- #
def _flyer(eid="e"):
    """A flying enemy: ground melee cannot touch it (R-1), so it is the clean
    test of reach. (Row alone is not — a melee hero in the back lunges forward.)"""
    out = _enemy(eid, row="front")
    out["keywords"] = ["flying"]
    return out


def test_make_ranged_lets_a_melee_hero_hit_a_flyer():
    party = [_char("p", attack_mode="melee",
                   library=[_mod_card("bow", "attack", "make_ranged"), _filler("f")],
                   hand=2)]
    st = _state(party, [_flyer()])
    assert _kinds(st, "attack", "p") == []       # ground melee can't reach it
    st = _cast_mod(st, "bow")
    assert st.character("p").attack_mode == "ranged"
    assert _kinds(st, "attack", "p"), "reach granted — the shot is legal now"


def test_make_melee_takes_a_ranged_heros_reach_away():
    party = [_char("p", attack_mode="ranged",
                   library=[_mod_card("bind", "attack", "make_melee"), _filler("f")],
                   hand=2)]
    st = _state(party, [_flyer()])
    assert _kinds(st, "attack", "p")             # the bow reaches it
    st = _cast_mod(st, "bind")
    assert st.character("p").attack_mode == "melee"
    assert _kinds(st, "attack", "p") == []       # …and now it does not


def test_switch_mode_flips_whichever_reach_you_started_with():
    for start, flipped in (("melee", "ranged"), ("ranged", "melee")):
        party = [_char("p", attack_mode=start,
                       library=[_mod_card("shift", "attack", "switch_mode"),
                                _filler("f")], hand=2)]
        st = _cast_mod(_state(party), "shift")
        assert st.character("p").attack_mode == flipped


def test_an_expired_reach_modifier_restores_the_authored_mode():
    party = [_char("p", attack_mode="melee",
                   library=[_mod_card("bow", "attack", "make_ranged"), _filler("f")],
                   hand=2)]
    st = _cast_mod(_state(party), "bow")
    assert st.character("p").attack_mode == "ranged"
    st = _end_turn(st)
    assert st.character("p").attack_mode == "melee"      # back to what was authored
    assert st.character("p").action_mods == {}


def test_an_encounter_reach_modifier_survives_the_end_step():
    party = [_char("p", attack_mode="melee",
                   library=[_mod_card("bow", "attack", "make_ranged",
                                      duration="encounter"), _filler("f")], hand=2)]
    st = _cast_mod(_state(party), "bow")
    st = _end_turn(st)
    assert st.character("p").attack_mode == "ranged"


def test_the_attack_offer_and_the_swing_both_wear_the_new_reach():
    """The modifier writes the live `attack_mode`, so every downstream read — the
    offer label and the stack item R-1 legality runs on — follows for free."""
    party = [_char("p", attack_mode="melee",
                   library=[_mod_card("bow", "attack", "make_ranged"), _filler("f")],
                   hand=2)]
    st = _cast_mod(_state(party), "bow")
    offer = next(a for a in legal_actions(st) if a.kind == "attack")
    assert "ranged" in offer.label
    st = apply_action(st, offer)[0]
    assert st.stack[-1].attack_mode == "ranged"


# --------------------------------------------------------------------------- #
# Defend
# --------------------------------------------------------------------------- #
def test_defend_double_doubles_the_buffer():
    party = [_char("p", power=3,
                   library=[_mod_card("brace", "defend", "defend_double"),
                            _filler("f")], hand=2)]
    st = _cast_mod(_state(party), "brace")
    assert "+6" in next(a.label for a in legal_actions(st) if a.kind == "defend")
    st = _do(st, kind="defend", actor_id="p")
    assert st.character("p").temp_mod == 6        # base Power 3, doubled


def test_defend_as_reaction_is_offered_in_the_enemy_window():
    party = [_char("p", power=3,
                   library=[_mod_card("guard", "defend", "defend_as_reaction"),
                            _filler("f")], hand=2)]
    st = _cast_mod(_state(party), "guard")
    st = _to_enemy_window(st)
    assert _kinds(st, "defend", "p"), "the held Defend is available in the window"


def test_a_plain_hero_gets_no_defend_in_a_reaction_window():
    """Control — Defend is a main-phase action without the modifier."""
    st = _to_enemy_window(_state([_char("p", power=3)]))
    assert _kinds(st, "defend", "p") == []


def test_defending_as_a_reaction_after_spending_the_action():
    """The point of the modifier: you already attacked, and the shield is still
    there when the swing comes back at you."""
    party = [_char("p", power=3, hp=30,
                   library=[_mod_card("guard", "defend", "defend_as_reaction"),
                            _filler("f")], hand=2)]
    st = _cast_mod(_state(party), "guard")
    st = _do(st, kind="attack", actor_id="p")    # spend the proactive action
    st = _resolve_stack(st)
    st = _to_enemy_window(st)
    assert _kinds(st, "defend", "p"), "the action is spent, the reaction is not"
    st = _do(st, kind="defend", actor_id="p")
    # Declaring it passes priority, so the enemy swing resolves into the fresh
    # buffer and the turn ends — read the shield off the log rather than off a
    # temp_mod the End step has already cleared.
    ev = next(e for e in st.log if e.type == "defend")
    assert ev.data.get("amount") == 3
    assert "as a reaction" in ev.msg


def test_a_reaction_defend_is_still_once_per_turn():
    party = [_char("p", power=3,
                   library=[_mod_card("guard", "defend", "defend_as_reaction"),
                            _filler("f")], hand=2)]
    st = _cast_mod(_state(party), "guard")
    st = _to_enemy_window(st)
    st = _do(st, kind="defend", actor_id="p")
    st = _to_enemy_window(st)
    assert _kinds(st, "defend", "p") == []


# --------------------------------------------------------------------------- #
# Mitigate
# --------------------------------------------------------------------------- #
def test_mitigate_full_reduces_by_whole_power_not_half():
    from ltg_combat.engine import _mitigate_value
    party = [_char("p", power=5,
                   library=[_mod_card("aegis", "mitigate", "mitigate_full"),
                            _filler("f")], hand=2)]
    st = _state(party)
    assert _mitigate_value(st.character("p")) == 3        # ceil(5/2)
    st = _cast_mod(st, "aegis")
    assert _mitigate_value(st.character("p")) == 5        # full Power


def test_mitigate_full_shows_the_bigger_number_on_the_offer():
    party = [_char("p", power=5, hp=30,
                   library=[_mod_card("aegis", "mitigate", "mitigate_full"),
                            _filler("f")], hand=2)]
    st = _to_enemy_window(_cast_mod(_state(party), "aegis"))
    label = next(a.label for a in legal_actions(st) if a.kind == "mitigate")
    assert "−5" in label or "-5" in label


def _two_swings(party):
    """Two enemies swing in the same enemy step, so two reaction windows fall
    inside ONE turn — the only way to observe a once-per-turn limit, since the
    flag resets at the turn boundary."""
    return _state(party, [_enemy("e1"), _enemy("e2")])


def _offered_again_this_turn(st, kind="mitigate") -> bool:
    """Play out the rest of THIS turn; True if `kind` is ever offered again."""
    turn = st.turn
    for _ in range(60):
        if st.turn != turn or st.result is not None:
            return False
        acts = legal_actions(st)
        if any(a.kind == kind for a in acts):
            return True
        nxt = (next((a for a in acts if a.kind == "pass"), None)
               or next((a for a in acts if a.kind == "end_turn"), None))
        if nxt is None:
            return False
        st = apply_action(st, nxt)[0]
    return False


def test_mitigate_again_lifts_the_once_per_turn_limit():
    party = [_char("p", power=4, hp=40,
                   library=[_mod_card("ward", "mitigate", "mitigate_again"),
                            _filler("f")], hand=2)]
    st = _to_enemy_window(_cast_mod(_two_swings(party), "ward"))
    st = _do(st, kind="mitigate", target_id="p")
    assert st.character("p").used_mitigate            # it was spent…
    assert _offered_again_this_turn(st), "…and offered again anyway"


def test_without_the_modifier_mitigate_stays_once_per_turn():
    st = _to_enemy_window(_two_swings([_char("p", power=4, hp=40)]))
    st = _do(st, kind="mitigate", target_id="p")
    assert not _offered_again_this_turn(st)


# --------------------------------------------------------------------------- #
# The two resource modifiers (instant — no duration)
# --------------------------------------------------------------------------- #
def test_refresh_skill_gives_the_skill_back():
    st = _state([_char("p", library=[_mod_card("second_wind", "skill",
                                               "refresh_skill"), _filler("f")],
                       hand=2)])
    st.character("p").skill_used = True
    st = _cast_mod(st, "second_wind")
    assert st.character("p").skill_used is False


def test_refresh_skill_on_an_unused_skill_says_so_and_changes_nothing():
    st = _state([_char("p", library=[_mod_card("second_wind", "skill",
                                               "refresh_skill"), _filler("f")],
                       hand=2)])
    st = _cast_mod(st, "second_wind")
    assert st.character("p").skill_used is False
    assert any(ev.type == "action_mod" and "already available" in ev.msg
               for ev in st.log)


def test_charge_ultimate_fills_the_gauge_by_the_amount():
    st = _state([_char("p", library=[_mod_card("surge", "ultimate",
                                               "charge_ultimate", amount=30),
                                     _filler("f")], hand=2)])
    before = st.character("p").ultimate_gauge
    st = _cast_mod(st, "surge")
    assert st.character("p").ultimate_gauge == min(100, before + 30)


def test_the_instant_modifiers_leave_nothing_riding_the_character():
    """They change a resource, not a rule — so there is nothing to expire, and
    nothing to show in the status line."""
    for cid, action, mod, amt in (("sw", "skill", "refresh_skill", 0),
                                  ("su", "ultimate", "charge_ultimate", 10)):
        st = _state([_char("p", library=[_mod_card(cid, action, mod, amount=amt),
                                         _filler("f")], hand=2)])
        st = _cast_mod(st, cid)
        assert st.character("p").action_mods == {}


# --------------------------------------------------------------------------- #
# The hostile modifiers — the enemy repertoire
# --------------------------------------------------------------------------- #
def _skill_card(cid="war_cry"):
    out = _filler(cid)
    out["effects"] = [{"kind": "pump", "power": 1, "toughness": 0,
                       "target": {"mode": "self"}}]
    return out


def _hostile_enemy(modifier, amount=0, duration="encounter", eid="cutter"):
    """An enemy whose one component lands a hostile action modifier on a hero."""
    verb = {"kind": "modify_action",
            "action": {"lock_skill": "skill", "drain_ultimate": "ultimate",
                       "make_melee": "attack"}[modifier],
            "modifier": modifier, "duration": duration,
            "target": {"mode": "chosen", "side": "ally", "targeted": True}}
    if amount:
        verb["amount"] = amount
    return {"id": eid, "name": eid, "hp": 30, "level": 3, "power": 2,
            "attack_mode": "melee",
            "components": [{"id": "cut", "archetype": "Debilitate",
                            "timing": "proactive", "priority": 10,
                            "once_per_encounter": True, "target_rule": "valuation",
                            "telegraph": f"{modifier}", "verbs": [verb]}]}


def _advance_turns(st, n):
    turn = st.turn
    while st.result is None and st.turn < turn + n:
        acts = legal_actions(st)
        if not acts:
            break
        st = apply_action(st, next((a for a in acts if a.kind in ("pass", "end_turn")),
                                   acts[0]))[0]
    return st


def test_hamstring_bars_the_skill():
    party = [_char("p", hp=40)]
    party[0]["skill"] = _skill_card()
    st = _state(party, [_hostile_enemy("lock_skill")])
    assert _kinds(st, "use_skill", "p"), "sanity: the Skill is available first"
    st = _advance_turns(st, 2)
    assert "lock_skill" in st.character("p").action_mods
    assert _kinds(st, "use_skill", "p") == []


def test_hamstring_leaves_the_ultimate_alone():
    """A separate action, deliberately untouched — Hamstring narrows the turn, it
    does not flatten the character."""
    party = [_char("p", hp=40)]
    party[0]["skill"] = _skill_card()
    party[0]["ultimate"] = _skill_card("limit_break")
    st = _state(party, [_hostile_enemy("lock_skill")])
    st = _advance_turns(st, 2)
    st.character("p").ultimate_gauge = 100
    assert _kinds(st, "use_skill", "p") == []
    assert _kinds(st, "use_ultimate", "p"), "the Ultimate is a separate action"


def test_a_this_turn_hamstring_wears_off():
    party = [_char("p", hp=40)]
    party[0]["skill"] = _skill_card()
    st = _state(party, [_hostile_enemy("lock_skill", duration="this_turn")])
    st = _advance_turns(st, 2)
    st = _advance_turns(st, 1)
    assert st.character("p").action_mods == {}
    assert _kinds(st, "use_skill", "p")


def _advance_to_the_drain(st):
    """Stop the moment the drain resolves. Going further would let the enemy's
    NEXT basic attack land, and taking damage charges the gauge (D8-3.3) — which
    would quietly hide what the drain actually did."""
    for _ in range(80):
        if any(e.type == "action_mod" and e.data.get("modifier") == "drain_ultimate"
               for e in st.log):
            return st
        acts = legal_actions(st)
        if not acts or st.result is not None:
            return st
        st = apply_action(st, next((a for a in acts if a.kind in ("pass", "end_turn")),
                                   acts[0]))[0]
    return st


def test_drain_ultimate_takes_the_gauge_down():
    st = _state([_char("p", hp=40)], [_hostile_enemy("drain_ultimate", amount=25)])
    st.party[0].ultimate_gauge = 60
    st = _advance_to_the_drain(st)
    assert st.character("p").ultimate_gauge == 35


def test_drain_ultimate_never_goes_below_zero():
    st = _state([_char("p", hp=40)], [_hostile_enemy("drain_ultimate", amount=80)])
    st.party[0].ultimate_gauge = 10
    st = _advance_to_the_drain(st)
    assert st.character("p").ultimate_gauge == 0


def test_drain_ultimate_logs_what_it_actually_took():
    """A gauge with 10 in it loses 10, not the 80 that was attempted — the log
    reports the real loss so the player can trust the number."""
    st = _state([_char("p", hp=40)], [_hostile_enemy("drain_ultimate", amount=80)])
    st.party[0].ultimate_gauge = 10
    st = _advance_turns(st, 2)
    ev = next(e for e in st.log
              if e.type == "action_mod" and e.data.get("modifier") == "drain_ultimate")
    assert ev.data.get("amount") == 10


def test_drain_ultimate_needs_a_positive_amount():
    with pytest.raises(ValueError, match="positive `amount`"):
        ModifyAction(action="ultimate", modifier="drain_ultimate", target=t_self())


def test_make_melee_strips_a_ranged_heros_reach_as_an_enemy_debuff():
    party = [_char("p", attack_mode="ranged", hp=40)]
    st = _state(party, [_hostile_enemy("make_melee")])
    st = _advance_turns(st, 2)
    assert st.character("p").attack_mode == "melee"


def test_a_hamstring_intent_telegraphs_as_interference():
    """Veiled intents classify by their first hostile verb. Lockdown gets its own
    category so the player can tell 'something is being done to me' from 'I am
    about to be hit' — the answers are different."""
    from ltg_combat.serialize import intent_category, veiled_intent
    st = _state([_char("p", hp=40)], [_hostile_enemy("lock_skill")])
    # `round_intent` is the durable record the intents window reads; `intent` is
    # cleared once it executes, so sampling that races the enemy step.
    while st.enemies[0].round_intent is None and st.result is None:
        acts = legal_actions(st)
        st = apply_action(st, next((a for a in acts if a.kind == "end_turn"), acts[0]))[0]
    declared = st.enemies[0].round_intent
    assert "lock_skill" in declared.name, "sanity: the Hamstring is what it declared"
    assert intent_category(declared) == "interference"
    assert "foil" in veiled_intent(st, st.enemies[0])["line"]


def test_the_hostile_set_is_exactly_the_enemy_legal_modifiers():
    from ltg_core.schema import HOSTILE_ACTION_MODIFIERS, ACTION_MODIFIERS
    known = {m for mods in ACTION_MODIFIERS.values() for m in mods}
    assert HOSTILE_ACTION_MODIFIERS <= known
    assert HOSTILE_ACTION_MODIFIERS == {"make_melee", "lock_skill", "drain_ultimate"}


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #
def test_modifiers_show_in_the_status_line():
    from ltg_combat.serialize import _status_tags
    party = [_char("p", power=3,
                   library=[_mod_card("brace", "defend", "defend_double"),
                            _filler("f")], hand=2)]
    st = _cast_mod(_state(party), "brace")
    assert "defend: ×2" in _status_tags(st.character("p"))


def test_card_text_reads_as_rules_not_as_a_field_dump():
    from ltg_core.translation import render_effects
    text = render_effects([ModifyAction(action="mitigate", modifier="mitigate_full",
                                        target=t_chosen("ally", targeted=True))])
    assert "full Power" in text and "mitigate_full" not in text


def test_an_instant_modifier_states_no_duration():
    from ltg_core.translation import render_effects
    text = render_effects([ModifyAction(action="skill", modifier="refresh_skill",
                                        target=t_self())])
    assert "Skill is refreshed" in text
    assert "this turn" not in text.lower()


# --------------------------------------------------------------------------- #
# Enemies have none of these actions
# --------------------------------------------------------------------------- #
def test_a_modifier_aimed_at_an_enemy_does_nothing():
    from ltg_combat.engine import _r_modify_action
    st = _state([_char("p")], [_enemy()])
    enemy = st.enemies[0]
    _r_modify_action(st, None, ModifyAction(action="defend", modifier="defend_double",
                                            target=t_chosen("enemy", targeted=True)),
                     enemy, {})
    assert not getattr(enemy, "action_mods", None)
