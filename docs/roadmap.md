# LTG roadmap — milestones & objectives

**As of 2026-09-25** (M1–M3 merged; M4 built on branch `Milestone-M4`; statuses of other milestones as checked at `a2cce25`, 2026-09-24). This page lists everything designed but not built, built but never tested, or verified as broken. Its sources are:

- the design history (v1 GDD, Updates 01–24);
- the 2026-09-02 review briefs;
- the owner's retune notes;
- the 2026-09-24 consolidation, which checked every row against the code.

Proposals that come from no design document are marked *Proposed*. They need a design pass (a numbered update in [design/](design/README.md)) before anyone builds them. Rules that already work are in [game_design.md](game_design.md), not here.

**How to use it.**
- Pick a milestone and work its objectives top-down; each row cites its sources.
- When one lands, delete the row or move it to *Done* (bottom), and fold any rule change into the canon.
- Milestones M2, M3 and M4 touch different code (client / tooling / `llm.py`), so they can run in parallel.

**Status**

| Tag | Meaning |
|---|---|
| **Bug** | The code contradicts the canon or its own design (verified). |
| **Not built** | Designed, no implementation. |
| **Partial** | Some parts exist (the row says which are missing). |
| **Untested** | Built, but the validation or playtest its design required never happened. |
| **Decide** | Needs an owner ruling before anyone builds it. |
| **Proposed** | Not in any design doc yet. |
| **Doc** | Documentation debt. |

**Size:** S ≈ under a day · M ≈ 1–3 days · L ≈ a design update's worth.

**Source keys:**
- `§…` design sections, resolved in [design/README.md](design/README.md);
- `R2.x` / `R3.x` / `R4.x` = the steps of review briefs 02 / 03 / 04 in [reviews/2026-09/](reviews/2026-09/README.md);
- `A-/B-/C-nn` = rows of the 2026-09-24 [sweeps](reviews/2026-09-24/sweeps.md);
- "GDD v2 §n notes", "arch notes", "generation notes", "register notes" = the code-verified [findings](reviews/2026-09-24/findings.md) recorded while GDD v2 and its companion docs were written;
- `obs.` = observed in play on 2026-09-24.

## Milestones at a glance

| | Milestone | Why | Objectives |
|---|---|---|---|
| **M0** | Foundations | Make the project cheap and safe to work on: docs, tests, CI, environment | 6 |
| **M1** | Make it correct | **Done 2026-09-25**: every row fixed or ruled, each with a test. | 37 |
| **M2** | Legibility | **Done 2026-09-25** except M2.22's clip coverage (owner). | 22 |
| **M3** | The playtest loop | **Tooling done 2026-09-25** (M3.1–M3.4, M3.12); M3.8 and M3.11 ruled and done. The owed playtests and M3.5 remain. | 12 |
| **M4** | Generation pipeline | **Done 2026-09-25** (Design Update 25, rulings confirmed); real-model judging owed. | 18 |
| **M5** | The world remembers | NPCs and towns react at runtime, not only in the next act's writing | 11 |
| **M6** | Economy & progression | Gold, gear and the deck get a job | 10 |
| **M7** | Voice & narration | Narrator, barks, party lines, and the sound of the world | 9 |
| **M8** | Co-op & distribution hardening | LAN sessions survive faults; the Windows install updates cleanly | 13 |
| **M9** | Contracts & code health | Explicit schemas, event registry, generated types, verb traits | 9 |
| **M10** | A trustworthy balance instrument | A stick good enough that balance questions stop costing the owner's evenings | 10 |
| **M11** | Later, by design | Deferred on purpose, or waiting on a need | — |

Suggested order: M0 → M1 → (M2 ∥ M3 ∥ M4) → M5 → M6 → M7, with M8–M10 interleaved as capacity allows. **M3's campaign playtest (M3.6) should come right after M1's crash and campaign fixes (M1.1–M1.9).**

---

## M0 · Foundations

