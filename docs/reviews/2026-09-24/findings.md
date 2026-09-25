# 2026-09-24 consolidation findings

Discrepancies and unbuilt items the writers of each 2026-09-24 document found while checking the design history against the code at `a2cce25`. The documents themselves ([game_design.md](../../game_design.md) and its companions) follow the **code**. These notes record where the old docs or the code are wrong. The actionable rows are tracked in [../../roadmap.md](../../roadmap.md), mostly M1. **This file is a dated record** and will not be kept up to date.


## GDD v2 §3–§4 (cards, the combat model)

**Discrepancies** (doc says X; code does Y. The canon above follows the code.)

1. **Deck size and rarity.** GDD §4.5, and the brief for this section, say "40-card singleton, caps 2/6/12/20". The code has a minimum of 20 cards and quotas of 1/3/6/10: mythic, rare and uncommon are exact, commons have no cap, and all of it is advisory (`schema.DECK_MINIMUM`, `RARITY_MINIMUMS`, `UNCAPPED_RARITIES`, `deck_status`). §X-1 already recorded this; the v1 GDD was never updated.
2. **Only one Mitigate per stack item (likely bug).** §L-5 says each character struck by a positional swipe may self-Mitigate. `StackItem` has a single `mitigate_by`/`mitigate_for`, and `engine._do_mitigate` overwrites it. `_legal_react` still offers Mitigate to a second character, whose declaration silently replaces the first; the first guard's once-per-round use is spent for nothing. The canon states the code ("the last one declared").
3. **Taunt vs the wall (likely bug).** §R-11 says a taunted hit "lands regardless of the taunter's row". In code, `_choose_enemy_attack` declares a melee swing at a taunter even if it stands behind a grounded body. `_execute_intent` then fizzles any redirectable intent whose target is out of reach ("no path"). If `_recheck_intents` runs first, it moves the swing off the unreachable taunter onto a reachable hero instead. So taunting from behind the wall cancels or deflects melee swings rather than drawing them. Untested: `tests/test_taunt.py` uses only a ranged enemy.
4. **Ally tokens are invisible to enemy aim.** §R-1 and GDD §9.6 treat tokens as ordinary row-holding creatures. In code, enemy intents pick only among heroes and never count ally tokens toward the wall: `_pickable`, `_recheck_intents` and the `_execute_intent` fizzle test all use `_reachable_targets(e, st.living_party())`. The one exception is the basic swing, which can also target controlled units (`_choose_enemy_attack`). Tokens are hit only by ally-side area or row effects (`_creatures_on_side`) and enemy trample carries. The canon §4.1 states this.
5. **PCs fire the death event.** GDD §4.3, §9.6 and §13 say incapacitation triggers no death effects. `engine._after_damage` fires `death` on an incapacitated character, and the schema's `TRIGGER_EVENTS` comment documents it. §D23-7.6 and `test_event_triggers.py::test_on_you_incapacitated_death_rattle` rely on it.
6. **Curve-up colour options.** GDD §4.4 says the colour is chosen from the character's identity (`Character.colors`, 1–3 colours). `scenario.party_entry_from_loadout` and `content.py` set the engine's `identity` to `starting_mana`, and `_distinct_identity` offers only those colours. A character whose starting mana omits one of its colours can never lock that colour. Also, `_r_ramp` and `_r_add_mana` resolve a `choice` colour to `identity[0]`, so the player gets no choice.
7. **Sap and channel reservation overlap rather than stack (likely bug).** `_refreshed_pool` and `_trim_pool_to_capacity` compare the unreserved pool with the sapped capacity, so pool = min(capacity − reserved, capacity − sap). A sap no larger than the reserved mana takes nothing. The docstring says "capacity minus reserved … and minus any live sap". `sap` has no design § (code only, 2026-08-21).
8. **Counter credit double-counts a basic attack (likely bug).** `_denied_value` adds `attack_power + power_bonus` and then `_effects_damage(victim.effects)`. An enemy basic swing carries both, because its `DealDamage.amount` is the same number, so countering it pays about twice the swing. `test_gauge_rework.py` covers only spell components.
9. **Re-check triggers.** §L-3 lists "any death" among the occupancy changes that re-check intents. `_recheck_intents` is called only after a Move resolves, a lunge, a dash, a forced move and enemy moves. A fallen target is instead handled when the intent executes. A melee swing at a downed hero fizzles in `_execute_intent`. An intent whose target has left the board is spoiled into a basic swing (`_intent_spoiled` → `_swing_instead`, §D19-4). A non-melee intent at a downed hero still executes, and lands harmlessly on the body.
10. **Released channel mana.** GDD §8 and the README say it is released "as a stack trigger that can be responded to". `_end_channels` returns it straight to the pool, and only `channel_break` effects use the stack.
11. **Skill timing.** §D8-3.1 and §D8-3.5 say the Skill is instant speed, with timing forced to instant and channeled illegal. The code makes it sorcery or channeled, with instant coerced to sorcery (`schema.Character._heroics_valid`), at active speed and main phase only (`_do_use_skill`). The authority is the §D8-3 "Update 11" amendment note plus §D23-1.
12. **Gauge.** The §D8-3.3 table (a 0–100 bar with flat +2/+1/+5/+25) is replaced by the 2026-08-29 rework, which exists only in code. Two further gaps against §D8-3.3:
    - regen ticks credit no one: `_tick_afflictions_one` calls `_heal` without `source_obj`, and `_place_regen_counters` ignores its `source_id`;
    - mana paid for the Skill earns nothing: `_do_use_skill` has no `_gain_gauge(len(paid))`.
