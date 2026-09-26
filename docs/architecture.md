# LTG architecture — a codebase map

For coding agents and developers. Verified against the code at commit `a2cce25` on 2026-09-24. Navigate by **symbol name**; line numbers drift, and the engine alone is 8.2k lines. The rules themselves are in [game_design.md](game_design.md), generation is in [generation.md](generation.md), and open work is in [roadmap.md](roadmap.md).

**The shape of the system.** The Deckbuilder authors characters (a loadout JSON). The game server owns sessions, seats, hidden information, the scenario and campaign layer, saves and generation jobs. It drives the pure engine through `legal_actions` / `apply_action` and ships seat-filtered snapshots to the React client, which renders them and sends back an index into the legal-action list. LLM writers run only at generation time (see [generation.md](generation.md)).

```
Deckbuilder (:8000) ──loadout JSON──▶ apps/deckbuilder/loadouts/   (per install)
                                              │
content/ (tracked: encounters, adventures,    ▼
towns, world, equipment, art) ──────▶ game server (:8020) ──▶ engine (pure, deterministic)
                                      sessions · seats · snapshots      legal_actions / apply_action
                                      scenario/campaign · saves/ · jobs
                                      LLM writers (generation time only)
                                              │ WebSocket + REST
                                              ▼
                                      React client (dist/ committed)
```

## 1. Packages, entry points and dependency rules

| Dist | Dir → import name | Py lines | Declared deps |
|---|---|---|---|
| `ltg-core` | `core/` → `ltg_core` | 4.7k | pydantic ≥2.5 |
| `ltg-combat` | `apps/combat/` → `ltg_combat` | 14.4k | core, fastapi, uvicorn |
| `ltg-deckbuilder` | `apps/deckbuilder/` → `ltg_deckbuilder` | 1.3k | core, requests |
| `ltg-game` | `apps/game-server/` → `ltg_game_server` | 15.4k | core, **combat** |
| `ltg-autoplay-tester` | `apps/autoplay-tester/` → `ltg_autoplay_tester` | 2.1k | core, combat, **game** |

**The dependency rule is core ← deckbuilder, and core ← combat ← game-server ← autoplay-tester.** Older docs said "apps never import each other", which was true when there were two apps. The import graph:

- `ltg_core` imports no app.
- `ltg_deckbuilder` imports only `ltg_core`.
- `ltg_combat` imports only `ltg_core`. Its `autoplay/runner.py` copies game-server constants by hand ("keep in sync") instead of importing them.
- `ltg_game_server` uses the engine as a library. It imports:
  - from `engine`: `apply_action`, `legal_actions`, `settle`, `auto_pass_action`, `pass_all_action`, `cast_target_labels`, `unplayable_reason`, `attack_preview`, and the private `_ordered` and `_objective_shielded`;
  - from `serialize`: the private `_character_dict`, `_enemy_dict`, `_token_dict`, `_corpse_dict` and `_stack_list`, plus public helpers;
  - from `scenario`: `compose_spec`, `scale_encounter`, `state_from_dict`, `sized_roster`, `SCENARIO_A`/`SCENARIO_C`, and the private `_slug`.
- `ltg_autoplay_tester` imports `ltg_combat.autoplay`, `ltg_combat.scenario`, `ltg_game_server.content` and `ltg_game_server.llm`. Nothing imports the tester.
- Coupling outside imports:
  - `ltg-start` spawns `python -m ltg_deckbuilder` as a subprocess.
  - The deckbuilder and the game server quit each other over HTTP (`selfupdate.quit_sibling`).
  - The game server, the tester and `spend_audit` all read characters from `apps/deckbuilder/loadouts/`.


| Console script | Entry point | Port |
|---|---|---|
| `ltg-combat` | `ltg_combat.__main__:main` (subcommands `cockpit`, `harness`, `repl [scenario.json]`, `validate <loadout>`) | — |
| `ltg-combat-cockpit` | `ltg_combat.cockpit:main` (serves `ltg_combat.server:app`) | 8001 |
| `ltg-autoplay` | `ltg_combat.autoplay.cli:main` (subcommands `run`, `report`, `diff`, `soak`) | — |
| `ltg-deckbuilder` | `ltg_deckbuilder.__main__:main` | 8000 |
| `ltg-game` | `ltg_game_server.launch:main` | 8020 |
| `ltg-start` | `ltg_game_server.launch_all:main` (no arguments; game plus a deckbuilder child process) | 8020 + 8000 |
| `ltg-autoplay-tester` | `ltg_autoplay_tester.launch:main` | 8030 |

**Installing:**
- `pip install -r requirements.txt` installs all five packages editable (core first), plus pytest and httpx. It applies `constraints.txt` (`-c`), which pins every third-party version, so the launchers, the updater and CI all resolve the same set.
- `.venv` runs **Python 3.9.6**. The packages declare `requires-python >=3.9,<3.15`; CI tests 3.9 and 3.14. Raise the bound only after CI passes on the newer Python.
- Editable installs map each import name to its directory, so new modules work without reinstalling. New console scripts or dependencies need the install run again.
- The `.command`/`.bat` launchers create `.venv` on first run.
- `ltg_core.selfupdate.apply_update` runs `git merge --ff-only`, then the same pip install.

## 2. Data directories

| Path | Git | Holds |
|---|---|---|
| `content/` | **tracked** | The live library; **the game writes and deletes here.** Encounters and adventures were purged for regeneration on 2026-09-25 (roadmap M3.11), so it holds `towns/` (4), `scenarios/` (empty), `world/`, `equipment/` (76 catalogue items) and `art/` (towns and items). |
| `apps/deckbuilder/loadouts/` | ignored | Per install: characters, `llm_settings.json` (**the API key**), `*hidden.json`, user `equipment/`, `lore/`, `anim/`, `llm_tape/` (recorded LLM replies, M3.4), and `art/` (portrait cache, spoils, cast, places). |
| `saves/` | ignored | `<run>/run.json`, `content/<sha>.json`, `saves/<id>.json`. Currently empty. |
| `examples/` | tracked | Last-resort fixtures the tests use; deleting one only hides it. |
| `scripts/` | tracked | `backfill_worldbook.py`. |
| `docs/` | tracked | Canon, architecture, generation, register, roadmap; `design/` history; `reviews/2026-09/` audit briefs. |

Sizes:
- After the 2026-09-25 purge, `content/art` holds 185 files, about 315 MB (towns and items). Git history still carries the deleted art.
- `du -sh .git` = **1.0 GB**.
- `delete_town` leaves the town's art behind; the two orphaned folders it had left (`medusel`, `windmill_town`) went in the purge.

## 3. `core/ltg_core/` — the shared vocabulary

- **`__init__.py`**: re-exports `schema.*`, `render_effects`, `translate`, `lint_card` and `LINT_RULES`.
- **`translation.py`** (1.5k lines) has two halves:
  - text→effects: `register` and `translate`, used by the Deckbuilder's Scryfall ingest;
  - effects→text:
    - `RENDERERS`, one entry for each of the 43 kinds;
    - `_CLAUSE`, subject-less phrases for shared-slot "Choose X: they …" sentences;
    - `render_effects`, `_channeled_body`, `_upkeep_clause`, `channel_break_clause`, `describe_target`.
- **`lints.py`**: `LINT_RULES` (9 advisory card lints) and `lint_card`.
- **`selfupdate.py`**: not vocabulary. It is the git/pip updater and quit logic for installs: `check_update`, `apply_update`, `_ff_failure`, `quit_sibling`.

`schema.py` (2.8k lines) regions, in file order:

