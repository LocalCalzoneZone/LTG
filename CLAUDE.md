# CLAUDE.md — working in the LTG repo

LTG (Langelier Tactical Game) is a personal project: a tactical card-combat RPG. It combines a **pure, deterministic combat engine** with an **LLM-generated RPG layer** (encounters, adventures, towns, quests, campaigns) and generated art. It is played solo or as LAN co-op, including a non-technical player on a standalone Windows install.

## Read first — the docs map

| Need | Read |
|---|---|
| The rules (canon) | [docs/game_design.md](docs/game_design.md), **GDD v2**, the current rules in one place. Each section cites the design § where the rule was decided. |
| Where code lives, contracts, checklists | [docs/architecture.md](docs/architecture.md): module and region maps, the wire protocol, "how to add a verb / keyword / event / hook" |
| LLM generation | [docs/generation.md](docs/generation.md): writers, timing, reader matrix, gates, repair loop, models, taste rules |
| Tunable numbers (`T-NN`) | [docs/balance_register.md](docs/balance_register.md) |
| What is not built or not tested yet | [docs/roadmap.md](docs/roadmap.md): milestones and objectives, with statuses verified against code |
| Why a rule is the way it is | [docs/design/](docs/design/README.md): v1 GDD and Design Updates 01–24 (**history**; later docs win; GDD v2 wins over all of them) |
| UI look and feel | [apps/game-ui/DESIGN_SYSTEM.md](apps/game-ui/DESIGN_SYSTEM.md), "Brasswork & Ink" |

**Resolving citations in code comments.** `§D17-6.3` means Design Update 17. The prefix table is in [docs/design/README.md](docs/design/README.md): `§R`=01, `§M`=02, `§E`=03, `§F`=04, `§P`=05, `§E6`=06, `§X`=07, `§D8`…`§D24`=08–24, `§L`=15, `§A`=16. `§M-A.7` (Combat Abilities) exists only in code and in GDD v2 §9.9. `GDD §n` resolves to docs/game_design.md, which keeps the v1 numbering for §1–§11. `T-NN` means docs/balance_register.md.

## Commands

```bash
.venv/bin/python -m pytest tests/ -q            # ~1,350 tests, ~1.5 min. Bare python/pytest are NOT on PATH.
.venv/bin/python -m pytest tests/test_x.py -q   # one file
.venv/bin/ltg-game --no-browser --port 8020     # game server (or preview config "game")
npm --prefix apps/game-ui run dev               # client dev server :5173, proxies /api and /ws to :8020
npm --prefix apps/game-ui run build             # tsc --noEmit + vite build → apps/game-ui/dist/
.venv/bin/python -m ltg_combat harness          # the scripted §A/§C proof fights
```

- **Tests run in a sandbox.** `tests/conftest.py` points `LTG_CONTENT_DIR` / `LTG_LOADOUTS_DIR` / `LTG_SAVES_DIR` at a temp copy (content without art; empty loadouts and saves, like a clean clone) before any app import. So the suite is safe beside a live server, and tests must not rely on per-install characters: use `examples/` (`loadout_soren`…) or `tests/fixtures/`.
- **CI** (`.github/workflows/ci.yml`) runs pytest on Python 3.9 and 3.14, the client build with a `dist/` drift check, and `ruff check .` (unused imports; a new blind `except Exception` needs a reason and `# noqa: BLE001`).
- **Dependencies are pinned** in `constraints.txt`, applied from `requirements.txt`. Supported Python: 3.9–3.14 (`requires-python`).
- **Restart after Python edits.** The :8020 server is normally started without `--reload`, so it keeps serving stale code until restarted.
- **Commit `apps/game-ui/dist/` after every client change.** The Windows standalone install serves the committed bundle without Node. `tsc` runs only inside `build`.
- **Bump the Deckbuilder cache-busters.** On every edit to `apps/deckbuilder/frontend/app.js` or `styles.css`, bump the matching `?v=N` in `apps/deckbuilder/frontend/index.html`. Otherwise browsers keep the old script and buttons silently "do nothing".
- **Commit only when the owner asks.** Work on the current feature branch; `main` receives merges.

## Invariants — don't break these

1. **The engine is pure and deterministic.** `apps/combat/ltg_combat/engine.py` exposes `legal_actions(state)` and `apply_action(state, action)`. It does no I/O, calls no LLM, and has no presentation logic. The server submits synthetic actions through `apply_action`. The client computes no rules: it renders the snapshot and sends back an index into the legal-action list.
2. **LLMs author content at generation time only.** At runtime nothing asks an LLM to adjudicate a rule. Town dialogue is closed-vocabulary trees walked deterministically. Generated content crosses into code through bounded vocabularies (effect verbs, dialogue hooks, objective kinds) and must pass the validators. Motto: *infinite nouns, finite verbs.*
3. **Data directories have fixed roles.**
   - `content/` is git-tracked and is also the **live write target** for shared content: encounters, adventures, towns, `world/`, and generated art in `art/`. Editors and generators write and delete there, and a commit ships it. `content/equipment/` is the tracked base item catalogue, which the game only reads.
   - `apps/deckbuilder/loadouts/` is gitignored and per-install: characters, `llm_settings.json` (contains the API key — never print it), hidden-id files, user-made `equipment/`, lore, animations, and run-scoped art (spoils, cast, places).
   - `saves/` is gitignored and holds campaign runs.
   - Never write per-install data (characters, keys, saves) into `content/`. Content *generated* during play is the exception, on purpose (ruled 2026-09-25, M1.15): quest-accept adventures, their art, and campaign towns and worldbook edits write to `content/`. The owner generates and commits them; the keyless Windows install only pulls.