13. **Stale infect gloss.** `schema.KEYWORDS["infect"]["gloss"]` still reads "a −0/−1 per Upkeep until cured", which predates §D22-2.
14. **Amplify is applied after Mitigate.** `_r_deal_damage` applies Mitigate, then `_deal_damage` applies `amplify`. So (h − X) × m is dealt, not h × m − X, and a fully mitigated hit never uses up the tag. This contradicts the `_deal_damage` docstring ("before the target's defences answer it"). The canon's hit order states the code.
15. **§R-13.2 is settled in code but undocumented.** §X-4 calls it still open. `_check_end` runs between resolutions, checks victory before defeat, and clears the stack. §R-13.1 (a PC downed by a wound recovers when the wound expires) is also settled: `_end_step` exempts PCs from the reap it runs before resetting layers.
16. **Auto-pass.** §D8-4.1's drop-channels refinement is superseded: a channel holder is never auto-passed (`auto_pass_action`).
17. **Mitigate display.** `serialize._mitigate_value` lacks the engine's minimum of 1 (§D19-5), so a 0-Power hero is shown "−0" but mitigates 1.
18. **First strike.** §R-12 says it strikes "the creature attacking it" or is used "as a mitigation reaction". In code it is a plain basic attack at any legal target, in any Enemies-step reaction window (`_legal_react`).
19. **Minor.**
    - §E-C says a bounced enemy returns to its "original row"; in code it returns to the row it was bounced from (`_redeploy_bounced`).
    - §D17-4.4 calls a consumable an "activated ability", but `_do_cast` pushes it as kind `"ability"`, so an `activated`-filter counter cannot answer it.
    - §D23-3 says spells are unaffected by the ranged-from-Front ban, but every valuation-targeted enemy component, spells included, aims through `_reachable_targets`. A ranged-mode enemy in Front therefore cannot aim any component at a hero. This is for the §9 writer.
20. **Round-structure wording and README staleness.** GDD §4.2 has no Allies step. §R-4 gives "Upkeep → Draw → Intents → …". The code and turn tracker use Upkeep (engine phases `upkeep`/`capacity`/`draw`/`intents`) → Players → Allies → Enemies → End. README "How the game is played" is stale in several places:
    - it has no Allies step;
    - it says End Step "every pending movement resolves";
    - it says intents "lock their target";
    - it says the Mitigate dash moves your "committed position";
    - it says "enemy cooldowns reset" at Upkeep, but they count by round number.
21. **Deckbuilder import.** The settled rule is that cards are authored in LTG's vocabulary, not translated from MTG. Yet Import Deck still asks for rules text "in Magic: The Gathering oracle wording" and runs the translation pass: see `/api/cards/import-custom`, `apps/deckbuilder/CUSTOM_CARD_SCHEMA.md` and `frontend/index.html`. The Scryfall endpoints remain as well (`/api/scryfall/search`, `/api/cards/add`). The canon says only "rules text is parsed".
22. **Code comment drift (no rule impact).**
    - The `_do_drop_channels` and `_drop_actions` docstrings say only channels from earlier turns are droppable, but `_voluntarily_droppable` returns all channels.
    - The `RESOLVERS` comment cites a `disable` branch that `_apply_static` doesn't have.
    - `prevent_pool` is read by `_deal_damage` but nothing fills it, and `parry_reduce` is never used.
23. **Vocabulary.** The docs say "once per turn", using the §R-4 meaning of "turn" as the whole cycle. The code resets these limits at Upkeep, so the canon says "per round". GDD §4.3's "HP, mana, and hand reset between encounters" is also out of date: an adventure carries HP (floored at 25%, T-59), reshuffles everything into a fresh hand, and keeps 50% of the gauge (§D10-2).

**Not built / unverified**

- **§L-2.2 / §L-6 attack of opportunity:** a Move is reactable, but no enemy trigger reads a `move` item (`_trigger_matches`). Not built.
- **§L-5 several self-Mitigates on one swipe:** not supported (Discrepancy 2).
- **GDD §10 / §R-3 archetype stats and attack profiles:** replaced by the points-buy (§P-1, Update 17). They are descriptive only and left out of the canon.
- **`disable`:** removed (§R-11); it has no handler.
- **Rulings found only in code:** §M-A.7 Combat Abilities, the 2026-08-29 gauge rework, `sap`, and `modify_action` action modifiers (§D19-7 covers only the channeled form). The canon cites them as code rulings.
- **Inferred from code, no test found:**
  - two freeing keywords allow both freed verbs plus one more (`_proactive_open`);
  - a downed character's regen tick can stand it back up (`_tick_afflictions_one`);
  - a last hero downed by a turn-scoped wound means immediate defeat (`_check_end` timing);
  - Discrepancies 3, 4, 7 and 8.
- **Cross-reference numbering:** I assumed the other writers keep the v1 GDD numbering plus the brief's pointers: §5 stack, §6 targeting, §7 keywords, §8 channeling, §9 / §9.5 / §9.6 / §9.7 / §9.9 enemies, §10 characters and build, §11 vocabulary, §12 encounters and adventures (phase carry-over), §12.2 objectives, §13.3 / §13.4 gear and consumables. §10, §12 and §13.x match the §10/§13/§14 writer's draft. The editor should confirm them.


## GDD v2 §5–§8, §11 (stack, targeting, keywords, channeling, verbs)

### Discrepancies (doc says X / code does Y)

