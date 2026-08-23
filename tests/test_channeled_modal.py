"""Playtest bug (2026-08-23): a `modal` ("choose one") written on a CHANNELED card
resolved nothing. `_start_channel` sorts a card's effects into continuous (held),
`channel_start` (fires once) and `upkeep`/event (recurring) — a `modal` wrapper is
none of those, so the mode the player picked at cast was never looked at.

The channel now holds its EXPANDED effects (`Channel.effects`): the card's, with a
top-level modal replaced by the picked mode. Every rule that asks what a channel is
doing reads that, so a mode's aura holds, its tick ticks, and its tags lift."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict

SELF = {"mode": "self"}
ALL_ENEMIES = {"mode": "all", "side": "enemy"}


def _card(effects, cid="choice"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "rare", "level": 2,
            "type": "Enchantment", "timing": "channeled",
            "cost": {"generic": 0, "colors": {}}, "effects": effects, "validated": True}


def _modal(*modes):
    return _card([{"kind": "modal", "choose": 1,
                   "modes": [{"label": lbl, "effects": effs} for lbl, effs in modes]}])


def _state(card, hp=20):
    st = state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 30, "power": 3, "hand_size": 1,
                   "identity": ["W", "W"], "row": "front", "attack_mode": "melee",
                   "library": [dict(card)]}],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 40, "level": 1,
                     "intent": {"name": "Bash", "amount": 1, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}]})
    st.character("p").hp = hp
    return st


def _cast(st, mode=None, card_id="choice"):
    a = next(x for x in legal_actions(st)
             if x.kind == "cast" and x.card_id == card_id
             and (mode is None or x.mode == mode))
    st = apply_action(st, a)[0]
    while True:
        picks = [x for x in legal_actions(st) if x.kind.startswith("choose")]
        if not picks:
            break
        st = apply_action(st, picks[0])[0]
    return apply_action(st, next(x for x in legal_actions(st) if x.kind == "pass"))[0]


def _do(st, kind, **m):
    for a in legal_actions(st):
        if a.kind == kind and all(getattr(a, k) == v for k, v in m.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal {kind} {m}")


def _next_turn(st):
    """Advance one turn, then drain any stack the new turn's upkeep triggers put
    up (a channel tick resolves through the stack like any triggered ability)."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        st = apply_action(st, next((a for a in acts if a.kind in ("end_turn", "pass")),
                                   acts[0]))[0]
    for _ in range(20):
        if st.result is not None or not st.stack:
            break
        nxt = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if nxt is None:
            break
        st = apply_action(st, nxt)[0]
    return st


HEAL_START = {"kind": "heal", "amount": 5, "target": SELF, "trigger": "channel_start"}
DEFENDER = {"kind": "grant_keyword", "keywords": ["defender"],
            "target": SELF, "duration": "while_channeled"}
ANTHEM = {"kind": "pump", "power": 2, "toughness": 0,
          "target": {"mode": "all", "side": "ally"}, "duration": "while_channeled"}
TICK = {"kind": "deal_damage", "amount": 2, "target": ALL_ENEMIES, "trigger": "upkeep"}


def test_the_picked_mode_fires_its_channel_start_and_holds_its_aura():
    st = _cast(_state(_modal(("Ward", [dict(HEAL_START), dict(DEFENDER)]),
                             ("Tick", [dict(TICK)]))), mode=0)
    p = st.character("p")
    assert p.hp == 25                                   # the channel_start half fired
    assert p.keywords.get("defender") == "while_channeled"
    assert len(p.channels) == 1


def test_the_mode_the_player_did_not_pick_does_nothing():
    st = _cast(_state(_modal(("Ward", [dict(HEAL_START), dict(DEFENDER)]),
                             ("Tick", [dict(TICK)]))), mode=1)
    p = st.character("p")
    assert p.hp == 20 and "defender" not in p.keywords  # mode 0 stayed shut
    assert len(p.channels) == 1
    assert st.enemy("ogre").hp == 40                    # the tick waits for upkeep


def test_a_modes_upkeep_tick_recurs_while_the_channel_holds():
    st = _cast(_state(_modal(("Tick", [dict(TICK)]),
                             ("Ward", [dict(DEFENDER)]))), mode=0)
    assert st.enemy("ogre").hp == 40                    # nothing at cast
    st = _next_turn(st)
    assert st.enemy("ogre").hp == 38                    # one upkeep
    st = _next_turn(st)
    assert st.enemy("ogre").hp == 36                    # and it keeps ticking


def test_a_modes_aura_lifts_when_the_channel_ends():
    st = _cast(_state(_modal(("Anthem", [dict(ANTHEM), dict(DEFENDER)]),
                             ("Tick", [dict(TICK)]))), mode=0)
    p = st.character("p")
    assert p.power_bonus == 2 and p.keywords.get("defender") == "while_channeled"
    st = _next_turn(st)
    assert st.character("p").power_bonus == 2           # re-asserted across the end step
    st = _do(st, "drop_channels")
    p = st.character("p")
    assert not p.channels
    assert p.power_bonus == 0 and "defender" not in p.keywords


def test_both_modes_are_offered_at_cast():
    st = settle(_state(_modal(("Ward", [dict(DEFENDER)]), ("Tick", [dict(TICK)]))))
    modes = sorted(a.mode for a in legal_actions(st)
                   if a.kind == "cast" and a.card_id == "choice")
    assert modes == [0, 1]


def test_a_non_modal_channel_is_untouched():
    """The regression spine: a plainly-written channel holds exactly as before."""
    st = _cast(_state(_card([dict(ANTHEM), dict(HEAL_START)])))
    p = st.character("p")
    assert p.hp == 25 and p.power_bonus == 2 and len(p.channels) == 1
    assert p.channels[0].effects == list(p.channels[0].card.effects)
