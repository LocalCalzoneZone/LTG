"""{X} casting costs and the `x` / `casting_cost` value references: the engine
offers one cast per affordable X, pays base + X, and resolution (including a
held channel's triggers) reads the chosen X back through refs. Also: a
conditional may carry its own trigger on a channeled card ("when … if …")."""

from __future__ import annotations

from ltg_core.schema import Card
from ltg_core.translation import render_effects
from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


_FIREBALL = {  # {X}{R}: deal X damage to target enemy.
    "id": "fireball", "name": "Fireball", "source_name": "Fireball",
    "rarity": "common", "level": 1, "type": "Sorcery", "timing": "sorcery",
    "cost": {"generic": 0, "colors": {"R": 1}, "x": True},
    "effects": [{"kind": "deal_damage", "amount": {"ref": "x"},
                 "target": {"mode": "chosen", "side": "enemy", "targeted": True}}],
    "validated": True,
}


def _state(cards, capacity=3):
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 2,
                   "hand_size": len(cards), "identity": ["R"] * capacity,
                   "row": "front", "attack_mode": "melee", "library": cards}],
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


def _settle(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def test_engine_enumerates_x_and_deals_x_damage():
    st = _state([dict(_FIREBALL)], capacity=3)
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    casts = [a for a in legal_actions(st) if a.kind == "cast"]
    # Pool is 3 R; base cost is {R}: X may be 0, 1, or 2 — one action each.
    assert sorted(a.x for a in casts) == [0, 1, 2]
    assert all("(X=" in a.label for a in casts)
    x2 = next(a for a in casts if a.x == 2)
    st = _settle(apply_action(st, x2)[0])
    assert st.enemy("ogre").hp == 28          # dealt X = 2
    assert st.character("p").pool == []        # paid {R} + 2 generic — all 3


def test_casting_cost_ref_includes_x():
    card = dict(_FIREBALL, id="drain", name="Drain", source_name="Drain",
                effects=[{"kind": "heal", "amount": {"ref": "casting_cost"},
                          "target": {"mode": "self"}}])
    st = _state([card], capacity=3)
    st.character("p").hp = 10
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    x2 = next(a for a in legal_actions(st) if a.kind == "cast" and a.x == 2)
    st = _settle(apply_action(st, x2)[0])
    assert st.character("p").hp == 13          # casting cost = 1 pip + X(2) = 3


def test_channel_trigger_reads_x():
    # A channeled {X} card whose upkeep tick heals X.
    card = {
        "id": "wellspring", "name": "Wellspring", "source_name": "Wellspring",
        "rarity": "common", "level": 0, "type": "Enchantment", "timing": "channeled",
        "cost": {"generic": 0, "colors": {}, "x": True},
        "effects": [{"kind": "heal", "amount": {"ref": "x"},
                     "target": {"mode": "self"}, "trigger": "upkeep"}],
        "validated": True,
    }
    st = _state([card], capacity=2)
    st.character("p").hp = 10
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    x2 = next(a for a in legal_actions(st) if a.kind == "cast" and a.x == 2)
    st = _settle(apply_action(st, x2)[0])
    st = _advance(st, lambda s: s.turn >= 2 and s.phase == "player")
    assert st.character("p").hp == 12          # the turn-2 upkeep tick healed X=2


def test_conditional_with_trigger_on_channeled_card():
    # "At the start of every turn while channeled: if your HP is 50% or less, heal 2."
    card = {
        "id": "vigil", "name": "Vigil", "source_name": "Vigil",
        "rarity": "common", "level": 0, "type": "Enchantment", "timing": "channeled",
        "cost": {"generic": 0, "colors": {}},
        "effects": [{"kind": "conditional", "trigger": "upkeep",
                     "condition": {"kind": "self_hp", "percent": 50, "compare": "or_less"},
                     "effects": [{"kind": "heal", "amount": 2, "target": {"mode": "self"}}]}],
        "validated": True,
    }
    parsed = Card.model_validate(card)
    text = render_effects(parsed.effects, channeled=True)
    assert "At the start of every turn while channeled: if your HP is 50%" in text

    st = _state([dict(card)], capacity=2)
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast")
    st = _settle(apply_action(st, cast)[0])
    st.character("p").hp = 20                  # full HP: turn-2 tick must skip
    st = _advance(st, lambda s: s.turn >= 2 and s.phase == "player")
    assert st.character("p").hp == 20
    st.character("p").hp = 8                   # wounded below half: turn-3 tick fires
    st = _advance(st, lambda s: s.turn >= 3 and s.phase == "player")
    assert st.character("p").hp == 10


def test_render_x_amounts():
    parsed = Card.model_validate(_FIREBALL)
    assert "Deal X damage" in render_effects(parsed.effects)


# --- StatValue: pump/wound/counters accept refs (pump X, per-player anthems) --- #
_SURGE = {  # {X}{R}: you get +X/+X until end of turn.
    "id": "surge", "name": "Surge of Might", "source_name": "Surge of Might",
    "rarity": "common", "level": 1, "type": "Sorcery", "timing": "sorcery",
    "cost": {"generic": 0, "colors": {"R": 1}, "x": True},
    "effects": [{"kind": "pump", "power": {"ref": "x"}, "toughness": {"ref": "x"},
                 "target": {"mode": "self"}}],
    "validated": True,
}


def test_pump_x_spell_buffs_by_the_chosen_x():
    st = _state([dict(_SURGE)], capacity=3)
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    x2 = next(a for a in legal_actions(st) if a.kind == "cast" and a.x == 2)
    st = _settle(apply_action(st, x2)[0])
    p = st.character("p")
    assert p.power_bonus == 2 and p.temp_mod == 2      # +X/+X with X = 2


def test_pump_x_renders_and_rejects_all():
    card = Card.model_validate(_SURGE)
    text = render_effects(card.effects, card.targets)
    assert "+X attack" in text and "+X temp HP" in text
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):  # "all" is not a stat value
        Card.model_validate({**_SURGE, "effects": [
            {"kind": "pump", "power": "all", "toughness": 1, "target": {"mode": "self"}}]})


