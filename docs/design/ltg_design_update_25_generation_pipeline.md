# Langelier Tactical Game (LTG) — Design Update 25: The Generation Pipeline

**Status:** APPROVED 2026-09-25 (the four defaults below were confirmed by the owner). **IMPLEMENTED 2026-09-25** on branch `Milestone-M4` (Parts B–D; GDD v2 §9.1, §12, §13.6, §14.5 and the companion docs already carry the rules it changed). The rulings marked **[ruled 2026-09-25]** began as defaults and were confirmed by the owner (see the last section). Part A is folded into GDD v2 and generation.md, and the M4 rows are ticked in roadmap.md.

**Origin.** An adventure is one model call: a ≈23k-token system prompt, up to 64k output tokens and a 15-minute timeout. One bad enemy re-emits all three phases. Nothing is cached, a 429 ends the job, and the quest-accept wait is the longest wait a player sees. Separately, several rules the enemy prompt teaches are enforced by nothing: an enemy's Level, the lockdown budget, the one-per-encounter caps, a channeler at standard. The 2026-09-24 sweeps (A-26, A-39, C-04, C-07…C-11, C-16, C-25, C-57, B-01, B-24, B-25, B-51) list them. This update fixes the pipeline and closes the gates.

**Motto kept:** *infinite nouns, finite verbs.* Nothing here lets a model decide a rule at runtime. Every change is either transport, prompt, or a gate that runs before content is saved.

---

## Part A — Design (canon)

### §D25-1 Transport: retry, timeouts, shape faults, coercion