1. **Released mana is not a stack event.** GDD §8, README "Channeling" and the brief call it "a stack trigger that can be responded to". `engine._end_channels` returns it straight to the pool ("no stack, no trigger"). Only `channel_break` *effects* stack (`_fire_channel_break`). §8.1 follows the code.
2. **Enemy "bodyguard" `redirect` doesn't work.** The `llm.py` "FIVE VERBS" block teaches a bare `{"kind":"redirect"}` on `on_ally_hit` / `on_targeted` as a bodyguard that takes the blow itself. In `_r_redirect`, an enemy redirector with no `new_target: {mode: self}` turns the item back on its caster. I simulated it: a hero's bolt at an enemy with an `on_targeted` redirect hit the hero for 3. On `on_ally_hit` (post-resolution), `_fire_reaction` returns without firing because the stack is empty. There is no "my charge is targeted" trigger either.
3. **The prompt's `conditional` example fails schema validation.** `{"condition":{"kind":"self_hp_pct","op":"<","value":50}}` uses component-condition vocabulary. `Conditional.condition` accepts only cast_mode, target_property, caster_property, self_hp, enemy_count and spells_cast. Checked with `TypeAdapter(List[Effect])`: rejected (`union_tag_invalid`).
4. **Enemy deathtouch does nothing.** README §Enemies and the llm keyword table price it at L3 / 4, but `_deal_damage` executes only `EnemyState` victims, so an enemy's deathtouch never affects a hero or party token.
5. **Indestructible is weaker than documented.** GDD v1 §7 ("killed only by exile or −X/−X") and the schema gloss both say otherwise. In code, `_r_destroy` and deathtouch execution also kill it, and `_r_lose_life` and the poison tick ignore the 1-HP floor.
6. **Stance replacements do trip on-attack.** §D9-2.3 says they don't. In code, a damaging replacement is a Combat Ability (`_do_stance_ability` → `_announce_combat_ability`, §M-A.7).
7. **Auto-pass.** §D8-4.1 allows it when the only options are pass and drop_channels and the drop would enable nothing. In `auto_pass_action`, a channel holder is never auto-passed, and Delay does not block auto end-turn.
8. **Delay.** README "What a character can do" and GDD v1 §4.6 list it among free reactions usable any time. `_can_delay` offers it only in `_legal_main`: main phase, before any verb, once per round.
9. **The veil leaks through the log.** §D8-1.4 promises players never see intent names. `_recheck_intents` logs `intent_redirect` with `intent.name` (the telegraph, often with numbers), and `snapshot.HIDDEN_LOG_TYPES` hides only `intent_declared`.
10. **`move` docs are stale.** The schema `Move` docstring and §D9-3.1 say it "never invalidates a declared intent" and writes a committed row. `_r_move` runs `_recheck_intents` (Update 15), and there is no committed row any more.
11. **Consumables stack as `ability`.** The schema comment on `Card.consumable_id` says they stack as activated abilities. `_do_cast` pushes kind `ability`, so an `activated` counter misses them. They still fire `spell_cast` event triggers and count toward `spells_cast`.
12. **Ultimate-counter filter.** The brief says Ultimate counters must use filter `ability`. `_check_ultimate_answer_guardrail` accepts `action`, `ability` or `activated`.
13. **Ignored durations.** The schema offers `encounter` on `prevent` and `taunt`, but `_end_step` clears all prevent tags and `taunted_by` every End Step. `remove_keyword`'s duration is unused: `_r_remove_keyword` removes for good.
14. **`*_base_power`.** The `REF_VALUES` comment says it is "before bonuses/counters". `_base_stat` returns `power`, which `_r_counters` has already raised.
15. **`ramp` / `add_mana` colour `choice`.** README implies the player chooses. `_r_ramp` and `_r_add_mana` take the first identity colour without asking.
16. **`spell_cast` events.** They fire only from a hero's `_do_cast`, so a hero channel watching `spell_cast` with `who: enemy` never fires. Separately, `_ref_value`'s comment "Only an enemy holds charge" is stale; heroes hold charge since §D22-1, and the code reads it correctly.
17. **Enemy channel event triggers.** They resolve off the stack (the enemy branch of `_fire_event` calls `_resolve_effect`). A `channel_drop` on an enemy *event* trigger can't find its channel (`component_id` is None), so it does nothing.
18. **Defend.** GDD v1 §5.1 lists it as an active ability; `_do_defend` applies its temp HP immediately, with no stack item.
19. **Intent categories.** §D8-1.2 lists 8; the code has 9, adding **interference** (`serialize._CONTROL_KINDS`).
20. **README staleness.** It still says "The 25 primitives"; the vocabulary is now 40 leaves plus 3 containers. Its keyword table lists `protection` (retired 2026-08-22) and gives enemy protection 4/3. Its line "at most one [enemy reaction] per enemy per window" is true, but only one reaction is pushed per offer: the best across all enemies.
21. **`other_ally` is committed.** The brief says it is uncommitted, but it landed in a2cce25 (2026-09-24 17:26) with its tests (`test_other_ally_*`). The working tree was clean.
22. **Custom-card import still translates MTG text.** `ingest.build_custom_card` runs MTG-worded `effect` text through `translation.translate` (see `apps/deckbuilder/CUSTOM_CARD_SCHEMA.md`). Scryfall routes also remain in the Deckbuilder backend, with no UI. §7 frames the terms as authoring meanings, as the brief asked.
23. **Drop docstrings.** `_do_drop_channels` and `_drop_actions` say only channels "started on an earlier turn" can be dropped. `_voluntarily_droppable` returns every channel (Update 06 ruling).

### Not built / unverified

- **Shroud** appears in GDD v1 §6/§7 and some comments, but is not in `KEYWORDS`.
- **Readable target aliases** (`targeted_ally`, `chosen_ally`, `all_enemies`) are not accepted; only structured descriptors are.
- **Sacrifice.** GDD v1 §7 says "the source loses half its remaining HP". No verb or rule implements this; the only mapping is a channeled card's `channel_break`.
- **Continuous `sap` and `remove_keyword`.** Legal in the schema, but `_apply_static` logs them as unhandled.
- **`relentless`** has no price and isn't taught to generation, so it appears on hand-authored enemies only.
- **Post-resolution reactions (untested reading).** `_do_pass` calls `_offer_reactions` once after a resolution, so each resolution draws at most one post-resolution reaction from the whole enemy side. An AoE that hits three `on_hit` enemies gets one punish.
- **Untested edge.** An untargeted `chosen` effect whose target was bounced or suspended in response still resolves on it. `_resolve_effect` checks `_legal_target` only for targeted effects, and `combatant()` still finds enemies in hand.
- **Edge.** A hero's taunt re-aims *every* declared intent of the enemy, including support heals (`_r_taunt`, `_apply_static`).
- **Dead field.** `prevent_pool` (the old numeric "Parry" reduction) is still read in `_deal_damage`, but nothing ever sets it.
- **Resolved in code, still open in the docs.** For the §R-13 / §X-4 loss-check question: `_check_end` runs on every `_advance` step, declares defeat as soon as no hero stands, and clears the stack.
- **Enemy keyword prices** exist only in the `llm.py` prompt table and are not enforced in code.


## GDD v2 §9, §12 (enemies; encounters, objectives, adventures)

### Discrepancies (doc vs code; the canon above follows the code)