1. **Enums:** `Color`, `Rarity`, `Timing`, `AttackMode`, `Row`, `TargetMode`, `Side`, `TargetState` (the corpse axis), `TargetScope` (row/blast).
2. **Targets:** `TargetDescriptor` and the constructors `t_self`, `t_chosen`, `t_all`, `t_row`.
3. **Stack vocabulary:** `ActionType`, `AbilityKind`, `Speed`, `spell_speed`, `FilterNode` (the counter lattice), `ActionTarget`, `Duration`.
4. **Triggers:** `TriggerType`, `TRIGGER_EVENTS`, `TRIGGER_WHO`, `EventTrigger`, `AfterTurnsTrigger`, and `trigger_key` (the key used for animations and log entries).
5. **Values:** `Ref` (checked against `REF_VALUES` or a `$stored` name), `REF_VALUES`, `REF_GROUPS`, `Value`, `StatValue`.
6. **Keywords:** `KEYWORDS` and the derived `GRANTABLE_KEYWORDS`.
7. **Slots and tags:** `SLOT_REF_PATTERN` (`$T1+row`), `CREATURE_TYPES`, `CREATURE_CLASSES`, `slot_name`, `slot_scope`.
8. **Effect primitives:** `EffectBase` (carries `trigger`), then the leaf classes `DealDamage` through `AddMana`. The `ACTION_MODIFIERS` block and `ModifyAction` sit in the middle; `Stance` sits near the end.
9. **Leaf list:** `LEAF_EFFECT_CLASSES` (40 classes).
10. **Containers:**
    - six condition models form `Condition`; then `Conditional`, `Mode`, `Modal`;
    - `EFFECT_CLASSES` (43 kinds) builds the `Effect` union;
    - `CORPSE_LEGAL_EFFECTS`, `STANCE_SLOTS`, `iter_effects`.
11. **Editor metadata:** `effect_specs()`, which the Deckbuilder serves as `/api/effect-specs`.
12. **Cards:** `Cost` and `Card`. `Card._check_targets` holds per-kind side and corpse rules.
13. **Progression and points-buy:**
    - `CREATION_BUDGET`, `PHASE_GRANTS` (10/20/30), `LEVEL_THRESHOLDS`;
    - `level_for_points`: callers pass spent points, though the parameter is named `earned_points`;
    - `level_progress`, `BASE_POWER`, `PRICE_CURVE`, `stat_price`;
    - `CREATION_KEYWORD_COST`, `BANNED_CREATION_KEYWORDS`, `PanelAnimation`.
14. **Characters:** `Brief` and `BriefVoice`, `Character` (with `stat_block`), `Loadout`.
15. **Items:** `ItemStatic`, `Item.as_card`, `BELT_SIZE`, `BUY_MULT`/`SELL_MULT`.
16. **Deck status:** `deck_status`.
17. **Objectives:** `EncounterObjective` (survive/waves/race/deadline), `Reinforcement`, `Escalation`.

Core has **no** Enemy or Encounter model; the only encounter-level model is `EncounterObjective`. Enemy JSON is validated piece by piece in `ltg_combat.scenario` and in the game server's generation gates.

## 4. `apps/combat/ltg_combat/` — the engine

- **`engine.py`** (8.2k lines, 356 functions, 40 of them `_r_*` resolvers): all the rules.
- **`state.py`**: runtime dataclasses.
- **`scenario.py`**: turns a spec into a `GameState`.
- **`serialize.py`**: presentation JSON for the cockpit and the game server.
- **The cockpit** (`server.py`, `cockpit.py`, `apps/combat/frontend/`): a FastAPI `Session` that keeps `history` and `cursor` in RAM for time travel. Routes: `/api/state`, `load/*`, `clear/character`, `scenario/builtin/{which}`, `start`, `overrides`, `action`, `step`, `goto`, `raw`.
- **`harness.py`**: the §A/§C proof.
- **`repl.py`**: the text UI.
- **`loader.py`**: `load_loadout`.
- **`__main__.py`**: the CLI.

### `engine.py` regions, in file order

