# Langelier Tactical Game (LTG) — Design Update 17: Scenario Mode — Towns, Acts, Gear, and the Campaign Save

**Status:** canonical design, **not yet built**. Where this document and prior documents (GDD, Updates 01–16) disagree, this document wins. Everything through Update 16 is implemented and assumed: three-fight adventures with carry-over and level-ups (10), objectives and the autoplay harness (12/13), live movement (15), panel animations (16).

**Purpose.** The campaign layer. A **Scenario** is a multi-adventure story run from a **Town**: talk to NPCs, take a quest, shop, rest, ride out on an adventure, return, and repeat — with **persistent progression** (levels toward 20, gold, gear), **branching saves** where nothing generated is ever lost, and generation timed so the party's shopping is the loading screen. It ships in phases (§D17-9), and it is deliberately larger than any prior update: the sections are ordered so a coding agent can build them in sequence.

**All magnitudes are playtest starting values**, collected in the Rebalance Register deltas (§D17-11).

---

## D17-0. Vocabulary — the ladder, and a rename

Two words swap meaning relative to Update 10. From this document forward:

| level | word | means |
|---|---|---|
| 1 | **Round** | one combat turn cycle (Upkeep → Intents → … → End Step) |
| 2 | **Encounter** | one fight, start to victory/defeat |
| 3 | **Phase** *(was "act")* | one of the three fights inside an adventure — Phase I gate, Phase II courtyard, Phase III throne room; level-ups happen between phases |
| 4 | **Adventure** | a three-phase run through one place; one generation call; HP carries across its phases; no town in between |
| 5 | **Act** *(new meaning)* | one **town visit + one adventure** — the story beat of a scenario ("Act II: The Siege of Hollowmere") |
| 6 | **Scenario** | a campaign: an **arc** of three acts against one villain, run from one town |
| 7 | **Everquest** | scenarios chained on one save; a new arc generates when the last completes |

**Rename errata (Update 10):** every "act" in Design Update 10, the player guide, and game-ui strings becomes "phase" (Phase I/II/III, "Phase I — clear," `phase` fields); the vocabulary word *act* is reserved for the scenario layer. The engine never used the word; this is docs, server field names, and UI copy. Do the rename **first**, as its own commit, before any Scenario work.

The party **returns to town only between adventures** — never between phases. Finishing an adventure's Phase III boss ends the act; arriving back in town begins the next act, and is a generation point (§D17-6).

---

## D17-1. What a scenario is

A **scenario** = a **town** + an **arc** (villain, stakes, three act outlines) + **three acts** played in order. It is started from a **run** (§D17-7) with fixed options:

- **Party** — fixed at scenario start; make a new run for a different party.
- **Difficulty** — easy / standard / hard, applied to every generated adventure.
- **Normal / Hardcore** — on adventure defeat: Normal returns the party to town with the quest unadvanced (narrative adjustment via flags, §D17-5.4); **Hardcore ends the run**.
- **Standard / Everquest** — Standard ends after Act III's adventure; **Everquest** generates a new arc from the same town when an arc completes, and continues indefinitely (levels and gear carry). Hardcore + Everquest is allowed — permadeath endless.
- **Content** — a **pre-generated scenario** (town + title, Act I already materialized) or **Town + New** (generate an arc for that town at start).

**Progression is persistent within the run** (levels, gold, gear, consumables, flags) and **never touches the saved character profile** — the Deckbuilder stays creation-only.

The combat engine is untouched by all of this except gear's stat-block composition (§D17-4.2) and consumables-as-cards (§D17-4.4), both applied at encounter setup. Everything else is session layer, content pipeline, and UI.

---

## D17-2. Progression: two levers

### D17-2.1 Earning — level derived from cumulative points

The earning rate stays **+30 points per phase level-up** (T-57, unchanged). What changes: **character level is derived from cumulative earned points** against an escalating threshold table, instead of +1 per level-up.

