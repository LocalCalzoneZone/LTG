# Langelier Tactical Game (LTG) — Design Update 24: Campaigns, the Interlude, and the Worldbook

**Status:** APPROVED 2026-09-06 (design settled with the owner). **IMPLEMENTED 2026-09-06** on branch `game-updates_23_campaign-mode_24` — Parts B, C and D landed in Part E order (Everquest removal → worldbook → campaign record + live identity → character layers → prompts → interlude and continue); the four shipped towns were backfilled into `content/world/`; `apps/game-ui/dist` rebuilt. Supersedes Update 17's "Standard / Everquest" option (§D17-1, §D17-7, the ladder row 7 in §D17-0) and the "inter-town travel" open question in §D17-10. Where this document and any prior document disagree, this document wins.

**Origin.** The 2026-09 review (`reviews/2026-09/04-rpg-aliveness.md`) found the combat core fun and the RPG layer thin: the world forgets, the heroes are a name and a level, and nothing pulls the player into the next session. The owner's diagnosis: what is missing is the drive to keep playing *with a cast*, which needs the characters to be people and the world to carry their history without garbling it across games. This update lays the data foundation for that: the **campaign** as the unit of continuity, the **interlude** as the way a campaign continues, the **worldbook** as the shared geography, and the **character layers** (brief, lore, situation, chronicle) with a fixed rule for who reads what and when. It deliberately does NOT write the voice work (barks, narrator, party lines), the economy retune, or the ledger-driven dialogue gates from brief 4; those follow once this shape exists.

Line numbers in the implementation notes were checked at commit `399b729` and will drift; re-grep the named functions.

---

## Part A — Design (canon)

### §D24-1 The ladder, amended

Update 17 §D17-0 rows 6 and 7 are replaced:

| level | word | means |
|---|---|---|
| 6 | **Scenario** | an **arc** of three acts against one villain, run from one town |
| 7 | **Campaign** | a sequence of scenarios played by **one fixed party** in **one continuity**; between scenarios the party rests in town (the **interlude**) and chooses where the story goes next; scenarios may stay in one town or move between towns |

**Everquest is removed.** There is no Standard/Everquest option. Every scenario game is a campaign of length one until the player continues it. Run options are difficulty and Normal/Hardcore only.

The **worldbook** sits beside the ladder, not on it: one shared book of brief facts about the world's places, read by every campaign and appended to whenever a town is generated.

### §D24-2 Three durable scopes

Everything the RPG layer knows lives in exactly one of three places. The rule that keeps overlapping casts from garbling: **identity sticks to the character, history sticks to the campaign, geography sticks to the world.**

| thing | scope | written by |
|---|---|---|
| brief, lore, default situation, portrait, art, animations | **character** (the loadout file) | the player (Deckbuilder) |
| card list, skill, ultimate, colours, keyword | **character** — read live (§D24-6) | the player (Deckbuilder) |
| points-buy fields (HP, starting mana, starting cards, bought Power), earned/spent points, level, gear, purse, carried HP | **campaign**, per hero (the instanced loadout) | the engine |
| chronicle (deeds, scars, stances) | **campaign**, per hero | the engine |
| current situation, ties to this cast | **campaign**, per hero | the player, between scenarios |
| ledger of scenarios and acts | **campaign** | the engine |
| town state (what changed here, who remembers the party, standing flags) | **campaign** | the engine and the act writer |
| journal, `knows_*`, the current arc and act | **scenario**, inside a campaign | the engine |
| town file (name, region, scene, locations, resident personas, topics) | **world** — content, as today | the town generator |
| worldbook entry (region, one-paragraph gist, neighbours, notable names) | **world** — append-only | the town generator |

Consequences, intended:

- The same hero in two campaigns is one person with two histories that never touch. Bort's brief is the same in both; his chronicle, level and purse are not.
- Continuing a story is staying in one campaign. Playing "some of the same heroes" in a different story is a new campaign with fresh chronicles.
- Two campaigns may visit the same town. They find the same Karzum and the same Poppy (world facts), who remembers different things in each (campaign state).
- Levels stay per campaign. A hero is level 1 in a new campaign. Carrying a party forward is a "continue from campaign X" feature, deferred (§D24-12); the data shape allows it.

### §D24-3 The campaign record

A campaign is the existing **run** (§D17-3), extended. `run.json` grows:

- `kind: "campaign"` (adventure runs stay `"adventure"`).
- `party`: unchanged (ids, names, portraits). **Composition is fixed for the campaign's life.** Drop-in/drop-out heroes are explicitly deferred (§D24-12).
- `state`: `"in_scenario"` | `"interlude"` | `"between"` — derived from the newest save, stored for the Load list.
- `scenario_count`, `current_scenario` (1-based).
- `ledger`: the structured PREVIOUSLY record, one entry per completed scenario (§D24-8.1).
- `towns_visited`: `[town_id]` in order; `current_town_id`.
- `town_state`: `{town_id: {flags: {...}, overrides: {location_id: {description, exterior_scene, interior_scene}}, met: [npc_id], talked: [npc_id]}}` — campaign-scoped memory per town, composed onto the town at arrival exactly as cast/places are (`town_for_act`).
- `heroes`: `{character_id: {situation: str, chronicle: [...]}}` (§D24-7.4, §D24-7.5).
- `hooks`: the last set of proposed hooks with the one chosen (§D24-5), so quitting at the rest screen and continuing tomorrow shows the same three.

