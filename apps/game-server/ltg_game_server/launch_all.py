"""`ltg-start` / `LTG-Start` — run the whole table: deckbuilder + game.

Spawns the deckbuilder as a child process (silent — the game's browser tab is
the front door; Options → Characters → Edit hops to the deckbuilder when
needed) and then runs the game server in this process, so the terminal window
owns the pair. Both apps stop together: the in-app Quit button quits the pair
over /api/quit?scope=all, closing this window also kills the child, and if the
game exits any other way the deckbuilder is terminated on the way out.

Ports are the defaults each app already uses (game 8020, deckbuilder 8000) —
the cross-app quit and the edit handoff both assume them. `ltg-start` takes no
arguments; for custom ports run the two apps separately.
"""

from __future__ import annotations

import subprocess
import sys

from . import launch


def main() -> int:
    deckbuilder = subprocess.Popen(
        [sys.executable, "-m", "ltg_deckbuilder", "--no-browser"])
    print("Deckbuilder starting at http://localhost:8000 (no tab — reach it "
          "from the game, or open it yourself).")
    try:
        return launch.main([])
    finally:
        deckbuilder.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