1. **Transport retry is separate from repair.** A transport fault (connection error, read timeout, HTTP 429, HTTP 5xx, including OpenRouter's 502/503/529) is retried inside `_live_chat` with exponential backoff, up to **3 tries in total** (T-89). A `Retry-After` header is honoured, capped at 30 s. A timeout is retried **once** at most, since a second full wait doubles the delay the player feels. A 401, any other 4xx, a malformed body and `finish_reason: "length"` are not retried: re-sending cannot fix them.
2. **Every call has a timeout that covers its ceiling** (≈75 tokens/s, plus headroom). Encounters: 24,000 tokens in **420 s** (was the 120 s default, T-90). Adventure phases: 32,000 in 480 s. Outlines: 6,000 in 180 s. Scenario writers keep 64,000 in 1,200 s.
3. **A shape fault is a repair turn.** The gates read model output, and malformed shapes (a component that is a string, `enemies` as an object) used to raise `TypeError`, `AttributeError` or `KeyError`. Those escaped the repair loop and ended the job (or became an HTTP 500). Every repair loop now catches them and feeds back "the output had an unexpected shape: …".
4. **Deterministic faults are fixed in code, not re-emitted.** Before the gates run, `_coerce_encounter` repairs what has exactly one right answer, and logs each fix:
   - `supertypes` is renamed to `classes` (the pre-§D21 spelling);
   - unknown types or classes are dropped when a valid one remains; the list is capped at 2;
   - a boss missing `enrage_round` or `neglect` gets the T-88 default; an `enrage_round` outside 3–5 or a `neglect` outside 1–2 is clamped into range (the gate range now equals the prompt's, §D25-10);
   - a ranged enemy placed in `front` moves to `mid` (§D23-3);
   - numeric fields written as strings (`"level": "3"`) become integers;
   - an enemy's Level is raised to its priced minimum (§D25-5).

   What remains a repair turn is anything with more than one right answer: a missing component, a clone kit, a thin narration, a missing channeler.

### §D25-2 Prompt caching

The long, stable system prompts are marked cacheable. `_live_chat` sends the system message as a content block with `cache_control: {"type": "ephemeral"}` for providers that need an explicit breakpoint (Anthropic and Google slugs), and a second breakpoint on the newest user turn so a repair turn re-reads the conversation from cache. OpenAI slugs cache automatically and get no markers. The tape (M3.4) hashes the plain messages, so recordings are unaffected.

What this buys: the three phase calls of an adventure (§D25-3), their repairs, and back-to-back encounter generations share the ≈21k-token prefix. On Anthropic models a cache read costs about a tenth of a fresh input token. The prefix must stay byte-stable to hit, so per-request text (rolls, library lines, party, context) lives only in the user turn. It already does.

### §D25-3 Phased adventures

An adventure is written in four calls instead of one:

| Call | Input | Output | Gate |
|---|---|---|---|
| **Outline** | the adventure's parameters (party, difficulty, per-phase levels, rolls, library lines, scenario context, note) with a short outline system prompt | `name`, `flavor`, `boss` (`name`, `level`, `concept`), `objective_phase` (0–3; 0 = none), and three `phases`, each with `station` (where in the place), `threat` (the phase's faction beat and its rolled signature), `mini_boss` (bool) and `beats` (two or three narration beats) | `_outline_problems`: three phases; the boss's level is an integer ≥ the Phase III party level; `objective_phase` is 0–3; the name and every station are non-empty |
| **Phase I** | the encounter instructions plus `PHASE_EXTENSION` (system); the outline and Phase I's own parameters (user) | one phase: `narration` plus a complete encounter | the full per-phase chain (§D25-4), plus the ladder against the outline: no enemy at or above the outline boss's level, a mini-boss only if the outline allows it, an objective only on `objective_phase` |
| **Phase II** | the same system prompt; the outline, a digest of the phases already written (names, enemy names and kits in one line each), Phase II's parameters | one phase | as Phase I |
| **Phase III** | as Phase II | one phase, with exactly one boss at the outline boss's level | as Phase I, plus the boss rule; an objective here must be a §D23-5 modifier shape |

- **Phase I is playable on its own.** In a run, the adventure job becomes `ready` as soon as Phase I is saved: *Start Adventure* lights up after the outline and one phase, not the whole adventure. Phases II and III are written in the background, in order, while Phase I is played. The job carries `phases_ready` (1–3) and `phases_total` (3). **[ruled 2026-09-25]**
- **The boundary waits, the fight never does.** At a phase boundary the level-up screen opens as today. If every seat confirms before the next phase has landed, the party waits on that screen: "The road ahead is still being written…". The next phase composes the moment it lands, and the phase-boundary save is written then, with its seed, as today — so a boundary save always has its next phase. (A restart during the wait reloads the previous save; the phase it would replay is rarely more than minutes of play, and the adventure itself is never re-rolled.) The UI waits on content, never on a rule.
- **What persists, and when.** Each phase is written to `content/` as it validates: the phase file `<id>__phase<n>.json`, and the wrapper, which carries `phases_total: 3` and `outline` while it is incomplete (a *partial* adventure). The run's content store receives the partial detail each time a phase lands, and the job's `adventure_ref` follows it. A partial adventure never appears in the New Game picker. When Phase III lands, the full §D10-4.1 adventure check runs over all three and the wrapper drops `outline` and `phases_total`. It passes by construction, because each phase was checked against the outline.
- **Reloads never re-roll.** A save made during Phase I points at the partial detail it saw. On load, the job's newer detail is taken when it extends the save's (same adventure id, same Phase I). The missing phases resume generating from the stored outline. A phase that exists is never written again.
- **Failure.** A phase that fails after its repairs marks the job `failed` with `phases_ready` intact. *Retry* resumes at the missing phase with the same outline; it does not start over. A party already in the adventure waits at the boundary with the error and a *Retry* button.
- **Outside a run** (New Game or Options → Adventures), the same four calls run back to back and the result is saved whole, as today.

**Why an outline rather than Phase I first.** Phase III's boss sets the adventure's level ladder (§D10-4.1: nothing may reach the boss's level), and the faction and place must hold across all three. The outline fixes both before any phase is written, so each phase can be checked alone and nothing later can invalidate an earlier phase.

### §D25-4 Per-phase repair

Each phase has its own repair loop (2 repair turns; 3 attempts in all). A failure re-prompts **that phase only**, never a phase that already passed. The generation gates (`_layout_problems` — layouts, bodies, variety, row placement — the scene and description checks, and every `_*_problems` gate) collect every problem before answering, in one message that names the phase and lists them one per line. The content save gate still stops at its first problem, but it runs only once all of those pass.

### §D25-5 Enemy pricing

`price_enemy(enemy) → {cost, level, lines}` prices an enemy from the §9.1–§9.2 tables (§F-6):

- **Body:** HP + 3 × Power, + 2 if `attack_mode` is ranged. The chassis are presets of this rule; Husk 2/1 costs 5.
- **Keywords:** the §9.1 prices (reach 1, trample 2, flying 4, lifelink 3, infect 3, deathtouch 4, protection 3, hexproof 6, indestructible 6, **relentless 3**, T-91); `rises` 3.
- **Components:** the archetype base cost (Burst 4, Evasive 2, Drain 5, Swarm 6, Fortify 3, Debilitate 4, Punish 3, Escalate 4, Ward 3, Counter 3, Resource attack 4, sap 5, Necromancy 5, Enrage 0; an unknown label prices as Debilitate). Then the modifiers: cooldown 0–1 ×1.5, `once_per_encounter` ×0.5, a channel ×1.5; round up; then +2 if reactive. A charge detonation (`on_charge_full`) prices at its base +2 with no other modifier.
- **Level:** the smallest L with B(L) = 5L + 5 ≥ cost; for a boss, 2.5 × B(L) ≥ cost.

**The gate raises, it does not reject.** **[ruled 2026-09-25]** A generated enemy whose written Level is below its priced Level has its Level raised to the priced one, in code (§D25-1.4). "Level is derived" is the canon, so this makes the file true without a repair turn. A Level *above* the price is legal (§F-6: "underspending is legal (a simple high-level enemy)"). A raise that breaks an adventure's ladder (a minion priced at or above the outline boss) becomes a repair turn, which names the enemy, its cost and its priced Level, and asks the model to trim the kit or the body.

Pricing reads the model's own numbers, before `_scale_hp` and the Update 18 Power register. Those multipliers are difficulty, not cost.

### §D25-6 Lockdown in play, and the per-encounter caps

- **Lockdown counts.** A lockdown piece is an enemy whose kit carries a verb that attacks the party's turns: `stun`, `taunt`, a silence (`prevent` with `parameter: "cast"`), forced discard (`move_card` from hand), `sap`, or the hostile `modify_action` forms (hamstring, drain ultimate, strip reach). Each **body** in a layout counts, clones included; a `waves` objective adds its waves' bodies at that size.
- **The budget is a floor.** Each layout must field at least `_lockdown_budget(size, difficulty)` pieces (T-93: 0/1/2/3 for sizes 1–4, −1 on easy, +1 on hard). The owner wants more control pressure (§D23 preamble), so there is no ceiling. Adventure requests now print the budget per phase and size, as encounters always did.
- **Caps per pool (design, not body).** At most one of each of these per encounter or phase:
  - a resource-attack design (forced discard, silence or sap);
  - a poisoner;
  - an infect creature;
  - a counter piece (a `counter` verb);
  - a gauge-punisher (an `on_ultimate_cast` trigger, or a `hero_gauge_pct` condition).

  Clones of the one design are fine; they are lockdown pieces like any other. This squares the budget with the "one resource attack" cap: at size 4 the budget is met by stun, taunt and the hostile modifiers, plus copies of the one resource attacker.
- **A channeler at standard and above** (§E6-5): every encounter and every adventure phase at standard or hard fields at least one enemy with a `channel` component.

### §D25-7 What the enemy designer knows about the party

§D24-9.5 kept the designer to name, level, colours and concept, and deferred "tactical facts" to a separate change. This is that change. Each hero's roster line now also carries: attack mode and row; the keyword; the Skill and Ultimate names and one-line text; types and classes; carried gear names; and the three most recent chronicle deeds. It still never carries lore, wants, voice or ties. Those belong to the scenario writers.

**Grudges are taught.** The target-rule vocabulary now includes `hero_class:<class>` and `hero_type:<type>` (§D23-6), with the rule that a grudge names a tag the party actually wears, which the roster line now shows. With nobody wearing the tag, it falls back to valuation.

### §D25-8 The avoid-list

The town generator and the arc writer receive a `# ALREADY TAKEN` block:
- every town name in the tracked towns and the worldbook;
- every NPC name in those towns;
- villains from this install's campaigns (each run's arc);
- a fixed list of cross-model attractors from the bake-offs (Hedda, Pip, Rook, Tobiah Rell / Tobin Rale, the Seven Lamps, Quill, the ledger or contract necromancer, the iron Bosun).

The instruction: no reused name, and no near-miss spelling of one. The names are listed so they can be avoided, not echoed. The block is capped (T-94: at most 60 names) so it cannot swamp the prompt. The interlude planner gets it too, for a `new` hook's seed. Hard checks: a new town (or a `new` hook's seed) may not take an existing town's name, and an arc's villain may not wear a taken villain's or an attractor's name as a whole word. NPC names are prompt-only.