The save tree, the content store and the branching rule are unchanged. **Continue always takes the newest save by timestamp**, not the furthest progression: loading an older save and playing on makes a newer save, and continue follows it. That is Update 17's fork rule applied to one button.

### §D24-4 Menus and flows

- **New Game** keeps a **Scenarios** column: a pre-generated scenario, or Town + New. It creates a campaign. The Everquest checkbox is gone.
- **Load Game** lists **campaigns only** (adventure runs are hidden from this list; their saves still exist and still work through the API). Selecting a campaign opens it at its newest save: mid-scenario resumes; interlude resumes in town; between-scenarios opens the rest screen with the stored hooks. An **older saves** disclosure under the campaign row keeps the Update 17 save list for loading an earlier point.
- **After Act III's Phase III:** Rewards modal → level-up (always; the closing-act exemption is gone with Everquest) → the **scenario-end menu**: **New Game** / **Continue Campaign** / **Quit**. The campaign record is saved before the menu regardless of which is pressed, so Quit does not close the door: Load shows the campaign at "victory in Karzum" and opening it runs the continue path.
- **Continue Campaign** requests the interlude (§D24-5). The town loads when it is ready.

### §D24-5 The interlude and the next scenario

The interlude is the town after victory. It is **act-shaped with no quest**: dialogue trees for the cast and residents in the light of what just happened, shops open, payment hooks for NPCs who promised pay, town state updated. Rest is the only exit.

**5.1 One generation call, started at boss death.** When the Act III boss falls, the server queues the **interlude call** on the sequential job queue, before the menu is even shown; by the time gear is assigned it is usually done. The call reads the ledger (all scenarios), the party (briefs, chronicles, situations — §D24-7.6), the current town as this campaign knows it (town state applied), and the worldbook: this town's entry plus its neighbours. It returns, in one JSON:

- `interlude`: `{arrival, dialogues, flavor, topics, town_state_delta, days}` — the same materialization shape the act writer emits, minus `quests`, plus a `town_state_delta` (one or two location overrides tied to the victory) and `days` (how long the party has been back).
- `hooks`: exactly THREE, each `{id, kind: "stay"|"neighbour"|"new", town_id | null, town_seed | null, narration, bridge, days, foreshadow: [{npc_id, ask, reply}]}`.
  - `narration`: 3–5 sentences in the second-person narrator voice of the rest screen ("You spend the next few weeks in Karzum…").
  - `bridge`: the arrival paragraph the arc writer will honour — how the party gets there and what has changed since; for `stay` it is the morning the trouble arrives.
  - `days`: elapsed time the bridge covers; applied to the day counter when chosen.
  - `foreshadow`: 1–2 topic exchanges per hook, merged into the interlude's topics so the player **has already heard** all three hooks in town before the rest screen shows them: a fisherman's sails to the south, a trader's complaint about the shut library, the innkeeper's late daughter.
  - **Placement rule (soft):** at least one hook stays in this town, at least one leaves; the third goes where the ledger points. `neighbour` hooks name a town already in the worldbook. `new` hooks carry a `town_seed`: a name and one line for the town generator, placed relative to a known town.
  - **The planner proposes premises, never outcomes, and never touches hero backstory.** It reads the world and what the party did. Lore is not among its inputs.

**5.2 Load into town.** The interlude materialization is put into the content store and the party arrives (`arrive()` with the interlude as the act). Mode is `"interlude"`. The quest card shows "Between scenarios". A save of kind `interlude` is written.

**5.3 The rest screen.** Choosing the inn's `rest` hook in the interlude opens the **rest screen** instead of healing: the three hooks' narrations as three cards, plus a fourth: **"You decide to [stay in <town>] / [travel to <dropdown: worldbook towns> / somewhere new (name + one line)], but…"** with a free-text note. A **Not yet** control returns to town; nothing is committed until a hook is chosen. Once chosen:

1. `days` apply to the day counter; the interlude rest heals fully as part of the time skip.
2. The journal closes the scenario (the bridge, in "we" voice, is its last entry).
3. If `new`: `generate_town` runs with the seed and the worldbook context (§D24-9.1); the town joins the content library and the worldbook.
4. `generate_arc` runs for the chosen town with the ledger, the chosen hook's `narration` + `bridge` as the premise, the player's note if any, and the party (§D24-9.2). The arc's Act I arrival paragraph must honour the bridge.
5. The scenario counter increments; Act I materializes under the entry splash exactly as a new game does; a save of kind `act_start` is written.

Latency is therefore no worse than a new game: the hooks were made at boss death, and Act I generation is the wait that exists today.

**5.4 Library scenarios and campaigns.** Towns are reusable; arcs are not. A pre-generated library scenario can **start** a campaign, and its town joins the worldbook on first use (§D24-8.3). A continuation may target a library **town** as a neighbour, reusing its residents with a fresh arc. A continuation never loads a library scenario's pregenerated Act I: it was written for a generic party with no ledger.

