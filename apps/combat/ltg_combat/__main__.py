"""CLI entry point: validate a loadout JSON, then hand off to the engine stub.

    python -m ltg_combat <loadout.json>

Proves the runtime skeleton: the loadout is loaded and validated through
`ltg_core` (JSON-in), then `engine.run` takes over — which is currently the
`TODO: combat engine` placeholder.
"""

from __future__ import annotations

import sys

from .engine import run
from .loader import LoadoutError, load_loadout


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m ltg_combat <loadout.json>", file=sys.stderr)
        return 2

    try:
        loadout = load_loadout(argv[0])
    except LoadoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"[ltg-combat] loadout OK: {argv[0]}")
    try:
        run(loadout)
    except NotImplementedError as exc:
        # Expected while combat is a scaffold: the JSON-in path worked, the
        # engine itself is the next brief.
        print(f"[ltg-combat] {exc}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
