# LTG roadmap — milestones & objectives

**As of 2026-09-24** (commit `a2cce25`). This page lists everything designed but not built, built but never tested, or verified as broken. Its sources are:

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
| **M1** | Make it correct | Verified bugs: two crash or loop, several would spoil the campaign playtest, and the rest are rules and session faults. Most are S. | 37 |
| **M2** | Legibility | The board explains itself: status, threat, boss state, beats, hand. The biggest felt improvement per hour. | 22 |
| **M3** | The playtest loop | Make the RPG layer cheap to test, then run the playtests that are owed | 12 |
| **M4** | Generation pipeline | Faster, cheaper, sturdier, less samey generation, with gates that match the prompts | 18 |
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

*Done when:* every row is fixed or ruled on, and each fix lands with a test. M1.1–M1.3 come first because they crash or break play outright. M1.4–M1.9 gate the campaign playtest (M3.6).

**Crashes and runaway loops**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.1 | **Python 3.11+ crash.** Fixed: `engine._move_shuffle` seeds with the str `f"{rng_seed}:shuffle:{n}"`, pinned by `test_seeded_shuffle_is_pinned_and_runs_on_every_python`; CI runs 3.14 (M0.3). Seeded in-game shuffle orders changed once. | Done 2026-09-25 | — | arch notes |
| M1.2 | **Unlimited Skill.** A Skill that carries `modify_action refresh_skill` on its caster can be re-used without limit in one main phase: `_proactive_open` keeps the taken mode open and the refresh clears `skill_used`. Reproduction: the local Vay loadout ("Perfect note") vs `the_sootfall_adit__phase2`, seed 99, 4,000 actions in round 2. | Bug | S | arch notes |
| M1.3 | **`python -m ltg_combat validate` raises `AttributeError`.** `engine.run` still reads the removed `Character.archetype`. Fix it or retire the stale `run()`. | Bug | S | arch notes |

**Campaign and scenario flow**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.4 | **Phase III objectives are vetoed.** `content.save_adventure` still rejects every Phase III objective that §D23-5 allows, so every generated boss-phase objective is repaired away and the feature has never run. Delete the pre-check and add a `save_adventure` test. | Bug | S | C-22; §D23-5 |
| M1.5 | **Unreachable foreshadow topics.** An NPC who also has an interlude tree never offers them, so the party hasn't "already heard" that hook. Short-term: allow foreshadow only on NPCs without a tree. Full fix: M5.3. | Bug | S | C-45; §D24-5.1 |
| M1.6 | **The hook's bridge never reaches Act I.** It reaches the arc writer but not the act writer who writes Act I's arrival. Pass the chosen hook to `generate_act` on a continuation. | Bug | S | C-44; §D24-5.3 |
| M1.7 | **In-session Continue skips the live-identity refresh** (`refresh_instance` runs only on load). While there, rule on the refresh overwriting **attack mode, row and the keyword**. The keyword is priced in the points-buy, so changing it silently changes the build's cost. | Bug / Decide | S | C-47; §D24-6; GDD v2 §14 notes |
| M1.8 | **Unlocked worker threads.** The interlude worker (`InterludeJobRunner._generate_locked`) mutates the session from a thread without the lock. `_materialize_task`, `_continue_task`, `generate_sync` and the art painters do the same (the general fix is M8.4). | Bug | S–M | C-65; R3.1.5 |
| M1.9 | **A failed act materialization wedges the town** until a reload. Add a `retry_materialize` verb, an `act_start` save before materializing, and a player-facing message. | Not built | S–M | R3.1.6 |
| M1.10 | **Rest isn't guaranteed.** The act validator doesn't require an innkeeper `rest` choice, so an act can leave the party no way to rest. | Bug | S | GDD v2 §14 notes |
| M1.11 | **Reward items vanish silently.** `assign_reward` checks room against the pre-adventure copies, items land on the adventure's copies, and the `ValueError` is swallowed. | Bug | S | R4.3.6; GDD v2 §14 notes |
| M1.12 | **Unspent creation points are lost in campaigns.** A hero built under 70 points loses the difference: `ScenarioRun.banked` starts at 0, while a lone adventure banks it. | Bug / Decide | S | GDD v2 §14 notes |
| M1.13 | **`town:` lore gates never open.** `generate_act` passes the composed town's id, which has been popped, so it arrives empty. | Bug | S | GDD v2 §14 notes |
| M1.14 | **The arc writer at a campaign's first scenario** gets only a roster line: no briefs, situations or world block. §D24-7.6 says all heroes' briefs at scenario start. | Bug | S | generation notes |

