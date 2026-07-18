# Langelier Tactical Game (LTG) — Design Update 12: Roadmap Tier One — Objectives, Enemy Insight, and the Balance Harness

**Status:** canonical design, **not yet built**. Where this document and prior documents (GDD, Updates 01–11) disagree, this document wins. Updates 08–10 are implemented; Update 11 exists **in code only** and is formally recorded in §D12-0 below.

**Purpose.** The three mechanical systems of Roadmap Tier One, to be built **in this order** (each leans on the one before):

1. **Alternate objectives** (§D12-1) — a closed set of three encounter objectives (*survive* / *waves* / *race*), with failure shapes, worked into adventures for flavour. The engine's win/loss reading grows three variants; everything else is content and UI.
2. **Enemy insight** (§D12-2) — the enemy AI learns to read the Update 08/11 state it currently ignores: primed combos, the ultimate gauge, and the hero ultimate on the stack.
3. **The autoplay balance harness** (§D12-3) — a headless, deterministic autoplayer that turns every Rebalance Register number into a measured one. Built last so it can play objectives and face insight-driven enemies from day one.

**Explicit non-goals for this update:** gear/items (Roadmap Tier 3, deferred behind Scenario by decision 2026-07-14), Scenario mode, the narrator, voice/music, exploration. Objectives must not grow hooks for any of these beyond what is specified here.

**All magnitudes are playtest starting values**, collected in the Rebalance Register deltas (§D12-5).

---

## D12-0. Errata: Balance Update 11, recorded

Update 11 landed code-first (see `tests/test_balance_update_11.py`); no design document describes it. Its deltas are canonical and recorded here, Update 07-style:

| # | topic | documents say | code does |
|---|---|---|---|
| 1 | Skill timing | instant speed, free, reactive (D8-3.1) | **an activated ability at active speed: consumes the proactive action; sorcery-timed one-shot _or_ channeled (skill-stances); never instant; vigilance lets it share a turn with Attack/Cast; legacy instant skills coerce to sorcery** |
| 2 | `prevent` parameter | free text | **closed vocabulary: `combat_damage` (attacks + activated abilities) · `spell_damage` (spells + triggered) · `all_damage` · `attack`; legacy spellings normalise** |
| 3 | combo suite | absent | **`amplify` (prime next outgoing damage/heal, ×N + M, one-shot, holds until spent), `copy_spell` (copier re-aims the copy; enemy reactive form mirrors the spell back at its caster; never channels), `double_next` (next spell/ability/action resolves twice), `caster_last_damage` / `target_last_damage` value refs. All enemy-legal; taught to the generation prompt.** |
| 4 | enemy Power | chassis table values | **+2 all enemies, +4 bosses, applied in the content layer (`content._bump_enemy_power`), intents included** |

New register entries: **T-64** = enemy Power bump (+2 minion / +4 boss). Items 1–3 are mechanisms, not magnitudes. Update 08 §D8-3.1/3.5 and §D8-4.1 (the Skill as a reactive option in auto-pass) should be read through this table.

---

## D12-1. Alternate objectives

### D12-1.1 The objective object

An encounter (and therefore an act) may carry **at most one** optional `objective`. No objective = the standard game, byte-identical to today — the scripted §A/§C scenarios carry none and must replay unchanged.

```
objective = {
  kind: "survive" | "waves" | "race",
  …kind-specific fields (below)
}
```

Standing rules, all kinds:

- **Objectives are fully public.** They are the mission, not an intent — no veiling, ever. The UI shows the objective and its countdown from turn 1 (§D12-1.5).
- **Adventures:** objectives may appear on **Acts I and II only**; **Act III is always the standard boss kill** (the climax stays a fight). At most **one** objective per adventure. Adventure-level validation enforces all three; standalone hand-authored encounters may carry any objective.
- **Defeat by wipe is unchanged** — a fully incapacitated party always loses, objective or not.
- **Timers count rounds** and tick at the **completion of each End Step**. All objective state (rounds elapsed, wave index, marked target) lives in `GameState` and is engine-owned — deterministic, serialized, time-travellable.

### D12-1.2 `survive` — hold out

```
{ kind: "survive", turns: N,
  reinforcements?: [ { turn: k, layouts: {"1": […], …} }, … ] }
```

