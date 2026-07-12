"""Balance Update 11 — the Skill as an activated ability (action economy +
channeled skills), the prevent damage-lane rework, combo primers (`amplify`,
the `*_last_damage` refs), spell multipliers (`copy_spell`, `double_next`),
enemy-schema legality for all of it, and the global enemy Power bump."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import AmplifyTag, Component
from ltg_core.schema import Card, Character, Prevent, effect_specs, t_chosen
from ltg_core.translation import render_effects

CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}
CHOSEN_ALLY_T = {"mode": "chosen", "side": "ally", "targeted": True}
SELF = {"mode": "self"}


def _card(cid, name, timing, cost, effects, level=1):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": level, "type": "Spell", "timing": timing, "cost": cost,
            "effects": effects, "validated": True}


def _char(cid, power=3, hp=30, hand=0, library=None, identity=None):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": identity or ["U"], "row": "front",
            "attack_mode": "melee", "library": library or []}


def _drive_turn(st):
    """End turns / pass windows until the turn counter advances or the game ends."""
    turn = st.turn
    while st.result is None and st.turn == turn:
        acts = legal_actions(st)
        if not acts:
            break
        act = next((a for a in acts if a.kind in ("end_turn", "pass")), acts[0])
        st = apply_action(st, act)[0]
    return st


def _enemy(eid, hp=10, amount=2, level=3):
    return {"id": eid, "name": eid, "hp": hp, "level": level,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}}


def _state(party, enemies, tweak=None):
    st = state_from_dict({"party": party, "enemies": enemies})
    if tweak:
        tweak(st)
    return st


def _do(st, kind, **match):
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal '{kind}' action ({match}) among "
                         f"{[a.label for a in legal_actions(st)]}")


# ========================================================================== #
# The Skill as an activated ability (channeled form)
# ========================================================================== #
def test_channeled_skill_starts_a_channel():
    """A channeled Skill (the skill-stance enabler) starts a held channel on
    resolution instead of firing once."""
    skill = Card.model_validate(_card(
        "skl", "Iron Focus", "channeled", {},
        [{"kind": "pump", "power": 1, "toughness": 0,
          "duration": "while_channeled", "target": SELF}]))

    def wire(s):
        s.character("p").skill = skill
    st = _state([_char("p")], [_enemy("e")], tweak=wire)
    st = _do(st, "use_skill")
    st = _do(st, "pass")
    p = st.character("p")
    assert p.skill_used and p.acted_mode == "skill"
    assert [ch.card.id for ch in p.channels] == ["skl"]
    assert p.current_power == 4                       # the aura holds


def test_skill_may_be_a_stance():
    """A channeled Skill may carry a stance — schema-legal, and the stance
    rewires the holder's abilities while the skill-channel holds."""
    skill = Card.model_validate(_card(
        "skl", "Duelist Form", "channeled", {},
        [{"kind": "stance", "attack": "removed"}]))

    def wire(s):
        s.character("p").skill = skill
    st = _state([_char("p")], [_enemy("e")], tweak=wire)
    st = _do(st, "use_skill")
    st = _do(st, "pass")
    assert [ch.card.id for ch in st.character("p").channels] == ["skl"]
    # On the holder's NEXT turn (action unspent) the stance still removes the
    # basic attack — the skill-channel holds the stance.
    st = _drive_turn(st)
    assert st.character("p").acted_mode is None
    assert not any(a.kind == "attack" for a in legal_actions(st))
    assert any(a.kind == "end_turn" for a in legal_actions(st))


