# Work brief 4 — RPG aliveness: characters and a world that remember

Source: whole-game review of 2026-09-02 (hands-on playtest plus thirteen subsystem code reads; their findings are folded into this brief). Line numbers were checked at commit `1fba7f4`; re-grep before editing.

## Session kickoff (read first)

- The RPG layer: `apps/game-server/ltg_game_server/scenario.py` (`ScenarioRun`: town walk, dialogue, journal, economy, rewards, save/restore), `scenario_content.py` (towns, `town_for_act` composition of cast/places), `dialogue.py` (closed hook vocabulary, trees, `knows_*` gating, `check_flag_consistency`), `adventure.py`, `runs.py`, `loot.py`, `items.py`, and the writers in `llm.py` (`generate_arc`, `generate_act`, `generate_town`, the enemy designer). Design: `ltg_design_update_17_scenario_mode.md` (§D17-5 towns/dialogue, §D17-10 open questions), `ltg_design_update_20_town_rpg.md`.
- Architecture rule: the LLM authors content at generation time; the engine never asks an LLM at runtime; dialogue is closed-vocabulary hook trees walked deterministically. Proposals here add plumbing the generators can exploit, never runtime adjudication.
- Quality bar: the newest scenario (Karzum / "The Relighting of the Kholdrun Deep") is the bar; older files are slated for regeneration. Judge systems, not old JSON.
- Tests: `tests/test_design_update_17_*.py`, `test_design_update_20_town_rpg.py`, `test_dialogue_journal.py`, `test_quest_commitment.py`. Run with `.venv/bin/python -m pytest tests/ -q`; do not run while hosting.

## Item 4.1 — Give the world a memory

### Problem (verified)
- **The next act learns one line.** `act_summaries` is a template naming only the accepted quest and adventure (`scenario.py` ~836-842); `materialize()` passes only `act_summaries[-1]` (~297); `completed_acts` and the previous act's `quests` are never sent to the writer.
- **Refused quests leave no trace.** The ACT prompt promises "the one they refuse stays refused; let an NPC or the next act's dialogue note it" (`llm.py` ~2557-2559), but `grant_quest` (`scenario.py` ~570-586) sets no `refused_<id>` flag and nothing records the refused option's title.
- **NPCs have no memory of the party.** Every `talk()` (~344-365) re-instantiates the tree from root; `visible_choices` (`dialogue.py` ~205-214) supports only positive `requires` (no `!flag`, no `once`, no "seen"); `_met_<npc>` is set (~639-642) but nothing reads it; greetings repeat verbatim (`_flavor_tree` ~430-450), and the journal dedupes only against the immediately previous entry (`add_journal` ~623-631), which is the duplicated Poppy greeting seen in the playtest.
- **Authored trees silence topics.** `talk()` uses `act.dialogues[npc_id]` verbatim; only `_flavor_tree` merges town and act `topics` (~438). In Kholdrun Act I this hides Poppy's, Serel's and Mokk's topics and an authored act topic; the materialization validator (`scenario_content.py` ~876-883) accepts "a tree OR a topic OR a line" and never notices the shadowing.
- **The adventure's outcome is invisible to the town.** `_harvest` (~787-819) pulls builds, gold, HP and burned consumables; who fell, which phase was hardest, the boss's name are not recorded; fallen heroes stand up at the 25% floor (~816-818) with no scar, remark or journal line; `on_adventure_defeat` writes one templated sentence (~882-883); `defeated_once` is popped when the act is won (~831).
- **No time, free rest, no town change.** `rest()` (~617-620) sets every hp to full for free; there is no day counter, weather or hour anywhere in run state (`snapshot()` ~1231-1255); the base town is byte-identical on every visit within an act; only cast/places overlay per act (`town_for_act`).
- **Bookkeeping flags leak into the generator.** `party_state()` returns every flag (~213) and `generate_act` prints them as "Flags set" (`llm.py` ~2889, ~2898) including `_met_*`, `_offered_*`, `_shop_open` (never cleared, ~607-608); `knows_*` survive `begin_next_arc` (~862-863).
- **Everquest continuity is thin:** `previous_arcs` entries are `{title, villain, outcome}` only (~856-857; `llm.py` ~2855-2860); `begin_next_arc` wipes `completed_acts` (~864).
- Inert hooks: `give_item` sets a flag only (~603-604) though `items.get_item` (`items.py` ~153) and `add_item` (~440-475) exist; `open_shop` sets `_shop_open` which nothing reads (shops open by location function, ~1208-1210) yet shipped content emits it; `advance_quest` (~594-596) has no reader.