- **Victory:** at the completion of round N's End Step, the party wins the act — surviving enemies withdraw (a log/flavour event; no kill credit, no death triggers). Killing everything early also wins, as always.
- **Reinforcements** (optional, recommended — survival must not be passive): each entry deploys at the **start of the Enemy Intents step** of round *k*, on the entering enemies' home rows, declaring intents that same step. Entries use the standard per-party-size layout map; ids reference the encounter pool; repeats clone.
- Undeployed reinforcements sit in the **reserve zone**: off the battlefield, untargetable, and — unlike waves below — they do **not** block the timer victory (the party wins at round N even with reinforcements still unarrived; withdrawal covers them).
- **No failure shape:** failing to survive *is* the wipe.
- Generated timer range: **4–6 rounds** (T-65).

### D12-1.3 `waves` — clear them all

```
{ kind: "waves", waves: [ {"1": […], "2": […], "3": […], "4": […]}, … ] }
```

- The encounter's top-level `layouts` field **is wave 1**; `objective.waves` lists the later waves, each its own per-size layout map. (Back-compatible: readers that ignore objectives still build wave 1.)
- Later waves wait in the **reserve zone**: off the battlefield, untargetable, **not defeated** — victory reads zones as always, so reserves block the win by construction. This is the bounce/"in hand" pattern, reused.
- **Deployment:** when every enemy of the current wave is defeated, the next wave deploys at the **start of the next round's Enemy Intents step** — the party always gets the End Step and an Upkeep breather between waves. Deploy on home rows, fresh intents same step.
- **Victory:** all waves defeated (the standard zone read — no special case).
- **Bodies and budget:** each wave fields at least **1× party size** bodies, total across waves at least the standing 2× (T-66); the summed Level budget may run to **1.5× the act's standard budget** — staggered arrival pays for the excess (T-67). A mini-boss, if any, appears in the **final** wave (validation).
- **No failure shape:** waves are a pacing structure, not a clock.

### D12-1.4 `race` — the doom clock

```
{ kind: "race", target: "<enemy pool id>", turns: N,
  fail: "defeat" | "escalate",
  escalation?: { telegraph, verbs: […] } }    # required iff fail == "escalate"
```

The DPS check. One enemy in the pool is the **marked target** (the ritualist, the summoner); the party must **defeat it — graveyard or exile — before the clock runs out**.

- **The clock is an objective, not an intent.** It ticks at each End Step regardless of anything done *to* the marked enemy short of defeating it: stun does not pause it, strip does not touch it, bounce does not (the enemy is alive, in hand), `control` does not (controlled is not defeated — and a controlled marked enemy snapping back at the fail moment is working as designed). **Kill it or exile it. Nothing else counts.**
- **Objective complete:** the marked enemy is defeated before the End Step of round N finishes. The clock vanishes; the act continues to standard victory (mop up).
- **Objective failed** (clock expires, marked enemy undefeated):
  - `fail: "defeat"` — the act is lost on the spot. Use sparingly; in an adventure this ends the run.
  - `fail: "escalate"` — the **escalation payload** fires: an enrage-shaped, multi-verb eruption (2–3 verbs — counters on the enemy side, an AoE, a token wave, a granted keyword) executed **on the stack**, sourced from the marked enemy, answerable like an enrage (mitigating it is fair play; its arrival is not preventable). The fight then continues under standard victory. The payload is budget-free, like an enrage (T-68). If the marked enemy is somehow already gone from play but undefeated (bounced/controlled) at expiry, it returns/reverts first, then the payload fires.
- The marked enemy carries a visible **doom-clock badge**; killing it is kill-priority made diegetic. Generated clock range: **3–5 rounds** (T-68). Generation guidance: prefer `escalate` — `defeat` is for hand-authored set pieces.
- Design note: the clock is deliberately **not** implemented as charge counters — charge is an enemy component with its own reset/counter rules; the objective clock is engine state. The two may coexist on one enemy (a gathering ritualist under a doom clock is a fine act).

### D12-1.5 UI

- **The objective banner:** the pinned **first line of the intents window** — "Survive: 3 rounds remain" · "Wave 2 of 3" · "The rite completes in 2 rounds — slay the Bonechanter." Updated each End Step; present from turn 1.
- The **marked enemy** renders its doom-clock badge (count in brass; the frame-state precedence of the design system is unchanged).
- **Reserve-zone enemies do not render** on the battlefield (like bounced enemies); the banner carries the wave count instead.
- Victory/defeat splashes state the objective outcome ("The rite completes…" / "You held the line"). In adventures, the act's `narration` should reference the objective — generation guidance, not validation.

