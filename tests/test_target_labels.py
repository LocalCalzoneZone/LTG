"""Per-site effect labels for the targeting popup (`cast_target_labels`).

A multi-target card (e.g. Agony Warp's two independent wounds) names each pick so
the UI shows "choose target to weaken −3/−0 (1 of 2)" instead of the ambiguous
"target 1 / target 2". A single-target card names its one site too.
"""

from ltg_core.schema import Card
from ltg_combat.engine import cast_target_labels
from ltg_combat.state import Action, CharacterState, GameState


def _card(**kw):
    base = {"id": "x", "name": "x", "source_name": "x", "rarity": "common",
            "level": 2, "type": "Instant", "timing": "instant"}
    base.update(kw)
    return Card.model_validate(base)


def _state_with(card):
    actor = CharacterState(id="ys", name="Ys", max_hp=10, hp=10, power=1,
                           hand_size=0, identity=list("UB"), hand=[card])
    return GameState(party=[actor], enemies=[])


def _labels(card, mode=None):
    st = _state_with(card)
    return cast_target_labels(st, Action("cast", "ys", card_id=card.id, mode=mode))


def test_agony_warp_names_each_wound_site():
    # Two independent slot-targeted wounds: −3/−0 then −0/−3.
    card = _card(name="Agony Warp", cost={"generic": 0, "colors": {"U": 1, "B": 1}},
                 effects=[
                     {"kind": "wound", "power": 3, "toughness": 0, "target": "$T1", "duration": "this_turn"},
                     {"kind": "wound", "power": 0, "toughness": 3, "target": "$T2", "duration": "this_turn"},
                 ],
                 targets={"T1": {"mode": "chosen", "side": "any", "targeted": True},
                          "T2": {"mode": "chosen", "side": "any", "targeted": True}})
    assert _labels(card) == ["weaken −3/−0", "weaken −0/−3"]


def test_single_target_damage_names_its_site():
    card = _card(name="Zap", cost={"generic": 1, "colors": {"U": 1}},
                 effects=[{"kind": "deal_damage", "amount": 3,
                           "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])
    assert _labels(card) == ["deal 3 damage"]


def test_untargeted_cast_has_no_site_labels():
    card = _card(name="Opt", cost={"generic": 0, "colors": {"U": 1}},
                 effects=[{"kind": "draw", "amount": 1}])
    assert _labels(card) == []


def test_non_cast_action_has_no_labels():
    st = _state_with(_card(name="x"))
    assert cast_target_labels(st, Action("attack", "ys", target_id="e1")) == []
