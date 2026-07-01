"""CLI entry point: launch the LTG Combat playtest cockpit.

    ltg-combat-cockpit              # serve on 0.0.0.0:8001 and open a browser
    ltg-combat-cockpit --port 9001  # pick a port
    ltg-combat-cockpit --reload     # auto-reload on code changes (dev)
    ltg-combat-cockpit --no-browser # don't open a browser

Equivalently: `python -m ltg_combat cockpit`. One FastAPI app serves both the API
and the static front end, so this single command is the whole tool.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import uvicorn

# Import string (not the app object) so --reload works.
APP = "ltg_combat.server:app"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="ltg-combat-cockpit", description="Launch the LTG Combat playtest cockpit."
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8001, help="port (default: 8001)")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = parser.parse_args(argv)

    browse_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{browse_host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    print(f"Starting LTG Combat cockpit at {url}  (Ctrl-C to stop)")
    uvicorn.run(APP, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