# --- the party_size reference -------------------------------------------------- #
def _two_party_state(cards):
    return state_from_dict({
        "party": [
            {"id": "p", "name": "P", "hp": 20, "power": 2, "hand_size": len(cards),
             "identity": ["R", "R", "R"], "row": "front", "attack_mode": "melee",
             "library": cards},
            {"id": "q", "name": "Q", "hp": 20, "power": 2, "hand_size": 0,
             "identity": ["W"], "row": "mid", "attack_mode": "ranged", "library": []},
        ],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 30, "level": 1,
                     "intent": {"name": "Bash", "amount": 0, "action_type": "attack",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })


def test_party_size_ref_scales_with_the_party():
    rally = {  # "You get +1 attack for each party member" — power = party_size.
        "id": "rally", "name": "Rally", "source_name": "Rally",
        "rarity": "common", "level": 1, "type": "Sorcery", "timing": "sorcery",
        "cost": {"generic": 0, "colors": {"R": 1}},
        "effects": [{"kind": "pump", "power": {"ref": "party_size"}, "toughness": 0,
                     "target": {"mode": "self"}},
                    {"kind": "deal_damage", "amount": {"ref": "party_size"},
                     "target": {"mode": "chosen", "side": "enemy", "targeted": True}}],
        "validated": True,
    }
    st = _two_party_state([rally])
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast")
    st = _settle(apply_action(st, cast)[0])
    p = st.character("p")
    assert p.power_bonus == 2                          # two players → +2
    assert st.enemy("ogre").hp == 28                   # and 2 damage
    text = render_effects(Card.model_validate(rally).effects, {})
    assert "the party size" in text


# --- live-stat refs: caster_power / caster_hp / target_power / target_hp ------- #
def _simple(cid, effects):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
            "effects": effects, "validated": True}


def _cast_and_settle(st, cid):
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == cid)
    return _settle(apply_action(st, cast)[0])


def test_caster_power_ref_deals_your_power():
    st = _state([_simple("strike", [{"kind": "deal_damage", "amount": {"ref": "caster_power"},
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])])
    st = _cast_and_settle(st, "strike")
    assert st.enemy("ogre").hp == 28            # P's Power is 2


def test_target_hp_ref_is_an_exact_kill():
    # "deal damage equal to its current HP" — resolves per target, exact lethal.
    st = _state([_simple("cull", [{"kind": "deal_damage", "amount": {"ref": "target_hp"},
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])])
    st = _cast_and_settle(st, "cull")
    assert st.enemy("ogre") is None and st.result == "victory"


def test_target_power_ref_pump_doubles_your_power():
    # pump power = target's Power on yourself — Power doubles at resolution.
    st = _state([_simple("mirror", [{"kind": "pump", "power": {"ref": "target_power"},
        "toughness": 0, "target": {"mode": "self"}}])])
    st = _cast_and_settle(st, "mirror")
    p = st.character("p")
    assert p.power_bonus == 2 and p.current_power == 4


def test_caster_hp_ref_and_render_labels():
    st = _state([_simple("lifeburst", [{"kind": "deal_damage", "amount": {"ref": "caster_hp"},
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])])
    st = _cast_and_settle(st, "lifeburst")
    assert st.enemy("ogre").hp == 10            # P's HP is 20 → 30 − 20
    # Display: refs read as prose, not raw objects.
    card = Card.model_validate(_simple("x", [
        {"kind": "deal_damage", "amount": {"ref": "caster_power"},
         "target": {"mode": "chosen", "side": "enemy", "targeted": True}},
        {"kind": "pump", "power": {"ref": "target_power"}, "toughness": 0,
         "target": {"mode": "self"}}]))
    text = render_effects(card.effects, card.targets)
    assert "your Power" in text and "its Power" in text


def test_x_cost_shows_in_pips_and_actions():
    # The {X} pip must reach the client: in the card's cost string and as the
    # `x` field on each per-X cast action (the UI's picker is built from both).
    from ltg_combat.serialize import cost_pips, serialize_actions
    card = Card.model_validate(_FIREBALL)
    assert cost_pips(card) == "{X}{R}"
    st = _state([dict(_FIREBALL)], capacity=3)
    st = _advance(st, lambda s: any(a.kind == "cast" for a in legal_actions(s)))
    acts = legal_actions(st)
    payload = serialize_actions(st, acts)
    xs = sorted(e["x"] for e in payload if e["kind"] == "cast")
    assert xs == [0, 1, 2]
