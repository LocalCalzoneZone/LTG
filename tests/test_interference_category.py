"""The `interference` veiled-intent category (§D8-1.2) and the party-size
lockdown budget.

Lockdown effects take away what a hero can DO rather than their HP, and the
answers are different — you dodge a swing, you cannot dodge a Silence. They get
their own telegraph word ("moves to foil X") instead of wearing "threatens X"
or, worse, "turns its attention to X", which read as support.
"""

from __future__ import annotations

import pytest

from ltg_combat.serialize import intent_category, _veiled_line
from ltg_core.schema import (DealDamage, Heal, ModifyAction, Prevent, Sap, Stun,
                             Taunt, MoveCard, t_all, t_chosen, t_self)
from ltg_combat.state import Intent


def _intent(effects, action_type="ability", **kw):
    return Intent(name="X", action_type=action_type, effects=effects,
                  target_id=kw.pop("target_id", "p"), **kw)


def _party(**kw):
    return t_chosen("ally", targeted=True, **kw)


# --------------------------------------------------------------------------- #
# What classifies as interference
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("effect", [
    Stun(target=_party()),
    Taunt(target=_party()),
    Sap(amount=2, target=_party()),
    ModifyAction(action="skill", modifier="lock_skill", target=_party()),
    ModifyAction(action="ultimate", modifier="drain_ultimate", amount=20,
                 target=_party()),
    Prevent(parameter="cast", target=_party()),                    # Silence
    Prevent(parameter="attack", target=_party()),                  # Pacifism
    MoveCard(count=1, source="hand", destination="graveyard",
             target=_party()),                                     # forced discard
])
def test_lockdown_verbs_read_as_interference(effect):
    assert intent_category(_intent([effect])) == "interference"


@pytest.mark.parametrize("effect", [
    DealDamage(amount=5, target=_party()),
    Sap(amount=1, target=_party()),
])
def test_damage_still_outranks_lockdown_in_a_mixed_intent(effect):
    """A mixed intent classifies by its FIRST hostile verb, so "deal 5 and stun"
    stays a threat — the damage is the part you have to answer first."""
    intent = _intent([DealDamage(amount=5, target=_party()), Stun(target=_party())])
    assert intent_category(intent) == "threat"


def test_a_lockdown_verb_after_a_charge_still_reads_as_gathering():
    """The windup dominates the fiction — unchanged by the new category."""
    from ltg_core.schema import Charge
    intent = _intent([Charge(amount=1, target=t_self()), Stun(target=_party())])
    assert intent_category(intent) == "gathering"


# --------------------------------------------------------------------------- #
# What does NOT
# --------------------------------------------------------------------------- #
def test_an_enemy_ward_on_itself_is_still_support():
    """`prevent` is side-sensitive: a shield on its OWN body is a Ward, and
    calling that 'interference' would tell the player they are being locked down
    when the enemy is actually turtling."""
    intent = _intent([Prevent(parameter="combat_damage", target=t_self())],
                     target_id=None)
    assert intent_category(intent) == "support"


def test_a_heal_is_still_support():
    assert intent_category(_intent([Heal(amount=3, target=t_self())],
                                   target_id=None)) == "support"


def test_plain_damage_is_still_a_threat():
    assert intent_category(_intent([DealDamage(amount=4, target=_party())])) == "threat"


def test_a_party_wide_blast_is_still_a_party_assault():
    intent = _intent([DealDamage(amount=3, target=t_all("ally"))], target_id=None)
    assert intent_category(intent) == "party assault"


def test_a_party_wide_lockdown_is_interference_not_an_assault():
    """Shape does not override kind here: a party-wide Hamstring is not an
    'assault on your whole party' — that wording would send the player reaching
    for a damage answer."""
    intent = _intent([ModifyAction(action="skill", modifier="lock_skill",
                                   target=t_all("ally"))], target_id=None)
    assert intent_category(intent) == "interference"


# --------------------------------------------------------------------------- #
# The telegraph line
# --------------------------------------------------------------------------- #
class _Enemy:
    id = "e"
    name = "The Cutter"


def test_the_line_names_the_target():
    line = _veiled_line(_Enemy(), "interference", "p", "Soren", "declared")
    assert line == "The Cutter moves to foil Soren."


def test_an_untargeted_lockdown_names_the_party():
    line = _veiled_line(_Enemy(), "interference", None, None, "declared")
    assert line == "The Cutter moves to foil your party."


def test_a_stunned_enemy_still_reports_the_stun():
    line = _veiled_line(_Enemy(), "interference", "p", "Soren", "stunned")
    assert "reels" in line


# --------------------------------------------------------------------------- #
# The party-size lockdown budget
# --------------------------------------------------------------------------- #
def test_the_lockdown_budget_grows_with_the_party():
    """The playtest complaint: standard difficulty felt too easy, and it got
    easier the bigger the party, because a bigger party had proportionally more
    action economy to spare."""
    from ltg_game_server.llm import _lockdown_budget
    budgets = [_lockdown_budget(size, "standard") for size in (1, 2, 3, 4)]
    assert budgets == sorted(budgets), "must never shrink as the party grows"
    assert budgets[0] == 0, "a solo hero has no slack to take"
    assert budgets[-1] >= 3, "a four-hero party should face real lockdown"


def test_difficulty_shifts_the_lockdown_budget():
    from ltg_game_server.llm import _lockdown_budget
    for size in (2, 3, 4):
        easy = _lockdown_budget(size, "easy")
        standard = _lockdown_budget(size, "standard")
        hard = _lockdown_budget(size, "hard")
        assert easy < standard < hard
    assert _lockdown_budget(1, "easy") == 0        # never negative


def test_the_budget_reaches_the_generated_prompt():
    """It is worth nothing unless the model is actually told the number."""
    from ltg_game_server.llm import _request_block
    party = {"size": 4, "avg_level": 3.0,
             "members": [{"name": f"h{i}", "level": 3, "colors": ["U"]}
                         for i in range(4)]}
    block = _request_block(party, "standard", "")
    assert "LOCKDOWN BUDGET" in block
    assert 'layouts["4"]' in block