def test_skill_stance_replacement_with_shared_slot_targets_and_lands():
    """The 'Resonate' regression: a channeled Skill carrying a channel_start
    amplify AND a stance whose attack replacement aims at a shared slot ($T1).
    The replaced attack must enumerate real targets (the slot's side resolves
    via the stance's card) and its damage must land."""
    skill = Card.model_validate({
        **_card("res", "Resonate", "channeled", {}, []),
        "effects": [
            {"kind": "amplify", "event": "spell_damage", "multiplier": 2,
             "target": SELF, "trigger": "channel_start"},
            {"kind": "stance",
             "attack": {"name": "Crystal darts",
                        "effects": [{"kind": "deal_damage",
                                     "amount": {"ref": "caster_power"},
                                     "target": "$T1"}]}},
        ],
        "targets": {"T1": {"mode": "chosen", "side": "any", "targeted": True}},
    })

    def wire(s):
        s.character("p").skill = skill
    st = _state([_char("p", power=3)], [_enemy("e", hp=20)], tweak=wire)
    st = _do(st, "use_skill")
    st = _do(st, "pass")
    p = st.character("p")
    # The channel holds, its channel_start amplify fired, the stance is on.
    assert [ch.card.id for ch in p.channels] == ["res"]
    assert [t.event for t in p.amplify_tags] == ["spell_damage"]
    # Next turn: the replaced attack is offered WITH a real enemy target…
    st = _drive_turn(st)
    darts = [a for a in legal_actions(st)
             if a.kind == "stance_ability" and a.card_id == "attack"]
    assert darts and any(a.target_id == "e" for a in darts)
    # …and it lands for the caster's Power (not silently fizzling).
    st = _do(st, "stance_ability", card_id="attack", target_id="e")
    st = _do(st, "pass")
    assert st.enemy("e").hp == 17
    # It resolved as the replacement — it did NOT restart the channel.
    assert len(st.character("p").channels) == 1
    # The spell_damage priming is untouched (an activated ability is the
    # combat lane, not the spell lane).
    assert [t.event for t in st.character("p").amplify_tags] == ["spell_damage"]


def test_instant_skill_is_rejected_in_schema():
    """The schema coerces a legacy instant skill to sorcery — no skill is ever
    instant-speed after Update 11."""
    ch = Character(name="X", colors=["U"], starting_mana=["U"],
                   skill=_card("s", "Trick", "instant", {},
                               [{"kind": "draw", "amount": 1, "target": SELF}]))
    assert ch.skill.timing.value == "sorcery"


# ========================================================================== #
# Prevent: the damage-lane dropdown vocabulary
# ========================================================================== #
def test_prevent_parameter_is_a_closed_vocabulary():
    with pytest.raises(ValidationError):
        Prevent(parameter="_combat_damage", target=t_chosen("ally"))
    with pytest.raises(ValidationError):
        Prevent(parameter="everything", target=t_chosen("ally"))


def test_prevent_legacy_spellings_normalise():
    assert Prevent(parameter="damage", target=t_chosen("ally")).parameter == "all_damage"
    assert Prevent(parameter="all", target=t_chosen("ally")).parameter == "all_damage"


def test_prevent_editor_spec_is_a_dropdown():
    spec = effect_specs()["prevent"]
    param = next(p for p in spec["params"] if p["name"] == "parameter")
    assert param["control"] == "enum"
    assert set(param["options"]) == {"combat_damage", "spell_damage",
                                     "all_damage", "attack"}


def test_all_damage_blanks_both_lanes():
    from ltg_combat.engine import _prevent_match
    for kind in ("attack", "ability", "activated", "spell", "triggered"):
        assert _prevent_match("all_damage", kind)
    assert _prevent_match("combat_damage", "activated")
    assert _prevent_match("combat_damage", "ability")
    assert not _prevent_match("combat_damage", "spell")
    assert not _prevent_match("combat_damage", "triggered")
    assert _prevent_match("spell_damage", "spell")
    assert _prevent_match("spell_damage", "triggered")
    assert not _prevent_match("spell_damage", "attack")


# ========================================================================== #
# Amplify — the combo primer
# ========================================================================== #
def _prime_card(event="combat_damage", multiplier=2, bonus=0):
    return _card("prime", "War Cry", "sorcery", {},
                 [{"kind": "amplify", "event": event, "multiplier": multiplier,
                   "bonus": bonus, "target": SELF}])


def test_amplify_doubles_the_next_combat_damage_once():
    st = _state([_char("p", power=3, hand=1, library=[_prime_card()])],
                [_enemy("e", hp=20)])
    st = _do(st, "cast", card_id="prime")
    st = _do(st, "pass")
    p = st.character("p")
    assert [t.event for t in p.amplify_tags] == ["combat_damage"]
    # Vigilance-free: cast then attack is illegal, so prime on turn 1 and
    # swing on turn 2 — the tag HOLDS across turns (a primed combo keeps).
    st = _drive_turn(st)
    st = _do(st, "attack")
    st = _do(st, "pass")
    assert st.enemy("e").hp == 20 - 6            # 3 Power ×2
    assert not st.character("p").amplify_tags    # one-shot: spent
    # The next swing is back to normal (no lingering multiplier).


