"""Event triggers on channeled cards: `{"event": ..., "who": ...}` triggers fire
whenever the watched combatant attacks, is dealt damage, gains life, casts a
spell (optionally of one type), or draws a card — scoped relative to the
channel's holder (you / target / ally / enemy / any)."""

from __future__ import annotations

import pytest

from ltg_core.schema import Card, EventTrigger
from ltg_core.translation import render_effects
from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _channel(cid, trigger, effect=None):
    """A free enchantment whose triggered effect heals the holder for 1."""
    eff = effect or {"kind": "heal", "amount": 1, "target": {"mode": "self"}}
    return {
        "id": cid, "name": cid, "source_name": cid, "rarity": "common",
        "level": 1, "type": "Enchantment", "timing": "channeled",
        "cost": {"generic": 0, "colors": {}},
        "effects": [{**eff, "trigger": trigger}],
        "validated": True,
    }


def _bolt(cid="bolt", timing="instant"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": timing.capitalize(), "timing": timing,
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "deal_damage", "amount": 1,
                         "target": {"mode": "chosen", "side": "enemy", "targeted": True}}],
            "validated": True}


def _state(cards, hp=20, enemy_damage=0, hand_size=None):
    """One hero (opening hand = top `hand_size` of `cards`, default all) vs one
    ogre. The ogre is passive by default (0-damage swings) so HP asserts stay
    deterministic."""
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": hp, "power": 2,
                   "hand_size": hand_size if hand_size is not None else len(cards),
                   "identity": ["U"], "row": "front",
                   "attack_mode": "melee", "library": cards}],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 30, "level": 1,
                     "intent": {"name": "Bash", "amount": enemy_damage,
                                "action_type": "attack", "intent_type": "attack",
                                "targeting": "lowest_hp_party", "mode": "melee"}}],
    })


def _settle(state):
    while state.stack:
        p = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if p is None:
            break
        state = apply_action(state, p)[0]
    return state


def _cast(state, card_id, target_id=None):
    for _ in range(200):
        acts = legal_actions(state)
        cast = next((a for a in acts if a.kind == "cast" and a.card_id == card_id), None)
        if cast is not None:
            if cast.target_id is None and target_id:
                cast.target_id = target_id
            return _settle(apply_action(state, cast)[0])
        nxt = (next((a for a in acts if a.kind == "pass"), None)
               or next((a for a in acts if a.kind == "end_turn"), None) or acts[0])
        state = apply_action(state, nxt)[0]
    raise AssertionError(f"never found cast for {card_id}")


def _attack(state, target_id="ogre"):
    for _ in range(200):
        acts = legal_actions(state)
        atk = next((a for a in acts if a.kind == "attack"), None)
        if atk is not None:
            atk.target_id = target_id
            return _settle(apply_action(state, atk)[0])
        nxt = (next((a for a in acts if a.kind == "pass"), None)
               or next((a for a in acts if a.kind == "end_turn"), None) or acts[0])
        state = apply_action(state, nxt)[0]
    raise AssertionError("never found attack action")


# --- schema ------------------------------------------------------------------ #
def test_event_trigger_validates_and_renders():
    card = Card.model_validate(_channel(
        "ward", {"event": "damage_taken", "who": "you"}))
    assert isinstance(card.effects[0].trigger, EventTrigger)
    text = render_effects(card.effects, channeled=True)
    assert "Whenever you are dealt damage while channeled" in text


def test_spell_type_only_on_spell_cast():
    with pytest.raises(Exception):
        Card.model_validate(_channel(
            "bad", {"event": "attack", "who": "you", "spell_type": "instant"}))


def test_render_covers_all_whos():
    for who, expect in [("you", "Whenever you attack"),
                        ("target", "Whenever the target attacks"),
                        ("ally", "Whenever an ally attacks"),
                        ("enemy", "Whenever an enemy attacks"),
                        ("any", "Whenever anyone attacks")]:
        card = Card.model_validate(_channel("c", {"event": "attack", "who": who}))
        assert expect in render_effects(card.effects, channeled=True)


