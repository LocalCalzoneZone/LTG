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
