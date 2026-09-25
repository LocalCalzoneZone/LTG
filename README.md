# Langelier Tactical Game (LTG)

LTG is a **tactical card-combat RPG** for a small party (1–4 player-characters), played solo or as LAN co-op in the browser. Each hero fights with a hand-built 20-card deck on a three-row battlefield. The party takes on **generated** enemies, adventures, towns, and campaigns, and nearly everything is illustrated with generated art.

The defining idea is a **hard wall between generation and resolution**:

- **Generation**: an LLM writes the content at authoring time. That covers enemies, encounters, three-phase adventures, towns and their residents, quests and dialogue, campaign interludes, and card flavour.
- **Resolution**: the rules of combat and the RPG layer are **pure deterministic code**. No LLM ever adjudicates a rule, computes a number, or picks a legal move at runtime.

The bridge is a **bounded vocabulary**: effect verbs for cards and enemies, and hooks for dialogue. An LLM can compose it freely, and code can execute it exactly. *Borrow the grammar, own the numbers; infinite nouns, finite verbs.*

> **Playing on a Windows machine with no dev tools?** Follow [WINDOWS_INSTALL.md](WINDOWS_INSTALL.md) (or [LTG_Install_Guide.html](LTG_Install_Guide.html)), then read the [player guide](ltg_player_guide.html).

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt       # editable installs: core + all apps
ltg-start                             # game (:8020) + Deckbuilder (:8000) in one window
```

| Command | Double-click launcher | Port | What it is |
|---|---|---|---|
| `ltg-start` | `LTG-Start.command` / `.bat` | 8020 + 8000 | **The whole table**: game plus Deckbuilder. In-app Quit stops both. |
| `ltg-game` | `LTG-Game.command` / `.bat` | 8020 | **The game**: React client, multiplayer seats, generation, scenarios and campaigns |
| `ltg-deckbuilder` | `LTG-Deckbuilder.command` / `.bat` | 8000 | **Authoring**: build characters and custom 20-card decks; brief, lore, and animations |
| `ltg-autoplay-tester` | `LTG-Autoplay-Tester.command` / `.bat` | 8030 | Playtest lab: scripted-policy probes, gauntlets, verdicts |
| `ltg-combat-cockpit` | — | 8001 | Engine debugger with time travel, not a game |
| `ltg-combat repl` | — | — | Play a fight in a terminal |

Every server except `ltg-start` takes `--port`, `--host`, `--reload`, and `--no-browser`. They bind `0.0.0.0` so LAN players can join at `http://<your-ip>:8020`. On first run `ltg-game` builds the React client if Node is present. Otherwise it serves the committed `apps/game-ui/dist/`.

**Generation needs an OpenRouter API key** (Options → LLM). Art uses either OpenRouter or a local ComfyUI server (Options → LLM → art backend).
- Without a key you can still play every standalone encounter and adventure in `content/`.
- Scenario mode writes its story on demand, and the library of pre-generated scenarios is currently empty (see the [roadmap](docs/roadmap.md)).

## What's in the game

| Area | In short |
|---|---|
| **Combat** | Rows and a melee "wall". A resolution stack with per-character reaction windows. Veiled enemy intents you answer before they land. Mana that curves up. Channeled enchantments that break under heavy hits. Mitigate and Defend. Skill, Ultimate, and a gauge. Corpses and necromancy, afflictions, forced movement, objectives, bosses with enrage and execute windows. |
| **Characters** | A points-buy build (HP, mana, opening hand, Power, one keyword) plus a custom 20-card singleton deck (rarity quotas) made in the Deckbuilder. Optional brief, lore, and animated portrait panels. |
| **Adventures** | Three fights in a row. HP carries over between them, and you level up between phases. |
| **Scenario mode** | A town with residents, dialogue, and shops, and a three-act story against one villain. Each act is a town visit plus one generated adventure. Gear, consumables, loot, and gold. Branching saves. |
| **Campaigns** | A fixed party continues scenario after scenario. After a victory the party rests in town (the *interlude*) and chooses where the story goes next. A shared **worldbook** records every town. |
| **Generation** | LLM writers for encounters, adventures, towns, arcs, acts, and interludes, each gated by validators. Generated art (portraits, enemies, scenes, towns, items) and image-to-video panel animations. |