def test_amplify_flat_bonus_and_spell_lane():
    boost = _card("bolt", "Bolt", "instant", {},
                  [{"kind": "deal_damage", "amount": 2, "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", hand=2,
                       library=[_prime_card(event="spell_damage", multiplier=1,
                                            bonus=3), boost])],
                [_enemy("e", hp=20)])
    st = _do(st, "cast", card_id="prime")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="bolt")
    st = _do(st, "pass")
    assert st.enemy("e").hp == 20 - (2 + 3)      # flat +3 on the spell lane


def test_spell_amplify_does_not_touch_the_basic_attack():
    def preprime(s):
        s.character("p").amplify_tags.append(
            AmplifyTag(event="spell_damage", multiplier=2))
    st = _state([_char("p", power=3)], [_enemy("e", hp=20)], tweak=preprime)
    st = _do(st, "attack")
    st = _do(st, "pass")
    assert st.enemy("e").hp == 17                # unamplified: wrong lane
    assert st.character("p").amplify_tags        # still primed


def test_amplify_heal_doubles_the_next_heal():
    mend = _card("mend", "Mend", "instant", {},
                 [{"kind": "heal", "amount": 3, "target": SELF}])
    st = _state([_char("p", hp=30, hand=1, library=[mend])], [_enemy("e")],
                tweak=lambda s: (
                    setattr(s.character("p"), "hp", 10),
                    s.character("p").amplify_tags.append(
                        AmplifyTag(event="heal", multiplier=2))))
    st = _do(st, "cast", card_id="mend")
    st = _do(st, "pass")
    assert st.character("p").hp == 16            # 3 ×2 = 6 restored
    assert not st.character("p").amplify_tags


def test_last_damage_refs_power_retroactive_combos():
    """'Heal an amount equal to the last damage you took.'"""
    salve = _card("salve", "Blood Debt", "sorcery", {},
                  [{"kind": "heal", "amount": {"ref": "caster_last_damage"},
                    "target": SELF}])

    def hit(s):
        p = s.character("p")
        p.hp = 20
        p.last_damage_taken = 7
    st = _state([_char("p", hp=30, hand=1, library=[salve])],
                [_enemy("e", amount=7)], tweak=hit)
    st = _do(st, "cast", card_id="salve")
    st = _do(st, "pass")
    assert st.character("p").hp == 27            # healed the last blow taken


def test_deal_damage_records_last_damage_taken():
    st = _state([_char("p", power=4)], [_enemy("e", hp=20)])
    st = _do(st, "attack")
    st = _do(st, "pass")
    assert st.enemy("e").last_damage_taken == 4


# ========================================================================== #
# Spell multipliers: copy_spell and double_next
# ========================================================================== #
def test_copy_spell_copies_and_the_copier_assigns_the_target():
    bolt = _card("bolt", "Bolt", "sorcery", {},
                 [{"kind": "deal_damage", "amount": 3, "target": CHOSEN_ENEMY_T}])
    mirror = _card("mirror", "Twincast", "instant", {},
                   [{"kind": "copy_spell"}])
    st = _state([_char("p", hand=2, library=[bolt, mirror])],
                [_enemy("e1", hp=10), _enemy("e2", hp=10)])
    st = _do(st, "cast", card_id="bolt", target_id="e1")
    # In the bolt's own window: copy it (the copy targets the spell on the stack).
    copy_act = next(a for a in legal_actions(st)
                    if a.kind == "cast" and a.card_id == "mirror")
    st = apply_action(st, copy_act)[0]
    st = _do(st, "pass")     # the mirror resolves; the copy needs a target pick
    assert st.pending_choice is not None and st.pending_choice.kind == "target"
    pick = next(a for a in legal_actions(st)
                if a.kind == "choose_target" and a.target_id == "e2")
    st = apply_action(st, pick)[0]
    # Pass out the windows; copy then original resolve.
    while st.stack:
        st = _do(st, "pass")
    assert st.enemy("e2").hp == 7                # the copy, re-aimed
    assert st.enemy("e1").hp == 7                # the original


def test_double_next_makes_the_spell_resolve_twice():
    bolt = _card("bolt", "Bolt", "sorcery", {},
                 [{"kind": "deal_damage", "amount": 3, "target": CHOSEN_ENEMY_T}])
    echo = _card("echo", "Echo Chant", "sorcery", {},
                 [{"kind": "double_next", "filter": "spell", "target": SELF}])
    st = _state([_char("p", hand=2, library=[bolt, echo])],
                [_enemy("e", hp=20)])
    st = _do(st, "cast", card_id="echo")
    st = _do(st, "pass")
    assert st.character("p").double_next == ["spell"]
    st = _do(st, "cast", card_id="bolt", target_id="e")
    while st.stack:
        st = _do(st, "pass")
    assert st.enemy("e").hp == 14                # resolved twice
    assert st.character("p").double_next == []   # spent
    assert any(ev.type == "double" for ev in st.log)


