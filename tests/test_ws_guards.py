"""WebSocket guards (roadmap M1.32): a malformed message or a fault anywhere in
dispatch answers with an `error` frame and keeps the socket, so the player's
seats survive. Dropping the socket used to release them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ltg_game_server import app as game_app, content


@pytest.fixture
def session():
    state, portraits, art = content.build_state(["loadout_soren"], content.list_encounters()[0]["id"], seed=1)
    return game_app.MANAGER.create(state, name="guards", portraits=portraits, art=art)


def _drain_until(ws, kind):
    for _ in range(20):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"no {kind} frame")


def test_bad_frames_and_dispatch_faults_answer_without_dropping_the_seat(session, monkeypatch):
    client = TestClient(game_app.app)
    with client.websocket_connect(f"/ws/{session.id}") as ws:
        hello = _drain_until(ws, "hello")
        cid = hello["client_id"]
        ws.send_json({"type": "claim_seat", "character_ids": [session.state.party[0].id]})
        _drain_until(ws, "seats")
        assert session.controlled_by(cid)

        ws.send_json(["not", "an", "object"])
        assert "objects" in _drain_until(ws, "error")["message"]
        ws.send_json({"type": "claim_seat", "character_ids": "everyone"})
        assert "list of ids" in _drain_until(ws, "error")["message"]
        ws.send_json({"type": "submit_action", "action": [1]})
        assert "object" in _drain_until(ws, "error")["message"]

        def boom(*a, **k):
            raise RuntimeError("rule fault in a confirm")
        monkeypatch.setattr(session, "answer_confirm", boom)
        ws.send_json({"type": "confirm", "id": 1, "yes": True})
        assert "rule fault" in _drain_until(ws, "error")["message"]

        ws.send_json({"type": "heartbeat"})
        _drain_until(ws, "heartbeat")               # the socket is still open…
        assert session.controlled_by(cid)           # …and the seat still held
