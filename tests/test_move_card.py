"""move_card: rendering, validation, and deterministic engine simulation."""

import pytest
from pydantic import ValidationError

from ltg_core.schema import Card
from ltg_core.translation import render_effects
from ltg_combat.state import CharacterState, GameState
from ltg_combat.engine import _r_move_card, _draw


def card(effects, timing="instant"):
    return Card.model_validate({
        "id": "x", "name": "x", "source_name": "x", "rarity": "common", "level": 1,
        "type": "X", "timing": timing, "effects": effects,
    })


# --- rendering: the three worked examples ------------------------------------ #
def test_render_draw_then_top():
    c = card([{"kind": "draw", "amount": 3},
              {"kind": "move_card", "count": 1, "source": "drawn", "destination": "library_top"}])
    assert render_effects(c.effects) == \
        "Draw 3 card(s). Put 1 of the drawn cards on top of your library."


def test_render_tutor_instant():
    c = card([{"kind": "move_card", "count": 1, "source": "library", "destination": "hand",
               "filter_type": "instant", "shuffle_after": True}])
    assert render_effects(c.effects) == \
        "Search your library for an instant, put it into your hand, then shuffle your library."


def test_render_discard():
    c = card([{"kind": "draw", "amount": 1},
              {"kind": "move_card", "count": 1, "source": "hand", "destination": "graveyard"}])
    assert render_effects(c.effects) == \
        "Draw 1 card(s). Put 1 card from your hand into your graveyard."


def test_render_level_filter():
    c = card([{"kind": "move_card", "count": 1, "source": "library", "destination": "hand",
               "filter_level": 3, "filter_level_compare": "or_more"}])
    assert render_effects(c.effects) == \
        "Search your library for a card of level 3 or more, put it into your hand."


# --- validation -------------------------------------------------------------- #
def test_move_card_cannot_target_enemy():
    with pytest.raises(ValidationError):
        card([{"kind": "move_card", "source": "hand", "destination": "graveyard",
               "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])


# --- engine simulation ------------------------------------------------------- #
def _mkcard(cid, timing="sorcery", level=1):
    return Card.model_validate({
        "id": cid, "name": cid.title(), "source_name": cid, "rarity": "common",
        "level": level, "type": "X", "timing": timing,
    })


def _mkchar(hand=None, library=None, graveyard=None):
    ch = CharacterState(id="p", name="P", max_hp=10, hp=10, power=1, hand_size=2)
    ch.hand = list(hand or [])
    ch.library = list(library or [])
    ch.graveyard = list(graveyard or [])
    return ch


def _move(ch, **kw):
    eff = card([{"kind": "move_card", **kw}]).effects[0]
    st = GameState(party=[ch], enemies=[])
    ctx = kw.pop("_ctx", None) or {}
    _r_move_card(st, None, eff, ch, ctx)
    return st


def test_engine_discard_hand_to_graveyard():
    a, b = _mkcard("a"), _mkcard("b")
    ch = _mkchar(hand=[a, b])
    _move(ch, count=1, source="hand", destination="graveyard")
    assert ch.hand == [b]
    assert ch.graveyard == [a]


def test_engine_tutor_picks_matching_type_and_shuffles():
    s1, inst, s2 = _mkcard("s1", "sorcery"), _mkcard("inst", "instant"), _mkcard("s2", "sorcery")
    ch = _mkchar(library=[s1, inst, s2])
    st = _move(ch, count=1, source="library", destination="hand",
               filter_type="instant", shuffle_after=True)
    assert inst in ch.hand and inst not in ch.library
    assert ch.library == [s1, s2]
    assert any(e.type == "shuffle" for e in st.log)


def test_engine_draw_then_put_one_on_top():
    c1, c2, c3, c4 = (_mkcard(f"c{i}") for i in range(1, 5))
    ch = _mkchar(library=[c1, c2, c3, c4])
    st = GameState(party=[ch], enemies=[])
    ctx = {}
    _draw(st, ch, 3, ctx)               # draws c1, c2, c3 (top first)
    assert ch.hand == [c1, c2, c3] and ctx["drawn_cards"] == [c1, c2, c3]
    eff = card([{"kind": "move_card", "count": 1, "source": "drawn",
                 "destination": "library_top"}]).effects[0]
    _r_move_card(st, None, eff, ch, ctx)
    assert ch.library[0] is c1          # the drawn card goes back on top
    assert c1 not in ch.hand and ch.hand == [c2, c3]
    assert c1 not in ctx["drawn_cards"]


def test_engine_no_match_logs_empty():
    ch = _mkchar(library=[_mkcard("s", "sorcery")])
    st = _move(ch, count=1, source="library", destination="hand", filter_type="instant")
    assert ch.hand == [] and any(e.type == "move_card_empty" for e in st.log)
