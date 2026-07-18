"""R-11 prevent-parameter matching against the two damage lanes (Update 11):
`prevent combat_damage` (Holy Day / Fog) stops the PHYSICAL lane — basic attacks
AND activated/component-ability damage (an enemy's "Slash"/"Claw" is narratively
an attack) — but not the ARCANE lane (spell / triggered damage), which
`prevent spell_damage` answers; `all_damage` blanks both. When a standing shield
doesn't match, the engine logs why the hit landed (the playtest-confusion fix)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import DealDamage, Heal, t_chosen, t_self

_FOG = {"id": "holy_day", "name": "Holy Day", "source_name": "Holy Day",
        "rarity": "common", "level": 1, "type": "Instant", "timing": "instant",
        "cost": {"generic": 0, "colors": {}},
        "effects": [{"kind": "prevent", "parameter": "combat_damage", "uses": "all",
                     "target": {"mode": "all", "side": "ally"},
                     "duration": "this_turn"}],
        "validated": True}


def _drain(action_type="ability"):
    return Component(id="leech", archetype="Drain", timing="proactive",
                     priority=30, cooldown=2, target_rule="valuation",
                     telegraph="Life Leech — deal 3, heal 3",
                     action_type=action_type,
                     verbs=[DealDamage(amount=3, target=t_chosen("ally", targeted=True)),
                            Heal(amount=3, target=t_self())])


def _state(components=None, intent_amount=3):
    st = state_from_dict({
        "party": [{"id": "ys", "name": "Ys", "hp": 10, "power": 2, "hand_size": 1,
                   "identity": ["W"], "row": "front", "attack_mode": "melee",
                   "library": [dict(_FOG)]}],
        "enemies": [{"id": "sov", "name": "Sovereign", "hp": 20, "level": 4,
                     "intent": {"name": "Swipe", "amount": intent_amount,
                                "action_type": "ability", "intent_type": "attack",
                                "targeting": "lowest_hp_party", "mode": "ranged"}}],
    })
    st.enemies[0].components.extend(components or [])  # runtime Components
    return st


def _run_until_enemy_acted(st):
    """Cast Holy Day on turn 1, end the turn, pass every reaction window, and stop
    once turn 2's player phase arrives (the turn-1 enemy action has resolved)."""
    while not (st.turn >= 2 and st.phase == "player" and not st.stack):
        acts = legal_actions(st)
        if not acts or st.result is not None:
            break
        a = (next((x for x in acts if x.kind == "cast" and x.card_id == "holy_day"), None)
             or next((x for x in acts if x.kind == "pass"), None)
             or next((x for x in acts if x.kind == "end_turn"), None)
             or acts[0])
        st = apply_action(st, a)[0]
    return st


def test_fog_stops_the_basic_attack():
    st = _run_until_enemy_acted(_state())          # enemy has only its basic attack
    assert st.character("ys").hp == 10             # the swing was prevented
    assert any(ev.type == "prevented" for ev in st.log if hasattr(ev, "type"))


def test_fog_now_stops_drain_ability_damage_too():
    """Update 11: combat_damage covers the physical lane — attacks AND
    activated/component abilities (a Drain's "Life Leech" is narratively an
    attack), so the Holy Day shield stops it."""
    st = _run_until_enemy_acted(_state(components=[_drain()]))
    # The Drain outranks the basic attack (priority 30 < 90); its ability damage
    # is now caught by the combat_damage shield.
    assert st.character("ys").hp == 10
    assert any(ev.type == "prevented" for ev in st.log if hasattr(ev, "type"))


def test_fog_does_not_stop_spell_damage_and_says_why():
    """A spell-classed component ("Fireball") is the ARCANE lane: it goes
    through a combat_damage shield, and the log explains why."""
    st = _run_until_enemy_acted(_state(components=[_drain(action_type="spell")]))
    assert st.character("ys").hp == 7
    note = [ev for ev in st.log if ev.type == "not_prevented"]
    assert note, "expected the shield-mismatch explanation in the log"
    assert note[0].data.get("damage_kind") == "spell"
    assert "combat_damage" in note[0].data.get("shields", [])


# --------------------------------------------------------------------------- #
# One vocabulary: the UI tag names the damage lane (spell | attack | ability).
# An ability NEVER wears its owner's melee/ranged reach — that dressed a ranged
# enemy's Drain as "(ranged)" and made it read as an attack.
# --------------------------------------------------------------------------- #
def test_action_mode_vocabulary():
    from ltg_combat.serialize import action_mode
    assert action_mode("attack", "ranged") == "ranged attack"
    assert action_mode("attack", "melee") == "melee attack"
    assert action_mode("attack", None) == "melee attack"      # default reach
    assert action_mode("spell", "ranged") == "spell"          # reach never leaks
    assert action_mode("ability", "ranged") == "ability"      # the Life Leech case
    assert action_mode("ability", "melee") == "ability"


def test_stack_row_tags_drain_as_ability_not_ranged():
    """Drive the ranged Sovereign's Drain onto the stack and read the row the UI
    renders: it must say 'ability', never the owner's reach."""
    from ltg_combat.serialize import _stack_list
    st = _state(components=[_drain()])
    # Advance until the enemy's action sits on the stack (the reaction window).
    while not st.stack:
        acts = legal_actions(st)
        if not acts:
            break
        a = (next((x for x in acts if x.kind == "end_turn"), None) or acts[0])
        st = apply_action(st, a)[0]
    rows = _stack_list(st)
    leech = next(r for r in rows if "Life Leech" in r["label"])
    assert leech["mode"] == "ability"
    assert leech["kind"] == "ability"
