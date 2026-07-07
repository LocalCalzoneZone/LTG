"""The `targeted` flag audit (playtest follow-up): the flag drives hexproof —
so it must be RIGHT at authoring time and ENFORCED at play time.

- translation registry: "target …" phrasing emits targeted:true (already did).
- ingest: "Choose two/three [or more] —" modals now parse (choose/or_more), and a
  modal with an untranslatable bullet is refused whole (no silent partial modes).
- engine: a player's TARGETED effect can neither offer nor land on a hexproof
  enemy; an untargeted-chosen effect beats hexproof (GDD §7); friendly targeting
  of a hexproof ally stays legal.
"""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict
from ltg_core.translation import translate
from ltg_deckbuilder.ingest import parse_modal


# --------------------------------------------------------------------------- #
# Registry + ingest
# --------------------------------------------------------------------------- #
def test_registry_marks_target_wording_as_targeted():
    (bounce,) = translate("Return target creature to its owner's hand", {})
    assert bounce.kind == "bounce" and bounce.target.targeted
    (destroy,) = translate("Destroy target creature", {})
    assert destroy.kind == "destroy" and destroy.target.targeted


def test_parse_modal_choose_two():
    modal = parse_modal(
        "Choose two —\n• Counter target spell.\n• Draw a card.\n• Destroy target creature.")
    assert modal is not None
    assert modal.choose == 2 and not modal.or_more
    assert len(modal.modes) == 3
    # The bounce/destroy bullets carry the targeting flag through.
    assert modal.modes[2].effects[0].target.targeted


def test_parse_modal_choose_one_or_more():
    modal = parse_modal("Choose one or more —\n• Draw a card.\n• Destroy target creature.")
    assert modal is not None
    assert modal.choose == 1 and modal.or_more


def test_parse_modal_refuses_partial_translation():
    # "Tap all creatures" has no registry rule: the whole modal must be refused
    # (needs_translation), never a silently mode-dropped card.
    assert parse_modal(
        "Choose two —\n• Draw a card.\n• Tap all creatures your opponents control.\n"
        "• Destroy target creature.") is None


# --------------------------------------------------------------------------- #
# Engine: hexproof vs player casts
# --------------------------------------------------------------------------- #
def _card(cid, effects):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "effects": effects,
            "validated": True}


_ZAP = _card("zap", [{"kind": "deal_damage", "amount": 2,
                      "target": {"mode": "chosen", "side": "enemy", "targeted": True}}])
_SLIP = _card("slip", [{"kind": "bounce",       # untargeted-chosen: beats hexproof
                        "target": {"mode": "chosen", "side": "enemy", "targeted": False}}])
_MEND = _card("mend", [{"kind": "heal", "amount": 3,
                        "target": {"mode": "chosen", "side": "ally", "targeted": True}}])


def _state(hand):
    return state_from_dict({
        "party": [{"id": "p", "name": "P", "hp": 20, "power": 2, "hand_size": len(hand),
                   "identity": ["U"], "row": "front", "attack_mode": "melee",
                   "library": hand, "keywords": ["hexproof"]}],
        "enemies": [
            {"id": "hexer", "name": "Hexer", "hp": 10, "level": 3,
             "keywords": ["hexproof"],
             "intent": {"name": "Hit", "amount": 1, "action_type": "ability",
                        "intent_type": "attack", "targeting": "lowest_hp_party",
                        "mode": "melee"}},
            {"id": "grunt", "name": "Grunt", "hp": 10, "level": 1,
             "intent": {"name": "Hit", "amount": 1, "action_type": "ability",
                        "intent_type": "attack", "targeting": "lowest_hp_party",
                        "mode": "melee"}},
        ],
    })


def _resolve_stack(st):
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st = apply_action(st, p)[0]
    return st


def test_targeted_spell_cannot_pick_hexproof_enemy():
    st = _state([dict(_ZAP)])
    tids = {a.target_id for a in legal_actions(st)
            if a.kind == "cast" and a.card_id == "zap"}
    assert "grunt" in tids and "hexer" not in tids


def test_untargeted_chosen_effect_beats_hexproof():
    st = _state([dict(_SLIP)])
    tids = {a.target_id for a in legal_actions(st)
            if a.kind == "cast" and a.card_id == "slip"}
    assert "hexer" in tids                       # non-targeting: offerable
    act = next(a for a in legal_actions(st)
               if a.kind == "cast" and a.card_id == "slip" and a.target_id == "hexer")
    st = _resolve_stack(apply_action(st, act)[0])
    assert st.enemy("hexer").in_hand             # and it lands


def test_friendly_targeting_of_hexproof_ally_is_legal():
    st = _state([dict(_MEND)])
    tids = {a.target_id for a in legal_actions(st)
            if a.kind == "cast" and a.card_id == "mend"}
    assert "p" in tids                            # own hexproof never blocks you
