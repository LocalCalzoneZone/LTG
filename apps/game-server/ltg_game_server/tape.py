"""The LLM tape: record and replay text-generation replies (roadmap M3.4).

Every text writer funnels through `llm._chat`, which consults this module
when the tape is on (Options → LLM → Playtest, or ``LTG_LLM_TAPE``):

- ``record``: live calls, and every reply is written to the tape.
- ``replay``: answer from the tape when a recording matches; a miss goes live
  and is recorded, so the tape fills as you play.
- ``replay_only``: a miss is an error. Never spends, needs no API key.

A recording is keyed by the SHA-256 of the prompt (the messages, not the
model, so a tape made on a premium model replays under the playtest model).
Prompts are not fully deterministic — the signature rolls are random, and the
library lines grow as content is written — so an exact miss falls back to the
closest recording of the same kind (town, arc, act, adventure …) at the same
repair depth, judged by the overlap of prompt lines. The replayed reply still
passes the same validators a live one does, so a stale match fails loudly
instead of slipping bad content in.

The tape is per-install and gitignored: ``loadouts/llm_tape/<kind>/<hash>.json``.
It holds prompts and replies, never the API key.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import content

TAPE_DIR = content.LOADOUTS_DIR / "llm_tape"
TAPE_MODES = ("off", "record", "replay", "replay_only")
TAPE_MODE_LABELS = {
    "off": "Off (live calls, nothing recorded)",
    "record": "Record (live calls, every reply kept)",
    "replay": "Replay (recorded reply when one matches, else live and recorded)",
    "replay_only": "Replay only (never calls the API; a miss is an error)",
}
# An exact miss replays the closest same-kind recording only when this share
# of prompt lines overlaps (Jaccard over the non-system messages' lines). A
# different town or party scores well under it; the same request with a new
# ledger line or a fresh signature roll scores well over it.
FUZZY_MIN_OVERLAP = 0.6


def env_mode() -> Optional[str]:
    """``LTG_LLM_TAPE``, when it names a mode — it overrides the settings file
    (the CLI tools and one-off shells use it)."""
    raw = (os.environ.get("LTG_LLM_TAPE") or "").strip().lower()
    return raw if raw in TAPE_MODES else None


def prompt_hash(messages: List[Dict[str, str]]) -> str:
    canon = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _kind_dir(kind: str) -> Path:
    safe = "".join(ch for ch in (kind or "misc") if ch.isalnum() or ch in "-_") or "misc"
    return TAPE_DIR / safe


def _lines(messages: List[Dict[str, str]]) -> set:
    out = set()
    for m in messages:
        if m.get("role") == "system":
            continue
        for line in str(m.get("content") or "").splitlines():
            line = line.strip()
            if line:
                out.add(line)
    return out


def _overlap(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def record(kind: str, model: str, messages: List[Dict[str, str]], reply: str) -> Path:
    """Keep one reply. The same prompt recorded twice keeps the newer reply."""
    h = prompt_hash(messages)
    d = _kind_dir(kind)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{h[:24]}.json"
    path.write_text(json.dumps({
        "kind": kind, "model": model, "hash": h,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "depth": len(messages), "messages": messages, "reply": reply,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def _entries(kind: str) -> List[Dict[str, Any]]:
    d = _kind_dir(kind)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("reply"), str):
            out.append(data)
    return out


def lookup(kind: str, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """The recording to replay for this prompt, or None: the exact prompt
    first, else the closest recording of the same kind and repair depth.
    Returns ``{"reply", "match": "exact"|"closest", "overlap", "model"}``."""
    h = prompt_hash(messages)
    exact = _kind_dir(kind) / f"{h[:24]}.json"
    if exact.is_file():
        try:
            data = json.loads(exact.read_text(encoding="utf-8"))
            if data.get("hash") == h and isinstance(data.get("reply"), str):
                return {"reply": data["reply"], "match": "exact", "overlap": 1.0,
                        "model": data.get("model", "")}
        except (OSError, json.JSONDecodeError):
            pass
    want = _lines(messages)
    best: Optional[Dict[str, Any]] = None
    best_key = (-1.0, "")
    for data in _entries(kind):
        if int(data.get("depth") or 0) != len(messages):
            continue
        score = _overlap(want, _lines(data.get("messages") or []))
        key = (score, str(data.get("recorded_at") or ""))
        if key > best_key:
            best_key, best = key, data
    if best is None or best_key[0] < FUZZY_MIN_OVERLAP:
        return None
    return {"reply": best["reply"], "match": "closest", "overlap": round(best_key[0], 3),
            "model": best.get("model", "")}


def summary() -> Dict[str, int]:
    """Recordings per kind, for Options → LLM."""
    if not TAPE_DIR.is_dir():
        return {}
    return {d.name: sum(1 for _ in d.glob("*.json"))
            for d in sorted(TAPE_DIR.iterdir()) if d.is_dir()}