*Done when:* a clean clone passes CI, tests can run beside a live server, and the docs match the code.

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M0.1 | **Docs consolidation.** GDD v2, generation, register, architecture, roadmap, design-history index, `CLAUDE.md`, README | Done 2026-09-24 | — | A-01, A-08…A-18, A-34, B-11, B-21, B-58, B-59, C-12, C-14, C-15, C-17, C-38, C-64 |
| M0.2 | **Test isolation.** Done differently from the plan: not a per-test `tmp_path` fixture (import-time path constants would dodge it) but a per-suite sandbox. `tests/conftest.py` sets `LTG_CONTENT_DIR` / `LTG_LOADOUTS_DIR` / `LTG_SAVES_DIR` before any app import (read by `content.data_dir` and the Deckbuilder). The flock and the "don't test while hosting" caveat are gone. Three tests that relied on the owner's `loadouts/` now use `examples/` or `tests/fixtures/soren.json`. | Done 2026-09-25 | — | R3.2.1 |
| M0.3 | **CI** (`.github/workflows/ci.yml`): pytest on Ubuntu 3.9 and 3.14 (the suite includes the soak smoke slice), a non-blocking Windows 3.14 job, `npm run build` with a `dist/` drift check, and `ruff check .` (F401 fixed; the 46 existing BLE001 grandfathered with `noqa`). **Still open:** a first green run on GitHub, then branch protection on `main` requiring the checks (a repository setting for the owner). | Partial | S | R3.2.2; §D12-3.7; B-06 |
| M0.4 | **Pin the environment.** `constraints.txt` (every compiled pin has 3.9 and Windows 3.14 wheels), applied from `requirements.txt` with `-c`, so the launchers, the updater and CI all use it; `requires-python >=3.9,<3.15`; `WINDOWS_INSTALL.md` now says which Python to download. | Done 2026-09-25 | — | R3.2.4 |
| M0.5 | **Doc debt outside the canon:** the player guide (Magic cards, "Act I is ready at once"), `apps/game-server/README.md` (rewritten, points at architecture §6–§8), `DESIGN_SYSTEM.md` (veiled intents, 45/55), both panel-animation docs (`revive`, `victory`, collision priority, the `channel` loop as M2.22), the `schema.py` docstring. | Done 2026-09-25 | — | B-35, C-12; arch notes |
| M0.6 | **Stale code comments**, all fixed: the runner and `run_adventure` (T-57), `_adventure_request_block` (T-62 ramp), `enrage_scale`, `art.py`, `_generate_locked` (now says it takes no lock; M1.8), `validate_materialization` (M4.11), the `jobs.py` states, the drop docstrings, the `RESOLVERS` `disable` note, `adventure.POINTS_PER_LEVEL`, `app.generate_scenario`. Dead `prevent_pool` / `parry_reduce` removed (engine, state, serializer, REPL, cockpit, the client's `reduced` fx case). | Done 2026-09-25 | — | register notes; GDD §3–§4 notes |

## M1 · Make it correct

*Status: done 2026-09-25.* *Done when:* every row is fixed or ruled on, and each fix lands with a test. M1.1–M1.3 come first because they crash or break play outright. M1.4–M1.9 gate the campaign playtest (M3.6).

**Crashes and runaway loops**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.1 | **Python 3.11+ crash.** Fixed: `engine._move_shuffle` seeds with the str `f"{rng_seed}:shuffle:{n}"`, pinned by `test_seeded_shuffle_is_pinned_and_runs_on_every_python`; CI runs 3.14 (M0.3). Seeded in-game shuffle orders changed once. | Done 2026-09-25 | — | arch notes |
| M1.2 | **Unlimited Skill.** Fixed: the Skill is offered once per turn (`"skill" not in proactive_modes`), so a refreshed Skill comes back for a later turn; pinned by `test_a_self_refreshing_skill_is_used_once_per_turn_not_looped`. | Done 2026-09-25 | — | arch notes |
| M1.3 | **`python -m ltg_combat validate` crashed.** Fixed: the stale `engine.run` is retired (the engine does no I/O); the CLI prints the report itself (`tests/test_combat_cli.py`). | Done 2026-09-25 | — | arch notes |

**Campaign and scenario flow**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.4 | **Phase III objectives were vetoed.** Fixed: the `save_adventure` pre-check is gone; `_validate_adventure`'s §D23-5 shape check decides (`test_save_adventure_keeps_a_modifier_objective_on_phase_three`). | Done 2026-09-25 | — | C-22; §D23-5 |
| M1.5 | **Unreachable foreshadow topics.** Fixed (short-term): `validate_interlude` refuses a foreshadow on an NPC with an interlude tree, and the planner prompt says so. Full fix: M5.3. | Done 2026-09-25 | — | C-45; §D24-5.1 |
| M1.6 | **The hook's bridge reaches Act I.** Fixed: a continuation's Act I writer gets `_hook_block` (`hook=` on `generate_act`). Also fixed: `chosen_hook()` dropped the player's note on a proposed hook, so neither writer saw it. | Done 2026-09-25 | — | C-44; §D24-5.3 |
| M1.7 | **Live identity at an in-session Continue.** Fixed: `content.refresh_party` runs on load and at Continue. Ruled 2026-09-25: keyword and attack mode stay as the campaign bought them (`BUILD_LOCKED_FIELDS`); a differing file gets a splash notice. | Done 2026-09-25 | — | C-47; §D24-6; GDD v2 §14 notes |
| M1.8 | **Worker threads.** Fixed: `jobs.call_locked` runs every read and write of the session under its lock on the event loop; the act writer, the road ahead, the adventure and interlude jobs and the art painters use it, and only the LLM calls run unlocked (`tests/test_worker_locking.py`). `load_save` / `continue_run` stay synchronous (M8.4). | Done 2026-09-25 | — | C-65; R3.1.5 |
| M1.9 | **A failed materialization no longer wedges the town.** The splash (and a banner) offer *Try again* (`retry_materialize`), which re-runs the act or, when a continuation never began, the whole road ahead; a failure also writes an act-less `act_start` save so a reload retries. Any exception counts. | Done 2026-09-25 | — | R3.1.6 |
| M1.10 | **Rest is guaranteed.** Fixed at runtime rather than in the validator: when no tree at the inn offers `rest` this act, the inn's first resident gets "Take a room." (`ScenarioRun._with_room`). | Done 2026-09-25 | — | GDD v2 §14 notes |
| M1.11 | **Reward items no longer vanish.** Room is checked on the copies the items land on (`_gear_loadouts`: the live adventure's while it is up), and a plan that no longer fits is refused whole, naming who is full. | Done 2026-09-25 | — | R4.3.6; GDD v2 §14 notes |
| M1.12 | **Creation leftovers are banked.** Ruled 2026-09-25: a campaign banks the points a hero was built without (`_creation_leftover`), as a lone adventure does. | Done 2026-09-25 | — | GDD v2 §14 notes |
| M1.13 | **`town:` lore gates.** Fixed: the run passes its `town_id` to `generate_act` (the composed town carries no id). | Done 2026-09-25 | — | GDD v2 §14 notes |
| M1.14 | **The first arc writer.** Fixed: Town + New passes `opening_party_state` (briefs, default situations) and the world block. | Done 2026-09-25 | — | generation notes |

**Data safety**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.15 | **Run content in `content/`.** Ruled 2026-09-25: play-time generated content (run adventures and their art, campaign towns, worldbook edits) stays in tracked `content/`, because the owner generates and commits it and the keyless install only pulls. The 13 old `run_only` adventures, their phase files and art were deleted. | Done 2026-09-25 | — | B-39, C-62; §D17-3.3 |
| M1.16 | **Name collisions.** Fixed: a NEW encounter, adventure (and its phase ids) or town takes the next free id (`content.fresh_id`); an explicit id still edits in place. | Done 2026-09-25 | — | generation notes |

**Rules engine** (verified in code; GDD v2 records the current behaviour)

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.17 | **One guard per struck character.** Ruled 2026-09-25 (§L-5): every hero a swipe strikes may Mitigate their own hit; `StackItem.mitigations` maps protected → guard, and a covered character is not offered again. | Done 2026-09-25 | — | §L-5; `StackItem.mitigate_by` |
| M1.18 | **Taunt and the wall.** Ruled 2026-09-25, replacing §R-11's "regardless of row": a taunt draws only what can reach the taunter (a melee swing at a rear taunter stays where it was aimed, no fizzle, no deflection), and an active taunt binds the enemy's hostile rules as well as its swing (`_taunt_reaim`, `_component_target`). | Done 2026-09-25 | — | §R-11 |
| M1.19 | **Curve-up colours.** Fixed: the lock offers the character's colours (the spec's `colors`), and a `choice` ramp or ritual is a pick at cast (`_color_options`, `StackItem.color`); `tests/test_mana_colors.py`. | Done 2026-09-25 | — | §4.4 |
| M1.20 | **Sap and reservation stack.** Fixed: the pool refreshes to capacity − sap − reserved (`_free_capacity`), at once and at every refresh. | Done 2026-09-25 | — | code ruling 2026-08-21 |
| M1.21 | **Countering a basic swing** pays its damage once: `_denied_value` no longer adds the swing's own `deal_damage` on top of `attack_power`. | Done 2026-09-25 | — | gauge rework |
| M1.22 | **Enrage waves.** Ruled 2026-09-25: a boss's Enrage and a race escalation are exempt from the T-27 cap (`StackItem.uncapped_spawns`), so the party-size wave spawns whole; `engine.TOKEN_CAP`; a clipped spawn logs `token_cap`. | Done 2026-09-25 | — | register notes |
| M1.23 | **Enemy rules skipped for want of a target.** Fixed: a spell reaches as a ranged body even from Front (`_component_reach`), and a rule whose verbs are all untargeted declares with nobody pickable (`_needs_a_pick`). | Done 2026-09-25 | — | §D23-3; GDD v2 §9 notes |
| M1.24 | **Easy bosses.** Fixed: `apply_boss_difficulty` stamps `double_intent: False` on Easy, so the build path's fallback can't re-stamp it, and `encounter_for` carries the made-at difficulty. | Done 2026-09-25 | — | GDD v2 §9 notes; T-54 |
| M1.25 | **Lockdown bites.** Ruled 2026-09-25: an enemy's turn-scoped lockdown on a hero (Silence/Pacify, wound, sap, hostile modifier, taunt) holds through the hero's next turn (the `nt_*` layer, `PreventTag.linger_turn`, `taunted_turn`, `_expire_lingering`), and a hero's one-shot Pacify/Silence on an enemy cancels its declared intent. | Done 2026-09-25 | — | GDD v2 §9 notes; lockdown ruling 2026-08-21 |
| M1.26 | **Enemy-rule findings.** Ruled 2026-09-25. Changed: a wound into the window enrages at once; a minion's `post_enrage` / `pre_enrage` gate reads its boss; neglect counts party-caused drops and applies to bosses only. Kept as canon: enemy raises are permanent; `survive` can't be won early while reinforcements wait; the 2× bodies rule skips hand-authored standalone encounters. | Done 2026-09-25 | — | GDD v2 §9, §12 notes |
| M1.27 | **Four rulings, all changed (2026-09-25):** (a) regen ticks pay the placer, Skill mana earns gauge; (b) amplify before Mitigate (h×m − X; a full Mitigate still spends the tag); (c) consumables stack as `activated`; (d) enemies aim at party tokens and grounded tokens wall (`_foes_of_enemies`). | Done 2026-09-25 | — | GDD v2 §4 notes |
| M1.28 | **Stale lines.** Ruled 2026-09-25: code kept for the bounce row, released channel mana and round-1 double intents. First strike narrowed: its only legal targets are enemies with an action on the stack. | Done 2026-09-25 | — | GDD v2 notes; A-49 |
| M1.29 | **Small fixes**, all done: the infect gloss (§D22-2 counters); `serialize._mitigate_value`'s floor of 1; `"drain"` removed from `_DAMAGE_KINDS` and the taunt gate; the sheet's effective level now reads earned potential + gear, like the budgets. | Done 2026-09-25 | — | A-42; arch and §14 notes |
| M1.30 | **Enemy deathtouch works.** Ruled 2026-09-25: connecting deathtouch damage executes any victim — an enemy (a boss only in its window), a party token, or a hero, who is downed. The enemy prompt now asks for low Power, no area damage, one per encounter. | Done 2026-09-25 | — | GDD v2 §7 notes |
| M1.31 | **§5–§11 rulings (2026-09-25).** Changed: indestructible is immune to destroy and deathtouch and floors life loss and poison at 1; `*_base_power` excludes counters (`counter_power`); enemy spells fire `spell_cast`; an enemy channel's event-triggered `channel_drop` works; an untargeted pick that left the field fizzles; a taunt spares heals. Kept: one post-resolution reaction per resolution for the whole enemy side. | Done 2026-09-25 | — | GDD v2 §5–§11 notes |

**Server and session**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.32 | **WebSocket guards.** Fixed: every message goes through one guarded `_dispatch`; bad frames and any fault answer with an `error` frame and a broadcast, keeping the seats. The pacer and confirm timer print faults; `_AUTO_CAP` warns; `get_running_loop` (`tests/test_ws_guards.py`). | Done 2026-09-25 | — | R3.1.1 |
| M1.33 | **The log is seat-filtered.** A teammate's `draw` / `scry` names no card (`snapshot._seat_log_line`). | Done 2026-09-25 | — | arch notes |
| M1.34 | **Server-side gates.** Start Adventure is refused inside a location, and `set_situation` outside the rest screen. | Done 2026-09-25 | — | GDD v2 §14 notes |
| M1.35 | **The veil holds in the log.** `intent_redirect` and `intent_spoiled` are rewritten without the intent's name in the seat feed. | Done 2026-09-25 | — | GDD v2 §5 notes; §D8-1.4 |
| M1.36 | **Deckbuilder port.** `ltg-start` reads `LTG_DECKBUILDER_PORT` / `LTG_GAME_PORT`, passes them to both apps, and the client's Edit link asks `/api/app/info`. | Done 2026-09-25 | — | arch notes |
| M1.37 | **Adventure runs.** Ruled 2026-09-25: the "Save as a run" option is gone from New Game (Load Game never listed those runs); the server path stays. | Done 2026-09-25 | — | GDD v2 §14 notes |

## M2 · Legibility — the board explains itself

*Status: done 2026-09-25* on branch `Milestone-M2`, except M2.22's clip coverage (the owner's to generate). Server-side fields are pinned in `tests/test_board_legibility.py`; the client was checked in the browser at 1440×900.

