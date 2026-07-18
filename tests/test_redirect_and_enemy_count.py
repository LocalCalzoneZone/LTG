"""The `redirect` effect (turn a targeted stack action onto a new target) and
the `enemy_count` value reference (the number of living enemies, read at
resolution)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import Card, REF_VALUES, effect_specs
from ltg_core.translation import render_effects

CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}


def _card(cid, name, timing, effects):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": 1, "type": "Spell", "timing": timing,
            "cost": {"generic": 0, "colors": {}},  # free: castable any window
            "effects": effects, "validated": True}


def _char(cid, hp=20, hand=0, library=None):
    return {"id": cid, "name": cid, "hp": hp, "power": 3, "hand_size": hand,
            "identity": ["U"], "row": "front", "attack_mode": "melee",
            "library": library or []}


def _enemy(eid, hp=10, amount=3, keyword=None):
    e = {"id": eid, "name": eid, "hp": hp, "level": 3,
         "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                    "intent_type": "attack", "targeting": "lowest_hp_party",
                    "mode": "melee"}}
    if keyword:
        e["keywords"] = [keyword]
    return e


def _do(st, kind, **match):
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal '{kind}' action ({match}) among "
                         f"{[a.label for a in legal_actions(st)]}")


def _pass_all(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


_BOLT = _card("bolt", "Bolt", "sorcery",
              [{"kind": "deal_damage", "amount": 3, "target": CHOSEN_ENEMY_T}])
_TURN = _card("turn", "Turn Aside", "instant",
              [{"kind": "redirect", "filter": "spell",
                "new_target": CHOSEN_ENEMY_T}])


# ========================================================================== #
# redirect: a chosen new target (two-site cast)
# ========================================================================== #
def test_redirect_turns_a_spell_onto_a_new_target():
    st = state_from_dict({
        "party": [_char("p", hand=2, library=[_BOLT, _TURN])],
        "enemies": [_enemy("e1"), _enemy("e2")],
    })
    st = _do(st, "cast", card_id="bolt", target_id="e1")
    # In the bolt's window: redirect it, picking (the bolt, e2) in one cast.
    turn = next(a for a in legal_actions(st)
                if a.kind == "cast" and a.card_id == "turn" and "e2" in (a.targets or ()))
    st = apply_action(st, turn)[0]
    st = _pass_all(st)
    assert st.enemy("e1").hp == 10               # spared
    assert st.enemy("e2").hp == 7                # the bolt, re-aimed
    assert any(ev.type == "redirect" for ev in st.log)


def test_redirect_with_nothing_on_the_stack_is_uncastable():
    st = state_from_dict({
        "party": [_char("p", hand=1, library=[_TURN])],
        "enemies": [_enemy("e1")],
    })
    assert not any(a.kind == "cast" and a.card_id == "turn"
                   for a in legal_actions(st))


# ========================================================================== #
# redirect: "to yourself" (single-site Bodyguard shape) + relentless
# ========================================================================== #
_INTERCEPT = _card("icpt", "Intercept", "instant",
                   [{"kind": "redirect", "filter": "action",
                     "new_target": {"mode": "self"}}])


def _enemy_swings(st):
    """Drive the enemy turn until its swing sits on the stack and the party
    holds a reaction window (or the turn ends)."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        if any(s.source_side == "enemy" for s in st.stack):
            acts = legal_actions(st)
            if any(a.kind == "cast" for a in acts):
                return st
        acts = legal_actions(st)
        if not acts:
            break
        a = next((x for x in acts if x.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, a)[0]
    return st


def test_redirect_pulls_an_enemy_swing_onto_the_caster():
    # q is healthier, so the enemy aims at p; q's Intercept pulls the blow.
    st = state_from_dict({
        "party": [_char("p", hp=10), _char("q", hp=20, hand=1, library=[_INTERCEPT])],
        "enemies": [_enemy("e1", amount=4)],
    })
    st = _do(st, "end_turn")                      # p passes the turn along
    st = _enemy_swings(st)
    st = _do(st, "cast", card_id="icpt")
    st = _pass_all(st)
    assert st.character("p").hp == 10             # spared
    assert st.character("q").hp == 16             # took the 4 instead


def test_relentless_swings_are_never_offered_to_redirect():
    st = state_from_dict({
        "party": [_char("p", hp=10), _char("q", hp=20, hand=1, library=[_INTERCEPT])],
        "enemies": [_enemy("e1", amount=4, keyword="relentless")],
    })
    st = _do(st, "end_turn")
    st = _enemy_swings(st)
    assert not any(a.kind == "cast" and a.card_id == "icpt"
                   for a in legal_actions(st))


# ========================================================================== #
# the enemy_count reference
# ========================================================================== #
def test_enemy_count_ref_scales_with_living_enemies():
    volley = _card("volley", "Volley", "sorcery",
                   [{"kind": "deal_damage", "amount": {"ref": "enemy_count"},
                     "target": CHOSEN_ENEMY_T}])
    st = state_from_dict({
        "party": [_char("p", hand=1, library=[volley])],
        "enemies": [_enemy("e1"), _enemy("e2"), _enemy("e3")],
    })
    st = _do(st, "cast", card_id="volley", target_id="e1")
    st = _pass_all(st)
    assert st.enemy("e1").hp == 7                 # three enemies → 3 damage
    text = render_effects(Card.model_validate(volley).effects, {})
    assert "the number of enemies" in text


def test_enemy_count_is_registered_for_the_editor():
    assert "enemy_count" in REF_VALUES
    specs = effect_specs()
    assert "redirect" in specs
    names = {p["name"] for p in specs["redirect"]["params"]}
    assert {"target", "filter", "new_target"} <= names
