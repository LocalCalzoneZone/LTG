"""The horde-divergence rule (§F-7.2 pending-claims refinement, playtest
2026-08): control declared this round is SPOKEN FOR before it lands.

Intents declare in canonical order before anything executes, so the landed-state
waste filters (`stunned`, `taunted_to`, `action_mods`) saw a clean board for
every clone in a horde: six copies of one debilitator all declared Hamstring on
the SAME hero — five wasted turns, since a persistent action modifier is a dict
overwrite, and the round read as one enemy telegraphed six times.
`_pending_control_claims` closes the window: a clone's control rule skips heroes
an earlier declaration already claims, spreads across the party, and once every
hero is claimed the rule EMPTIES — the clone falls through to its next component
or the sword, desynchronising the horde's cooldowns for the rest of the fight.
"""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _filler(cid):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "instant", "cost": {"generic": 0, "colors": {}},
            "effects": [{"kind": "draw", "amount": 0}]}


def _char(cid, row="front", power=2, hp=30):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 1,
            "identity": ["U"], "row": row, "attack_mode": "melee", "keywords": [],
            "library": [_filler(cid + "_a"), _filler(cid + "_b")]}


def _enemy(eid, components, power=3):
    # Ranged, so every hero row is in reach — these tests are about the claims
    # filter, not the reach rules.
    return {"id": eid, "name": eid, "hp": 20, "level": 3, "power": power,
            "attack_mode": "ranged", "row": "rear",
            "intent": {"name": "Volley", "amount": power, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "ranged"},
            "components": components}


def _comp(cid, verbs, **kw):
    base = {"id": cid, "timing": "proactive", "priority": 10, "cooldown": 3,
            "target_rule": "valuation", "telegraph": cid, "verbs": verbs}
    base.update(kw)
    return base


def _hamstring():
    return _comp("hamstring", [
        {"kind": "modify_action", "action": "skill", "modifier": "lock_skill",
         "duration": "this_turn",
         "target": {"mode": "chosen", "side": "ally", "targeted": True}},
        {"kind": "deal_damage", "amount": 2,
         "target": {"mode": "chosen", "side": "ally", "targeted": True}}])


def _stunner():
    return _comp("skull_ring", [
        {"kind": "stun",
         "target": {"mode": "chosen", "side": "ally", "targeted": True}}])


def _declared(state):
    """Advance until every enemy has filed this round's slot-1 declaration."""
    for _ in range(120):
        if state.enemies and all(e.round_intent_status != "none"
                                 for e in state.enemies if e.hp > 0):
            return state
        a = next((a for a in legal_actions(state) if a.kind == "pass"), None)
        if a is None:
            a = next((a for a in legal_actions(state) if a.kind == "end_turn"), None)
        if a is None:
            return state
        state = apply_action(state, a)[0]
    return state


def _lock_targets(state):
    """(enemy id, target id) for every declared intent that carries a lock."""
    out = []
    for e in state.enemies:
        i = e.intent
        if i is not None and any(getattr(v, "kind", "") in ("modify_action", "stun")
                                 for v in i.effects):
            out.append((e.id, i.target_id))
    return out


def test_clone_locks_spread_across_the_party():
    """Three Hamstring clones, three heroes: three DIFFERENT victims — not one
    hero locked thrice while two walk free."""
    st = state_from_dict({
        "party": [_char("a"), _char("b", row="mid"), _char("c", row="rear")],
        "enemies": [_enemy(f"cutter_{i}", [_hamstring()]) for i in range(3)]})
    st = _declared(st)
    locks = _lock_targets(st)
    assert len(locks) == 3
    assert len({t for _, t in locks}) == 3          # three distinct heroes


def test_surplus_clones_fall_through_to_the_sword():
    """Four clones, two heroes: two locks, and the OTHER TWO do something else
    (the basic attack) instead of declaring redundant copies."""
    st = state_from_dict({
        "party": [_char("a"), _char("b", row="mid")],
        "enemies": [_enemy(f"cutter_{i}", [_hamstring()]) for i in range(4)]})
    st = _declared(st)
    locks = _lock_targets(st)
    assert len(locks) == 2
    assert {t for _, t in locks} == {"a", "b"}
    swings = [e for e in st.enemies if e.intent is not None
              and e.intent.source_component is None]
    assert len(swings) == 2                          # the surplus swings instead


def test_pending_stuns_spread_too():
    st = state_from_dict({
        "party": [_char("a"), _char("b", row="mid")],
        "enemies": [_enemy(f"ringer_{i}", [_stunner()]) for i in range(3)]})
    st = _declared(st)
    stuns = [(e.id, e.intent.target_id) for e in st.enemies
             if e.intent is not None
             and any(getattr(v, "kind", "") == "stun" for v in e.intent.effects)]
    assert len(stuns) == 2                           # one per hero, third swings
    assert len({t for _, t in stuns}) == 2


def test_a_landed_lock_still_blocks_next_round():
    """The pre-existing landed-state behaviour survives the refactor: a hero
    already carrying the modifier is skipped even with no pending intents."""
    st = state_from_dict({
        "party": [_char("a"), _char("b", row="mid")],
        "enemies": [_enemy("cutter", [_hamstring()])]})
    st = _declared(st)
    st.character("a").action_mods["lock_skill"] = "encounter"
    # Re-declare from scratch against the landed lock.
    from ltg_combat.engine import _pickable
    e = st.enemies[0]
    comp = next(c for c in e.components
                if getattr(c, "timing", "proactive") == "proactive")
    cands = _pickable(st, e, comp)
    assert [c.id for c in cands] == ["b"]


def test_focus_fire_damage_is_untouched():
    """Only control dedupes. Plain damage clones may still all pick the same
    hero — focus fire is legitimate tactics, not waste."""
    biter = _comp("bite", [{"kind": "deal_damage", "amount": 3,
                            "target": {"mode": "chosen", "side": "ally",
                                       "targeted": True}}])
    st = state_from_dict({
        "party": [_char("a"), _char("b", row="mid", hp=10)],
        "enemies": [_enemy(f"wolf_{i}", [dict(biter)]) for i in range(3)]})
    st = _declared(st)
    targets = {e.intent.target_id for e in st.enemies if e.intent is not None}
    assert len(targets) == 1                         # the pack converges
