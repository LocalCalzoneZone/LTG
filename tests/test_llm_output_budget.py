"""The completion budget and the truncation guard.

Playtest evidence (2026-08-28): scenario calls were coming back with
finish_reason "length" and exactly 12,000 output tokens — the ceiling, not the
model finishing. A town is the biggest artifact the game generates (a full cast
with persona prose runs past 11k output tokens), so the budget was too tight,
and worse, `_chat` never looked at finish_reason: a cut-off reply went into the
generic repair loop, which re-sent the dead stub and asked the model to "fix"
it against the same wall."""

from __future__ import annotations

import json

import pytest

from ltg_game_server import llm


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _reply(content: str, finish_reason: str = "stop"):
    return {"choices": [{"message": {"content": content},
                         "finish_reason": finish_reason}]}


@pytest.fixture
def capture(monkeypatch):
    """Patch llm's httpx.post; records each request payload, replies as told."""
    calls: list = []
    box = {"reply": _reply('{"ok": true}')}

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"payload": json, "timeout": timeout, "headers": headers})
        return _Resp(box["reply"])

    monkeypatch.setattr(llm.httpx, "post", post)
    return calls, box


# --------------------------------------------------------------------------- #
# The budget
# --------------------------------------------------------------------------- #
def test_a_town_sized_reply_fits_the_scenario_budget():
    """The measured worst case: the largest shipped town serializes to ~11k
    output tokens, and the raw reply is at least that. The ceiling must clear it
    with real room, not by a few hundred tokens."""
    assert llm.SCENARIO_MAX_TOKENS >= 32000

def test_the_scenario_timeout_covers_the_scenario_budget():
    """A budget the timeout can't sit through just fails a different way. At the
    ~75 output tok/s these models sustain, the wait has to cover the ceiling."""
    slowest_tok_per_s = 75
    assert llm.SCENARIO_TIMEOUT >= llm.SCENARIO_MAX_TOKENS / slowest_tok_per_s


def test_the_adventure_timeout_covers_its_budget_too():
    assert llm.ADVENTURE_TIMEOUT >= llm.ADVENTURE_MAX_TOKENS / 75


def test_the_scenario_budget_reaches_the_request(capture, monkeypatch):
    calls, _ = capture
    monkeypatch.setattr(llm, "load_settings", lambda: {
        "api_key": "sk-test", "model": "z-ai/glm-5.3", "task_models": {},
        "scenario_tone": "", "instructions": ""})
    llm._scenario_chat("sys", "user", 1, lambda raw: raw, "thing")
    assert calls[0]["payload"]["max_tokens"] == llm.SCENARIO_MAX_TOKENS
    assert calls[0]["timeout"] == llm.SCENARIO_TIMEOUT


# --------------------------------------------------------------------------- #
# The truncation guard
# --------------------------------------------------------------------------- #
def test_a_truncated_reply_raises_instead_of_returning_a_stub(capture):
    calls, box = capture
    box["reply"] = _reply('{"quests": [{"title": "The Unfini',
                          finish_reason="length")
    with pytest.raises(ValueError) as exc:
        llm._chat("sk-test", "m", [{"role": "user", "content": "go"}],
                  max_tokens=12000)
    msg = str(exc.value)
    assert "cut off" in msg and "12000" in msg     # names the wall it hit
    assert "raise the budget" in msg               # …and what to do about it


def test_the_truncation_message_is_honest_when_no_cap_was_set(capture):
    """Encounter calls send no max_tokens — the provider's own default applies,
    so the message must not invent a number we never sent."""
    calls, box = capture
    box["reply"] = _reply("{", finish_reason="length")
    with pytest.raises(ValueError) as exc:
        llm._chat("sk-test", "m", [{"role": "user", "content": "go"}])
    assert "no max_tokens was set" in str(exc.value)
    assert "max_tokens" not in calls[0]["payload"]


def test_a_complete_reply_is_returned_untouched(capture):
    calls, box = capture
    box["reply"] = _reply('{"ok": true}', finish_reason="stop")
    assert llm._chat("sk-test", "m", [{"role": "user", "content": "go"}]) == '{"ok": true}'


def test_a_truncation_does_not_burn_a_repair_attempt(capture, monkeypatch):
    """The whole point: re-prompting cannot shorten the output, so a cut-off
    reply must stop the loop rather than re-send the dead stub at full price."""
    calls, box = capture
    box["reply"] = _reply('{"partial": ', finish_reason="length")
    monkeypatch.setattr(llm, "load_settings", lambda: {
        "api_key": "sk-test", "model": "z-ai/glm-5.3", "task_models": {},
        "scenario_tone": "", "instructions": ""})
    with pytest.raises(ValueError, match="cut off"):
        llm._scenario_chat("sys", "user", 3, lambda raw: raw, "town")
    assert len(calls) == 1     # not 3


# --------------------------------------------------------------------------- #
# The model roster
# --------------------------------------------------------------------------- #
def test_glm_flash_is_selectable():
    ids = [m["id"] for m in llm.MODELS]
    assert "z-ai/glm-5.3-flash" in ids
    assert llm._valid_model("z-ai/glm-5.3-flash") == "z-ai/glm-5.3-flash"
    # …and it is a distinct choice, not a rename of the standard model.
    assert "z-ai/glm-5.3" in ids


def test_every_model_choice_has_a_label_and_is_valid():
    for m in llm.MODELS:
        assert m["id"] and m["label"]
        assert llm._valid_model(m["id"]) == m["id"]
    assert len({m["id"] for m in llm.MODELS}) == len(llm.MODELS)


def test_the_new_model_reaches_the_ui_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm_settings.json")
    assert any(m["id"] == "z-ai/glm-5.3-flash" for m in llm.public_settings()["models"])