**Data safety**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.15 | **Run data leaks into tracked `content/`.** Quest-accept adventures (`run_only=True`) go through `_write_content`, and 13 are already committed. A `new` hook's town, its worldbook entry and the reverse edges also edit tracked files. This dirties the tree and blocks the brother's in-app update. Write run content to the run's store (or `content_local/`, M8.8), and remove the 13 files. | Bug | M | B-39, C-62; §D17-3.3 |
| M1.16 | **Name collisions overwrite.** `save_encounter`, `save_adventure` and `save_town` key files by the slug of the name, and a `new` hook whose seed repeats a town name overwrites that town. | Bug | S | generation notes |

**Rules engine** (verified in code; GDD v2 records the current behaviour)

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.17 | **One Mitigate per stack item.** A second hero's Mitigate on the same swipe silently replaces the first, and the first guard's once-per-round use is wasted. §L-5 says each struck character may self-Mitigate. Either support several, or stop offering the second. | Bug / Decide | S–M | §L-5; `StackItem.mitigate_by` |
| M1.18 | **Taunt from behind the wall** makes melee swings fizzle or deflect instead of landing on the taunter; §R-11 says the taunted hit lands regardless of row. `test_taunt.py` only uses a ranged enemy. | Bug / Decide | S–M | §R-11 |
| M1.19 | **Curve-up colours** are read from `starting_mana`, not the character's colours, so a colour missing from starting mana can never be locked. A `choice` ramp or ritual auto-resolves to the first colour. | Bug | S | §4.4 |
| M1.20 | **Sap and channel reservation overlap instead of stacking**: pool = min(cap − reserved, cap − sap). | Bug | S | code ruling 2026-08-21 |
| M1.21 | **Countering a basic swing pays about double gauge**: `_denied_value` adds both `attack_power` and the swing's `DealDamage`. | Bug | S | gauge rework |
| M1.22 | **T-27 caps live tokens at 2 per creator.** That silently clips the party-size Enrage token scaling (§D18-2) and race escalation waves at party sizes 3–4. Decide whether Enrage bypasses the cap. | Bug / Decide | S | register notes |
| M1.23 | **Enemy rules skipped for want of a target.** A ranged enemy in Front can't aim any component at a hero, spells included, although §D23-3 says spells are unaffected. More generally, `_try_declare_component` skips any rule whose non-`self` target rule finds nobody, even when its verbs are untargeted (a `mode: all` blast). | Bug | S | §D23-3; GDD v2 §9 notes |
| M1.24 | **Easy bosses still get two intents.** `build_state_from_loadouts` passes `scenario.get("difficulty") or "standard"`, and neither `encounter_for` nor `scenario_from_detail` carries the difficulty. So every boss is stamped `double_intent`, including on Easy. | Bug | S | GDD v2 §9 notes; T-54 |
| M1.25 | **Enemy lockdown mostly expires before it bites.** Enemies act after the party, so these are gone before the hero's next turn:<br>• a one-shot `prevent` (Silence / Pacify) ignores its duration and clears at End Step;<br>• `this_turn` modifiers and sap end at End Step;<br>• a taunt on a hero clears at the next Upkeep.<br>A one-shot `prevent` on an enemy also never cancels its declared intent. The owner wants *more* control pressure, so rule on the intended durations. | Bug / Decide | M | GDD v2 §9 notes; lockdown ruling 2026-08-21 |
| M1.26 | **Smaller enemy-rule findings:**<br>• a wound that drops a boss into its window doesn't enrage it until the next HP change;<br>• a `post_enrage` rule on a minion is never eligible (the comment says "ignored");<br>• neglect applies to any enemy with `neglect > 0`, from any HP drop, not just party-sourced ones;<br>• enemy-raised undead are permanent;<br>• `survive` can't be won early while reinforcements wait in reserve (§D12-1.2 says it can);<br>• the 2× minimum-bodies rule isn't checked on hand-authored standalone encounters. | Bug / Decide | S each | GDD v2 §9, §12 notes |
| M1.27 | **Four rulings needed** on behaviour the canon records as-is:<br>(a) regen ticks and mana paid for the Skill earn no gauge;<br>(b) amplify applies after Mitigate ((h−X)×m), contrary to its docstring;<br>(c) consumables stack as kind `ability`, so an `activated`-filter counter can't answer them;<br>(d) enemies never aim at, or get walled by, ordinary ally tokens. | Decide | S each | GDD v2 §4 notes |
| M1.28 | **Stale lines worth a ruling** rather than a silent code change:<br>• a bounced enemy returns to the row it was bounced *from*;<br>• released channel mana returns straight to the pool, not as a stack trigger;<br>• first strike is a plain basic attack in any Enemies-step window;<br>• bosses get two intents from round 1 on standard/hard (T-54, code-only). | Decide | S | GDD v2 notes; A-49 |
| M1.29 | **Small fixes:**<br>• the `infect` gloss predates §D22-2 (A-42);<br>• `serialize._mitigate_value` lacks the engine's minimum of 1 (R3.3.3);<br>• `_DAMAGE_KINDS` and the llm taunt gate list `"drain"`, which isn't a verb;<br>• the sheet's "effective level" isn't the one budgets use. | Bug | S | A-42; arch and §14 notes |
| M1.30 | **Enemy deathtouch does nothing.** `_deal_damage` executes only `EnemyState` victims, yet the prompt prices deathtouch for enemies (L3 / 4). Make it work on heroes and party tokens, or drop it from the enemy table. | Bug / Decide | S | GDD v2 §7 notes |
| M1.31 | **More rulings from the §5–§11 review:**<br>• `indestructible` dies to destroy and deathtouch, and ignores its 1-HP floor against life loss and poison;<br>• `*_base_power` refs include +1/+1 counters, though the comment says otherwise;<br>• a hero channel watching `spell_cast` with `who: enemy` never fires;<br>• an enemy `channel_drop` on an event trigger does nothing;<br>• only one post-resolution enemy reaction fires per resolution across the whole enemy side (an AoE hitting three `on_hit` enemies draws one punish);<br>• an untargeted `chosen` effect still lands on a target bounced or suspended in response;<br>• a hero's taunt re-aims even an enemy's support heals. | Decide | S each | GDD v2 §5–§11 notes |

