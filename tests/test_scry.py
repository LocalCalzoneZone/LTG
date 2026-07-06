"""Interactive scry: after seeing the top X cards the player places each on the
top (in a chosen order) or the bottom of the library. Driven through the engine's
legal_actions / apply_action contract (exactly as the cockpit does)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.serialize import build_menu
from ltg_combat.scenario import state_from_dict

_ATTACK = {"name": "Hit", "amount": 1, "action_type": "ability",
           "intent_type": "attack", "targeting": "lowest_hp_party", "mode": "melee"}


def _spell(cid, effects):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
            "effects": effects}


def _plain(cid):
    return _spell(cid, [{"kind": "draw", "amount": 0}])  # a harmless filler card


_SCRY3 = [{"kind": "scry", "amount": 3, "target": {"mode": "self"}}]


def _state(library, hand_size=1):
    spec = {
        "party": [{"id": "p", "name": "Caster", "hp": 30, "power": 2,
                   "hand_size": hand_size, "identity": ["U"], "library": library}],
        "enemies": [{"id": "ea", "name": "EnemyA", "hp": 12, "level": 1, "intent": dict(_ATTACK)}],
    }
    return state_from_dict(spec)


def _do(state, **kw):
    a = next(a for a in legal_actions(state)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(state, a)[0]


def _lib(state):
    return [c.id for c in state.character("p").library]


def _open_scry(card_ids):
    """Cast a scry-3 card and resolve it into the pending scry choice. The library
    under test (after the opening hand + turn-1 upkeep draw) is exactly `card_ids`."""
    library = [_spell("sift", _SCRY3)] + [_plain(c) for c in card_ids]
    st = _state(library, hand_size=1)               # opening hand = [sift]
    # The upkeep draws the first filler; cast Sift and let the sorcery resolve.
    st = _do(st, kind="cast", card_id="sift")
    st = _do(st, kind="pass")
    return st


def _place(state, card_id, dest):
    a = next(a for a in legal_actions(state)
             if a.kind == "choose_scry" and a.target_id == dest
             and state.pending_choice.candidates[a.choice].id == card_id)
    return apply_action(state, a)[0]


# --- the prompt --------------------------------------------------------------- #
def test_scry_reveals_top_and_offers_top_or_bottom_per_card():
    st = _open_scry(["a", "b", "c", "d"])           # upkeep drew 'a' → top is b,c,d
    assert st.pending_choice is not None and st.pending_choice.kind == "scry"
    assert [c.id for c in st.pending_choice.candidates] == ["b", "c", "d"]

    acts = legal_actions(st)
    assert acts and all(a.kind == "choose_scry" for a in acts)
    # Two placements (top / bottom) per revealed card.
    assert len(acts) == 2 * 3
    assert {a.target_id for a in acts} == {"top", "bottom"}


def test_scry_orders_top_by_pick_order_and_bottoms_the_rest():
    st = _open_scry(["a", "b", "c", "d"])           # library is b, c, d (then nothing)
    # Keep c on top first (drawn first), then b on top, send d to the bottom.
    st = _place(st, "c", "top")
    st = _place(st, "b", "top")
    st = _place(st, "d", "bottom")

    assert st.pending_choice is None                # all revealed cards placed
    # c (1st top pick) is drawn first, then b; the untouched rest, then bottomed d.
    assert _lib(st) == ["c", "b", "d"]
    assert _lib(st)[0] == "c"                        # the next draw is the chosen top card


def test_scry_all_to_bottom_inverts_nothing_but_sinks_them():
    st = _open_scry(["a", "b", "c"])                # library is b, c
    st = _place(st, "b", "bottom")
    st = _place(st, "c", "bottom")
    assert st.pending_choice is None
    # Nothing kept on top; both revealed cards sink under the (empty) rest.
    assert _lib(st) == ["b", "c"]


def test_scry_draw_position_label_advances_as_cards_are_kept():
    st = _open_scry(["a", "b", "c", "d"])
    first = [a.label for a in legal_actions(st) if a.target_id == "top"]
    assert all("draw #1" in lbl for lbl in first)   # nothing kept yet
    st = _place(st, "b", "top")
    second = [a.label for a in legal_actions(st) if a.target_id == "top"]
    assert all("draw #2" in lbl for lbl in second)  # one already on top


def test_scry_menu_renders_for_cockpit():
    st = _open_scry(["a", "b", "c"])
    menu = build_menu(st, legal_actions(st))
    assert menu[0]["kind"] == "prompt" and "Scry" in menu[0]["label"]
    assert all(m["kind"] in ("prompt", "choose_scry") for m in menu)
    assert any("on top" in m["label"] for m in menu)
    assert any("bottom" in m["label"] for m in menu)


def test_scry_then_chosen_effect_resolves_on_the_picked_target():
    """A card like Gods Willing (scry + a `chosen`/`targeted:false` prevent) now
    enumerates a target at cast — `chosen` means the caster picks, whether or not
    the effect is `targeted` (which only governs interaction rules). The post-scry
    effect must resolve onto that pick, not fizzle target-less (the old pinned
    behaviour — the same bug that made Cryptic Command's bounce fizzle)."""
    card = _spell("gods_willing", [
        {"kind": "scry", "amount": 1, "target": {"mode": "self"}},
        {"kind": "prevent", "parameter": "combat_damage", "uses": "all",
         "duration": "this_turn",
         "target": {"mode": "chosen", "side": "any", "targeted": False}},
    ])
    st = _state([card] + [_plain(c) for c in ("a", "b")], hand_size=1)
    st = _do(st, kind="cast", card_id="gods_willing", target_id="p")  # pick self
    st = _do(st, kind="pass")                    # resolve the sorcery → raises the scry choice
    revealed = st.pending_choice.candidates[0].id
    st = _place(st, revealed, "top")             # complete the scry → resolves the prevent
    assert st.pending_choice is None and not st.stack
    caster = st.character("p")
    assert any(t.parameter == "combat_damage" for t in caster.prevent_tags)


def _chan(cid, effects):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Enchantment", "timing": "channeled",
            "cost": {"generic": 0, "colors": {}}, "effects": effects}


