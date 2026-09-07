"""Deck flavour (Deckbuilder, 2026-09): one LLM call that writes 2–3 lines per
card and heroic ability on how it manifests in the game world for THIS
character, from the character's "Abilities & Combat" text (with the brief's
concept and the lore for colour). The result lands in each card's
`flavor_text` — the card editor's Flavour field — and nothing mechanical is
touched.

Reads the same `llm_settings.json` the game's Options → LLM writes (the
loadouts dir is shared), so the Deckbuilder needs no settings of its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# The model used when the settings file names none. Must be a LIVE OpenRouter
# slug: a retired one here would 404 on every call from a fresh install.
DEFAULT_MODEL = "google/gemini-3.8-flash"
# Retired slugs → their successors. The game's `llm._MODEL_ALIASES` is the
# source of truth and maps these on read; a settings file WRITTEN before a
# rename still holds the old slug on disk, so map here too rather than send a
# dead one. (Not imported: the apps depend on `core`, never on each other.)
_RETIRED_MODELS = {
    "z-ai/glm-5.2": "google/gemini-3.8-flash",
    "z-ai/glm-5.3": "google/gemini-3.8-flash",
    "z-ai/glm-5.3-flash": "google/gemini-3.8-flash",
    "google/gemini-3.5-flash": "google/gemini-3.8-flash",
    "google/gemini-3.7-flash": "google/gemini-3.8-flash",
    "anthropic/claude-opus-4.8": "anthropic/claude-opus-5",
    "anthropic/claude-sonnet-5": "openai/gpt-5.6-sol",
}
MAX_TOKENS = 16000
TIMEOUT = 300.0

INSTRUCTIONS = """You write CARD FLAVOUR for LTG, a painterly tactical fantasy card game.
Your one duty: for each card and heroic ability listed, write 2–3 lines (one
short paragraph, 25–60 words) describing how THAT card or ability MANIFESTS in
the game world when this character uses it — what a bystander would see, hear
and feel. Return ONLY JSON.

Rules:
- Ground every line in the character's ABILITIES & COMBAT text below: their
  style, their weapons, the source of their magic, their tells. The brief and
  lore are colour, not subject.
- Concrete and physical: what the hands do, what the air does, what the target
  feels. No rules text, no numbers, no "deals damage" — the mechanics are on the
  card already; you write what it LOOKS like.
- Match the card's timing: an instant is a flinch or a snap of the fingers, a
  sorcery is a deliberate act, a channel is something held — a stance, a hum, a
  ward kept up.
- Vary the register across the deck: not every line is a thunderclap. Small
  cards get small, exact moments.
- No second person addressed to the player; write it as narration.

Output contract:
{"flavours": {"<card id>": "...", ...}}
— one entry per id you were given, and no others.
"""


def load_llm_settings(loadout_dir: Path) -> Dict[str, Any]:
    """The api_key and the model for the "flavour" task, from the game's
    shared settings file (Options → LLM → Card Flavour; empty when unset):
    the per-task override if one is set, else the file's default model."""
    out: Dict[str, Any] = {"api_key": "", "model": DEFAULT_MODEL}
    try:
        data = json.loads((loadout_dir / "llm_settings.json").read_text())
        if isinstance(data, dict):
            if isinstance(data.get("api_key"), str):
                out["api_key"] = data["api_key"]
            if isinstance(data.get("model"), str) and data["model"]:
                out["model"] = data["model"]
            task = (data.get("task_models") or {}).get("flavour") if isinstance(data.get("task_models"), dict) else None
            if isinstance(task, str) and task:
                out["model"] = task
    except (OSError, json.JSONDecodeError):
        pass
    out["model"] = _RETIRED_MODELS.get(out["model"], out["model"])
    return out


