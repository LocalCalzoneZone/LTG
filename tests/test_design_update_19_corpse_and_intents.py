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


# --------------------------------------------------------------------------- #
# §D19-5 — playtest follow-ups: the register tells the truth, Mitigate always
# turns a point, and a channel's strip_intent works at both trigger moments.
# --------------------------------------------------------------------------- #
def test_the_register_retells_its_numbers_in_the_telegraph():
    """Playtest: the log read "deal 2 damage to the attacker" while the lifted
    verb hit for 4 — the register moved the amount and left the prose."""
    from ltg_game_server.content import _bump_enemy_power
    scen = {"enemies": [{"id": "e", "name": "e", "level": 3, "power": 1, "components": [
        {"id": "snap", "archetype": "Punish",
         "telegraph": "Flare-Snap — deal 2 to the attacker",
         "verbs": [{"kind": "deal_damage", "amount": 2,
                    "target": {"mode": "chosen", "side": "ally", "targeted": True}}]},
        {"id": "syphon", "telegraph": "Syphon — deals 4 damage and heals 4 HP",
         "verbs": [{"kind": "deal_damage", "amount": 4,
                    "target": {"mode": "chosen", "side": "ally", "targeted": True}},
                   {"kind": "heal", "amount": 4, "target": {"mode": "self"}}]},
    ]}]}
    comps = _bump_enemy_power(scen, 1)["enemies"][0]["components"]
    assert comps[0]["telegraph"] == "Flare-Snap — deal 4 to the attacker"
    # The ambiguous case: only the DAMAGE 4 moves; the heal's 4 stands.
    assert comps[1]["telegraph"] == "Syphon — deals 6 damage and heals 4 HP"


def test_a_scaled_enrage_retells_its_pump_and_burn():
    from ltg_game_server.content import _bump_enemy_power
    boss = {"id": "b", "name": "b", "level": 6, "power": 3, "is_boss": True,
            "components": [{"id": "fury", "archetype": "Enrage",
                            "telegraph": "FURY — +2/+2 permanently, and the hall burns for 3",
                            "verbs": [{"kind": "counters", "power": 2, "toughness": 2,
                                       "target": {"mode": "self"}},
                                      {"kind": "deal_damage", "amount": 3,
                                       "target": {"mode": "all", "side": "ally"}}]}]}
    comp = _bump_enemy_power({"enemies": [boss]}, 4)["enemies"][0]["components"][0]
    assert comp["telegraph"] == "FURY — +8/+5 permanently, and the hall burns for 8"


def test_mitigate_never_reduces_by_zero():
    """Playtest sweep: a hero wounded to 0 Power was offered the Mitigate, spent
    the once-per-turn reaction, and reduced nothing. X floors at 1."""
    from ltg_combat.engine import _mitigate_value

    class _C:
        current_power = 0
        modify_action_tags = []
    assert _mitigate_value(_C()) == 1
    _C.current_power = 1
    assert _mitigate_value(_C()) == 1
    _C.current_power = 5
    assert _mitigate_value(_C()) == 3


def _unravel_state():
    card = {"id": "unravel", "name": "Unravel", "source_name": "Unravel",
            "rarity": "common", "level": 1, "type": "Enchantment",
            "timing": "channeled", "cost": {"generic": 0, "colors": {}},
            "effects": [
                {"kind": "strip_intent", "trigger": "channel_start",
                 "target": {"mode": "chosen", "side": "enemy", "targeted": True}},
                {"kind": "strip_intent", "trigger": "upkeep",
                 "target": {"mode": "chosen", "side": "enemy", "targeted": True}},
            ], "validated": True}
    filler = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
              "level": 1, "type": "Instant", "timing": "instant",
              "cost": {"generic": 0, "colors": {}},
              "effects": [{"kind": "draw", "amount": 0}]}
    return state_from_dict({
        "party": [{"id": "p", "name": "p", "hp": 30, "power": 2, "hand_size": 1,
                   "identity": ["U"], "row": "front", "attack_mode": "melee",
                   "library": [card, filler]}],
        "enemies": [{"id": "ogre", "name": "ogre", "hp": 40, "level": 1,
                     "intent": {"name": "Bash", "amount": 5, "action_type": "attack",
                                "intent_type": "attack",
                                "targeting": "lowest_hp_party", "mode": "melee"}}]})