def test_channel_break_scry_is_interactive():
    """Regression: a channel_break trigger's scry must pause for the player's
    top/bottom picks when the break trigger resolves off the stack — it used to
    auto-reveal (the `trigger is None` gate skipped the interactive path) and any
    following draw fired immediately with the library untouched."""
    moonstone = _chan("moonstone", [
        {"kind": "scry", "amount": 2, "target": {"mode": "self"}, "trigger": "channel_break"},
        {"kind": "draw", "amount": 1, "target": {"mode": "self"}, "trigger": "channel_break"},
    ])
    st = _state([moonstone] + [_plain(c) for c in ("a", "b", "c", "d")], hand_size=1)
    st = _do(st, kind="cast", card_id="moonstone")   # upkeep drew 'a'; hand held moonstone
    st = _do(st, kind="pass")                        # the channel starts (nothing fires)
    assert st.character("p").channels and st.pending_choice is None

    for ch in st.character("p").channels:            # make the drop legal this turn
        ch.started_turn = st.turn - 1
    st = _do(st, kind="drop_channels")               # break trigger goes on the stack
    assert [i.kind for i in st.stack] == ["triggered"]
    st = _do(st, kind="pass")                        # resolve it → the scry must pause
    assert st.pending_choice is not None and st.pending_choice.kind == "scry"
    assert [c.id for c in st.pending_choice.candidates] == ["b", "c"]

    st = _place(st, "c", "top")                      # keep c on top…
    st = _place(st, "b", "bottom")                   # …sink b
    assert st.pending_choice is None and not st.stack
    # The trigger's remaining draw resolved AFTER the scry, onto the ordered library.
    assert [c.id for c in st.character("p").hand][-1] == "c"
    assert _lib(st) == ["d", "b"]


def test_channel_start_scry_is_interactive():
    """The channel_start (ETB) analogue of the same regression: an on-start scry
    pauses at cast-resolution instead of auto-revealing."""
    lens = _chan("lens", [
        {"kind": "scry", "amount": 2, "target": {"mode": "self"}, "trigger": "channel_start"},
    ])
    st = _state([lens] + [_plain(c) for c in ("a", "b", "c")], hand_size=1)
    st = _do(st, kind="cast", card_id="lens")
    st = _do(st, kind="pass")                        # channel starts → scry pauses
    assert st.pending_choice is not None and st.pending_choice.kind == "scry"
    assert [c.id for c in st.pending_choice.candidates] == ["b", "c"]
    st = _place(st, "b", "bottom")
    st = _place(st, "c", "bottom")
    assert st.pending_choice is None
    assert st.character("p").channels                # the channel held through it
    assert _lib(st) == ["b", "c"]