*Done when* all of these hold:
- after a kill, the Chronicle's newest line is the kill;
- an enraged boss wears its state;
- each hero shows how many enemies aim at it without hovering;
- a stunned enemy shows it;
- every dimmed card says why;
- hand text is readable without the OS tooltip.

(From brief 02 acceptance.)

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M2.1 | **Chronicle.** Fixed: the snapshot's log tail is oldest-first (the pin-to-bottom now shows the newest line), rows are keyed by `seq`, and the client merges every snapshot into the whole fight's history (`store.chronicle`, `mergeChronicle`), so `LOG_TAIL = 60` no longer limits what can be re-read. | Done 2026-09-25 | — | R2.1.1; obs. |
| M2.2 | **FX key mismatches.** Fixed: stun reads `enemy`/`character`; a channel suspension (`channeled`) slips away instead of imploding; placing regen counters plays a `regen` ring and chip (each Upkeep tick still heals with its own `heal`). | Done 2026-09-25 | — | R2.1.6 |
| M2.3 | **Arming survives unrelated broadcasts.** A snapshot keeps `armed` / `manaSelect` / the mode pick when its `legal_actions` equal the last one's. | Done 2026-09-25 | — | R2.2.8 |
| M2.4 | **Party column overflow.** Fixed: the party's cards shrink together to fit the most crowded row (`partyCardWidth`, a `cqh` size container per row). | Done 2026-09-25 | — | obs. |
| M2.5 | **Card flavour in play.** `card_dict` ships `flavor`; the enlarged card (hand hover, Stack, Chronicle) shows it under the rules text. | Done 2026-09-25 | — | R4.2.5, C-53 |
| M2.6 | **Hover-enlarge** in the hand after 150 ms, and on keyboard focus; the enlarged card never clips its text. | Done 2026-09-25 | — | R2.2.1 |
| M2.7 | **Why-not chips.** The server names the reason per hand card (`engine.unplayable_reason`: downed, waiting, stunned, silenced, your turn only, turn spent, stance held, N short, needs {C}, no target); a seeded random-play test pins that a card has a reason exactly when no cast of it is offered. | Done 2026-09-25 | — | R2.2.2 |
| M2.8 | **Status chips** on hero and creature cards (`serialize.status_chips`, lockdown first: stunned, silenced, pacified, sapped, hamstrung, taunted; boons: action modifiers, protected, primed). | Done 2026-09-25 | — | R2.1.5 |
| M2.9 | **Boss state on the card.** An Enraged plaque and fury glow until death; a "swells +N" chip that pulses while the round still owes the boss a wound; a "guarded ×N" chip on a race target its guards shield. The objective banner stays up after it resolves, tinted by the outcome. | Done 2026-09-25 | — | R2.1.3 |
| M2.10 | **Beats.** `guards_down`, `objective_complete`, `withdraw` (brass) and `wave_deployed`, `reinforcements`, `escalation` (blood) flash the banner and wash the screen; `neglect` swells the boss; the Chronicle tints all of them plus `redeploy` and `risen`. | Done 2026-09-25 | — | R2.1.2 |
| M2.11 | **Persistent threat marks.** A blood chevron and count on each targeted hero (restamps when it changes); a redirect rings the new target ("drawn in"). Hairlines across the field were built and then rejected by the owner as clutter (2026-09-25). | Done 2026-09-25 | — | R2.1.4 |
| M2.12 | **Entrances.** Any creature or token new since the last snapshot rises in (brass sheen for allies, crimson for enemies): tokens, raised and risen dead, waves, reinforcements, redeploys. The banner previews the next arrival (`objective.next_arrival`: "next round · 2 Raiders"). | Done 2026-09-25 | — | R2.1.7 |
| M2.13 | **Sap and the classifier.** The mana widget shows "sapped −N" (`mana.sapped`); a forced `move` on a hero reads as interference, and corpse `control` / `consume_corpse` as summon when nothing hostile rides with them (GDD v2 §9 category list). | Done 2026-09-25 | — | R2.1.8 |
| M2.14 | **End Turn guard.** The button names what is left ("2 cards · attack"); with something castable or the Attack unused, the first click asks and a second ends the turn. Options → Settings → Play turns the confirm off. | Done 2026-09-25 | — | R2.2.5 |
| M2.15 | **Keyboard** (`lib/keyboard.ts`): Space/Enter Pass or End Turn (through its guard), 1–9 hand cards, A/D/M/V/S/U verbs, Enter to cast a completed payment; hand cards are `role="button"` keyboard stops. | Done 2026-09-25 | — | R2.2.4 |
| M2.16 | **Mana payment.** The fixed pips arrive paid (an X cast's generic from the colours the hand needs least), so clicks add only X; a Max X button; a non-X cast asks for the generic colour only when paying it would leave another card in hand short. | Done 2026-09-25 | — | R2.2.6 |
| M2.17 | **Damage preview while aiming** a basic attack: the hovered target reads "→ 4 · kills", "temp HP eats 2", "ward eats a hit", "breaks its channel". Server-side (`engine.attack_preview`), through the real `_deal_damage` on a copy. | Done 2026-09-25 | — | R2.2.7 |
| M2.18 | **Right-click** cancels on the board and the console only. A themed tooltip (`TooltipLayer`, driven by `data-tip`) replaces `title=` across the combat UI. | Done 2026-09-25 | — | R2.2.9 |
| M2.19 | **`damage` events carry `mode`** (`engine._damage_mode`); the client's label→mode guess (`stackModes`) is deleted. | Done 2026-09-25 | — | R2.1.6 |
| M2.20 | **The Ultimate cell.** Once primed it takes the Skill cell (split, Skill above, Ultimate below) as §D23-9 lays out; the column is the gauge, with a reason when it can't be used; the word "action" is gone. | Done 2026-09-25 | — | C-33 |
| M2.21 | **The turn diamond.** Ruled 2026-09-25: it stays on every sorcery and channel card, brass only while the card is castable, dim grey otherwise. | Done 2026-09-25 | — | C-34 |
| M2.22 | **Panel clips.** Built: a held stance loops its `channel` clip (the stance card's pick, else the default) under every other clip, skipped under reduced motion. **Still open (owner):** generate clips for Soren, Vay and Ys, and Bones's ultimate and victory. | Partial | M | B-27, B-30 |

*Rejected, do not re-add:* the reaction strip; the "Mitigate −N" label (removed in playtest, 2026-09-06); dashed threat hairlines or dashed outlines on the battlefield (clutter, 2026-09-25).

## M3 · The playtest loop

*Why:* seeing the interlude once takes nine fights, three adventure generations (≈$3 each on Opus 5 Fast) and three act generations. As a result the flagship Update 24 path has never been played, and every retune waits on a human evening.

*Done when:* the campaign loop and the retune watch-list have been played, and a fresh session can reach any campaign state in minutes for cents.

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M3.1 | **Jump-to states.** Built: `ltg_game_server/devstates.py`. It drives the real scenario verbs to `act`, `ready` or `defeat` (Act N), `between` (Act III's boss down, a true ledger, the interlude planned), `interlude` or `scenario2`, and leaves an ordinary run in `saves/` (1–2 s; about 6 s with autopilot fights). Stand-in writers need no key and write nothing to `content/`; `--writers llm` uses the real ones. New Game → Scenarios → Town + New → *Playtest · start at* (playtest profile), or `python -m ltg_game_server.devstates <state>`. | Done | M | advisory |
| M3.2 | **Autopilot fights.** Built: the ribbon's Autopilot toggle (playtest profile) lets `GreedyPolicy` play every party decision, a chunk at a time, off the lock; level-ups, spoils and towns stay with the players. A fight takes seconds. Its results are not balance evidence. | Done | M | advisory |
| M3.3 | **Cheap-model dev profile.** Built: Options → LLM → Playtest (or `LTG_PLAYTEST=1`) routes every text task, the Deckbuilder's flavour included, to `playtest_model` (Luna Pro by default) and idles the automatic art queues. | Done | S | advisory |
| M3.4 | **Record and replay LLM responses.** Built: `ltg_game_server/tape.py` inside `llm._chat`. Record, replay (a miss goes live and is recorded) and replay-only (never calls out, needs no key). A miss on the exact prompt hash replays the closest same-kind prompt. Stored in `loadouts/llm_tape/`. | Done | M | advisory |
| M3.5 | **Regenerate the scenario library** (`content/scenarios/` is empty). M4.5 (the avoid-list) is in place (2026-09-25). Decide whether library scenarios bring back a pre-baked Act I adventure, which gives an instant start and lets a keyless install play Act I. | Not built / Decide | S–M | C-05, C-04, B-52 |
| M3.6 | **Play the campaign loop.** Now cheap: jump to `interlude` (or `between`), rest at the inn, and choose each hook kind once (stay / neighbour / new). After the jump, play is live: a neighbour or new hook generates town, arc and Act I (use the playtest profile and the tape for flow; a premium model to judge). Kholdrun is deleted, so start from Karzum. | Untested | M | C-42; §D24 Part E |
| M3.7 | **Regenerate Karzum Act I with a briefed party** and judge the `# THE PARTY` block. The baseline is in git at `1ae6620^`. Judge on the premium model, not the playtest one. | Untested | S | C-41 |
| M3.8 | **Review the four backfilled worldbook entries.** Reviewed 2026-09-25: each notable matches its town file, and Karzum in `frostcap_peaks` agrees with the town's own text (the doc example was only stale prose). The book was a star through Azure, so a neighbour hook from Karzum, Millhaven or Nalindor could only name Azure. **Ruled 2026-09-25: add links.** Millhaven now joins Karzum (twelve days by the drove road) and Nalindor (nine days over the hill-marches). Karzum–Nalindor was dropped: the regions put the Frostcaps in the north and the Elderwood in the south. Still open: Karzum–Azure reads "six weeks", while a hook's `days` usually runs 4–14. | Done | S | C-43 |
| M3.9 | **Retune watch-list at the table.** Five open checks:<br>• §M-A.7 made the shipped components mitigatable<br>• Defend = base Power magnitude<br>• Enrage at party size 4<br>• gauge c = 20<br>• boss round-1 double intent<br>The lockdown budget is watched too, but only to push control pressure up; never tune it down. Jump to `ready` at the act you want and play the fight by hand (Autopilot results are not evidence). | Untested | M | C-01, C-02, C-39, C-40; T-54 |
| M3.10 | **Economy across a multi-scenario campaign:** T-79 prices, T-81 effective level, gold income versus sinks, and the free rest. `scenario2` jumps arrive levelled (spent through the policy's balanced plan) with spoils assigned, but no gold spent: shop for real. | Untested | M | B-36, B-40, B-57, A-33 |
| M3.11 | **Legacy content.** None of the library's 7 bosses had boss dials, and none of its 56 enemies had types or classes. **Ruled 2026-09-25:** a dial-less boss gets `enrage_round` 4 and `neglect` 1 at build (T-88, GDD §9.5), and the encounter and adventure library was purged for regeneration (towns, the worldbook and the equipment catalogue kept). Regenerated content passes the current gates, types and dials included. Until the owner regenerates and commits, a keyless install has only the bundled examples, and the jump-to builder's stand-in writers ride adventures strung from them. | Done | S–M | C-23, C-13 |
| M3.12 | **A-20:** a hero downed only by a turn-scoped wound stands back up when it expires (GDD v2 §4.2 step 5, §4.3). Pinned by `tests/test_wound_recovery.py`: the fall is real while it lasts (the others are paid their gauge), and a hero still at 0 HP once it lifts stays down. | Done | S | A-20; §R-13.1 |

## M4 · Generation pipeline

*Why:* an adventure was one call: a ≈23k-token system prompt, up to 64k output tokens, and a 15-minute timeout. A single bad enemy re-emitted all three phases, there was no caching and no transport retry, and quest-accept latency is the wait players feel. Gates were also looser than the prompts in several places.

**Built 2026-09-25** on branch `Milestone-M4`, designed in [Design Update 25](design/ltg_design_update_25_generation_pipeline.md) and pinned by `tests/test_design_update_25_pipeline.py` and `tests/test_design_update_25_gates.py`. Its four defaults were confirmed by the owner on 2026-09-25. **Owed:** judge real output on a premium model (§1 of [generation.md](generation.md): count cost, latency and repair rate). The new gates are stricter, so the first real runs show whether the prompt now teaches enough for them to pass on the first try.

**Latency, cost, resilience**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M4.1 | **Prompt caching.** `_wire_messages` marks the system prompt and the newest user turn `cache_control: ephemeral` for Anthropic and Google slugs (OpenAI caches by itself); the tape still hashes the plain messages. The three phase calls and their repairs share one cached prefix. | Done | S | advisory; §D25-2 |
| M4.2 | **Phased adventures.** An outline call (place, faction, boss and its Level, each phase's station, threat, signature and beats, the objective's phase), then one call per phase, each saved as it lands (`content.save_adventure_phase`, a partial wrapper hidden from pickers) and finalized after Phase III. In a run the job is ready at Phase I; II–III are written while Phase I is played, and a party that confirms a boundary early waits on the level-up screen until the phase lands (`Session.phase_landed`). A later failure shows at the boundary with a Retry that resumes; a save made mid-writing loads the fuller copy. **Ruled 2026-09-25:** Start Adventure opens at Phase I. | Done | M–L | advisory; C-04; §D25-3 |
| M4.3 | **Per-phase repair.** Each phase (and the outline) has its own repair loop; a failure re-prompts that phase only, and the encounter/phase gates report every problem, one per line. | Done | M | generation §7; §D25-4 |
| M4.4 | **Transport resilience.** `_live_chat` retries connection errors, 429 and 5xx (and a provider error inside a 200) up to 3 tries with backoff and `Retry-After` (T-89), a timeout once; encounters get a 420 s timeout (T-90). Shape faults (`TypeError`, `AttributeError`, `KeyError`, `IndexError`) are repair turns in every writer (`_repair_loop`). `_coerce_encounter` fixes one-right-answer faults in code: numeric strings, `supertypes`, stray tags, ranged-in-Front, boss dials, underpriced Levels. | Done | M | R3.2.8; generation notes; §D25-1 |

**Quality and variety**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M4.5 | **Avoid-list.** `# ALREADY TAKEN` (tracked and worldbook towns, town NPCs, run villains, and the bake-off attractors: Hedda, Pip, Rook, Tobiah Rell, the Seven Lamps, Quill, the ledger necromancer, the iron Bosun) goes to the town, arc and interlude writers, capped at 60 names (T-94). A new town may not take an existing name, nor a `new` hook's seed; an arc's villain may not wear a taken or attractor name. | Done | S–M | C-11; §D25-8 |
| M4.6 | **Party tactical facts** to the enemy designer: attack mode and row, keyword, types and classes, Skill and Ultimate (name and text), carried gear, the 3 latest chronicle deeds (`_roster_text`). Lore, wants, voice and ties stay out. | Done | S | R4.2.1, C-57; §D25-7 |
| M4.7 | **Grudges taught.** `hero_class:<class>` / `hero_type:<type>` in the target-rule vocabulary and the JSON contract, with the rule that a grudge names a tag the roster shows. | Done | S | C-25; §D23-6 |
| M4.8 | **Enemy pricing.** `price_enemy` prices every generated enemy from the §F tables (body, keywords, `rises`, components after modifiers; a boss against 2.5 × B(L)) before any scaling; an underpriced Level is raised in code, an overpriced one is legal. The prompt's own worked examples were re-priced. **Ruled 2026-09-25:** raise, don't reject. | Done | M | A-26; §F-6; §D25-5 |
| M4.9 | **Lockdown floor in play.** Adventure requests print the floor per phase and size; `_lockdown_problems` counts pieces per layout (clones and waves included) against `_lockdown_budget` (T-93). The one-resource-attack cap counts designs, so clones of it fill the budget. **Ruled 2026-09-25:** the budget is a floor. | Done | S | generation notes; §D25-6 |
| M4.10 | **Prompt-only rules gated:** a channeler at standard and hard (§E6-5); one design per pool of each of resource attacker, poisoner, infect creature, counter piece, gauge-punisher (a boss's T-70 ultimate counter excepted). | Done | S | A-39; §D25-6 |
| M4.11 | **Validator blind spots closed:** the `defeated_once` branch after a defeat (C-07); lines for absent NPCs rejected by name (C-08); duplicate JSON keys (C-09); ≤ 2 enemies per shared reaction (C-10); quest themes compared by content overlap; gate ranges equal to the prompts (`enrage_round` 3–5, depth 8, cast 3); `target_rule` and `trigger` checked at load (`scenario._check_rule_vocabulary`). | Done | S each | C-07…C-10; generation and arch notes |
| M4.18 | **The enemy prompt's own examples fixed:** the bodyguard `redirect` carries `new_target: self` on `on_attack` / `on_spell_cast` (never post-resolution); the `conditional` example uses the effect-condition vocabulary; "single target = L+1" reads L+2. | Done | S | GDD v2 §5–§11 notes |
| M4.12 | **Standalone encounters learn objectives** (`ENCOUNTER_EXTENSION`, sharing `OBJECTIVE_KINDS` with the phase prompt). | Done | S | B-01; §D12-7 |
| M4.13 | **The rest of the vocabulary taught:** `relentless` priced at min Level 3 / cost 3 (T-91; ruled 2026-09-25), composite self-moving intents (charge; hit-and-fade — verified in the engine), and countdown rites (`after_turns` + `channel_drop`, verified). | Done | S each | B-24, B-25, C-16 |
| M4.14 | **Library scenarios read the world:** `pregenerate_scenario` passes the worldbook context to the arc and Act I writers, and the arc gets the avoid-list. The party is still unknown at pregeneration (M3.5 decides the rest). | Done | S | generation notes |
| M4.15 | **Merchant stock named by the act writer:** stock is rolled before the act call, listed in `# THE MERCHANTS' STOCK`, and `stock_names` renames items (names and flavour only; `name_stock`). No extra call. | Done | S | B-51; §D17-6.2; §D25-9 |
| M4.16 | **Adventure art re-queues after a restart:** on every client connect a ready adventure's unpainted images queue (painted ones are adopted). | Done | S | generation notes |
| M4.17 | **Generated gauntlets:** `generate_gauntlet` is pinned end to end by a mocked test (quarantine, manifest, hash). A paid run (freshness, the enemy-schema sample) is the owner's. | Untested (paid run) | S | B-19 |

## M5 · The world remembers

*Why:* Update 24 made the *writers* remember. At runtime, dialogue still reads positive flags only, and nothing records who you spoke to, what you refused or who fell. So an NPC greets you with the same line on every visit.

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M5.1 | **Standing flags.** Set `refused_<quest>`, `talked_<npc>`, `fell_<hero>` and `defeated_act_<n>`. Write `town_state.talked`, and unify the two `STANDING_FLAGS` copies. | Not built | S | R4.1.2, C-55 |
| M5.2 | **Negated and once-only gates** (`requires: ["!flag"]`, `once`, a per-conversation seen set). Also the validator's `!` support and an ACT-prompt paragraph ("second greetings differ"). | Not built | S | R4.1.3; §D24-12 |
| M5.3 | **Merge unasked town and act topics into authored trees**, and warn when a tree shadows topics. This is the full fix for M1.5. | Not built | S | R4.1.4 |
| M5.4 | **Journal hygiene.** Dedupe per (npc, node); an act-close entry naming the boss, the fallen and the phases; date entries with the day counter; group by act. | Partial | S–M | R4.1.5, C-56 |
| M5.5 | **Finish the inert hooks:**<br>• `give_item` → `items.add_item`<br>• `open_shop` wired or dropped (today it sets an unread flag)<br>• `advance_quest` gets a reader | Not built | S | R4.1.9, B-48, B-49 |
| M5.6 | **Clear `_offered_*` on arrival** (a leftover from the flag-hygiene item). | Not built | S | R4.1.8 |
| M5.7 | **A quest card** at the top of the Quest Log: title, text, status, `direct_to`. | Not built | S | R4.3.5 |
| M5.8 | **Consequences you can see:** toasts in dialogue (gold, quest, knowledge, rest), a "Level N" stamp on level-up, and spoils dropped onto portraits. (The silent item loss itself is M1.11.) | Not built | M | R4.3.6 |
| M5.9 | **Record promises of pay** on quests and the ledger, so interlude payment hooks aren't inferred from prose. | Partial | S–M | C-46 |
| M5.10 | **Library and hand-made towns join the worldbook on first use.** | Partial | S | C-50 |
| M5.11 | **Lore gates.** `gate:` on text-field lore, `met:` reading `talked_` flags, and choices only a lore-matched hero sees. Or retire `gate:`. | Decide | S–M | C-51 |

## M6 · Economy & progression

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M6.1 | **Paid rest** at the inn's tier, a cheaper rough camp, and a dated journal line. | Not built | S–M | R4.3.1, C-60 |
| M6.2 | **Shop shelves worth visiting:**<br>• stock at the act tier (not tier − 1), plus a rare chance<br>• the catalogue's card-granting accessories and rare weapons reachable<br>• a distinct shelf per act<br>• an affordable first weapon | Not built | S–M | R4.3.2, B-55 |
| M6.3 | **Drops that change play:** an `ability` affix that grants a card; fix `_name`'s stem doubling; bigger lexicon banks. | Not built | M | R4.3.3, B-54 |
| M6.4 | **Purse hooks.** `take_gold` / `requires_gold`, `give_gold` to one hero, and `give_consumable`. Teach bribes, tolls, fees and bounties, and validate that a promise of pay carries a hook. | Not built | M | R4.3.4 |
| M6.5 | **Earned cards.** Campaign-scoped cards granted from deeds: a relic pried from a boss, a technique from a fight won. They are composed from the verb vocabulary, validated by the schema, priced by the points model and rarity-gated. Needs an instanced card layer beside the live deck (§D24-6 re-reads the deck on every load). | Proposed | L | A-56; advisory |
| M6.6 | **Scars and boons.** The `scarred` chronicle kind is reserved; also `spent`. | Proposed | M | C-54; advisory |
| M6.7 | **Rarity quotas that grow with level.** | Not built | M | A-06 |
| M6.8 | **Points pricing for the Skill and Ultimate** (left open since §D8-9). | Decide | S–M | A-46 |
| M6.9 | **An `uncounterable` consumable flag**, if play shows a countered potion feels bad. | Decide | S | B-42; §D17-10 |
| M6.10 | **Gold sinks per act** (repairs, shrine blessings, a bounty board). | Proposed | S–M | R4.3.2 |

## M7 · Voice & narration

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M7.1 | **The narrator.** An async job reads a round's or phase's structured events and writes 2–4 concrete sentences into the Chronicle and the ledger, under VOICE and CONCRETENESS. It is never on the critical path and never adjudicates. Needs M9.2. | Not built | L | A-07, B-10; R4.2.6; GDD §2 |
| M7.2 | **Hero barks.** `on_use` lines for attack, defend, mitigate, skill, ultimate, downed and revived; a `bark` event; a Deckbuilder "Voice" panel; tide-coloured Chronicle lines. | Not built | M | R4.2.3 |
| M7.3 | **Enemy barks and boss lines** (declare, bloodied, enrage, death, wave, escalation), written at generation and shown in place of the veiled templates. The information contract is unchanged. | Not built | M | R4.2.4 |
| M7.4 | **Trait-gated, voiced party lines** (`requires: ["party:<colour\|keyword\|class>"]`), written by the act writer in that hero's register. | Not built | M | R4.2.2, B-43; §D24-12 |
| M7.5 | **Vendor voice** on entering, buying and selling. | Not built | S | R4.3.7 |
| M7.6 | **Morale.** A `flee` verb, plus "every warband has one coward", so fights end in stories. | Not built | M | R4.2.7 |
| M7.7 | **`stance` chronicle entries**, which feed the party-line gates. | Not built | S | C-54 |
| M7.8 | **The first five minutes and the world's sound:** a title screen, an audio bed, town ambience, onboarding. | Proposed | M–L | review 2.3 (not selected then) |
| M7.9 | **Free-typed questions to NPCs.** Answered in persona, but able to act only through whitelisted, budgeted hooks. The `freeform: true` seam is already reserved. Do this after the narrator, since it is the riskiest for the house taste rules. | Proposed | L | B-47; §D17-5.4 |

## M8 · Co-op & distribution hardening

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M8.1 | **Durable player identity.** A player token, a 90 s seat grace, presence in the seat ribbon, and confirms that count players rather than sockets. | Not built | M | R3.1.2 |
| M8.2 | **Restart recovery.** On a fatal session error, offer "Load your last save" instead of an endless "Connecting…"; handle `popstate`. | Not built | M | R3.1.3 |
| M8.3 | **Mid-fight recovery.** A `GameState` deserializer, a golden round-trip test, and an autosave at priority stops or an action journal replayed from the last boundary. | Not built | L | R3.1.4, B-37 |
| M8.4 | **Thread discipline.** Workers compute and the loop applies under the lock; make `load_save` / `continue_run` async. | Not built | M | R3.1.5 |
| M8.5 | **Session odds and ends.** Reap idle sessions; seed `_end_saved` from a loaded save; drop `__import__("time")`; re-evaluate pending confirms on disconnect. | Not built | S | R3.1.7 |
| M8.6 | **Close the drive-by hole.** CORS only in `--dev`; a host token for quit, update, deletes, LLM settings and the worldbook PUTs; Origin/Host checks. | Not built | S–M | R3.2.7, C-65 |
| M8.7 | **Tests for the release paths:** a two-socket WebSocket test (claim, submit, confirm race, garbage frame, rejoin) and a `selfupdate` test over a temp bare repo. | Not built | M | R3.2.3 |
| M8.8 | **Shipped vs local content.** A gitignored `content_local/` searched first, so play never dirties the tracked tree, plus a "reset shipped content" path. **Mostly retired by the M1.15 ruling (2026-09-25):** play-time generated content belongs in tracked `content/`. What is left: a way for the keyless install to recover if a local edit dirties its tree. | Decide | S | R3.2.6, C-62 |
| M8.9 | **Art out of git's growth path.** WebP on save; the orphaned town art went in the 2026-09-25 purge; decide on LFS or a release asset (the tracked PNGs are ≈918 MB, and `.git` is 1.0 GB). | Not built | M–L | R3.2.5 |
| M8.10 | **Deckbuilder "Update Game Character"** keeps draft cards (or a sibling `.draft.json`); loadout errors return 422, not a raw 500. | Not built | S | R3.2.9 |
| M8.11 | **Panel clips travel with a character** (loadout export/import), which matters for the Windows install. | Not built | M | B-28 |
| M8.12 | **A view-only mode for a fallen Hardcore run's saves.** | Partial | S | B-53 |
| M8.13 | **Explicit UTF-8 file I/O.** Several reads and writes omit `encoding="utf-8"` (`content._load_json`, `_read_id_set` and `_write_content`; `scenario_content`'s item write; `ltg_combat.loader` and `scenario.load_scenario`; the Deckbuilder's `api_load`; the autoplay tester's JSON reads). On Windows, Python 3.14 then uses the locale code page (cp1252) against UTF-8 JSON: 17 tracked content files hold non-ASCII text. Found in code. The first Windows CI run (2026-09-25) passed every test except one unrelated path-separator assertion, so the suite doesn't reach these paths with non-ASCII data; still worth fixing before a player hits it. | Bug | S | found 2026-09-25 |

## M9 · Contracts & code health

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M9.1 | **Schema hardening.** `extra="forbid"` on effects, `Card`, `Cost`, `Item`, `Character` and `Loadout`, with a legacy-prune pass. Bounds on `intents`, `to_fraction`, `amount`, `count`, `generic` and `level`. Run every stored file through it once. The `Ref` validator is already done. | Partial | M | R3.3.1 |
| M9.2 | **Typed event registry.** `EVENT_TYPES` with required keys, asserted in tests; a generated `events.ts`; a test that every `fx.ts` case names a registered type. The engine emits 148 types and the client handles 35. | Not built | M | R3.3.2 |
| M9.3 | **One snapshot contract.** Pydantic snapshot models feed both serializers and generate `types.ts` (which has already drifted: no `"deadline"`). The serializer imports the engine's value functions. | Not built | L | R3.3.3 |
| M9.4 | **`VERB_TRAITS`.** One table replaces the eight engine classification sets and the serializer/Deckbuilder copies. Honour or remove the ignored `duration` fields (`Taunt`, `RemoveKeyword`, `Counters`). | Not built | M–L | R3.3.4 |
| M9.5 | **Merge the enemy/party forks** (`_push_intent`, `_build_default_attack`, a `RoundSlot` dataclass). | Not built | M | R3.3.5 |
| M9.6 | **Version `ScenarioRun.restore`.** Bump `SAVE_SCHEMA_VERSION`, keep one field list, and add a migration test from real saves. | Not built | M | R3.3.6 |
| M9.7 | **Give unregistered tunables T-ids from T-88:** stat buffs, ability and row bonuses, `enrage_scale`, `ATTACK_CADENCE`, the emergency band, double-intent difficulties, the lockdown budget, `GAUGE_LEVEL_STEP`, boss-dial ranges, the variety floor, `_defend_value`, and the later archetype costs. Turn the literals (T-27, T-52, T-45/46) into constants. | Not built | S | register notes |
| M9.8 | **A parity test for register mirrors** (`runner` vs `content` constants). | Not built | S | B-06 |
| M9.9 | **Split `engine.py`** (8.2k lines) along its regions once M9.2 and M9.4 land. | Proposed | L | arch notes |

## M10 · A trustworthy balance instrument

*Why:* the owner rightly distrusts the greedy stick. It can't sequence combos, barely uses position and wastes mana. So every balance question (the whole M3.9–M3.10 list) costs a human playtest. The engine is pure and deterministic, which is ideal for search. The obstacle is speed: a step costs ≈8 ms, almost all of it the whole-state `deepcopy`.

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M10.1 | **Cheap state copy.** Share immutable card definitions (≈54% of a copy) and move the growing log out of the copied state; pickle alone is 2.4× faster. Determinism must hold (§D12-7). | Proposed | M | B-04; advisory |
| M10.2 | **A search stick.** A lookahead or MCTS-with-greedy-rollouts policy family, versioned like the greedy one. | Proposed | L | advisory |
| M10.3 | **Soak the real content.** Fix the no-op pool invariant, add "stack empty at rest", and soak `content/` in CI. | Partial | S–M | B-05 |
| M10.4 | **Verdicts go STALE** when the policy or the rules change, not only the gauntlet. | Bug | S | B-16 |
| M10.5 | **Recalibrate the T-74 band** with the new stick (skipped for greedy-1.5.0 on purpose). | Not built | S | C-37, B-15 |
| M10.6 | **Re-run the spend audit to L9 (T-79).** The 2026-08-18 run found greedy-power over the band at every stage and blamed the stick. | Partial | M | B-36 |
| M10.7 | **Measure positional play** (§L-7): old vs new damage taken and time to kill; flying still held "pending data". | Untested | M | B-23 |
| M10.8 | **Archetype gauge rates vs the c = 20 target** (control within ±20% of damage casters on `gauge_per_turn`). | Untested | S | C-40 |
| M10.9 | **A register-wide review** of every "playtest starting value" with the new instrument. | Untested | M | A-33 |
| M10.10 | **Tester features:**<br>• pair ablation (B-14)<br>• enemy variant levers and bench tab (B-17)<br>• enemy-schema verdicts (B-18)<br>• the re-run loop and delta chart (B-20)<br>• enemy-broken-channel and random-policy floor metrics (B-08)<br>• item probes (B-41)<br>• the interpose-dodge rule (B-22)<br>• multi-turn combo lines (B-03) | Partial | M each | B-03…B-41 |

## M11 · Later, by design

Deferred on purpose or waiting for a need. Promote a row into a milestone when its trigger arrives.

- **Party and campaigns:**
  - drop-in / drop-out party composition (C-58);
  - "continue from campaign X" (C-59);
  - cross-install sync of characters, campaigns and the worldbook (C-62);
  - a Deckbuilder interview that drafts a brief from lore (C-63);
  - `mode: open` lore seeds (C-52).
- **Objectives and adventures:**
  - compound objectives and protect-the-NPC, which needs an allied NPC combatant (B-02, A-50);
  - five-phase or longer adventures (A-55).
- **Rules waiting for a card that needs them:**
  - the stance-dancer (one stance per slot, A-53);
  - controlled creatures charging the gauge (A-52);
  - dragging corpses between rows (A-51);
  - a taunt that overrides reach (A-22);
  - the `shroud` keyword: cut it from the rules or build it (A-16).
- **Enemies:**
  - per-enemy AI `temperament` (C-26);
  - faction manifests and multi-faction encounters (A-27);
  - reactive-component tiebreaks: still authoring order (A-31);
  - a progress assertion in the enemy-reaction loop (A-32);
  - enemy mana: won't do, by design (A-30).
- **Animation:**
  - per-enemy panel clips (B-29);
  - per-colour big-spell clips and an ally-Mitigate dash clip (B-31);
  - H3 duration experiments (B-34).
- **Tools:**
  - the town editor editing an arc's cast and places (C-06);
  - content-store GC (B-38).
- **Proposed directions for later design updates:**
  - expeditions: choices between phases with closed-vocabulary outcomes;
  - the worldbook drawn as a travel map;
  - faction standing.

## Decisions needed

M3.5, M5.11, M6.8, M6.9. Also:
- whether the Deckbuilder's Import Deck should keep reading MTG-worded rules text (`CUSTOM_CARD_SCHEMA.md`) now that cards are authored in LTG's own vocabulary;
- whether `shroud` stays in the rules at all.

## Rejected — do not re-propose

- standing orders;
- relevance auto-pass;
- Move consequence previews;
- the swipe-trap change;
- Defend buffering the ally behind;
- stunned-turn instants;
- any change to the *shape* of Defend or Mitigate (Power scaling is intended);
- the reaction strip;
- the "Mitigate −N" label;
- dashed threat lines or outlines across the battlefield;
- tuning the lockdown budget down;
- MTG/Scryfall import in the Deckbuilder UI;
- quests hooked to hero backstory.

(Sources: §D23 preamble and §D23-8; owner rulings 2026-08-21 → 09-06.)

## Done since the 2026-09-02 review (for the record)

- M0 Foundations (2026-09-25): the test sandbox, CI, pinned dependencies, doc and comment debt; M0.3 awaits its first green run and branch protection.
- **M1 Make it correct (2026-09-25):** all 37 rows fixed or ruled (see the M1 table).
- **M2 Legibility (2026-09-25):** 21 of 22 rows done; M2.22 waits on clip generation.
- **M4 Generation pipeline (2026-09-25):** Design Update 25 — transport retry, prompt caching, phased adventures playable at Phase I, per-phase repair, enemy pricing, the lockdown floor and caps, party facts and grudges, the avoid-list, stock naming, the validator blind spots; M4.17's paid run owed.
- **M3 tooling (2026-09-25):** jump-to states, autopilot fights, the playtest profile and the LLM tape (M3.1–M3.4); A-20 pinned (M3.12); worldbook links (M3.8); default boss dials, T-88, and the library purged for regeneration (M3.11).
- Update 23 in full.
- Update 24 in full.
- The `Ref` validator (R3.3.1, partial).
- The "we" voice on the defeat journal line (R4.1.5, partial).
- The per-trigger panel animations.
- The `other_ally` trigger scope.
- The card frames in the hand.
- This documentation consolidation.