### What to build
1. **A structured PREVIOUSLY ledger** replacing `act_summaries`: per act, `{accepted: {id,title}, refused: [{id,title}], learned: [knows_*], met: [npc ids], gold_spent: {npc/location: amount}, items_bought: [...], defeats: n, fallen: [hero names], boss: name, phases_hardest: ...}`; pass ALL acts (not just the last) to `generate_act` as a `# PREVIOUSLY` block and the same ledger into `generate_arc`'s previous-arcs block; keep `completed_acts` across arcs under a `scenario_number` key. All the data already exists in `ScenarioRun`; this is plumbing.
2. **Standing flags with meaning:** set `refused_<quest_id>` in `grant_quest` for every non-taken option; `defeated_act_<n>` that survives the act win; `talked_<npc>` set in `talk()`; `fell_<hero>` from `_harvest`. Add them to `STANDING_FLAGS` (`scenario.py` ~46 and `dialogue.py` ~42, currently duplicated: unify) so `check_flag_consistency` accepts gates on them.
3. **Negated and once-only gates:** `requires: ["!knows_x"]` (hide the naive question once answered), `once: true` per choice, and a per-conversation "seen" set; three-line changes in `visible_choices` / `choose`; `check_flag_consistency` accepts the `!` prefix; the ACT prompt gets one paragraph ("second greeting must differ: gate a root variant on `talked_<npc>`").
4. **Merge topics into authored trees:** when an act tree exists, append the NPC's unasked town/act topics as root choices (respecting `MAX_CHOICES`), and make the validator flag a tree that shadows topics.
5. **Journal hygiene:** dedupe `heard` per `(npc_id, node_id)`; "we" voice for the defeat line; journal the adventure's phases, the boss and who fell; mark the entry that closes an act. Client: group entries by act/location (see `TownScreen.tsx` QuestLogPanel ~511-533).
6. **Town-state overlay per act:** let the materialization carry `town_state: {location_id: {description, exterior_scene, interior_scene}}` overrides composed in `town_for_act` exactly like cast/places, so Act III's map shows the burned waystation or the cistern running again; teach the ACT prompt to write one or two per act tied to the ledger.
7. **Time and rest:** a `day` counter on the run (advance on rest and on ride-out); rest costs gold at the inn's tier (see item 4.3); NPC `acts` lists can later read days.
8. **Flag hygiene:** filter `_`-prefixed bookkeeping flags out of what the writer sees; clear `_offered_*` in `arrive()`; namespace `knows_*` per arc or clear on `begin_next_arc`.
9. Finish the hooks: `give_item` → `items.add_item(lo, items.get_item(id))` + journal line; drop or wire `open_shop`; give `advance_quest` a reader (quest card status, item 4.3).

### Acceptance
- Regenerate Karzum Act II after refusing Mokk's quest: an NPC line references the drivers the party left; Poppy's second greeting differs; her topics are askable; the journal has no verbatim repeats.
- Tests: extend `test_design_update_20_town_rpg.py` (negated/once gates, topic merge, ledger contents), `test_dialogue_journal.py` (dedupe), a flag-hygiene test across acts and arcs.

## Item 4.2 — Let NPCs know the heroes, and give everyone a voice

### Problem (verified)
- **Writers do not know the party.** `party_state()` gives the act writer names and levels (`scenario.py` ~207-214); the enemy designer's `party_summary_from_loadouts` (`llm.py` ~1106-1127) exports name, level, colours only, while its own prompt conditions design on facts it cannot know (ranged attackers, channelers, healers, counterspells; ~333-336, ~1295-1303). Loadouts carry `description`, `attack_mode`, keyword, gear, skill/ultimate (`party_block` ships `description` at ~1122). Pre-generated scenarios use `_generic_party` ("the first hero").
- **Attribution is cosmetic.** `speaker: "party"` lines can be attributed to a hero (`dialogue.py` ~184-196; `TownScreen.tsx` attribute buttons) but a choice cannot `require` a character trait and the line is not written in that hero's voice. §D17-5.4 built this as "the seam for LLM-written party lines later"; §D17-9 Phase 3 (narrator, party lines) was never scheduled.
- **Heroes have no voice in combat.** `ability_flavor` gives Attack/Defend/Mitigate a display name and one line (`serialize.py` ~537-560); the engine log for a player action is mechanical (`engine.py` ~2606-2609); `gauge_full` (~6116-6121) carries no authored line; `Card.flavor_text` (schema ~1679) is not in `card_dict` (`serialize.py` ~61-74); hero `description` reaches only the inspect view.
- **Enemies have no voice.** Every shipped enemy has `flavor` and `description`, shown only in the Inspect modal (`InspectModal.tsx` ~342-393); veiled intents are eight generic templates (`serialize._veiled_line` ~295-330); the generation prompt asks for `telegraph` names but no bark set (`llm.py` ~806-812, ~817-903); bosses have no enrage/bloodied/wave lines; no morale or flee.
- **The narrator was never started.** GDD §2 lists it as architecture component 5 ("turns the engine's event log into prose; reads events, never changes them"); `state.py` ~852 documents `Event` as "the narrator's (future) input". Nothing exists.
- Hero `types`/`classes` exist (§D21) but no component `target_rule` or condition reads them, so enemies never react to who the heroes are.