1. **Public API** (top of file): `legal_actions`, `settle`, `apply_action`. Each deep-copies its input, runs `_advance`, and leaves the caller's state untouched. `apply_action` recomputes `_legal`, raises `ValueError` for an illegal `Action.key()`, and returns `(state', st.log[start:])`.
2. **Driver:** `_advance` runs the phases upkeep → capacity → draw → intents → player → allies → enemy → end. It pauses for:
   - a pending choice;
   - a non-empty stack (a reaction window);
   - a paced `settle` stop;
   - a capacity-colour choice;
   - a hero's main phase.
3. **Turn steps:**
   - `_begin_turn`, `_lock_capacity`;
   - channel and event triggers: `_fire_channel_effects`, `_STACK_FACING`, `_bind_trigger_stack_target`, and `_fire_event`, which stops recursion at depth 8;
   - `_upkeep_draws`, `_fire_recurring`, `_declare_intents`.
4. **Objectives:** `_objective_tick`, `_check_guards_down`, `_race_expire`. The enemy **proactive pass** sits under the same header:
   - `_declare_enemy_intent`: stun, the boss's double intent, attack cadence;
   - `_pick_enemy_intent`: first eligible rule wins; honours `EMERGENCY_BAND`;
   - `_declare_default_attack`.
5. **Components:**
   - `_seeded_key`, and `_proactive_rules` (ordered by priority, then the seeded key);
   - `_cooldown_ready`, `_start_cooldown`;
   - `_condition_met` (13 kinds; an unknown kind fails closed);
   - `_component_target` (dispatches on `target_rule`), `_filter_control_targets`;
   - `_rank_valuation`, which prefers finishable targets, then channel-breakable, then primed, then by role, HP and row.
6. **Update 18 pressure:** `ATTACK_CADENCE`, `_DAMAGE_KINDS`, `_taunt_with_teeth`, `_outclassed_by_the_sword`, the row-shape helpers, and `_try_declare_component` (turns a component into an `Intent`).
7. **Enemy movement and execution:**
   - interposition: `_redirectable`, `_recheck_intents`;
   - `_choose_enemy_attack`, `_swing_instead`;
   - `_execute_intent` (pushes the intent onto the stack), `_execute_ally`;
   - the End step: `_end_step`, `_reap_dead`, `_expire_keywords`.
8. **Action dispatch:**
   - `_apply` maps 18 action kinds to handlers: pass, settle, end_turn, delay, attack, cast, defend, mitigate, move, five `choose_*` kinds, drop_channels, use_skill, use_ultimate, stance_ability.
   - `_do_pass`: once everyone has passed, enemies get pre-resolution reactions, then `_resolve_top` and `_process_breaks` run, then post-resolution reactions.
9. **Enemy reactions:** `_offer_reactions`, `_trigger_matches` (the `on_*` triggers), `_reaction_signature` (the pile-on rule), `_fire_reaction`. The **hero verbs** sit under the same header:
   - the turn economy: `TURN_VERBS`, `PAIR_VERBS`, `_freed`, `_proactive_open`, `_spend_proactive`;
   - `_do_attack`, `_do_cast`, `_do_defend`, `_do_move`, `_do_delay`;
   - Mitigate: `_mitigate_value`, `_do_mitigate`, `_apply_mitigation`, `_mitigated_rider`;
   - `_do_use_skill`, `_do_use_ultimate`, `_do_stance_ability`;
   - stack plumbing: `_push` (assigns the uid, derives the combat-ability flag), `_open_window`.
10. **Resolution:** `_resolve_top`, `_queue_echo` (double_next), `_new_ctx`. `_resolve_effect_list` resolves damage first under a Mitigate, `consume_corpse` last, and pauses for picks.
11. **Channels:**
    - `_start_channel`, `_start_enemy_channel`, **`_apply_static`**, `_reapply_channel_stats`, `_reap_aura_kills`;
    - breaks: `_process_breaks`, `_fire_channel_break`;
    - picks made when a trigger fires: `_raise_next_trigger_pick`.

    The **effect core** also sits under this header:
    - `_TARGETLESS`, `_CARD_ZONE_VERBS`;
    - **`_resolve_effect`**: expands containers, handles fizzles, hexproof and splash, then calls `RESOLVERS` once for each victim;
    - `_resolution_targets`, `_REACHES_DOWNED`, `_condition_holds`, `_ref_value`.
12. **Resolvers:** the `_r_*` functions, roughly in schema order.
13. **Control:** `_r_control`, `_raise_corpse`, `_tick_control`; then **`RESOLVERS`** (40 entries) and `_filter_matches`.
14. **Typed counters** (poison, regen, charge): `_tick_afflictions`, `_check_charge_full`.
15. **Gauge:** `_gain_gauge`, `_gain_gauge_pct`, `_control_credit`.
16. **Damage and death:**
    - action shields: `_prevented_action`, `_silenced_for`;
    - damage lanes: `_is_combat_ability`, `_prevent_match`, `_apply_amplify`;
    - **`_deal_damage`**, the only damage function (there is no `_apply_damage`);
    - `_heal`;
    - **`_after_damage`**, which checks lethality and routes to `_kill_enemy`, `_remove_token` or hero incapacitation;
    - `_purge_stack_from`; **`_kill_enemy`**, which leaves a `Corpse`; `_draw`; **`_check_end`**.
    - Other corpse code lives elsewhere: `_tick_stirring` (rises) in turn steps, `_corpse_for` (the necromancy pick) in components, `_r_consume_corpse` in the resolvers, and `_raise_corpse` in control.
17. **Rows:** `_ordered`, `_reachable_targets`.
18. **Legal actions:**
    - `_legal` → `_legal_main` / `_legal_react` / `_legal_choice`;
    - `_heroic_actions`, `_cast_actions`, `_pick_options`, **`_target_sites`**, `_effect_site_label`;
    - public `auto_pass_action` and `pass_all_action`, which both deep-copy; `cast_target_labels` and `unplayable_reason` (why a hand card can't be cast, M2.7), which do not; `attack_preview` (a basic attack's outcome through the real `_deal_damage`, M2.17), which deep-copies.
19. **Mana and log:** `_can_pay`, `_pay` (pays generic costs in WUBRG order), **`_log`**, and the stale `run(loadout)`.

### `state.py`

`GameState` has 28 fields, including:
- combatants: `party`, `enemies`, `tokens`, `corpses`, `party_order`;
- randomness: `rng_seed`, `shuffle_count`;
- flow: `turn`, `phase`, `stack`, `priority`, `passes`, `paced`/`settle`;
- bookkeeping: the acted and reacted lists, `pending_choice`, `event_depth`;
- outcome: `objective`, `result`, `log`.

The other dataclasses:
- `CharacterState` (61 fields). `effective_hp = hp + temp_mod`; `ultimate_charge_cost = 100 + 20·(level−1)`.
- `EnemyState` (58 fields), `TokenState`, `Corpse`, `Channel`, `EnemyChannel`, `Intent`, `Component`, `StackItem`, `Objective`, `PendingChoice`.
- Tag types.
- `Action`, whose `key()` leaves out `mana`, `auto` and `label`.
- `Event(type, msg, data)`.

### `serialize.py`

Presentation only. The game server's `snapshot.py` imports its private helpers, so a change here also changes the game client's contract. Main pieces:
- `to_jsonable`, a one-way conversion to JSON;
- `card_dict`, and `serialize_state`, which ships the whole log to the cockpit;
- `intent_category`, built on `_HOSTILE_KINDS`, `_CONTROL_KINDS` and `_SIDE_SENSITIVE_HOSTILE`;
- `veiled_intent(s)`, `objective_block`, `doom_clock`, `build_menu`, `serialize_actions`.

Some rule questions go to the engine through lazy imports (`_redirectable`, `_proactive_open`). Others are copies of engine functions:
- `_mitigate_value`
- `_defend_value`
- `_enemy_charge_threshold`
- `_lane_text`
- `_channel_countdown`

The `_mitigate_value` copy has **already drifted**: it is missing the engine's `max(1, …)` floor.

### `scenario.py`

- `state_from_dict(spec, seed)`: seeded library shuffles and turn order. It builds enemies through `_component_from_dict`, which runs a `TypeAdapter(List[Effect])` over the verbs, `_check_enemy_verbs` and `_CONDITION_KINDS`.
- `compose_spec(loadouts, scenario, overrides)`, with `party_entry_from_loadout` (reads `stat_block`) and `fold_gear`.
- `scale_encounter` picks the per-party-size layout.
- `SCENARIO_A`/`SCENARIO_C`, `build_state`, `build_channeling_state`, `load_scenario`.

### `autoplay/`

- **`runner.py`**:
  - `run_one(spec, policy, seed)` returns a RunRecord.
  - `run_adventure` copies the server's rules between phases: HP floor at 25%, 50% gauge carry, level-ups from `PHASE_GRANTS`.
  - `prepare_scenario` scales for difficulty and layouts, then adds the T-64 Power bump (constants copied from the game server).
  - `_drive` calls `legal_actions`, then `apply_action`, for each step. Anomalies: `round_cap` (50), `no_actions`, `action_cap` (20k).
  - Metrics read from the log:
    - per hero: damage and healing, casts, mana granted/spent/wasted, gauge and Ultimate timing;
    - per card: channel economy, draws and casts, conditional whiffs, castability;
    - party: moves and reaction windows per round, and which ladder rule made each decision;
    - enemies and the fight: death rounds, objective margin, redirects.
- **`policies.py`**: `RandomPolicy` (`random-1.0.0`), `GreedyPolicy` (**`greedy-1.5.0`**), `SPEND_PLANS` (balanced, greedy-hp, greedy-power, greedy-mana), `make_policy`.
  - Greedy is a fixed ladder of rules (`1-win-now` … `12b-pair-move`). `last_rule` records which rule made each choice.
  - It **cannot**: sequence amplify→spike combos, plan across turns, look ahead, or value refs and X damage (it scores them as 0).
  - It never Delays, and it takes the first option on every forced choice.
  - Its positioning is blunt: vacate a lethal telegraphed row, move ranged heroes out of Front, take the pair move.
- **`report.py`** (`aggregate`, `diff_reports`, the T-72 outliers), **`soak.py`** (invariant fuzzing with the random policy), **`cli.py`**.

## 5. Determinism and state

**Randomness enters only through `rng_seed`:**
- `state_from_dict` shuffles each library, then the turn order, from one `random.Random(seed)`.
- In-game shuffles use `random.Random(f"{rng_seed}:shuffle:{shuffle_count}")`. A str seed is stable across processes and Pythons (the old tuple seed raised `TypeError` on 3.11+); `tests/test_move_card.py` pins the order.
- Equal-priority enemy rules tie-break through `_seeded_key` (a crc32 of seed, enemy, turn and component). Without a seed it uses 0, which is still deterministic.
- Callers choose the seeds: the game server picks `random.randrange(2**31)` for each fight, the cockpit a fresh seed per start, and the runner seeds each run (`seed·1000003 + i` for each adventure phase).

**Deep copy on every call.** `legal_actions`, `settle`, `apply_action`, `auto_pass_action` and `pass_all_action` each deep-copy the whole state. `legal_actions` and `apply_action` also both re-run `_advance`. I measured with 3 heroes holding 20-card decks against 3–7 enemies:

| Point in the fight | Cost per copy |
|---|---|
| Start of the fight | ≈3 ms |
| After ~200 log events | ≈4 ms |
| 8k log events (a runaway loop) | ≈42 ms |

- `Card` models account for 60–80% of the copy cost.
- The engine never trims the log, so every action makes later copies slower.
- One greedy autoplay step (`legal_actions` + `apply_action`) takes ≈8 ms.
- Each server snapshot adds another `settle` and `legal_actions` call.

**No `GameState` deserializer exists.** `to_jsonable` only goes one way, and `PendingChoice.candidates` relies on deepcopy preserving shared objects. The consequences:
- The game server saves only at boundaries (adventure and phase boundaries, act_start, quest_accept, inn, town).
- A restore rebuilds the phase from content plus the seed.
- The cockpit's history lives only in RAM.

## 6. `apps/game-server/ltg_game_server/` — the game server

The server is an authority and relay. Every combat action goes through the engine's `apply_action`. The server adds seats, hidden-information filtering, pacing, persistence and the RPG layer.

| Module | Role and key symbols |
|---|---|
| `app.py` (1.3k) | FastAPI `app`, `MANAGER`, `RUNS`. All routes, `ws_endpoint`, and `_broadcast` (sends seats, state and prompt to every socket, plus game_over once a result exists). `_scenario_async(session, kind)` does off-lock work: `materialize`, `interlude`, `continue`, `adventure_job`, `confirm_timer`. `_open_save` and `_continue_sync`. It serves `/art/*` (`content/art`, then `loadouts/art`), `/anim/*`, and `dist` (`index.html` no-store). |
| `session.py` (1.05k) | `Session`: one `GameState` (`None` in town), `seats`, `clients`, a lazy lock, `pass_all`, `confirm`. `SessionManager` is in-memory and never evicts. `apply_index`. `_auto_advance` is a synchronous drain (cap 200). It also runs at phase openings, so those are unpaced. `_drain_paced` is one task per session: one broadcast per synthetic step, with 1.1 s, 0.6 s or 0.18 s pauses, holding the lock only while stepping. Confirmations (T-84): all sockets must say yes, one "no" cancels, 30 s of silence counts as yes, and a lone socket skips the vote. `set_pass_all` works per character, per turn step. Also `town_verb`, `economy_verb`, `start_adventure`, `materialize_act` (blocking), `continue_campaign`, `choose_hook`, `_scenario_transitions` (the act wrap-up and defeat), `confirm_level_up`, `save_point`, `snapshot_for`. |
| `snapshot.py` (475) | `build_snapshot`, `priority_fields`, `priority_kind`, `LOG_TAIL=60` (oldest-first), `HIDDEN_LOG_TYPES={"intent_declared"}`, the seat log filter `_seat_log_line`, and the per-entity reshapers. |
| `scenario.py` (1.9k) | `ScenarioRun`: town + arc + three acts. `mode` is town, adventure, complete or interlude. It holds the `campaign` record and run copies of the party's loadouts, points, gold and HP. Verbs: `arrive`, `materialize`, `visit`, `talk`, `choose`, `buy`, `sell`, `give`, `accept_rewards`, `start_adventure`, `on_adventure_complete`, `on_adventure_defeat`, `begin_interlude`, `choose_hook`, `begin_next_scenario`, `town_snapshot`, `snapshot`, `restore`. Its generators can be swapped out in tests. |
| `scenario_content.py` | CRUD for towns (`content/towns/`) and pre-generated scenarios (`content/scenarios/`). Validators: `validate_town`, `validate_arc`, `validate_materialization`, `validate_interlude`. `town_for_act` merges the base town with the arc's cast and places and the campaign's overrides. |
| `dialogue.py` | `validate_dialogue` (the closed `HOOKS` vocabulary) and the `Conversation` walker. |
| `adventure.py` | `AdventureRun`: three phases, carry-over (`HP_FLOOR_PCT`, `GAUGE_CARRY`), the per-seat level-up gate, `advance` / `restore` / `snapshot_block`. |
| `runs.py` | `RunManager` / `RunStore`: `saves/<run>/run.json`, a SHA-256 content store, and save snapshots at boundaries only, never mid-combat. `load_scenario_save` applies `content.refresh_instance`, so the character's identity is read live. `RUN_SCHEMA_VERSION=2`. |
| `content.py` (1.7k) | Registry, validation and persistence. `CONTENT_DIR` is tracked and is the write target. `_SCAN_DIRS = [content, loadouts, examples]`; the first file to claim an id wins. `portrait_url` caches portraits in `loadouts/art/portraits/`. `save_encounter` writes through `_write_content`. `delete_encounter` removes the JSON and art, then hides the id. Adventure phases are `<adv>__phase<n>`. `build_state_from_loadouts` applies the balance register and the T-88 default boss dials (`apply_boss_dials`). Also lore and `refresh_instance`. |
| `items.py` | Catalogue in `content/equipment/` (read). User items go to `loadouts/equipment/`. Also `AFFIXES`, `roll_stock` and the gear helpers. |
| `loot.py` | `forge_drops` uses the arc's frozen `loot_lexicon`. Deterministic, with no LLM call. |
| `jobs.py` | `RUNNER` generates the adventure at quest accept (idle → pending → ready or failed, persisted in run.json). Since §D25-3 it is written a phase at a time: the job turns ready at Phase I (`phases_ready`/`phases_total`, `writing`), freezes each later phase as it lands and hands it to a running adventure (`Session.phase_landed`); a later failure leaves it ready with a `phase_error`, and a restart resumes at the missing phase from the stored `outline`. In-flight jobs are tracked per process (`_inflight`), never by a persisted flag. `INTERLUDE` runs the planner at boss death. |
| `llm.py` (3.5k) | OpenRouter client, settings, and every text generator. See [generation.md](generation.md). `_chat` consults the tape; `model_for` honours the playtest profile (`playtest_on`, `require_key`). |
| `tape.py` | The LLM tape (roadmap M3.4): `record`, `lookup` (exact prompt hash, else the closest same-kind prompt at the same depth), `summary`. `loadouts/llm_tape/`. Modes `off`, `record`, `replay`, `replay_only`; `LTG_LLM_TAPE` overrides. |
| `autopilot.py` | Autopilot fights (roadmap M3.2): `play_chunk(state, seed)` plays up to `CHUNK_ACTIONS` party decisions with `GreedyPolicy` on a copy (`ROUND_CAP`, per-fight `ACTION_CAP`). `Session.set_autopilot` / `start_autopilot` / `_drive_autopilot` run it off the lock on a worker thread and commit a chunk only if nobody acted meanwhile (`_autopilot_commit`). Playtest profile only; level-ups, spoils and towns stay with the players. |
| `devstates.py` | Jump-to campaign states (roadmap M3.1): `build(state, town_id, character_ids, act, …)` drives the real `ScenarioRun`/`Session` verbs to `STATES` (`act`, `ready`, `defeat`, `between`, `interlude`, `scenario2`) and leaves an ordinary run in `saves/`. Writers `stub` (stand-ins built from the town plus library adventures; no key, no content writes) or `llm`; fights `instant` or `autopilot` (a loss is a real defeat and is retried). Level-ups spend through the policy's balanced plan. CLI: `python -m ltg_game_server.devstates <state>`; REST: `POST /api/playtest/jump`. |
| `art.py` | OpenRouter image model or ComfyUI. `ART_DIR = content/art`. `LEGACY_ART_DIR = loadouts/art` is the read fallback and also receives the run-scoped spoils, cast and places art. `ArtQueue` runs sequentially, is idempotent, and skips failures. |
| `world.py` | Worldbook in `content/world/`: `append_entry` (neighbours are symmetric), `update_entry`, `context_for`, `placement_context`. |
| `appctl.py` | `/api/update/*`, `/api/quit` and `/api/app/info` (the Deckbuilder's port for the client's Edit link), wrapping `ltg_core.selfupdate`. `LTG_DECKBUILDER_PORT` defaults to 8000. |
| `launch.py` | The `ltg-game` CLI. Defaults: host `0.0.0.0`, port 8020. Flags: `--reload`, `--no-browser`, `--skip-build`, `--rebuild`, `--dev`. It rebuilds `dist` when source mtimes are newer. Without npm it serves the committed `dist`. |
| `launch_all.py` | `ltg-start` takes no arguments. It reuses or spawns the Deckbuilder on `LTG_DECKBUILDER_PORT` (8000), runs the game in-process on `LTG_GAME_PORT` (8020), exports both so each app's Quit finds its sibling, and kills the child on exit. |

## 7. The wire protocol

### WebSocket `/ws/{session_id}`

On connect the server sends `hello {client_id, session_id}`, then `seats`, `state` and `prompt`. For an unknown id it sends `error {message, fatal: true}` and closes. The client then stops its 1 s reconnect loop.

**Client → server**

| `type` | Payload | Handling |
|---|---|---|
| `heartbeat` | – | Echoed. The client sends one every 20 s. |
| `claim_seat` / `release_seat` | `character_ids[]` | Claim works only on free or already-own seats. Then broadcast. Takes no lock. |
| `pass_all` | `on`, `character_ids[]` (required) | Runs under the lock. Then broadcast and start the pacer. |
| `submit_action` | `action {index, mana?[]}` | `apply_index(drain=False)` under the lock. Any exception sends an `error` and a fresh `state` to that client. Otherwise broadcast and start the pacer. |
| `town` | `verb`, `payload{}` | Runs `economy_verb` during a scenario fight, `town_verb` otherwise. A `ValueError` becomes an `error`. |
| `confirm` | `id`, `yes` (default true) or `cancel` | `answer_confirm` / `cancel_confirm`. |
| `retry_job` | – | Re-fires the adventure job; on a partly written adventure it resumes at the first missing phase (§D25-3). |
| `confirm_level_up` | `character_id`, `build{}` | A `ValueError` becomes an `error` and a re-sync. |
| `autopilot` | `on` | `set_autopilot` (refused unless the playtest profile is on). After every message the dispatcher calls `start_autopilot`, so a fight that opens while it is on is played. The snapshot carries `autopilot {on, available, note}`. |
| other | – | `error "unknown message"` |

**The guard.** Every message goes through `_dispatch` inside one guard in `ws_endpoint`. A non-JSON or non-object frame, a bad shape (`character_ids` not a list of ids, `action` or `payload` not an object), or any exception raised while handling a message is answered with an `error` frame and a broadcast. The socket stays open, so the player's seats survive. The pacer task (`_drain_paced_guarded`) and the confirm timer print a fault instead of dying silently, and hitting `_AUTO_CAP` prints a warning.

**Town verbs.** Verbs marked ★ need every player to confirm.
- `town_verb`: `continue_campaign`, `dismiss_splash`, `dismiss_notices`, `rest_screen`, `rest_back`, `set_situation` (rest screen only), `retry_materialize`, `choose_hook {index}`★, `visit {location_id}`★, `leave`★, `talk {npc_id}`, `attribute`, `end_talk`, `choose {index}` (★ when party-wide), `start_adventure`★, `save`.
- `economy_verb`. Gear verbs all take `character_id`: `equip {item_id, slot}`, `unequip {slot}`, `to_belt`, `from_belt`, `discard` and `sell` (each `{item_id}`), `buy {item_id, location_id?}`, and `give {to, item_id?, gold?}` (if another player controls the recipient, that player must accept). Also `trade_answer {yes}`, `reward_assign {index, target}`, `reward_accept`★ and `flee`.

**Server → client:** `hello`; `seats {seats, you, pass_all}`; `state` (§3); `prompt {holder_character_id, kind}`, which the client ignores; `game_over {result}`, sent on every broadcast while the result stands and shown by the client after choreography; `error {message, fatal?}`; `heartbeat`. Confirmations, notices and saves ride inside `state`: `confirm {id, kind, label, initiator, you_are_initiator, answered, yes_count, player_count, seconds_left}`, `notices` and `run.last_save`.

### REST (56 `/api` routes, all unauthenticated; CORS `*`; bound to `0.0.0.0`)

`[A]` marks admin or destructive routes. `…` repeats the group's prefix.

- **Playtest:** `POST /api/playtest/jump` (`town_id`, `character_ids`, `state`, `act`, `difficulty`, `hardcore`, `writers`, `fights`) builds a `devstates` run and opens its newest save; 403 unless the playtest profile is on. `GET /api/setup-options` reports `playtest` and `jump_states`.
- **Setup:** `GET /api/setup-options`; `POST /api/games` (`character_ids` plus one of `encounter_id`, `adventure_id`, `scenario_id`, `town_id`, with optional `run` and `note`; scenario and town games are always runs, and Town + New blocks on arc generation); `GET /api/games/{id}`.
- **Characters:** `POST /api/characters` (imports into loadouts); `DELETE …/{id}` [A].
- **Runs:** `GET /api/runs`; `GET …/{id}`; `POST …/{id}/continue` (newest save); `POST …/{id}/saves/{sid}/load`; `DELETE …/{id}` [A]; `DELETE …/{id}/saves/{sid}` [A].
- **Encounters:** `GET` / `DELETE`[A] `/api/encounters/{id}` (delete removes the tracked JSON and art); `POST /api/encounters`; `POST …/generate`; `POST` / `DELETE`[A] `…/{id}/art`; `POST` / `GET …/{id}/art/all` (start or poll the queue).
- **Adventures:** `GET` / `PUT` / `DELETE`[A] `/api/adventures/{id}`; `POST …/generate`; `POST` / `GET …/{id}/art/all`.
- **Towns:** `GET /api/towns`; `GET` / `DELETE`[A] `…/{id}`; `POST /api/towns`; `POST …/generate`; `POST …/{id}/topics`; `POST …/{id}/art`; `POST` / `GET …/{id}/art/all`.
- **Worldbook:** `GET /api/world`; `GET …/regions`; `PUT …/regions/{rid}` [A] (force-overwrites); `GET` / `PUT`[A] `…/{town_id}`.
- **Equipment:** `GET /api/items`; `GET` / `DELETE`[A] `…/{id}`; `POST /api/items` (writes `loadouts/equipment`); `POST …/{id}/art`; `POST` / `GET …/art/all`.
- **Scenarios:** `GET /api/scenarios`; `GET` / `DELETE`[A] `…/{id}`; `POST …/generate`.
- **LLM:** `GET /api/llm/settings` returns `has_key`, never the key. `PUT` [A] writes the key; `api_key: null` clears it. `LlmSettingsBody` silently drops unknown fields.
- **App control:** `GET /api/update/check` (runs `git fetch`); `POST /api/update/apply` [A]; `POST /api/quit?scope=all|self` [A].
- **Static:** `/art/{path}`, `/anim/{path}`, `/`.

## 8. The state contract (engine → snapshot → client)

**Pipeline**
- The engine's `GameState` is stored un-settled on the `Session`.
- `build_snapshot` renders the view from `settle(stored)`, computes `legal_actions(stored)`, and reuses the `ltg_combat.serialize` helpers.
- `Session.snapshot_for` adds the session blocks.
- The client mirrors this in `apps/game-ui/src/lib/types.ts`. **It is mirrored by hand, not generated.** It has already drifted: `ObjectiveView.kind` lacks `"deadline"`.
- The cockpit's `serialize_state` is a third shape, unfiltered.

**Combat `state` fields:** `turn`, `phase`, `phase_label`, `phase_step`, `scene_image`, `encounter_id`, `priority`, `characters[]`, `creatures[]` (from `living_enemies()`), `tokens[]`, `corpses[]`, `stack[]` (top first, with `uid`), `objective`, `intents[]`, `pending_choice`, `log[]`, `legal_actions[]`, `result`, `game_over`.
- The session adds `adventure` (the phase, the narration and the per-seat `level_up` gate), `run` and `confirm`.
- Inside a scenario it also adds `mode:"adventure"`, `scenario`, `quest_log`, `party_sheet`, `rewards`, `defeat_pending` and `gear_editable`.

**Town `state`:** `mode` is `"town"` or `"complete"` (the interlude reports as `town`). Fields: `party_sheet`, `run`, `confirm`, plus `town_snapshot()`: `town`, `location`, `conversation`, `splash`, `materializing`, `materialize_error`, `quest_log`, `scenario`, `interlude`, `notices`, `adventure_job`, `shop`, `trade`. The client routes on `mode`: town states apply immediately, combat states queue.

**Priority**
- The holder is the first legal action's actor. If there are no legal actions, it falls back to `view.priority`.
- `priority_kind` checks in this order:
  1. `pending_choice` → `card_choice`, for move, scry, target and mode picks.
  2. A non-empty stack → `reaction`.
  3. The `capacity` phase → `mana_choice`.
  4. Otherwise `main_action`.
  5. No priority → `null`.
- A paced **settle stop** reads as `main_action`, and its only legal action is a synthetic `settle`. Only the game server sets `GameState.paced`. The client draws nothing for it; the pacer submits it.

**Seats**
- Seats exist only on the server; the engine never sees them.
- They are keyed by live ids in combat and by roster ids in town. `_remap_seats` maps them across by slot.
- Each socket gets a fresh `client_id`. `remove_client` releases its seats on disconnect, so a reconnect starts with none. The TopRibbon offers per-seat chips and **Claim all**.
- Submitting an action requires owning `actions[index].actor_id`.

**Hidden information**
- Only the controlling client receives `hand`, `library` (in draw order), `graveyard`, the Skill and Ultimate faces, and the level-up build rows.
- It also receives `legal_actions`, but only if it controls the holder, and `pending_choice` candidates, but only if it is the chooser.
- Intents are **veiled** for everyone: category and target only. `intent_declared` log lines are dropped.
- **The log is seat-filtered** (`_seat_log_line`): a teammate's `draw` or `scry` reads "X draws a card." with no card attached (`PRIVATE_CARD_LOG_TYPES`), and `intent_redirect` / `intent_spoiled` are rewritten without the intent's name (`VEILED_LOG_TYPES`). The engine's own log keeps everything.
- `log` is the 60 newest visible entries, **oldest first** (M2.1). `seq` is the absolute index in the stored log; the client merges snapshots by `seq` into the fight's whole Chronicle (`store.chronicle`, `mergeChronicle`).

**Legibility fields (M2, 2026-09-25)**
- Characters and creatures carry `status_chips` (`serialize.status_chips`: `{label, tone: bane|boon, tip}`, lockdown first); a hero's `mana` block carries `sapped`.
- Creatures carry `enraged`, `neglect` (`{amount, hurt}` or null, bosses only) and `guarded_by` (the race guards' names).
- `objective` carries `next_arrival` (`{when, line}` or null) and stays in the snapshot after it resolves.
- Hand cards carry `unplayable_reason` (`engine.unplayable_reason`) and every card `flavor`; an `attack` legal action carries `preview` ("→ 4 · kills").
- `damage` log entries carry `mode` ("melee attack", "ranged attack", "spell", "combat ability", "ability", "fight"), which the FX read directly (the client's label→mode guess is gone).

**[`INTERFACE_NOTES.md`](design/INTERFACE_NOTES.md) status** (the July Phase-1 contract, now kept in `docs/design/`; still cited by `session.py`, `snapshot.py`, `content.py`, `app.py`, `CreatureCard.tsx`):

| § | Status | Note |
|---|---|---|
| 1 engine contract | PARTLY STALE | The model holds. Line refs are stale; `auto_pass_action`, `pass_all_action` and settle stops are new. |
| 2 `priority.kind` | PARTLY STALE | The table still matches. `card_choice` now also covers target and mode picks; the settle stop is missing. |
| 3 field mapping | STALE | `hp.current` is effective HP. The mana block is `by_color[]`. Intents are veiled. The boss and channel gaps are closed. |
| 4.1, 4.2 | VALID | Capacity flag; single holder. |
| 4.3 no bosses | STALE | `is_boss` and `in_execute_window` are live. The "dormant" comments in `CreatureCard.tsx` and `layout.ts` are stale. |
| 4.4 creature channels | STALE | Enemies channel. Tokens still report `false`. |
| 4.5 no enemy graveyard | PARTLY STALE | Dead enemies leave `corpses[]`, which can rise. The server filters with `living_enemies()`. |
| 4.6 tokens | RESOLVED | Built as recommended, plus control chips. |
| 4.7, 4.8, 4.9 | VALID | 4.8 gained an optional `mana` list. 4.9 gained `targets` and `target_labels`. |
| 4.9b drop channels | STALE | Per-channel drop exists, plus "drop all". |
| 5 seats | PARTLY STALE | The hidden-field list is incomplete, and the log is unfiltered. |
| 6 setup-options | STALE | `content.py` is the registry (content → loadouts → examples, plus adventures, scenarios and towns). |
| 7 reuse vs add | VALID | The list of additions is incomplete. |

## 9. `apps/game-ui/src/` — the client

About 16.6k lines. Stack: React 18, zustand, Tailwind 3, Vite 5, strict TypeScript.

**`lib/`**
- `store.ts` is the single zustand store. It holds the socket and the `handle(msg)` switch. States enter a presentation queue (`_snapQueue` / `_drainPresent`) and each is held until its FX timeline has landed (`holdUntil`, `HOLD_SETTLE_MS=680`). It also runs panel-clip pre-roll and arming (`selectChoice`, `pickTargetId`, the `beginCast` mana payment, which pre-pays the fixed pips and asks only when the colour matters). An applied snapshot clears `armed` and `manaSelect` only when its `legal_actions` differ from the last one (M2.3).
- `ws.ts` reconnects every 1 s and sends a heartbeat every 20 s. `api.ts` holds every REST call; `types.ts` the contract; `choices.ts` groups legal actions; `fx.ts` maps log entries to FX; `motion.ts` does FLIP slides; `fieldView.ts` zoom and pan; `keyboard.ts` the console keys (M2.15); `settings.ts` the per-browser preferences.

**`components/` (39 files)**
- **Battlefield:** party rows take 45% of the width and the enemy cascade 55%. Also corpses, departure ghosts and projectiles.
- **`CharacterCard`:** hosts `PanelAnim`, `StatPop`, `WardAura`, `KeywordBadges` and `FxLayer`.
- **`CreatureCard`:** also exports `TokenCard` and `CorpseMarker`.
- **`BottomBar`:** zones, `ManaWidget`, `UltimateColumn`, `ActionBar` (verb cells, `PassAllToggle`, Pass, End Turn) and `Hand`.
- **`SidePanel`:** Stack, Intents and Chronicle. In town it shows the journal instead.
- **Modals:** `Modals` (`CardPickPrompt`, `ChooseModeModal`, `ZoneModal`, `GameOverOverlay`, `PhaseBanner`, `Toast`) and `InspectModal`.
- **`TopRibbon`:** turn tracker, seats, Claim all, Options, New Game and `QuitControl`.
- **`TownScreen`:** map, `DialogueModal`, `RestScreen`, `RunEndScreen`, `QuestLogPanel`, `DeedsTab`, `TradeOffer`, `CharacterSheetModal`, `ConfirmOverlay` and `DefeatSplash`.
- **`AdventureFlow`:** victory, then level-up, then narration.
- **`Items`:** shop, gear and spoils.
- **`NewGameModal` / `LoadGameModal`:** start or resume a game.
- **`OptionsModal`:** nine tabs, using `EncounterEditor`, `AdventurePanel`, `ScenarioPanels`, `WorldPanel`, `LlmSettingsPanel` and `SettingsPanel`.
- **Shared:** `Icons`, `Splitter`, `StatusChips` and `TooltipLayer` (the themed tooltip: any element with `data-tip` gets it; prefer it to `title=`).

**FX pipeline**
- `fxFromLog` walks entries with `seq > lastSeq`, oldest first, through `switch (e.type)`.
- It schedules 33 `FxKind`s on a beat timeline (`BEAT_IMPACT=180`, `BEAT_CAP=1500` ms) and records departures (death, exile, bounce) for the ghosts.
- `syncSeq` skips history when `seq` resets.
- **The client handles 43 log types. The engine emits 148 distinct types** (an AST count of `_log(...)` literals in `apps/combat/ltg_combat`). Every type still shows as Chronicle text, and `SidePanel.logTint` tints about 40 types by category.
- Arrivals are not log-driven: `Battlefield.useEntrances` animates any creature or token absent from the previous snapshot (M2.12).

**Styling**
- Colour tokens and the Optima `display` font are in `tailwind.config.js`. `src/index.css` holds `.caps-label`, `.panel-ticks`, `.chamfer-x` and the keyframes. `src/styles/fx-*.css` load after it.
- Rules from `DESIGN_SYSTEM.md` ("Brasswork & Ink"):
  - No emoji; icons come only from `Icons.tsx`.
  - **Brass is the only interaction accent.**
  - Colour meanings: tide = player, blood = enemy and harm, vigor = heal or buff, aether = channel or ability, spell = the spell lane.
  - Sharp corners: no `rounded-*` except mana pips.
  - Optima small caps (`.caps-label`) for labels; `font-light` for body text.
  - No default Tailwind palette.

**Build and dev**
- `npm --prefix apps/game-ui run build` runs `tsc --noEmit && vite build` and writes `dist/`.
- **`dist/` is committed** (`.gitignore` re-includes it) because the Node-less Windows install serves it. Rebuild and commit it after every client change.
- `npm run dev` starts Vite on :5173 and proxies `/api`, `/art`, `/anim` and `/ws` to :8020.
- **There are no client tests.** The only scripts are `dev`, `build` and `preview`.

## 10. `apps/deckbuilder/` — the authoring tool

**Backend** (`ltg_deckbuilder/app.py`, default port 8000)
- **Used by the UI:**
  - `POST /api/cards/import-custom`: the "Import Deck" button; `ingest.build_custom_card` translates MTG-worded effects.
  - `POST /api/cards/validate` and `POST /api/loadout/validate`.
  - `GET /api/loadout/{name}`: falls back to `examples/`.
  - `POST /api/loadout/export` and `POST /api/loadout/update-game`.
  - `GET /api/effect-specs` and `GET /api/character-model`.
  - `POST /api/flavour/generate`: `flavour.py`, one LLM call using the game's `llm_settings.json`.
  - Animation clips in `loadouts/anim/`: `POST /api/anim/upload`, `POST /api/anim/delete`, and `GET /anim/{path}`.
- **Kept but unused by the UI:**
  - Scryfall: `GET /api/scryfall/search`, `POST /api/cards/import`, `POST /api/cards/add`.
  - `GET /api/loadouts`, `POST /api/loadout/save`, `POST /api/character/price`, `GET /api/lore/{name}` (tests only), `GET /api/schema`.
- **`update.py`:** the same update and quit routes as the game. `LTG_GAME_PORT` defaults to 8020.

**Frontend** (`frontend/`)
- A static SPA with no build step.
- `index.html` is served `no-store` and loads `styles.css?v=23` and `app.js?v=35`. **Bump the matching `?v=N` on every edit** to either file, or browsers keep running the old script.
- Save and Load use the browser's File System Access API.

**`CUSTOM_CARD_SCHEMA.md`** is the paste-ready JSON format for Import Deck, so an LLM or a person can author cards outside the tool. Fields: `name`, `type`, `mana_cost`, `effect` (MTG oracle wording), optional `flavour` and `rarity`.

**Update Game Character**
1. In the game, Options → Characters → Edit opens `http://<host>:<port>/?edit=<id>` (port from localStorage `ltg_deckbuilder_port` if set, else the server's `/api/app/info`, default 8000).
2. The export button becomes "Update Game Character".
3. It writes **validated cards only** over `loadouts/<id>.json`, keeping the id through a rename. Unvalidated draft cards are dropped.
4. The game re-scans on every request.

**Custom cards only since 2026-08-30.** The Scryfall UI is gone. Legacy fields (`source_name`, `ignore_source`, `original_text`, `needs_translation`) still load but are pruned on save, export and update-game (`pruneLoadout` / `_prune_loadout_dict`). Rarity is kept.

## 11. Autoplay and the Autoplay Tester

The playtest lab from Design Update 13: a FastAPI app with a plain-JS UI on port 8030. Run it with `ltg-autoplay-tester` or `LTG-Autoplay-Tester.command`/`.bat`.

**Jobs and probes:**
- `jobs.JobRunner` runs one probe at a time on a worker thread, spread across a process pool of `cpu_count − 2`.
- Probe kinds: `card`, `skill`, `ultimate`, `character`, `enemy_schema`.
- Each probe is a paired A/B ablation on identical seeds, run across a pressure ladder (enemy HP and Power ×0.5–2.2).
- Presets: `quick` (8 seeds) and `thorough` (24 seeds plus leave-one-out).
- Verdicts record the gauntlet hash and the policy version.

**Reading and writing content:**
- The tester reads characters through `ltg_game_server.content` and never edits content, except `promote`.
- "Edit in Deckbuilder" links to `:8000/?edit=<id>`.

**Data:**
- `data/gauntlets/<id>/` is tracked: a manifest plus encounters. `baseline-1` and `baseline-2` are frozen.
- `data/runs/` and `data/verdicts/` are gitignored.

**Spend audit:** `.venv/bin/python -m ltg_autoplay_tester.spend_audit [--seeds 8] [--stages 3] [--curve JSON]`.
- It chains the baseline adventure over the local loadouts.
- `--curve` patches `schema.PRICE_CURVE` in-process.
- Results are in `SPEND_AUDIT_UPDATE_17.md`.

**T-74 band** (in `probes.py`):
- `OVER_PP = +4.0` and `UNDER_PP = −4.0` percentage points;
- `OVER_Z = 2.0` is advisory;
- calibrated under greedy-1.2.0 and **deliberately not recalibrated** for 1.5.0.

**In the game (roadmap M3.2):** the same `GreedyPolicy` drives Autopilot in live sessions (`ltg_game_server/autopilot.py`) and the `devstates` jump-to builder's `autopilot` fights. It moves playtests through the game; its wins and losses there are not evidence either. A heuristic change that bumps the policy version changes both.

**Trust caveat:** the owner does not currently trust the greedy policy's absolute numbers. Use the harness to detect crashes and anomalies, and to compare A/B deltas within one run. Never cite its win rates or verdicts as balance evidence, and don't gate work on them.

## 12. Tests

**Files.** `tests/` has 102 files: `__init__.py`, `conftest.py`, and 100 `test_*.py` (about 1,300 test functions, 25k lines).
- 20 are `test_design_update_NN[_topic].py`; the unnumbered one covers Update 01.
- One is `test_balance_update_11.py`.
- The rest are feature files: `test_enemy_*`, `test_game_server`, `test_cockpit`, `test_autoplay_tester` and so on.

**The regression spine.** The "scripted scenarios" (the hand-traced proof fights §A and §C) are `harness.py`: `run_scenario` (§A) and `run_channeling_scenario` (§C), run over the in-code `SCENARIO_A`/`SCENARIO_C`.
- `tests/test_combat_scenario.py` asserts it.
- `test_cockpit.py` rebuilds both fights from `examples/loadout_*.json` and `encounter_a/c.json`.
- `examples/scenario_*.json` are REPL copies and have drifted from the code.
- `python -m ltg_combat harness` takes about 0.2 s.

**Fixtures in `conftest.py`:**
- **The data sandbox** (module level, before any app import): a fresh temp dir holds a copy of `content/` without `art/`, plus empty `loadouts/` and `saves/`, and `LTG_CONTENT_DIR`, `LTG_LOADOUTS_DIR` and `LTG_SAVES_DIR` point at it. `content.data_dir` (and the Deckbuilder's `LOADOUT_DIR`) read those variables at import, so every derived path follows. `_sandboxed_data_dirs` (session, autouse) fails the run if any root escaped the sandbox. It is removed at exit.
- `gate_clean_pool` / `clean_pool`: builds an encounter that passes every generation gate.

**Tests never touch the real data dirs.** Within the sandbox, per-test isolation is still per module:
- `_isolate`, `_isolate_content` and `_isolate_hidden_roster` snapshot the (sandbox) directories, then delete new JSON and restore the hidden lists afterwards.
- `_dirs`, `_isolate_dirs` and `_world_dir` monkeypatch the directory constants to `tmp_path`, which is the cleaner pattern.
- Some tests write with a `finally: unlink`.

Because the sandbox starts like a clean clone, tests must use the bundled `examples/` characters (`loadout_soren`, `loadout_ys`, …) or `tests/fixtures/`, never a per-install `loadouts/` file. The suite can run beside a live server, and two suites can run at once.

**CI** (`.github/workflows/ci.yml`): pytest on Ubuntu with Python 3.9 and 3.14, plus a non-blocking Windows 3.14 job; the client build (tsc) with a `dist/` drift check; `ruff check .` (F401 unused imports and BLE001 blind except, configured in the root `pyproject.toml`; the broad excepts that predate the rule carry `# noqa: BLE001`). Checkouts skip `content/art/`.

**Command:** `.venv/bin/python -m pytest tests/ -q` takes about 80 s (the 2026-09-02 review recorded 1,221 passing in 78 s).

## 13. Ops: launchers, updater, the Windows install

**Launchers.** `LTG-Start.command` / `.bat` is the front door. It creates `.venv` and runs `ltg-start`: the Deckbuilder on :8000 and the game on :8020. `LTG-Game`, `LTG-Deckbuilder` and `LTG-Autoplay-Tester` launch one app each.

**Updater** (`core/ltg_core/selfupdate.py`)
- It fetches, then `merge --ff-only` toward the branch's upstream (`origin/main` if none), then `pip install -r requirements.txt` (which applies `constraints.txt`).
- `_ff_failure` names what blocks the merge. Usually that is files the game dirtied under `content/`.
- The UI is Options → Settings → Updates, which runs a quiet check on open. Relaunch after updating.

**Quit** stops both apps and ends every player's session. `scope=all` calls `quit_sibling` (with `scope=self`), then `os._exit(0)` after 0.4 s.

**Windows standalone install** (`WINDOWS_INSTALL.md`, `LTG_Install_Guide.html`)
- Requires a full `git clone`; a ZIP download cannot update.
- There is no Node, so the committed `dist/` runs.
- There is no API key and no ComfyUI. Generation raises `ValueError("No OpenRouter API key set…")`, which surfaces as a 422/502 or a failed job, and art falls back to sigils.
- Shipped encounters and adventures still play. **Scenario Mode does not:** it needs the LLM, and `content/scenarios/` is empty.

**`.claude/launch.json` ports:** game 8020, game-alt 8021, game-ui 5173, deckbuilder 8012 and 8013, cockpit 8011, autoplay-tester 8030. There is no `ltg-start` config.

**Restarting.** The :8020 server usually runs **without `--reload`**. Restart it after Python edits.

## 14. How-to checklists

### Adding an effect verb

1. **`schema.py`:**
   - Add the model class and append it to `LEAF_EFFECT_CLASSES`. The unions and `effect_specs()` are derived from it.
   - Add per-kind rules to `Card._check_targets`.
   - Add the kind to `CORPSE_LEGAL_EFFECTS` if it may target corpses.
   - Ignore the module docstring's recipe: it points to `mappings.RENDERERS`, and `mappings.py` no longer exists.
2. **`translation.py`:**
   - `RENDERERS` is required; without it the raw kind shows in card text.
   - `_CLAUSE` is needed if the verb takes a target; without it `$slot` leaks into card text.
   - Optional: channeled phrasing and `@register` text rules.
3. **`engine.py`:**
   - Write `_r_<verb>(st, item, effect, target, ctx)` and add it to `RESOLVERS`. If it is missing, the engine only logs "unhandled".
   - Decide which classification sets the verb belongs in:
     - `_TARGETLESS`: resolves with no creature.
     - `_CARD_ZONE_VERBS`: acts on hero zones only.
     - `_STACK_FACING`: targets a stack item; also update `_target_sites`.
     - `_REACHES_DOWNED`: can land on downed heroes. Leaving it out is the safe default.
     - `_STAT_CONTINUOUS`, `_REAPPLIED_CONTINUOUS`, `_CHANNEL_TAG_KINDS`, plus a branch in **`_apply_static`**, if it has a `while_channeled` form.
     - `_DAMAGE_KINDS`.
   - Damaging verb: `_damage_verbs` and `_effects_damage` count only `deal_damage` today.
   - Removal verb: `_pick_options`, `_removal_legal`, `_boss_shrugs_removal`.
   - Control verb: `_filter_control_targets`, `_pending_control_claims`.
   - Label: `_effect_site_label`.
4. **`lints.py`:** only if you want a new advisory rule. There is no per-kind registry.
5. **`serialize.py`:** the `_HOSTILE_KINDS`, `_CONTROL_KINDS`, `_SIDE_SENSITIVE_HOSTILE` and `_CORPSE_KINDS` sets; `_status_tags` if the verb leaves a status, and `status_chips` if the card should wear it.
6. **Enemy use:**
   - `scenario._check_enemy_verbs`;
   - in `apps/game-server/ltg_game_server/llm.py`: `DEFAULT_INSTRUCTIONS` (the verb prose and the JSON block), `_SELF_DEV_KINDS`, `_SUPPORT_VERB_KINDS`;
   - if it deals damage: `content._HOSTILE_DAMAGE_VERBS` and its copy in `autoplay/runner.py`.
7. **Deckbuilder:** the editor is driven by `effect_specs()`. Only `CORPSE_KINDS` in `apps/deckbuilder/frontend/app.js` is a hand-kept fallback, and the server replaces it with `CORPSE_LEGAL_EFFECTS` at load.
8. **Autoplay:** `policies._SINK_ORDER` (bump `GreedyPolicy.version` if you change it) and `probes.COMBO_KINDS`.
9. **Tests:** nothing checks that every kind has a resolver and a renderer. Add `tests/test_<verb>.py` that checks `effect_specs()`, the rendered text, and resolution through `apply_action`.

### Adding a keyword

- Add a `KEYWORDS` entry.
- If players can buy it, add it to `CREATION_KEYWORD_COST`.
- Put the engine rule at each site that needs it, using `_has_kw(c, "kw")` or `"kw" in c.keywords`. There is no registry; see `_freed`, `_reachable_targets`, `_deal_damage`, `_resolve_effect`, `_redirectable`.
- Add it to `translation._KEYWORD_WORDS`.
- Add it to the LLM prompt if enemies may carry it.
- Add a test.

### Adding an enemy condition, target rule or reactive trigger

- **Condition:** `scenario._CONDITION_KINDS` (checked at load), `engine._condition_met`, the prompt.
- **Target rule:** `engine._component_target` (for reactive rules, `trigger_source` lives in `_reaction_target`), `llm._HERO_TARGET_RULES`, the prompt. Target rules are **not validated at load**: an unknown string is treated as a combatant id and the rule silently never fires.
- **Trigger:** `engine._trigger_matches`, plus `_pre_trigger_ctx`/`_post_trigger_ctx` if it needs new context, and the prompt. Unknown triggers also silently never fire. `on_charge_full` is handled elsewhere, in `_check_charge_full`.

### Adding a log event the client animates

There is **no typed registry**. The engine emits **148 distinct literal `type` strings** from 210 `_log` calls, and `LogEntry.type` is a plain `string` on the client.

1. Call `_log(st, "type", msg, **data)` with JSON-plain data only. The game server sends `e.data` unchanged through `ws.send_json`.
2. `snapshot.py` ships the newest 60 entries oldest-first (`LOG_TAIL`), minus `HIDDEN_LOG_TYPES`, through `_seat_log_line`. A line that names a hidden card or a veiled intent belongs in `PRIVATE_CARD_LOG_TYPES` or `VEILED_LOG_TYPES`.
3. Add a case to `switch (e.type)` in `apps/game-ui/src/lib/fx.ts` (43 types handled today), and a new `FxKind` if it needs a new visual.
4. Add the type to the tint sets in `SidePanel.tsx`.
5. If it should be counted, add it to `runner._collect_metrics`.

## 15. Known structural debts

Each of these is tracked as an objective in [roadmap.md](roadmap.md) (mostly M1, M8 and M9).

**Engine and core**

- **Engine size:** `engine.py` is 8.2k lines, and its section headers undersell what they contain.
- **Verb meaning is scattered:** about 10 engine sets, about 47 `.kind` literal comparisons, and more copies in serialize, llm, content, the runner, the policies, the probes and the Deckbuilder JS. No test checks coverage.
- **No typed event registry:** 148 event type strings, matched as strings on the client.
- **Duplicated rules in `serialize.py`:** it copies engine value functions (one has drifted), and the game server imports its private helpers.
- **Copy cost:** every call deep-copies the whole state, `_advance` runs twice per step, and the log never shrinks.
- **Saves:** `GameState` has no round trip, so saves happen only at boundaries. `ScenarioRun.snapshot`/`restore` (in the game server) are hand-maintained field lists.
- **Enemy JSON has no schema:** a typo in `target_rule` or `trigger` fails silently.
- **Hand-copied constants:** the runner copies the game server's balance constants and carry-over rules by hand.

**Server, client and ops**

- **Seats:** seats are keyed by socket, with no player token. A reconnect loses them, and confirmations count sockets.
- **Worker threads** (the act writer, the road ahead, the adventure and interlude jobs, the art painters) read and write the session only through `jobs.call_locked`, which runs the step under the session lock on the event loop; the LLM calls and file writes run unlocked. `load_save` / `continue_run` are still synchronous routes (roadmap M8.4), so a loaded save that needs its adventure job resumed sets `Session.resume_adventure_job`, and `ws_endpoint` starts the job when a client connects.
- **The phase-boundary wait** (§D25-3). When every seat has confirmed a level-up and the next phase is not written yet, `Session.confirm_level_up` parks the run (`AdventureRun.awaiting_phase`) without saving; `phase_landed` (called under the lock by the job) takes the fuller detail (`AdventureRun.add_phase`, a strict extension only) and, if the party is waiting, writes the phase-boundary save and composes the phase. The snapshot's adventure block carries `phases_ready`, `awaiting_phase` and `phase_error`.
- **Sync loads:** `load_save` and `continue_run` are synchronous, so the scenario hooks run inline and block HTTP on LLM calls.
- **Open admin routes:** CORS is `*` on a `0.0.0.0` bind, and the admin routes have no authentication (the Deckbuilder's too).
- **Untested surfaces:** CI runs the suite, the client build and a lint, but nothing tests the client's behaviour, the WebSocket, `selfupdate` or the launchers.
- **File encodings:** several reads and writes (`content._load_json` and `_write_content`, `scenario_content.py`, `ltg_combat.loader`, the autoplay tester) omit `encoding="utf-8"`, so on Windows they use the locale code page against UTF-8 JSON (roadmap M8.13).
- **Art in git:** about 315 MB of PNG art is tracked (more in history), written raw, and repaints only add to it.
- **`types.ts`** is hand-mirrored and has already drifted.
- **Sessions** live in memory and are never evicted. A restart loses mid-fight state back to the last boundary save.