### §D25-9 Merchant stock is named by the act writer

Stock is still rolled in code at the act's tier (§D17-4.3). It is now rolled **before** the act writer runs, and the act prompt lists it by id, slot and rarity. The writer may return `stock_names: {item_id: {name, flavor}}`. The validator keeps entries whose id is in the roll and whose name is 2–40 characters and flavour at most 160, and drops the rest silently. It never touches stats, prices or rarity. The shop then shows the writer's names, and an unnamed item keeps its code name. No extra call is made. §D17-6.2's "the LLM only names/flavors" is now true.

### §D25-10 Gates that match their prompts

| Gap | Rule now |
|---|---|
| `defeated_once` (C-07) | When the act is written after a defeat, the questgiver's tree must contain a node gated on `defeated_once`, or the act is rejected |
| Lines for absent NPCs (C-08) | Flavour, topics and lines addressed to an NPC who is not in this act's town are a repair turn naming the NPC, not a silent drop |
| Duplicate JSON keys (C-09) | `_extract_json` rejects an object with a repeated key and names it |
| Identical reactions (C-10) | At most 2 enemies in a pool may carry the same reactive signature (trigger and verb shape), whatever else their kits hold |
| Quest themes (C-19 notes) | Two quests whose themes share 60% of their content words are duplicates (was: exact string match) |
| `enrage_round` | 3–5, as the prompt says (was 2–6); clamped by §D25-1.4 |
| Dialogue depth | 8, as the prompt says (was 10) |
| Arc cast | at most 3, as the prompt says (was 4) |
| `target_rule` and `trigger` strings | checked at load against the closed vocabularies (with `hero_class:`/`hero_type:`, `on_self_below_N`, `on_ally_below_N` and pool ids as the open forms); a typo is an error, where before it silently never fired |

