"""Roadmap M1.29: small fixes pinned — the display Mitigate value keeps the
engine's floor of 1, "drain" is not a verb, and the infect gloss describes
§D22-2 poison counters."""

from __future__ import annotations

from ltg_combat import engine, serialize
from ltg_combat.scenario import state_from_dict
from ltg_core.schema import KEYWORDS


def _hero(power):
    st = state_from_dict({
        "party": [{"id": "p", "name": "p", "hp": 20, "power": power, "hand_size": 0,
                   "identity": ["U"], "row": "front", "attack_mode": "melee", "library": []}],
        "enemies": [{"id": "e", "name": "e", "hp": 5, "level": 1, "power": 1}]})
    return st.character("p")


def test_the_display_mitigate_value_matches_the_engine_at_zero_power():
    p = _hero(0)
    assert serialize._mitigate_value(p) == engine._mitigate_value(p) == 1


def test_drain_is_not_a_damage_kind_because_it_is_not_a_verb():
    assert "drain" not in engine.RESOLVERS
    assert engine._DAMAGE_KINDS <= set(engine.RESOLVERS)


def test_the_infect_gloss_describes_poison_counters():
    gloss = KEYWORDS["infect"]["gloss"]
    assert "poison counter" in gloss and "−0/−1" not in gloss


def test_the_server_reports_the_deckbuilder_port(monkeypatch):
    """Roadmap M1.36: the client's Edit link and the pair-wide Quit follow the
    host's LTG_DECKBUILDER_PORT, not a hard-coded 8000."""
    from ltg_game_server import appctl
    monkeypatch.setattr(appctl, "DECKBUILDER_PORT", 8123)
    assert appctl.info() == {"deckbuilder_port": 8123}