def test_render_spell_cast_with_type():
    card = Card.model_validate(_channel(
        "c", {"event": "spell_cast", "who": "you", "spell_type": "instant"}))
    assert "Whenever you cast an instant" in render_effects(card.effects, channeled=True)


# --- engine: each event fires -------------------------------------------------- #
def test_on_you_attack_fires():
    st = _state([_channel("battlehymn", {"event": "attack", "who": "you"})], hp=20)
    st.character("p").hp = 15
    st = _cast(st, "battlehymn")
    before = st.character("p").hp
    st = _attack(st)
    assert st.character("p").hp == before + 1  # the on-attack heal landed


def test_on_enemy_damage_taken_fires():
    # Watch the ENEMY side: whenever an enemy is dealt damage, heal 1.
    st = _state([_channel("leech", {"event": "damage_taken", "who": "enemy"}),
                 _bolt()], hp=20)
    st.character("p").hp = 10
    st = _cast(st, "leech")
    st = _cast(st, "bolt", target_id="ogre")
    assert st.enemy("ogre").hp == 29
    assert st.character("p").hp == 11


def test_on_you_dealt_damage_fires():
    st = _state([_channel("thorns", {"event": "damage_taken", "who": "you"},
                          effect={"kind": "deal_damage", "amount": 1,
                                  "target": {"mode": "chosen", "side": "enemy",
                                             "targeted": True}})],
                hp=25, enemy_damage=2)  # the ogre must actually connect
    st = _cast(st, "thorns")
    # Let the enemy turn happen: its Bash hits P, the thorns trigger hits back.
    for _ in range(300):
        if st.enemy("ogre") is None or st.enemy("ogre").hp < 30 or st.turn >= 3:
            break
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    assert st.enemy("ogre").hp == 29


def test_on_spell_cast_with_type_filter():
    # Fires only on instants: the sorcery cast must not trigger it.
    st = _state([_channel("echo", {"event": "spell_cast", "who": "you",
                                   "spell_type": "instant"}),
                 _bolt("sorc", timing="sorcery"), _bolt("inst", timing="instant")],
                hp=20)
    st.character("p").hp = 10
    st = _cast(st, "echo")
    st = _cast(st, "sorc", target_id="ogre")
    assert st.character("p").hp == 10  # sorcery: no trigger
    st = _cast(st, "inst", target_id="ogre")
    assert st.character("p").hp == 11  # instant: fires


def test_on_card_draw_fires():
    # hand_size 1: insight starts in hand; two spares stay in the library — the
    # turn-1 upkeep draw takes one BEFORE the channel is up, the turn-2 draw
    # happens with the channel held and must fire the trigger.
    st = _state([_channel("insight", {"event": "card_draw", "who": "you"}),
                 _bolt("spare1"), _bolt("spare2")], hp=20, hand_size=1)
    st.character("p").hp = 10
    st = _cast(st, "insight")
    hp_before = st.character("p").hp
    # Advance into the next turn: the upkeep draw must fire the trigger.
    for _ in range(300):
        if st.turn >= 2 and st.phase == "player":
            break
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    assert st.character("p").hp > hp_before


def test_on_life_gain_fires_and_self_heal_loop_terminates():
    # 'Whenever you gain life, heal 1' triggers ITSELF — the event depth cap must
    # end the cascade instead of recursing forever.
    mend = {"id": "mend", "name": "mend", "source_name": "mend", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "heal", "amount": 3, "target": {"mode": "self"}}],
            "validated": True}
    st = _state([_channel("loop", {"event": "life_gain", "who": "you"}), mend], hp=20)
    st.character("p").hp = 5
    st = _cast(st, "loop")
    st = _cast(st, "mend")
    hp = st.character("p").hp
    assert hp > 5 + 3          # the trigger fired at least once on top of the heal
    assert hp <= 20            # and the cascade terminated (capped, never past max)


def test_who_you_does_not_fire_for_enemy_events():
    st = _state([_channel("selfish", {"event": "damage_taken", "who": "you"}),
                 _bolt()], hp=20)
    st.character("p").hp = 10
    st = _cast(st, "selfish")
    st = _cast(st, "bolt", target_id="ogre")  # damages the ENEMY, not you
    assert st.character("p").hp == 10  # must not fire
