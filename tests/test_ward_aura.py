"""The ward-aura contract: the snapshot tells a client which damage shields are
standing on each combatant, so a warded card can show it (see WardAura.tsx).

The distinction that matters here is that `prevent` covers two unrelated things.
The DAMAGE lanes (combat / spell / all) guard a creature — those are wards. The
ACTION shields (`prevent attack` = Pacifism, `prevent cast` = Silence) BIND a
creature instead, and must never be reported as protection it does not have."""

from __future__ import annotations

from ltg_combat.scenario import state_from_dict
from ltg_combat.state import PreventTag, ProtectionTag, TokenState
from ltg_game_server.snapshot import build_snapshot


def _state():
    st = state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 2, "hand_size": 0,
                   "identity": ["W"], "row": "front", "library": []}],
        "enemies": [{"id": "ogre", "name": "Ogre", "hp": 12, "power": 2, "level": 2,
                     "row": "front",
                     "intent": {"name": "Bash", "amount": 2, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })
    st.tokens.append(TokenState(id="wisp", name="Wisp", max_hp=3, hp=3, power=1))
    return st


def _snap(st):
    return build_snapshot(st, {"p"})


def _wards_of(snap, kind, cid):
    return next(c["wards"] for c in snap[kind] if c["id"] == cid)


def test_a_card_with_no_shield_reports_an_empty_list():
    snap = _snap(_state())
    assert _wards_of(snap, "characters", "p") == []
    assert _wards_of(snap, "creatures", "ogre") == []
    assert _wards_of(snap, "tokens", "wisp") == []


def test_a_prevent_shield_reports_its_lane_kind_and_clock():
    """Unbending Resolve — "prevent all damage this turn": every matching hit
    until the End step, so `uses` is None."""
    st = _state()
    st.character("p").prevent_tags.append(PreventTag("all_damage", None, "all"))
    assert _wards_of(_snap(st), "characters", "p") == [
        {"lane": "all", "kind": "prevent", "reach": "all", "uses": None}]


def test_an_n_shot_shield_carries_its_remaining_uses():
    """Soothing Verse — "prevent the NEXT combat damage": a one-shot."""
    st = _state()
    st.character("p").prevent_tags.append(PreventTag("combat_damage", 1, "all"))
    assert _wards_of(_snap(st), "characters", "p") == [
        {"lane": "combat", "kind": "prevent", "reach": "all", "uses": 1}]


def test_a_combat_shield_keeps_its_reach():
    st = _state()
    st.character("p").prevent_tags.append(PreventTag("combat_damage", None, "ranged"))
    assert _wards_of(_snap(st), "characters", "p")[0]["reach"] == "ranged"


def test_protection_charges_are_reported_one_per_charge():
    """A protection charge has no clock — it waits until something matching is
    negated — so each charge is its own entry and the client counts them."""
    st = _state()
    st.character("p").protection_tags.extend(
        [ProtectionTag("spell_damage", "all"), ProtectionTag("spell_damage", "all")])
    wards = _wards_of(_snap(st), "characters", "p")
    assert wards == [{"lane": "spell", "kind": "protection", "reach": "all", "uses": 1}] * 2


def test_an_action_shield_is_never_a_ward():
    """Pacifism and Silence bind the creature rather than guard it: a ward aura
    on a silenced enemy would advertise protection it does not have."""
    st = _state()
    st.character("p").prevent_tags.extend(
        [PreventTag("attack", None, "all"), PreventTag("cast", None, "all")])
    assert _wards_of(_snap(st), "characters", "p") == []
    # …and the player can still SEE the bind — it stays in the status tags.
    tags = next(c["status_tags"] for c in _snap(st)["characters"] if c["id"] == "p")
    assert "pacified" in tags and "silenced" in tags


def test_a_bound_creature_that_is_also_warded_reports_only_the_ward():
    st = _state()
    st.character("p").prevent_tags.extend(
        [PreventTag("cast", None, "all"), PreventTag("spell_damage", None, "all")])
    assert _wards_of(_snap(st), "characters", "p") == [
        {"lane": "spell", "kind": "prevent", "reach": "all", "uses": None}]


def test_enemies_and_tokens_carry_wards_too():
    """Both sides of the table: the aura reads the same on an enemy card."""
    st = _state()
    st.enemy("ogre").prevent_tags.append(PreventTag("spell_damage", None, "all"))
    st.enemy("ogre").protection_tags.append(ProtectionTag("all_damage", "all"))
    st.tokens[0].prevent_tags.append(PreventTag("combat_damage", 2, "melee"))
    snap = _snap(st)
    assert _wards_of(snap, "creatures", "ogre") == [
        {"lane": "spell", "kind": "prevent", "reach": "all", "uses": None},
        {"lane": "all", "kind": "protection", "reach": "all", "uses": 1}]
    assert _wards_of(snap, "tokens", "wisp") == [
        {"lane": "combat", "kind": "prevent", "reach": "melee", "uses": 2}]
