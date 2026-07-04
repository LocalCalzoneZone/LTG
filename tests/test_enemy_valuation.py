"""Design Update 04 §F-7.2 — the target-valuation brain: reachable candidates ranked
finishable → channel-breakable → role value → lowest HP → deterministic tiebreak.

A component with `target_rule="valuation"` declares against this ranking; the tests
read the target the enemy telegraphs (via `settle`)."""

from __future__ import annotations

from ltg_combat.engine import settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Channel, Component
from ltg_core.schema import Card, DealDamage, t_chosen


def _char(cid, hp=10, power=2, attack_mode="melee", row="front"):
    return {"id": cid, "name": cid, "hp": hp, "power": power, "hand_size": 0,
            "identity": ["U"], "row": row, "attack_mode": attack_mode, "library": []}


def _ranged_enemy(eid="e"):
    # Ranged so reachability never confounds the ranking (it hits any row).
    return {"id": eid, "name": eid, "hp": 30, "level": 3,
            "intent": {"name": "Shot", "amount": 2, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party",
                       "mode": "ranged"}}


def _burst(dmg=3):
    return Component(id="burst", archetype="Burst", priority=30,
                     verbs=[DealDamage(amount=dmg, target=t_chosen("ally", targeted=True))],
                     target_rule="valuation", telegraph="Burst")


def _channel_card():
    return Card.model_validate({"id": "ch", "name": "Focus", "source_name": "Focus",
                                "rarity": "common", "level": 1, "type": "Enchantment",
                                "timing": "channeled", "effects": []})


def _target(st):
    return settle(st).enemies[0].intent.target_id


# 1. Finishable — kill the biggest target you can, not just any low one.
def test_finishable_prefers_highest_hp_kill():
    def tweak(s):
        s.enemies[0].components.append(_burst(dmg=3))
    st = state_from_dict({"party": [_char("a", hp=2), _char("b", hp=3)],
                          "enemies": [_ranged_enemy()]})
    tweak(st)
    assert _target(st) == "b"        # both ≤3; take the higher-HP kill


# 2. Channel-breakable — when nothing is finishable, break the exposed channeler.
def test_channel_breakable_when_nothing_finishable():
    def tweak(s):
        s.enemies[0].components.append(_burst(dmg=6))   # 25% of 20 = 5, 6 ≥ 5 → break
        chan = s.character("chan")
        chan.channels.append(Channel(card=_channel_card(), holder_id="chan"))
    st = state_from_dict({"party": [_char("chan", hp=20), _char("other", hp=10)],
                          "enemies": [_ranged_enemy()]})
    tweak(st)
    assert _target(st) == "chan"     # neither is finishable (10,20 > 6) → break the channel


# 3. Role value — a caster/support over a wounded frontliner when neither is finishable.
def test_role_value_prefers_the_channeler():
    def tweak(s):
        s.enemies[0].components.append(_burst(dmg=3))
        s.character("caster").channels.append(Channel(card=_channel_card(), holder_id="caster"))
    st = state_from_dict({"party": [_char("caster", hp=12), _char("front", hp=8)],
                          "enemies": [_ranged_enemy()]})
    tweak(st)
    # dmg 3: no one finishable, no channel-break (3 < 25% of 12); role value ranks the
    # channeler (support) above the melee frontliner despite its higher HP.
    assert _target(st) == "caster"


# 4. Lowest HP within a role, deterministic tiebreak.
def test_lowest_hp_within_role():
    def tweak(s):
        s.enemies[0].components.append(_burst(dmg=3))
    st = state_from_dict({"party": [_char("a", hp=8), _char("b", hp=5), _char("c", hp=12)],
                          "enemies": [_ranged_enemy()]})
    tweak(st)
    assert _target(st) == "b"        # all melee; none finishable → lowest effective HP