**Server and session**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M1.32 | **Guards.** A rule error in the ws `confirm` branch or anywhere in dispatch should send an `error` frame, not drop the player's seats. Also: guard the pacer, make `_AUTO_CAP` exhaustion loud, use `get_running_loop`, and validate message shapes. | Bug | S | R3.1.1 |
| M1.33 | **The combat log isn't seat-filtered.** Teammates see each other's draws (the `draw` line names the card). | Bug | S | arch notes |
| M1.34 | **The server trusts the client on two gates.** Start Adventure is disabled only in the client, and `set_situation` is accepted anywhere in town. | Bug | S | GDD v2 §14 notes |
| M1.35 | **The veil leaks through the log.** `_recheck_intents` logs `intent_redirect` with the intent's name (its telegraph, often with numbers), and only `intent_declared` is hidden from seats. | Bug | S | GDD v2 §5 notes; §D8-1.4 |
| M1.36 | **Deckbuilder port mismatch.** With the Deckbuilder on another port, the game's Quit and Edit still target 8000 unless an env var or localStorage key is set. | Bug | S | arch notes |
| M1.37 | **Adventure runs are saved but unreachable.** "As a run" adventures are written as `kind: adventure`, but Load Game filters them out. List them or stop offering the option. | Decide | S | GDD v2 §14 notes |

