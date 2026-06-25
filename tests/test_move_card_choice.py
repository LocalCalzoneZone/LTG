"""Interactive 'which cards?' choice for move_card, driven through the engine's
legal_actions / apply_action contract (as the cockpit does)."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions
from ltg_combat.scenario import state_from_dict

_ATTACK = {"name": "Hit", "amount": 1, "action_type": "ability",
           "intent_type": "attack", "targeting": "lowest_hp_party", "mode": "melee"}


def _spell(cid, effects):
    return {"id": cid, "name": cid, "source_name": cid, "rarity": "common", "level": 1,
            "type": "Instant", "timing": "sorcery", "cost": {"generic": 0, "colors": {}},
            "effects": effects}


def _plain(cid):
    return _spell(cid, [{"kind": "draw", "amount": 0}])  # a harmless filler card


def _state(library, hand_size):
    spec = {
        "party": [{"id": "p", "name": "Caster", "hp": 30, "power": 2,
                   "hand_size": hand_size, "identity": ["U"], "library": library}],
        "enemies": [{"id": "ea", "name": "EnemyA", "hp": 12, "level": 1, "intent": dict(_ATTACK)}],
    }
    return state_from_dict(spec)


def _do(state, **kw):
    a = next(a for a in legal_actions(state)
             if all(getattr(a, k) == v for k, v in kw.items()))
    return apply_action(state, a)[0]


def _cast_and_resolve(state, card_id):
    state = _do(state, kind="cast", card_id=card_id)
    return _do(state, kind="pass")  # one PC → the pass resolves the spell


def _names(cards):
    return [c.name for c in cards]


# --- discard: choose which card leaves the hand -------------------------------- #
def test_discard_prompts_and_moves_chosen_card():
    sift = _spell("sift", [{"kind": "move_card", "count": 1,
                            "source": "hand", "destination": "graveyard"}])
    st = _state([sift, _plain("alpha"), _plain("beta")], hand_size=3)
    st = _cast_and_resolve(st, "sift")            # hand is now [alpha, beta]

    choices = legal_actions(st)
    assert choices and all(a.kind == "choose_card" for a in choices)
    assert len(choices) == 2                       # a genuine choice of which to discard

    pick = next(a for a in choices if "alpha" in a.label)
    st = apply_action(st, pick)[0]
    p = st.party[0]
    assert "alpha" in _names(p.graveyard)
    assert _names(p.hand) == ["beta"]              # the unchosen card stays
    assert st.pending_choice is None               # choice complete


# --- Brainstorm: choose from the just-drawn cards, two picks, resumable -------- #
def test_brainstorm_choose_from_drawn_two_picks():
    brainstorm = _spell("brainstorm", [
        {"kind": "draw", "amount": 3},
        {"kind": "move_card", "count": 2, "source": "drawn", "destination": "library_top"},
    ])
    lib = [brainstorm] + [_plain(f"d{i}") for i in range(1, 7)]
    st = _state(lib, hand_size=1)                  # opening hand [brainstorm]; upkeep draws d1
    st = _cast_and_resolve(st, "brainstorm")       # draws d2,d3,d4 → choice among them

    c1 = legal_actions(st)
    assert all(a.kind == "choose_card" for a in c1)
    # only the just-drawn cards are candidates — the upkeep-drawn d1 is NOT offered.
    labels = " ".join(a.label for a in c1)
    assert "d1 " not in labels and {"d2", "d3", "d4"} <= {w for w in labels.split()}

    st = apply_action(st, next(a for a in c1 if "d2" in a.label))[0]
    assert st.pending_choice is not None and st.pending_choice.need == 1  # one more to move
    st = apply_action(st, next(a for a in legal_actions(st) if "d4" in a.label))[0]

    p = st.party[0]
    assert _names(p.library[:2]) == ["d4", "d2"]   # last picked ends up on top
    assert "d2" not in _names(p.hand) and "d4" not in _names(p.hand)
    assert "d3" in _names(p.hand)                  # the kept drawn card
    assert st.pending_choice is None


# --- mandatory: no choice when candidates ≤ count ------------------------------ #
def test_no_prompt_when_one_legal_card():
    sift = _spell("sift1", [{"kind": "move_card", "count": 1,
                             "source": "hand", "destination": "graveyard"}])
    st = _state([sift, _plain("only")], hand_size=2)  # after cast, hand == [only]
    st = _cast_and_resolve(st, "sift1")
    assert all(a.kind != "choose_card" for a in legal_actions(st))  # auto-discarded
    assert "only" in _names(st.party[0].graveyard)


def test_no_prompt_and_empty_log_when_no_legal_cards():
    sift = _spell("sift2", [{"kind": "move_card", "count": 1,
                             "source": "hand", "destination": "graveyard"}])
    st = _state([sift], hand_size=1)                 # after cast, hand is empty
    state = _do(st, kind="cast", card_id="sift2")
    state, events = apply_action(state, next(a for a in legal_actions(state) if a.kind == "pass"))
    assert state.pending_choice is None
    assert any(e.type == "move_card_empty" for e in state.log)