def test_channel_start_and_upkeep_strips_both_work():
    """The reported card: 'on channel start, strip intent' + 'on upkeep, strip
    intent'. The start half fell back to the card's (absent) primary target and
    silently no-opped; the upkeep half resolved BEFORE intents were declared and
    no-opped too. Now: the start strip is a cast-time pick, and a strip landing
    on an intent-less enemy lingers and smothers the next declaration."""
    st = _unravel_state()
    cast_seen = False
    for _ in range(400):
        acts = legal_actions(st)
        if not acts or st.result is not None:
            break
        cast = next((a for a in acts if a.kind == "cast"), None)
        if cast is not None and not cast_seen:
            assert cast.target_id == "ogre"      # the start strip is aimed at cast
            cast_seen = True
            st = apply_action(st, cast)[0]
            continue
        pick = next((a for a in acts if a.kind.startswith("choose")), None)
        if pick is not None:
            st = apply_action(st, pick)[0]
            continue
        a = next((a for a in acts if a.kind == "pass"), None) or \
            next((a for a in acts if a.kind == "end_turn"), None) or acts[0]
        st = apply_action(st, a)[0]
        if st.turn >= 4:
            break
    strips = [l for l in st.log if l.type == "strip_intent"]
    assert len(strips) >= 3                      # cast + two upkeeps
    assert st.character("p").hp == 30            # every Bash was smothered
    assert any(l.type == "strip_intent_pending" for l in st.log)


def test_base_stat_refs_read_the_printed_numbers():
    """§D19-5 deckbuilder ask: base Power / base toughness references, beside
    the live ones."""
    from ltg_combat.engine import _value
    from ltg_core.schema import REF_VALUES, Ref

    class _Obj:
        power = 2          # printed
        power_bonus = 3    # pumped
        max_hp = 20
        hp = 7

        @property
        def current_power(self):
            return self.power + self.power_bonus

        @property
        def effective_hp(self):
            return self.hp
    ctx = {"caster_obj": _Obj(), "target_obj": _Obj()}
    assert _value(Ref(ref="caster_power"), ctx) == 5        # live: base + bonus
    assert _value(Ref(ref="caster_base_power"), ctx) == 2   # printed only
    assert _value(Ref(ref="target_base_power"), ctx) == 2
    assert _value(Ref(ref="caster_hp"), ctx) == 7           # current
    assert _value(Ref(ref="caster_base_hp"), ctx) == 20     # max (base toughness)
    assert _value(Ref(ref="target_base_hp"), ctx) == 20
    for r in ("caster_base_power", "caster_base_hp",
              "target_base_power", "target_base_hp"):
        assert r in REF_VALUES                              # the editor dropdown sees them


def test_a_corpse_exclusive_pick_offers_corpses_only():
    """§D19-5 deckbuilder ask: `state: "corpse"` on a corpse-legal verb means the
    pick CANNOT name a living enemy — the editor's "corpse only" checkbox."""
    from ltg_combat.engine import _pick_options
    st = _state([_char("p")], [_enemy("living_one")])
    _lay_a_corpse(st, cid="fallen")
    opts = _pick_options(st, "enemy", True, "exile", state="corpse")
    assert [tid for tid, _ in opts] == ["fallen"]           # never the living
    # Without the flag, exile offers the living AND the corpses.
    both = _pick_options(st, "enemy", True, "exile", state=None)
    assert {"living_one", "fallen"} <= {tid for tid, _ in both}
