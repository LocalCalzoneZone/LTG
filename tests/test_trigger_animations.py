"""Per-trigger panel animations (Update 16 amendment, 2026-09).

A card's triggered effects used to play nothing: the panel had one clip for
the whole card, fired when the card itself resolved. A channeled card whose
retaliation is its whole point ("whenever you are dealt damage, deal damage
equal to your charge counters") therefore looked identical to the quiet turn
it was cast on. A card may now wire a clip PER TRIGGER — the same trigger key
the engine names when the trigger fires, so the client can pick it up.

The chain pinned here: `trigger_key` (one name for a trigger, shared by
everything) → `Card.trigger_animations` → the panel bundle the client is
handed → the engine naming the trigger on the stack item and in the log the
picker reads.
"""

from __future__ import annotations

import copy

import pytest

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import Card, EventTrigger, trigger_key, trigger_key_label
from ltg_game_server import content

from tests.test_break_channel import RETALIATOR, _filler


# --------------------------------------------------------------------------- #
# The key, and how it reads
# --------------------------------------------------------------------------- #
def test_one_trigger_has_one_name_whatever_shape_it_arrives_in():
    assert trigger_key("channel_start") == "channel_start"
    assert trigger_key("channel_break") == "channel_break"
    assert trigger_key(EventTrigger(event="damage_taken", who="you")) == "damage_taken:you"
    assert trigger_key({"event": "attack", "who": "enemy"}) == "attack:enemy"
    assert trigger_key({"event": "attack"}) == "attack:you"          # `who` defaults
    assert trigger_key({"after_turns": 3}) == "after_turns"
    assert trigger_key(None) == ""


def test_a_trigger_key_reads_as_english_for_the_picker():
    assert trigger_key_label("channel_start") == "When this channel begins"
    assert trigger_key_label("channel_break") == "When this channel ends"
    # The subject decides the verb form — "you ARE dealt damage", "an ally IS".
    assert trigger_key_label("damage_taken:you") == "Whenever you are dealt damage"
    assert trigger_key_label("damage_taken:ally") == "Whenever an ally is dealt damage"
    assert trigger_key_label("death:enemy") == "Whenever an enemy falls"
    assert trigger_key_label("") == "(no trigger)"


# --------------------------------------------------------------------------- #
# The card field and the bundle handed to the client
# --------------------------------------------------------------------------- #
def _card(**kw):
    base = {"id": "glint", "name": "Glintblades", "rarity": "uncommon", "level": 2,
            "type": "Enchantment", "timing": "channeled",
            "cost": {"generic": 0, "colors": {}},
            "effects": [{"trigger": "channel_start", "kind": "charge", "op": "add",
                         "amount": 3, "target": {"mode": "self"}},
                        {"trigger": {"event": "damage_taken", "who": "you"},
                         "kind": "deal_damage", "amount": {"ref": "caster_charge"},
                         "target": {"mode": "chosen", "side": "any", "targeted": True}}],
            "validated": True}
    base.update(kw)
    return base


def _loadout(cards, anims=("a_cast", "a_retaliate")):
    return {"ltg_version": "0.1",
            "character": {"name": "Lasarre", "colors": ["U"], "starting_mana": ["U"],
                          "animations": [{"id": a, "title": a, "file": f"/anim/{a}.webm",
                                          "trigger": "cast"} for a in anims]},
            "cards": cards}


def test_the_card_carries_a_clip_per_trigger_and_defaults_to_none():
    card = Card.model_validate(_card(trigger_animations={"damage_taken:you": "a_retaliate"}))
    assert card.trigger_animations == {"damage_taken:you": "a_retaliate"}
    assert Card.model_validate(_card()).trigger_animations == {}      # nothing by default


def test_the_bundle_carries_the_per_trigger_picks_to_the_client():
    bundle = content.panel_anim_bundle(_loadout([
        _card(animation="a_cast", trigger_animations={"damage_taken:you": "a_retaliate",
                                                      "channel_start": "a_cast"})]))
    assert bundle["cards"] == {"glint": "a_cast"}
    assert bundle["triggers"] == {"glint": {"damage_taken:you": "a_retaliate",
                                            "channel_start": "a_cast"}}
    # A pick naming a clip the character no longer has is dropped, exactly as
    # the per-card pick is — the trigger falls back to playing nothing.
    stale = content.panel_anim_bundle(_loadout([
        _card(trigger_animations={"damage_taken:you": "deleted_clip"})]))
    assert stale["triggers"] == {}
    # A loadout with no clips at all still hands over the empty shape.
    assert content.panel_anim_bundle(_loadout([_card()], anims=()))["triggers"] == {}


# --------------------------------------------------------------------------- #
# The engine names the trigger, so the picker can find its clip
# --------------------------------------------------------------------------- #
def test_the_engine_names_which_trigger_fired_on_the_stack_and_in_the_log():
    st = state_from_dict({
        "party": [{"id": "p", "name": "p", "hp": 30, "power": 2, "hand_size": 1,
                   "identity": ["U"], "row": "front", "attack_mode": "melee",
                   "capacity": 4,
                   "library": [copy.deepcopy(RETALIATOR), _filler("x1"), _filler("x2")]}],
        "enemies": [{"id": "ogre", "name": "ogre", "hp": 40, "level": 3, "power": 12,
                     "row": "front", "components": [],
                     "intent": {"name": "Hit", "amount": 12, "action_type": "attack",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}]})
    st.party[0].pool = ["U", "U", "U", "U"]
    st = apply_action(st, next(a for a in legal_actions(st)
                               if a.kind == "cast" and a.card_id == "glint"))[0]
    st = _settle(st)
    for _ in range(400):
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "choose_target"), None)
             or next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
        if st.party[0].hp < 30:
            st = _settle(st)
            break
    fired = {(e.data.get("card"), e.data.get("trigger"))
             for e in st.log if e.type in ("channel_trigger", "channel_break_trigger")}
    assert ("glint", "damage_taken:you") in fired
    assert ("glint", "channel_break") in fired
    # …and the RESOLVE entry the panel picker reads carries it too, so the clip
    # plays as the ability lands rather than when it goes on the stack.
    resolved = {(e.data.get("card"), e.data.get("trigger"))
                for e in st.log if e.type == "resolve" and e.data.get("kind") == "triggered"}
    assert ("glint", "damage_taken:you") in resolved
    # An ordinary cast is not a trigger and names none.
    assert all(not e.data.get("trigger") for e in st.log
               if e.type == "resolve" and e.data.get("kind") == "spell")


def _settle(st):
    for _ in range(300):
        acts = legal_actions(st)
        a = (next((x for x in acts if x.kind == "choose_target"), None)
             or next((x for x in acts if x.kind == "choose_mode"), None)
             or next((x for x in acts if x.kind == "pass"), None))
        if a is None:
            return st
        st = apply_action(st, a)[0]
    return st
