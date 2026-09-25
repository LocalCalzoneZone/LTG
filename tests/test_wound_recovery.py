"""Roadmap M3.12 (sweep A-20, §R-13.1): a hero downed ONLY by a turn-scoped
wound stands back up when the wound expires at the End step — GDD v2 §4.2
step 5 and §4.3. The fall is real while it lasts (incapacitated at once:
stack items gone, channels broken, the others paid their gauge), and a hero
whose HP is still ≤ 0 once the wound lifts stays down."""

from __future__ import annotations

from ltg_combat.engine import _end_step, apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _hero(hid, hand=None, hp=20):
    return {"id": hid, "name": hid.upper(), "archetype": "Fighter", "hp": hp, "power": 3,
            "hand_size": len(hand or []), "identity": ["W", "U", "B", "R", "G"],
            "attack_mode": "melee", "row": "front", "library": hand or []}


def _enemy():
    # A slow, harmless body: the fight must outlast the round under test.
    return {"id": "orc", "name": "Orc", "hp": 40, "level": 1, "row": "front",
            "intent": {"name": "Wait", "amount": 0, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _wound_spell(toughness):
    """A turn-scoped −0/−N aimed at a party member."""
    return {"id": "sap", "name": "Sap", "source_name": "sap", "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {},
            "effects": [{"kind": "pump", "power": 0, "toughness": -toughness,
                         "target": {"mode": "chosen", "side": "ally", "targeted": True}}],
            "validated": True}


def _cast_on(st, target_id):
    cast = next(a for a in legal_actions(st)
                if a.kind == "cast" and a.target_id == target_id)
    st, _ = apply_action(st, cast)
    while st.stack and st.result is None:
        st, _ = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))
    return st


def _party():
    # The seeded turn order opens on b; b holds the free wound and aims it at c.
    return {"party": [_hero("a"), _hero("b", hand=[_wound_spell(25)]), _hero("c")],
            "enemies": [_enemy()]}


def test_a_turn_scoped_wound_downs_the_hero_at_once():
    st = state_from_dict(_party(), seed=1)
    gauge_before = {c.id: c.ultimate_gauge for c in st.party}
    st = _cast_on(st, "c")
    c = st.character("c")
    assert c.effective_hp <= 0 and c.hp == 20      # only the wound put c down
    assert not c.alive                             # incapacitated on the spot
    # §4.3: each other standing hero is paid the downing gauge.
    assert st.character("a").ultimate_gauge > gauge_before["a"]


def test_the_hero_stands_back_up_when_the_wound_expires():
    st = state_from_dict(_party(), seed=1)
    st = _cast_on(st, "c")
    assert not st.character("c").alive
    _end_step(st)                                  # the End step: turn-scoped layers lapse
    c = st.character("c")
    assert c.alive and c.effective_hp == 20        # back up, at the HP it never lost
    assert st.result is None


def test_a_hero_still_at_zero_after_the_wound_lifts_stays_down():
    st = state_from_dict(_party(), seed=1)
    st = _cast_on(st, "c")
    st.character("c").hp = 0                        # real damage taken meanwhile
    _end_step(st)
    assert not st.character("c").alive             # the expiring wound hands back nothing
