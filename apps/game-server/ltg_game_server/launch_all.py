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

If a deckbuilder is ALREADY answering on 8000 (a previous launch still up), it
is reused rather than spawning a child doomed to die on "address in use"; if
the child fails to come up for any other reason, that is said out loud instead
of scrolling past.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request

from . import launch

DECKBUILDER_PORT = 8000
DECKBUILDER_URL = f"http://localhost:{DECKBUILDER_PORT}"


def _deckbuilder_up() -> bool:
    try:
        with urllib.request.urlopen(f"{DECKBUILDER_URL}/api/character-model", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    deckbuilder = None
    if _deckbuilder_up():
        print(f"Deckbuilder already running at {DECKBUILDER_URL} — reusing it.")
    else:
        deckbuilder = subprocess.Popen(
            [sys.executable, "-m", "ltg_deckbuilder", "--no-browser"])
        # Give it a moment; a port clash or import error exits at once.
        for _ in range(30):
            if deckbuilder.poll() is not None:
                break
            if _deckbuilder_up():
                break
            time.sleep(0.2)
        if deckbuilder.poll() is not None:
            print("\n!! The Deckbuilder FAILED to start (see the lines above — usually "
                  f"port {DECKBUILDER_PORT} is in use by something else).\n"
                  "!! Free the port or run LTG-Deckbuilder separately; the game "
                  "starts anyway.\n", flush=True)
            deckbuilder = None
        else:
            print(f"Deckbuilder starting at {DECKBUILDER_URL} (no tab — reach it "
                  "from the game's Edit buttons, or open it yourself).")
    try:
        return launch.main([])
    finally:
        if deckbuilder is not None:
            deckbuilder.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
