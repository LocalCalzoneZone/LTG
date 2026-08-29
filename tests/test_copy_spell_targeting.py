"""Copy-spell targeting fixes (playtest, 2026-08): uncopyable spells are never
offered as copy targets, a copied enemy spell turns on the ENEMY side (the
ally/enemy language flips to the copier), stack-facing copies keep the
original's aim instead of fizzling, and a copy that keeps the original's
targets says so in the log."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import StackItem
from ltg_core.schema import Card

CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}
CHOSEN_ALLY_T = {"mode": "chosen", "side": "ally", "targeted": True}
ALL_ALLIES = {"mode": "all", "side": "ally"}


def _card(cid, name, timing, effects):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": 1, "type": "Spell", "timing": timing, "cost": {},
            "effects": effects, "validated": True}


def _char(cid, hand=0, library=None):
    return {"id": cid, "name": cid, "hp": 30, "power": 3, "hand_size": hand,
            "identity": ["U"], "row": "front", "attack_mode": "melee",
            "library": library or []}


def _enemy(eid, hp=10):
    return {"id": eid, "name": eid, "hp": hp, "level": 3,
            "intent": {"name": "Hit", "amount": 2, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _do(st, kind, **match):
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal '{kind}' action ({match}) among "
                         f"{[a.label for a in legal_actions(st)]}")


MIRROR = _card("mirror", "Twincast", "instant", [{"kind": "copy_spell"}])


def _effects(effect_dicts):
    return Card.model_validate(_card("tmp", "Tmp", "sorcery", effect_dicts)).effects


def test_channeled_cast_is_not_a_copy_target():
    ward = _card("ward", "Slow Burn", "channeled",
                 [{"kind": "pump", "power": 1, "toughness": 0,
                   "duration": "while_channeled", "target": {"mode": "self"}}])
    st = state_from_dict({"party": [_char("p", hand=2, library=[ward, MIRROR])],
                          "enemies": [_enemy("e1")]})
    st = _do(st, "cast", card_id="ward")
    # The channelled cast is on the stack — the mirror has nothing legal to
    # copy, so it is not offerable at all (no wasted card, no fizzle).
    assert not any(a.kind == "cast" and a.card_id == "mirror"
                   for a in legal_actions(st))


def test_enemy_channel_start_intent_is_not_a_copy_target():
    st = state_from_dict({"party": [_char("p", hand=1, library=[MIRROR])],
                          "enemies": [_enemy("e1")]})
    st.stack.append(StackItem(
        kind="spell", source_id="e1", source_side="enemy", label="Dread Ritual",
        effects=_effects([{"kind": "pump", "power": 2, "toughness": 2,
                           "target": {"mode": "self"}}]),
        starts_channel=True, uid=901))
    assert not any(a.kind == "cast" and a.card_id == "mirror"
                   for a in legal_actions(st))


def test_copied_enemy_aoe_flips_onto_the_enemy_side():
    st = state_from_dict({"party": [_char("p", hand=1, library=[MIRROR])],
                          "enemies": [_enemy("e1"), _enemy("e2")]})
    # An enemy Firestorm: deal 3 to every hero (enemy verbs say side "ally").
    st.stack.append(StackItem(
        kind="spell", source_id="e1", source_side="enemy", label="Firestorm",
        effects=_effects([{"kind": "deal_damage", "amount": 3,
                           "target": ALL_ALLIES}]),
        uid=902))
    st = _do(st, "cast", card_id="mirror", target_id="#902")
    while st.stack and st.result is None:
        st = _do(st, "pass")
    # The COPY hit the enemies; only the ORIGINAL hit the party.
    assert st.enemy("e1").hp == 7 and st.enemy("e2").hp == 7
    assert st.character("p").hp == 27


def test_copied_enemy_bolt_reaims_at_enemies_not_the_party():
    st = state_from_dict({"party": [_char("p", hand=1, library=[MIRROR])],
                          "enemies": [_enemy("e1"), _enemy("e2")]})
    st.stack.append(StackItem(
        kind="spell", source_id="e1", source_side="enemy", label="Shadow Bolt",
        effects=_effects([{"kind": "deal_damage", "amount": 4,
                           "target": CHOSEN_ALLY_T}]),
        target_id="p", uid=903))
    st = _do(st, "cast", card_id="mirror", target_id="#903")
    st = _do(st, "pass")     # the mirror resolves; the copy asks for a target
    assert st.pending_choice is not None and st.pending_choice.kind == "target"
    offers = {a.target_id for a in legal_actions(st) if a.kind == "choose_target"}
    assert offers == {"e1", "e2"}      # the copier's pick is among ENEMIES
    st = _do(st, "choose_target", target_id="e2")
    while st.stack and st.result is None:
        st = _do(st, "pass")
    assert st.enemy("e2").hp == 6


def test_multi_target_copy_keeps_targets_and_says_so():
    warp = _card("warp", "Agony Warp", "sorcery",
                 [{"kind": "deal_damage", "amount": 2, "target": CHOSEN_ENEMY_T},
                  {"kind": "deal_damage", "amount": 1, "target": CHOSEN_ENEMY_T}])
    st = state_from_dict({"party": [_char("p", hand=2, library=[warp, MIRROR])],
                          "enemies": [_enemy("e1"), _enemy("e2")]})
    st = _do(st, "cast", card_id="warp")
    mirror_act = next(a for a in legal_actions(st)
                      if a.kind == "cast" and a.card_id == "mirror")
    st = apply_action(st, mirror_act)[0]
    while st.stack and st.result is None:
        st = _do(st, "pass")
    assert any(e.type == "copy_spell"
               and "keeps the original's targets" in e.msg for e in st.log)


def test_copied_counter_raises_a_stack_pick_and_counters():
    negate = _card("negate", "Negate", "instant",
                   [{"kind": "counter", "filter": "spell"}])
    st = state_from_dict({"party": [_char("p", hand=2, library=[negate, MIRROR])],
                          "enemies": [_enemy("e1")]})
    st.stack.append(StackItem(
        kind="spell", source_id="e1", source_side="enemy", label="Doom Ray",
        effects=_effects([{"kind": "deal_damage", "amount": 9,
                           "target": CHOSEN_ALLY_T}]),
        target_id="p", uid=904))
    st = _do(st, "cast", card_id="negate", target_id="#904")
    negate_uid = st.stack[-1].uid
    st = _do(st, "cast", card_id="mirror", target_id=f"#{negate_uid}")
    st = _do(st, "pass")     # the mirror resolves; the copy asks for a STACK pick
    assert st.pending_choice is not None and st.pending_choice.kind == "target"
    offers = {a.target_id for a in legal_actions(st) if a.kind == "choose_target"}
    assert offers == {"#904"}    # enemy actions only — never the party's Negate
    st = _do(st, "choose_target", target_id="#904")
    while st.stack and st.result is None:
        st = _do(st, "pass")
    # The copy countered the ray (the original Negate then found nothing left —
    # its fizzle is the harmless one).
    assert any(e.type == "countered" and "Copy of" in e.msg for e in st.log)
    assert st.character("p").hp == 30        # the ray never landed


def test_copy_a_counter_to_counter_the_counter():
    # Two enemy rays on the stack: Negate answers one, its copy re-aims at the
    # OTHER — one Negate cast, both rays dead.
    negate = _card("negate", "Negate", "instant",
                   [{"kind": "counter", "filter": "spell"}])
    st = state_from_dict({"party": [_char("p", hand=2, library=[negate, MIRROR])],
                          "enemies": [_enemy("e1")]})
    for uid, label in ((905, "Doom Ray"), (906, "Ruin Ray")):
        st.stack.append(StackItem(
            kind="spell", source_id="e1", source_side="enemy", label=label,
            effects=_effects([{"kind": "deal_damage", "amount": 9,
                               "target": CHOSEN_ALLY_T}]),
            target_id="p", uid=uid))
    st = _do(st, "cast", card_id="negate", target_id="#905")
    negate_uid = st.stack[-1].uid
    st = _do(st, "cast", card_id="mirror", target_id=f"#{negate_uid}")
    st = _do(st, "pass")
    offers = {a.target_id for a in legal_actions(st) if a.kind == "choose_target"}
    assert offers == {"#905", "#906"}
    st = _do(st, "choose_target", target_id="#906")
    while st.stack and st.result is None:
        st = _do(st, "pass")
    assert st.character("p").hp == 30            # neither ray landed
    assert sum(1 for e in st.log if e.type == "countered") == 2
