"""Downed characters are targetable (they stay on the battlefield — R-7
incapacitation is recoverable), and `revive` effects offer ONLY downed allies.
The playtest bug: Dawn Charm's revive mode couldn't select incapacitated Ys —
downed characters were excluded from target enumeration entirely, and would
have fizzled at resolution even if offered."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict


def _card(cid, effects, text="Choose one"):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "translated_text": text,
            "effects": effects, "validated": True}


_REVIVE = _card("raise", [{"kind": "revive", "to_fraction": 0.5,
                           "target": {"mode": "chosen", "side": "ally", "targeted": True}}])
_MEND = _card("mend", [{"kind": "heal", "amount": 5,
                        "target": {"mode": "chosen", "side": "ally", "targeted": True}}])
# A Dawn-Charm-like modal: a prevent mode + a revive mode ("choose one").
_CHARM = _card("charm", [{
    "kind": "modal",
    "modes": [
        {"label": "Shield", "effects": [{"kind": "prevent", "parameter": "combat_damage",
                                         "uses": "all", "target": {"mode": "all", "side": "ally"},
                                         "duration": "this_turn"}]},
        {"label": "Revive", "effects": [{"kind": "revive", "to_fraction": 0.5,
                                         "target": {"mode": "chosen", "side": "ally",
                                                    "targeted": True}}]},
    ]}], text="Choose one — • Shield. • Revive.")


def _state(hand, downed=True):
    st = state_from_dict({
        "party": [
            {"id": "soren", "name": "Soren", "hp": 20, "power": 3, "hand_size": len(hand),
             "identity": ["W"], "row": "front", "attack_mode": "melee", "library": hand},
            {"id": "ys", "name": "Ys", "hp": 8, "power": 2, "hand_size": 0,
             "identity": ["U"], "row": "rear", "library": []},
        ],
        "enemies": [{"id": "e", "name": "Gnasher", "hp": 12, "level": 2,
                     "intent": {"name": "Bite", "amount": 2, "action_type": "ability",
                                "intent_type": "attack", "targeting": "lowest_hp_party",
                                "mode": "melee"}}],
    })
    legal_actions(st)          # settle through upkeep
    if downed:
        st.party[1].hp = 0     # Ys is incapacitated (effective_hp 0)
    return st


def _casts(st, cid):
    return [a for a in legal_actions(st) if a.kind == "cast" and a.card_id == cid]


def test_heal_can_target_the_downed_ally():
    st = _state([dict(_MEND)])
    assert "ys" in {a.target_id for a in _casts(st, "mend")}


def test_heal_brings_the_downed_ally_back():
    st = _state([dict(_MEND)])
    act = next(a for a in _casts(st, "mend") if a.target_id == "ys")
    st = apply_action(st, act)[0]
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    assert not any(e.type == "fizzle" for e in st.log)
    assert st.character("ys").alive and st.character("ys").hp == 5


def test_revive_offers_only_downed_allies():
    st = _state([dict(_REVIVE)])
    tids = {a.target_id for a in _casts(st, "raise")}
    assert tids == {"ys"}                     # Soren (standing) is NOT offered


def test_revive_resolves_at_half_hp():
    st = _state([dict(_REVIVE)])
    st = apply_action(st, _casts(st, "raise")[0])[0]
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    ys = st.character("ys")
    assert ys.alive and ys.hp == 4            # 50% of 8


def test_charm_revive_mode_targets_the_downed_ally():
    """The Dawn Charm scenario itself: the modal's revive mode offers Ys."""
    st = _state([dict(_CHARM)])
    revive_casts = [a for a in _casts(st, "charm") if a.mode == 1]
    assert {a.target_id for a in revive_casts} == {"ys"}


def test_charm_revive_mode_uncastable_with_nobody_down():
    st = _state([dict(_CHARM)], downed=False)
    modes = {a.mode for a in _casts(st, "charm")}
    assert 0 in modes and 1 not in modes      # shield yes, revive no

# --- the SAME rule on the side-wide path (`mode: all`) ------------------------- #
# The playtest bug: Windry's Ultimate heals "all allies", but a downed ally got
# nothing — the chosen-target path let a heal reach a downed body while the
# side-wide path built its set from the LIVING party only.
ALL_ALLY = {"mode": "all", "side": "ally", "exclude_self": False, "targeted": False}

_MASS_MEND = _card("mass_mend", [{"kind": "heal", "amount": 9999, "target": ALL_ALLY}])
_MASS_WARD = _card("mass_ward", [
    {"kind": "heal", "amount": 6, "target": ALL_ALLY},
    {"kind": "grant_keyword", "keywords": ["lifelink"], "target": ALL_ALLY,
     "duration": "encounter"},
    {"kind": "pump", "power": 0, "toughness": 3, "target": ALL_ALLY,
     "duration": "this_turn"},
])
_MASS_HARM = _card("mass_harm", [{"kind": "deal_damage", "amount": 4, "target": ALL_ALLY}])


def _resolve(st, cid):
    st = apply_action(st, next(a for a in _casts(st, cid)))[0]
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def test_mass_heal_reaches_the_downed_ally_and_stands_them_up():
    st = _resolve(_state([dict(_MASS_MEND)]), "mass_mend")
    ys = st.character("ys")
    assert ys.alive and ys.hp == ys.max_hp
    assert st.character("soren").hp == st.character("soren").max_hp   # …and everyone else


def test_restorative_verbs_all_reach_a_downed_ally():
    st = _resolve(_state([dict(_MASS_WARD)]), "mass_ward")
    ys = st.character("ys")
    assert ys.hp == 6 and "lifelink" in ys.keywords and ys.temp_mod == 3


def test_a_harmful_side_wide_effect_still_passes_a_downed_ally_by():
    """An enemy AoE is authored as `deal_damage` on side 'ally' — the downed body
    is not a victim (enemies never single-target one either). Kicking someone
    while they are down would turn one downing into a death spiral."""
    st = _resolve(_state([dict(_MASS_HARM)]), "mass_harm")
    assert st.character("ys").hp == 0                       # untouched on the floor
    assert st.character("soren").hp == 20 - 4               # the standing ally is hit


def test_downed_ally_is_skipped_when_nothing_is_down_changes_nothing():
    st = _resolve(_state([dict(_MASS_MEND)], downed=False), "mass_mend")
    assert all(c.hp == c.max_hp for c in st.party)