### §D24-6 Instanced mechanics, live identity

On every **load or continue** of a campaign, each hero's instanced loadout is refreshed from the character file before anything else runs:

- **Replaced from the file:** `cards` (the deck list), skill and ultimate, colours, keyword, `description` and the brief (§D24-7.2), portrait, art and animation references.
- **Kept from the instance:** `hp`, `starting_mana`, `starting_cards`, `power_bought`, `earned_points`, `spent_points`, `level`, gear, consumables, purse, carried HP.

Reconcile: a `starting_cards` entry naming a card no longer in the live deck is dropped and the player told on the load splash ("Bort's opening hand lost *Ember Lash*; it is no longer in his deck."). If the live deck's colours no longer cover an instanced `starting_mana` pip, the pip is re-rolled to a live colour. Level-up validation (`validate_level_up`) continues to lock cards, colours and keyword *during a run*: the refresh happens only at load/continue, so mid-run rules are unchanged.

Why: balance changes are coming, and restarting a campaign is not as cheap as restarting a scenario. A campaign should never be stranded on a stale deck.

### §D24-7 Character layers

A hero has five layers. Each has one author and a size that keeps a new character a ten-minute job, not a novel.

**7.1 Sheet.** As today: the mechanical character. Unchanged by this update.

**7.2 Brief** — player-written, on the loadout, **always visible to every writer**. A `brief` object on `character`:

```
"brief": {
  "concept":    "one line — who this is in the world (≤ 20 words)",
  "appearance": "one sentence",
  "voice":      {"register": "one line — how they speak", "samples": ["…", "…", "…"]},
  "wants":      "one line",
  "wont":       "one line — what they will not do",
  "tell":       "one line — a flaw, habit or tic",
  "ties":       ["one line each — people, factions, places; other heroes by name"]
}
```

Budget: about 150 words. The existing `description` stays as the sheet's one-liner (the picker, the Inspect view); `brief.concept` may default from it. The Deckbuilder gets a **Brief** panel with these seven fields; nothing in it is required, and a hero with no brief plays exactly as today.

**7.3 Lore** — player-written, optional, any length, on disk beside the loadout as a folder of Markdown files: `apps/deckbuilder/loadouts/lore/<character_id>/<slug>.md`, each with front matter:

```
---
title: The Order of the Kettle
keys: [order of the kettle, kettle-priests, brass ring]
gate: ""            # optional: a standing flag / act ≥ n / "met:<npc_id>" / "town:<town_id>"
mode: closed        # closed = canon, may be referenced; open = a seed the game may resolve
---
…any length of prose…
```

**Rules of use.** Lore never generates plot. It colours reaction. An entry reaches a writer only when the world touches it: a `keys` match against the current town's names, personas and topics, the arc's cast and places, or an explicit `gate`; and **at most two entries per act, ≤ 120 words each** (an entry longer than that is truncated to its first paragraph for the writer, never for the player). What the writer may do with it: a line in that hero's voice, a choice only that hero would see (a future update wires the gate), an NPC who recognises a name. The arc writer and the interlude planner **never** receive lore. The enemy designer never receives lore. Given the owner's taste ("I hate it when every quest is tied to my backstory"), `mode: open` exists in the schema but nothing in this update reads it; a later update may let an act writer resolve a seed, with the result written to the chronicle as canon.

Import is a file drop, not a form: copying existing documents into the folder with a few lines of front matter is the whole job.

> **Amendment (2026-09-06, after the first build):** the owner asked for lore to be a **plain text field** rather than a gated folder — `character.lore` on the loadout, pasted into the Deckbuilder's Lore tab, any length. Headings and blank lines split it into entries; keys are **derived** from each paragraph's capitalised names, so the "world touches it" rule and the ≤ 2 / ≤ 120-word budget above still hold with no front matter. The folder loader stays as a fallback (front matter optional). A third field, `character.combat_lore` ("Abilities & Combat" — how the hero fights), feeds the Deckbuilder's *Generate deck flavour* call and, later, fight narration; `gate:` and `mode: open` are unread.

**7.4 Situation** — where this hero stands *right now*, in this campaign. A short paragraph (≤ 80 words), campaign-scoped per hero, **seeded** from `character.brief_situation` (a player-written default on the loadout, e.g. "travelling with Lasarre since the fall of the Kettle house; low on coin, high on grudge") when the hero first joins a campaign, and **editable by the player on the rest screen** between scenarios. This is where ties to *this* cast live, and it is the one place a player gets to steer characterisation between sessions without touching the character file. Read by the act writer and the interlude planner.

