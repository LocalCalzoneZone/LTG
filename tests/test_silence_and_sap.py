"""The two lockdown shapes added alongside forced discard:

SILENCE (`prevent cast`) — an ACTION shield, the twin of Pacifism's `prevent
attack`. It binds the tongue: no cards may be cast. It deliberately spares the
basic attack, the Skill/Ultimate (activated abilities, not spells) and carried
consumables, so a silenced character still has a turn to play — and it binds
ENEMY spell-classed components too, so silencing a caster actually silences it.

SAP (`sap`) — a temporary mana-capacity debuff, the mana-side twin of `wound`.
It rides its own `capacity_mod` layer with `this_turn` / `encounter` durations,
so it expires through the same End-step reset the stat layers use.
"""

from __future__ import annotations

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _card(cid, effects, timing="instant", cost=0, consumable=False):
    out = {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
           "level": 1, "type": "Instant", "timing": timing,
           "cost": {"generic": cost, "colors": {}}, "effects": effects}
    if consumable:
        out["consumable_id"] = cid
        out["type"] = "Item"
    return out


def _bolt(cid="bolt", amount=3):
    return _card(cid, [{"kind": "deal_damage", "amount": amount,
                        "target": {"mode": "chosen", "side": "enemy",
                                   "targeted": True}}])


def _potion(cid="potion"):
    return _card(cid, [{"kind": "heal", "amount": 2,
                        "target": {"mode": "self"}}], consumable=True)


def _char(cid, row="front", power=2, hp=30, library=None, hand=1):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": ["U"], "row": row, "attack_mode": "melee",
            "library": library or [_bolt(cid + "_a"), _bolt(cid + "_b")]}


def _enemy(eid="e", hp=30, components=None):
    return {"id": eid, "name": eid, "hp": hp, "level": 2, "power": 2,
            "attack_mode": "melee",
            "intent": {"name": "Bash", "amount": 2, "action_type": "attack",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"},
            "components": components or []}


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


def _kinds(st, kind):
    return [a for a in legal_actions(st) if a.kind == kind]


def _silence(st, cid, uses="all"):
    """Drop a Silence shield straight onto a character (the effect under test is
    the shield's behaviour, not the card that delivers it)."""
    from ltg_combat.state import PreventTag
    st.character(cid).prevent_tags.append(PreventTag("cast", None if uses == "all" else 1))
    return st


# --------------------------------------------------------------------------- #
# Silence: what it stops
# --------------------------------------------------------------------------- #
def test_silence_stops_casting():
    st = _state([_char("p", library=[_bolt("bolt"), _bolt("bolt2")], hand=2)],
                [_enemy()])
    assert _kinds(st, "cast"), "sanity: the bolt is castable before the silence"
    st = _silence(st, "p")
    assert _kinds(st, "cast") == []


def test_silence_spares_the_sword():
    """Pacifism binds the sword, Silence binds the tongue — they are separate
    shields and neither does the other's job."""
    st = _state([_char("p", library=[_bolt("bolt"), _bolt("bolt2")], hand=2)],
                [_enemy()])
    st = _silence(st, "p")
    assert _kinds(st, "attack"), "a silenced character can still swing"


def test_silence_spares_a_consumable():
    """The deliberate out: drinking a potion is not speech. It keeps a silenced
    character from simply losing the turn, and makes items a real answer."""
    st = _state([_char("p", library=[_potion("potion"), _bolt("bolt")], hand=2)],
                [_enemy()])
    st = _silence(st, "p")
    casts = _kinds(st, "cast")
    assert [a.card_id for a in casts] == ["potion"]


def test_silence_does_not_blunt_damage():
    """An ACTION shield is not a damage shield: `prevent cast` must not show up
    in the prevention lanes (that is what `_ACTION_PREVENT` guards)."""
    from ltg_combat.engine import _prevent_match
    for kind in ("attack", "ability", "activated", "spell", "triggered"):
        assert not _prevent_match("cast", kind)


def test_silence_does_not_drop_a_held_channel():
    """Silence stops you STARTING something, not holding what you already have."""
    channel = _card("hold", [{"kind": "pump", "power": 1, "toughness": 0,
                              "target": {"mode": "self"},
                              "duration": "while_channeled"}],
                    timing="channeled")
    st = _state([_char("p", library=[channel, _bolt("b")], hand=2)], [_enemy()])
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "hold")
    st = apply_action(st, cast)[0]
    while st.stack:
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    assert st.character("p").channels, "sanity: the channel is held"
    st = _silence(st, "p")
    assert st.character("p").channels                     # still held


