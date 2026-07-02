# LTG-Game

A real, playable multiplayer game UI for the Langelier Tactical Game — a new
frontend + server layer on top of the existing headless combat engine
(`ltg_combat`). It is a **sibling** to the playtest cockpit: both consume the same
engine; neither replaces the other.

The server is an authority/relay around the engine; the client is a pure
view + input layer. **Neither re-implements game rules** — all legality,
resolution, ordering and state transitions come from the engine
(`legal_actions` / `apply_action`). See [`INTERFACE_NOTES.md`](../../INTERFACE_NOTES.md)
at the repo root for the engine ↔ UI field reconciliation this is built on.

## Launch

From the repo root (sets up the venv on first run, builds the client if needed,
serves everything on one port, opens a browser):

```bash
./LTG-Game.command
```

Or, once the monorepo is installed (`pip install -r requirements.txt`):

```bash
LTG-Game                 # ≡ ltg-game — build client if needed, serve on :8020
LTG-Game --port 9000
LTG-Game --no-browser
LTG-Game --skip-build    # serve whatever is already in apps/game-ui/dist
LTG-Game --rebuild       # force a client rebuild
LTG-Game --dev           # API/WS only (run the Vite dev server for the client)
```

This launches independently of, and without disturbing, the cockpit
(`ltg-combat-cockpit`).

### Multiplayer

`New Game` creates a session and puts its id in the URL (`?s=<id>`). Share that URL
(the seat bar's **🔗 Copy invite** button) so others can join the same session. Each
client **claims** one or more characters (single-player: **Claim all**). A client may
act only for characters it controls and sees hand contents only for those characters
(enforced server-side).

## Development

```bash
# Terminal 1 — API/WS server (no client build)
LTG-Game --dev

# Terminal 2 — Vite dev server (HMR); proxies /api and /ws to :8020
cd apps/game-ui && npm install && npm run dev
```

## Architecture

```
Browser (React/TS/Vite/Tailwind)  ──WebSocket (live state + actions)──►  LTG-Game server (FastAPI + WS)
        many clients, one session  ──REST (lobby: setup/create/join)───►    SessionManager → engine
                                                                             game-state (authoritative)
                                                                                    │
                                                                                    ▼
                                                                   existing headless engine (ltg_combat)
```

- **Server** (`apps/game-server/ltg_game_server`): `app.py` (REST + WS + static),
  `session.py` (authoritative state, seats, gating), `snapshot.py` (seat-filtered
  state contract — reuses `ltg_combat.serialize`), `content.py` (setup-options),
  `launch.py` (`LTG-Game`).
- **Client** (`apps/game-ui/src`): a WS-driven store (`lib/store.ts`) is the single
  source of truth; components are pure views; every interaction submits an
  engine-legal action **index** the server re-validates.

### REST
- `GET  /api/setup-options` — available characters + encounters.
- `POST /api/games` `{character_ids, encounter_id}` → `{session_id}`.
- `GET  /api/games/{id}` — existence/status (for joining by URL).

### WebSocket `ws /ws/{session_id}`
- client→server: `claim_seat`, `release_seat`, `submit_action {action:{index}}`, `heartbeat`.
- server→client: `hello`, `seats`, `state` (seat-filtered full snapshot), `prompt`,
  `error`, `game_over`.

## Phase 1 scope

In: lobby/New Game, sessions, single- & multi-player seats with hidden-hand
filtering, live WS state sync, full battlefield/side-panel/bottom-bar layout,
select→action→target (+ cancel), choose-one modal, move row picker, mana display +
start-of-turn colour choice, priority/reaction prompts, zone modals, channeling
indicators, enemy-disappears-on-leave-play, downed treatment, game-over overlay.

Deferred (hooks built, not features): animation polish, art asset pipeline (grey
placeholders), auth/access control, persistence beyond in-memory + resync,
diff-based sync, boss support (the engine has none yet — the client's boss visual
hooks stay dormant; see `INTERFACE_NOTES.md` §4.3).
