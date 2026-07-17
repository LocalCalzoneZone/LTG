# Langelier Tactical Game (LTG) — Design Update 13: The Autoplay Tester — Probes, Gauntlets, and Verdicts

**Status:** IMPLEMENTED 2026-07-16 (`apps/autoplay-tester/`, `tests/test_autoplay_tester.py`). The four structural decisions (§D13-7) were made by the designer 2026-07-16. Two amendments landed during implementation and are canonical: the **pressure ladder** (§D13-1.1a) replaced flat paired seeds as the probe instrument, and **`greedy-1.1.0` + the NOT-EXERCISED guard** (§D13-1.1b) replaced the launch measuring stick after it proved to play only 2 of 20 cards of a real deck. T-74/T-76 are calibrated to both (§D13-5).

**Purpose.** One new app: the **Autoplay Tester** — a standalone playtest-lab UI over the §D12-3 harness that turns "is this card/skill/character/enemy fair?" into a measured verdict with a recommended lever. It owns three ideas:

1. **Probes** (§D13-1) — automated A/B analyses of one card, one Skill/Ultimate, or one whole character, producing balance recommendations from paired-seed runs.
2. **Gauntlets** (§D13-2) — versioned encounter sets to test against: a frozen baseline gauntlet, plus LLM-generated gauntlets minted on demand.
3. **Verdicts** (§D13-3) — the recommendation layer: per-card levers (cost / timing / magnitude) on the player side, and proposed Rebalance-Register/price-table deltas on the enemy side.

**Explicit non-goals:** the Tester never edits content itself. Player characters change only through the Deckbuilder's existing edit flow (the Tester deep-links into it); enemy-side recommendations are advisory text (a proposed register delta / prompt patch), applied by a human. The harness policies stay untouched — the Tester is a consumer of the measuring stick, never a modifier of it.

---

## D13-0. Placement, naming, dependencies

