"""Enemy channels (GDD §8, enemy side): a `channel: true` component resolves into
a held EnemyChannel — continuous verbs (while_channeled) hold, upkeep verbs tick
every turn — until the party breaks it: one hit of ≥25% of the channeler's max HP,
or removing the channeler (kill / bounce / suspension). It enters play through the
stack (counterable), and the snapshot names it so the player knows what breaking
buys them."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict

# "Ritual of Thorns": a channelled wound-aura on the whole party (-1/-1 while held).
_RITUAL = {
    "id": "ritual", "archetype": "Debilitate", "timing": "proactive",
    "priority": 10, "cooldown": 2, "target_rule": "self",
    "channel": True, "action_type": "spell",
    "telegraph": "Ritual of Thorns — all heroes -1/-1 while channeled",
    "verbs": [{"kind": "wound", "power": 1, "toughness": 1,
               "duration": "while_channeled",
               "target": {"mode": "all", "side": "ally"}}],
}

# "Burning Litany": a channelled ritual tick — 2 damage to a hero every upkeep.
_LITANY = {
    "id": "litany", "archetype": "Burst", "timing": "proactive",
    "priority": 10, "cooldown": 2, "target_rule": "valuation",
    "channel": True,
    "telegraph": "Burning Litany — 2 damage every turn",
    "verbs": [{"kind": "deal_damage", "amount": 2, "trigger": "upkeep",
               "target": {"mode": "chosen", "side": "ally", "targeted": True}}],
}

_NEGATE = {"id": "negate", "name": "Negate", "source_name": "Negate",
           "rarity": "common", "level": 1, "type": "Instant", "timing": "instant",
           "cost": {"generic": 0, "colors": {}},
           "effects": [{"kind": "counter", "filter": "spell",
                        "target": {"class": "action", "side": "enemy"}}],
           "validated": True}


def _state(comp, power=3, hand=None):
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": power,
                   "hand_size": len(hand or []), "identity": ["U"], "row": "front",
                   "attack_mode": "melee", "library": hand or []}],
        "enemies": [{"id": "warlock", "name": "Warlock", "hp": 12, "level": 3,
                     "intent": {"name": "Bash", "amount": 1, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"},
                     "components": [dict(comp)]}],
    })


def _advance(st, until, budget=80):
    for _ in range(budget):
        if until(st):
            return st
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    return st


def _channeling(st):
    e = st.enemy("warlock")
    return e is not None and bool(e.channels)


def test_channel_starts_and_aura_holds():
    st = _advance(_state(_RITUAL), _channeling)
    w = st.enemy("warlock")
    assert [ch.name for ch in w.channels] == [_RITUAL["telegraph"]]
    p = st.character("p")
    assert p.temp_mod == -1 and p.power_bonus == -1     # the aura is ON
    assert any(e.type == "channel_start" for e in st.log)


def test_big_hit_breaks_the_channel_small_hit_does_not():
    # power 2 < ceil(12/4)=3: no break. power 4 ≥ 3: break, aura lifts.
    st = _advance(_state(_RITUAL, power=2), _channeling)
    st = _advance(st, lambda s: any(a.kind == "attack" for a in legal_actions(s)))
    st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "attack"))[0]
    st = _advance(st, lambda s: not s.stack)
    assert st.enemy("warlock").channels                  # 2 dmg: still held

    st = _advance(_state(_RITUAL, power=4), _channeling)
    st = _advance(st, lambda s: any(a.kind == "attack" for a in legal_actions(s)))
    st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "attack"))[0]
    st = _advance(st, lambda s: not s.stack)
    assert not st.enemy("warlock").channels              # 4 ≥ 25%: broken
    assert st.character("p").temp_mod == 0               # aura lifted
    assert any(e.type == "channel_end" for e in st.log)


def test_killing_the_channeler_lifts_the_aura():
    st = _advance(_state(_RITUAL), _channeling)
    st.enemy("warlock").hp = 1
    st = _advance(st, lambda s: any(a.kind == "attack" for a in legal_actions(s)))
    st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "attack"))[0]
    st = _advance(st, lambda s: not s.stack)
    assert st.enemy("warlock") is None or not st.enemy("warlock").alive
    assert st.character("p").temp_mod == 0               # died -> aura lifted


def test_upkeep_tick_fires_each_turn_until_broken():
    st = _advance(_state(_LITANY), _channeling)
    hp_after_start = st.character("p").hp
    # Run to the NEXT turn's player phase: the litany ticks 2 at upkeep.
    turn = st.turn
    st = _advance(st, lambda s: s.turn == turn + 1 and s.phase == "player" and not s.stack)
    assert st.character("p").hp <= hp_after_start - 2
    assert any(e.type == "damage" or "Litany" in e.msg for e in st.log)


def test_channel_is_counterable_on_the_stack():
    st = _state(_RITUAL, hand=[dict(_NEGATE)])
    # Run until the ritual (a spell) sits on the stack awaiting reactions.
    st = _advance(st, lambda s: any("Ritual" in i.label for i in s.stack))
    cast = next(a for a in legal_actions(st) if a.kind == "cast" and a.card_id == "negate")
    st = apply_action(st, cast)[0]
    st = _advance(st, lambda s: not s.stack)
    assert any(e.type == "countered" for e in st.log)
    assert not st.enemy("warlock").channels              # never came into being
    assert st.character("p").temp_mod == 0


def test_snapshot_names_the_channel():
    from ltg_game_server.snapshot import build_snapshot
    st = _advance(_state(_RITUAL), _channeling)
    snap = build_snapshot(st, set())
    (creature,) = snap["creatures"]
    assert creature["is_channeling"]
    assert creature["channels"] == [{"name": _RITUAL["telegraph"]}]
    assert creature["break_threshold"] == 3              # ceil(12/4)

# "Cursed Pact": a channelled aura with a dying sting — breaking it fires 3 damage
# at the party as a respondable stack trigger (channel_break, §8 both ways).
_PACT = {
    "id": "pact", "archetype": "Debilitate", "timing": "proactive",
    "priority": 10, "cooldown": 2, "target_rule": "self",
    "channel": True, "action_type": "spell",
    "telegraph": "Cursed Pact — all heroes -1/-1; 3 damage to all heroes if broken",
    "verbs": [
        {"kind": "wound", "power": 1, "toughness": 1, "duration": "while_channeled",
         "target": {"mode": "all", "side": "ally"}},
        {"kind": "deal_damage", "amount": 3, "trigger": "channel_break",
         "target": {"mode": "all", "side": "ally"}},
    ],
}


def test_break_verb_fires_when_the_channel_is_broken():
    st = _advance(_state(_PACT, power=4), _channeling)   # 4 ≥ ceil(12/4): a breaking hit
    hp_before = st.character("p").hp
    assert st.character("p").temp_mod == -1              # aura on; sting not yet fired
    st = _advance(st, lambda s: any(a.kind == "attack" for a in legal_actions(s)))
    st = apply_action(st, next(a for a in legal_actions(st) if a.kind == "attack"))[0]
    st = _advance(st, lambda s: not s.stack)
    assert not st.enemy("warlock").channels              # broken
    assert st.character("p").hp == hp_before - 3         # the sting resolved off the stack
    assert any(e.type == "channel_break_trigger" for e in st.log)
