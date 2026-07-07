"""Multi-select modal casts (Cryptic Command's "Choose two"): `choose: 2` offers
one cast per legal PAIR of modes (bitmask-encoded), each mode's chosen targets are
picked at cast (per-site), and resolution runs both modes' effects. Also pins the
untargeted-chosen fix: a `chosen`/`targeted:false` bounce enumerates real targets
instead of casting target-less and fizzling (the playtest bug)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict

# A faithful miniature of the translated Cryptic Command: counter / stun-all /
# bounce (chosen, UNtargeted — as the deckbuilder emits) / draw. Choose two.
_CRYPTIC = {
    "id": "cryptic", "name": "Cryptic Command", "source_name": "Cryptic Command",
    "rarity": "rare", "level": 4, "type": "Instant", "timing": "instant",
    "cost": {"generic": 0, "colors": {}},
    "translated_text": "Choose two — • Counter. • Stun all. • Bounce. • Draw.",
    "effects": [{
        "kind": "modal", "choose": 2, "or_more": False,
        "modes": [
            {"label": "", "effects": [{"kind": "counter", "filter": "action",
                                       "target": {"class": "action", "side": "enemy"}}]},
            {"label": "", "effects": [{"kind": "stun", "intents": 1,
                                       "target": {"mode": "all", "side": "enemy"}}]},
            {"label": "", "effects": [{"kind": "bounce",
                                       "target": {"mode": "chosen", "side": "any",
                                                  "targeted": False}}]},
            {"label": "", "effects": [{"kind": "draw", "amount": 1,
                                       "target": {"mode": "self"}}]},
        ],
    }],
    "validated": True,
}

_FILLER = {"id": "filler", "name": "filler", "source_name": "filler",
           "rarity": "common", "level": 1, "type": "Instant", "timing": "instant",
           "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "draw", "amount": 0}], "validated": True}


def _state():
    return state_from_dict({
        "party": [{"id": "ys", "name": "Ys", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["U"], "row": "front", "attack_mode": "melee",
                   "library": [dict(_CRYPTIC), dict(_FILLER), dict(_FILLER)]}],
        "enemies": [{"id": "e1", "name": "Gnasher", "hp": 10, "level": 2,
                     "intent": {"name": "Bite", "amount": 2, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}},
                    {"id": "e2", "name": "Howler", "hp": 10, "level": 2,
                     "intent": {"name": "Howl", "amount": 2, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })


def _casts(st):
    return [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "cryptic"]


def _mask_of(a):  # the bitmask combo encoding carried on the action
    return a.mode


def test_choose_two_offers_pair_combos_not_single_modes():
    st = _state()
    casts = _casts(st)
    masks = {_mask_of(a) for a in casts}
    # Main phase, empty stack: combos with the counter (bit 0) are uncastable.
    # Legal pairs of {stun(1), bounce(2), draw(3)}: 0b0110, 0b1010, 0b1100.
    assert masks == {0b0110, 0b1010, 0b1100}
    # Every combo is a PAIR (two set bits) — never a single mode.
    assert all(bin(m).count("1") == 2 for m in masks)


def test_bounce_mode_enumerates_targets():
    """The playtest bug: the bounce mode cast with no target and fizzled. Now every
    bounce-carrying combo offers one cast per creature."""
    st = _state()
    bounce_draw = [a for a in _casts(st) if _mask_of(a) == 0b1100]
    tids = {a.target_id for a in bounce_draw}
    assert {"e1", "e2", "ys"} <= tids            # side "any": enemies + party


def test_choose_two_resolves_both_modes():
    st = _state()
    # Cast "bounce + draw" aimed at Gnasher.
    act = next(a for a in _casts(st) if _mask_of(a) == 0b1100 and a.target_id == "e1")
    st = apply_action(st, act)[0]
    while st.stack:  # pass the reaction window; let it resolve
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    assert st.enemy("e1").in_hand                 # bounce landed
    assert len(st.character("ys").hand) >= 1      # draw landed
    assert not any(e.type == "fizzle" for e in st.log)


def test_stun_all_plus_draw_needs_no_target():
    st = _state()
    stun_draw = [a for a in _casts(st) if _mask_of(a) == 0b1010]
    assert len(stun_draw) == 1                    # zero target sites -> one cast
    st = apply_action(st, stun_draw[0])[0]
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    assert st.enemy("e1").stunned == 1 and st.enemy("e2").stunned == 1
    assert not any(e.type == "fizzle" for e in st.log)


def test_counter_combo_castable_only_with_an_enemy_action_on_stack():
    st = _state()
    # End the turn so the enemy step pushes an attack onto the stack.
    end = next(a for a in legal_actions(st) if a.kind == "end_turn")
    st = apply_action(st, end)[0]
    assert st.stack, "expected an enemy action awaiting reactions"
    casts = _casts(st)
    counter_combos = [a for a in casts if _mask_of(a) & 0b0001]
    assert counter_combos, "counter combos should appear in the reaction window"
    # Cast "counter + draw" at the enemy's swing.
    act = next(a for a in counter_combos if _mask_of(a) == 0b1001)
    st = apply_action(st, act)[0]
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    assert any(e.type == "countered" for e in st.log)
    assert not any(e.type == "counter_fizzle" for e in st.log)
