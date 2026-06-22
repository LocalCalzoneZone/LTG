"""CLI entry point: launch the LTG Deckbuilder.

    ltg-deckbuilder                 # serve on 0.0.0.0:8000 and open a browser
    ltg-deckbuilder --port 9000     # pick a port
    ltg-deckbuilder --reload        # auto-reload on code changes (dev)
    ltg-deckbuilder --no-browser    # don't open a browser

Equivalently: `python -m ltg_deckbuilder`. The FastAPI app serves both the API
and the static frontend, so this single command is the whole authoring tool.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import uvicorn

# Import string (not the app object) so --reload works.
APP = "ltg_deckbuilder.app:app"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="ltg-deckbuilder", description="Launch the LTG Deckbuilder."
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = parser.parse_args(argv)

    # 0.0.0.0 isn't a browsable address; point the browser at localhost.
    browse_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{browse_host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    print(f"Starting LTG Deckbuilder at {url}  (Ctrl-C to stop)")
    uvicorn.run(APP, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