Cumulative points to reach level *L* (T-78, playtest starting values, shaped to the agreed milestones — ≈level 3 after adventure 1, 5 after 2, 6 after 3, 7 after 5, thinning toward 20):

| L | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pts | 30 | 60 | 105 | 150 | 210 | 300 | 390 | 480 | 570 | 690 | 810 | 930 | 1050 | 1200 | 1350 | 1500 | 1650 | 1830 | 2010 |

(Each adventure earns 60: two level-ups. Adventure 1 → 60 → L3; adventure 2 → 120 → L5; adventure 3 → 180 → L5 (L6 at 210, early in adventure 4); adventure 5 → 300 → L7. Beyond L10 each level costs a full adventure or more.)

Consequences: the **level-up screen still appears after every phase** (30 fresh points, banking as built), but the level number on it may not tick; **enemy budgets read the derived level** (adventure phases budget at level, level+1, level+2 as today's "level N per phase" pattern, now anchored on the derived level at adventure start); the **Power cap** (T-60, `2 × level`) reads the derived level. `Character.level` is written to the run's copy of the character, never the profile.

### D17-2.2 Spending — the escalating price curve

The flat price table (Update 05, T-1x) is replaced by **escalating per-stat prices**: the *n*th purchase of a stat costs more than the (*n*−1)th. Creation (the first 70 points) uses the **same curve** — a fresh character is simply the first few steps of it. **The four archetype presets are removed** (Deckbuilder and level-up screen alike): the points-buy is the only creation path. Fighter/Tactician/Caster/Channeler survive only as *descriptive* words in docs and the player guide (§XV's reference builds become worked examples on the new curve, not selectable presets). Existing saved loadouts are **revalidated on load** against the curve; one that now over-spends is flagged in the picker with its overage (advisory, non-blocking, exactly like deck status) so its owner can trim it in the Deckbuilder.

Prices for the *n*th purchase (T-79):

| stat | 1st | 2nd | 3rd | 4th | 5th | 6th+ |
|---|---|---|---|---|---|---|
| +1 mana capacity | 15 | 15 | 20 | 25 | 30 | +5 each |
| +1 starting card | 15 | 15 | 20 | 25 | 30 | +5 each |
| +1 Power | 10 | 10 | 15 | 20 | 25 | +5 each |
| +2 HP (a pair) | 5 | 5 | 5 | 5 | 6 | 6, 7, 7, 8, 8, … (+1 per two) |
| keyword (one, ever) | creation price list, unchanged | | | | | |

**Mandatory validation before this ships:** the harness's spend audit already shows the flat table penalizing support kits (balanced 33% vs greedy-power 67%). The curve is a playtest starting value; **run the autoplay tester's spend audit and the four spend plans across levels 1–9 under the frozen `greedy-1.4.0` stick and adjust T-79 until no single spend plan dominates by more than the T-74 band.** This is Phase 0 work (§D17-9) and gates persistent leveling.

---

## D17-3. Runs, saves, and the content store

### D17-3.1 The save tree

Saves are a **branching history per run**, not slots. Nothing generated is ever discarded.

- **Run** — the top-level object: party (ids + portraits), start date, latest-save date, immutable options (difficulty, Normal/Hardcore, Standard/Everquest), scenario reference. The **Load Game** menu lists runs.
- **Save** — a row under a run: timestamp + **progression label** (`Hollowmere · Scenario 1 · Act II · Town — the Inn` / `… · Act II · Adventure, Phase 3`). Selecting a run lists its saves oldest → newest, each **loadable** and **deletable** (delete is confirmed).
- **Forking:** loading an older save and continuing appends new rows with new timestamps; two saves at the same progression on different dates are two branches. Uniqueness is (progression, timestamp). No automatic pruning, ever.

### D17-3.2 Save points

| when | kind |
|---|---|
| each phase boundary inside an adventure (after level-ups confirm), and adventure start/end | auto |
| **Quest Accept** (§D17-6.3) — the moment the next adventure is generated | auto |
| the inn — talking to the innkeeper | manual (rest + restore + save); "Save Game" is also always available in town |
| mid-combat | **never** — deferred |

### D17-3.3 The content store — why saves stay cheap and forks stay honest

The one rule that makes the tree work: **saves reference generated content; they never regenerate it.**

```
saves/<run_id>/
  run.json                       # party, options, dates, schema_version
  content/<content_hash>.json    # immutable: arcs, act materializations, adventures
  content/art/<id>/…             # immutable: generated images (moved from loadouts/art for runs)
  saves/<timestamp>.json         # small snapshots: state + references into content/
```

- Content is **written once, content-addressed, immutable**. A save snapshot holds party state (run copies of the characters with levels/spend, gold, gear, consumables, flags), the current act/phase/location, and hashes of the arc, the current act's materialization, and the current adventure.
- Loading an old save restores the **exact** adventure, dialogue, and art it pointed at. Forks share everything they don't diverge on. Deleting a save deletes only its snapshot; content is never garbage-collected in v1 (it is small; art is the bulk and worth keeping).
- Everything under `saves/` is **runtime data**: gitignored, never under `content/` (per the distribution rule), **schema-versioned and self-contained** — a save must load after content or schema changes elsewhere, and a run must be transportable as its directory.

Server-side: `RunManager` owns runs and saves; loading a save rebuilds a `Session` in the right mode (town / adventure) from the snapshot; any client can open a run and claim seats.

---

## D17-4. Gear and consumables

### D17-4.1 Slots and rules

Each character has **three gear slots** — **primary weapon**, **secondary weapon**, **accessory** — a **consumable belt of 3**, and an **inventory** of **3 unequipped gear + 3 unequipped consumables** (T-80). Beyond that, discard or sell.

- **Primary weapon** sets the character's **attack mode** (melee or ranged — it may grant a mode the build didn't buy) and applies its **power bonus**. Its other effects apply too.
- **Secondary weapon** applies **only** its non-mode, non-power effects (keyword, granted ability, stat riders). Attack mode and power come from the primary alone.
- **Accessory** applies its effects. Any item type may carry keywords, stat riders, or a granted ability.
- **Swapping** happens on the **character sheet only** — in town, or on the between-phase character-sheet/level-up screen. Never mid-encounter.
- **Keywords via gear:** the creation-banned keywords (protection, hexproof, indestructible, deathtouch, infect) **arrive here** — as rare finds and boss drops, never in merchant stock. The one-keyword-ever creation rule is unaffected: gear keywords are worn, not bought.
- **Gear is worn by the run copy of the character**; the profile never sees it.

### D17-4.2 What an item is

```
item = { id, name, slot: "weapon" | "accessory" | "consumable",
         rarity: common | uncommon | rare | mythic,
         level_min, points_price,               # points_price is the balance handle
         flavor,                                  # ONE line
         art_desc, art_url?,
         effects: [ … ],                          # see below
         consumable?: { timing: "instant" | "sorcery" } }
```

Gear `effects` use the **existing effect vocabulary** for granted abilities plus three item-only statics: `attack_mode` (weapons), `power_bonus` (weapons), `keyword` (a single grant, permanent while worn), and `stat` riders (`hp`, `mana`, `cards` — flat adds, folded into the stat block). Composition: at encounter setup, `compose_spec` folds worn gear into the character's **stat block** and keyword list, exactly as a level-up would; a granted ability rides the existing skill/stance-ability machinery as an extra `stance_ability`-style slot named for the item. **The engine sees a stat block, as it always has.**

**Pricing:** `points_price` is on the **same scale as level-up points** (a +1 Power sword prices like the +1 Power purchase, plus a scarcity premium for rarity/keywords), so gold — which is XP-shaped (§D17-5.3) — prices gear directly, and encounter budgeting can read **effective level = derived level + worn points ÷ 30** (rounded down) (T-81). Reads at adventure start.

### D17-4.3 The base catalogue and the procedural vocabulary

**Options → Equipment** manages a **hand-curated base catalogue** — the balance floor, probeable by the autoplay tester like cards. Ship v1 with (T-82): 6 weapons (melee/ranged × plain / +1 Power / +1 Power + a soft keyword such as reach or trample), 4 accessories (+4 HP, +1 mana, +1 card, a granted minor ability), and 6 consumables (heal 5 sorcery · heal 3 instant · prevent next combat damage instant · +2/+2 pump instant · cure poison instant · strip intent sorcery). All `points_price`d, all with flavor and art_desc.

**Procedural gear** = **template × affix**: templates are catalogue entries; affix tables carry mechanical riders (a keyword, a stat, a small granted ability) each with a points cost and a level_min. Generation picks mechanics from tables **in code**; the LLM only **names, flavors, and describes** the result. Nothing generated is ever off-vocabulary or off-budget. Boss drops roll higher rarity and may roll banned-keyword affixes; merchant stock rolls common/uncommon only and **caps below the drop tier for the act's level**.

Equipment tab: full catalogue list; **New** item editor (the card effect editor with the item statics); per-item **Generate art**; **Generate all missing** (the sequential art queue, reused).

### D17-4.4 Consumables in combat — always-in-hand cards

A carried consumable is a **card in hand from turn 1** of every encounter, above the drawn opening hand, until used or the encounter ends unused (it stays on the belt).

- **No mana cost.** Speed per item (`instant` or `sorcery`).
- On the stack it is an **activated ability** — a spell-counter cannot stop you drinking; a broad ability/action counter can.
- Effects use the card vocabulary verbatim; the card renders with the item's art and flavor.
- **Never sharable mid-encounter**; trading is town-only (§D17-5.3).
- Setup: `compose_spec` prepends consumables to the character's opening hand as cards flagged `consumable_id`; a resolved consumable is removed from the belt in the run state at encounter end (or immediately in the session; the save is at boundaries anyway).

### D17-4.5 Rewards — after Phase III

When an adventure's Phase III boss falls, **before** the level-up screen: the **Rewards modal**.

- Drops: **(party size + 1) gear** and **(party size × 2) consumables** (T-83), rolled from the procedural tables at the adventure's tier (boss tier — always ≥ merchant tier), each rendered as a card.
- Each item has a **dropdown: a character, or Discard**. Assigning to a character whose inventory/belt would overflow is disallowed by the dropdown (shows "full") — the party swaps or discards to make room. When all are assigned, any player clicks **Accept** → the all-players confirmation, **30s auto-yes** (T-84) → items land → auto-save → level-up screen.
- **Nothing is generated by an LLM here** — flavor names come from the affix tables' name fragments; art for drops is generated lazily by the queue after the fact (placeholder sigil until then).

---

## D17-5. Towns, NPCs, dialogue, and gold

### D17-5.1 Towns — pre-generated stages

**Options → Towns.** A town is standalone content, generated offline (LLM + art queue) or authored, and is the **starting point for many scenarios**:

```
town = { id, name, region_flavor, scene, art_url?,
         locations: [ { id, name, function, scene, art_url?, description,
                        npcs: [ { id, name, role, persona, portrait_desc, art_url? } ] } ] }
```

- **Required functions**, one location each: **inn** (rest / restore / save), **weaponsmith**, **artificer** (accessories), **apothecary** (consumables). Plus **1–3 flavor locations** (tavern, shrine, witch's hut, guard post) that host questgivers and handoff NPCs.
- Each location has 1–2 **resident NPCs** with a role and **persona prose** — but **no dialogue and no inventory**: those are act materializations. The persona prose is **injected verbatim** into every later generation so the innkeeper is the same person across acts and scenarios.
- Town validation: the four functions present, every location has a scene, every NPC has a portrait_desc.

### D17-5.2 The town screen — the battlefield grammar, repurposed

The town reuses the combat screen's shell: backdrop + card slots + inspect modal + a verb button + splash on entry.

- **Entering town:** the splash (town scene + a paragraph from the act's materialization).
- **Town map:** the town scene; the card slots show **locations** (name, art, function badge) instead of enemies. Console: no hand, no mana; action buttons **Save Game · Quest Log · Leave Location · Start Adventure**, greyed unless actionable.
- **Click a location** → inspect modal (description) → **Visit X**.
- **Visiting:** splash (location scene + a line of narrative) → location screen: location scene; the slots show its **NPCs**. Click an NPC → inspect (persona) → **Talk to X** or, for merchants, **See their wares** (§D17-5.5). **Leave Location** returns to the map.
- **Movement is party-wide:** Visit / Leave / Start Adventure open the **all-players confirmation** (every *player*, not character; **30s auto-yes**, initiator may cancel — T-84). Browsing inspects and shopping are per-player and asynchronous.
- **Start Adventure** is enabled only when the act's `adventure_ready` flag is set (§D17-6.3) — otherwise it shows the generation state ("Preparing the road… 4/9").
- **Character sheet:** click a character's name (anywhere — town, combat, level-up) → the sheet modal: stats and build history (locked / new / banked), deck list, Skill/Ultimate, **gear slots + belt + inventory** rendered as cards, gold, level and points-to-next. **Edit affordances (equip/swap/discard/trade) only in town and on the between-phase screens; read-only in combat.**

### D17-5.3 Gold — per character, XP-shaped

Every character earns **gold at the same rate as points: +30 per phase level-up** (T-85), into their **own** wallet; how it is split and spent is per character. Additional gold from selling (50% of `points_price`, T-86) and from quest hooks (`give_gold`). Prices are `points_price` in gold (merchant premium: ×1.25 on stock, T-86). No free restock anywhere — potions are priced, and the party gets no pass for lacking a healer. Trading items and gold between characters is **town-only**, via the character sheet, and needs both players' clicks (a two-party confirm, not the whole table).

### D17-5.4 Dialogue — authored at generation, walked at runtime

Dialogue is written when an act is materialized (§D17-6) and executed deterministically. Live LLM dialogue is **not** in v1; the schema reserves `freeform: true` (unimplemented, rejected by the runtime).

```
dialogue = { root, nodes: { id: { speaker: "npc" | "party", text,
                                 choices: [ { label, next?: id,
                                              requires?: [flag…], effects?: [hook…] } ] } } }
```

- 2–4 nodes deep, 2–3 choices per node; a choice with no `next` ends the conversation.
- **Hooks — a closed vocabulary**, like effect verbs: `set_flag`, `grant_quest`, `advance_quest`, `unlock_adventure` (sets the act's Start-Adventure gate — **write-once per act**), `give_gold`, `give_item`, `rest` (full restore), `open_shop`, `direct_to` (journal points at another NPC/location). Nothing else; the prompt is told so.
- **`requires` reads flags** the hooks set. Flags live in the run state and persist across acts and scenarios; standing flags the runtime sets itself: `defeated_once` (Normal-mode defeat this act — the questgiver's tree carries a "you return bloodied" branch, written up front), `act_<n>_complete`, `quest_accepted`.
- **The dialogue modal:** party portraits **left** — a slightly zoomed 3:4 crop of each character portrait's upper portion, tiled; NPC portrait and text center; choices as ghost buttons. **The initiating player chooses** and advances; everyone sees the same text. Before choosing, the initiator may **click a party portrait to attribute the line to that character** (`speaker: "party"` nodes carry the attributed id) — cosmetic today, the seam for LLM-written party lines later. Choices carrying **party-wide hooks** (`grant_quest`, `unlock_adventure`, `rest`) open the all-players confirmation; flavor choices don't.
- **Quest Accept** is the `grant_quest` + `unlock_adventure` choice; it is **irreversible per act** — its confirmation reads *"Accept ‹quest› as your next quest?"* On yes: hooks fire → auto-save → the adventure generation job starts (§D17-6.3). If a future act offers several quests, accepting one closes the others.

### D17-5.5 Shops (design-later stub)

`open_shop` / **See their wares** opens the shop modal — per-player, asynchronous. Stock is per-location, generated with the act (§D17-6.2), **fixed for the act, refreshed each act**, common/uncommon only, priced ×1.25; sell-back at 50%. The modal's design (card grid, buy/sell, wallet) is a later pass; the data contract is fixed here.

### D17-5.6 Quest log (a panel, not a system)

A read-only panel: the arc's title, the current act's quest (title, text, status), the `direct_to` pointer if any, and completed acts. Sourced entirely from materialization data + flags.

---

## D17-6. Generation — grains and timing

Three grains, three moments; every later call receives the earlier grains **verbatim** for consistency.

### D17-6.1 The arc — once, at scenario start

Input: the town (name, region flavor, locations, NPC personas), the party (size, level, colours), difficulty. Output (one small call): `arc = { title, villain, stakes, acts: [ {title, hook, questgiver_location, questgiver_npc, handoff?, adventure_theme, tone_notes} ×3 ] }`. Pre-generated scenarios ship an arc **plus Act I fully materialized** (town portion, adventure, art) so New Scenario is instant; Acts II–III are always dynamic. Everquest: when Act III's adventure ends, a **new arc** generates for the same town on return (same call, plus a "previous arcs" summary block), and continues.

### D17-6.2 The act's town portion — at act start (arrival in town)

Under the town-entry splash, one fast text call. Input: town + arc + this act's outline + party state (levels, gold, flags incl. `defeated_once`) + the previous act's summary. Output: the **quest** (title, text), **dialogue trees** for the questgiver, the handoff NPC if any, and a line or two of fresh flavor for others; the **arrival paragraph**; the **merchant stock** (rolled in code from tables at the act's tier — the LLM only names/flavors, §D17-4.3). Saved to the content store; referenced by the act.

### D17-6.3 The adventure — on Quest Accept, in the background

The single trigger for everything the adventure needs. On accept: (1) auto-save; (2) fire the **adventure generation** — the existing one-call adventure generator with an added **context block**: `arc_context` (title, villain, this act's outline, tone), `town_context` (name, NPCs it may reference), `quest_context` (the accepted quest) — scoped to the party's **effective level** (§D17-4.2); (3) on **validated save** of the adventure, queue **all its art** (Phase I first — the existing sequential queue). Shopping is the loading screen.

**The job model:** `adventure_job = { state: pending | generated | art_queued | ready | failed, progress n/m, adventure_ref, error? }`, **persisted with the run** and reflected on the greyed **Start Adventure** button. `ready` is reached at **adventure generated** — art is best-effort and continues in the background even after the adventure starts (as the queue already does for later phases). Failure after retries → *"Generation failed — Retry"*; the quest stays accepted; the town never wedges. A reload/restart resumes the job from its saved state.

**Save-consistency rule:** the generated adventure and completed art are written to the content store immediately, so a manual inn save after accepting the quest reloads the *same* adventure — never a re-roll.

### D17-6.4 Defeat and return

**Normal:** on adventure defeat, the party returns to town; the quest is **not** advanced; `defeated_once` is set; the act's town portion is **re-materialized** on arrival with that flag (a fresh, defeat-aware questgiver tree — the narrative adjustment); the same quest is offered again; accepting it **generates a fresh adventure** (levels and gear may have moved; the old adventure stays in the content store). **Hardcore:** the run ends; its saves remain loadable-for-viewing but not continuable (a `dead: true` flag on the run — Load Game shows it struck through).

---

## D17-7. Menus and flows

- **New Game modal** gains a fourth column: **Scenarios** (pre-generated scenarios and Town + New). Choosing it reveals the run options (difficulty · Normal/Hardcore · Standard/Everquest). Start creates a **run** and its first auto-save.
- **Load Game** (top ribbon): runs → saves list → load. Delete on saves; delete on a whole run (double-confirm).
- **Options → Towns** / **Options → Scenarios** / **Options → Equipment**: lists, Generate/New, per-item art + Generate all missing, hide/delete, inspect (a scenario opens its arc; its Act I adventure opens in the existing adventure editor).
- **Between-phase flow** (unchanged from Update 10 apart from the rename and the rewards insert): victory splash → *(Phase III only)* **Rewards modal** → level-up (now with the character sheet's gear tab available for swaps) → narrative splash → next phase. **After Phase III:** rewards → level-up → **return-to-town splash** → the town map (next act begins; town portion generates under the splash).

---

## D17-8. Engine, server & schema touchpoints (for the implementation pass)

| system | where |
|---|---|
| rename act→phase | Update 10 doc, player guide, `adventure.py` field names + WS messages, game-ui strings; own commit |
| level thresholds + price curve | `core/ltg_core/schema.py` — `LEVEL_THRESHOLDS` (T-78), `PRICE_CURVE` (T-79) replacing the flat table; `Character` build validation reads the curve; **presets deleted** (schema, Deckbuilder `app.js`/`index.html` preset row, level-up screen); loadout revalidation lint for over-spend; `adventure.py:price_table/validate_level_up` read the curve; level derived from cumulative points |
| runs & saves | new `apps/game-server/ltg_game_server/runs.py` — `RunManager`, content store (hash-addressed, immutable), snapshot schema (versioned), progression labels; `saves/` gitignored; `session.py` gains town mode + rebuild-from-snapshot |
| items | `schema.py` `Item` + item statics; catalogue in `content/equipment/` (tracked base catalogue) with the Equipment tab writing new items to `loadouts/equipment/`; `compose_spec` folds worn gear into the stat block/keywords and prepends consumables as flagged cards; consumable resolution as an activated ability (`engine.py`, minimal — a card flag) |
| affix tables + drops | `game-server/items.py` — templates × affixes, tiering, boss-drop and merchant-stock rollers, naming fragments; LLM naming/flavor pass in `llm.py` |
| towns / scenarios / arcs / acts | `content.py` registries + validation; `llm.py` — town generator, arc generator, act-materialization generator (dialogue trees with the closed hook set, quest, arrival paragraph, stock naming), adventure context block; `art.py` town/location/NPC/item art + the queue reused |
| dialogue runtime | `game-server/dialogue.py` — tree walker, `requires`/flags, hook executor (closed set), party-wide vs flavor confirmation routing |
| generation jobs | `game-server/jobs.py` — persisted `adventure_job` state machine, resume on load, retry |
| game-ui | town map / location / NPC screens on the battlefield shell; splash reuse; console button set; dialogue modal (portrait strip, attribution, choices); rewards modal; character sheet modal (cards for gear); Load Game; New Game 4th column; Options tabs; shop modal (stub); quest log panel; Start Adventure job state |

**Regression spine:** encounters and adventures started outside a run are byte-identical to today (rename aside); the §A/§C scenarios and the Update 10 adventure flow are the gates; the autoplay smoke slice must pass under the new price curve *and* the tester's spend audit must be re-run (Phase 0) before persistent leveling lands.

---

## D17-9. Build phasing

- **Phase 0 — prerequisites:** the rename; T-78/T-79 tables + preset removal + loadout revalidation lint + spend-audit validation under greedy-1.4.0; run/save/content-store infrastructure with load/fork/delete and Load Game.
- **Phase 1 — the spine:** scenario object, arc + act-materialization + adventure-context generation, the job model, town/location/NPC screens and dialogue runtime + modal, quest log, character sheet, New Game column, Normal/Hardcore + Standard/Everquest, defeat/return. Merchants exist but the **shop modal is a stub** (wares listed read-only) and drops are **not** yet rolled.
- **Phase 2 — the economy:** items schema, catalogue + Equipment tab + item art, affix tables, gear composition and consumables-as-cards, rewards modal, shop modal, selling/trading, effective-level budgeting.
- **Phase 3 — dressing (separate updates):** narrator and voice in town, LLM party lines in the dialogue modal, evolving towns and travel between towns, multiple quests per act.

---

## D17-10. Open questions

- **[OPEN] Effective-level budgeting** (T-81) — the `worn points ÷ 30` heuristic is a starting value; the tester should probe whether a fully-geared party at derived level N plays like N+1.
- **[OPEN] Consumable counters** — a broad ability-counter can stop a potion. If that feels bad in play, an `uncounterable` item flag is a one-line addition.
- **[OPEN] Content-store GC** — never in v1; revisit if `saves/` growth matters.
- **[OPEN] Multiple quests per act; town evolution; inter-town travel** — explicitly Phase 3+; the schemas leave room (write-once `accepted_quest`, town as standalone content).
- **[OPEN] Party-line generation** — the dialogue modal's attribution click and `speaker: "party"` nodes are the seam; the generator is a later update.

---

## D17-11. Rebalance Register deltas *(amends Update 04 §F-10 and successors)*

| ID | value | sets |
|---|---|---|
| T-78 | 30 / 60 / 105 / 150 / 210 / 300 / 390 / 480 / 570 / 690 / 810 / 930 / 1050 / 1200 / 1350 / 1500 / 1650 / 1830 / 2010 | cumulative points to reach levels 2–20 |
| T-79 | mana & cards 15/15/20/25/30 (+5) · Power 10/10/15/20/25 (+5) · HP pair 5/5/5/5/6/6/7/7/8/8… · keyword unchanged | escalating price curve (nth purchase) |
| T-80 | 3 gear + 3 consumable | inventory slots (unequipped) |
| T-81 | derived level + floor(worn points ÷ 30) | effective level for encounter budgeting |
| T-82 | 6 weapons · 4 accessories · 6 consumables | v1 base catalogue size |
| T-83 | (party + 1) gear · (party × 2) consumables | Phase III boss drops |
| T-84 | 30 s → yes | all-players confirmation timeout |
| T-85 | +30 gold per phase level-up, per character | gold earning rate (= points) |
| T-86 | buy ×1.25 · sell ×0.5 of points_price | merchant pricing |

---

## D17-12. Glossary deltas *(amends GDD §13; supersedes Update 10's "act" entries)*

- **Phase** — one of the three fights in an adventure (formerly "act"). **Act** — one town visit plus one adventure; a scenario's story beat. **Scenario** — an arc of three acts from one town. **Everquest** — scenarios chained on one save. **Run** — a party + options + its branching save tree.
- **Arc** — the scenario's generated spine: villain, stakes, three act outlines; passed verbatim to every later generation.
- **Materialization (act)** — the act's generated town portion: quest, dialogue trees, arrival paragraph, merchant stock.
- **Content store** — the run's immutable, hash-addressed store of generated content and art; saves reference it and never regenerate.
- **Quest Accept** — the irreversible per-act dialogue choice that grants the quest, unlocks Start Adventure, auto-saves, and triggers adventure generation + art.
- **Adventure job** — the persisted generation state (`pending → generated → art_queued → ready | failed`) behind the Start Adventure button.
- **Primary / secondary weapon, accessory, belt, inventory** — the gear slots (§D17-4.1). **Consumable** — a belt item that is an always-in-hand, mana-free, activated-ability card in every encounter until used.
- **Effective level** — derived level plus worn-gear points ÷ 30; what encounter budgets read.
- **Hook** — a closed-vocabulary dialogue effect (`set_flag`, `grant_quest`, `advance_quest`, `unlock_adventure`, `give_gold`, `give_item`, `rest`, `open_shop`, `direct_to`).
- **All-players confirmation** — the party-wide yes/no every player answers for movement, quest acceptance, and rewards; 30 s auto-yes.