def chat(api_key: str, model: str, messages: List[Dict[str, str]]) -> str:
    payload = {"model": model, "messages": messages, "temperature": 0.9,
               "response_format": {"type": "json_object"}, "max_tokens": MAX_TOKENS}
    try:
        resp = httpx.post(OPENROUTER_URL, json=payload, timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json",
                                   "HTTP-Referer": "https://ltg.local",
                                   "X-Title": "LTG Deckbuilder"})
    except httpx.HTTPError as exc:
        raise ValueError(f"could not reach OpenRouter: {exc}") from exc
    if resp.status_code == 401:
        raise ValueError("OpenRouter rejected the API key (401). Set it in the game's Options → LLM.")
    if resp.status_code >= 400:
        raise ValueError(f"OpenRouter error {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"unexpected OpenRouter response: {exc}") from exc


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("the reply held no JSON object")
    return json.loads(m.group(0))


def _rows(loadout: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every card and heroic ability the writer must cover: id, name, kind,
    timing and the mechanical text (as the card editor renders it)."""
    rows: List[Dict[str, str]] = []
    for c in loadout.get("cards") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        rows.append({"id": str(c["id"]), "name": str(c.get("name") or c["id"]),
                     "kind": str(c.get("type") or "card"), "timing": str(c.get("timing") or ""),
                     "text": str(c.get("translated_text") or "")})
    ch = loadout.get("character") or {}
    for slot, label in (("skill", "Skill (once per encounter)"), ("ultimate", "Ultimate (the gauge is its cost)")):
        card = ch.get(slot)
        if isinstance(card, dict) and card.get("id"):
            rows.append({"id": str(card["id"]), "name": str(card.get("name") or slot.title()),
                         "kind": label, "timing": str(card.get("timing") or ""),
                         "text": str(card.get("translated_text") or "")})
    return rows


def prompt_for(loadout: Dict[str, Any]) -> str:
    ch = loadout.get("character") or {}
    brief = ch.get("brief") if isinstance(ch.get("brief"), dict) else {}
    lines = [f'# THE CHARACTER — {ch.get("name", "")}']
    if brief.get("concept") or ch.get("description"):
        lines.append(f'Concept: {brief.get("concept") or ch.get("description")}')
    if brief.get("appearance"):
        lines.append(f'Appearance: {brief["appearance"]}')
    voice = brief.get("voice") if isinstance(brief.get("voice"), dict) else {}
    if voice.get("register"):
        lines.append(f'Voice: {voice["register"]}')
    lines += ["", "# ABILITIES & COMBAT — how this character fights (your primary source):",
              str(ch.get("combat_lore") or "").strip() or "(nothing written — infer a style from the deck and the concept)"]
    lore = str(ch.get("lore") or "").strip()
    if lore:
        words = lore.split()
        lines += ["", "# LORE (colour only, never the subject):", " ".join(words[:300]) + (" …" if len(words) > 300 else "")]
    lines += ["", "# THE CARDS AND ABILITIES (write one flavour per id):"]
    for r in _rows(loadout):
        lines.append(f'- [{r["id"]}] {r["name"]} — {r["kind"]}{", " + r["timing"] if r["timing"] else ""}: {r["text"] or "(no text yet)"}')
    lines.append("\nWrite the flavours now. Return ONLY the JSON.")
    return "\n".join(lines)


def generate_flavours(loadout: Dict[str, Any], loadout_dir: Path,
                      chat_fn: Optional[Callable[..., str]] = None,
                      attempts: int = 2) -> Dict[str, str]:
    """`{card id: flavour}` for every card and heroic ability of the loadout.
    Raises ValueError with a human message (no key, no cards, bad reply)."""
    rows = _rows(loadout)
    if not rows:
        raise ValueError("the deck has no cards to write flavour for")
    settings = load_llm_settings(loadout_dir)
    if not settings["api_key"] and chat_fn is None:
        raise ValueError("No OpenRouter API key set. Add one in the game's Options → LLM.")
    call = chat_fn or chat
    wanted = {r["id"] for r in rows}
    messages = [{"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": prompt_for(loadout)}]
    last = ""
    for _ in range(max(1, attempts)):
        reply = call(settings["api_key"], settings["model"], messages)
        try:
            raw = _extract_json(reply)
            table = raw.get("flavours") if isinstance(raw.get("flavours"), dict) else raw
            out = {k: str(v).strip() for k, v in table.items() if k in wanted and str(v).strip()}
            missing = sorted(wanted - set(out))
            if missing:
                raise ValueError("no flavour for: " + ", ".join(missing[:8]) + (" …" if len(missing) > 8 else ""))
            return out
        except ValueError as exc:
            last = str(exc)
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"That output was rejected: {last}\nFix it and return ONLY the corrected JSON."})
    raise ValueError(f"flavour generation failed after {attempts} attempts: {last}")