### D12-1.6 Generation (`llm.py`)

The adventure prompt gains an **objectives block**: the three kinds with their JSON shapes, the standing rules (one per adventure, Acts I–II only, never Act III), the T-65/T-67/T-68 ranges and budget allowances, and per-kind guidance — *survive* wants scheduled reinforcements and a defensible theme; *waves* wants a war-band theme with distinct wave compositions (vary roles, don't clone one statline thrice); *race* wants a ritualist/summoner marked target with real HP, a Ward bodyguard, and an escalation that transforms the fight. Standalone encounter generation is unchanged (objectives are adventure flavour; the encounter prompt does not learn them in this update).

---

## D12-2. Enemy insight

The AI's valuation and component vocabulary catch up with Updates 08–11. All extensions are deterministic and priced through the existing budget machinery.

### D12-2.1 Valuation: the primed-threat rank

The default-attack valuation (Update 06) currently ranks: finishable → channel-breakable → role value → lowest HP. Insert a new rank between channel-breakable and role value:

> **2.5 Primed threat** — heroes carrying a live `amplify` tag or `double_next` tag, or whose ultimate gauge is ≥ **80** (T-69). Score = 2 for a primed tag + 1 for the gauge threshold; rank by score descending, ties falling through to the existing order.

The archer that snipes the war-cried duelist before the doubled swing lands, without being scripted to. Note what needs **no work**: stance-holders are channel-holders, so the existing channel-breakable rank already hunts them.

### D12-2.2 New component vocabulary

- **Condition** `hero_gauge_pct {op, value}` — gates a component on any hero's gauge (arm the gauge-punisher only when it matters).
- **Condition** `hero_primed {op: ">=", value: 1}` — gates on the count of heroes holding amplify/double_next tags.
- **Target rule** `primed_hero` — the hero with the highest primed-threat score (§D12-2.1 scoring), falling back to `valuation` when nobody is primed (so a rule using it never whiffs into an empty target).
- **Trigger** `on_ultimate_cast` — a hero's Ultimate is on the stack. The dread window.

### D12-2.3 The ultimate-answer guardrail

`on_ultimate_cast` components may **punish** (damage, wound, stun the caster — the tyrant makes you pay for your moment) freely, priced as normal reactives. A **counter verb on this trigger is boss-only and once-per-encounter** (T-70) — cancelling a once-per-fight, gauge-priced ultimate is the single most feel-bad answer in the game, so it is reserved for one dramatic "Tyrant's Contempt" per boss, ever, and the party can still respond to the counter itself on the stack. Validation enforces both constraints; the prompt teaches them.

### D12-2.4 Generation (`llm.py`)

The component vocabulary block gains the two conditions, the target rule, and the trigger, plus one blessed pattern: the **GAUGE-PUNISHER** (reactive Debilitate/Punish, condition `hero_gauge_pct >= 80` or trigger `on_ultimate_cast`, target `primed_hero` / `trigger_source`) — at most one per encounter; it exists to make charging an ultimate a decision, not to lock it out.

---

## D12-3. The autoplay balance harness

### D12-3.1 What it is, and is not

A **headless, deterministic autoplayer** over the engine's public contract — `legal_actions(state)` / `apply_action(state, action)` — that plays thousands of complete fights and adventures and reports metrics. It is **not a learned AI and not an opponent**: policies are fixed, versioned, scripted heuristics, because they are the measuring stick — a balance change's effect is only readable if the stick doesn't move. Absolute win rates will read low (a greedy bot underplays combos, stances, and interception); **the harness's product is deltas** — between builds, encounters, difficulties, and balance patches. No LLM anywhere in the loop.

### D12-3.2 Placement and naming

Module `ltg_combat.autoplay`, console script **`ltg-autoplay`** — *not* an extension of `ltg-combat harness`, which is the existing §A/§C scripted-proof command and keeps its name and behaviour untouched. Depends only on `ltg_combat` + `ltg_core` (it composes fights via the same `compose_spec`/`state_from_dict` path the servers use). Adventure runs replicate the game server's carry-over/level-up rules (§D10-2/3) inside the runner — the session layer is not imported.

### D12-3.3 Policies

The policy interface: `choose(state, legal_actions, rng) -> action`, plus `spend_level_up(build, points) -> build` for adventure runs. Every policy is deterministic given its seed and carries a **version string** embedded in every report row.

- **`random`** — uniform over legal actions (seeded). The floor: an encounter random wins 40% of on hard is broken. Also the fuzz driver (§D12-3.6).
- **`greedy`** — a fixed-priority heuristic, evaluated in order: (1) win now (lethal on the last enemy / complete the race target); (2) answer incoming lethal (Mitigate / prevent / heal the doomed); (3) cast the Ultimate when full and a rank-1 valuation target exists; (4) finish finishable enemies, race-marked target first, then the enemy side's own kill-priority mirror (healers, escalators, channelers); (5) break breakable enemy channels; (6) objective duty (survive → Defend/reposition bias; waves → mana discipline between waves); (7) spend remaining mana on damage-efficient casts (damage per mana, then card economy); (8) attack; (9) Defend. Level-up spend plans: **`balanced`**, **`greedy-hp`**, **`greedy-power`**, **`greedy-mana`** — a matrix dimension, not a smart optimiser.

Two policies and four spend plans are the whole launch surface. Resist adding cleverness — cleverness moves the measuring stick.

### D12-3.4 The runner and determinism

`run_one(spec, policy, seed) -> RunRecord`, with the invariant that identical `(spec, policy version, seed)` yields an identical record — asserted by a test that runs the same fight twice. Batches fan out across processes; a **round cap of 50** (T-71) flags non-terminating fights as anomalies rather than hanging. Every record carries the full repro key `(spec hash, policy version, seed)` — because the engine is deterministic, **the repro *is* the key**: any crash or anomaly replays exactly from those three values.

Per-run metrics: result and end round; per-character damage dealt/taken/healed, cards cast vs. dead-in-hand, mana spent vs. wasted (unspent at End Step), gauge fill rate and ultimate round, channels held/broken (suffered and inflicted); objective margin (rounds to spare, or short); per-enemy survival rounds; for adventures, per-act snapshots of all of the above plus entering HP and spend-plan state.

### D12-3.5 Reports and the diff

```
ltg-autoplay run  --parties … --content … --difficulties standard,hard
                  --sizes 1-4 --seeds 200 --policy greedy --out runs/base.jsonl
ltg-autoplay report runs/base.jsonl          # aggregate tables + outlier flags
ltg-autoplay diff   runs/base.jsonl runs/after.jsonl
```

Raw output is JSONL (one record per run); `report` aggregates to win rate, mean rounds, and damage-source tables per (party × content × difficulty × size), flagging outliers against thresholds: win rate outside **30–85%** on standard, mean rounds > **12**, any character contributing < **10%** of party damage across a cell (T-72, all three). `diff` is the tool's whole reason to exist: two report files, same matrix, showing per-cell deltas — every future Rebalance Register change lands with a before/after diff, and T-64's Power bump should be its first retroactive customer.

### D12-3.6 Soak mode: the free fuzzer

`ltg-autoplay soak --games 10000 --policy random` runs seeded random-policy games asserting engine invariants after every action: HP within `[0, max]` bounds, mana pools non-negative and ≤ capacity, the stack empty between decision points at rest, `legal_actions` non-empty whenever the game is undecided, `apply_action` never raising, and termination under the round cap. Failures write the repro key and stop-state to a report. This is the overnight bug-finder the scripted scenarios can't be — they cover the happy paths; soak covers the space.

### D12-3.7 CI

A pytest-marked **smoke slice** (`ltg-autoplay` over a 2-cell matrix, ~20 seeds, plus a 200-game soak) runs in the normal suite with generous thresholds — it exists to catch determinism breaks and crashes, not to gate balance. Full matrices are manual, by design.

---

## D12-4. Engine & schema touchpoints (for the implementation pass)

| system | where |
|---|---|
| objective schema | `core/ltg_core/schema.py` — the `objective` object on encounters; adventure validation (one per adventure, Acts I–II only, never Act III; waves: mini-boss in final wave, per-wave body minimums) in `content.save_adventure` |
| objective state & rules | `apps/combat/ltg_combat/state.py` (`GameState.objective`, rounds elapsed, wave index, marked target, reserve zone on `EnemyState`) and `engine.py`: the win/loss check variants, End-Step tick, wave/reinforcement deployment in the Enemy Intents step, race expiry + escalation-payload push |
| reserve zone | `EnemyState` flag beside `in_hand`/`exiled`; excluded from `living_enemies()`; blocks victory for `waves`, not for `survive` reinforcements |
| objective UI | game-ui intents window banner (pinned first line), doom-clock badge on the marked enemy, splash outcome lines; snapshot additions in `snapshot.py` (objectives are public — no seat filtering) |
| valuation & vocabulary | `engine.py` valuation order (primed-threat rank), component condition/trigger/target-rule registries; validation for the T-70 guardrail |
| generation | `llm.py` — objectives block in the adventure prompt; insight vocabulary + GAUGE-PUNISHER pattern in the component block |
| autoplay | new `apps/combat/ltg_combat/autoplay/` (policies, runner, metrics, report, soak) + `ltg-autoplay` console script; adventure carry-over/level-up replicated per §D10-2/3; determinism + smoke tests under `tests/` |

**Regression spine:** encounters and adventures without an `objective` field must behave byte-identically to today; §A/§C scripted scenarios and the Update 10 adventure flow are the gates. The valuation insertion (§D12-2.1) does alter enemy targeting in states where a hero is primed — no scripted scenario creates such a state, but the harness smoke run should be added to CI *before* the valuation change lands, so the change itself ships with a diff.

**Build order for the coding agent:** D12-1 → D12-2 → D12-3, each with its tests green before the next begins. The harness must be able to play objectives (greedy rule 1/4/6) and face insight enemies at launch.

---

## D12-5. Rebalance Register deltas *(amends Update 04 §F-10 and successors)*

| ID | value | sets |
|---|---|---|
| T-64 | +2 minion / +4 boss | the Update 11 enemy Power bump (recorded, §D12-0) |
| T-65 | 4–6 rounds | generated `survive` timer range |
| T-66 | ≥ 1× party size per wave; ≥ 2× total | wave body minimums |
| T-67 | ≤ 1.5× act budget | summed Level budget across waves |
| T-68 | 3–5 rounds; escalation budget-free | generated `race` clock range and payload pricing |
| T-69 | gauge ≥ 80; tag = 2 pts, gauge = 1 pt | primed-threat valuation threshold and scoring |
| T-70 | boss-only, once per encounter | `counter` on the `on_ultimate_cast` trigger |
| T-71 | 50 rounds | autoplay non-termination cap |
| T-72 | 30–85% win · ≤ 12 mean rounds · ≥ 10% damage share | report outlier thresholds |

---

## D12-6. Glossary deltas *(amends GDD §13)*

- **Objective** — an optional, fully public encounter goal from the closed set survive / waves / race; at most one per adventure, Acts I–II only.
- **Reserve zone** — where undeployed wave/reinforcement enemies wait: off the battlefield, untargetable; blocks victory for `waves`, not for `survive`.
- **Marked target** — the enemy a `race` objective demands defeated before its clock expires; wears the doom-clock badge; only graveyard/exile satisfies the clock.
- **Escalation payload** — the enrage-shaped, budget-free, multi-verb eruption a failed `escalate` race fires onto the stack from its marked enemy.
- **Primed threat** — a hero carrying a live amplify/double_next tag or a gauge ≥ T-69; ranked between channel-breakable and role value in enemy valuation.
- **Autoplay / policy** — the headless balance runner and its fixed, versioned decision heuristics (`random`, `greedy`); products are deltas, not absolutes.
- **Soak** — the random-policy invariant-asserting fuzz mode; repro = (spec hash, policy version, seed).

---

## D12-7. Open questions

- **[OPEN] Objectives in standalone encounter generation.** Hand-authored standalone encounters may carry objectives; the *encounter* generation prompt does not learn them in this update. Revisit once adventure objectives have playtest hours.
- **[OPEN] Compound objectives.** `survive` takes reinforcements, but kinds do not compose (no "survive AND protect"). Deliberate; revisit only with the (deferred) protect-the-NPC objective, which needs an ally-NPC entity that does not exist.
- **[OPEN] Greedy policy and combos.** The launch greedy policy does not sequence amplify→spike lines; combo-deck win rates will read artificially low. Acceptable for deltas; note it in every report footer.
- **[OPEN] Engine copy performance.** `apply_action` deep-copies state; if full matrices are slow, optimisation is a separate, measured change — the harness must never trade determinism for speed.