4. **Identity lives on the character file, history on the campaign, geography in the worldbook** (§D24-2). Deck, skills, and art are read live from the character file whenever a campaign save loads and at an in-session Continue. Levels, gear, purse, chronicle, and the priced keyword and attack mode live in the campaign's instanced copy.
5. **Dependencies run one way:** `core` ← `deckbuilder`, and `core` ← `combat` ← `game-server` ← `autoplay-tester`. The game server imports engine and serializer helpers, some of them private (`_character_dict`, `_ordered`…), so changing those changes the client contract. The Deckbuilder imports only `core`, which is why its `flavour.py` keeps its own copy of the retired-model map. The autoplay runner hand-copies some server balance constants; keep them in sync.
6. **Saves are made only at boundaries**: phase ends, quest accept, the inn, the interlude. There are no mid-combat saves (no `GameState` deserializer exists). Saves reference immutable content and never regenerate it.

## Conventions

- **Keep the canon current.** When you change a rule, update `docs/game_design.md` (and `docs/balance_register.md` for magnitudes) in the same change, and cite the §. Rulings made in code comments without a doc update are how the old docs drifted.
- **New design work** goes in `docs/design/ltg_design_update_25_<topic>.md` in the house shape: Part A canon, B implementation notes, C docs to update, D tests, E order. Once implemented, fold it into GDD v2 and tick `docs/roadmap.md`.
- **T-numbers.** Take the next free id, implement it as a named constant, cite `T-NN` in a comment, and add a register row.
- **Tests** are named `test_design_update_NN_<topic>.py` or `test_<feature>.py`, and pin rules, prompts (the `*_prompt()` builders are pure), and validators. Mock the LLM; never call a real API in tests.
- **UI** stays on the "Brasswork & Ink" theme:
  - No emoji; use the stroke icons in `Icons.tsx`.
  - Brass/gold is the ONLY interaction accent: gold means "you can act on this". Tide = player, blood = enemy, vigor = heal/buff, aether = channel/ability.
  - Sharp corners, hairline borders, Optima small-caps labels, and `prefers-reduced-motion` respected.
- **Generated text taste** (see docs/generation.md): the owner hates punchline-shaped "try-hard LLM dialogue". Aim for character shown through action, at most one wry voice per town, and contrast between levity and gravitas. Hero lore may colour a line but never drives a quest. PG, classic high fantasy by default.

## Settled decisions — don't re-propose these

- **Rejected (2026-09-05/06):** standing orders, relevance auto-pass, Move consequence previews, the swipe-trap change, Defend buffering the ally behind, stunned-turn instants, and any change to the SHAPE of Defend/Mitigate (Power scaling is intended). The reaction strip was removed, and so was the "Mitigate −N" label on the Mitigate cell; don't re-add either.
- **Gauge payouts** for churn, tanking, and downing are intended.
- **Enemies never Mitigate.** The owner wants MORE enemy control pressure, not less; don't tune the lockdown budget down.
- **Shipped content is not the quality bar.** Old scenarios were deleted for regeneration; gates are meant to fail weak content.
- **The Deckbuilder is custom-cards-only.** No MTG/Scryfall import UI. Legacy fields load but are pruned on save. Rarity stays as a balance lever.
- **Autoplay harness numbers are not balance evidence.** Keep the harness working and versioned (bump the policy `version` on heuristic changes). Use it for crash/anomaly detection and A/B deltas within one run. Don't cite its win rates as balance evidence or gate work on a run.
- **No quests hooked to hero backstory.** Knowledge is party-level. Party composition is fixed per campaign.
- **M1 rulings (2026-09-25),** recorded in the canon and the roadmap's M1 rows: generated play content stays in `content/`; an enemy's turn-scoped lockdown on a hero holds through that hero's next turn; a taunt respects the wall; enemy deathtouch downs heroes; enemies aim at party tokens; each struck hero may Mitigate their own hit; keyword and attack mode stay as the campaign bought them.

## Gotchas

- `engine.py` is about 8.2k lines. Navigate by function name using the region map in docs/architecture.md; line numbers drift.
- **Adding an effect verb touches about 10 places**: schema class, several engine classification sets, `RESOLVERS`, `translation.RENDERERS`, lints, serializer sets, the Deckbuilder JS copies, and the LLM vocabulary. Follow the checklist in docs/architecture.md.
- **`apps/game-ui/src/lib/types.ts` is hand-mirrored** from `snapshot.py`/`serialize.py`; change them together. `fx.ts` switches on engine log event type strings, and there is no registry, so keep the data keys in sync.
- `starting_cards` is an INT (opening-hand size), not a card list. Decks are 20 cards (1 mythic / 3 rare / 6 uncommon / 10+ common), advisory only.
- The dev venv is **Python 3.9.6**; CI also runs 3.14, and the Windows install uses a current Python. Don't use 3.10+ syntax (`match`, `X | Y` types at runtime), and never seed `random.Random` with a tuple (TypeError on 3.11+).
- Ultimates are `kind="activated"` on the stack. An Ultimate counter must use filter `action`, `ability` or `activated`; a `"spell"` filter is rejected at load (T-70).
- `content/scenarios/` is empty right now. Scenario mode generates on demand and needs an OpenRouter key in Options → LLM. Installs without a key play standalone encounters and adventures only.
- The design docs in `docs/design/` still contain stale "not yet built" status lines; trust `docs/design/README.md` and the roadmap instead.
- Before changing a rule, check [docs/roadmap.md](docs/roadmap.md) M1: many rules behave differently from their design docs, and those rows say which way the owner still needs to rule.