## M2 · Legibility — the board explains itself

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
| M2.1 | **Chronicle.** It is sent newest-first but pinned to the bottom, so new lines append out of view (since `347dfa7`, 2026-08-29). Fix the order or the pin, key rows by `seq`, and page past `LOG_TAIL = 60`. | Bug | S | R2.1.1; obs. |
| M2.2 | **FX key mismatches.** The stun FX never renders (it reads `d.target`); a channel-suspend exile plays the banish implosion; regen glows like a heal. | Bug | S | R2.1.6 |
| M2.3 | **Arming is cancelled by any snapshot.** A teammate claiming a seat resets your half-paid X cast. | Bug | S | R2.2.8 |
| M2.4 | **Party column overflow.** Three heroes in one row don't fit at 1440×900 (the bottom card sits under the console). | Bug | S | obs. |
| M2.5 | **Card flavour in play.** `card_dict` omits `flavor_text`, so about 65 generated lines are never seen. Show them on the enlarged card and the Stack hover. | Partial | S | R4.2.5, C-53 |
| M2.6 | **Hover-enlarge** hand cards, on focus too, reusing the Stack/Chronicle popup. | Not built | S | R2.2.1 |
| M2.7 | **Why-not chips** on dimmed cards ("2 short", "sorcery", "no target", "holding"), with a server `unplayable_reason` where the client can't know. | Not built | M | R2.2.2 |
| M2.8 | **Status chips** on hero and creature cards (`status_tags` on `CreatureView`: silenced, pacified, sapped, warded, taunted…). | Not built | M | R2.1.5 |
| M2.9 | **Boss state on the card.** An enraged plaque, a neglect-swelling badge and a `guarded_by` hairline. The objective banner stays up with its outcome line. | Not built | M | R2.1.3 |
| M2.10 | **Beats.** FX and Chronicle tints for `guards_down`, `wave_deployed`, `reinforcements`, `escalation`, `objective_complete`, `withdraw`, `neglect`, `redeploy`, plus a `PhaseBanner` flash. | Not built | M | R2.1.2 |
| M2.11 | **Persistent threat marks.** A chevron with a count on each targeted hero, a hairline while surfaced, and animation on `intent_redirect`. The swing/pursues stamp is already done. | Partial | M | R2.1.4 |
| M2.12 | **Entrances** for tokens, raised or risen dead, waves, reinforcements and redeploys, plus a "next round: 2 Raiders" preview. | Not built | M | R2.1.7 |
| M2.13 | **Sap in the mana widget.** Classifier fixes: an enemy forced `move` counts as interference, and corpse `control` / `consume_corpse` as summon. | Not built | S | R2.1.8 |
| M2.14 | **End Turn guard.** A count on the button and a one-click confirm, with a Settings toggle. | Not built | S | R2.2.5 |
| M2.15 | **Keyboard.** Pass/End Turn, 1–9 for cards, A/D/M/V for the verbs, Enter in the mana picker; `role` and `tabIndex` on cards. | Not built | M | R2.2.4 |
| M2.16 | **Mana payment.** Auto-pay the fixed pips so clicks add only X; a max-X button; ask for generic colour only when it matters. | Not built | M | R2.2.6 |
| M2.17 | **Damage preview while aiming** a basic attack ("→ 4 · kills", "ward eats 2"). | Not built | M | R2.2.7 |
| M2.18 | **Scope the right-click cancel** to the board and console (it currently kills paste in Options). Add a themed tooltip component to replace `title=`. | Not built | M | R2.2.9 |
| M2.19 | **Tag `damage` events with a `mode`** and delete the client's label→mode guess. Best done after M9.2. | Not built | M | R2.1.6 |
| M2.20 | **The Ultimate cell**: a turn-rule reason when it is disabled, no banned word "action", and placement in the Skill cell as §D23-9 lays out. | Partial | S | C-33 |
| M2.21 | **The turn diamond** now shows on every sorcery and channel card, castable or not (a2cce25). §D23-9 says castable only, and gold means "clickable". Gate it, or ratify the static mark. | Decide | S | C-34 |
| M2.22 | **Panel clips.** Loop the `channel` clip while a stance is held (§A-7). Fill in coverage: Soren, Vay and Ys have none; Bones lacks ultimate and victory. | Not built | M | B-27, B-30 |

