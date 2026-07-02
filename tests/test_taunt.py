"""Continuous taunt (Lure): a channeled `taunt` forces every enemy to target the
channeler — on the cast turn (redirecting already-declared intents) AND on every
following turn (re-asserted at the end step). Driven through the engine's
legal_actions / apply_action contract."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict

# Lure: while channeled, all enemies must target the channeler.
_LURE = {
    "id": "lure", "name": "Lure", "source_name": "Lure", "rarity": "uncommon",
    "level": 1, "type": "Enchantment", "timing": "channeled",
    "cost": {"generic": 1, "colors": {"G": 2}},
    "effects": [{"kind": "taunt",
                 "target": {"mode": "all", "side": "enemy", "targeted": False},
                 "duration": "while_channeled"}],
    "validated": True,
}


def _state():
    return state_from_dict({
        "party": [
            # The Lure holder — high HP so the enemy wouldn't pick it by default, and
            # a hit won't break concentration.
            {"id": "bait", "name": "Bait", "hp": 25, "power": 2, "hand_size": 1,
             "identity": ["G", "G", "W"], "row": "front", "library": [dict(_LURE)]},
            # The low-HP ally the enemy targets by default.
            {"id": "ally", "name": "Ally", "hp": 5, "power": 2, "hand_size": 1,
             "identity": ["U"], "row": "rear",
             "library": [{"id": "f", "name": "f", "source_name": "f", "rarity": "common",
                          "level": 1, "type": "Instant", "timing": "instant",
                          "cost": {"generic": 0, "colors": {}},
                          "effects": [{"kind": "draw", "amount": 0}]}]},
        ],
        # Ranged so it reaches any row; hunts the lowest-HP character (→ Ally).
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 20, "level": 1,
                     "intent": {"name": "Hurl", "amount": 3, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "ranged"}}],
    })


def _cast_lure(state):
    """Advance to Bait's main phase and channel Lure."""
    while True:
        acts = legal_actions(state)
        lure = next((a for a in acts if a.kind == "cast" and a.card_id == "lure"), None)
        if lure is not None:
            return apply_action(state, lure)[0]
        nxt = next((a for a in acts if a.kind == "end_turn"), None) or acts[0]
        state = apply_action(state, nxt)[0]


def _pass_all(state):
    while state.stack:
        p = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if p is None:
            break
        state = apply_action(state, p)[0]
    return state


def _advance_to_turn2_player(state):
    """Advance to turn 2's player phase — i.e. past the capacity choice and the
    intents step, so the turn-2 enemy intents have been declared."""
    while not (state.turn >= 2 and state.phase == "player"):
        acts = legal_actions(state)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        state = apply_action(state, a)[0]
    return state


def test_lure_redirects_the_current_and_future_enemy_intents():
    st = _state()

    # Before Lure: the ogre hunts the lowest-HP character (Ally).
    assert settle(st).enemy("ogre").intent.target_id == "ally"

    # Channel Lure, then resolve the reaction window it opened.
    st = _cast_lure(st)
    st = _pass_all(st)

    # Cast turn: the already-declared intent is redirected onto the channeler.
    assert st.enemy("ogre").intent.target_id == "bait"

    # Next turn: the taunt is re-asserted, so the freshly declared intent also
    # targets the channeler (not the low-HP Ally).
    st = _advance_to_turn2_player(st)
    ogre = st.enemy("ogre")
    assert ogre is not None and ogre.intent is not None
    assert ogre.intent.target_id == "bait"


def test_taunt_lifts_when_the_channel_is_dropped():
    st = _state()
    st = _cast_lure(st)
    st = _pass_all(st)
    assert st.enemy("ogre").taunted_by == "bait"

    # Voluntarily drop concentration → the taunt is lifted.
    drop = next((a for a in legal_actions(st) if a.kind == "drop_channels"), None)
    assert drop is not None
    st = apply_action(st, drop)[0]
    st = _pass_all(st)
    assert st.enemy("ogre").taunted_by is None
