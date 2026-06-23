"""CLI entry point for LTG Combat.

    python -m ltg_combat harness          run the §A scripted scenario (asserts)
    python -m ltg_combat repl             play the §A encounter in the text REPL
    python -m ltg_combat validate <path>  load + validate a loadout JSON via core

The harness is the engine's correctness proof; the REPL is hands-on feel. Both
drive the engine through only `legal_actions` / `apply_action`.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from .loader import LoadoutError, load_loadout


_USAGE = (
    "usage: python -m ltg_combat <command>\n"
    "  cockpit [opts]     launch the web cockpit (FastAPI + browser GUI)\n"
    "  harness            run the §A scripted scenario (asserts; exits non-zero on failure)\n"
    "  repl [scenario]    play in the text UI (defaults to §A; or a scenario JSON path)\n"
    "  validate <path>    load + validate a loadout JSON through core"
)


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2

    command = argv[0]
    if command == "cockpit":
        from .cockpit import main as cockpit_main
        return cockpit_main(argv[1:])
    if command == "harness":
        from .harness import main as harness_main
        return harness_main()
    if command == "repl":
        from .repl import main as repl_main
        return repl_main(argv[1:])
    if command == "validate":
        if len(argv) != 2:
            print("usage: python -m ltg_combat validate <loadout.json>", file=sys.stderr)
            return 2
        try:
            loadout = load_loadout(argv[1])
        except LoadoutError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        from .engine import run
        print(f"[ltg-combat] loadout OK: {argv[1]}")
        run(loadout)
        return 0

    print(f"unknown command '{command}'\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
