"""Playtest bug (2026-08-23): a `while_channeled` grant written BELOW a channelled
card's top level — inside a `channel_start` trigger, a conditional, a modal mode
or a stance's replaced ability — never lifted when the channel ended, because the
break only walked the card's top-level continuous effects.

The live case is Turin's "Inspired Defence": *when this channel begins, if you are
in the front row, your Mitigate is no longer once per turn while channeled* — the
unlimited Mitigate outlived the channel for the rest of the encounter."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict

SELF = {"mode": "self"}
MITIGATE_AGAIN = {"kind": "modify_action", "action": "mitigate",
                  "modifier": "mitigate_again", "amount": 0,
                  "target": SELF, "duration": "while_channeled"}
DEFENDER = {"kind": "grant_keyword", "keywords": ["defender"],
            "target": SELF, "duration": "while_channeled"}


def _card(cid, effects, timing="channeled"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "rare", "level": 2,
            "type": "Enchantment", "timing": timing,
            "cost": {"generic": 0, "colors": {}}, "effects": effects,
            "validated": True}


def _inspired_defence(cid="aura", row="front"):
    """The shipped shape: a channel_start conditional wrapping the tag."""
    return _card(cid, [
        {"trigger": "channel_start", "kind": "conditional",
         "condition": {"kind": "caster_property", "property": "row", "row": row},
         "effects": [dict(MITIGATE_AGAIN)]}])


def _state(cards, row="front", hand=None):
    hand = len(cards) if hand is None else hand
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 30, "power": 3, "hand_size": hand,
                   "identity": ["W", "W"], "row": row, "attack_mode": "melee",
                   "library": [dict(c) for c in cards]}],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 40, "level": 1,
                     "intent": {"name": "Bash", "amount": 2, "action_type": "attack",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })


def _do(st, kind, **match):
    for a in legal_actions(st):
        if a.kind == kind and all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal {kind} {match} — have "
                         f"{sorted({a.kind for a in legal_actions(st)})}")


def _hold(st, card_id):
    """Cast the channel and let it resolve."""
    st = _do(st, "cast", card_id=card_id)
    return _do(st, "pass")


def _next_turn(st):
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        st = apply_action(st, next((a for a in acts if a.kind in ("end_turn", "pass")),
                                   acts[0]))[0]
    return st


# --------------------------------------------------------------------------- #
# The reported bug
# --------------------------------------------------------------------------- #
def test_a_channel_start_action_mod_lifts_when_the_channel_is_dropped():
    st = _hold(_state([_inspired_defence()]), "aura")
    p = st.character("p")
    assert p.action_mods.get("mitigate_again") == "while_channeled"
    st = _next_turn(st)                       # a same-turn channel can't be dropped
    st = _do(st, "drop_channels")
    p = st.character("p")
    assert not p.channels
    assert "mitigate_again" not in p.action_mods


def test_a_channel_start_action_mod_lifts_when_the_channel_is_broken():
    st = _hold(_state([_inspired_defence()]), "aura")
    from ltg_combat.engine import _break_channels          # the ≥25% hit path
    _break_channels(st, st.character("p"), reason="break")
    p = st.character("p")
    assert not p.channels and "mitigate_again" not in p.action_mods


def test_a_channel_start_keyword_lifts_too():
    st = _hold(_state([_card("ward", [
        {"trigger": "channel_start", "kind": "conditional",
         "condition": {"kind": "caster_property", "property": "row", "row": "front"},
         "effects": [dict(DEFENDER)]}])]), "ward")
    assert st.character("p").keywords.get("defender") == "while_channeled"
    st = _next_turn(st)
    st = _do(st, "drop_channels")
    assert "defender" not in st.character("p").keywords


def test_a_plain_top_level_continuous_tag_still_lifts_exactly_once():
    """The regression guard: the sweep must not double-lift what the continuous
    pass already took (nor log a second time)."""
    st = _hold(_state([_card("aura", [dict(MITIGATE_AGAIN), dict(DEFENDER)])]), "aura")
    p = st.character("p")
    assert p.action_mods.get("mitigate_again") == "while_channeled"
    assert p.keywords.get("defender") == "while_channeled"
    st = _next_turn(st)
    st = _do(st, "drop_channels")
    p = st.character("p")
    assert "mitigate_again" not in p.action_mods and "defender" not in p.keywords
    lifts = [e for e in st.log if e.type == "grant_keyword" and "loses" in e.msg]
    assert len(lifts) == 1


def test_an_unfired_conditional_lifts_nothing_and_says_nothing():
    """Turin in the REAR row: the condition fails, so the mod was never granted —
    the break must not log a phantom lift."""
    st = _hold(_state([_inspired_defence(row="front")], row="rear"), "aura")
    p = st.character("p")
    assert "mitigate_again" not in p.action_mods
    st = _next_turn(st)
    st = _do(st, "drop_channels")
    assert not [e for e in st.log if e.type == "grant_keyword" and "loses" in e.msg]
    assert "mitigate_again" not in st.character("p").action_mods


def test_a_lift_leaves_keywords_the_channel_never_granted():
    """A lift takes back only what a CHANNEL tagged: a keyword the character holds
    for the encounter from another source is not swept up by the break."""
    st = _state([_card("grant", [{"kind": "grant_keyword", "keywords": ["vigilance"],
                                  "target": SELF, "duration": "encounter"}],
                       timing="sorcery"),
                 _card("aura", [dict(DEFENDER)])], hand=2)
    st = _do(st, "cast", card_id="grant")
    st = _do(st, "pass")
    assert st.character("p").keywords.get("vigilance") == "encounter"
    st = _next_turn(st)
    st = _hold(st, "aura")
    assert st.character("p").keywords.get("defender") == "while_channeled"
    st = _next_turn(st)
    st = _do(st, "drop_channels")
    kws = st.character("p").keywords
    assert kws.get("vigilance") == "encounter"     # untouched
    assert "defender" not in kws                   # the channel's own grant is gone


def test_the_walker_finds_tags_in_every_nested_position():
    """A unit check on the sweep itself: it must see a while_channeled tag wherever
    a card can legally put one, and must NOT re-report a plain top-level continuous
    tag (the continuous pass already lifts that one — reporting it twice would
    double-lift)."""
    from ltg_combat.engine import _nested_channel_effects
    from ltg_core.schema import Card

    card = Card.model_validate(_card("everything", [
        dict(MITIGATE_AGAIN),                                   # top-level continuous
        {"trigger": "channel_start", "kind": "conditional",
         "condition": {"kind": "caster_property", "property": "row", "row": "front"},
         "effects": [dict(DEFENDER)]},                          # under a trigger
        {"kind": "modal", "choose": 1, "modes": [
            {"label": "A", "effects": [{"kind": "grant_keyword", "keywords": ["flying"],
                                        "target": SELF, "duration": "while_channeled"}]},
            {"label": "B", "effects": [{"kind": "heal", "amount": 1, "target": SELF}]}]},
        {"kind": "stance", "defend": "unchanged", "mitigate": "unchanged",
         "move": "unchanged",
         "attack": {"name": "Guard", "effects": [
             {"kind": "modify_action", "action": "defend", "modifier": "defend_double",
              "amount": 0, "target": SELF, "duration": "while_channeled"}]}},
        {"kind": "heal", "amount": 2, "target": SELF, "trigger": "channel_start"},
    ]))
    found = _nested_channel_effects(card.effects)
    assert sorted(getattr(e, "modifier", None) or ",".join(e.keywords) for e in found) \
        == ["defend_double", "defender", "flying"]
    # The top-level continuous mitigate_again is left to the continuous pass.
    assert not any(getattr(e, "modifier", None) == "mitigate_again" for e in found)