### §D25-11 Vocabulary taught

- **Prompt errata (M4.18).** The bodyguard `redirect` is shown as `{"kind": "redirect", "new_target": {"mode": "self"}}` on `on_attack` (a hero's attack or Combat Ability is on the stack), plus `on_spell_cast` for a spell-warder. The old example turned the blow back on the hero and sat on `on_ally_hit`, a post-resolution trigger with nothing left to redirect. The `conditional` example uses the effect-condition vocabulary (`{"kind": "self_hp", "percent": 50, "compare": "or_less"}`), not the component-condition one, which the schema rejects there. The magnitude line "single target = L+1" becomes L+2 (T-20 after §D18-2). The worked examples' Levels are re-priced so the prompt's own examples pass §D25-5.
- **`relentless`** is listed with the keywords at min Level 3, cost 3 (T-91): an elite's or boss's intents pursue their declared target (§L-6.2).
- **Composite moving actions** (§L-2.3): one component whose verbs move the enemy itself and then strike (a charge), or strike and then fall back (hit-and-fade).
- **Countdown rites** (§D22-3/4): an enemy channel with an `after_turns` trigger that fires its payload and a `channel_drop` that ends it, so the party sees a clock and must break it in time.
- **Objectives in standalone encounters** (§D12-7, B-01): the objectives section moves out of the adventure extension into a shared block that encounters receive too. At most one objective per encounter, the same four kinds and the same gates.

### §D25-12 Also in this update

- **Adventure art resumes after a restart** (M4.16). When a client connects to a session whose adventure is ready (or partly written), its unpainted images queue. Painted images are adopted, not repainted. The playtest profile still idles it.
- **Library scenarios read the world** (M4.14). `pregenerate_scenario` passes the worldbook context (this town and its neighbours) to the arc writer, and the avoid-list. There is still no party at pregeneration, so the act writer, which runs at play, remains the party's reader.
- **Generated gauntlets** (M4.17). The tester's `generate_gauntlet` is pinned by a mocked test. Running it for real, which costs calls, is the owner's.

---

## Part B — Implementation notes

- **B.1 Transport (§D25-1):** `_live_chat` retry loop with `TRANSPORT_TRIES`, `RETRY_BASE_S` and `RETRY_CAP_S`; `ENCOUNTER_TIMEOUT`; `_coerce_encounter` runs after `_normalize` in both generators. Repair loops catch `(ValueError, TypeError, AttributeError, KeyError)`.
- **B.2 Caching (§D25-2):** `_wire_messages(model, messages)` builds the content-block form in `_live_chat` only. The tape's hash is unchanged.
- **B.3 Phases (§D25-3, §D25-4):** `llm.generate_adventure` keeps its signature and gains `on_phase(index, partial_detail)` and `resume` (outline plus phases done). New helpers: `adventure_outline`, `generate_adventure_phase`, `_outline_problems`, `_phase_ladder_problems`. `content.save_adventure_phase` writes a phase and the partial wrapper; `content.adventure_detail` returns partial details (`phases_total`, `outline`); `list_adventures` hides partials. `AdventureRun` reads `phases_total`, gains `add_phase` and `next_phase_ready`, and `advance` refuses a missing phase. `Session.confirm_level_up` parks on `awaiting_phase`, and `Session.phase_landed` composes when the phase arrives. `jobs.AdventureJobRunner` becomes ready at Phase I and keeps writing; it resumes from `outline` and `phases_ready`. A load that needs the job resumed defers it to the first client connect (`Session.resume_adventure_job`), because the load route has no event loop. `RunManager._freshest_detail` loads the job's fuller copy of the same adventure over a save's. The snapshot's `adventure_job` gains `phases_ready`/`phases_total`, and the adventure block gains `awaiting_phase`. The client shows both.
- **B.4 Pricing (§D25-5):** `llm.price_enemy`, `ARCHETYPE_COSTS`, `KEYWORD_COSTS`; called by `_coerce_encounter`.
- **B.5 Lockdown and caps (§D25-6):** `_lockdown_pieces(enemy)`, `_lockdown_problems(encounter, difficulty)`, `_cap_problems(encounter)`, `_channeler_problems(encounter, difficulty)`.
- **B.6 Party facts (§D25-7):** `party_summary_from_loadouts` adds `attack_mode`, `row`, `keyword`, `skill`, `ultimate`, `types`, `classes`, `gear`, `deeds` (deeds from the campaign chronicle when a run supplies it); `_roster_lines` renders them for both request blocks.
- **B.7 Avoid-list (§D25-8):** `llm.avoid_names()` (towns, NPCs, run villains), `ATTRACTOR_NAMES`, `ATTRACTOR_MOTIFS`, `_avoid_block`; used by `town_prompt`, `arc_prompt`, `interlude_prompt`; the name checks live in the writers' `fix` closures (`generate_town`, `generate_arc`, `generate_interlude`).
- **B.8 Stock (§D25-9):** `ScenarioRun.roll_stock()` moves out of `_take_materialization`; `materialize_inputs` passes `stock`; `act_prompt` renders it; `validate_materialization` cleans `stock_names`; `_take_materialization` applies them.
- **B.9 Gates (§D25-10):** in `llm._extract_json` (`object_pairs_hook`), `_sameness_problems`, `_boss_pressure_problems`, `scenario_content` (`validate_materialization`, `_clean_quests`, `validate_arc`), `dialogue.MAX_DEPTH`, and `ltg_combat.scenario._component_from_dict` for target rules and triggers.

## Part C — Documents to update

- [game_design.md](../game_design.md): §9.1 (relentless price; pricing is enforced), §12 (lockdown floor and caps; channeler rule), §13 (phased adventures, stock naming).
- [generation.md](../generation.md): §2 writers table, §4 reader matrix (enemy designer; avoid-list), §6 gates, §7 repair loop and transport, §10 attractors.
- [balance_register.md](../balance_register.md): T-89–T-94.
- [architecture.md](../architecture.md): the adventure job's phase states and the boundary wait.
- [roadmap.md](../roadmap.md): M4 rows.

## Part D — Tests

`tests/test_design_update_25_pipeline.py` (transport retry, caching markers, coercion, shape faults, phased adventures incl. resume and the boundary wait), `tests/test_design_update_25_gates.py` (pricing, lockdown, caps, channeler, validator tightening, prompt errata, party facts, avoid-list, stock naming). Every model call is mocked.

## Part E — Order

1. Transport and caching (§D25-1, §D25-2).
2. Gates and prompt errata (§D25-5, §D25-6, §D25-10, §D25-11).
3. Party facts, avoid-list, stock naming (§D25-7–§D25-9).
4. Phased adventures and per-phase repair (§D25-3, §D25-4), then art resume.

## Decisions confirmed (owner, 2026-09-25)

1. **§D25-3:** Start Adventure opens after the outline plus Phase I, with II and III written while Phase I is played; a fast party can wait at a boundary.
2. **§D25-5:** an underpriced Level is raised in code rather than sent back to the model; an overpriced Level stays legal.
3. **§D25-6:** the lockdown budget becomes a floor that rejects a thin layout (it was prose only).
4. **§D25-11:** `relentless` at min Level 3, cost 3.