1. **Every boss acts twice from turn 1, Easy included.** The docs say Easy bosses declare one intent until they enrage: the comment on content.py `DOUBLE_INTENT_DIFFICULTIES`, §D19-2, and the prompt's "at Standard and Hard". In code, content.py `build_state_from_loadouts` calls `apply_boss_difficulty(scenario, scenario.get("difficulty") or "standard")`. Neither `encounter_for` nor `scenario_from_detail` carries `difficulty`, so every boss in every real game is stamped `double_intent: True`. In adventures, `AdventureRun._scenario`'s Easy pass stamps nothing, and then the build pass stamps Standard. Verified with a two-line script. The canon states the code behaviour, with a flag. Likely fix: stamp `double_intent: False` on Easy, or pass the difficulty through.
2. **Phase III objectives are refused.** §D23-5, `llm.ADVENTURE_EXTENSION`, `content._validate_adventure` and `_phase_three_objective_problem` all accept three modifier shapes. But `content.save_adventure` raises "Phase III is always the standard boss kill" before those checks run. As a result:
   - Any saved or generated adventure with a Phase III objective is rejected, and generation burns repair attempts on the shape the prompt teaches.
   - Only a later phase edit (`_check_phase_edit`) reaches the shape check.
   - tests/test_boss_pressure.py covers `_validate_adventure` alone. test_design_update_12 `test_adventure_rejects_an_phase_three_objective` still pins the veto, using a survive objective.
3. **Enemy lockdown mostly expires before it bites.**
   - engine `_r_prevent_only` stores no duration, and `_end_step` clears every hero's `prevent_tags`. So a one-shot Silence or Pacify lasts until the End Step, whatever its `duration` says.
   - `this_turn` modifiers and sap also end at the End Step.
   - An enemy taunt on a hero is cleared at the next Upkeep (`_upkeep_draws`).
   - Proactive enemy intents execute after the party's turns, so none of these ever touches the hero's next turn. The prompt's "as a one-shot it lasts the turn" and "never stack it on the same hero two turns running" imply otherwise.
   - A one-shot `prevent attack/cast` on an enemy also neither cancels its declared intent (only a channel-held shield does; see `_apply_static`) nor survives to its next declaration.
4. **Survive: killing everything does not win early.** §D12-1.2 says killing everything early wins. But undeployed reinforcements are reserve bodies, and engine `_check_end` requires `not st.reserve_enemies()`, so the party must wait for them or for the timer.
5. **A ranged enemy in Front loses its whole hero-aimed kit.** §D23-3 says spells are unaffected by the Front rule. In code, enemy component picks go through engine `_pickable` → `_reachable_targets` using the enemy's standing mode, which returns nothing for a ranged body in Front. So every hero-aimed rule is skipped, spell-classed ones included. More generally, `_try_declare_component` skips any rule whose non-`self` target rule finds nobody, even when its verbs are untargeted, such as a `mode: all` blast.
6. **Enrage tokens vs the creator cap.** §D18-2: an Enrage's `create_token` gains n−1 bodies. content `_scale_enrage` does raise `count`, but engine `_create_enemy_tokens` caps living tokens at 2 per creator, so most of the extra bodies never spawn.
7. **Minimum bodies.** §X-5.3 / T-41 calls 2× bodies "a standing property of every encounter, authored or generated". Code checks it only in llm `_check_layouts` and content `_validate_phase` (adventure phases); standalone hand-authored encounters are exempt.
8. **Level pricing is not validated.** §F-6 says "overspending is impossible", and README says Level is "DERIVED … never authored". No code prices an enemy or sums a layout's Levels. `level` is authored and trusted, and `_validate_encounter` requires only a positive integer.
9. **Type and class registries.** §D21 lists 25 types and 22 classes. schema `CREATURE_TYPES` adds `halfling` and `CREATURE_CLASSES` adds `monk` (26 / 23).
10. **`protection` is no longer a keyword.** The §F-5 table and README list protection (min 4 / cost 3) as enemy-eligible. schema `KEYWORDS` retired it on 2026-08-22 (not grantable; authors use the `protection` effect instead), and the prompt's table omits it.
11. **Magnitude schedule.** Update 04 T-20–T-24 and README (L+1, Drain ceil(L/2)+1, ±ceil(L/3), +1/+1, lose_life ceil(L/2)) are superseded by the §D18-2 table in `llm.DEFAULT_INSTRUCTIONS` (L+2 and so on). The same prompt's T-55 block still says "single target = L+1". autoplay-tester `enemy_analysis.LEVERS` also cites the old numbers.
12. **`enrage_round` range.** The prompt and the gate's message both say 3–5, but `llm._boss_pressure_problems` accepts 2–6.
13. **Grudges and target-rule validation.** §D23-6 B.5 says to teach `hero_class:` / `hero_type:` in the prompt; they are absent from llm.py (roadmap M3). Unlike conditions, `target_rule` is not validated at load (scenario `_component_from_dict`), so a typo resolves to nobody and the rule never fires.
14. **Factions.** §F-8, the README "Factions" section and the README enemy object's `faction_id` describe a faction manifest. No faction data exists in code; cohesion is prompt guidance only.
15. **Skirmisher ranged fallback.** §F-2 gives the Skirmisher "melee + ranged fallback", but the generation contract has no field for it. Only a legacy `ranged_intent` template gives an enemy a fallback, and no shipped enemy has one.
16. **Neglect source.** The brief and §D23-5 say "party-sourced". engine `_mark_hurt` marks any HP drop, whatever its source. Neglect is also not boss-only in the engine: `_end_step` applies it to any enemy with `neglect > 0`.
17. **Enemy raises are permanent.** §D9-1.4 gives raises a duration, but enemy-side raises (`_raise_corpse` with source_side enemy) become permanent enemy tokens.
18. **Home row.** §F-2 calls the home row the redeploy row. In code a bounced enemy redeploys on the row it left (`_redeploy_bounced`); `home_row` is used only by reserve deploys and `move_home`.
19. **`post_enrage` on non-bosses.** A state.py comment says the phase gate is "ignored on non-bosses", but `_component_eligible` makes a `post_enrage` rule on a minion never eligible.
20. **A wound into the window does not enrage.** `_r_wound` calls `_after_damage` only at ≤0 effective HP. A wound that drops a boss to ≤25% therefore does not enrage it until the next HP change. Left out of the canon as an edge case.
21. **T-40 is inconsistent inside the docs.** The §X-7 register row says 1.5/2.0/2.5, but §X-5.2 says 1.0/1.2/1.5. Code uses 1.0/1.2/1.5, plus the ×1.2 / ×1.3 stat buff that README's "Encounter budget" omits.
22. **`content.enrage_scale` docstring.** It says lethality covers "the AoE, the token wave". The code applies padding to damage and heals and adds n−1 to the token count, which matches §D18-2's text.
23. **Undocumented code rules, now stated in the canon:**
   - ordinary ally tokens are never single-targeted by enemies and do not form the melee wall (`_choose_enemy_attack` uses heroes plus controlled units; `_pickable` uses heroes only);
   - a token made mid-round acts in that round's Allies step (`_execute_ally` re-picks);
   - a dominated enemy that dies under control leaves no corpse;
   - the register bump never reaches spawned tokens;
   - `turn` / `turn_mod` conditions read the global turn, while the boss dials count from arrival.

