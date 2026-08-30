"""§D22 — charge-counter references, the channel_drop verb, and the
after_turns countdown trigger.

- §D22-1: charge counters are readable via the `caster_charge` /
  `target_charge` value references (grantable before, now usable), and the
  reference registry is grouped for the editor dropdown.
- §D22-3: `channel_drop` — an enchantment-only, always-triggered verb that
  ends ITS OWN channel (never a sibling's).
- §D22-4: the `after_turns` trigger — an authorable N that counts down each
  Upkeep and fires the effect once when it expires.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from ltg_combat.engine import _value, apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import (REF_GROUPS, REF_VALUES, Card, Ref, effect_specs)
from ltg_core.translation import render_effects


def _filler(cid):
    return {"id": cid, "name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _hero(library, identity=("U",), hand=1):
    return {"id": "p", "name": "p", "hp": 30, "power": 2, "hand_size": hand,
            "identity": list(identity), "row": "front", "attack_mode": "melee",
            "library": library}


def _enemy(eid="ogre", hp=30, components=None):
    return {"id": eid, "name": eid, "hp": hp, "level": 3, "power": 2, "row": "front",
            "components": components or [],
            "intent": {"name": "Hit", "amount": 0, "action_type": "attack",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _drive(st, until, budget=400):
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


def _cast_and_hold(st, card_id):
    """Drive until the hero holds `card_id` as a channel."""
    def step(s):
        return any(ch.card.id == card_id for ch in s.character("p").channels)
    for _ in range(300):
        if step(st):
            return st
        acts = legal_actions(st)
        if not acts:
            return st
        a = (next((x for x in acts if x.kind == "cast" and x.card_id == card_id), None)
             or next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    return st


# --------------------------------------------------------------------------- #
# §D22-1 — charge counter references
# --------------------------------------------------------------------------- #
def test_charge_refs_are_registered_and_grouped():
    assert "caster_charge" in REF_VALUES and "target_charge" in REF_VALUES
    # Every non-shortcut ref appears in exactly one dropdown group.
    grouped = [n for _, names in REF_GROUPS for n in names]
    assert sorted(grouped) == sorted(set(grouped))          # no duplicates
    assert set(grouped) == set(REF_VALUES) - {"mana_capacity"}


def test_charge_refs_resolve_from_the_combatants():
    class Holder:
        charge = 4
    assert _value(Ref(ref="target_charge"), {"target_obj": Holder()}) == 4
    assert _value(Ref(ref="caster_charge"), {"caster_obj": Holder()}) == 4
    # A hero has no charge field — the read degrades to 0, never raises.
    class Hero:
        pass
    assert _value(Ref(ref="caster_charge"), {"caster_obj": Hero()}) == 0
    assert _value(Ref(ref="target_charge"), {"target_obj": None}) == 0


def test_charge_refs_render_and_reach_the_editor():
    card = Card.model_validate({
        "id": "surge", "name": "Surge", "rarity": "common", "level": 1,
        "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
        "effects": [{"kind": "deal_damage", "amount": {"ref": "target_charge"},
                     "target": {"mode": "chosen", "side": "enemy", "targeted": True}}]})
    assert "charge counters" in render_effects(card.effects)


def test_charge_reads_a_live_enemy_gauge():
    from ltg_combat.engine import _new_ctx, _resolve_effect_list
    from ltg_combat.state import StackItem
    from ltg_core.schema import DealDamage
    st = state_from_dict({"party": [_hero([_filler("x")])], "enemies": [_enemy()]})
    e = st.enemies[0]
    e.charge = 3
    eff = DealDamage.model_validate({"kind": "deal_damage",
                                     "amount": {"ref": "target_charge"},
                                     "target": {"mode": "chosen", "side": "enemy",
                                                "targeted": False}})
    item = StackItem(kind="spell", source_id="p", source_side="party",
                     label="Surge", effects=[eff], target_id=e.id)
    _resolve_effect_list(st, item, [eff], _new_ctx(st, item))
    assert e.hp == 27                          # dealt damage equal to its charge


# --------------------------------------------------------------------------- #
# §D22-1 — charge opened to players: add / remove N / remove all
# --------------------------------------------------------------------------- #
def _resolve_on(st, effects, source_id="p", side="party", target_id=None):
    from ltg_combat.engine import _new_ctx, _resolve_effect_list
    from ltg_combat.state import StackItem
    item = StackItem(kind="spell", source_id=source_id, source_side=side,
                     label="t", effects=effects, target_id=target_id)
    _resolve_effect_list(st, item, effects, _new_ctx(st, item))


def test_charge_is_authorable_on_player_cards_now():
    card = Card.model_validate({
        "id": "windup", "name": "Windup", "rarity": "common", "level": 1,
        "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
        "effects": [{"kind": "charge", "amount": 2}]})          # default: add, self
    assert card.effects[0].op == "add"
    assert "Add 2 charge counter(s)" in render_effects(card.effects)
    with pytest.raises(ValidationError):                        # "all" needs remove
        Card.model_validate({
            "id": "bad", "name": "Bad", "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "charge", "amount": "all"}]})
    # Legacy enemy shape (bare amount, no op/target) still validates.
    from ltg_core.schema import Charge
    legacy = Charge.model_validate({"kind": "charge", "amount": 1})
    assert legacy.op == "add" and legacy.target.mode.value == "self"


def test_a_hero_builds_spends_and_empties_charge():
    from ltg_core.schema import Charge
    st = state_from_dict({"party": [_hero([_filler("x")])], "enemies": [_enemy()]})
    p = st.character("p")
    _resolve_on(st, [Charge.model_validate({"kind": "charge", "amount": 2})])
    assert p.charge == 2
    _resolve_on(st, [Charge.model_validate({"kind": "charge", "op": "remove", "amount": 1})])
    assert p.charge == 1
    assert _value(Ref(ref="caster_charge"), {"caster_obj": p}) == 1
    _resolve_on(st, [Charge.model_validate({"kind": "charge", "op": "remove", "amount": "all"})])
    assert p.charge == 0
    _resolve_on(st, [Charge.model_validate({"kind": "charge", "op": "remove", "amount": 5})])
    assert p.charge == 0                                        # never negative


def test_a_defuse_strips_an_enemy_gauge():
    from ltg_core.schema import Charge
    st = state_from_dict({"party": [_hero([_filler("x")])], "enemies": [_enemy()]})
    e = st.enemies[0]
    e.charge = 3
    defuse = Charge.model_validate({
        "kind": "charge", "op": "remove", "amount": "all",
        "target": {"mode": "chosen", "side": "enemy", "targeted": True}})
    assert "Remove all charge counters" in render_effects([defuse])
    _resolve_on(st, [defuse], target_id=e.id)
    assert e.charge == 0
    assert any(l.type == "charge_drained" for l in st.log)


# --------------------------------------------------------------------------- #
# §D22-3 — channel_drop validation
# --------------------------------------------------------------------------- #
def _drop_card(trigger, extra_effects=(), cid="fuse"):
    return {"id": cid, "name": "Fuse", "rarity": "common", "level": 1,
            "type": "Enchantment", "timing": "channeled",
            "cost": {"generic": 0, "colors": {"U": 1}},
            "effects": list(extra_effects) + [{"kind": "channel_drop", "trigger": trigger}],
            "validated": True}


def test_channel_drop_is_enchantment_only_and_needs_a_fuse():
    assert "channel_drop" in effect_specs()
    Card.model_validate(_drop_card({"after_turns": 2}))     # legal
    with pytest.raises(ValidationError):                    # not on a one-shot card
        Card.model_validate({**_drop_card({"after_turns": 2}),
                             "type": "Sorcery", "timing": "sorcery"})
    with pytest.raises(ValidationError):                    # never untriggered
        Card.model_validate(_drop_card(None))


def test_channel_drop_renders_with_its_fuse():
    card = Card.model_validate(_drop_card({"after_turns": 3}))
    assert "After 3 turns: this enchantment drops." in render_effects(
        card.effects, card.targets, channeled=True)


# --------------------------------------------------------------------------- #
# §D22-3 — channel_drop in play: it ends ITS channel, not a sibling's
# --------------------------------------------------------------------------- #
AURA = {"id": "aura", "name": "Warcry", "rarity": "common",
        "level": 1, "type": "Enchantment", "timing": "channeled",
        "cost": {"generic": 0, "colors": {"U": 1}},
        "effects": [{"kind": "pump", "power": 2, "toughness": 0,
                     "duration": "while_channeled", "target": {"mode": "self"}}],
        "validated": True}


def test_channel_drop_ends_only_its_own_channel():
    fuse = _drop_card({"after_turns": 1},
                      extra_effects=[{"kind": "pump", "power": 1, "toughness": 0,
                                      "duration": "while_channeled",
                                      "target": {"mode": "self"}}])
    st = state_from_dict({
        "party": [_hero([copy.deepcopy(AURA), copy.deepcopy(fuse), _filler("x")],
                        identity=("U", "U", "U"), hand=2)],
        "enemies": [_enemy()]})
    st = _cast_and_hold(st, "aura")
    st = _cast_and_hold(st, "fuse")
    p = st.character("p")
    assert {ch.card.id for ch in p.channels} == {"aura", "fuse"}
    reserved_before = sum(len(ch.reserved) for ch in p.channels)
    assert reserved_before == 2

    # The next Upkeep: the fuse's countdown expires, the drop fires and ends
    # ONLY the fuse's channel — the aura keeps humming.
    turn = st.turn
    st = _drive(st, lambda s: s.turn > turn and not s.stack)
    p = st.character("p")
    assert {ch.card.id for ch in p.channels} == {"aura"}
    assert any(l.type == "channel_drop" for l in st.log)
    assert any(l.type == "channel_end" and l.data.get("reason") == "channel drop"
               for l in st.log)
    assert p.power_bonus == 2                   # the aura's pump still applies
    assert "U" in p.pool                        # the fuse's reserved pip returned


# --------------------------------------------------------------------------- #
# §D22-4 — after_turns fires once, at the right Upkeep
# --------------------------------------------------------------------------- #
def test_after_turns_fires_once_after_n_upkeeps():
    bomb = {"id": "bomb", "name": "Slow Bomb", "rarity": "common",
            "level": 1, "type": "Enchantment", "timing": "channeled",
            "cost": {"generic": 0, "colors": {"U": 1}},
            "effects": [{"kind": "deal_damage", "amount": 5,
                         "target": {"mode": "all", "side": "enemy"},
                         "trigger": {"after_turns": 2}}],
            "validated": True}
    st = state_from_dict({
        "party": [_hero([bomb, _filler("x"), _filler("y")],
                        identity=("U", "U"), hand=2)],
        "enemies": [_enemy(hp=30)]})
    st = _cast_and_hold(st, "bomb")
    cast_turn = st.turn

    st = _drive(st, lambda s: s.turn == cast_turn + 1 and not s.stack)
    assert st.enemies[0].hp == 30               # turn +1: still counting down

    st = _drive(st, lambda s: s.turn == cast_turn + 2 and not s.stack)
    assert st.enemies[0].hp == 25               # turn +2: the countdown fires

    st = _drive(st, lambda s: s.turn == cast_turn + 3 and not s.stack)
    assert st.enemies[0].hp == 25               # and never fires again


def test_after_turns_countdown_is_surfaced_to_the_client():
    from ltg_combat.serialize import _channel_countdown
    st = state_from_dict({
        "party": [_hero([_drop_card({"after_turns": 3}, cid="fuse"), _filler("x")],
                        identity=("U", "U"), hand=2)],
        "enemies": [_enemy()]})
    st = _cast_and_hold(st, "fuse")
    ch = st.character("p").channels[0]
    assert _channel_countdown(st, ch) == 3
    turn = st.turn
    st = _drive(st, lambda s: s.turn > turn and not s.stack)
    ch = st.character("p").channels[0]
    assert _channel_countdown(st, ch) == 2      # down one each Upkeep
