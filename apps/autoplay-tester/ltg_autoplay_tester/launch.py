"""`LTG-Autoplay-Tester` / `ltg-autoplay-tester` — serve the playtest lab.

    ltg-autoplay-tester                  # serve on 0.0.0.0:8030, open browser
    ltg-autoplay-tester --port 9030
    ltg-autoplay-tester --no-browser
    ltg-autoplay-tester --reload         # auto-reload on code changes
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import uvicorn

APP = "ltg_autoplay_tester.app:app"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="ltg-autoplay-tester",
        description="Launch the LTG Autoplay Tester (the playtest lab).")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8030,
                        help="port (default: 8030)")
    parser.add_argument("--reload", action="store_true",
                        help="auto-reload the server")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't open a browser")
    args = parser.parse_args(argv)

    browse_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{browse_host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    print(f"Starting the LTG Autoplay Tester at {url}  (Ctrl-C to stop)")
    uvicorn.run(APP, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
