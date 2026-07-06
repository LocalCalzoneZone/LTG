"""The `channel_start` trigger (the ETB analogue on channeled cards): its
effects fire ONCE as the channel begins — distinct from `while_channeled`
statics (continuous) and `upkeep` ticks (recurring)."""

from __future__ import annotations

from ltg_core.schema import Card
from ltg_core.translation import render_effects
from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_deckbuilder import ingest


_WELCOME = {  # "When this enters, draw a card" — plus an upkeep tick to contrast.
    "id": "welcome", "name": "Welcome", "source_name": "Welcome", "rarity": "common",
    "level": 1, "type": "Enchantment", "timing": "channeled",
    "cost": {"generic": 0, "colors": {}},
    "effects": [
        {"kind": "heal", "amount": 2, "target": {"mode": "self"},
         "trigger": "channel_start"},
        {"kind": "heal", "amount": 1, "target": {"mode": "self"},
         "trigger": "upkeep"},
    ],
    "validated": True,
}


def _state():
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 2, "hand_size": 1,
                   "identity": ["U"], "row": "front", "attack_mode": "melee",
                   "library": [dict(_WELCOME)]}],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 30, "level": 1,
                     "intent": {"name": "Bash", "amount": 0, "action_type": "attack",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })


def _advance(st, until, budget=300):
    for _ in range(budget):
        if until(st):
            return st
        acts = legal_actions(st)
        if not acts:
            return st
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    return st


def test_channel_start_fires_once_at_cast_then_upkeep_ticks():
    st = _state()
    st.character("p").hp = 10
    # Cast the enchantment; settle the stack.
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast")
    st = apply_action(st, cast)[0]
    st = _advance(st, lambda s: not s.stack)
    assert st.character("p").hp == 12          # channel_start fired exactly once
    # Next turn's upkeep: only the upkeep tick fires (start does NOT repeat).
    st = _advance(st, lambda s: s.turn >= 2 and s.phase == "player")
    assert st.character("p").hp == 13


def test_channel_start_renders_distinctly():
    card = Card.model_validate(_WELCOME)
    text = render_effects(card.effects, channeled=True)
    assert "When this channel begins: restore 2 HP to yourself." in text
    assert "At the start of every turn while channeled: restore 1 HP" in text


def test_ingest_maps_etb_wording_to_channel_start():
    card = ingest.build_custom_card({
        "name": "Omen Gate", "type": "enchantment", "mana_cost": "1U",
        "effect": "When Omen Gate enters the battlefield, draw a card.",
    })
    assert card.effects, card
    assert all(e.trigger == "channel_start" for e in card.effects)


def test_ingest_landfall_still_wins_over_etb_rule():
    card = ingest.build_custom_card({
        "name": "Verdant Pulse", "type": "enchantment", "mana_cost": "G",
        "effect": "Whenever a land enters the battlefield under your control, draw a card.",
    })
    for e in card.effects:
        assert e.trigger == "capacity_increase"