*Rejected, do not re-add:* the reaction strip; the "Mitigate −N" label (removed in playtest, 2026-09-06).

## M3 · The playtest loop

*Why:* seeing the interlude once takes nine fights, three adventure generations (≈$3 each on Opus 5 Fast) and three act generations. As a result the flagship Update 24 path has never been played, and every retune waits on a human evening.

*Done when:* the campaign loop and the retune watch-list have been played, and a fresh session can reach any campaign state in minutes for cents.

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M3.1 | **Jump-to states.** Fabricate campaign states for testing: "Act III boss down with a plausible ledger" → interlude, mid-act, after a defeat, a `between` campaign. | Proposed | M | advisory |
| M3.2 | **Autopilot fights** in scenario mode. The existing policy plays the combat phases while a human plays the towns. | Proposed | M | advisory |
| M3.3 | **Cheap-model dev profile.** One switch routes every task to a volume model (Luna Pro or Gemini Flash) for flow testing; premium models are kept for judging quality. | Proposed | S | advisory |
| M3.4 | **Record and replay LLM responses**, keyed by prompt hash, so UI and flow iteration doesn't regenerate. | Proposed | M | advisory |
| M3.5 | **Regenerate the scenario library** (`content/scenarios/` is empty). Do M4.5 (the avoid-list) first. Decide whether library scenarios bring back a pre-baked Act I adventure, which gives an instant start and lets a keyless install play Act I. | Not built / Decide | S–M | C-05, C-04, B-52 |
| M3.6 | **Play the campaign loop.** Finish a scenario, Continue, and choose each hook kind once (stay / neighbour / new). Kholdrun is deleted, so start from Town + New in Karzum. Needs M1.1–M1.9. | Untested | M | C-42; §D24 Part E |
| M3.7 | **Regenerate Karzum Act I with a briefed party** and judge the `# THE PARTY` block. The baseline is in git at `1ae6620^`. | Untested | S | C-41 |
| M3.8 | **Review the four backfilled worldbook entries.** All edges run through Azure as a hub, and Karzum sits in `frostcap_peaks`. | Untested | S | C-43 |
| M3.9 | **Retune watch-list at the table.** Five open checks:<br>• §M-A.7 made 72 shipped components mitigatable<br>• Defend = base Power magnitude<br>• Enrage at party size 4<br>• gauge c = 20<br>• boss round-1 double intent<br>The lockdown budget is watched too, but only to push control pressure up; never tune it down. | Untested | M | C-01, C-02, C-39, C-40; T-54 |
| M3.10 | **Economy across a multi-scenario campaign:** T-79 prices, T-81 effective level, gold income versus sinks, and the free rest. | Untested | M | B-36, B-40, B-57, A-33 |
| M3.11 | **Legacy content.** None of the 21 shipped bosses has boss dials. 136 of 243 enemies lack types and classes, so grudges and type-gated cards read nothing. Regenerate, or default the dials at load. | Decide | S–M | C-23, C-13 |
| M3.12 | **A rule for A-20:** a hero downed by a turn-scoped wound stands back up when it expires. Pin the ruling with a test. | Untested | S | A-20; §R-13.1 |

## M4 · Generation pipeline