**7.5 Chronicle** — engine-written, append-only, campaign-scoped per hero. Entries are `{scenario, act, day, kind, text}` with `kind` in `fell | slew | refused | accepted | spent | bought | met | stance | levelled | scarred`. Sources already exist: `_harvest` (who fell, the boss), `grant_quest` (accepted / refused options), `talk` (met), shop purchases, level-up confirms. Bounded for the writers: **the ten most recent lines plus one summary line per past scenario** (the summary is the ledger entry's one-liner). Unbounded for the player: the full chronicle renders on the character sheet as a **Deeds** tab, grouped by scenario. `stance` entries are reserved for the party-line gates of a later update; the kind exists so the schema does not change when they arrive.

**7.6 Who reads what, and when** — the reader matrix. This is the load-bearing table of the update; every prompt change in §D24-9 follows from it.

| reader | when | brief | lore | situation | chronicle | ledger | town state | worldbook |
|---|---|---|---|---|---|---|---|---|
| **Arc writer** | scenario start / continue | all heroes | — | all heroes | summaries only | all scenarios | this town | this town + neighbours (one line each) |
| **Act writer** | act start | all heroes | ≤ 2 entries, key-matched | all heroes | recent 10 + summaries | all scenarios (PREVIOUSLY block) | this town | this town only |
| **Interlude planner** | Act III boss death | all heroes | — | all heroes | recent 10 + summaries | all scenarios | this town | this town + neighbours |
| **Enemy designer** | quest accept | `concept` only | — | — | — | — | — | — |
| **Town generator** | new town | — | — | — | — | — | — | the region it is placed in + its neighbours |
| **Town dialogue at runtime** | every click | — | — | — | — | — | gates only | — |
| **The player** | always | own | own | own | own, full | full | — | full (Options → World) |

Two budgets fall out of it. With four heroes the act writer's hero material is under a thousand words: four briefs (~600), two lore entries (~240), four situations (~320 max), chronicles (~40 lines). The arc writer and planner get less, never more.

**7.7 Flag hygiene for the writers.** `_`-prefixed bookkeeping flags (`_met_*`, `_offered_*`, `_shop_open`) are never shown to any writer; `knows_*` are scenario-scoped and cleared at scenario end (the ledger carries what was learned as prose).

### §D24-8 The ledger, town state, and the worldbook

**8.1 The ledger** replaces `act_summaries` as the writer's memory. One entry per completed scenario, holding per act: `{act, title, accepted: {id, title}, refused: [{id, title}], adventure, boss, fallen: [hero], defeats: n, met: [npc_id], learned: [knows_* as prose], gold_spent: {location_id: n}, items_bought: [name]}` and per scenario: `{scenario, title, villain, town_id, outcome, days, one_liner}`. It is rendered to the writers as a `# PREVIOUSLY` block, most recent scenario in full, older scenarios as their `one_liner` plus refused quests and fallen heroes (those are what NPCs bring up). `previous_arcs` and `completed_acts` are subsumed. The ledger survives everything: it is on `run.json`, not the scenario snapshot.

**8.2 Town state** is the campaign's memory of a town, composed onto the town at arrival by `town_for_act` in the same pass that merges cast and places: `overrides` replace a location's description and scenes; `flags` join the run flags under a `town:` namespace; `met`/`talked` seed the `_met_*` and `talked_<npc>` flags so a second visit's greetings can differ once the dialogue gates of brief 4 land. The act writer and the interlude planner may each emit a `town_state_delta` of one or two overrides tied to the ledger (the burned waystation stays burned in Act III; the cistern runs again in the next scenario).

**8.3 The worldbook** is new infrastructure, built like towns: a tracked content directory, `content/world/`, holding one JSON per entry plus a `regions.json`. It is **append-only in play** and editable under Options → World.

```
content/world/<town_id>.json
{
  "kind": "world_entry",
  "town_id": "karzum",
  "name": "Karzum",
  "region_id": "kholdrun_reach",
  "gist": "one paragraph — what a traveller knows of this place",
  "notable": ["Poppy, keeper of the Kettle and Anvil", "the Ninth Slag Company's adit"],
  "neighbours": [{"town_id": "nalindor", "how": "three days north by the Greatway"}],
  "added_by": "generate_town | import | scenario:<id>"
}

content/world/regions.json
{"regions": [{"id": "kholdrun_reach", "name": "The Kholdrun Reach",
              "gist": "one paragraph — climate, peoples, what the land is known for"}]}
```

Rules:

- **Every town has an entry.** `generate_town` writes one in the same call (§D24-9.1). The four shipped towns get entries by a one-time backfill (a short LLM call over each town file, reviewed by hand). A town without an entry is a validation warning in Options → Towns, not a crash: the writers simply get no neighbours for it.
- **Neighbours are symmetric** and written on the newer town: a new town names one or two known towns it sits near, and the book adds the reverse edge.
- **A region is named once.** A new town may join an existing region or found one; founding one requires the region's gist in the same call.
- **The book is brief on purpose.** No history, no politics beyond a sentence, no plot. It is what a traveller knows. The act writer gets the current town's entry only; the arc writer and planner add the neighbours' one-liners; the town generator gets the region and the neighbours it is being placed beside. Nobody ever receives the whole book.
- Town state (§D24-8.2) is not in the book. The book says what Karzum is; the campaign says what happened there.

### §D24-9 Prompt adjustments

All writers are the existing generators in `llm.py`; the prompts change, the pipeline shape does not, except for the new planner.

**9.1 Town generator** (`TOWN_INSTRUCTIONS`, `generate_town`): gains a `# WORLD` block: the region it is placed in (or "found a new region, name it") and one line per neighbour it is placed beside. The output contract gains `"world_entry": {region_id | new_region: {id, name, gist}, gist, notable, neighbours: [{town_id, how}]}`; `save_town` writes the town and the book entry in one step. The instruction "the home base for many campaigns" stands and now means it literally.

**9.2 Arc writer** (`ARC_INSTRUCTIONS`, `generate_arc`): the `# PREVIOUS ARCS` block becomes `# PREVIOUSLY` (the ledger, §D24-8.1). New blocks: `# THE PARTY` (each hero's brief, situation and chronicle summaries — §D24-7.6), `# THE WORLD HERE` (this town's entry and its neighbours' one-liners), and on a continuation `# HOW WE GOT HERE` (the chosen hook's narration and bridge; the player's note). Rules added: Act I's arrival paragraph honours the bridge; the villain must be new unless the ledger says one escaped; hero backstory is not a plot source — heroes may be *addressed* by their briefs, never *explained* by them; a neighbour named in the ledger or the world block may be referred to but the arc stays in this town.

**9.3 Act writer** (`ACT_INSTRUCTIONS`, `generate_act`): `# PARTY STATE` grows to `# THE PARTY` with briefs, situations and recent chronicles; `# PREVIOUSLY` is the ledger; `# LORE IN PLAY` carries the ≤ 2 key-matched entries with the rule "colour a line, never a quest"; `Flags set` is filtered per §D24-7.7. The writer may emit `town_state_delta`. One paragraph on voice: when a line is attributed to a hero, write it in that hero's register from the brief. (The trait-gated `requires: ["party:…"]` choice is brief 4 item 4.2 and is not part of this update; the writer is told only to write attributed lines in voice.)

**9.4 Interlude planner** (new: `INTERLUDE_INSTRUCTIONS`, `generate_interlude`): the contract in §D24-5.1. Inputs per the matrix. Its validator (`validate_interlude` in `scenario_content.py`) checks: exactly three hooks; the placement rule; `neighbour` hooks name a worldbook town; `new` hooks carry a seed and a known anchor town; every hook has a bridge and days; foreshadow exchanges name NPCs present in the interlude town; the dialogue portion passes `validate_materialization` with `quests` absent and no `grant_quest` / `unlock_adventure` hooks (payment hooks allowed).

**9.5 Enemy designer** (`party_summary_from_loadouts`): each hero's line gains `brief.concept` only. Nothing else from the layers reaches it; the tactical facts brief 4 item 4.2 asks for are a separate change.

**9.6 The `# THE PARTY` block** is one shared renderer (`_party_block(heroes, depth)`) used by the arc writer, act writer and planner so the four-hero budget is enforced in one place: five lines per hero maximum at `depth="full"`, two lines at `depth="summary"`.

### §D24-10 Time

A `day` counter on the campaign, starting at 1, advanced by the interlude's `days`, by the chosen hook's `days`, and by one per ride-out. Rest remains free of gold in this update (the paid rest is brief 4 item 4.3); the counter exists so the interlude can say "day 41" and the journal can date its entries. NPC `acts` lists do not read it yet.

### §D24-11 Vocabulary

- **Campaign** — the unit of continuity: one party, one sequence of scenarios, one ledger, one set of chronicles.
- **Interlude** — the town after a scenario's victory, before the next scenario is chosen.
- **Hook** — one of the three proposed premises for the next scenario, plus the player's own.
- **Bridge** — the prose that carries the party from one scenario to the next.
- **Brief / Lore / Situation / Chronicle** — the four non-mechanical layers of a character (§D24-7).
- **Worldbook** — the shared, append-only book of what a traveller knows about each town and region.
- **Ledger** — the campaign's structured memory of what happened, per act and per scenario.
- **Everquest** — retired.

### §D24-12 Deferred (explicitly not in this update)

- Drop-in / drop-out party composition; "continue from campaign X" (carrying a party and world state into a new campaign).
- Paid rest and the day-priced inn; the gold sinks (brief 4 item 4.3).
- Negated / once-only dialogue gates, trait-gated party lines, barks, the narrator, morale (brief 4 items 4.1.3, 4.2).
- Reading `mode: open` lore seeds.
- Cross-install sync of characters, campaigns or the worldbook (the brothers' installs).
- A Deckbuilder interview flow that drafts a brief from lore.

---

## Part B — Implementation notes

Server work in `apps/game-server/ltg_game_server/` unless stated. The engine (`apps/combat`) is untouched by this update.

### B.1 Remove Everquest (§D24-1)

- `scenario.py`: `opts` (~106) drops `everquest`; `on_adventure_complete` (~824-850) returns `"next_act"` or `"scenario_complete"` only; `act_ends_on_screen` (~732) returns `True` for the closing act unconditionally (level-up always shows). Keep `begin_next_arc` (~852) but rename to `begin_next_scenario(arc, town, town_id)` and let it change town (§B.4).
- `session.py` `_after_adventure` (~366): delete the `"everquest"` branch; `scenario_complete` enters town with `complete=True` **after** the campaign record is saved (`run_manager.save(kind="scenario_complete")`).
- `app.py`: `RunOptionsBody.everquest` (~51) removed; `_new_arc_sync` / `_new_arc_task` (~228-245) are replaced by the continue path (§B.5).
- Client: `NewGameModal.tsx` (~79, ~130, ~147, ~448-450) drop the checkbox; `LoadGameModal.tsx` (~30) drop the label; `api.ts` (~87, ~124) and `types.ts` (~846) drop the field.
- Tests: `test_design_update_17_scenario.py` `test_standard_ends_after_act_three_and_everquest_rolls_a_new_arc` (~381) and `test_the_closing_act_has_an_end_screen_only_in_everquest` (~614) are rewritten for the campaign flow (§D); `test_design_update_17_runs.py` (~65) option pin.
- Docs: `ltg_player_guide.html` (~895, ~902).

### B.2 The campaign record (§D24-3)

- `runs.py`: `RUN_SCHEMA_VERSION` bump; `create_scenario_run` (~324) writes `kind: "campaign"`, `state`, `scenario_count: 1`, `current_scenario: 1`, `ledger: []`, `towns_visited`, `current_town_id`, `town_state: {}`, `heroes: {cid: {situation, chronicle: []}}` (situation seeded from `character.brief_situation`), `hooks: null`, `day: 1`. `save` (~379) updates `state` from the save kind (`act_start|quest_accept|inn|town|adventure_*` → `in_scenario`; `interlude` → `interlude`; `scenario_complete` → `between`). New save kinds: `scenario_complete`, `interlude`, `hooks_chosen`.
- `progression_label` (~198): `interlude` → `"<Town> · Campaign, between scenarios — the Interlude"`; `scenario_complete` → `"… · Scenario n complete"`.
- `list_runs` (~249): return `kind`, `state`, `scenario_count`, `newest_save_id`; the client filters to `kind == "campaign"`.
- `RunManager.newest_save(run_id)` (new): by `saved_at`, the continue target. `load_scenario_save` (~474) already rebuilds a `ScenarioRun`; it now also hands the run-level `ledger`, `town_state`, `heroes`, `day`, `hooks` to the `ScenarioRun` (new attributes, read-through to the run record: `ScenarioRun.campaign`).
- Migration: an existing run without `kind` loads as `"campaign"` with an empty ledger and `heroes` seeded from its party; nothing else is required (old saves stay loadable — the Update 17 rule).

### B.3 Character layers (§D24-7)

- `core/ltg_core/schema.py` `Character` (~2084): add `brief: Optional[Brief]` (a new model with the seven fields, all optional, `samples` ≤ 3) and `brief_situation: str = ""`. `description` (~2086) unchanged.
- `content.py`: `lore_entries_for(character_id) -> List[LoreEntry]` reading `LOADOUTS_DIR / "lore" / <id> / *.md` (front matter parsed by hand: title, keys, gate, mode; body); `select_lore(entries, town, arc, flags, limit=2, max_words=120)` — key match against the town/arc names, personas, topics and place descriptions (case-insensitive substring), gate check against flags / act index / `met:` / `town:`, most keys matched first, then title order. Unit-tested in isolation.
- `scenario.py`: `party_state()` (~207) grows per member: `brief`, `situation`, `chronicle_recent` (10), `chronicle_summaries`; keep `flags` but filter `_`-prefixed and `knows_*` into a separate `knows` list for the writer (§D24-7.7). `chronicle_add(cid, kind, text)` called from `_harvest` (~787: `fell`, `slew`), `grant_quest` (~570: `accepted`, `refused` for every non-taken option), `talk` (~345: `met` once per NPC), the shop verbs (`bought`, `spent`), `on_level_up_confirm` (`levelled`).
- Deckbuilder (`apps/deckbuilder/ltg_deckbuilder/app.py`, `api_save` ~334, `api_character_model` ~228): the Brief panel and the default-situation field; the Deckbuilder writes `brief` and `brief_situation` onto `character`; a **Lore** tab lists the folder's files (read-only listing with a "reveal folder" path; editing stays in the player's own editor).
- Client: `InspectModal.tsx` / the character sheet gain a **Deeds** tab rendering `chronicle` grouped by scenario; the rest screen (§B.5) carries the situation editor.

### B.4 Live identity on load (§D24-6)

- `runs.py load_scenario_save` (~474): after loadouts are fetched from the content store, call `content.refresh_instance(instanced, live)` for each hero where `live = content.loadout_for(cid)` (skip silently if the character file is gone). `refresh_instance` copies `cards`, skill/ultimate, `colors`, `keyword`, `description`, `brief`, `brief_situation`, portrait/art/anim refs from `live`; keeps the points-buy and progression fields; reconciles `starting_cards` and `starting_mana`; returns a list of notices. Notices ride on the load response and render on the entry splash.
- The same refresh runs on **Continue** before the interlude loads.
- `ScenarioRun.restore` (~1257) accepts the refreshed loadouts unchanged (it already re-syncs levels).
- Test: a live deck with one card removed → the instance drops it from `starting_cards` and the notice names it; level and gear untouched.

### B.5 Interlude and continue (§D24-5)

- `llm.py`: `INTERLUDE_INSTRUCTIONS` + `generate_interlude(town, arc, ledger, party_state, world_ctx, attempts=3)`; `_party_block(members, depth)` shared by `generate_arc`, `generate_act`, `generate_interlude`; `_world_block(entry, neighbours)`.
- `scenario_content.py`: `validate_interlude(raw, town, world)` per §D24-9.4; reuse `validate_materialization` on the dialogue portion with `quests` optional and a hook blacklist.
- `jobs.py`: a job kind `interlude` on the sequential runner, started from `session._after_adventure` the moment `state.result == "victory"` on the closing act (before rewards); result stored on `ScenarioRun.pending_interlude` and in the content store; broadcast a `interlude_ready` flag so the scenario-end menu can show a spinner if the player is faster than the writer.
- `session.py`: `continue_campaign()` — waits on `pending_interlude`, applies `town_state_delta`, sets `sc.mode = "interlude"`, `arrive(interlude_materialization)`, `save_point("interlude")`. `town_verb` (~683): when `sc.mode == "interlude"` and a fired hook is `rest`, do **not** heal; instead set `sc.rest_screen = True` and broadcast. New verbs: `rest_back` (clears it), `choose_hook(index, note, town_choice)`, `set_situation(cid, text)`.
- `app.py`: `_scenario_async` (~184) gains `"interlude"` and `"continue"` kinds; `_continue_sync(session, choice)`: apply days; journal the bridge; `generate_town` if `new` (then `world.append_entry`); `generate_arc(...)` with the hook + note + ledger + world block; `sc.begin_next_scenario(arc, town, town_id)`; `session.materialize_act()`; `save_point("act_start")`. Endpoint `POST /api/runs/{run_id}/continue` opens the newest save and returns a session (the Load Game "open" for a `between`/`interlude` campaign).
- `scenario.py`: `begin_next_scenario(arc, town, town_id)`: write the ledger entry (from `completed_acts`, the quest records and the chronicle), reset act state, swap `base_town`/`town`/`town_id`, clear `knows_*` and `act_n_complete`, bump `scenario_number`, keep `flags` under `town:` for the town left (into `campaign.town_state[old_town_id]`), apply `campaign.town_state[new_town_id]` in `town_for_act`.
- `scenario_content.town_for_act` (~441): accept `town_state: Optional[dict]` and apply `overrides` after cast/places merge.
- Client: `TownScreen.tsx` — the interlude quest card ("Between scenarios"); the **RestScreen** component (three narration cards + the fourth card with a town dropdown fed by `GET /api/world`, a "somewhere new" name + line, and the note; a **Not yet** control; the per-hero situation editor in a drawer); `RunEndScreen` (~770) becomes the scenario-end menu with New Game / Continue Campaign / Quit and the `interlude_ready` spinner; `LoadGameModal.tsx` filters to campaigns, shows `state`, opens the newest save, keeps the old list under a disclosure.

### B.6 The worldbook (§D24-8.3)

- New module `world.py`: `WORLD_DIR = content.CONTENT_DIR / "world"`; `list_entries()`, `entry_for(town_id)`, `neighbours_of(town_id)`, `regions()`, `append_entry(entry)` (adds the reverse neighbour edges; refuses to overwrite an existing entry unless `force`), `validate_entry`.
- `llm.generate_town` (~2830) takes `world_ctx: {region, neighbours, anchor_town_id}` and the seed; `TOWN_INSTRUCTIONS` gains the `# WORLD` block and the `world_entry` output; `sc.save_town` (~283) writes both (the entry via `world.append_entry`).
- Backfill: `scripts/backfill_worldbook.py` — for each town in `content/towns` without an entry, one LLM call that returns only the `world_entry`; write; print for review. Run once, commit the four entries.
- `app.py`: `GET /api/world`, `GET /api/world/{town_id}`, `PUT /api/world/{town_id}` (Options → World editor), `GET /api/world/regions`.
- Client: `OptionsModal.tsx` gains a **World** tab (`ScenarioPanels.tsx` pattern): regions with their towns, each entry editable (gist, notable, neighbours), a warning row for towns without an entry.

### B.7 Prompts (§D24-9)

- `generate_arc` (~2881): replace the roster line and `# PREVIOUS ARCS` with `_party_block(depth="full")`, `_ledger_block(ledger)`, `_world_block(...)`, and `# HOW WE GOT HERE` when a hook is given. Rules text per §D24-9.2.
- `generate_act` (~2905): `# THE PARTY` via `_party_block(depth="full")`; `# PREVIOUSLY` via `_ledger_block`; `# LORE IN PLAY` via `content.select_lore`; the filtered flags line; the `town_state_delta` output (validated: location ids exist; ≤ 2).
- `party_summary_from_loadouts` (~1110): append `concept` to each member.
- `_ledger_block(ledger, current_scenario)`: most recent scenario per act; older scenarios as one-liners plus refused quests and fallen heroes.

---

## Part C — Documents to update

- `README.md`: the ladder table; "Run it" (Load lists campaigns); a "Characters: brief and lore" subsection under "Building a character" (~328) with the lore folder layout and front matter.
- `ltg_game_design_document.md` §2 (architecture: the worldbook as a content store beside towns; the interlude planner as a generation-time writer) and §13 glossary (§D24-11).
- `ltg_design_update_17_scenario_mode.md`: §D17-0 rows 6–7, §D17-1 (options), §D17-7 (menus), §D17-10 (inter-town travel resolved) — pointers to this document.
- `ltg_design_update_20_town_rpg.md` §D20-2: `town_for_act` also composes campaign town state (pointer).
- `ltg_player_guide.html`: the ladder row (~895), the run options paragraph (~902), a short "Continuing a campaign" section (the interlude, the rest screen, the fourth card).
- `reviews/2026-09/04-rpg-aliveness.md`: a pointer at the top: items 4.1.1 (ledger), 4.1.6 (town-state overlay), 4.1.7 (day counter, unpaid), 4.1.8 (flag hygiene) and 4.2.1 (party profile, partial) are delivered by this update; the rest stands.

---

## Part D — Tests (new or extended)

- `tests/test_design_update_24_campaign.py` (new): a scenario game creates a `campaign` run; Act III victory writes `scenario_complete` and the ledger entry; Continue waits on the interlude, enters `interlude` mode with the foreshadow topics askable; `rest` in interlude opens the rest screen and does not heal; `rest_back` returns; `choose_hook(stay)` bumps `scenario_number`, applies days, journals the bridge, keeps level/gear/purse, clears `knows_*`; `choose_hook(neighbour)` swaps the town and applies stored town state on return; `choose_hook(new)` calls the town generator with the seed and appends a worldbook entry with symmetric neighbours; the fourth card's note reaches `generate_arc`; Quit at the menu leaves a `between` campaign that Load opens onto the rest screen with the same hooks; newest-save-wins after loading an older save.
- `tests/test_design_update_24_layers.py` (new): brief validates and round-trips through the Deckbuilder save; `select_lore` picks by key match and gate, caps at two and 120 words, never returns for the arc writer / planner inputs; chronicle entries from `_harvest`, `grant_quest`, `talk`, purchases and level-up; the writer view is bounded to 10 + summaries while the sheet view is full; `_party_block` at both depths stays within its line budget for four heroes; `party_state` hides `_` flags and moves `knows_*` to `knows`.
- `tests/test_design_update_24_live_identity.py` (new): `refresh_instance` replaces the deck and identity fields, keeps progression, reconciles `starting_cards` / `starting_mana` with notices; a missing character file is a no-op.
- `tests/test_design_update_24_worldbook.py` (new): `append_entry` writes reverse edges and refuses silent overwrite; `validate_entry`; a town saved through `save_town` with a `world_entry` lands in both stores; `generate_town` prompt carries the `# WORLD` block (prompt-assembly test, no LLM); backfill is idempotent.
- `test_design_update_17_scenario.py`, `test_design_update_17_runs.py`: the Everquest cases rewritten (§B.1); the save-kind and label pins extended.
- `test_design_update_20_town_rpg.py`: `town_for_act` applies `town_state` overrides after cast/places and stays idempotent.

---

## Part E — Suggested order

1. **§B.1 Everquest removal** with its test rewrites (small, unblocks everything).
2. **§B.6 Worldbook** module, backfill, Options → World, town generator prompt (§B.7 part). Independent of the rest; the planner needs it.
3. **§B.2 Campaign record** + **§B.4 live identity** (the load path; one test file each).
4. **§B.3 Character layers**: schema, Deckbuilder Brief panel, lore loader/selector, chronicle writers, Deeds tab.
5. **§B.7 Prompts**: `_party_block`, `_ledger_block`, `_world_block`; arc and act writers read the layers. Regenerate Karzum Act I with a briefed party and judge it against the current file before moving on.
6. **§B.5 Interlude and continue**: planner + validator, job, session verbs, rest screen, scenario-end menu, Load filter. Playtest: finish Kholdrun, continue, choose each hook kind once.
7. Docs (Part C); rebuild `apps/game-ui/dist` and commit it.

## Touched surfaces

Server: `scenario.py` (options, `on_adventure_complete`, `begin_next_scenario`, `party_state`, chronicle writers, `rest` in interlude, campaign read-through), `session.py` (`_after_adventure`, `continue_campaign`, `town_verb`, new verbs), `app.py` (options body, async kinds, continue endpoint, world endpoints), `runs.py` (record fields, save kinds, labels, newest save, load refresh), `content.py` (lore loader/selector, `refresh_instance`), `scenario_content.py` (`town_for_act` town state, `validate_interlude`, `save_town` + world entry), new `world.py`, `llm.py` (town/arc/act prompts, `_party_block`, `_ledger_block`, `_world_block`, `generate_interlude`, enemy summary concept line), `jobs.py` (interlude job). Schema: `Character.brief`, `Character.brief_situation`. Deckbuilder: Brief panel, Lore tab, default situation. Client: `NewGameModal`, `LoadGameModal`, `TownScreen` (interlude card, RestScreen, scenario-end menu, situation editor), `InspectModal` (Deeds), `OptionsModal` (World tab), `api.ts`, `types.ts`. Content: `content/world/` (new, tracked), the four backfilled entries. Scripts: `scripts/backfill_worldbook.py`. Tests and documents per Parts C and D.