### Not built / unverified

- **Not built:** the faction manifest (§F-8). The enemy pricing / Level validator. `temperament` (per-enemy band permutation), which §D23-6 permits but nobody has built. Boss chrome in the UI (enraged, neglect tally, guarded_by) and the objective outcome banner (roadmap M1 2.1-3). Protect-the-NPC and compound objectives (§D12-7, deferred). Enemy barks and boss lines (roadmap M6). Objectives in standalone encounter generation (§D12-7 open).
- **`relentless`:** implemented in the engine, but unpriced (§L-6.2 said "priced at implementation"), not taught to generation, and used by no shipped content.
- **Taught but not gated:**
  - pool size 5–8; layout Level budgets; waves ≤ 1.5× budget; survive 4–6 rounds;
  - the lockdown budget; one-per-encounter pieces (necromancer, gatherer, poisoner, infect, gauge-punisher, counter-piece, resource attack);
  - the forced-mover cap; a channeler at Standard+; a boss on Hard.
- **Shipped content:** none of the 21 shipped bosses carries `enrage_round` or `neglect`, and the only shipped objectives are 8 races (no survive, waves or deadline). The timed-enrage, neglect and deadline paths are exercised only by tests and new generation.
- **Unverified:** the test suite was not run. Client FX were checked only in `fx.ts` departures and `Battlefield.tsx`. `_would_be_lethal` counts only constant, unprevented damage, as its code comment says. The pile-on semantics were read from code, not play.


## GDD v2 §10, §13, §14 (characters; progression and economy; scenario mode and campaigns)

**Pointers assumed.** §3 = cards and deck, §4 = combat model/turn, §7 = keywords, §12 = encounters and adventures (phase carry-over, budget formula, difficulty). Please confirm the numbering. docs/generation.md is referenced for the reader matrix and prompt blocks, and docs/roadmap.md is not referenced.

### Discrepancies (doc says X / code does Y; canon follows the code)

1. **T-78 L2.** The §D17-11 register row reads "30 / 60 / 105 …" (L2 = 30). Code `schema.LEVEL_THRESHOLDS` has L2 = 10, which matches the §D17-2.1 body.
2. **T-79 HP pairs.** The §D17-2.2 table and the §D17-11 register give 5/5/5/5/6/6/7/7…. Code `schema.PRICE_CURVE["hp_step"]` and `stat_price` give 4/4/5/5/6/6, then 7/7/8/8 (+1 every two). That matches the post-audit note in `apps/autoplay-tester/SPEND_AUDIT_UPDATE_17.md`. The classic 20/2/2/+1 build prices at exactly 70 (verified).
3. **T-57.** The Update 10 register has "30 points per level-up". Code `schema.PHASE_GRANTS` = 10/20/30 per phase won. `LEVEL_UP_POINTS = 30` survives only as the T-81 divisor and T-85 unit.
4. **Deck size.** The assignment brief says "40-card deck". Code `schema.DECK_MINIMUM` = 20 (quotas 1 mythic / 3 rare / 6 uncommon / 10 common, commons uncapped; advisory). Every shipped loadout has 20 cards, so the canon says 20.
5. **Banned creation keywords.** Update 05 §P-3 and README list protection/hexproof/indestructible/deathtouch. Code `schema.BANNED_CREATION_KEYWORDS` = hexproof, indestructible, deathtouch, infect. `protection` is a retired keyword (`KEYWORDS`, non-grantable) and is refused as off-list.
6. **README "Building a character"** (~lines 347–392) is stale. It still describes the flat costs, the four presets and "escalating curve designed but not built".
7. **§D24-6 identity list.** The doc replaces cards, skill/ultimate, colours, keyword, description, brief, portrait and art/animation refs. Code `content.IDENTITY_FIELDS` also replaces name, **attack_mode, row**, types, classes, ability_flavor, brief_situation, lore and combat_lore, so attack mode and row follow the file on every load.
   - The keyword is priced in the points-buy but refreshed as identity. A changed keyword silently changes the copy's build cost, with no pool adjustment (`content.refresh_instance`).
8. **§D24-6 starting-cards reconcile.** `starting_cards` is an int, so there is nothing to reconcile.
   - The notice names deck cards lost or gained instead.
   - Off-colour mana pips are re-rolled cyclically through the live colours, not randomly (`content.refresh_instance`).
   - `content.PROGRESSION_FIELDS` is declared but unused: refresh keeps everything that is not an identity field.