- **App:** `apps/autoplay-tester/` — package `ltg_autoplay_tester`, console script **`ltg-autoplay-tester`**, default port **8030** (cockpit 8011 · deckbuilder 8012 · game 8020/8021). Launcher: **`LTG-Autoplay-Tester.command`** at the repo root, same shape as the existing launchers (venv bootstrap, then `exec ./.venv/bin/ltg-autoplay-tester`).
- **UI:** served by the same process (a static frontend like the Deckbuilder's, or a small Vite build like game-ui — implementation's choice), on the **Brasswork & Ink** design system: Optima, brass hairlines, no emoji. The Tester is a *lab*, so its accent register may lean instrument-panel (tables, bands, flags) — but it is the same house.
- **Dependencies:** `ltg_core` + `ltg_combat` (the harness), **plus `ltg_game_server` as a library** for two things it must not duplicate: the content registry (`content.py` — the discovery/validation gate over loadouts, encounters, adventures) and the LLM client + encounter prompt (`llm.py`). This adds the dependency edge *tester → game-server* (**decided 2026-07-16**); the existing "apps never depend on each other" rule was written for deckbuilder↔combat and stays true there. Direction of the edge matters: the game server never imports the Tester.
- **Data:** everything the Tester produces lives under `apps/autoplay-tester/data/`:
  - `runs/<job-id>/` — the raw JSONL per variant + a `manifest.json` (subject, gauntlet hash, policy version, matrix, timestamps);
  - `gauntlets/` — gauntlet manifests and generated encounter JSONs (quarantined: NOT in the game's scan dirs, so the New Game picker never sees test content — §D13-2.3);
  - `verdicts/` — the rendered recommendation reports (kept, so history is reviewable).

---

## D13-1. Probes — the automated analyses

A **probe** is one question about one subject, answered by paired runs over a gauntlet. All probes share the same statistical spine:

### D13-1.1 The paired-ablation spine

- Every comparison is **A/B on identical seeds**: variant A and variant B play the same seed list, so each pair shares its shuffle and initiative. Paired design removes most run-to-run variance — card-sized effects (a few win-rate points) resolve at hundreds of seeds instead of thousands.
- The measuring stick is the harness greedy policy (**`greedy-1.1.0`** — see §D13-1.1b), `balanced` spend, seeds `0..N-1`. Every verdict records the full context (gauntlet hash, policy version, matrix) and is comparable only within it.
- **Presets:** `quick` is the bench **default** (decided 2026-07-16) — a ~1-minute while-you-wait read; `thorough` is one click away, adds the full leave-one-out deck sweep, and is the bar for a verdict you'd act on. A quick verdict renders with a "screening only" sub-band so the two are never confused. The UI shows the estimated run count and time before launch.

### D13-1.1a The pressure ladder *(implementation amendment, canonical)*

Playtest of the probe spine surfaced a property flat seed-sampling cannot handle: with a deterministic engine and fixed policies, a given (fixture × size × difficulty) cell sits hard against 0% or 100% — shuffle order barely moves outcomes, so paired deltas read zero everywhere. The instrument that works is the **pressure ladder**: every cell runs at each enemy HP+Power multiplier in **0.5–1.6, step 0.1** (T-77), and a probe measures each fight's **breaking point** — the rung where victory tips to defeat — rather than a win rate at one point. A card's marginal contribution is then a threshold shift ("how much harder a fight can this card win"), which registers at 0.1-multiplier resolution. Seeds stay deliberately few (the variance lives across rungs, not shuffles): `quick` = 8 seeds × 12 rungs, `thorough` = 24 seeds × 12 rungs + the deck sweep. ×1.0 is the game as shipped; the other rungs are instruments, not content.
- **The combo-blindness tag.** greedy never sequences amplify→spike lines (§D12-7). Any subject whose effects include `amplify`, `double_next`, `copy_spell`, or `stance` is stamped **COMBO-BLIND** in its verdict: the harness can convict such a card of being overpowered (if it wins games even under a policy that plays it badly, it is), but can never acquit it of being weak. The report says so in those words.

### D13-1.1b `greedy-1.1.0` and the honest-verdict guard *(implementation amendment, canonical)*

Measured against a real deck, the §D12-3.3 launch ladder (`greedy-1.0.0`) cast **2 of 20 cards** across 256 games — constant-damage spells and reactive saves were its whole vocabulary, so per-cell outcomes were fully deterministic and a card probe on anything else measured the filler swap, not the card. Two corrections, made while zero baseline archives existed (the version bump was free):

- **`greedy-1.1.0` supersedes the launch ladder** and is vocabulary-complete while staying fixed, scripted, and deterministic: it compares the multi-cast damage line against the basic attack instead of always preferring casts, primes an attack turn with instant self-pumps, uses the Skill (damage at kill-order; utility on round 2), starts channels early (round ≤ 3), treats destroy/bounce as removal for finishing and channel-breaking, answers windows with kill-the-attacker (first strike) and counterspells against big actions or channel starts, and sinks leftover mana in a fixed utility order (heal-the-wounded → wound → poison → draw → scry → permanent counters → regen). Under it the reference deck plays 13 of 20 cards and per-cell seed variance is real. It remains deliberately blunt: no amplify/double_next sequencing, no interception, no lookahead.
- **The NOT-EXERCISED guard:** a card/heroic probe whose subject was cast in **zero** as-is games verdicts `NOT EXERCISED` — never IN_BAND. No measurement without exercise; the flag names the policy vocabulary as the gap.

Recalibrating the policy is a **stick move**: every T-74 band recalibrates with it, and verdicts from different policy versions never compare (the reader stamps and refuses silently-mixed diffs).

### D13-1.2 The card probe

*Question: what does this one card contribute, and if too much, which lever fixes it?*

1. **Ablation:** deck-as-is vs. the same deck with the card replaced by the **filler card** — "Practice Swing," `{1}` sorcery, deal 2 to a chosen enemy, level 1 common (colourless cost so it is castable in any identity; T-73). The paired win-rate delta is the card's **marginal contribution**.
2. **Context:** the same ablation for every other card in the deck (the full leave-one-out sweep is the default — 20 cards ≈ 21 variants — because a card is only an outlier *relative to its deck's distribution*).
3. **Flags:** a card is **OVER** when its marginal contribution exceeds the pool by the T-74 band (default: > +6 pp and ≥ 2 SD above the deck mean); **UNDER** below −4 pp (combo-blind tag applies).
4. **The lever ladder** (runs only for OVER cards): re-run the paired matrix for each generated variant, in order —
   `+1 generic` → `+2 generic` → `instant → sorcery` (if instant) → `amount −1` (largest constant magnitude).
   The **recommendation is the smallest lever whose variant re-enters the band**, reported with numbers: *"Fireblast at `{R}`: +9 pp over filler. At `{1}{R}`: +3 pp — in band. Recommend +1 generic."* The instant→sorcery rung isolates the price of reactivity: if the sorcery twin is in band and the instant is not, the fix is the timing, not the number.
5. **Free screening metrics** (no variants needed, read from the base run's logs): times drawn / cast / dead-in-hand, damage per cast, and the **cast-vs-held split** (win rate in games where the card was cast vs. drawn-but-never-cast). Confounded but cheap — the Tester uses it to rank the deck and suggest which cards deserve the expensive probe.

### D13-1.3 The heroic probe (Skill / Ultimate)

Same spine, different variants:

- **Skill:** loadout-as-is vs. loadout with the Skill removed (the slot is optional in the schema). Marginal contribution + the lever ladder where applicable (Skills carry real mana costs; timing is already fixed by Update 11's ruling).
- **Ultimate:** as-is vs. removed, **plus the gauge instruments** the harness already records: `ultimate_round`, `gauge_full_round`, and the share of wins in which the ultimate was cast. An Ultimate is flagged when the with/without delta exceeds the T-74 band *or* when >T-75 (default 60%) of wins route through casting it — a build that only wins through its limit break is a balance smell even if the aggregate win rate looks fair. Levers for ultimates are magnitude-side only (there is no cost to raise; the gauge is the cost), so the report recommends `amount −N` or an effect-count trim.

### D13-1.4 The character probe

*Question: is this whole character above or below the roster's curve?*

- **Roster percentile:** the character solo and paired with a fixed reference partner, over the gauntlet, vs. every other loadout the registry can see under identical cells. The verdict places the character's win rate in the roster distribution and flags outliers by the same band logic.
- **Attribution:** damage share, healing share, mana wasted, cards dead-in-hand — the "where does the win come from" table, plus the top-3 card probe screening so the report says *which part* of the kit carries them.
- **Points-buy audit:** the spend-plan matrix (already in the harness) run on this character — `greedy-hp` vs `greedy-power` vs `greedy-mana` vs `balanced` across acts. If one plan dominates across the board the *price table* is implicated, not the character; the report then recommends a §P-2 register delta (e.g. "Power at 10/pt underpriced for this chassis — winrate/point slope +2.1 pp vs +0.4 pp for HP") rather than a character nerf.

---

## D13-2. Gauntlets — what probes run against

A **gauntlet** is a named, ordered set of encounters with a manifest: `{name, encounter files, party sizes, difficulties, created, content_hash}`. Verdicts are stamped with the gauntlet hash; two verdicts compare only when hashes match (the content is part of the measuring stick).

### D13-2.1 The baseline gauntlet

A frozen, **purpose-built** fixture set (decided 2026-07-16 over curating the bundled examples — coverage control is worth the authoring), versioned in-repo at `apps/autoplay-tester/data/gauntlets/baseline-1/`. Eight fixtures, one per mechanical axis, each with layouts "1"–"4":

| # | fixture | exercises |
|---|---|---|
| 1 | the bodies fight | plain chassis pressure; the attack/defend baseline |
| 2 | the healer knot | lowest_hp_ally support + a medic-punisher — kill-priority |
| 3 | the ritual | a channel the party must break; ward bodyguard |
| 4 | the control pack | stun/taunt action-economy attack |
| 5 | the swarm | token creators at cap; AoE value |
| 6 | the boss | phases, enrage, the execute window |
| 7 | the hold (survive) | a 5-round timer with scheduled reinforcements |
| 8 | the clock (race) | a marked ritualist, escalate on failure |

Fixtures are hand-authored to the standard budget at each size, validated through the normal content gate, and **never edited in place** — the baseline changes only by minting `baseline-2` (verdicts stamp the gauntlet hash, so history stays readable).

### D13-2.2 Generated gauntlets

One click calls the existing generator (`llm.generate_encounter` / `generate_adventure` with the party scoped to the probe subject) N times, with the standard repair loop and the engine gate. Purpose:

- **Freshness:** verdicts that hold on both the frozen baseline *and* a fresh generated set are robust; a card that is only strong against the baseline is overfit to it.
- **Enemy-schema testing (§D13-3.2):** a large generated sample is the only honest way to evaluate the *generation rules* themselves — archetype prices, chassis rows, budgets.

### D13-2.3 Quarantine

Generated test content persists **only** under the Tester's `data/gauntlets/` and never enters the game's scan directories — the New Game picker stays clean. A **"promote to game"** action copies a keeper through `content.save_encounter` (the normal gate) when a generated set turns out to be good content in its own right.

### D13-2.4 Enemy-side variation

The same lever machinery points the other way: a gauntlet can be re-run with mechanical enemy variants — `--raw-power` (the T-64 retro diff, already shipped), HP ±20%, a named component's cooldown +1, an archetype magnitude −1 — generated as patched copies of the encounter JSONs. This is how a specific enemy design gets its own probe.

---

## D13-3. Verdicts — the recommendation layer

### D13-3.1 Player-side (cards / heroics / characters)

A verdict is a report, never a write: subject, matrix context, marginal contribution with confidence interval, the flag (OVER / UNDER / IN BAND / COMBO-BLIND), the lever ladder results, and one recommended change in plain words. Next to it, one button: **"Edit in Deckbuilder"** — opens `http://localhost:<deckbuilder>/?edit=<character id>` (the existing edit flow; its save posts through `/api/loadout/update-game`). When the Tester regains focus it re-reads the registry and offers **"re-run probe on the updated build"** — the before/after diff of the human's actual change closes the loop.

### D13-3.2 Enemy-side (the generation schema)

Over a generated gauntlet's results, the Tester attributes outcomes to the *generation vocabulary*, not to individual enemies:

- Per **component archetype** (Punish, Fortify, Ward, Drain, Counter, Swarm, …), per **pattern** (channel, windup, gauge-punisher, necromancy), and per **chassis**: presence-weighted deltas on win rate and mean rounds across cells. A big sample of generated encounters gives each archetype hundreds of appearances — enough to read.
- Flags map to the **existing levers**: the archetype base costs and multipliers, the chassis table, the verb magnitude schedule (L+1 …), B(L), and the T-values (T-55, T-66/67/68 …). Example verdict: *"Encounters fielding a Drain component run +1.8 mean rounds and −11 pp party win rate vs. the pool at equal budget — Drain is underpriced at base 5; recommend 6, or Drain magnitude ceil(L/2) instead of ceil(L/2)+1."*
- Output is a **proposed Rebalance Register delta** plus, where the fix lives in the prompt, a ready-to-paste patch of the relevant `DEFAULT_INSTRUCTIONS` lines. **Report-only (decided 2026-07-16):** a human applies it through Options → LLM — silent drift of the generation rules would corrupt every archived baseline, so the Tester never writes them.

### D13-3.3 What a verdict must always carry

Gauntlet hash · policy version · seeds/preset · the combo-blind tag where applicable · the §D12-7 footer. A verdict whose context no longer matches the current build (policy version bumped, gauntlet re-minted) renders with a **STALE** band across it.

---

## D13-4. The app itself

### D13-4.1 Server

FastAPI on 8030. A **job queue** (probes are minutes-long): jobs run in a background process pool, persist their manifests/results to `data/runs/` incrementally, and survive a restart (the UI re-attaches to finished/failed jobs; a half-run job is marked interrupted and re-runnable — determinism makes re-running free of surprises). Endpoints, roughly:

| area | endpoints |
|---|---|
| roster | `GET /api/roster` (all loadouts via the content registry, with per-character probe history) |
| gauntlets | `GET/POST /api/gauntlets` · `POST /api/gauntlets/generate` (LLM, N encounters, note) · `POST /api/gauntlets/{id}/promote` |
| probes | `POST /api/probes` (subject, kind, gauntlet, preset) · `GET /api/probes/{job}` (progress) · `DELETE` (cancel) |
| verdicts | `GET /api/verdicts` · `GET /api/verdicts/{id}` (full report incl. lever ladder + raw cell tables) |
| handoff | `GET /api/deckbuilder-url/{character_id}` (resolves the deckbuilder port; the UI opens it) |

### D13-4.2 UI — four views

1. **Roster** — every loadout the registry sees: name, colours, level, last verdict chip (IN BAND / OVER / UNDER / COMBO-BLIND / STALE / never probed). Actions per row: *Probe character* · *Probe a card…* (card picker with the free screening metrics inline) · *Probe Skill/Ultimate* · *Edit in Deckbuilder*.
2. **Test Bench** — compose a probe: subject → gauntlet (baseline / generated / mint-new-now) → preset → estimated games & minutes → launch. A second tab composes enemy-side runs (gauntlet × enemy variant levers).
3. **Queue** — running/finished jobs with live progress (games done / total, current cell), cancel, and re-run.
4. **Verdicts** — the report reader: the flag and recommendation up top in one sentence; below, the lever ladder table, the per-cell report (the §D12-3.5 aggregate rendering, reused), the paired-delta chart, and the context stamp. Enemy-schema verdicts render the proposed register delta + prompt patch in a copy block.

### D13-4.3 Launcher

`LTG-Autoplay-Tester.command` — byte-for-byte the house pattern: `cd` to repo root, bootstrap `.venv` from `requirements.txt` on first run, `exec ./.venv/bin/ltg-autoplay-tester` (which builds/serves its frontend and opens the browser).

---

## D13-5. Rebalance Register deltas *(proposed)*

| ID | value | sets |
|---|---|---|
| T-73 | `{1}` sorcery, deal 2, level 1 | the filler card the ablation spine substitutes |
| T-74 | OVER > +4 pp and ≥ 2 SD; UNDER < −6 pp | probe flag bands, calibrated to the pressure ladder UNDER `greedy-1.1.0` (empirically: a reference deck reads −1.1 ± 2.3 pp — utility instants sit below the filler because vanilla damage is genuinely playable — while a deliberately broken card reads +8.6 pp, 4.2 SD out). Recalibrate on every policy version bump |
| T-75 | 60% | ultimate dependence flag: share of wins routed through the ultimate |
| T-76 | quick = 8 seeds × ladder / thorough = 24 × ladder + LOO sweep | probe presets |
| T-77 | ×0.5–×1.6, step 0.1 (enemy HP + Power) | the pressure ladder (§D13-1.1a) |

---

## D13-6. Glossary deltas

- **Probe** — one automated A/B analysis of one subject (card / heroic / character / enemy variant) over a gauntlet, on paired seeds.
- **Gauntlet** — a named, hashed encounter set probes run against; baseline gauntlets are frozen, generated gauntlets are minted by the LLM and quarantined from the game.
- **Verdict** — a probe's report: flag, marginal contribution, lever ladder, and one recommended change. Advisory, always.
- **Filler card** — the neutral `{1}` sorcery (T-73) swapped in for ablation.
- **Lever ladder** — the ordered variant sweep (cost +1/+2 → instant→sorcery → magnitude −1) whose first in-band rung becomes the recommendation.
- **Combo-blind** — the stamp on any verdict about amplify/double_next/copy_spell/stance subjects: the greedy stick can convict them, never acquit them.

---

## D13-7. Decisions and open questions

**Decided (designer, 2026-07-16):**

| decision | call |
|---|---|
| Dependency edge | The Tester imports `ltg_game_server` (content registry + LLM client/prompt); the edge is one-way, tester → game-server |
| Enemy-schema authority | Report-only — proposed register deltas + prompt patches, applied by hand through Options → LLM |
| Bench default | `quick` preset default (screening band); `thorough` opt-in and required for act-on-able verdicts |
| Baseline gauntlet | Purpose-built frozen fixture set (the eight-fixture table, §D13-2.1), not curated examples |
| Quarantine (by design intent) | Generated test gauntlets never enter the game's scan dirs; keepers are promoted explicitly |

**Still open:**

- **[OPEN] The reference partner.** The character probe's party-of-2 cell needs a fixed reference partner for comparability. A frozen "sparring partner" loadout shipped with the baseline gauntlet is the likely answer; pick it when the fixtures are authored.
- **[OPEN] Frontend stack.** Static single-file frontend (Deckbuilder-style) vs. a small Vite/React build (game-ui-style). Implementation's choice; the design constrains only the theme.
- **[OPEN] Pair-ablation pass.** Leave-one-out misses two-card synergies. A second-pass pair ablation over flagged cards is sketched but deferred until single-card probes have playtest hours.
