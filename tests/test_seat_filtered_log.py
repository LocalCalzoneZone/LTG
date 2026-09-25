"""The seat-filtered log (roadmap M1.33 / M1.35): a teammate's draw names no
card, and a redirected or spoiled intent names no telegraph before it reaches
the stack (§D8-1.1). The engine's own log keeps everything."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import state_from_dict
from ltg_combat.state import Event
from ltg_game_server.snapshot import build_snapshot


def _filler(cid):
    return {"id": cid, "name": f"Card {cid}", "source_name": cid, "rarity": "common",
            "level": 1, "type": "Instant", "timing": "instant",
            "cost": {"generic": 0, "colors": {}}, "effects": [{"kind": "draw", "amount": 0}]}


def _state():
    party = [{"id": h, "name": h.title(), "hp": 20, "power": 2, "hand_size": 1,
              "identity": ["U"], "row": "front", "attack_mode": "melee",
              "library": [_filler(f"{h}{i}") for i in range(5)]} for h in ("ann", "bo")]
    enemy = {"id": "brute", "name": "Brute", "hp": 20, "level": 2, "power": 2}
    return settle(state_from_dict({"party": party, "enemies": [enemy]}, seed=1))


def _lines(snap, kind):
    return [row for row in snap["log"] if row["type"] == kind]


def _until_drawn(st):
    for _ in range(200):
        if any(e.type == "draw" for e in st.log):
            return st
        acts = legal_actions(st)
        st = apply_action(st, next((a for a in acts if a.kind in ("pass", "end_turn")),
                                   acts[0]))[0]
    raise AssertionError("no draw")


def test_a_teammates_draw_names_no_card():
    st = _until_drawn(_state())
    drawn = next(e for e in st.log if e.type == "draw" and e.data["character"] == "ann")
    mine = _lines(build_snapshot(st, {"ann"}), "draw")
    theirs = _lines(build_snapshot(st, {"bo"}), "draw")
    ann_mine = next(r for r in mine if r["data"]["character"] == "ann")
    ann_theirs = next(r for r in theirs if r["data"]["character"] == "ann")
    assert drawn.data["card_name"] in ann_mine["msg"]
    assert ann_theirs["msg"] == "Ann draws a card."
    assert "card" not in ann_theirs["data"] and ann_theirs["card"] is None


def test_a_redirected_intent_names_no_telegraph():
    st = _state()
    st.log.append(Event(type="intent_redirect",
                        msg="Brute's Skull-Crusher — deal 9 redirects — Ann is covered; "
                            "it now falls on Bo.",
                        data={"enemy": "brute", "intent": "Skull-Crusher — deal 9",
                              "target": "bo", "was": "ann"}))
    st.log.append(Event(type="intent_spoiled",
                        msg="Brute's Skull-Crusher — deal 9 comes to nothing — its "
                            "target fell. It attacks instead.",
                        data={"enemy": "brute", "label": "Skull-Crusher — deal 9",
                              "reason": "its target fell"}))
    snap = build_snapshot(st, {"ann", "bo"})
    for kind in ("intent_redirect", "intent_spoiled"):
        (row,) = _lines(snap, kind)
        assert "Skull-Crusher" not in row["msg"] and "9" not in row["msg"]
        assert "intent" not in row["data"] and "label" not in row["data"]
    assert "falls on Bo" in _lines(snap, "intent_redirect")[0]["msg"]