9. **§D24-6 / §B.4 "the same refresh runs on Continue".** It runs only on loads (`runs.load_scenario_save`, via `app._open_save`, including `POST /api/runs/{id}/continue`). The in-session **Continue Campaign** button (`session.continue_campaign`) does not refresh identity.
10. **§D24-4 "between-scenarios opens the rest screen with the stored hooks".** Code opens the interlude **town** (`app._open_save` → `session.continue_campaign`) with the same stored hooks. The rest screen then opens from the inn's `rest` hook **or** the console's "The road ahead" button (`session.town_verb` verb `rest_screen`); the doc mentions only the inn.
11. **§D24-5.1 "neighbour hooks name a town already in the worldbook".** `llm.generate_interlude` passes `world_towns` = this town's neighbours plus itself to `scenario_content.validate_interlude`. A proposed neighbour hook must therefore be an actual worldbook **neighbour**. The custom fourth card (`scenario._custom_hook`) accepts any town with a worldbook entry or town file.
12. **§D24-7.3 lore amendment ("gate: and mode: open are unread"; the folder is a fallback).**
    - Code honours `gate:` in folder files (`content._gate_open`: `act>=n`, `met:`, `town:`, or a flag); only `mode` is unread.
    - The folder is read **in addition to** `character.lore`, not only when the field is empty (`content.lore_entries_for`).
    - The ≤ 2 cap applies across the whole party (`content.lore_in_play`).
13. **§D24-7.5 chronicle sources.** The doc lists `spent` among the shop verbs and "level-up confirms". Code writes only accepted, refused, met, fell, slew, bought and levelled. `levelled` is written once at adventure end (`scenario._harvest`, comparing derived levels), not per level-up confirm. `spent`, `stance` and `scarred` are never written.
14. **§D17-5.3 "every character rides into a scenario with 15 gold".** Code sets `STARTING_GOLD` once, in `ScenarioRun.__init__` (per campaign); `begin_next_scenario` adds nothing.
15. **Creation leftovers.** A lone adventure opens the pool with the creation leftover (`AdventureRun.start` banks `points_remaining`). A campaign starts `ScenarioRun.banked` at 0 and overwrites the adventure's pool (`scenario.start_adventure`). A hero built under 70 therefore loses the difference in a campaign (a gap, or a ruling to confirm).
16. **§D17-4.3 "merchant stock caps below the drop tier".** Code stocks at act tier − 1 (`items.roll_stock`) and forges spoils at act tier + 1 (`scenario.spoils_tier`), two tiers apart. Separately, the catalogue claims "common or uncommon" but ships 2 rare weapons (`boar_spear`, `siege_bow`) that stock never rolls.
17. **§D17-6.3 job states** "pending → generated → art_queued → ready". Code `jobs.AdventureJobRunner` goes idle → pending → ready | failed. `generated` and `art_queued` are accepted by `adventure_ready` but never set, and art is queued after `ready`.
18. **§D17-5.1 "inn (rest / restore / save)".** A rest exists only if the act writer gives the innkeeper a tree with a `rest` choice. The ACT prompt asks for one, but `scenario_content.validate_materialization` does not require it, so a normal act can leave the party no way to rest.
19. **§D17-6.4 Hardcore "saves remain loadable-for-viewing".** `runs.load_save` and `load_scenario_save` refuse a dead run. The Load list shows it as "Fallen" with loading disabled.
20. **§D20-2 cast/place art "under content/art/cast/ and content/art/places/".** Code paints under the gitignored `loadouts/art/cast|places/` (`art.SPOILS_ROOT`). The run store's `content/art/` (§D17-3.3) is reserved and unused.
21. **Docstring vs enforcement in `scenario_content`.**
    - `validate_materialization` says the questgiver's tree must carry a `defeated_once` branch; only "has a tree" is enforced (a Normal return re-materializes anyway).
    - `validate_town` says every location needs an exterior scene; only the interior scene is required.
    - Spreading quest options across NPCs requires a `direct_to` per the doc, but that rule is prompt-only.
22. **§D17-5.4 "2–4 deep, 2–3 choices".** `dialogue.validate_dialogue` allows depth ≤ 10 and 1–5 choices; `MAX_TOPICS` = 4 truncates silently.
23. **§D24-8.3 "a new town names one or two neighbours".** `world.validate_entry` allows up to 4 written edges, and reverse edges can grow a list to 6. The gist is capped at 160 words and notable at 6; neither cap is in the doc.
24. **Effective level on the sheet.** `scenario.party_block` reports `effective_level` = derived (spent) level + gear bonus. Budgets and tiers use earned potential + gear bonus (`scenario.effective_level`), so the sheet's "eff." is not what the game budgets against.
25. **Campaign play writes tracked content** (distribution rule: never write runtime data into `content/`).
    - A `new` hook's town lands in `content/towns/` and its entry in `content/world/`, and the reverse edges edit existing tracked entries (`app._continue_sync` → `scenario_content.save_town` → `world.append_entry`).
    - Every quest accept writes the generated adventure and its three phase encounters into tracked `content/` (flagged `run_only`, hidden from lists) via `content._write_content`.
    - Both can collide with the brother's Update (git pull).
26. **`town:` lore gates never open.** `llm.generate_act` passes `town.get("id")` of a composed town whose id was popped, so `town_id` is "".
27. **Interlude foreshadow can be unhearable.** Foreshadow topics are merged into NPC topics, but `scenario.talk` uses an authored tree verbatim without topics. A foreshadowing NPC who also has an authored interlude tree never offers the foreshadow ask.
28. **Minor UI/server splits.**
    - `set_situation` is accepted anywhere in town (`session.town_verb`), not only on the rest screen.
    - Start Adventure is disabled at a location by the client only; the server allows it.
    - The buy price uses Python `round` (half-to-even).
29. **Lone adventure runs.** New Game → Adventure "as a run" saves (`kind: adventure`), but `LoadGameModal` filters them out, so the UI cannot reach them.

### Not built / unverified (kept out of the canon as working rules)

- **Hooks and flags.**
  - `give_item` sets only the `item_<id>` flag; no item lands (`scenario._apply_hook`).
  - `open_shop` sets `_shop_open`, which nothing reads.
  - `advance_quest` only relabels the status, and the only reader is the SidePanel's status text.
  - Dialogue `requires` supports positive flags only: no negated or once-only gates.
  - Nothing sets `talked_<npc>`, `refused_*` or `fell_*` flags, and `town_state.talked` is never written.
