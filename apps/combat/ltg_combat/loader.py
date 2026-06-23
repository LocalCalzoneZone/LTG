"""Load a finished loadout JSON and validate it through `core`.

This is the JSON-in boundary. Combat consumes ONLY the validated loadout
artifact the Deckbuilder emits — it never imports the Deckbuilder, reads its live
state, touches Scryfall, or translates anything. The single gate a loadout
passes through is `ltg_core`'s schema validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from pydantic import ValidationError

from ltg_core.schema import Loadout


class LoadoutError(Exception):
    """A loadout file was missing, unparseable, or failed schema validation."""


def load_loadout(path: Union[str, Path]) -> Loadout:
    """Read, parse and validate a loadout JSON file into a `core` Loadout.

    Raises `LoadoutError` (with a readable message) if the file is missing, not
    valid JSON, or does not satisfy the loadout schema.
    """
    path = Path(path)
    if not path.exists():
        raise LoadoutError(f"no loadout file at {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise LoadoutError(f"{path} is not valid JSON: {exc}") from exc
    return validate_loadout(raw, source=str(path))


def validate_loadout(raw: dict, source: str = "<loadout>") -> Loadout:
    """Validate an already-parsed loadout dict through the `core` schema."""
    try:
        return Loadout.model_validate(raw)
    except ValidationError as exc:
        errors = "; ".join(
            ".".join(str(p) for p in err["loc"]) + ": " + err["msg"]
            for err in exc.errors()
        )
        raise LoadoutError(f"{source} failed loadout validation: {errors}") from exc
