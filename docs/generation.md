# How LTG content is generated

A reference for designers and coding agents, verified against the code on 2026-09-24. The code is the source of truth. Symbols live in `apps/game-server/ltg_game_server/` unless a path says otherwise. Design decisions are cited by section and resolved in [design/README.md](design/README.md). Known gaps are tracked in [roadmap.md](roadmap.md) (mostly M4).

## 1. The wall

- **Generation and resolution never mix** (GDD §1). Three places call a model: `llm._chat` (every text writer in the game server), `art._request_image` / `art._request_comfyui` (images) and `ltg_deckbuilder/flavour.py` `chat`. `ltg_core` and `ltg_combat` import no model client.
- **The runtime is deterministic.** Enemy intents come from code heuristics. `dialogue.Conversation` walks validated trees over the closed `dialogue.HOOKS`, and `freeform: true` is rejected. Loot names come from code word-banks (`loot.build_lexicon`, §D17-4.5) and shop stock from tables (`items.roll_stock`). No narrator exists.
- **Writers can run during a session** (on arrival, Quest Accept, a boss's death, Continue), but they only produce content. It is validated, frozen into the run's content store (`RunManager.put_content`), then walked or executed by code. A reload reuses it and never re-rolls it (§D17-6.3). The UI waits on content (the entry splash, the greyed Start Adventure button), never on a rules decision.
- **Bounded vocabularies bridge the two sides**: effect verbs, enemy `types`/`classes` (§D21), archetypes, triggers, conditions, target rules, dialogue hooks, location functions and hook kinds. Models compose within them; code defines them.
- **Validators are the gate.** Generated content takes the authored save path (`content.save_encounter`, `content.save_adventure`, `scenario_content.save_town`, …), plus generation-only gates that are stricter than authoring.
- **Judge a model by running the real validator, never by `json.loads`.** In the 2026-08/09 bake-offs every failure was a validator failure: cycles, dangling `next`, invented classes, cloned kits. The `save_*` functions write to disk, so repoint the content directories first when judging samples offline, as the test fixtures do.

## 2. The writers

| Writer | Function | Trigger | Inputs (system; user) | Output | Gates | Task | Tokens / timeout / attempts |
|---|---|---|---|---|---|---|---|
| Encounter designer | `llm.generate_encounter` | New Game → Generate encounter (`POST /api/encounters/generate`); Autoplay Tester gauntlets (`persist=False`) | `settings["instructions"]`; `_request_block` | an encounter saved to `content/<slug>.json` | §6 encounter chain, then `content.save_encounter` | `encounters` | 24,000 / 120 s / 2 |
| Adventure writer | `llm.generate_adventure` | Quest Accept (`jobs.AdventureJobRunner`, `run_only=True`); New Game or Options → Adventures (`POST /api/adventures/generate`) | the instructions plus `ADVENTURE_EXTENSION`; `_adventure_request_block`, plus `_adventure_context_lines` in a run | 3 phases with narrations, saved as a wrapper plus `<id>__phase1..3` | the per-phase chain, `_narration_problems`, `content.save_adventure` | `adventures` | 64,000 / 900 s / 3 |
| Town generator | `llm.generate_town` | Options → Towns (`POST /api/towns/generate`); Continue on a `new` hook | `TOWN_INSTRUCTIONS`; `town_prompt` | a town plus its `world_entry`, saved to `content/towns/` and `content/world/` | `validate_town`, `world.validate_entry`, the seed name | `towns` | 64,000 / 1,200 s / 3 |
| Standing topics | `llm.generate_town_topics` | Options → Towns → topics (`POST /api/towns/{id}/topics`) | `TOPICS_INSTRUCTIONS`; `_town_block(topics=False)` plus the NPCs without topics | `{topics: {npc: [{ask, reply}]}}`, merged into the town | NPC resolution, `clean_topics`, coverage of every listed NPC | `towns` | same |
| Arc writer | `llm.generate_arc` | Town + New (blocking inside `POST /api/games`); `scenario.pregenerate_scenario`; Continue | `ARC_INSTRUCTIONS`; `arc_prompt` | title, villain, stakes, cast, places, 3 act outlines | `validate_arc` | `scenarios` | same |
| Act writer | `llm.generate_act` | every arrival in town; after a Normal-mode defeat; `pregenerate_scenario` (Act I); resume on load | `ACT_INSTRUCTIONS`; `act_prompt` | quests, arrival, dialogue trees, flavour, topics, closing lines, `town_state_delta` | `validate_materialization` | `scenarios` | same |
| Interlude planner | `llm.generate_interlude` | the Act III boss's death (`jobs.InterludeJobRunner`); Continue re-queues a failure | `INTERLUDE_INSTRUCTIONS`; `interlude_prompt` | the post-victory town plus 3 hooks | `validate_interlude` | `scenarios` (default) | same |
| Worldbook backfill | `scripts/backfill_worldbook.py` `backfill` | run by hand, for towns with no entry (`--dry-run` prints the prompts) | `BACKFILL_INSTRUCTIONS`; `_town_block` plus `_book_block` | a `world_entry`, written by `world.append_entry` | `world.validate_entry` | `towns` | same |
| Deck flavour | `ltg_deckbuilder.flavour.generate_flavours` | Deckbuilder topbar → Generate deck flavour (`POST /api/flavour/generate`) | `flavour.INSTRUCTIONS`; `prompt_for` | `{flavours: {card id: text}}`, which the client writes into `flavor_text` | every card, Skill and Ultimate id covered | `flavour` | 16,000 / 300 s / 2 |
| Art | `art.generate`, `generate_town_art`, `generate_item_art`, `generate_cast_art`, `generate_place_art`, `generate_spoil_art` | per-image buttons; `art.QUEUE` | `_style()` plus task framing plus the content's prose | an image file, with its URL written onto the JSON | backend errors only | `ART_MODEL` or ComfyUI | 180 s (OpenRouter) or 300 s (ComfyUI) / 1 |

No model is involved in loot or item naming (`loot`, `items`), merchant stock, or panel animations. Animations are made offline and uploaded (§11).

## 3. When generation happens in play

1. **Town (offline).** Options → Towns → *Generate town* takes a note and a placement: "placed on its own" founds a region; "beside *town*" passes `anchor_town_id` to `world.placement_context` (the anchor's region, the anchor and its neighbours). One call writes the town and its worldbook entry.
2. **Scenario start.** New Game → Scenarios always creates a run.
   - *Town + New*: `generate_arc` runs blocking inside the create-game request, with only the town and a roster line (502 on failure). Act I then materializes off-thread under the entry splash (`app._materialize_task` → `Session.materialize_act` → `ScenarioRun.materialize` → `generate_act`).
   - *Library scenario*: `pregenerate_scenario` stores an arc (written for a generic two-hero party at `standard`) and Act I's town portion, with no adventure (§D20-3). `content/scenarios/` is empty today, so every scenario starts from a town.
3. **Arrival (every act).** `_take_materialization` rolls the stock and forges the spoils in code, and their art queues. Acts II and III materialize on arrival. A Normal-mode defeat re-materializes the act with `defeated_once` set (§D17-6.4).
4. **Quest Accept.** A `grant_quest` + `unlock_adventure` choice auto-saves `quest_accept` and starts `jobs.AdventureJobRunner`.
   - The state (`idle → pending → ready | failed`, with `progress`, `adventure_ref` and `error`) persists to `run.json` via `RunManager.set_job`.
   - The generator runs in a worker thread with the run's party copies, `levels()`, `effective_level()`, `phase_budget_levels()` and `adventure_context()`. The player's note is not passed.
   - On success the detail is frozen into the content store before `ready`, and its art queues, Phase I first.
   - On failure the button reads "Generation failed — Retry" (`retry_job` restarts the whole loop), and the quest stays accepted. Loading a save with an unlocked adventure and no detail resumes the job.
5. **The closing boss's death (Act III).** `Session._scenario_transitions` calls `note_boss_death` and queues `jobs.InterludeJobRunner` before the spoils modal. The result lands on `pending_interlude` and in `run.json` (`interlude_ref`). An early Continue sets `continue_requested` and lands when the planner returns.
6. **Continue.** `continue_campaign` → `begin_interlude` runs no model: the planner's town is the act. The inn's `rest` opens the rest screen, and choosing a hook (`choose_hook`) applies the days, heals and saves `hooks_chosen`. Then `app._continue_sync` runs in a thread:
   1. A `new` hook calls `generate_town(seed line, 3, placement_context(anchor), seed)`. `neighbour` uses the named town; `stay` keeps this one.
   2. `generate_arc` runs with `ledger_for_writers()`, `party_state()`, `world.context_for(town_id)` and the hook.
   3. `begin_next_scenario` closes the ledger entry, parks town flags on the campaign's town state and draws a new loot lexicon.
   4. `arrive(None)` and `materialize_act()` build Act I under the splash.

   A failure sets `materialize_error` ("the road ahead: …"); *Try again* on the splash (or reloading the save) retries it.
7. **Art** paints in the background throughout (§11).

## 4. What each writer reads

The table follows the code. † marks a difference from the reader matrix in §D24-7.6.

| Reader | Party | Lore | Ledger | Town | Worldbook | Also |
|---|---|---|---|---|---|---|
| Arc writer (`arc_prompt`) | a roster line (name, level, colours) and difficulty, plus `_party_block(depth="full", chronicle="summaries")` (at a campaign's start from `opening_party_state`: briefs and default situations, no chronicle) | never | at Continue (a new campaign has none) | `_town_block` of the raw town file, with no town state † | this town and its neighbours (a pre-generated scenario's arc gets neither party nor world) | `_hook_block` at Continue; the note |
| Act writer (`act_prompt`) | `_party_block(full, recent)` | up to 2 entries | all scenarios, including the one in progress | the composed town (`town_for_act`: cast, places, town state) plus `_arc_block` with the cast's secrets | this town only | the day, public flags, the `knows` list, a `defeated_once` paragraph; `_hook_block` on a continuation's Act I (the chosen hook's road, bridge and note) |
| Interlude planner (`interlude_prompt`) | `_party_block(full, recent)` | never | all, with the current scenario recorded as a victory | the last act's composed town plus `_arc_block` | this town and its neighbours, or a "stay/new only" line | the villain is defeated |
| Enemy designer (`_request_block`, `_adventure_request_block`) | name, level, colours and `brief.concept` (§D24-9.5) | never | — | in a run: the town's name, region and NPC names | — | in a run, the arc, act and quest; the library avoid-list; signature rolls |
| Town generator (`town_prompt`) | — | — | — | — | `_world_placement_block`: the region to join or found, and the towns it sits beside | the seed (name, line, bridge); the note |
| Topics writer, backfill | — | — | — | `_town_block(topics=False)` | the backfill only: the whole book (`_book_block`) | the topics writer: the NPCs it must cover |
| Deck flavour | concept, appearance, voice register | the first 300 words of `character.lore` | — | — | — | `combat_lore` and every card's text |

**The block renderers**, all in `llm.py`:

| Block | Renderer | Content |
|---|---|---|
| `# THIS ENCOUNTER'S PARAMETERS` | `_request_block` | Roster, average level, difficulty. Per party size: `_min_enemies` bodies, a `_budget` level target and a `_lockdown_budget` count. Boss rule (hard), channeler rule (not easy), 2 signature rolls, library lines, note. |
| `# THIS ADVENTURE'S PARAMETERS` | `_adventure_request_block` | Roster, difficulty, entry level. Bodies and budget per phase and size at `phase_budget_levels` (+10/+20/+30 grants), with **no lockdown lines**. Boss rule, a channeler per phase, one roll per phase, library lines, context. |
| `# SCENARIO CONTEXT` | `_adventure_context_lines` | Arc title, villain and stakes; the act outline, with the accepted quest's `adventure_theme` replacing the outline's; act *n* of 3 (the finale's boss is the villain); town name, region and NPC names; the quest's title and text. |
| Library steer | `_library_lines`, `_recurring_motifs` | Owned encounters (with enemy names) and non-run adventures (with flavour), marked off-limits, plus five-letter stems recurring across two or more of them. |
| Signature rolls | `_signature_rolls(k)` | `random.sample` of `SIGNATURE_POOL` (24 mechanics) |
| `# TOWN` | `_town_block` | Locations `[id]` (tagged when the arc added them); NPCs with `(vendor)`/`(CAST)` tags and personas; with `topics=True`, their standing topics. |
| `# ARC` | `_arc_block` | Villain, stakes, cast (with "SECRET (writers only)" lines), places, act outlines. |
| `# THE PARTY` | `_party_block(depth, chronicle)` | Per hero: name, level, colours, concept and appearance; voice register and up to 3 samples; wants, won't, tell; ties; Now / Before this / Recently (last 10). Capped at `PARTY_LINES_FULL` (5) or `PARTY_LINES_SUMMARY` (2); no caller uses `summary`. |
| `# PREVIOUSLY` | `_ledger_block`, `_act_ledger_lines` | Older scenarios as one-liners plus refused quests and the fallen; the latest in full, per act. |
| `# THE WORLD HERE` | `_world_block(ctx, neighbours)` | Region gist, town gist, "Known for", and neighbours' one-liners (arc writer and planner only). |
| `# HOW WE GOT HERE` | `_hook_block` | The hook's narration, its bridge and the player's note. |
| `# WORLD` / `# THE SEED` | `_world_placement_block`, `town_prompt` | Placement; on a continuation, the seed. |
| `# LORE IN PLAY` | `act_prompt` | Up to 2 entries from `content.lore_in_play`: "Colour a line, never a quest." |

**Flag hygiene** (§D24-7.7). `ScenarioRun.party_state()` drops `_`-prefixed bookkeeping flags (`_met_*`, `_offered_*`, `_shop_open`) and moves `knows_*` into a separate `knows` list. `act_prompt` prints the public flags (including `town:*`) and "The party already knows of: …" separately. `knows_*` are cleared at scenario end; the ledger keeps what was learned as prose.

**Lore selection** (§D24-7.3, amended). `content.lore_text_entries` splits `character.lore` into entries (a heading starts one, otherwise each paragraph is one), and `_auto_keys` derives keys from capitalised names and the title. `lore_entries_for` adds `loadouts/lore/<char>/*.md`. `select_lore` keeps an entry when a key is a substring of the town/arc haystack (`_lore_haystack`) or its `gate` is open, ranks by keys matched, and cuts each to its first paragraph, at most `LORE_MAX_WORDS` (120). `lore_in_play` caps the whole party at `LORE_MAX_PER_ACT` (2). `mode: open` is never read.

## 5. The prompts

### The encounter designer: `DEFAULT_INSTRUCTIONS`

84,379 characters (about 21k tokens), sent as the system message on every encounter and adventure call. Its headings, in order:

- `# Setting & theme`: classic high fantasy (MTG / D&D register), NO CHILD COMBATANTS, one fresh theme, owned titles off-limits, BE CONCRETE.
- `# The enemy framework` (Update 04): chassis; types and classes (§D21, closed lists substituted at import); archetypes and costs; the HARD REQUIREMENTS (two components, the punching-bag rule, no lone taunt, row shapes aim at ground); typed counters; resource attacks and hostile `modify_action`; magnitudes by level; the trigger, condition and target-rule vocabulary; corpses, forced movement, positional intents, windups, channels; spell vs ability ("Combat Abilities are DERIVED"); keywords; budget → level (B(L) = 5L + 5).
- `# Design guidance` (6.7k characters): the pattern palette, MECHANICAL VARIETY anti-rut rules, one signature mechanic per fight.
- `# Party-size layouts`: a pool of 5–8, size+1 distinct designs, at most 3 copies, the boss in every layout.
- `# Bosses` (4.8k): 2.5× budget, execute window, two intents, the required `enrage_round`/`neglect`, a multi-verb Enrage, phase gates, silhouettes.
- `# Scene & visual descriptions`.
- `# Output JSON contract` (14.2k), including §D23-6's five under-used verbs and the enemy-legal limits.
- `# Three worked examples` (25.9k, 31% of the prompt).

**The user override.** Options → LLM exposes the whole text as `settings["instructions"]`, which also prefixes adventures. `save_settings` stores `""` when the text equals the default, so upgrades reach uncustomised installs. A customised copy, type lists included, stays frozen until reset (`instructions: null`).

**Difficulty.**
- `_budget` = round(2 × size × average level × `DIFFICULTY`, 1.0 / 1.5 / 2.5); `_min_enemies` = 2 × size; `_lockdown_budget` = 0/1/2/3 for sizes 1–4, −1 on easy, +1 on hard.
- Hard requires a boss, every difficulty but easy a channeler; easy asks for lean designs.
- `_scale_hp` then multiplies HP by `ENEMY_HP_MULT` (1.0 / 1.2 / 1.5) × `ENEMY_STAT_BUFF` (1.2; `BOSS_STAT_BUFF` 1.3), and Power by the buff alone.
- At play, `AdventureRun` rescales HP by the `ENEMY_HP_MULT` ratio when the run's difficulty differs from the adventure's stamp, and `content.apply_boss_difficulty` gives bosses two intents on standard and hard. `content._bump_enemy_power` adds the Update 18 register (+2 Power and hostile damage, +4 for bosses, +2 more on row shapes), so generated files show numbers from before the register.

### `ADVENTURE_EXTENSION` (10.2k characters, about 2.5k tokens)

Appended for adventures (§D10-5). It asks for:
- three stations of one place, with per-phase budgets and one rolled signature per phase;
- exactly one boss in Phase III, the adventure's highest-level enemy; optional, strictly lower mini-bosses in Phases I and II;
- a `narration` per phase (2–4 paragraphs, 120–250 words, second person: the road in, the discovery, the reason, one voice) and a one-line `flavor`;
- an objectives block (§D12-1, amended by §D23-5): at most one objective per adventure, and on Phase III only a guarded race on the boss, waves ending on the boss, or a deadline. §6 covers how the save gate treats that.

### The scenario writers

`_scenario_chat` fills `%TONE%`, `%CONCRETE%` and `%VOICE%` from `settings["scenario_tone"]`, `CONCRETENESS_RULE` and `VOICE_RULE`; only the tone is user-editable. Rendered sizes: town about 2.0k tokens, topics 1.0k, arc 2.0k, act 4.5k, interlude 1.9k.

- **`TOWN_INSTRUCTIONS`**: the four required locations (literal function words) plus 1–3 flavour locations, each with a description, `exterior_scene`, `interior_scene` (which doubles as the entry splash) and 1–2 NPCs. Each NPC gets a persona (reused verbatim later), a `portrait_desc` and 2–3 topics. One vendor per shop; no dialogue, stock or quests. A `world_entry`: join or found a region, a one-paragraph gist with no plot, 2–4 notable things, and 1–2 neighbours taken only from `# WORLD`.
- **`TOPICS_INSTRUCTIONS`**: 2–3 specific exchanges per listed NPC, with no plot and no stage directions.
- **`ARC_INSTRUCTIONS`**: one villain across three acts; a real fork named in each hook ("never the same job by two roads"); an optional cast of 0–3 (each with a writers-only `secret`) and 0–2 places; rules for THE PARTY, PREVIOUSLY and HOW WE GOT HERE.
- **`ACT_INSTRUCTIONS`**: 2–4 materially different quests written as the party's journal, each with its own `adventure_theme`; an arrival paragraph; short acyclic trees (BE UNDERSTANDABLE, required narration beats, closed hooks, accept = `grant_quest` + `unlock_adventure` with a defer beside every offer, a `defeated_once` branch, `knows_*` gating); flavour lines, gated act topics, closing lines, and an optional `town_state_delta`.
- **`INTERLUDE_INSTRUCTIONS`**: premises, never outcomes, and no lore. It writes the town after victory (no quest hooks, back 1–14 days) and exactly three hooks (stay / neighbour / new), each with a narration, bridge, days and 1–2 foreshadowing exchanges.

## 6. Gates

| Gate | Where | What it enforces |
|---|---|---|
| `_extract_json` | every `llm.py` writer | Strips code fences, falls back to the outermost `{…}`, and requires an object. Duplicate keys pass, with the last one winning. |
| `_normalize` | encounters, each adventure phase | `enemies` must be a list. Fills in missing enemy ids (from the name) and component ids (from the archetype). |
| `_scale_hp` | same | Not a check: applies the stat multipliers from §5. |
| `_check_layouts` | same | Layouts "1"–"4" exist; each has at least 2 × size bodies and size + 1 distinct designs; no design appears more than 3 times. Then calls `_check_ranged_placement`: no ranged enemy in the front row (§D23-3). |
| inline scene / description checks | `generate_encounter`, `generate_adventure` | A top-level `scene`, and a `description` on every enemy. |
| `_design_problems` | same | The §D14 kit floor: at least 2 components; no proactive, repeatable, cooldown-under-2 component built only from self-buffs (`_SELF_DEV_KINDS`); every `charge` has its `on_charge_full` detonation. |
| `_corpse_problems` | same | §D19-1: when a corpse `exile` shares a component with other verbs, it must be `consume_corpse`. |
| `_type_problems` | same | §D21: 1–2 `types` and 1–2 `classes`, each from its closed list. |
| `_taunt_problems` | same | §D18-1: a taunt also carries `deal_damage`, `lose_life` or `drain`. |
| `_sameness_problems` | same | Rejects:<br>• two enemies with the same kit signature (archetype, timing, trigger and verb shapes; amounts ignored)<br>• three or more hero-aimed components that all use one `target_rule`<br>• fewer than min(4, pool size) distinct archetypes<br>• a pool of 3 or more that all share one row or one attack mode |
| `_boss_pressure_problems` | same | Every boss has `enrage_round` (accepted range 2–6; the prompt says 3–5) and `neglect` of 1–2. |
| `_objective_problems` | same | A race needs 1–2 `guards` and 3–5 `turns`. A survive needs at least 2 reinforcement entries. A deadline needs 4–6 `turns`. |
| `_narration_problems` | adventure phases | The narration is at least `NARRATION_MIN_WORDS` (100). |
| `_lockdown_budget` | `_request_block` | Not a gate: it prints a number, and nothing counts lockdown pieces. |
| `content._validate_encounter` (inside `save_encounter`; called directly when `persist=False`) | encounters, each phase | Named enemies with positive hp and level; at most one boss; layout ids exist, with the boss in every layout (or the final wave); the objective schema, with a race's target and guards in every layout. Then a **build probe**: `state_from_dict` with a stub party for every layout runs the engine's own component checks (for example the §D12-2.3 ultimate-counter guardrail). |
| `content.save_adventure` | adventures | Exactly 3 phases, at most one objective, and **no objective at all on Phase III** ("Phase III is always the standard boss kill"). Each phase passes `_validate_encounter` and `_validate_phase` (layouts, bodies, descriptions). `_validate_adventure` then checks the narrations, a single Phase III boss, strictly lower mini-bosses, and no enemy above the boss. |
| `scenario_content.validate_town` | towns, topics | Name and scene; each required function exactly once; 1–8 flavour locations; an interior scene everywhere (exterior optional); 1–4 NPCs per location, each with a persona and a `portrait_desc`. Ids are slugged and de-duplicated; one vendor per shop is settled, not rejected. `clean_topics` keeps at most 4. |
| `world.validate_entry` | towns, backfill | A gist (silently cut at 160 words); a `region_id` or a valid `new_region`; at most 6 notable things and 4 neighbours (extras dropped), each neighbour a known town. `generate_town` also makes a continuation town keep its seed's name. |
| `scenario_content.validate_arc` | arcs | Title, villain, stakes; exactly 3 acts, each with a title, hook and `adventure_theme`. The questgiver resolves (by id or name) to a town NPC or a cast member present that act; an unknown handoff becomes none. Cast is capped at 4 and places at 2 (extras dropped), and every cast member stands at a real location. |
| `scenario_content.validate_materialization` | acts, interludes | • `_clean_quests`: 2–4 options, each with its own non-empty `adventure_theme`; exact duplicates are refused<br>• an arrival paragraph<br>• dialogue only for real NPCs (`dialogue.validate_dialogue`), and a tree for the questgiver<br>• narration nodes: at least 1 in any tree of 4 or more nodes, and at least 2 in the questgiver's<br>• `_bind_quest_hooks`: every grant names an option and carries `unlock_adventure`; every option can be accepted somewhere; a defer sits beside every accept<br>• `check_flag_consistency`<br>• every NPC has something to say<br>• `validate_town_state_delta` (at most 2 real locations)<br>Lines addressed to unknown NPCs are dropped silently. |
| `dialogue.validate_dialogue` | inside the above | Closed `HOOKS`; speakers limited to npc, party and narration; at most 5 choices per node; every `next` exists; no cycles; depth at most 10; no `freeform`. |
| `dialogue.check_flag_consistency` | inside the above | Every `requires` flag must be standing (`STANDING_FLAGS`), have an `item_` or `town:` prefix, already be true in the run, or be set by some `set_flag` in this act's trees. |
| `scenario_content.validate_interlude` | the interlude | Exactly 3 hooks, at least one staying and at least one leaving. Each has a narration and a bridge. A `neighbour` names a known town (checked only when this town has a worldbook entry). A `new` hook carries a seed and a known anchor. At most 2 foreshadow exchanges per hook, spoken by NPCs in town who have no interlude tree. The town portion passes `validate_materialization` with no quests and `QUEST_HOOKS` forbidden. |
| flavour check | `generate_flavours` | Every card, Skill and Ultimate id gets non-empty text. |

## 7. The repair loop

- **Shape.** Call, parse, validate. On a `ValueError` the writer appends its reply plus `That output was rejected: <error>\nFix it and return ONLY the corrected <what> JSON.` and calls again, up to `attempts`: 2 for encounters and flavour, 3 for everything else. Then it raises `<what> generation failed after N attempts: <last error>`.
- **What is fed back** is the validator's own message. The `_*_problems` gates collect every problem; `_normalize`, `_check_layouts`, the content gates and the scenario validators stop at the first. Adventure phases are checked in order and the loop stops at the first failing phase ("phase 2: …"), so later phases go unchecked in that attempt. The retry re-emits the whole adventure, which can break a phase that had passed.
- **Growth.** Each retry re-sends the system prompt, every earlier reply and every error. No call uses prompt caching.
- **`_chat`.** One POST per attempt with `temperature` 0.9, `response_format: {"type": "json_object"}`, `max_tokens`, and the caller's timeout (120 s if none is given). Transport errors, a 401, any other status of 400 or above, and malformed bodies raise `ValueError` outside the repair `try`, ending the loop at once. `finish_reason == "length"` also raises ("ran out of room … raise the budget"), so truncation never burns a repair. There is no transport-level retry.
- **Budgets.** Encounters: 24,000 tokens with `_chat`'s default 120 s timeout. Adventures: 64,000 / 900 s. Scenario writers: 64,000 / 1,200 s, sized for about 75 tokens/s. Flavour: 16,000 / 300 s; it does not check `finish_reason`, so a truncated flavour reply does burn a repair.
- **What a failure costs** after the last attempt:

| Where | Result |
|---|---|
| Options or New Game (encounter, adventure, town, topics, pregenerated scenario) | HTTP 422 or 502 with the last error. Nothing is saved. |
| Town + New arc | `POST /api/games` returns 502. No run is created. |
| Act materialization | The splash shows "The chronicle faltered: …" with *Try again* (the `retry_materialize` town verb), and a banner keeps the retry if the splash is dismissed. An act-less `act_start` save is written, so reloading runs it again too. Any exception counts, not only a `ValueError`. |
| Adventure job | The job becomes `failed`. *Retry* re-runs the whole loop from a fresh conversation, and the quest stays accepted. |
| Interlude | The job becomes `failed`, and Continue re-queues it. |
| Continue (town, arc or act) | `materialize_error` is set and the chosen hook stays. *Try again* re-runs the whole road ahead (town, arc, Act I) when the next scenario never began, or only Act I when it did. Reloading also retries. |

## 8. Models

- **Transport.** OpenRouter chat completions (`OPENROUTER_URL`) via `httpx`. The key lives in the gitignored `apps/deckbuilder/loadouts/llm_settings.json`, shared with the Deckbuilder; `public_settings()` reports only `has_key`.
- **`MODELS`**: Gemini 3.8 Flash (`MODELS[0]`, the fallback default), Claude Opus 5, Claude Fable 5.1, Claude Opus 5 Fast, GPT-5.6 Sol, GPT-5.6 Luna Pro.
- **`MODEL_TASKS`** is the registry Options → LLM renders verbatim: `encounters`; `adventures`; `towns` (towns, topics, backfill); `scenarios` (arcs, acts, and the interlude through `_scenario_chat`'s default task); `flavour`. `""` follows the default `model`; `model_for(task)` resolves it. A new task needs no client change.
- **`_MODEL_ALIASES`** maps retired slugs on read: GLM and Gemini 3.5 / 3.7 Flash → Gemini 3.8 Flash, Opus 4.8 → Opus 5, Sonnet 5 → Sol. Unknown slugs fall back to the default. `flavour.py` keeps its own copy (`_RETIRED_MODELS`) because the apps may not import each other; change both.
- **Images**: `ART_MODEL` (`google/gemini-3.1-flash-lite-image`) or ComfyUI (`ART_BACKENDS`).

**Bake-off guidance** (from the owner's notes, 2026-08-29 → 09-05). Prices are OpenRouter's per-call cost at the time. When comparing models, count a validator failure as about 2× the cost and latency.

| Model | Verdict | Evidence |
|---|---|---|
| Opus 5 Fast | Showcase and finale; the fast premium tier | Richest act output (134¢, 106 s); the only clean pass in the 08-29 adventure round (about 296¢ per adventure) |
| Opus 5 | Best prose. Suited to work where latency does not matter (towns, scenarios made ahead of time). Best encounter craft per cent. | Best town of its round (40¢, 247 s); an encounter run costs about 178¢; once wrote a dialogue cycle |
| Fable 5.1 | Best campaign seeds and best single ideas; the most expensive | Town 94¢; encounter run about 341¢; once produced a child enemy |
| GPT-5.6 Sol | Mid tier, the default | About 90% of Sol Pro's quality at a third of the price; act 10¢, 83 s |
| GPT-5.6 Luna Pro | Volume; best quality per cent | Act about 3¢, 86 s |
| Gemini Flash | Speed fallback | Tested as 3.7 (about 3¢, 25 s), which is now aliased to 3.8. Near-deterministic across trials. |
| GPT-6 Astra | Reliable for encounters on a budget; dropped from towns | Clean first-try encounters (118¢, 252 s). Its towns were thin and written in the quip register. It is not in `MODELS`. |
| Pruned | Sonnet 5 (aliased to Sol), Sol Pro, GLM (aliased to Gemini Flash) | — |
| Rejected | Mercury 2, a diffusion model that put `effects` on dialogue nodes, so its flags could never be set. Minimax M2.7, off-spec: third-person flavour and a skipped `defeated_once` branch. | — |

**Current picks on this install:** Opus 5 Fast for encounters, adventures and scenarios; Fable 5.1 for towns; Luna Pro for flavour and as the default model; ComfyUI for art, with a customised art style; the default instructions and tone.

## 9. Taste rules

- **Tone.** `DEFAULT_SCENARIO_TONE` is classic high fantasy: warm and wondrous rather than grim, towns worth saving, peril belonging to the villain and the road, rated PG. It is editable in Options → LLM, and only writers that go through `_scenario_chat` (including the backfill) receive it.
- **Concreteness.** `CONCRETENESS_RULE` is in every scenario writer, and the encounter prompt has an inline version. It asks for nouns a painter could paint and threats with a body, a place and a method. It bans abstract dread ("a wrongness"). Tropes are welcome; freshness belongs in the detail. The test: if a sentence would still be true of a completely different monster, it is too vague.
- **Voice.** `VOICE_RULE` covers towns, topics, arcs, acts and interludes, and it is the owner's strongest taste rule.
  - Weight comes from context and contrast: write a cast as a palette of registers.
  - A town has at most one genuinely wry voice. Most people speak plainly about their trade and their troubles.
  - Banned: the "try-hard" register, meaning punchline-shaped replies, the arch faux-understated quip, whimsy props, and a whole cast speaking in one droll narrator's voice.
  - When judging output, reward character shown through action, object and trade, and mark down quip density.
- **NO CHILD COMBATANTS** (encounter prompt). Every enemy is an adult of its kind; a young-seeming monster is fine. The rule lives only in the prompt.
- **Heroes are people, not plot.** A writer may address a hero by their brief but never explain the trouble with it (ARC and ACT prompts). "Lore may colour a line, never a quest." Among the scenario writers only the act writer receives lore; the deck-flavour writer also reads it, as colour.
- **Enemy design.**
  - Classify by fiction. Never set `action_type: "spell"` to make a physical hit hurt more: that takes it out of the combat lane and out of Mitigate's reach. `mode: "all"` blasts are deliberately unmitigable, so price them that way.
  - No ability hits for less than the enemy's own Power.
  - The lockdown budget (stun, taunt, silence, hamstring, discard, sap, drain-ult, strip-reach) scales with party size. The owner wants more control pressure, so spend it and spread it across different heroes.
  - Per encounter: at most one resource attack (discard, silence or sap), one poisoner, one infect creature, one counter piece and one gauge-punisher.

## 10. Variety and known attractors

- **Floors in code.** Each layout needs size+1 distinct designs, no more than 3 clones and at least 2 × size bodies. Bosses need `enrage_round` and `neglect`; races need guards. The shipped content does not set the bar: the older clone-horde content fails these gates on purpose.
- **The code rolls the variety.** `_signature_rolls` samples `SIGNATURE_POOL`, two per encounter and one per adventure phase. Without it, models converge on the same healer, clock and ticking-channel kit.
- **The steer covers only the library.** Encounters and adventures receive `_library_lines` and `_recurring_motifs`, which leave out run-only adventures. No other writer receives an avoid-list.
- **Attractors that span vendors.** With no names in the prompt, different models re-invent the same things:
  - NPCs: "Hedda Stromm" and a smith named Hedda, "Pip", a retired boatman "Tobiah Rell"/"Tobin Rale", a "Seven Lamps" chapel, an artificer named "Quill";
  - villains named Rook; a mole-outrider;
  - bosses: the ledger or contract necromancer, and an iron Bosun who punishes ultimates in phase 2.

  Regenerating does not diversify the output, and Gemini is near-deterministic. The recommended fix is an avoid-list of existing NPC names, villains and towns in the arc and town prompts. It has not been built.
- **Name collisions overwrite.** `save_encounter`, `save_adventure` and `save_town` key files by the slug of the name, with no collision check.
- **Validator blind spots.**
  - The `defeated_once` branch is only asked for in the prompt, although `validate_materialization`'s docstring claims it is checked.
  - Lines written for NPCs who are not present (for example, cast members absent from an act) are dropped silently.
  - Duplicate JSON keys pass.
  - The sameness gate catches identical kits but not identical reactions across different kits, such as every enemy carrying an `on_incoming_lethal` save.
  - The lockdown budget and the one-per-encounter caps go unchecked.
  - Quest themes are compared as exact strings, so two paraphrases of the same dungeon pass.

## 11. Art and animation

| Subject | Prompt | Aspect (ComfyUI pixels) | Stored in | Queue key |
|---|---|---|---|---|
| Encounter backdrop | `scene_prompt`: style + `_SCENE_TASK` + `scene` | 16:9 (1792×1024) | `content/art/<encounter_id>/scene-*` | `encounter:<id>`, `adventure:<id>` |
| Enemy or token | `enemy_prompt`: style + `_ENEMY_TASK` + description + types/classes line + a scene hint | `enemy` → 1:1 (768×768) | `content/art/<encounter_id>/<pool id>-*`; clones share the base design's image | same |
| Town map, exteriors, interiors | `_TOWN_TASK`, `_EXTERIOR_TASK` (with town context), `_INTERIOR_TASK` | 16:9 | `content/art/towns/<town_id>/` | `town:<id>` |
| Town NPC | `_NPC_TASK` + `portrait_desc` | 1:1 (1024²) | same | same |
| Arc cast and places | `_NPC_TASK`, `_INTERIOR_TASK`, `_EXTERIOR_TASK` | 1:1, 16:9 | `loadouts/art/cast/<key>/`, `loadouts/art/places/<key>/<int\|ext>/`, content-addressed by `_cast_key` (id + prose hash) | `cast:<run>:<scenario>` |
| Catalogue items | `_ITEM_TASK` + name + `art_desc` | `item` → 3:2 (960×640) | `content/art/items/<item_id>/` | `items` |
| Forged spoils | same | same | `loadouts/art/spoils/<item_id>/` | `spoils:<run>:<scenario>:<act>` |

- **Serving.** `/art/…` serves `content/art` first, then `loadouts/art` (run data and pre-split legacy art). Every write carries a random token, so a regenerated image gets a new URL. Hero portraits are player uploads, not generated.
- **`art.ArtQueue`** runs one sequential job per key, one image in flight. Enqueueing is idempotent and re-checked at execution; a failure is logged and skipped; state lives in memory only. It is fed by the *Generate all art* buttons and by an adventure job reaching `ready`. Spoils and cast art also queue at run start, after each materialization, after Continue, and on every client connect.
- **Style.** Each prompt is `_style()` (`settings["art_style"]`, defaulting to `DEFAULT_ART_STYLE`, a romantic dark-fantasy chiaroscuro), then task framing, then the content's prose. The town, exterior and interior framings add "classic high fantasy" and warm light.
- **Backends.** OpenRouter sends `image_config.aspect_ratio` (via `OPENROUTER_ASPECTS`), retries once without it on HTTP 400, and times out at 180 s. ComfyUI needs an API-format workflow containing `%prompt%` (`%width%`, `%height%`, `%seed%` optional), uses `COMFY_SIZES`, and times out at 300 s.

**Panel animations** (Update 16) are made offline; no LTG code calls a video model.
- **Production and storage.** MiniMax H3 image-to-video in ComfyUI (`minimax_h3_fl2va_pruned_int8_convrot`): 9:16 at 768×1344, 5 s at 24 fps, VP9 WebM with no audio. Clips are uploaded through the Deckbuilder's Animations modal to `apps/deckbuilder/loadouts/anim/<char>/` (gitignored; `content/anim/` is the tracked fallback) and served at `/anim/…`.
- **Wiring.** `Character.animations` holds the clips (`PanelAnimation`: `trigger`, `alternate`, `speed`, `duration_s`, `impact_s`). Picks live on `Card.animation`, `StanceReplacement.animation`, and per trigger on `Card.trigger_animations {trigger_key: anim_id}`. Keys come from `ltg_core.schema.trigger_key()` (`channel_start`, `upkeep`, `channel_break`, `capacity_increase`, `<event>:<who>`, `after_turns`), and `trigger_key_label()` labels them. `content.panel_anim_bundle` ships `{animations, cards, stances, triggers}`. A trigger with no clip stays static.
- **The H3 prompting rule.** Prompt **bold** motion (whips, lunges, erupts, slams) and a dynamic camera. Never stack stillness constraints ("static camera, locked framing, subtle, holds nearly still"): they produce a statue. First- and last-frame conditioning (FL2V), with the panel PNG as both keyframes, handles the pose return; `death` is the exception and holds its own final frame. Write one continuous shot with no cuts, as a bracketed timeline with identity anchors, and end on a single beat: "returns to the pose and framing of the opening frame". Retime before upload; never cut.
- **Where the prompts live.** The approved set is [panel_animation_prompts.md](panel_animation_prompts.md) (Lasarre). [panel_animation_prompt_guide.md](panel_animation_prompt_guide.md) is the brief to hand an LLM, with a portrait and a loadout, to write a set for any character. The guide does not yet document the `revive` trigger (roadmap M0.5).

## 12. Adding or changing a writer

1. Write a pure `*_prompt()` builder for the user turn, as `town_prompt`, `arc_prompt`, `act_prompt` and `interlude_prompt` are. Tests pin prompts without calling a model (`tests/test_design_update_24_layers.py`, `tests/test_design_update_24_worldbook.py`, `tests/test_llm_freshness.py`). If the writer produces people talking, put `%TONE%`/`%CONCRETE%`/`%VOICE%` in the system prompt.
2. Call `_scenario_chat(system, user, attempts, fix, what, task=…)`. `fix(raw)` either returns the cleaned value or raises `ValueError` with a message that can guide a repair: say what to change, in the prompt's own vocabulary, and collect every problem rather than stopping at the first.
3. Put the validator in `scenario_content.py`, or in `world.py` for worldbook data. Any structural rule (acyclicity, reachability, coverage) must be a check, not prose alone.
4. Choose a model task: reuse one, or add `{id, label}` to `MODEL_TASKS`. Any path outside `_scenario_chat` must set `max_tokens` and a timeout that covers it (`tests/test_llm_output_budget.py`).
5. Decide what the writer reads using the reader matrix (§D24-7.6), and update that matrix. Hide `_` flags, and give lore to no writer other than the act writer.
6. If the writer runs in play:
   - give it a job runner in `jobs.py` whose state is persisted to `run.json`;
   - freeze its result into the run's content store before anything uses it;
   - resume it on load in `app._open_save`;
   - keep the model call outside the session lock;
   - give the client a way to show it failed and to retry.
7. Tests: prompt pins, validator accept/reject cases, and swappable generators (`ScenarioRun.materializer` / `arc_generator` / `interlude_generator` / `town_generator`, the jobs' `generator`/`runner`). Tests never make a live model call.
8. Judge real outputs with the validator, and record cost, latency and failure rate for each model.
