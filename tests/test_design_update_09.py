"""Design Update 09 — Tier Two: corpses & necromancy (§D9-1), stances (§D9-2),
forced movement & row blasts (§D9-3), and the boss endgame (§D9-4).

Engine behaviour is driven through the two-function contract, exactly like the
Update-08 suite."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Component
from ltg_core.schema import Card, Control, t_chosen

CHOSEN_ENEMY_T = {"mode": "chosen", "side": "enemy", "targeted": True}
CHOSEN_ALLY_T = {"mode": "chosen", "side": "ally", "targeted": True}
CORPSE_T = {"mode": "chosen", "side": "enemy", "targeted": True, "state": "corpse"}
ANY_STATE_T = {"mode": "chosen", "side": "enemy", "targeted": True, "state": "any"}
SELF = {"mode": "self"}


def _card(cid, name, timing, cost, effects, level=1):
    return {"id": cid, "name": name, "source_name": name, "rarity": "common",
            "level": level, "type": "Spell", "timing": timing, "cost": cost,
            "effects": effects, "validated": True}


def _char(cid, power=3, hp=30, hand=0, library=None, identity=None, row="front",
          attack_mode="melee"):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": hand,
            "identity": identity or ["U"], "row": row, "attack_mode": attack_mode,
            "library": library or []}


def _enemy(eid, hp=10, amount=2, level=3, row="front", **extra):
    return {"id": eid, "name": eid, "hp": hp, "level": level, "row": row,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "melee"}, **extra}


def _state(party, enemies, tweak=None, tokens=None):
    spec = {"party": party, "enemies": enemies}
    if tokens:
        spec["tokens"] = tokens
    st = state_from_dict(spec)
    if tweak:
        tweak(st)
    return st


def _do(st, kind, **match):
    """Apply the first legal action of `kind` matching the given fields."""
    for a in legal_actions(st):
        if a.kind != kind:
            continue
        if all(getattr(a, k) == v for k, v in match.items()):
            return apply_action(st, a)[0]
    raise AssertionError(f"no legal '{kind}' action ({match}) among "
                         f"{[a.label for a in legal_actions(st)]}")


def _has(st, kind, **match):
    return any(a.kind == kind and all(getattr(a, k) == v for k, v in match.items())
               for a in legal_actions(st))


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


def _bolt(cid="bolt", amount=10):
    return _card(cid, "Bolt", "sorcery", {"colors": {"U": 1}},
                 [{"kind": "deal_damage", "amount": amount, "target": CHOSEN_ENEMY_T}])


# Plain descriptors, no `state` authoring: the corpse-legal verbs offer corpses
# alongside the living BY DEFAULT (§D9-1.2/§D9-1.4) — cards never opt in.
def _banish(cid="banish"):
    return _card(cid, "Banish", "sorcery", {"colors": {"U": 1}},
                 [{"kind": "exile", "target": CHOSEN_ENEMY_T}])


def _dominate(cid="dominate", turns=None):
    eff = {"kind": "control", "target": CHOSEN_ENEMY_T}
    if turns is not None:
        eff["turns"] = turns
    return _card(cid, "Dominate", "sorcery", {"colors": {"U": 1}}, [eff])


# ========================================================================== #
# §D9-1.1 / §D9-1.2 — the corpse rule, destroy vs exile
# ========================================================================== #
def test_death_by_damage_leaves_a_corpse_on_its_row():
    st = _state([_char("p", hand=1, library=[_bolt()])],
                [_enemy("e", hp=3, row="mid"), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="e")
    st = _do(st, "pass")
    assert st.enemy("e") is None
    corpse = st.corpse("e")
    assert corpse is not None and corpse.row == "mid"
    assert corpse.max_hp == 3 and corpse.stirring == 0


def test_destroy_leaves_a_corpse_but_exile_leaves_none():
    unmake = _card("unmake", "Unmake", "sorcery", {"colors": {"U": 1}},
                   [{"kind": "destroy", "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", hand=2, library=[unmake, _banish()], identity=["U", "U"])],
                [_enemy("a", hp=5), _enemy("b", hp=5), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="unmake", target_id="a")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="banish", target_id="b")
    st = _do(st, "pass")
    assert st.corpse("a") is not None      # destroyed → corpse
    assert st.corpse("b") is None          # exiled → no corpse, ever
    # Exile fires no death triggers (§D9-1.2): no enemy_died event for b.
    assert not any(ev.type == "enemy_died" and ev.data.get("enemy") == "b"
                   for ev in st.log)
    assert any(ev.type == "enemy_died" and ev.data.get("enemy") == "a"
               for ev in st.log)


def test_corpses_are_defeated_victory_is_unchanged():
    st = _state([_char("p", hand=1, library=[_bolt()])], [_enemy("e", hp=3)])
    st = _do(st, "cast", card_id="bolt", target_id="e")
    st = _do(st, "pass")
    assert st.result == "victory"
    assert st.corpse("e") is not None      # the fight ends over a field of bodies


def test_tokens_never_leave_corpses():
    swarm = Component(id="spawn", archetype="Swarm", priority=10, cooldown=9,
                      verbs=[], target_rule="self", telegraph="Spawn")
    from ltg_core.schema import CreateToken
    swarm.verbs = [CreateToken(token_id="husk", count=1, hp=1, power=1)]
    st = _state([_char("p", hand=1, library=[_bolt()])],
                [_enemy("mother", hp=20)],
                tweak=lambda s: s.enemy("mother").components.append(swarm))
    st = _drive_turn(st)  # mother spawns a husk token
    husk = next((e for e in st.enemies if e.created_by == "mother"), None)
    assert husk is not None
    st = _do(st, "cast", card_id="bolt", target_id=husk.id)
    st = _do(st, "pass")
    assert st.corpse(husk.id) is None      # tokens never leave corpses


def test_exile_burns_a_corpse_off_the_battlefield():
    st = _state([_char("p", hand=2, library=[_bolt(), _banish()],
                       identity=["U", "U"])],
                [_enemy("e", hp=3), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="e")
    st = _do(st, "pass")
    assert st.corpse("e") is not None
    st = _do(st, "cast", card_id="banish", target_id="e")
    st = _do(st, "pass")
    assert st.corpse("e") is None          # burned — nothing to raise


def test_living_verbs_never_offer_corpses_as_targets():
    st = _state([_char("p", hand=2, library=[_bolt("bolt1", 3), _bolt("bolt2", 3)],
                       identity=["U", "U"])],
                [_enemy("e", hp=3), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt1", target_id="e")
    st = _do(st, "pass")
    assert st.corpse("e") is not None
    assert not _has(st, "cast", card_id="bolt2", target_id="e")


# ========================================================================== #
# §D9-1.3 — schema: the state axis and is_dead
# ========================================================================== #
def test_schema_rejects_living_verbs_on_corpses():
    with pytest.raises(ValidationError):
        Card.model_validate(_card("x", "X", "sorcery", {},
                                  [{"kind": "deal_damage", "amount": 2,
                                    "target": CORPSE_T}]))


def test_schema_control_requires_enemy_side():
    with pytest.raises(ValidationError):
        Card.model_validate(_card("x", "X", "sorcery", {},
                                  [{"kind": "control", "target": CHOSEN_ALLY_T}]))


def test_is_dead_conditional_renders_the_condition():
    # The card text must NAME the condition — "If the target is dead, …" — not
    # collapse it into an opaque "that qualifies".
    from ltg_core.schema import Conditional
    from ltg_core.translation import render_effects
    eff = Conditional.model_validate(
        {"kind": "conditional",
         "condition": {"kind": "target_property", "property": "is_dead"},
         "effects": [{"kind": "deal_damage", "amount": 1, "target": CHOSEN_ENEMY_T}]})
    text = render_effects([eff])
    assert text.startswith("If the target is dead (a corpse), ")
    assert "qualifies" not in text


def test_corpse_state_narrows_the_pick_to_corpses_only():
    # An authored `state: "corpse"` (Raise Dead) offers ONLY corpses — no living pick.
    raise_dead = _card("raise", "Raise Dead", "sorcery", {"colors": {"U": 1}},
                       [{"kind": "control", "target": CORPSE_T}])
    st = _state([_char("p", hand=2, library=[_bolt(), raise_dead],
                       identity=["U", "U"])],
                [_enemy("husk", hp=3), _enemy("wall", hp=20)])
    assert not _has(st, "cast", card_id="raise")     # no corpse yet — uncastable
    st = _do(st, "cast", card_id="bolt", target_id="husk")
    st = _do(st, "pass")
    assert _has(st, "cast", card_id="raise", target_id="husk")
    assert not _has(st, "cast", card_id="raise", target_id="wall")


def test_is_dead_conditional_reads_the_resolved_target():
    # "…if the target is dead, do X instead": exile a corpse and draw a card.
    # No `state` authoring — the conditional is the corpse-facing pattern.
    reap = _card("reap", "Reap", "sorcery", {"colors": {"U": 1}},
                 [{"kind": "exile", "target": CHOSEN_ENEMY_T},
                  {"kind": "conditional",
                   "condition": {"kind": "target_property", "property": "is_dead"},
                   "effects": [{"kind": "draw", "amount": 1, "target": SELF}]}])
    st = _state([_char("p", hand=2,
                       library=[_bolt(), reap, _bolt("later", 1), _bolt("later2", 1),
                                _bolt("later3", 1)],
                       identity=["U", "U"])],
                [_enemy("e", hp=3), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="e")
    st = _do(st, "pass")
    hand_before = len(st.character("p").hand)
    st = _do(st, "cast", card_id="reap", target_id="e")  # e is now a corpse
    st = _do(st, "pass")
    assert st.corpse("e") is None
    assert len(st.character("p").hand) == hand_before  # cast −1, drew +1


# ========================================================================== #
# §D9-1.4 — control: mind control
# ========================================================================== #
def test_mind_control_moves_the_enemy_to_the_party_side():
    st = _state([_char("p", hand=1, library=[_dominate()])],
                [_enemy("brute", hp=8, amount=4), _enemy("wall", hp=20)],
                tweak=lambda s: s.enemy("brute").keywords.update({"trample": ""}))
    st = _do(st, "cast", card_id="dominate", target_id="brute")
    st = _do(st, "pass")
    assert st.enemy("brute") is None
    ctl = next(t for t in st.tokens if t.controlled_by == "p")
    assert ctl.hp == 8 and ctl.power == 4 and "trample" in ctl.keywords
    assert ctl.revert is not None
    # It is NOT defeated — the fight can't be won while it stands controlled.
    assert st.result is None


def test_controlled_enemy_attacks_the_closest_enemy_in_the_ally_step():
    st = _state([_char("p", hand=1, library=[_dominate()])],
                [_enemy("brute", hp=8, amount=4),
                 _enemy("wall", hp=20, row="front"),
                 _enemy("archer", hp=3, row="rear")])
    st = _do(st, "cast", card_id="dominate", target_id="brute")
    st = _do(st, "pass")
    st = _drive_turn(st)
    # The controlled melee brute struck the closest (front) enemy, not the archer.
    assert st.enemy("wall").hp == 16
    assert st.enemy("archer").hp == 3


def test_turn_bound_control_snaps_back_at_the_end_step():
    st = _state([_char("p", hand=1, library=[_dominate(turns=1)])],
                [_enemy("brute", hp=8, amount=4), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="dominate", target_id="brute")
    st = _do(st, "pass")
    ctl = next(t for t in st.tokens if t.controlled_by == "p")
    ctl.hp = 5  # damage it took while yours stays (§D9-1.4)
    st = _drive_turn(st)
    brute = st.enemy("brute")
    assert brute is not None and brute.alive
    assert brute.hp == 5
    assert not any(t.controlled_by == "p" for t in st.tokens)


def test_control_never_wins():
    st = _state([_char("p", hand=2, library=[_dominate(), _bolt()],
                       identity=["U", "U"])],
                [_enemy("a", hp=8), _enemy("b", hp=3)])
    st = _do(st, "cast", card_id="dominate", target_id="a")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="bolt", target_id="b")
    st = _do(st, "pass")
    # b is dead; a is controlled — every enemy defeated EXCEPT the controlled one:
    # all control ends immediately and the fight continues.
    assert st.result is None
    assert st.enemy("a") is not None and st.enemy("a").alive
    assert not any(t.controlled_by == "p" for t in st.tokens)


def test_bosses_are_never_control_targets():
    st = _state([_char("p", hand=1, library=[_dominate()])],
                [_enemy("boss", hp=30, is_boss=True), _enemy("wall", hp=20)])
    assert not _has(st, "cast", card_id="dominate", target_id="boss")
    assert _has(st, "cast", card_id="dominate", target_id="wall")


def test_hexproof_blocks_targeted_control_of_the_living():
    st = _state([_char("p", hand=1, library=[_dominate()])],
                [_enemy("slippery", hp=8), _enemy("wall", hp=20)],
                tweak=lambda s: s.enemy("slippery").keywords.update({"hexproof": ""}))
    assert not _has(st, "cast", card_id="dominate", target_id="slippery")


# ========================================================================== #
# §D9-1.4 — control: raise dead
# ========================================================================== #
def test_raise_dead_consumes_the_corpse_and_raises_an_undead_ally():
    st = _state([_char("p", hand=2, library=[_bolt(), _dominate()],
                       identity=["U", "U"])],
                [_enemy("ogre", hp=9, amount=3, row="mid"), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="ogre")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="dominate", target_id="ogre")
    st = _do(st, "pass")
    assert st.corpse("ogre") is None                       # consumed
    undead = next(t for t in st.tokens if t.controlled_by == "p")
    assert undead.hp == 4 and undead.max_hp == 4           # half of 9, floor (T-52)
    assert undead.power == 3 and undead.row == "mid"
    assert undead.revert is None                           # crumbles, never returns


def test_raised_undead_crumbles_when_the_duration_ends_and_leaves_no_corpse():
    st = _state([_char("p", hand=2, library=[_bolt(), _dominate(turns=1)],
                       identity=["U", "U"])],
                [_enemy("ogre", hp=9), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="ogre")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="dominate", target_id="ogre")
    st = _do(st, "pass")
    st = _drive_turn(st)
    assert not any(t.controlled_by == "p" for t in st.tokens)  # crumbled
    assert st.corpse("ogre") is None                           # tokens leave none
    assert st.enemy("ogre") is None                            # and it stays down


# ========================================================================== #
# §D9-1.5 — rises: the stirring corpse
# ========================================================================== #
def test_rises_enemy_revives_after_its_upkeeps_at_half_hp():
    st = _state([_char("p", hand=1, library=[_bolt()])],
                [_enemy("thrall", hp=8, rises=2), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="thrall")
    st = _do(st, "pass")
    corpse = st.corpse("thrall")
    assert corpse is not None and corpse.stirring == 2
    st = _drive_turn(st)                     # upkeep 1: still stirring
    assert st.corpse("thrall") is not None
    assert st.enemy("thrall") is None
    st = _drive_turn(st)                     # upkeep 2: it rises
    thrall = st.enemy("thrall")
    assert thrall is not None and thrall.hp == 4     # half of 8 (T-52)
    assert st.corpse("thrall") is None
    assert thrall.rises is None                       # once per encounter


def test_stirring_corpse_blocks_victory_until_exiled():
    st = _state([_char("p", hand=2, library=[_bolt(), _banish()],
                       identity=["U", "U"])],
                [_enemy("thrall", hp=6, rises=2)])
    st = _do(st, "cast", card_id="bolt", target_id="thrall")
    st = _do(st, "pass")
    assert st.result is None                 # stirring — not defeated
    st = _do(st, "cast", card_id="banish", target_id="thrall")
    st = _do(st, "pass")
    assert st.result == "victory"            # exile defeats it on the spot


def test_raising_a_stirring_corpse_cancels_the_rise():
    st = _state([_char("p", hand=2, library=[_bolt(), _dominate()],
                       identity=["U", "U"])],
                [_enemy("thrall", hp=8, rises=2), _enemy("wall", hp=20)])
    st = _do(st, "cast", card_id="bolt", target_id="thrall")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="dominate", target_id="thrall")
    st = _do(st, "pass")
    assert st.corpse("thrall") is None
    assert any(t.controlled_by == "p" for t in st.tokens)   # the body is yours now
    st = _drive_turn(st)
    st = _drive_turn(st)
    assert st.enemy("thrall") is None                        # no rise


# ========================================================================== #
# §D9-1.6 — the enemy necromancer
# ========================================================================== #
def _necromancer():
    return Component(
        id="raise", archetype="Necromancy", priority=20, cooldown=2,
        action_type="spell",
        verbs=[Control(target=t_chosen("enemy", targeted=True).model_copy(
            update={"state": "corpse"}))],
        target_rule="corpse", telegraph="Raise the Fallen")


def test_necromancer_raises_a_fallen_minion_as_an_enemy_token():
    st = _state([_char("p", hp=40, hand=1, library=[_bolt()])],
                [_enemy("husk", hp=3, amount=1), _enemy("necro", hp=12, amount=1)],
                tweak=lambda s: s.enemy("necro").components.append(_necromancer()))
    st = _do(st, "cast", card_id="bolt", target_id="husk")
    st = _do(st, "pass")
    assert st.corpse("husk") is not None
    st = _drive_turn(st)   # this round the necro attacks (declared pre-corpse)
    st = _drive_turn(st)   # next round it raises the fallen husk
    risen = next((e for e in st.enemies if e.created_by == "necro"), None)
    assert risen is not None
    assert st.corpse("husk") is None
    assert risen.hp == 1   # half of 3, floor, min 1 (T-52)


def test_corpse_burst_consumes_the_corpse_and_blasts_a_row():
    from ltg_core.schema import DealDamage, Exile, TargetDescriptor
    burst = Component(
        id="burst", archetype="Burst", priority=15, cooldown=3,
        verbs=[Exile(target=TargetDescriptor.model_validate(CORPSE_T)),
               DealDamage(amount=3, target=TargetDescriptor.model_validate(
                   {"mode": "all", "side": "ally", "rows": ["front"]}))],
        target_rule="corpse", telegraph="Corpse-burst")
    st = _state([_char("p", hp=40, hand=1, library=[_bolt()], row="front"),
                 _char("mage", hp=20, row="rear", attack_mode="ranged")],
                [_enemy("husk", hp=3, amount=1), _enemy("burster", hp=12, amount=1)],
                tweak=lambda s: s.enemy("burster").components.append(burst))
    st = _do(st, "cast", card_id="bolt", target_id="husk")
    st = _do(st, "pass")
    st = _do(st, "pass")   # both heroes pass — the bolt resolves
    assert st.corpse("husk") is not None
    st = _drive_turn(st)   # round 1: burster attacked (intent pre-dates the corpse)
    st = _drive_turn(st)   # round 2: it eats the corpse and blasts the front row
    assert st.corpse("husk") is None
    assert st.character("mage").hp == 20          # rear row untouched by the row hit
    assert any(ev.type == "exiled" and ev.data.get("corpse") for ev in st.log)


def test_enemy_exile_of_living_heroes_is_rejected():
    with pytest.raises(Exception):
        _state([_char("p")],
               [_enemy("e", hp=5, components=[{
                   "id": "banish", "archetype": "Debilitate", "timing": "proactive",
                   "verbs": [{"kind": "exile", "target": CHOSEN_ALLY_T}]}])])


def test_snapshot_ships_corpses_control_chips_and_two_boss_lines():
    from ltg_game_server.snapshot import build_snapshot
    st = _state([_char("p", hand=2, library=[_bolt(), _dominate()],
                       identity=["U", "U"])],
                [_enemy("boss", hp=40, amount=3, is_boss=True),
                 _enemy("husk", hp=3), _enemy("wall", hp=20)])
    boss = st.enemy("boss")
    boss.hp = 8
    boss.enraged = True
    st = _do(st, "cast", card_id="bolt", target_id="husk")
    st = _do(st, "pass")
    st = _do(st, "cast", card_id="dominate", target_id="wall")
    st = _do(st, "pass")
    snap = build_snapshot(st, {"p"})
    assert [c["id"] for c in snap["corpses"]] == ["husk"]
    tok = next(t for t in snap["tokens"] if t["control_kind"] == "dominated")
    assert tok["controlled_by"] == "p"
    boss_lines = [it for it in snap["intents"] if it["enemy_id"] == "boss"]
    assert [it["slot"] for it in boss_lines] == [1, 2]   # fury: two veiled lines


def test_necromancer_with_no_corpse_falls_through_to_its_attack():
    st = _state([_char("p", hp=40)],
                [_enemy("necro", hp=12, amount=2)],
                tweak=lambda s: s.enemy("necro").components.append(_necromancer()))
    st = settle(st)
    assert st.enemy("necro").intent is not None
    assert st.enemy("necro").intent.name != "Raise the Fallen"


# ========================================================================== #
# §D9-2 — stances
# ========================================================================== #
def _stance_card(cid="trance", attack="unchanged", defend="unchanged",
                 mitigate="unchanged", move="unchanged"):
    return _card(cid, "Trance", "channeled", {"colors": {"U": 1}},
                 [{"kind": "stance", "attack": attack, "defend": defend,
                   "mitigate": mitigate, "move": move}])


SOOTHE = {"name": "Soothing Palm",
          "effects": [{"kind": "heal", "amount": 3, "target": CHOSEN_ALLY_T}]}


def test_stance_removed_attack_is_gone_and_replaced_defend_is_offered():
    st = _state([_char("p", hp=30, hand=1,
                       library=[_stance_card(attack="removed", defend=SOOTHE)])],
                [_enemy("e", hp=10)])
    st = _do(st, "cast", card_id="trance")
    st = _do(st, "pass")
    st = _drive_turn(st)  # to turn 2 — the proactive slot is fresh again
    p = st.character("p")
    p.hp = 10
    acts = legal_actions(st)
    assert not any(a.kind == "attack" for a in acts)          # removed is total
    assert not any(a.kind == "defend" for a in acts)          # replaced, not added
    st = _do(st, "stance_ability", card_id="defend", target_id="p")
    st = _do(st, "pass")
    p = st.character("p")
    assert p.hp == 13                                          # Soothing Palm healed 3
    assert p.acted_mode == "defend" and p.used_defend          # the slot's economy


def test_stance_removed_move_denies_the_haste_free_move_too():
    st = _state([_char("p", hand=1, library=[_stance_card(move="removed")])],
                [_enemy("e", hp=10)],
                tweak=lambda s: s.party[0].keywords.update({"haste": "encounter"}))
    st = _do(st, "cast", card_id="trance")
    st = _do(st, "pass")
    assert not any(a.kind == "move" for a in legal_actions(st))


def test_one_stance_at_a_time():
    st = _state([_char("p", hand=2, identity=["U", "U"],
                       library=[_stance_card("t1", attack="removed"),
                                _stance_card("t2", move="removed")])],
                [_enemy("e", hp=10)])
    st = _do(st, "cast", card_id="t1")
    st = _do(st, "pass")
    assert not _has(st, "cast", card_id="t2")   # casting a second is illegal
    st = _do(st, "drop_channels", card_id="t1")
    assert _has(st, "cast", card_id="t2")       # dropping frees the slot (and mana)


def test_breaking_the_stance_channel_restores_the_abilities():
    st = _state([_char("p", hp=8, hand=1, library=[_stance_card(attack="removed")])],
                [_enemy("e", hp=10, amount=4)])  # 4 ≥ 25% of 8 — a breaking hit
    st = _do(st, "cast", card_id="trance")
    st = _do(st, "pass")
    assert not any(a.kind == "attack" for a in legal_actions(st))
    st = _drive_turn(st)                        # the enemy's hit breaks the channel
    p = st.character("p")
    assert p.channels == []
    assert any(a.kind == "attack" for a in legal_actions(st))


def test_replaced_mitigate_fires_in_the_attack_window_instead_of_reducing():
    counter_heal = {"name": "Turn the Blow",
                    "effects": [{"kind": "heal", "amount": 2, "target": SELF}]}
    st = _state([_char("p", hp=20, hand=1,
                       library=[_stance_card(mitigate=counter_heal)])],
                [_enemy("e", hp=10, amount=4)])
    st = _do(st, "cast", card_id="trance")
    st = _do(st, "pass")
    st = _do(st, "end_turn")
    # The enemy attack is on the stack: the replacement reacts in that window.
    assert st.stack and st.stack[-1].kind == "attack"
    p = st.character("p")
    p.hp = 15
    assert not any(a.kind == "mitigate" for a in legal_actions(st))
    st = _do(st, "stance_ability", card_id="mitigate")
    # Once per turn: not offered again while the window is still open.
    assert not _has(st, "stance_ability", card_id="mitigate")
    st = _do(st, "pass")   # replacement resolves (heal 2)
    st = _do(st, "pass")   # then the attack resolves, UNREDUCED
    p = st.character("p")
    assert p.hp == 15 + 2 - 4


def test_counter_replaced_mitigate_answers_a_non_attack_enemy_action():
    """A mitigate replacement whose authored effect is a COUNTER ("cancel an
    enemy action") reacts to any enemy top its filter matches — not only
    attacks. The old attack-only gate hid it against a spell/ability top,
    which collapsed the window to pass-only (and auto-pass then drained it)."""
    flash = {"name": "Blinding Flash",
             "effects": [{"kind": "counter", "filter": "action",
                          "target": {"class": "action", "side": "enemy"}}]}
    st = _state([_char("p", hp=20, hand=1, library=[_stance_card(mitigate=flash)])],
                [_enemy("e", hp=10,
                        intent={"name": "Dark Chant", "amount": 6,
                                "action_type": "ability", "intent_type": "ability",
                                "targeting": "lowest_hp_party", "mode": "melee"})])
    st = _do(st, "cast", card_id="trance")
    st = _do(st, "pass")
    st = _do(st, "end_turn")
    # The enemy ability is on the stack — NOT an attack.
    assert st.stack and st.stack[-1].kind == "ability"
    uid = st.stack[-1].uid
    # The counter replacement is offered against it and cancels it.
    st = _do(st, "stance_ability", card_id="mitigate", target_id=f"#{uid}")
    st = _do(st, "pass")
    assert not any(s.uid == uid for s in st.stack)
    assert st.character("p").hp == 20       # the chant never landed


def test_stance_attack_replacement_satisfies_the_proactive_choice():
    smite = {"name": "Radiant Smite",
             "effects": [{"kind": "deal_damage", "amount": 2, "target": CHOSEN_ENEMY_T}]}
    st = _state([_char("p", hp=40, hand=1, library=[_stance_card(attack=smite)])],
                [_enemy("e", hp=12)])
    st = _do(st, "cast", card_id="trance")
    st = _do(st, "pass")
    st = _drive_turn(st)  # to turn 2 — the proactive slot is fresh again
    st = _do(st, "stance_ability", card_id="attack", target_id="e")
    st = _do(st, "pass")
    assert st.enemy("e").hp == 10
    p = st.character("p")
    assert p.used_attack and p.acted_mode == "attack"
    # Once per round: not offered again.
    assert not _has(st, "stance_ability", card_id="attack")


def test_stance_is_rejected_on_non_channeled_cards_and_enemy_verbs():
    with pytest.raises(ValidationError):
        Card.model_validate(_card("x", "X", "sorcery", {},
                                  [{"kind": "stance", "attack": "removed"}]))
    with pytest.raises(Exception):
        _state([_char("p")],
               [_enemy("e", hp=5, components=[{
                   "id": "s", "archetype": "Debilitate", "timing": "proactive",
                   "verbs": [{"kind": "stance", "attack": "removed"}]}])])


# ========================================================================== #
# §D9-3.1 — forced movement
# ========================================================================== #
def _shove(cid="shove", direction="back", side="enemy"):
    return _card(cid, "Shove", "instant", {"colors": {"U": 1}},
                 [{"kind": "move", "direction": direction,
                   "target": {"mode": "chosen", "side": side, "targeted": True}}])


def test_forced_move_is_immediate_current_and_committed():
    st = _state([_char("p", hand=1, library=[_shove()])],
                [_enemy("bruiser", hp=10)])
    st = _do(st, "cast", card_id="shove", target_id="bruiser")
    st = _do(st, "pass")
    b = st.enemy("bruiser")
    assert b.row == "mid" and b.committed == "mid"   # the body moves NOW


def test_shoving_the_wall_opens_melee_reach_this_turn():
    st = _state([_char("p", hand=1, library=[_shove()])],
                [_enemy("wall", hp=10, row="front"),
                 _enemy("artillery", hp=4, row="rear")])
    # Before the shove, melee reaches only the front wall.
    assert not _has(st, "attack", target_id="artillery")
    st = _do(st, "cast", card_id="shove", target_id="wall")
    st = _do(st, "pass")
    st.enemy("wall").row = st.enemy("wall").committed = "rear"  # push it all the way
    assert _has(st, "attack", target_id="artillery")            # the wall is open


def test_forced_move_never_invalidates_a_declared_intent():
    st = _state([_char("p", hand=1, library=[_shove(direction="to_rear")])],
                [_enemy("biter", hp=10, amount=3)])
    st = settle(st)
    assert st.enemy("biter").intent is not None      # melee attack declared
    st = _do(st, "cast", card_id="shove", target_id="biter")
    st = _do(st, "pass")
    assert st.enemy("biter").row == "rear"
    hp_before = st.character("p").hp
    st = _drive_turn(st)
    assert st.character("p").hp == hp_before - 3     # it lunges — the hit lands


def test_bosses_can_be_shoved():
    st = _state([_char("p", hand=1, library=[_shove()])],
                [_enemy("boss", hp=30, is_boss=True), _enemy("wall", hp=10)])
    st = _do(st, "cast", card_id="shove", target_id="boss")
    st = _do(st, "pass")
    assert st.enemy("boss").row == "mid"             # affects in place → works


def test_forward_from_front_is_a_noop():
    st = _state([_char("p", hand=1, library=[_shove(direction="forward")])],
                [_enemy("e", hp=10, row="front")])
    st = _do(st, "cast", card_id="shove", target_id="e")
    st = _do(st, "pass")
    assert st.enemy("e").row == "front"


def test_enemy_hooker_drags_a_hero_to_the_front():
    from ltg_core.schema import Move as MoveEffect
    hooker = Component(
        id="hook", archetype="Debilitate", priority=10, cooldown=2,
        verbs=[MoveEffect(direction="to_front",
                          target=t_chosen("ally", targeted=True))],
        target_rule="valuation", telegraph="The Hook")
    st = _state([_char("mage", hp=20, row="rear", attack_mode="ranged")],
                [_enemy("hooker", hp=10, amount=1)],
                tweak=lambda s: s.enemy("hooker").components.append(hooker))
    st = _drive_turn(st)
    mage = st.character("mage")
    assert mage.row == "front" and mage.committed == "front"


# ========================================================================== #
# §D9-3.2 — row-scoped area targeting
# ========================================================================== #
def _row_nuke(cid="nuke", rows=("front",), amount=3):
    return _card(cid, "Nuke", "sorcery", {"colors": {"U": 1}},
                 [{"kind": "deal_damage", "amount": amount,
                   "target": {"mode": "all", "side": "enemy", "rows": list(rows)}}])


def _blast(cid="blast", scope="blast", amount=2):
    return _card(cid, "Blast", "sorcery", {"colors": {"U": 1}},
                 [{"kind": "deal_damage", "amount": amount,
                   "target": {"mode": "chosen", "side": "enemy", "targeted": True,
                              "scope": scope}}])


def test_rows_filter_hits_only_the_named_rows():
    st = _state([_char("p", hand=1, library=[_row_nuke()])],
                [_enemy("f", hp=10, row="front"), _enemy("m", hp=10, row="mid"),
                 _enemy("r", hp=10, row="rear")])
    st = _do(st, "cast", card_id="nuke")
    st = _do(st, "pass")
    assert st.enemy("f").hp == 7
    assert st.enemy("m").hp == 10 and st.enemy("r").hp == 10


def test_row_scope_splashes_the_picked_creatures_row_only():
    st = _state([_char("p", hand=1, library=[_blast(scope="row")])],
                [_enemy("a", hp=10, row="front"), _enemy("b", hp=10, row="front"),
                 _enemy("c", hp=10, row="mid")])
    st = _do(st, "cast", card_id="blast", target_id="a")
    st = _do(st, "pass")
    assert st.enemy("a").hp == 8 and st.enemy("b").hp == 8
    assert st.enemy("c").hp == 10


def test_blast_on_mid_catches_everything_front_and_rear_are_not_adjacent():
    st = _state([_char("p", hand=2, identity=["U", "U"],
                       library=[_blast("b1"), _blast("b2")])],
                [_enemy("f", hp=10, row="front"), _enemy("m", hp=10, row="mid"),
                 _enemy("r", hp=10, row="rear")])
    st = _do(st, "cast", card_id="b1", target_id="m")   # mid: adjacent to both
    st = _do(st, "pass")
    assert (st.enemy("f").hp, st.enemy("m").hp, st.enemy("r").hp) == (8, 8, 8)
    st = _do(st, "cast", card_id="b2", target_id="f")   # front: catches front+mid
    st = _do(st, "pass")
    assert (st.enemy("f").hp, st.enemy("m").hp, st.enemy("r").hp) == (6, 6, 8)


def test_channeled_scoped_exile_suspends_the_whole_row_and_returns_it():
    # "While channeled: exile the chosen target and its whole row" (Ys's
    # Elsewhere shape). A CHANNELED scoped effect covers the pick PLUS its
    # §D9-3.2 splash — the victims are pinned as the channel starts, so the
    # SAME creatures are lifted when it ends (suspended creatures sit off the
    # living lists meanwhile, and row moves must not change the set).
    elsewhere = _card("elsewhere", "Elsewhere", "channeled", {"colors": {"U": 1}},
                      [{"kind": "exile", "duration": "while_channeled",
                        "target": {"mode": "chosen", "side": "any", "targeted": True,
                                   "scope": "row"}}])
    st = _state([_char("p", hand=1, library=[elsewhere])],
                [_enemy("a", hp=10, row="front"), _enemy("b", hp=10, row="front"),
                 _enemy("c", hp=10, row="mid")])
    st = _do(st, "cast", card_id="elsewhere", target_id="a")
    st = _do(st, "pass")
    assert st.enemy("a").exiled and st.enemy("b").exiled  # the pick AND its row-mate
    assert not st.enemy("c").exiled                       # mid row untouched
    st = _do(st, "drop_channels", card_id="elsewhere")    # ending it returns the SET
    assert not st.enemy("a").exiled and not st.enemy("b").exiled


def test_hexproof_shelters_the_pick_but_not_the_splash():
    st = _state([_char("p", hand=1, library=[_blast(scope="row")])],
                [_enemy("slick", hp=10, row="front"),
                 _enemy("open", hp=10, row="front")],
                tweak=lambda s: s.enemy("slick").keywords.update({"hexproof": ""}))
    # The hexproof creature can't be the PICK…
    assert not _has(st, "cast", card_id="blast", target_id="slick")
    st = _do(st, "cast", card_id="blast", target_id="open")
    st = _do(st, "pass")
    # …but it IS caught incidentally by the splash (the trample-carry precedent).
    assert st.enemy("slick").hp == 8
    assert st.enemy("open").hp == 8


def test_whole_effect_fizzles_when_the_pick_dies_in_response():
    zap = _card("zap", "Zap", "instant", {"colors": {"U": 1}},
                [{"kind": "deal_damage", "amount": 10, "target": CHOSEN_ENEMY_T}])
    st = _state([_char("p", hp=30, hand=2, identity=["U", "U"],
                       library=[_blast("blast", scope="row", amount=2), zap])],
                [_enemy("a", hp=3, row="front"), _enemy("b", hp=10, row="front")])
    st = _do(st, "cast", card_id="blast", target_id="a")
    st = _do(st, "cast", card_id="zap", target_id="a")   # respond: kill the pick
    st = _do(st, "pass")   # zap resolves, a dies…
    st = _do(st, "pass")   # …then the blast fizzles wholesale
    assert st.enemy("b").hp == 10                          # no pick, no blast


# ========================================================================== #
# §D9-4 — the boss endgame: two intents post-enrage
# ========================================================================== #
def _fury_state(hand_cards=None, identity=None):
    boss = _enemy("boss", hp=40, amount=3, is_boss=True)
    st = _state([_char("p", hp=40, hand=len(hand_cards or []),
                       library=list(hand_cards or []), identity=identity)],
                [boss, _enemy("wall", hp=20, amount=1)])

    def enrage(s):
        b = s.enemy("boss")
        b.hp = 8            # ≤25% of max — the execute window
        b.enraged = True
    enrage(st)
    return st


def test_enraged_boss_declares_and_executes_two_intents():
    st = _fury_state()
    view = settle(st)
    boss = view.enemy("boss")
    assert boss.intent is not None and boss.intent2 is not None   # two lines
    hp0 = view.character("p").hp
    st = _drive_turn(st)
    # Both boss intents executed in declaration order (3 + 3), plus the wall's 1.
    assert st.character("p").hp == hp0 - 3 - 3 - 1


def test_stun_suppresses_one_of_the_two_intents():
    stun = _card("daze", "Daze", "sorcery", {"colors": {"U": 1}},
                 [{"kind": "stun", "target": CHOSEN_ENEMY_T}])
    st = _fury_state(hand_cards=[stun])
    st = _do(st, "cast", card_id="daze", target_id="boss")
    st = _do(st, "pass")
    hp0 = st.character("p").hp
    st = _drive_turn(st)   # round 1's already-declared intents still land (6 + 1)
    hp1 = st.character("p").hp
    assert hp1 == hp0 - 3 - 3 - 1
    view = settle(st)
    boss = view.enemy("boss")
    # Next round: the stun suppressed ONE declaration — one intent, not zero.
    assert boss.intent is not None and boss.intent2 is None
    assert boss.round_intent2_status == "stunned"
    st = _drive_turn(st)
    assert st.character("p").hp == hp1 - 3 - 1   # boss's single 3 + the wall's 1


def test_strip_removes_one_chosen_intent_of_two():
    strip = _card("unravel", "Unravel", "instant", {"colors": {"U": 1}},
                  [{"kind": "strip_intent", "target": CHOSEN_ENEMY_T}])
    st = _fury_state(hand_cards=[strip])
    # The legal-action expansion offers one strip per declared intent (§D9-4).
    assert _has(st, "cast", card_id="unravel", target_id="boss")
    assert _has(st, "cast", card_id="unravel", target_id="boss::2")
    hp0 = settle(st).character("p").hp
    st = _do(st, "cast", card_id="unravel", target_id="boss::2")
    st = _do(st, "pass")
    boss = settle(st).enemy("boss")
    assert boss.intent is not None and boss.intent2 is None
    assert boss.round_intent2_status == "stripped"
    st = _drive_turn(st)
    # Only the surviving first intent (3) and the wall's 1 landed.
    assert st.character("p").hp == hp0 - 3 - 1