*Why:* an adventure is one call: a ≈23k-token system prompt, up to 64k output tokens, and a 15-minute timeout. A single bad enemy re-emits all three phases, there is no caching and no transport retry, and quest-accept latency is the wait players feel. Gates are also looser than the prompts in several places.

**Latency, cost, resilience**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M4.1 | **Prompt caching** (`cache_control`) on the ≈21k-token encounter system prompt and the scenario prompts. | Proposed | S | advisory |
| M4.2 | **Phased adventures.** An outline call (villain, boss, phase themes, narration beats), then Phase I, then Phases II–III generated in the background while Phase I is played. The quest-accept wait drops to the outline plus one phase. | Proposed | M–L | advisory; C-04 |
| M4.3 | **Per-phase repair.** Validate every phase before re-prompting, report all problems, and re-generate only what failed. | Proposed | M | generation §7 |
| M4.4 | **Transport resilience.** Bounded retry with backoff on 429/5xx/timeouts; treat `TypeError` / `AttributeError` from the gates as repair turns; coerce deterministic faults in code. Give encounters a real timeout: 120 s against a 24k ceiling, with only 2 attempts. | Not built | M | R3.2.8; generation notes |

**Quality and variety**

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M4.5 | **Avoid-list** of existing town and NPC names and villains for the arc and town writers. Cross-model convergence (Hedda, Pip, Rook, the ledger-necromancer) doesn't regenerate away. | Not built | S–M | C-11 |
| M4.6 | **Party tactical facts** to the enemy designer and act writer: keyword, attack mode, row, Skill/Ultimate, types/classes, gear, deeds. Today it sends name, level, colours and concept only. | Partial | S | R4.2.1, C-57 |
| M4.7 | **Teach grudges** (`hero_class:` / `hero_type:`): the engine has them, the prompt never mentions them. | Partial | S | C-25; §D23-6 |
| M4.8 | **Enemy pricing gate.** Compute each generated enemy's cost from the §F tables and reject a self-reported Level that doesn't match. Today the model's Level feeds budgets, level-gated removal and gauge credit unchecked. | Not built | M | A-26; §F-6 |
| M4.9 | **Lockdown budget in play.** Adventure requests carry no lockdown lines, and nothing counts pieces. Add both, and reconcile with the prompt's "one resource attack" caps. | Bug | S | generation notes |
| M4.10 | **Gate the prompt-only rules**: a channeler at standard and above (§E6-5), and the one-per-encounter caps (resource attack, poisoner, infect, counter, gauge-punisher). | Not built | S | A-39 |
| M4.11 | **Validator blind spots:**<br>• the `defeated_once` branch (C-07)<br>• lines for absent NPCs dropped silently (C-08)<br>• duplicate JSON keys (C-09)<br>• identical reactions across different kits (C-10)<br>• quest themes compared as exact strings<br>• gates looser than their prompts (`enrage_round` 2–6 vs 3–5, depth 10 vs 8, cast 4 vs 3)<br>• enemy `target_rule` and `trigger` strings not validated at load (a typo silently never fires) | Bug | S each | C-07…C-10; generation and arch notes |
| M4.18 | **The enemy prompt's own examples are wrong.**<br>• The "bodyguard" `redirect` turns the blow back on the hero (it needs `new_target: self`), and on `on_ally_hit` it never fires (post-resolution, empty stack).<br>• The `conditional` example uses component-condition vocabulary that the schema rejects. | Bug | S | GDD v2 §5–§11 notes |
| M4.12 | **Standalone encounter generation learns objectives.** | Not built | S | B-01; §D12-7 |
| M4.13 | **Teach the rest of the vocabulary:** `relentless` (priced), composite moving actions (charge then strike; hit-and-fade), and enemy countdown rites (`channel_drop`, `after_turns`). | Partial | S each | B-24, B-25, C-16 |
| M4.14 | **Library scenarios**, once regenerated (M3.5), take the arc through the same reader matrix as Town + New. | Not built | S | generation notes |
| M4.15 | **An LLM naming pass for merchant stock** (shops are voiceless). | Not built | S | B-51; §D17-6.2 |
| M4.16 | **Re-queue an adventure's art after a server restart** (nothing does today). | Not built | S | generation notes |
| M4.17 | **Generated gauntlets** for the tester (freshness check, enemy-schema sample). | Untested | S | B-19 |