# --------------------------------------------------------------------------- #
# Silence on the enemy side
# --------------------------------------------------------------------------- #
def _caster(eid="mage"):
    """A caster whose Fireball is spell-classed and whose fallback is a swing."""
    return _enemy(eid, components=[{
        "id": "fireball", "archetype": "Burst", "timing": "proactive",
        "priority": 10, "target_rule": "valuation", "action_type": "spell",
        "telegraph": "Fireball — deal 5",
        "verbs": [{"kind": "deal_damage", "amount": 5,
                   "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}])


def _silence_enemy(st, eid):
    from ltg_combat.state import PreventTag
    st.enemy(eid).prevent_tags.append(PreventTag("cast", None))
    return st


def _to_enemy_declaration(st):
    """Advance to just after the enemy declares its intent for the round."""
    while st.enemies[0].intent is None and st.result is None:
        acts = legal_actions(st)
        a = next((x for x in acts if x.kind == "end_turn"), None) or acts[0]
        st = apply_action(st, a)[0]
    return st


def test_a_silenced_enemy_cannot_run_its_spell_component():
    """The point of enemy silence: a spell-classed COMPONENT *is* the enemy's
    spell. Before this, silencing a caster did nothing, because its Fireball was
    a 'component' rather than a 'spell'."""
    from ltg_combat.engine import _component_eligible
    st = _state([_char("p", hp=20)], [_caster()])
    enemy, comp = st.enemies[0], st.enemies[0].components[0]
    assert _component_eligible(st, enemy, comp)         # sanity: it casts freely
    st = _silence_enemy(st, "mage")
    assert not _component_eligible(st, enemy, comp)     # …and not while silenced


def test_a_channelled_silence_keeps_a_caster_quiet_across_turns():
    """The realistic shape. A `prevent` shield is wiped every End step by design,
    so lasting silence comes from a CHANNEL re-asserting it each turn — the same
    way a channelled Pacifism holds a creature's sword."""
    hush = _card("hush", [{"kind": "prevent", "parameter": "cast",
                           "target": {"mode": "chosen", "side": "enemy",
                                      "targeted": True},
                           "duration": "while_channeled"}], timing="channeled")
    st = _state([_char("p", hp=20, library=[hush, _bolt("b")], hand=2)], [_caster()])
    cast = next(a for a in legal_actions(st)
                if a.kind == "cast" and a.card_id == "hush")
    st = apply_action(st, cast)[0]
    while st.stack:
        st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))[0]
    st = _to_enemy_declaration(st)
    intent = st.enemies[0].intent
    assert intent is not None                       # it still acts…
    assert intent.action_type != "spell"            # …but not with its spell
    assert "Fireball" not in intent.name


def test_an_unsilenced_caster_does_declare_its_spell():
    """The control for the test above — without the hush, Fireball is what it picks."""
    st = _to_enemy_declaration(_state([_char("p", hp=20)], [_caster()]))
    assert st.enemies[0].intent.action_type == "spell"
    assert "Fireball" in st.enemies[0].intent.name


def test_pacifying_a_caster_leaves_the_spell_standing():
    """The mirror, and the reason the intent-cancel had to become parameter-aware:
    a shield only cancels the intents IT forbids."""
    from ltg_combat.engine import _intent_blocked_by
    from ltg_combat.state import Intent

    spell = Intent(name="Fireball", action_type="spell", effects=[], target_id="p")
    swing = Intent(name="Claw", action_type="attack", effects=[], target_id="p")
    assert _intent_blocked_by(spell, "cast") and not _intent_blocked_by(spell, "attack")
    assert _intent_blocked_by(swing, "attack") and not _intent_blocked_by(swing, "cast")


# --------------------------------------------------------------------------- #
# Sap: mana capacity as a target
# --------------------------------------------------------------------------- #
def _sap(amount=2, duration="this_turn", side="ally"):
    return {"kind": "sap", "amount": amount, "duration": duration,
            "target": {"mode": "chosen", "side": side, "targeted": True}}


def _sapper(eid="wraith", amount=2, duration="encounter"):
    """`once_per_encounter` so the debuff lands exactly once — otherwise the rule
    re-fires every turn and the totals under test stack."""
    return _enemy(eid, components=[{
        "id": "sap", "archetype": "Debilitate", "timing": "proactive",
        "priority": 10, "target_rule": "valuation", "once_per_encounter": True,
        "telegraph": "Mana Blight — capacity −2",
        "verbs": [_sap(amount, duration)]}])


def _advance_turns(st, n):
    turn = st.turn
    while st.result is None and st.turn < turn + n:
        acts = legal_actions(st)
        if not acts:
            break
        a = next((x for x in acts if x.kind in ("pass", "end_turn")), acts[0])
        st = apply_action(st, a)[0]
    return st


def test_sap_lowers_capacity_and_the_refreshed_pool():
    st = _state([_char("p", hp=30)], [_sapper(amount=2)])
    st = _advance_turns(st, 2)
    p = st.character("p")
    assert p.capacity_mod == -2
    assert p.capacity == max(0, len(p.mana_colors) - 2)
    assert len(p.pool) <= p.capacity        # the refresh honours the sap


def test_sap_never_drives_capacity_below_zero():
    st = _state([_char("p", hp=30)], [_sapper(amount=99)])
    st = _advance_turns(st, 2)
    assert st.character("p").capacity == 0
    assert st.character("p").pool == []


@pytest.mark.parametrize("duration,after_end", [("this_turn", 0), ("encounter", -2)])
def test_sap_duration_rides_the_same_layer_reset_as_a_wound(duration, after_end):
    """Unit-level, because the layer reset IS the mechanism: a `this_turn` sap
    falls back to the encounter share (0) at End, an `encounter` one is the
    encounter share and survives. Exactly how `wound` behaves."""
    from ltg_combat.engine import _r_sap, _reset_temp_layers
    from ltg_core.schema import Sap, t_chosen

    st = _state([_char("p", hp=30)], [_enemy()])
    p = st.character("p")
    _r_sap(st, None, Sap(amount=2, duration=duration,
                         target=t_chosen("ally", targeted=True)), p, {})
    assert p.capacity_mod == -2
    _reset_temp_layers(p)
    assert p.capacity_mod == after_end


def test_an_encounter_sap_is_still_biting_a_turn_later():
    """The end-to-end version: an enemy's encounter sap outlives the End step.
    (An enemy `this_turn` sap would be near-worthless — the enemy acts last, so
    the End step lifts it almost immediately. Enemy saps want `encounter`.)"""
    st = _state([_char("p", hp=30)], [_sapper(amount=2, duration="encounter")])
    st = _advance_turns(st, 2)
    assert st.character("p").capacity_mod == -2
    st = _advance_turns(st, 1)
    assert st.character("p").capacity_mod == -2     # once_per_encounter: no stacking


def test_sap_is_rendered_in_card_text():
    from ltg_core.translation import render_effects
    from ltg_core.schema import Sap, t_chosen
    text = render_effects([Sap(amount=2, target=t_chosen("ally", targeted=True))])
    assert "capacity" in text.lower() and "2" in text


def test_a_card_cannot_sap_an_enemy():
    """Enemies run no mana engine, so this would ship as a dead card. Caught at
    authoring, the same way `draw` on an enemy is."""
    from ltg_core.schema import Card

    with pytest.raises(ValueError, match="mana capacity"):
        Card.model_validate(_card("drain_mana", [
            {"kind": "sap", "amount": 1,
             "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]))


def test_sap_reaches_the_authoring_dropdown():
    """The deckbuilder derives its editor from the schema, so a new primitive
    surfaces with no frontend change — this pins that contract."""
    from ltg_core.schema import effect_specs
    assert "sap" in effect_specs()


# --------------------------------------------------------------------------- #
# Forced discard (already a primitive — pinned so it stays enemy-legal)
# --------------------------------------------------------------------------- #
def test_an_enemy_can_force_a_hero_to_discard():
    discard = _enemy("thief", components=[{
        "id": "cutpurse", "archetype": "Debilitate", "timing": "proactive",
        "priority": 10, "target_rule": "valuation",
        "telegraph": "Cutpurse — a hero discards a card",
        "verbs": [{"kind": "move_card", "count": 1, "source": "hand",
                   "destination": "graveyard",
                   "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}])
    st = _state([_char("p", hp=30, library=[_bolt("a"), _bolt("b"), _bolt("c")],
                       hand=2)], [discard])
    st = _advance_turns(st, 2)
    # Either the pick is pending (more candidates than it takes) or a card moved.
    moved = st.pending_choice is not None or st.character("p").graveyard
    assert moved, "the discard must actually reach the hero's hand"
