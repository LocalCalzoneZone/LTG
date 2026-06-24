"""Thin Scryfall client. Sends a User-Agent and throttles ~100ms between calls.

Only the fields the schema needs are used: name, mana_cost, cmc, type_line,
oracle_text, rarity, color_identity. We never fetch images.
"""

from __future__ import annotations

import time
from typing import List

import requests

BASE = "https://api.scryfall.com"
HEADERS = {
    "User-Agent": "LTG-DeckBuilder/0.1 (local experimentation tool)",
    "Accept": "application/json",
}
_THROTTLE_SECONDS = 0.1
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < _THROTTLE_SECONDS:
        time.sleep(_THROTTLE_SECONDS - elapsed)
    _last_call = time.monotonic()


def search(query: str) -> List[dict]:
    """Return a short list of {name, type_line, rarity} matches for a name query."""
    if not query or not query.strip():
        return []
    _throttle()
    resp = requests.get(
        f"{BASE}/cards/search",
        params={"q": query, "order": "name", "unique": "cards"},
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code == 404:  # Scryfall returns 404 for "no cards found"
        return []
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [
        {
            "name": c.get("name"),
            "type_line": c.get("type_line", ""),
            "rarity": c.get("rarity", ""),
            "mana_cost": c.get("mana_cost", ""),
            "oracle_text": c.get("oracle_text", ""),
            "cmc": c.get("cmc", 0),
        }
        for c in data[:20]
    ]


def fetch_named(name: str) -> dict:
    """Fetch a single card by exact name. Raises on not-found."""
    _throttle()
    resp = requests.get(
        f"{BASE}/cards/named",
        params={"exact": name},
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code == 404:
        raise ValueError(f"Card not found on Scryfall: {name!r}")
    resp.raise_for_status()
    return resp.json()


def fetch_best(name: str) -> dict:
    """Best match for an imported line: exact name first, then a fuzzy fallback."""
    try:
        return fetch_named(name)
    except ValueError:
        pass
    _throttle()
    resp = requests.get(
        f"{BASE}/cards/named", params={"fuzzy": name}, headers=HEADERS, timeout=15
    )
    if resp.status_code == 404:
        raise ValueError(f"Card not found on Scryfall: {name!r}")
    resp.raise_for_status()
    return resp.json()


# Scryfall's batch endpoint accepts at most 75 identifiers per request.
_COLLECTION_CHUNK = 75


def fetch_collection(names: List[str]) -> tuple[dict[str, dict], List[str]]:
    """Resolve many card names in one request each (75 per call) via
    `/cards/collection`, instead of 1-2 requests per card.

    Returns ``(found, not_found)`` where ``found`` maps each *input* name to its
    Scryfall payload and ``not_found`` lists the names Scryfall couldn't match.
    Matching is by exact name only — callers wanting a fuzzy fallback should run
    one over the returned ``not_found`` list.
    """
    found: dict[str, dict] = {}
    not_found: List[str] = []
    for start in range(0, len(names), _COLLECTION_CHUNK):
        chunk = names[start : start + _COLLECTION_CHUNK]
        _throttle()
        resp = requests.post(
            f"{BASE}/cards/collection",
            json={"identifiers": [{"name": n} for n in chunk]},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        # Map results back to the input names. Scryfall matches case-insensitively
        # and may return a double-faced card by a single face name (input "Fire",
        # card name "Fire // Ice"), so index every face of each returned card.
        by_name: dict[str, dict] = {}
        for c in payload.get("data", []):
            full = c.get("name", "")
            by_name.setdefault(full.lower(), c)
            for face in full.split("//"):
                by_name.setdefault(face.strip().lower(), c)
        for n in chunk:
            card = by_name.get(n.strip().lower())
            if card is not None:
                found[n] = card
            else:
                not_found.append(n)
    return found, not_found
