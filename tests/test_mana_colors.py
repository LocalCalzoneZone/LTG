"""Roadmap M1.19: the curve-up locks the character's COLOURS (it read the
starting mana, so a colour missing from it could never be locked), and a
`choice` ramp or ritual is a pick made at cast, like a mode or X (it
auto-resolved to the first colour)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict


def _card(cid, effects, timing="instant"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": timing.title(), "timing": timing,
            "cost": {"generic": 0, "colors": {}}, "effects": effects}


def _filler(cid):
    return _card(cid, [{"kind": "draw", "amount": 0}])


def _state(hand_cards, colors=("G", "W", "U"), mana=("G", "G")):
    party = [{"id": "p", "name": "p", "hp": 30, "power": 2, "hand_size": len(hand_cards),
              "identity": list(mana), "colors": list(colors), "row": "front",
              "attack_mode": "melee",
              "library": list(hand_cards) + [_filler(f"f{i}") for i in range(6)]}]
    enemy = {"id": "e", "name": "e", "hp": 30, "level": 2, "power": 1, "row": "front",
             "attack_mode": "melee",
             "intent": {"name": "Bash", "amount": 1, "action_type": "attack",
                        "intent_type": "attack", "targeting": "lowest_hp_party",
                        "mode": "melee"}}
    return state_from_dict({"party": party, "enemies": [enemy]}, seed=3)


def _run_to(st, pred):
    for _ in range(200):
        acts = legal_actions(st)
        if pred(st, acts):
            return st, acts
        nxt = next((a for a in acts if a.kind in ("pass", "end_turn")), acts[0])
        st = apply_action(st, nxt)[0]
    raise AssertionError("never reached")


def test_the_curve_up_offers_every_colour_of_the_character():
    st, acts = _run_to(_state([]), lambda s, a: any(x.kind == "choose_mana" for x in a))
    offered = sorted(a.color for a in acts if a.kind == "choose_mana")
    assert offered == ["G", "U", "W"]          # U and W were never in the starting mana
    pick = next(a for a in acts if a.kind == "choose_mana" and a.color == "U")
    st = apply_action(st, pick)[0]
    assert st.character("p").mana_colors.count("U") == 1


def test_a_choice_ramp_is_picked_at_cast():
    ramp = _card("grow", [{"kind": "ramp", "amount": 1, "color": "choice",
                           "availability": "immediate"}])
    st = settle(_state([ramp]))
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "grow"]
    assert sorted(a.color for a in casts) == ["G", "U", "W"]
    assert all("(as " in a.label for a in casts)
    st = apply_action(st, next(a for a in casts if a.color == "W"))[0]
    while st.stack:
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    assert "W" in st.character("p").mana_colors and "W" in st.character("p").pool


def test_a_choice_ritual_is_picked_at_cast_and_a_one_colour_hero_is_not_asked():
    ritual = _card("spark", [{"kind": "add_mana", "amount": 2, "color": "choice"}])
    st = settle(_state([ritual]))
    casts = [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "spark"]
    st = apply_action(st, next(a for a in casts if a.color == "U"))[0]
    while st.stack:
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    assert st.character("p").pool.count("U") == 2
    mono = settle(_state([ritual], colors=("G",), mana=("G",)))
    casts = [a for a in legal_actions(mono) if a.kind == "cast" and a.card_id == "spark"]
    assert [a.color for a in casts] == [None]
