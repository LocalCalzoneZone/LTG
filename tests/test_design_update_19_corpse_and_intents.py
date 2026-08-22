"""Design Update 19 — corpse fuel, intent re-validation, and the hexproof price.

Playtest again: corpse-explosion effects had no proper way to spend their body
(§D19-1), a boss's second intent was invisible in the inspect panel (§D19-2),
Warded gear read as an auto-include (§D19-3), and telegraphed intents crawled
onto the stack long after they had stopped making sense (§D19-4).
"""

from __future__ import annotations

from ltg_combat.engine import (
    _cost_last,
    _intent_spoiled,
    _try_declare_component,
    apply_action,
    legal_actions,
)
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Corpse, StackItem
from ltg_core.schema import CORPSE_LEGAL_EFFECTS, ConsumeCorpse, DealDamage, TargetDescriptor
from ltg_core.translation import render_effects


CORPSE_T = {"mode": "chosen", "side": "enemy", "targeted": True, "state": "corpse"}


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", hp=30, power=2, keywords=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 1,
            "identity": ["U"], "row": row, "attack_mode": "melee",
            "keywords": keywords or [],
            "library": [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid="ghoul", power=4, hp=30, components=None, level=3):
    return {"id": eid, "name": eid, "hp": hp, "level": level, "power": power,
            "attack_mode": "melee", "row": "front",
            "intent": {"name": "Claw", "amount": power, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"},
            "components": components or []}


def _comp(cid, verbs, **kw):
    base = {"id": cid, "timing": "proactive", "priority": 10,
            "target_rule": "valuation", "telegraph": cid, "verbs": verbs}
    base.update(kw)
    return base


def _state(party, enemies):
    return state_from_dict({"party": party, "enemies": enemies})


def _lay_a_corpse(st, cid="thrall", row="front"):
    body = st.enemies[-1]
    corpse = Corpse(id=cid, name=cid, row=row, power=1, max_hp=4, level=2,
                    attack_mode="melee", is_boss=False, stirring=0, body=body)
    st.corpses.append(corpse)
    return corpse


def _resolve(st, intent, source):
    from ltg_combat.engine import _new_ctx, _resolve_effect_list
    item = StackItem(kind="ability", source_id=source.id, source_side="enemy",
                     label=intent.name, effects=intent.effects,
                     target_id=intent.target_id, corpse_id=intent.corpse_id)
    _resolve_effect_list(st, item, item.effects, _new_ctx(st, item))
    return item


# --------------------------------------------------------------------------- #
# §D19-1 — corpse fuel
# --------------------------------------------------------------------------- #
def _feast(verbs=None, **kw):
    return _comp("feast", verbs or [
        {"kind": "deal_damage", "amount": 5,
         "target": {"mode": "all", "side": "ally", "rows": ["front"]}},
        {"kind": "consume_corpse", "target": dict(CORPSE_T)},
    ], **kw)


def test_consume_corpse_is_a_corpse_legal_verb_that_reads_as_a_cost():
    assert "consume_corpse" in CORPSE_LEGAL_EFFECTS
    text = render_effects([
        ConsumeCorpse(target=TargetDescriptor.model_validate(CORPSE_T)),
        DealDamage(amount=3, target=TargetDescriptor.model_validate(
            {"mode": "all", "side": "ally", "rows": ["front"]})),
    ])
    assert "Consume an enemy corpse." in text


def test_the_fuel_is_spent_after_the_payload_however_it_is_authored():
    """The point of the verb: 'devour a fallen kin and blast the row' is ONE
    action whose payload happens and THEN eats the body."""
    payload = DealDamage(amount=3, target=TargetDescriptor.model_validate(
        {"mode": "all", "side": "ally"}))
    fuel = ConsumeCorpse(target=TargetDescriptor.model_validate(CORPSE_T))
    assert [e.kind for e in _cost_last([fuel, payload])] == ["deal_damage", "consume_corpse"]
    assert [e.kind for e in _cost_last([payload, fuel])] == ["deal_damage", "consume_corpse"]
    assert [e.kind for e in _cost_last([payload])] == ["deal_damage"]


def test_a_corpse_rule_does_not_declare_without_a_body():
    st = _state([_char("p")], [_enemy(components=[_feast()])])
    e = st.enemies[0]
    assert _try_declare_component(st, e, e.components[0]) is None   # nothing to eat
    _lay_a_corpse(st)
    assert _try_declare_component(st, e, e.components[0]) is not None


def test_the_body_binds_separately_from_the_payloads_target():
    """The live bug: a component aiming its payload at a HERO (`target_rule`
    valuation) bound its corpse verb to that hero — and exiled them outright."""
    st = _state([_char("p", hp=30)], [_enemy(components=[_feast()])])
    _lay_a_corpse(st)
    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert intent.target_id == "p" and intent.corpse_id == "thrall"
    _resolve(st, intent, e)
    assert st.corpse("thrall") is None          # the body was spent
    assert st.character("p").hp == 25           # …and the hero took the blast, not the exile
    assert st.character("p").alive


def test_a_raw_exile_on_a_corpse_also_binds_to_the_body():
    """Shipped content predates the verb and writes `exile` — it must not be able
    to hit the living target the payload named."""
    burn = _comp("fuel", [
        {"kind": "exile", "target": dict(CORPSE_T)},
        {"kind": "deal_damage", "amount": 4, "target": {"mode": "all", "side": "ally"}},
    ])
    st = _state([_char("p", hp=30)], [_enemy(components=[burn])])
    _lay_a_corpse(st)
    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert intent.corpse_id == "thrall"
    _resolve(st, intent, e)
    assert st.corpse("thrall") is None
    assert st.character("p").hp == 26 and st.character("p").alive


def test_the_generation_gate_asks_for_the_fuel_verb():
    from ltg_game_server.llm import _corpse_problems
    hand_rolled = {"enemies": [{"name": "Widow", "components": [{"id": "feast", "verbs": [
        {"kind": "exile", "target": dict(CORPSE_T)},
        {"kind": "deal_damage", "amount": 3}]}]}]}
    assert any("consume_corpse" in p for p in _corpse_problems(hand_rolled))
    proper = {"enemies": [{"name": "Widow", "components": [{"id": "feast", "verbs": [
        {"kind": "deal_damage", "amount": 3},
        {"kind": "consume_corpse", "target": dict(CORPSE_T)}]}]}]}
    assert _corpse_problems(proper) == []
    # A plain corpse-burn on its own (an anti-necromancy tool) is still fine.
    lone = {"enemies": [{"name": "Widow", "components": [{"id": "burn", "verbs": [
        {"kind": "exile", "target": dict(CORPSE_T)}]}]}]}
    assert _corpse_problems(lone) == []


# --------------------------------------------------------------------------- #
# §D19-4 — an intent is re-validated before it is announced
# --------------------------------------------------------------------------- #
def _curse():
    return _comp("curse", [{"kind": "wound", "power": 1, "toughness": 1,
                            "target": {"mode": "chosen", "side": "ally",
                                       "targeted": True}}],
                 action_type="spell")


def _mend():
    return _comp("mend", [{"kind": "heal", "amount": 5,
                           "target": {"mode": "chosen", "side": "enemy",
                                      "targeted": True}}],
                 target_rule="lowest_hp_ally")


def test_a_hexproof_target_spoils_the_intent_before_the_stack():
    """The curse is aimed at a bare hero, who then wards themself — exactly the
    window the telegraph opens. (A hero already hexproof at declaration is never
    picked in the first place; that half is §D18-4's `_pickable`.)"""
    st = _state([_char("p")], [_enemy(components=[_curse()])])
    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert intent.target_id == "p" and _intent_spoiled(st, e, intent) is None
    st.character("p").keywords["hexproof"] = "encounter"
    assert "Hexproof" in (_intent_spoiled(st, e, intent) or "")


def test_a_dead_ally_spoils_a_support_intent():
    """'Heal the wounded ally' whose ally has since died: the id now names a
    BODY, and only control/exile-class verbs have business with one."""
    st = _state([_char("p")], [_enemy(components=[_mend()]), _enemy("wretch", hp=6)])
    st.enemy("wretch").hp = 2                     # give the healer something to mend
    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert intent.target_id == "wretch" and _intent_spoiled(st, e, intent) is None
    st.enemies = [x for x in st.enemies if x.id != "wretch"]
    _lay_a_corpse(st, cid="wretch")
    assert _intent_spoiled(st, e, intent) == "wretch is dead"


def test_a_spent_body_spoils_a_corpse_intent():
    st = _state([_char("p")], [_enemy(components=[_feast()])])
    _lay_a_corpse(st)
    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert _intent_spoiled(st, e, intent) is None
    st.corpses.clear()                            # the party burned it in response
    assert _intent_spoiled(st, e, intent) == "the body it would spend is gone"


def test_a_good_intent_is_not_spoiled():
    st = _state([_char("p")], [_enemy(components=[_curse()])])
    e = st.enemies[0]
    intent = _try_declare_component(st, e, e.components[0])
    assert _intent_spoiled(st, e, intent) is None


def test_a_spoiled_intent_swings_instead_of_evaporating():
    """End to end through the real declare → execute path: the curse is aimed,
    the hero wards themself in the window the telegraph opens, and the enemy
    takes its basic attack rather than losing the whole activation."""
    from ltg_combat.engine import _declare_enemy_intent, _execute_intent

    st = _state([_char("p", hp=30)], [_enemy(power=4, components=[_curse()])])
    e = st.enemies[0]
    _declare_enemy_intent(st, e)
    assert e.intent.name == "curse" and e.intent.target_id == "p"

    st.character("p").keywords["hexproof"] = "encounter"   # warded in response
    _execute_intent(st, e)

    spoiled = [l for l in st.log if l.type == "intent_spoiled"]
    assert spoiled and "Hexproof" in spoiled[0].data["reason"]
    assert e.round_intent_status == "fizzled"              # the telegraph is struck
    # A real swing is on the stack — the party still gets its reaction window.
    assert [i.kind for i in st.stack] == ["attack"]
    assert st.stack[-1].target_id == "p" and st.stack[-1].attack_power == 4
    assert st.priority is None and st.passes == 0
    assert e.rounds_since_swing == 0                       # §D18-3: the sword counts


def test_a_spoiled_intent_with_nothing_to_hit_simply_ends():
    """Pacified, or nothing in reach: there is no sword to fall back on and the
    activation is genuinely lost — no crash, no phantom stack item."""
    from ltg_combat.engine import _declare_enemy_intent, _execute_intent
    from ltg_combat.state import PreventTag

    st = _state([_char("p", hp=30)], [_enemy(power=4, components=[_curse()])])
    e = st.enemies[0]
    _declare_enemy_intent(st, e)
    st.character("p").keywords["hexproof"] = "encounter"
    e.prevent_tags.append(PreventTag(parameter="attack"))  # pacified
    _execute_intent(st, e)
    assert st.stack == [] and e.round_intent_status == "fizzled"


# --------------------------------------------------------------------------- #
# §D19-3 — hexproof is priced like what it turns off
# --------------------------------------------------------------------------- #
def test_warded_is_the_dearest_rider_in_the_affix_table():
    from ltg_game_server.items import AFFIXES
    by_id = {a["id"]: a for a in AFFIXES}
    warded = by_id["warded"]
    assert warded["points"] == 40 and warded["rarity_min"] == "mythic"
    assert warded["level_min"] == 6 and warded["banned"] is True
    # Above indestructible: removal is narrow next to turning off every targeted
    # curse, stun, silence, sap, drain and snipe an encounter carries.
    assert warded["points"] > by_id["unbroken"]["points"]
    assert all(warded["points"] >= a["points"] for a in AFFIXES)
