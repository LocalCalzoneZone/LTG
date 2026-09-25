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
        # Mid, because §D23-3 leaves a ranged enemy in the Front row no shot.
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 20, "level": 1,
                     "row": "mid", "attack_mode": "ranged",
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

    # Voluntarily drop concentration → the taunt is lifted. A channel is only droppable
    # from the next turn on, so mark it as started last turn to reach that state.
    for ch in st.character("bait").channels:
        ch.started_turn = st.turn - 1
    drop = next((a for a in legal_actions(st) if a.kind == "drop_channels"), None)
    assert drop is not None
    st = apply_action(st, drop)[0]
    st = _pass_all(st)
    assert st.enemy("ogre").taunted_by is None


# --------------------------------------------------------------------------- #
# The wall holds (roadmap M1.18, ruled 2026-09-25) and heals are spared (M1.31)
# --------------------------------------------------------------------------- #
_TAUNT = {"id": "jeer", "name": "Jeer", "source_name": "Jeer", "rarity": "common",
          "level": 1, "type": "Instant", "timing": "instant",
          "cost": {"generic": 0, "colors": {}},
          "effects": [{"kind": "taunt",
                       "target": {"mode": "chosen", "side": "enemy", "targeted": True}}],
          "validated": True}


def _hero(hid, row, hp, library=()):
    return {"id": hid, "name": hid.title(), "hp": hp, "power": 2,
            "hand_size": len(library), "identity": ["U"], "row": row,
            "attack_mode": "melee", "library": list(library)}


def _melee(components=None, eid="brute"):
    e = {"id": eid, "name": eid.title(), "hp": 20, "level": 2, "power": 2,
         "row": "front", "attack_mode": "melee",
         "intent": {"name": "Smash", "amount": 3, "action_type": "attack",
                    "intent_type": "attack", "targeting": "lowest_hp_party",
                    "mode": "melee"}}
    if components:
        e["components"] = components
    return e


def _jeer(st, target="brute"):
    for _ in range(20):
        acts = legal_actions(st)
        act = next((a for a in acts if a.kind == "cast" and a.card_id == "jeer"
                    and a.target_id == target), None)
        if act is not None:
            return _pass_all(apply_action(st, act)[0])
        st = apply_action(st, next(a for a in acts if a.kind == "end_turn"))[0]
    raise AssertionError("Jeer never castable")


def test_a_rear_taunter_cannot_draw_a_melee_swing_and_the_swing_still_lands():
    """A melee body can't reach behind the wall, so the swing stays on the
    front row: it neither fizzles nor gets pushed around."""
    st = settle(state_from_dict({
        "party": [_hero("wall", "front", 12), _hero("mouth", "rear", 30, [_TAUNT])],
        "enemies": [_melee()]}))
    assert st.enemy("brute").intent.target_id == "wall"
    st = _jeer(st)
    assert st.enemy("brute").taunted_by == "mouth"
    assert st.enemy("brute").intent.target_id == "wall"     # the wall holds


def test_a_reachable_taunter_draws_an_enemy_ability_not_only_its_swing():
    gore = {"id": "gore", "timing": "proactive", "priority": 20,
            "target_rule": "valuation", "telegraph": "Gore — deal 4",
            "verbs": [{"kind": "deal_damage", "amount": 4,
                       "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}
    st = settle(state_from_dict({
        "party": [_hero("weak", "front", 6), _hero("loud", "front", 30, [_TAUNT])],
        "enemies": [_melee([gore])]}))
    assert st.enemy("brute").intent.target_id == "weak"
    st = _jeer(st)
    assert st.enemy("brute").intent.target_id == "loud"


def test_a_taunt_spares_the_enemys_heals():
    mend = {"id": "mend", "timing": "proactive", "priority": 20,
            "target_rule": "lowest_hp_ally", "telegraph": "Mend — heal 4",
            "verbs": [{"kind": "heal", "amount": 4,
                       "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}
    hurt = _melee(eid="hurt")
    hurt["hp"] = 20
    st = state_from_dict({
        "party": [_hero("loud", "front", 30, [_TAUNT])],
        "enemies": [_melee([mend], eid="brute"), hurt]})
    st.enemy("hurt").hp = 5
    st = settle(st)
    assert st.enemy("brute").intent.target_id == "hurt"      # it heals its friend
    st = _jeer(st)
    assert st.enemy("brute").intent.target_id == "hurt"      # the taunt spares it


def test_a_lured_enemy_declares_its_next_ability_at_the_channeler():
    """M1.18: under a held Lure the NEXT round's rule (not just the basic
    swing) lands on the channeler — declared there by `_component_target`, and
    re-aimed there by the Lure's own re-assertion."""
    gore = {"id": "gore", "timing": "proactive", "priority": 20,
            "target_rule": "valuation", "telegraph": "Gore — deal 4",
            "verbs": [{"kind": "deal_damage", "amount": 4,
                       "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}
    st = state_from_dict({
        "party": [{**_hero("bait", "front", 25, [dict(_LURE)]), "identity": ["G", "G", "W"]},
                  _hero("weak", "front", 5)],
        "enemies": [_melee([gore])]})
    st = _pass_all(_cast_lure(st))
    st = _advance_to_turn2_player(st)
    intent = st.enemy("brute").intent
    assert intent.source_component == "gore" and intent.target_id == "bait"
