"""Death is final (playtest fix, 2026-08): once a creature's effective_hp is
≤ 0 it dies and STAYS dead — an expiring −X/−X must not hand its victim back
the toughness that killed it. Covers the End-step reap ordering, the lethality
checks on the non-damage stat verbs (negative pump / negative counters), and
the aura-lift buffer accounting."""

from __future__ import annotations

from ltg_combat.engine import (_apply_static, _end_step, apply_action,
                               legal_actions)
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import Pump


def _enemy(eid, name, hp, amount=0):
    return {"id": eid, "name": name, "hp": hp, "level": 1, "row": "front",
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _hero(hand=None):
    return {"id": "h", "name": "H", "archetype": "Fighter", "hp": 20, "power": 3,
            "hand_size": len(hand or []), "identity": ["W", "U", "B", "R", "G"],
            "attack_mode": "melee", "row": "front", "library": hand or []}


def _pump_spell(power, toughness):
    return {"id": "hex", "name": "Hex", "source_name": "hex", "rarity": "common",
            "level": 1, "type": "Sorcery", "timing": "sorcery",
            "cost": {"colors": {"U": 1}},
            "effects": [{"kind": "pump", "power": power, "toughness": toughness,
                         "target": {"mode": "chosen", "side": "enemy",
                                    "targeted": True}}],
            "validated": True}


def _settle(st):
    while st.stack and st.result is None:
        st, _ = apply_action(st, next(a for a in legal_actions(st)
                                      if a.kind == "pass"))
    return st


def test_enemy_at_zero_effective_hp_dies_at_end_step_and_stays_dead():
    # An enemy driven to effective_hp ≤ 0 by a turn-scoped −X/−X (through any
    # path that missed the eager kill check) must be reaped BEFORE the End-step
    # layer reset — not resurrected by the wound wearing off.
    st = state_from_dict({"party": [_hero()],
                         "enemies": [_enemy("orc", "Orc", 3)]})
    st.enemy("orc").temp_mod = -4          # eff −1: dead, but not yet reaped
    assert not st.enemy("orc").alive
    _end_step(st)
    assert st.enemy("orc") is None         # reaped, not resurrected
    assert any(c.id == "orc" for c in st.corpses)


def test_negative_pump_kills_immediately():
    st = state_from_dict({"party": [_hero(hand=[_pump_spell(0, -4)])],
                         "enemies": [_enemy("orc", "Orc", 3)]})
    st, _ = apply_action(st, next(a for a in legal_actions(st)
                                  if a.kind == "cast"))
    st = _settle(st)
    assert st.enemy("orc") is None         # −0/−4 on 3 HP is lethal on the spot
    assert any(c.id == "orc" for c in st.corpses)


def test_aura_lift_consumes_only_the_surviving_buffer():
    # A +0/+3 aura whose buffer was partly spent by damage: lifting it removes
    # what REMAINS of the buffer, never digging a phantom wound (the spent share
    # was already paid for via _apply_damage's absorption).
    st = state_from_dict({"party": [_hero()],
                         "enemies": [_enemy("orc", "Orc", 5)]})
    orc = st.enemy("orc")
    eff = Pump(power=0, toughness=3, target={"mode": "self"})
    _apply_static(st, orc, eff, +1)
    assert orc.temp_mod == 3
    orc.temp_mod -= 2                      # damage absorbed into the buffer
    _apply_static(st, orc, eff, -1)
    assert orc.temp_mod == 0               # not −2 — and the orc lives
    assert orc.alive and st.enemy("orc") is not None
