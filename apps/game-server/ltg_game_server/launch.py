"""`LTG-Game` / `ltg-game` — build the client (if needed) and serve everything.

One FastAPI app serves the built React client, the REST lobby, and the per-session
WebSocket on a single port. This launcher is independent of the cockpit
(`ltg-combat-cockpit`) — running it disturbs nothing else.

    LTG-Game                     # build client if needed, serve on 0.0.0.0:8020, open browser
    LTG-Game --port 9000
    LTG-Game --no-browser
    LTG-Game --skip-build        # serve whatever is already in apps/game-ui/dist
    LTG-Game --dev               # API/WS only (run `npm run dev` for the client yourself)
    LTG-Game --reload            # auto-reload the server on code changes
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

APP = "ltg_game_server.app:app"
UI_DIR = Path(__file__).resolve().parents[2] / "game-ui"  # apps/game-ui
DIST = UI_DIR / "dist"


def _build_client(force: bool = False) -> None:
    """Ensure apps/game-ui/dist exists (npm install + build on first run)."""
    if DIST.exists() and not force:
        return
    npm = shutil.which("npm")
    if npm is None:
        print("!! npm not found — cannot build the client. Install Node.js, or use "
              "--dev and run the Vite dev server yourself.", file=sys.stderr)
        return
    if not (UI_DIR / "node_modules").exists():
        print("First run: installing client dependencies (npm install)…")
        subprocess.run([npm, "install"], cwd=str(UI_DIR), check=True)
    print("Building the client (npm run build)…")
    subprocess.run([npm, "run", "build"], cwd=str(UI_DIR), check=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="LTG-Game",
                                     description="Launch the LTG-Game playable UI.")
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8020, help="port (default: 8020)")
    parser.add_argument("--reload", action="store_true", help="auto-reload the server")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    parser.add_argument("--skip-build", action="store_true", help="don't (re)build the client")
    parser.add_argument("--rebuild", action="store_true", help="force a client rebuild")
    parser.add_argument("--dev", action="store_true",
                        help="serve API/WS only (use the Vite dev server for the client)")
    args = parser.parse_args(argv)

    if not args.dev and not args.skip_build:
        _build_client(force=args.rebuild)

    browse_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{browse_host}:{args.port}"
    if not args.no_browser and not args.dev:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    mode = "API/WS only (dev)" if args.dev else "client + API/WS"
    print(f"Starting LTG-Game ({mode}) at {url}  (Ctrl-C to stop)")
    uvicorn.run(APP, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
