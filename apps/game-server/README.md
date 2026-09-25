# LTG-Game

The game server: a FastAPI + WebSocket authority around the pure combat engine
(`ltg_combat`), plus the RPG layer on top of it (adventures, towns, scenarios,
campaigns, runs and saves, LLM generation, art). It also serves the built client
from `apps/game-ui/dist/`.

The server submits engine-legal actions through `apply_action`; the client is a
view that renders the snapshot and sends back an index into the legal-action
list. Neither re-implements game rules.

The module map, the REST and WebSocket protocol, and the state contract live in
[docs/architecture.md](../../docs/architecture.md) §6–§8. This page only covers
launching.

## Launch

From the repo root, the launcher sets up the venv on first run, builds the
client if needed, serves everything on one port and opens a browser:

```bash
./LTG-Game.command
```

Or, once the monorepo is installed (`pip install -r requirements.txt`):

```bash
ltg-game                 # build the client if needed, serve on :8020
ltg-game --port 9000
ltg-game --host 127.0.0.1  # bind address (default 0.0.0.0)
ltg-game --no-browser
ltg-game --skip-build    # serve whatever is already in apps/game-ui/dist
ltg-game --rebuild       # force a client rebuild
ltg-game --reload        # auto-reload on Python edits
ltg-game --dev           # API/WS only (run the Vite dev server for the client)
ltg-start                # the game server and the Deckbuilder together
```

Without `--reload` the server keeps serving the code it started with, so restart
it after Python edits.

### Multiplayer

New Game creates a session and puts its id in the URL (`?s=<id>`). Share the URL
(the link icon in the top ribbon copies it; set the host address other players
reach this machine at under Options → Settings) so others can join the same
session. Each client claims one or more characters. A client may act only for
the characters it controls, and sees hand contents only for those; the server
enforces both.

## Development

```bash
# Terminal 1 — API/WS server (no client build)
ltg-game --dev

# Terminal 2 — Vite dev server (HMR); proxies /api and /ws to :8020
npm --prefix apps/game-ui install
npm --prefix apps/game-ui run dev
```

After any client change, run `npm --prefix apps/game-ui run build` and commit
`apps/game-ui/dist/`: the Windows standalone install serves the committed bundle
without Node.