## Documentation

| Document | For |
|---|---|
| [docs/game_design.md](docs/game_design.md) | **The rules**, current canon (GDD v2) |
| [docs/generation.md](docs/generation.md) | How content is generated: writers, timing, gates, models, taste rules |
| [docs/balance_register.md](docs/balance_register.md) | Every tunable number (`T-NN`) with its current value |
| [docs/architecture.md](docs/architecture.md) | Codebase map, wire protocol, how-to checklists |
| [docs/roadmap.md](docs/roadmap.md) | What's not built or not tested yet, as milestones and objectives |
| [docs/design/](docs/design/README.md) | Design history: v1 GDD and Design Updates 01–24, with a guide to the `§` citations in code |
| [docs/reviews/](docs/reviews/2026-09-24/README.md) | Dated review records: the [2026-09 whole-game review](docs/reviews/2026-09/README.md) and the [2026-09-24 consolidation](docs/reviews/2026-09-24/README.md) findings |
| [ltg_player_guide.html](ltg_player_guide.html) | The player-facing guide |
| [apps/game-ui/DESIGN_SYSTEM.md](apps/game-ui/DESIGN_SYSTEM.md) | The "Brasswork & Ink" UI design system |
| [apps/deckbuilder/CUSTOM_CARD_SCHEMA.md](apps/deckbuilder/CUSTOM_CARD_SCHEMA.md) | The custom-card import format (e.g. for LLM-drafted decks) |
| [CLAUDE.md](CLAUDE.md) | Orientation for coding agents (and a fast primer for humans) |

## Repository layout

```
core/ltg_core/          shared library: schema (effect vocabulary, cards, characters, items),
                        card-text renderer, lints, self-updater
apps/combat/            the deterministic engine (+ text REPL, debugging cockpit, autoplay policies)
apps/game-server/       the game server: sessions and seats, snapshots, scenario/campaign layer,
                        dialogue, economy, LLM writers, art, saves
apps/game-ui/           the React + Vite + Tailwind client; dist/ is committed
apps/deckbuilder/       character and deck authoring (FastAPI + static SPA)
apps/autoplay-tester/   the playtest lab over the autoplay harness
content/                shared, git-tracked content, also the live write target
                        (encounters, adventures, towns, world/, art/; equipment/ = item catalogue)
examples/               fixture loadouts and encounters (the §A/§C proof fights)
tests/                  pytest suite (~1,350 tests)
docs/                   canon, architecture, generation, register, roadmap, design history
```

Per-install data is gitignored: characters, settings (including the API key), and user-made items live in `apps/deckbuilder/loadouts/`, and campaign saves in `saves/`.

## Developing

```bash
.venv/bin/python -m pytest tests/ -q     # runs in a temp sandbox; safe beside a live server
npm --prefix apps/game-ui run dev        # client dev server :5173 → proxies to :8020
npm --prefix apps/game-ui run build      # then commit apps/game-ui/dist/
.venv/bin/python -m ltg_combat harness   # the hand-traced §A/§C fights, asserted step by step
```

The engine's whole contract is `legal_actions(state)` and `apply_action(state, action) → (state', events)`. Every client drives it through only those two functions and owns zero rules. See [docs/architecture.md](docs/architecture.md) for the module map and the checklists for adding an effect verb, a keyword, an enemy condition, target rule or trigger, or a log event the client animates. [CLAUDE.md](CLAUDE.md) lists the invariants and settled decisions.

## Status

Built: the combat engine and its full vocabulary, the enemy framework and AI, adventures, objectives, the autoplay harness, scenario mode (towns, dialogue, gear, economy, branching saves), campaigns with the interlude and worldbook, and generation for all of it.

Next ([docs/roadmap.md](docs/roadmap.md)):
- fixing the verified bugs first (M1): a Python 3.11+ crash, an unlimited-Skill loop, campaign-flow bugs, and rules faults;
- making the board legible (status, threat, and boss state on the cards; a working Chronicle);
- a cheaper loop for playtesting the campaign layer;
- a faster generation pipeline;
- NPCs that remember the party;
- voice (narrator, barks);
- session hardening for co-op.