def test_double_next_ability_filter_doubles_the_basic_attack():
    st = _state([_char("p", power=3)], [_enemy("e", hp=20)],
                tweak=lambda s: s.character("p").double_next.append("ability"))
    st = _do(st, "attack")
    while st.stack:
        st = _do(st, "pass")
    assert st.enemy("e").hp == 14                # the swing echoed


# ========================================================================== #
# Enemy schema: the new verbs are enemy-legal
# ========================================================================== #
def test_enemy_components_accept_the_new_verbs():
    st = state_from_dict({
        "party": [_char("p")],
        "enemies": [{
            "id": "w", "name": "Warcaller", "hp": 10, "level": 3, "power": 2,
            "components": [
                {"id": "prime", "timing": "proactive", "priority": 30,
                 "target_rule": "self", "telegraph": "War Chant",
                 "verbs": [{"kind": "amplify", "event": "combat_damage",
                            "multiplier": 2, "target": SELF}]},
                {"id": "mirror", "timing": "reactive", "trigger": "on_spell_cast",
                 "verbs": [{"kind": "copy_spell"}]},
                {"id": "chant", "timing": "proactive", "priority": 50,
                 "target_rule": "self", "telegraph": "Echo",
                 "verbs": [{"kind": "double_next", "filter": "ability",
                            "target": SELF}]},
            ]}],
    })
    assert len(st.enemies[0].components) == 3


def test_enemy_amplify_primes_its_next_swing():
    st = _state([_char("p", hp=30)],
                [_enemy("e", amount=2)],
                tweak=lambda s: s.enemies[0].amplify_tags.append(
                    AmplifyTag(event="combat_damage", multiplier=2)))
    st = _drive_turn(st)
    assert st.character("p").hp == 26            # 2 ×2 = 4
    assert not st.enemies[0].amplify_tags


# ========================================================================== #
# The global enemy Power bump (+2 / +4 boss) — the game-server balance register
# ========================================================================== #
def test_bump_enemy_power_lifts_minions_and_bosses():
    from ltg_game_server.content import _bump_enemy_power
    scenario = {"enemies": [
        {"id": "m", "name": "m", "hp": 5, "level": 1, "power": 1,
         "intent": {"name": "Claw", "amount": 1, "action_type": "ability"},
         "ranged_intent": {"name": "Spit", "amount": 1, "action_type": "ability"}},
        {"id": "b", "name": "b", "hp": 20, "level": 5, "power": 3,
         "is_boss": True},
    ]}
    out = _bump_enemy_power(scenario)
    minion, boss = out["enemies"]
    assert minion["power"] == 3                  # +2 across the board
    assert minion["intent"]["amount"] == 3       # the attack template follows
    assert minion["ranged_intent"]["amount"] == 3
    assert boss["power"] == 7                    # +4 for a boss
    # The source scenario is untouched (deep-copied).
    assert scenario["enemies"][0]["power"] == 1


def test_bumped_legacy_enemy_swings_harder_in_play():
    from ltg_game_server.content import _bump_enemy_power
    scenario = _bump_enemy_power({"enemies": [_enemy("e", amount=2)]})
    st = state_from_dict({"party": [_char("p", hp=30)],
                          "enemies": scenario["enemies"]})
    st = _drive_turn(st)
    assert st.character("p").hp == 26            # 2 (+2 bump) = 4 damage


# ========================================================================== #
# Rendering: the new effects read as card text
# ========================================================================== #
def test_render_new_effects():
    amp = Card.model_validate(_card(
        "a", "War Cry", "sorcery", {},
        [{"kind": "amplify", "event": "spell_damage", "multiplier": 2,
          "target": SELF}]))
    assert "next spell damage dealt is doubled" in render_effects(amp.effects).lower()
    dbl = Card.model_validate(_card(
        "d", "Echo", "sorcery", {},
        [{"kind": "double_next", "filter": "spell", "target": SELF}]))
    assert "resolves twice" in render_effects(dbl.effects)
    cpy = Card.model_validate(_card(
        "c", "Twincast", "instant", {}, [{"kind": "copy_spell"}]))
    assert "copy a spell" in render_effects(cpy.effects).lower()