### What to build
1. **Party profile for both writers:** extend `party_state()["members"]` and `party_summary_from_loadouts` with `description`, colours, keyword, `attack_mode`, worn gear names, skill/ultimate names, and run deeds (acts survived, times downed, bosses felled). Five lines per hero in the prompt. Let the enemy designer write "the undead hunt the cleric" with a `target_rule: hero_class:<x>` (brief 1 item 1.3 adds the engine side).
2. **Trait-gated, voiced party lines:** `requires: ["party:<colour>"|"party:<keyword>"|"party:<class>"]` on choices (visible only if a fitting hero is in the party; auto-attributed to that hero); ask the ACT writer for 1-2 such lines per NPC written in that hero's register; cache at materialisation, never live.
3. **Character barks:** optional `on_use` lines in `ability_flavor` (attack, defend, mitigate, skill, ultimate, downed, revived) emitted as a `bark` event by `_do_attack/_do_defend/_do_mitigate/_do_use_*`; the deckbuilder gets a small "Voice" panel next to Animations; the Chronicle renders barks in the hero's tide colour; the panel animations can key off them.
4. **Enemy bark tables:** ask the enemy designer for `barks: {declare_threat, declare_support, bloodied, enrage, death, wave_arrive}` (1-2 lines each, generated from `flavor` + types) and render them in place of the veiled templates (same information contract: category/target/rows unchanged, different words). Boss `enrage_line`, `bloodied_line`, `wave_lines[]`, `escalation_narration` rendered as the FX chip caption (brief 2 item 2.1 stages the beat).
5. **Ship card flavour:** add `flavor_text` to `card_dict`; render it on the enlarged hand card and the Stack hover (brief 2 item 2.2). Ask the in-house card writer for flavour lines.
6. **The narrator (async, non-blocking):** a job on the existing sequential queue (`jobs.py` pattern) that once per round (or per encounter end) sends the round's structured events (`type` + `data`, filtered by the registry from brief 3 item 3.3) plus the party profile and enemy `flavor` to the LLM and returns 2-4 sentences; render as an italic Chronicle interstitial and in the between-phase splash; skip silently when there is no key. Never on the critical path.
7. **Morale:** a `flee` verb (enemy leaves to reserve/exile, counts as defeated, no corpse, no kill credit) and a generation rule "every warband has one coward" gated on `self_hp_pct` + `ally_count`, so fights end in stories.

### Acceptance
- With a red-mage in the party, at least one NPC choice in a regenerated act is visible only to her and reads in her voice.
- A boss enrage shows its authored line on the board; an enemy's declared threat uses its bark, not "X threatens Y".
- Narration appears within a few seconds after a round without delaying any input.

## Item 4.3 — Give gold, rest and loot a job

