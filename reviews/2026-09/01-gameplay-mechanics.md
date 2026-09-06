# Work brief 1 — Gameplay mechanics

> **Superseded 2026-09-05.** The mechanics decisions were settled in discussion and recorded as canon in [`ltg_design_update_23_turn_groups_and_reach.md`](../../ltg_design_update_23_turn_groups_and_reach.md). Implement from that document. In particular: Defend and Mitigate scaling with Power is INTENDED (the tank's second axis), so the "retune" below is withdrawn; standing orders, the relevance auto-pass, Move previews, the swipe-trap change, the "Defend buffers the ally behind" rule and the stunned-turn change were rejected; the "rear-row shots ignore Mitigate" idea was wrong (enemies never Mitigate). The text below is kept only as the review record.

Source: whole-game review of 2026-09-02 (hands-on playtest plus thirteen subsystem code reads; their findings are folded into this brief). Every line number below was checked against the code on branch `UI-and-immersion-updates` at commit `1fba7f4`; re-grep before editing, they drift.

## Session kickoff (read first)

- Repo orientation: `README.md` (long, grep headings), `ltg_game_design_document.md`, `ltg_design_update_*.md` (later wins). The engine is `apps/combat/ltg_combat/engine.py` (7.9k lines); the game server is `apps/game-server/ltg_game_server/`; the client is `apps/game-ui/src/`.
- Tests: `.venv/bin/python -m pytest tests/ -q` (78 s, 1221 passing at review time). Do not run the suite while a game server is hosting: tests write into the real `content/` and `loadouts/` directories.
- Rule of the house: the engine is pure and deterministic; the server submits synthetic actions through `apply_action`; the client computes no rules.
- Settled decisions to respect: ultimate-gauge payouts for churn, tanking and downing are intended; the owner wants MORE enemy control pressure, not less; Defend retune (temp HP = base Power) is an open item you may resolve here; Design Update 08 §D8-4's "no user-configurable stops" is the one settled decision this brief deliberately overturns, with evidence.

## Item 1.1 — Kill the reaction-window pass parade

### Problem (verified)
- `auto_pass_action` (`engine.py` ~7734-7780) auto-passes only when the legal set is exactly `{pass}` (or `⊆ {end_turn, delay}`), never for a channeler. Any hero with an unused Mitigate (legal against every single-target enemy attack, including ally mode for a reachable ally, see the Mitigate offers around `engine.py` ~7120-7150) or any instant in hand keeps every window open.
- Hands-on: one enemy turn, 5 enemies vs 3 heroes, produced "Alder passes. Bort passes." for every enemy action: 10 manual Pass clicks before the party could act again. A 4-hero party vs 8 enemies is ~24 clicks per enemy turn. It scales linearly with party size and caps co-op.
- `ltg_design_update_08_tier_one.md` §D8-4 (~line 186-205) calls the pass-tax "the game's worst flow cost" and then says "There are no user-configurable stops — the rule below is the whole feature". Nothing in the code offers pass-for-the-phase or standing orders (grep for `pass_all|standing|auto_react`: nothing).
- The client compounds it: every batch with a HOLD kind gates the whole console for `max(delayMs) + 680 ms` (`store.ts` ~20-24, ~365-376, ~418-427; `BottomBar.tsx` ~124-132), on top of the server pacer's dwells (`session.py` ~44-46: 1.1 s beat, 0.6 s hold). Clicks during the hold are swallowed, not queued. Each Pass in the playtest waited 1-2 s.
- The reaction strip says "Reaction Window" but not what is being answered or what Mitigate would reduce; `mitigate_value` ships in the snapshot and is unused (`ActionBar.tsx` ~100-104; `types.ts` ~170). (Fixing this belongs to brief 2 item 2.2 but matters here: each window should be a one-glance decision.)

### What to build
1. **Standing orders, per hero, server-side.** A small per-character setting owned by the session (persisted in the run options): `stop_for: {lethal: true, hit_at_least: N|null, channel_start: true, instants: true, mitigate: "always"|"self_only"|"never"}`. In the paced drain (`session.py` `_auto_advance` ~213-233 / `_drain_paced` ~244-288), before offering a window, evaluate the legal set against the orders: if every non-pass option is filtered out, submit `Action("pass", auto=True, label="Pass (standing order)")` through the same `apply_action` path. The engine's `legal_actions` stays the truth; the log says what happened.
2. **"Pass for the rest of this enemy phase"** button in the reaction strip: a session flag cleared at the next player phase; while set, the drain auto-passes that seat. Also a Shift+Pass or hotkey (brief 2).
3. **Relevance rule (engine-truth, deterministic):** treat a window as auto-passable when its only non-pass options are ally-mode Mitigates for a hero who is not the struck target of the top stack item, or a Mitigate whose `X` is 0 against the blow. Implement as a helper next to `auto_pass_action` so the runner and tests can call it; keep `auto_pass_action` itself unchanged for the cockpit.
4. **Client hold:** do not hold when the batch's FX touch no party member and the stack top has not changed; cap the hold at ~500 ms when the pending prompt is a reaction window; let a click on Pass during a hold queue the submit instead of swallowing it (`store.ts` ~365-376; `fx.ts` ~159-166, ~362-380).
5. **Telemetry:** tally reaction windows opened per round and manual passes in the autoplay runner (`apps/combat/ltg_combat/autoplay/runner.py` ~306-464 collects metrics; `report.py` ~41-90 surfaces them) so the fix is measurable. The engine already logs a `pass` event per character (`engine.py` ~2260).

### Acceptance
- A 3-hero party vs a 5-enemy standard layout completes an enemy turn with at most one manual click per hero per turn under default orders, and zero when "pass for the phase" is set.
- Determinism: same state + same orders always auto-passes the same seats (extend `tests/test_design_update_08.py`'s auto-pass tests; add a runner metric assertion).
- No engine rule changes; cockpit behaviour unchanged.

## Item 1.2 — Make position and defence real decisions

### Problem (verified)
- **Move is priced out.** `_do_move` (`engine.py` ~2702-2718) spends the whole proactive action unless the mover has haste; the label is a bare "Move to Rear" (`engine.py` ~7049) with no consequence preview even though `_recheck_intents` is deterministic and cheap to simulate on a copy. The reference greedy policy has no Move rule at all (`autoplay/policies.py`), so nothing has ever measured positional play (Update 15 §L-7 asked for that before balance conclusions).
- **Interposition covers only nominal melee basic swings.** `_redirectable` (`engine.py` ~1626-1637) requires `intent.kind == "action" and intent.action_type == "attack"`; component telegraphs never redirect, so a melee "Battering Ram — deal 5" combat ability (Mitigate-answerable since §M-A.7) walks past the wall, and the veiled telegraph does not tell the player which intents honour the wall (`serialize.py` `_veiled_entry` ~190-225 ships no `redirectable` bit).
- **Defend and Mitigate scale with Power.** Defend = base Power temp HP (`engine.py` ~2936-2941); Mitigate X = ceil(current Power / 2), min 1 (~2689-2700). A Power-1 caster gets +1 and X=1; the bruiser who least needs it gets the most. Memory notes the Defend retune as open.
- **Rows matter only for enemy melee.** `_reachable_targets` (~6789-6825) restricts melee to the front-most enemy row; the lunge auto-corrects the hero's own row; there is no row-conditional offence anywhere in shipped content (`"property": "row"` appears in 0 content files; the `caster_property row` condition at ~4238-4243 is unused).
- **Ally-Mitigate trap on row swipes:** for a positional attack the ally loop offers "Mitigate for X (move to row)" to a guard in an adjacent row (~7130-7148); the dash lands the guard in the swept row and they eat their own hit unmitigated (~2732-2735, ~2751). No label warns.
- Small related: the Ultimate silently vanishes once any proactive action was taken (`_heroic_actions` ~7208-7212) with no tooltip reason; a stunned hero's own main phase offers nothing, not even free instants (`_legal_main` ~6994-6996), contrary to the `_r_stun` comment (~5178-5182).

### What to build
1. **Move previews.** When enumerating Move actions (`engine.py` ~7040-7050), simulate the move on a deep copy, run the re-check, and put the outcome in the label / a new `preview` field: "Move to Rear — Grukk's Cleave redirects onto Soren", "Move to Mid — you leave the Cleaver's row". Serialize it; the client shows it in the arming hint.
2. **Move as a half-action.** Legal while the hero has not attacked this turn (Move + Cast, Move + Defend legal; Move + Attack still needs haste). Enemy-side attack-of-opportunity triggers already exist as a design lever (§L-2.2) and can price it back if playtest says so.
3. **Interposition for melee combat abilities.** Extend `_redirectable` to melee-mode, single-target, ground combat abilities (the §M-A.7 derived class), excluding flying/relentless attackers and positional intents. Add a `redirectable` bit to the veiled entry so the client can stamp "swing" vs "pursues" (brief 2 item 2.1 renders it).
4. **Defend/Mitigate retune.** Pick one: Defend grants `max(base Power, ceil(max_hp / 6))`; or Defend also grants Mitigate-again this turn (a reaction enabler); or a Guard stat in the 70-point build. Keep the gauge credit for temp HP as is (intended).
5. **Rows with offensive meaning** (one or two rules, content can grow from there): rear-row ranged attacks ignore the first point of Mitigate; a front-row hero's Defend also buffers the ally directly behind. Teach the generation prompt and the deckbuilder that `caster_property row` exists.
6. **Fix the swipe trap:** exclude out-of-row guards from positional Mitigate offers, or mitigate the guard's own hit too and say so in the label.
7. Small: show the "opens the turn" rule in the Ultimate's disabled tooltip; offer instants and channel drops during a stunned main phase.

### Acceptance
- Greedy policy gains a minimal positional layer (vacate a lethal row; interpose when it saves more than the forgone attack; use the haste free move) so the harness measures the change; add `positional_relevance` (redirects, whiffs, moves per game) to the runner metrics.
- Tests: `tests/test_movement_mitigate.py`, `tests/test_design_update_15.py`, `tests/test_defender_and_defend.py` extended for previews, half-action Move, ability interposition, the swipe trap.

## Item 1.3 — Give fights a shape the content actually uses

### Problem (verified)
- **Boss dials are absent from content and never defaulted.** `_begin_turn` (`engine.py` ~288-298) fires the timed enrage and neglect only when `enrage_round` / `neglect` are set; 21 shipped bosses carry neither; `content.py` validation (~620-631) and the boss difficulty pass (~1328-1334) do not default them; `_objective_problems` / `_boss_pressure_problems` in `llm.py` are generation-only gates. Every adventure already on disk is the shelve-the-boss fight the dials were built to end.
- **Objectives can never be on the climax.** The adventure prompt contract (`llm.py` ~1994-2000): at most one objective per adventure, only on Phase I or II, "Phase III is ALWAYS the standard boss kill". Objective kinds are a stringly switch replicated in ~7 places (schema `EncounterObjective._coherent`, combat `scenario.py` `_resolve_objective`/`_objective_state`, engine `_deploy_objective_arrivals` ~638 / `_objective_tick` ~686 / `_objective_shielded` ~719 / `_race_expire` ~763, `serialize.objective_block` ~793-832, `content._validate_objective` ~734-805, `policies.py`), so kinds do not compose.
- **Neglect punishes the decks that are killing the boss.** `hurt_this_round` is set only inside `_apply_damage` (`engine.py` ~6481). `_tick_afflictions_one` (~6039-6058) and `_r_lose_life` (~4589-4598) mutate hp directly, so a poison or life-loss deck "goes unbloodied" every End Step (~2072-2083) and the boss grows +N/+N.
- **Timed enrage announces at Upkeep but lands in an unrelated window:** the `on_enrage` component is evaluated only post-resolution (`_trigger_matches` ~2402-2406), so the blow arrives after the player's first spell or the boss's first swing. `_race_expire` (~793-801) already shows the right pattern (push the payload directly).
- **A reserve (waves) boss ignores its fuse:** `enrage_round` and `neglect` are absolute turn numbers evaluated over `living_enemies()`; a boss deployed on turn 6 with `enrage_round: 4` enrages at its first upkeep. `_deploy_reserve` (~676-684) records no `deployed_turn`.
- **AI is solved once learned.** Components are priority-sorted with cooldowns as the only variety (`_proactive_rules` ~996-1003; `_rank_valuation` ~1304). Conditions (`_condition_met` ~1026-1063) know self HP, turn, counts, channeling, gauge, primed; nothing reads hero rows, hero HP %, corpse count, hero types/classes. Cadence counts declarations not rounds (`_note_swing` ~893, force at ~853/~909-911) and overrides even emergency-band components. Component cooldown starts at declaration for a boss's slot 1 (~861-862) but at execution for everything else (~1939-1940), so strip-locking a one-trick minion is free (`_strip_slot` ~5035).

### What to build
1. **Engine defaults for boss dials** when the encounter omits them and does not set `null`: `enrage_round = 3 + level // 3`, `neglect = 1`; apply in `content.py`'s build path (near the boss difficulty pass) so old content gets the pressure without a migration. Guardless races: auto-ward the target with the highest-HP non-target minion.
2. **Objectives as boss-fight modifiers.** Lift the Phase III ban for modifier-shaped objectives: guards on the boss until its lieutenants fall (`_objective_shielded` already works on any enemy id), a reinforcement schedule during the boss phase, a deadline with narration. Longer term, refactor kinds into orthogonal clauses (`clock`, `schedule`, `marks`) evaluated generically; today's four kinds become presets.
3. **Neglect counts every party-sourced HP drop:** set `hurt_this_round` in the poison tick, `lose_life`, and wound paths, or snapshot `effective_hp` at `_begin_turn` and compare at End Step.
4. **One-beat enrage:** at the timed crossing push the Enrage component straight onto the stack (the `_race_expire` pattern). Store `deployed_turn` on reserve deploy and evaluate both dials relative to it.
5. **AI temperament without breaking determinism:** a seeded tiebreak within a priority band (use the existing `rng_seed`) or a per-enemy `temperament` that permutes bands; add conditions `hero_in_row`, `hero_hp_pct`, `corpse_count`, `turn_mod`, and a `target_rule: hero_class:<x>` so generated enemies can hold grudges. Exempt priority 10-19 (emergencies) from the cadence force; make cooldown spend at declaration everywhere.
6. Teach `llm.py`'s enemy prompt the richer verbs the engine already resolves but shipped enemies never use: `conditional`, `redirect` (bodyguard), `fight` (duelist), `amplify` (visible gathering), `remove_keyword` (anti-flyer). Library census: 0 uses of each across 243 enemies.

### Acceptance
- A shipped pre-dial boss now enrages and swells on schedule in the harness; a poison deck no longer triggers neglect; the enrage beat is a single stack resolution.
- Tests: extend `tests/test_boss_pressure.py` (dial defaults, reserve boss, one-beat enrage), `tests/test_enemy_bloodied.py`, `tests/test_enemy_intelligence.py` (cadence bands, cooldown at declaration, new conditions).

## Quick rules fixes to land first (all verified, each small)

1. **Silence blocks Skill and Ultimate.** `_hero_ability_actions` (~7216) enumerates through `_cast_actions` (~7228), which returns `[]` when `_silenced_for` (~6217-6225) is true; the docstring says heroic actions are never gated. Pass a `heroic=True` flag or check `card is actor.skill / actor.ultimate`. Add the missing test in `tests/test_silence_and_sap.py`.
2. **`_is_targeted` is blind to `$slot` refs.** (~4350-4352) `getattr(str, "targeted")` is False, so the legal-target gate (~4039) and the hexproof fizzle (~4047-4053) are skipped for slot-referenced cards (about half of custom-deck effects). Resolve through `_effect_desc(item, effect)` (~5608).
3. **`_kill_enemy` / `_remove_token` are not idempotent** (~6654-6704): a victim killed mid-loop by aura reaping is killed again, logging a second death, purging the stack again and appending a duplicate Corpse. Early-return when the body is already off the board, or `continue` on a dead victim in the loop at ~4085.
4. **Unknown `Ref.ref` names validate and crash mid-resolution.** `Ref` (schema ~320-335) checks only `mult`; `_ref_value` (~4389-4430) raises ValueError at cast time. Add a `field_validator("ref")` against `REF_VALUES ∪ {"$…"}` (see brief 3 item 3.3 for the wider schema hardening).
5. **Taunt-with-teeth freezes its bite at declaration** (~1364) unlike the basic swing, so a wound landed after declaration does not blunt it; carry `attack_power` the way `_declare_default_attack` does (~986-991).
6. **A PC downed by a continuous aura is downed silently:** `_reap_aura_kills` (~3455-3462) skips PCs and `_reap_dead` (~2095-2107) never calls `_after_damage`, so no incapacitated log, no gauge credit, no death event. Route it through `_after_damage`.

## Suggested order
Quick fixes (half a day) → 1.1 (the biggest felt change; two days incl. telemetry) → 1.3 steps 1, 3, 4 (a day) → 1.2 previews and interposition (two days) → 1.2 retune and rows (design session + a day) → 1.3 steps 2, 5, 6.