- **Rewards overflow.** Items that don't fit are dropped silently at acceptance. `assign_reward` checks room against the pre-adventure copies (`sc.loadouts`), but `session._accept_rewards` lands items on the adventure's copies, then `accept_rewards` swallows the `ValueError`.
- **Quest Log.** The panel (`TownScreen.QuestLogPanel`) never renders `quest_log.quest` title/text. Only the journal's "We took on…" entry and the SidePanel title/status carry it.
- **Deferred designs.** Paid rest and a day-priced inn, gold sinks, barks, the narrator, LLM party lines, trait-gated choices, `mode: open` lore, drop-in/out party, "continue from campaign X", NPC `acts` reading the day counter, the consumable `uncounterable` flag, and content-store GC. Optional canon line: "(not built — see docs/roadmap.md)".
- **Recovery gaps.**
  - A failed act materialization has no in-session retry ("The chronicle faltered: …"); only a reload resumes it.
  - A failed interlude planner is re-queued by Continue Campaign.
- **§D24-5.4.** "A library scenario's town joins the worldbook on first use" is not built. Entries come only from `save_town` (the generator), `scripts/backfill_worldbook.py` and Options → World. All four shipped towns (azure, karzum, millhaven, nalindor) have entries.
- **Content gaps.** `content/scenarios/` is empty (no pre-generated scenario ships), and `saves/` is empty. The Update 24 continue loop is likely unplayed end to end, and scenario mode needs an LLM key (arc, act and interlude writers).
- **Unchecked.** The T-79 spend-audit gate is recorded as "not met by the instrument" (SPEND_AUDIT_UPDATE_17.md), and harness data is not trusted, so no balance claim is made here.
- **Not described in the canon.** The legacy `archetype` migration (`Character._migrate_archetype`, `legacy` flag) and the pre-§D17-2.3 `spent_points` migration are load-compatibility behaviour, not rules.


## generation.md (generation notes)

### Doc ≠ code (the doc follows the code)

1. **Phase III objectives.** `content.save_adventure` refuses any Phase III objective before `_validate_adventure` runs, which makes `_validate_adventure`'s §D23-5 modifier check (`_phase_three_objective_problem`) unreachable from generation, even though `ADVENTURE_EXTENSION` teaches Phase III objectives. Confirmed with a local call that wrote nothing. Tests exercise `_validate_adventure` directly.
2. **The lockdown budget.** `_lockdown_budget` appears only in `_request_block`. The adventure request, which is the in-play path, has no lockdown lines, yet the system prompt says to "see the LOCKDOWN BUDGET in this encounter's parameters". Nothing enforces the budget.
3. **The arc writer's inputs.** §D24-7.6 says the arc writer reads briefs, situations, town state and the worldbook at "scenario start / continue". The code passes party, ledger and world only at Continue (never at Town + New or pregeneration), and always passes the raw town (`town_detail`) with no town state.
4. **Art paths.** §D20-2 places cast and place art under `content/art/cast|places/`; the code writes `apps/deckbuilder/loadouts/art/cast|places/` (`SPOILS_ROOT = LEGACY_ART_DIR`, gitignored). README "Art generation", the `art.py` docstring and the `save_encounter` docstring say encounter art goes to `loadouts/`; the code writes `content/`. README still listed "GLM, Gemini, Claude" models.
5. **Docstrings that overstate.** `validate_materialization` claims it checks the `defeated_once` branch; it doesn't. `jobs.py` and §D17-6.3 list the job states `generated` / `art_queued`, which are never set. `InterludeJobRunner._generate_locked` says it takes the session lock; it doesn't.
6. **Attempts.** Encounters and flavour default to 2 attempts, not 3.
7. **Narration and stock names.** §D10-5 calls narration "one short paragraph"; the code wants ≥ 100 words, and the prompt asks for 2–4 paragraphs. §D17-6.2 says the LLM names merchant stock; the code doesn't ("an LLM naming pass is a later polish").
8. **Gates looser than their prompts:** `enrage_round` accepts 2–6 (prompt 3–5); `MAX_DEPTH` 10 (prompt 8); cast truncated at 4 (prompt 0–3); 1–4 NPCs per location (prompt 1–2); `exterior_scene` not required.
9. **Grudges and the whole book.** §D23-6 says to teach `hero_class:` / `hero_type:`; `llm.py` never does. §D24-8.3 and `world.py` say nobody reads the whole worldbook, but `scripts/backfill_worldbook.py` sends every entry's gist.
10. **Resource-attack caps.** The encounter prompt says "one per encounter" twice, while its resource-attack section budgets them by the lockdown budget. The doc reads them together: at most one resource attack, with the rest of the budget spent elsewhere.

### Not verified

- Bake-off figures and verdicts come from the owner's notes; slugs and prices may have drifted. "Gemini 3.7 Flash" was tested, and the picker now aliases it to the untested 3.8.
- No live generation was run, and the ComfyUI and H3 tooling was not exercised.
- `_chat`'s ~75 tok/s comment implies a 24k-token encounter reply would exceed the 120 s timeout.
- Generated `flavor_text` is not serialized to the client (`serialize.card_dict`).
- `_party_block(depth="summary")` has no caller.
- Nothing re-queues an adventure's art after a server restart.
- A `new` hook seed that repeats an existing town name would overwrite that town's file (read from code, not tested).


## balance_register.md (register notes)

### How firmly each value is pinned down

- **Prompt-only** values exist only as prose in the generation prompt. No code computes or validates them, and an Options → LLM override can replace them: T-01–T-24, T-26, T-28–T-32, T-34–T-36, T-39, T-47, T-53, T-65, T-67, and the prices in T-51 and T-56. No code prices an enemy or checks its Level against B(L).
- **Tagged in a comment but not a named constant:** T-27 (the literal `2`, twice), T-52 (`// 2`, twice), T-45/T-46 (hard-coded 1 per counter).
- **Untagged in code:** T-25, T-42–T-44, T-50, T-77.
- "T-1x" in §D17-2.2 is a loose pointer to T5-1x.

### Doc ≠ code conflicts worth a decision