## M5 · The world remembers

*Why:* Update 24 made the *writers* remember. At runtime, dialogue still reads positive flags only, and nothing records who you spoke to, what you refused or who fell. So an NPC greets you with the same line on every visit.

| ID | Objective | Status | Size | Sources |
|---|---|---|---|---|
| M5.1 | **Standing flags.** Set `refused_<quest>`, `talked_<npc>`, `fell_<hero>` and `defeated_act_<n>`. Write `town_state.talked`, and unify the two `STANDING_FLAGS` copies. | Not built | S | R4.1.2, C-55 |
| M5.2 | **Negated and once-only gates** (`requires: ["!flag"]`, `once`, a per-conversation seen set). Also the validator's `!` support and an ACT-prompt paragraph ("second greetings differ"). | Not built | S | R4.1.3; §D24-12 |
| M5.3 | **Merge unasked town and act topics into authored trees**, and warn when a tree shadows topics. This is the full fix for M1.2. | Not built | S | R4.1.4 |
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
| M8.8 | **Shipped vs local content.** A gitignored `content_local/` searched first, so play never dirties the tracked tree, plus a "reset shipped content" path. Worldbook appends are the other writer (C-62). | Not built | M | R3.2.6, C-62 |
| M8.9 | **Art out of git's growth path.** WebP on save; delete the 69 orphaned town-art files (`medusel`, `windmill_town`); decide on LFS or a release asset (the tracked PNGs are ≈918 MB, and `.git` is 1.0 GB). | Not built | M–L | R3.2.5 |
| M8.10 | **Deckbuilder "Update Game Character"** keeps draft cards (or a sibling `.draft.json`); loadout errors return 422, not a raw 500. | Not built | S | R3.2.9 |
| M8.11 | **Panel clips travel with a character** (loadout export/import), which matters for the Windows install. | Not built | M | B-28 |
| M8.12 | **A view-only mode for a fallen Hardcore run's saves.** | Partial | S | B-53 |
| M8.13 | **Explicit UTF-8 file I/O.** Several reads and writes omit `encoding="utf-8"` (`content._load_json`, `_read_id_set` and `_write_content`; `scenario_content`'s item write; `ltg_combat.loader` and `scenario.load_scenario`; the Deckbuilder's `api_load`; the autoplay tester's JSON reads). On Windows, Python 3.14 then uses the locale code page (cp1252) against UTF-8 JSON: 17 tracked content files hold non-ASCII text. Found in code, not reproduced on Windows yet; the non-blocking Windows CI job (M0.3) should show it. | Bug | S | found 2026-09-25 |

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

M1.7, M1.12, M1.17, M1.18, M1.22, M1.25, M1.26, M1.27 (a–d), M1.28, M1.30, M1.31, M1.37, M2.21, M3.5, M3.11, M5.11, M6.8, M6.9. Also:
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
- tuning the lockdown budget down;
- MTG/Scryfall import in the Deckbuilder UI;
- quests hooked to hero backstory.

(Sources: §D23 preamble and §D23-8; owner rulings 2026-08-21 → 09-06.)

## Done since the 2026-09-02 review (for the record)

- M0 Foundations (2026-09-25): the test sandbox, CI, pinned dependencies, doc and comment debt; M0.3 awaits its first green run and branch protection.
- M1.1, the Python 3.11+ shuffle crash (2026-09-25).
- Update 23 in full.
- Update 24 in full.
- The `Ref` validator (R3.3.1, partial).
- The "we" voice on the defeat journal line (R4.1.5, partial).
- The per-trigger panel animations.
- The `other_ally` trigger scope.
- The card frames in the hand.
- This documentation consolidation.