### Problem (verified)
- **Gold has no sink after Act I.** Income: `STARTING_GOLD = 15` (`scenario.py` ~45), one gold per point (10/20/30 per phase, ~60 per act, `_harvest` ~806-810) plus 50% of `points_price` on every sale. Sinks: shops only; `rest()` (~617-620) is a free full heal, contradicting §D17-5.3 "no free restock". Shops roll at `stock_tier = max(1, tier - 1)` capped at uncommon (`items.py` ~361-379) while spoils forge at `act_tier + 1` with affixes and a rarity bump (~196-203; `loot.py` ~501-568). The tier-2 spoils of the first boss out-class the best shelf a shop ever shows; seven drops per act against six slots force sales. The playtest's Act III party had spent 39 gold of 405 earned.
- **The starting purse cannot buy either Power weapon** (`buy_price(15 pts) = 19 g`, `items.py` ~382-387) and act tiers 1 and 2 draw the same shelf.
- **Drops add numbers, never verbs.** `forge_gear` uses Power steps, stat riders and `AFFIXES` (`loot.py` ~275-280), which has no `ability` kind, so a drop can never grant a card; the seven card-granting catalogue accessories (`items.py` ~219-259, ~289-298) reach the party only through uncommon stock rolls; the two rare catalogue weapons are unreachable in play. Worn points raise effective level → budget → spoils tier (`items.py` ~418-424), a treadmill.
- **Dialogue cannot touch the purse.** Kholdrun's Mokk and Serel promise payment in prose; no shipped tree uses `give_gold`/`give_item`; `give_item` is a flag stub (~603-604); there is no `take_gold` / `requires_gold` hook (`dialogue.py` HOOKS ~35-36), so bribes, tolls, fees and bounties cannot exist as choices.
- **The Quest Log omits the quest.** `quest_log()` (`scenario.py` ~1073-1095) returns `quest {title, text, status}`, `direct_to`, `completed`; `QuestLogPanel` (`TownScreen.tsx` ~483-507) renders the journal, deeds and `direct_to` and never reads `log.quest`; `quest.text` is rendered nowhere (only a 9 px "Quest: title · status" in `SidePanel.tsx` ~94-96).
- **Choices have silent consequences:** when a hook fires (gold, flag, quest, rest) nothing in the dialogue modal acknowledges it (`TownScreen.tsx` ~356-481). Rewards are "a grid of dropdowns" (`Items.tsx` ~334-384); level-ups have no moment (`AdventureFlow.tsx` ~89-116, ~236-255); `accept_rewards` silently drops items when the party is full (~993-996).
- Also: forged names double stems ("Ember-Lit Ember-Brass Tonic", `loot.py` `_name` ~453-474); loot lexicon banks are 4 lines per theme so all three Azure scenarios' spoils read identically (~48-189, ~258, ~378-413); shops are voiceless.

### What to build
1. **Paid rest and a day:** the inn charges by tier (or by act), advances the `day` counter (item 4.1 step 7), and journals it ("We slept at the Kettle and Anvil, day 3"); carried HP now matters; an optional cheaper "rough camp" that heals partially.
2. **Shop tiers with something to want:** `stock_tier = act_tier` (not minus one), a small chance of one rare, the catalogue's card-granting accessories and rare weapons reachable, a distinct shelf per act; raise `STARTING_GOLD` or price the first weapons at 15 so the arrival purchase is a real choice; consider a gold sink per act (repairs, a shrine blessing that grants a consumable, a bounty board).
3. **Drops that change play:** an `ability` affix kind in `AFFIXES` that grants a card (draw from the recipe table `loot.py` ~296-351 and the catalogue accessories), weighted so one drop per act carries a verb; fix `_name` stem doubling by comparing all stems; grow lexicon banks to 8-10 lines per theme and draw a subset.
4. **Purse hooks in dialogue:** `take_gold` (with `requires_gold` visibility), `give_gold` targetable at one hero (the attributed one), `give_item` wired to `items.add_item`, `give_consumable`; teach the ACT prompt bribes/tolls/fees/bounties and "every promise of pay is a hook, not prose"; validate that a tree which mentions payment carries a hook.
5. **Quest card:** a pinned card at the top of the Quest Log (title, text, status chip none/offered/accepted/advanced/complete, `direct_to`), journal below grouped by act; read `advance_quest` into the status.
6. **Consequence toasts** inside the dialogue modal ("+12 gold to Bort", "Quest accepted: …", "You now know of the orc camp", "Rested: day 4"); a per-character "Level N" stamp on level-up confirm; portraits as drop targets in the spoils; journal a dropped-for-space item instead of losing it silently.
7. Shops with voice: one line from the vendor on entering, buying and selling (from the NPC's persona at materialisation).

### Acceptance
- Simulate `roll_stock` / `forge_drops` / `_harvest` offline for three acts: by Act III a 3-hero party has spent at least half its income and can still afford the inn.
- At least one boss drop per act carries a card; a dialogue bribe reduces a purse; the Quest Log shows the quest text and status without opening the journal.
- Tests: extend `tests/test_design_update_17_economy.py` (paid rest, stock tiers, ability affix), `test_design_update_17_towns.py` (purse hooks, quest status), and a client check of the quest card.

## Suggested order
4.1 steps 2-5 and 9 (flags, gates, topics, journal; two days) → 4.3 steps 1, 2, 5 (rest, shelves, quest card; a day) → 4.1 steps 1, 6, 8 (ledger, overlay, hygiene; two days + regeneration) → 4.2 steps 1, 2, 5 (party profile, voiced lines, flavour) → 4.3 steps 3, 4, 6 → 4.2 steps 3, 4, 6, 7.