1. **T-27 vs §D18-2.** `_scale_enrage` adds n−1 tokens to an Enrage, but `_create_enemy_tokens` caps living tokens at 2 per creator, so at party sizes 3–4 the extra bodies never appear. The same clip hits a race escalation's token wave. Found by reading the code.
2. **T-48/T-49.** §D8-3.3 and §D8-7 still describe a flat 100-point bar. The level-scaled cost, percentage tempo payouts, Mitigate credit and control credits exist only in code comments, and T-58 (raw carry) and T-69 (a %) moved with them.
3. **T-79.** HP pairs are 4/4/5/5 in code, 5/5/5/5 in §D17-2.2 and §D17-11. The change is recorded only in `SPEND_AUDIT_UPDATE_17.md`.
4. **T-20/T-21/T-55.** The prompt's magnitude table says single-target L+2, but its T-55 line says L+1. `enemy_analysis.LEVERS` still says L+1 and Drain ceil(L/2)+1. README's magnitude table predated §D18-2, and its keyword list priced `protection` (T-33).
5. **T-54.** The round-1 double intent on standard and hard is recorded in no design doc.
6. **T-74.** U23 Part B said recalibrate; the owner declined. §D13-1.2 still quotes the +6 pp launch band.
7. **Stale register rows in their own documents:** T-40 (§X-7 vs §X-5.2), T-78 (§D17-11 says L2 = 30), T-81 (§D17-11 and the §D17-12 glossary say "derived level"). §D17-2.1's milestone prose also contradicts its own table.
8. **Stale code comments:**
   - `runner`'s docstring ("30 points per level") and `run_adventure`;
   - `adventure.POINTS_PER_LEVEL` tagged T-57;
   - `llm._adventure_request_block` ("L / L+1 / L+2, T-62"; the real ramp is 1.0 / 2.0 / 2.4 from L1);
   - the `content.enrage_scale` docstring on the AoE rate.

### Numbering

- T-01…T-87 and T5-01…T5-24 run without gaps; the next free id is T-88.
- Updates 18–24 added tunables but no register section, so none has an id.
- Several amendments never reached a register table: T-57 and T-62 (§D17-2.3), T-87, T-20/21/23/24 (§D18-2), T-34 (§D19-3), T-45/46/51 (§D22-2), and T5-11 (§L-6.1, §D23-2).


## architecture.md — engine and core (arch notes)

**README contradictions:**
- The dependency rule, repeated in the root `pyproject.toml` (which still says "three packages" and "both apps"), is wrong; see §1. The README tree also omits `selfupdate.py`, `loader.py`, `autoplay/` and the tester.
- It says the cockpit has "no RNG and no shuffle", but `server.Session.start` seeds each fight randomly.
- Its example `python -m ltg_combat validate examples/sample_loadout.json` prints "loadout OK" and then raises `AttributeError`: `engine.run` reads `Character.archetype`, which no longer exists. I ran it to confirm.
- It calls a new effect handler "a localized change in `engine.RESOLVERS`", which understates the work (see the checklist in §4).

**Stale text in the code:**
- The `schema.py` docstring cites `mappings.RENDERERS` and a "(future) resolver".
- The `translation.py` docstring uses `CounterIntent()` in an example.
- `probes.py` says the stick is `greedy-1.0.0`.
- The `Action.kind` comment lists `parry`, which is not one of the 18 action kinds.
- The `EnemyState` docstring says "bosses are out of scope".
- The `RESOLVERS` comment mentions the retired `disable`.
- `_apply_static` refers to `_apply_damage`, which doesn't exist (it's `_deal_damage`). The task brief uses the same wrong name.

**Bugs and drift:**
- `_DAMAGE_KINDS` and the taunt gate in `llm.py` include `"drain"`, which is not a verb.
- `serialize._mitigate_value` has no floor of 1, so the UI can show a Mitigate of 0 when the engine applies 1.
- Seeded shuffles build `random.Random` from a tuple, which raises `TypeError` on Python 3.11 and later. The game server seeds every fight, so any `shuffle_after` or `library_shuffle` effect would crash on a Windows install running a current Python.
- **New finding:** a Skill containing `modify_action refresh_skill` on its caster can be re-used without limit in one main phase. `_proactive_open` keeps an already-taken mode open, and the refresh clears `skill_used`. Reproduction: the local `vay` loadout ("Perfect note") against `the_sootfall_adit__phase2` with seed 99. greedy-1.5.0 looped 4,000 actions inside round 2, gaining +5% gauge on each use.
- The copy costs I measured differ from the brief: cards take 60–80% of each copy, not half.
- `examples/scenario_c.json` gives Maul's intent amount as 5; `SCENARIO_C` in the code has 4.


## architecture.md — server, client, Deckbuilder (arch notes)

**Where the brief is wrong**
- The Equipment editor writes to `loadouts/equipment/`, not `content/`. The only tracked item writes are `art_url` and `content/art/items/`. Spoils, cast and places art go to gitignored `loadouts/art`.

**Other findings**
- Stale code comments: the `art.py` docstring (says `loadouts/art`) and `_generate_locked` (claims a lock).
- Client bugs, all confirmed in code: the Chronicle ordering (regressed in `347dfa7`), the stun FX key, and every snapshot cancelling targeting.
- `docs/` does not exist yet, so the `docs/generation.md` link is forward-looking.

**README.md is stale**
- API table: 9 rows, but there are 55 routes.
- WebSocket row: 3 client verbs, but there are 9.
- Apps tree: lists 6 of 19 server modules.
- Deckbuilder: still described as importing MTG cards, and its Scryfall routes are listed.
- Cockpit port: 8001 in the README, 8011 in `launch.json`.

**`apps/game-server/README.md` is stale**
- It calls bosses, persistence and art deferred.
- It lists 3 REST routes and 4 WebSocket types.
- It says Vite proxies only `/api` and `/ws`.
- It uses a link emoji (U+1F517) in "Copy invite".

**Design docs**
- `INTERFACE_NOTES.md`: see §3. §4.3, §4.4, §4.9b and §6 are plainly wrong.
- `DESIGN_SYSTEM.md` §8 says intents are never shown, but veiled intents now render. Its 40/60 layout split is now 45/55.

**Ports and branch**
- If the Deckbuilder runs on 8012, the game's Quit and Edit still target 8000 unless `LTG_DECKBUILDER_PORT` or localStorage `ltg_deckbuilder_port` is set.
- This branch is 3 commits ahead of local `main`. Standalone installs follow `origin/main`.
