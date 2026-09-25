# Design history

This folder holds LTG's design record. The v1 Game Design Document plus Design Updates 01–24 were written between June and September 2026. Each one amended the ones before it, and **a later document wins where they disagree**.

**These files are history, not the current rules.** The current rules are in [`../game_design.md`](../game_design.md) (GDD v2), which folds all of them into one canon. Come here for the *why* behind a rule, the implementation notes of a past change, or to resolve a `§` citation in a code comment.

The files keep their original names and section numbers, because code comments cite them about 1,400 times. Many status lines inside them are stale (for example "canonical design, **not yet built**"). The table below records the actual status as of 2026-09-24.

## Resolving a § citation

| Citation prefix | Document | Topic |
|---|---|---|
| `GDD §n` | [ltg_game_design_document.md](ltg_game_design_document.md) (v1) | GDD v2 keeps the same numbers for §1–§11, so `GDD §8` is channeling in both |
| `§R-` | [Update 01](ltg_design_update_01.md) | rows, attack modes, reachability, HP errata |
| `§M-` | [Update 02](ltg_design_update_02.md) | Mitigate (`§M-A`), the first movement model (`§M-B`, superseded by Update 15), haste (`§M-C`) |
| `§M-A.7` | *no document* | **Combat Abilities**, ruled 2026-08-21 in code (`engine._announce_combat_ability`, `tests/test_combat_ability.py`); written up in GDD v2 §9.9 |
| `§E-` | [Update 03](ltg_design_update_03.md) | the win condition as enemy zone state; bounce and removal |
| `§F-` | [Update 04](ltg_design_update_04_enemy_framework.md) | the enemy framework; `§F-10` is where the Rebalance Register started |
| `§P-` | [Update 05](ltg_design_update_05_character_build.md) | character points-buy |
| `§E6-` | [Update 06](ltg_design_update_06_enemy_intelligence.md) | enemy intelligence, counterspells, wards, encounter scaling |
| `§X-` | [Update 07](ltg_design_update_07_errata_and_rebalance.md) | errata and rebalance |
| `§D8-` … `§D24-` | Updates 08–24 (table below) | — |
| `§L-` | [Update 15](ltg_design_update_15_live_movement.md) | live movement |
| `§A-` | [Update 16](ltg_design_update_16_panel_animations.md) | panel animations |
| `§G13-` / `§G14-` | *tests only* | greedy-policy change notes in `tests/test_greedy_1_3.py` |
| `T-NN` | [../balance_register.md](../balance_register.md) | a tunable number in the Rebalance Register |
| `INTERFACE_NOTES §n` | [INTERFACE_NOTES.md](INTERFACE_NOTES.md) | the July Phase-1 engine↔client contract; partly stale, see [../architecture.md](../architecture.md) |

## The documents

| # | Date | Title / scope | Status (2026-09-24) |
|---|---|---|---|
| GDD v1 | 2026-06-22 → 09-06 | [Game Design Document](ltg_game_design_document.md): the original rules spec with amendment call-outs | **Superseded** by [GDD v2](../game_design.md) |
| 01 | 2026-06-23 | [Rows, attack modes, reachability; HP errata](ltg_design_update_01.md); resolves most v1 `[OPEN]`s, lists open edges in §R-13 | Built |
| 02 | 2026-06-25 | [Mitigate (renamed from Parry), movement, haste](ltg_design_update_02.md) | §M-A built; §M-B and the movement parts of §M-C superseded by Update 15 |
| 03 | 2026-06-29 | [The win condition as enemy zones; bounce and removal](ltg_design_update_03.md) | Built |
| 04 | 2026-07-03 | [Enemy framework](ltg_design_update_04_enemy_framework.md): chassis and components, budget and level, AI priority list, bosses, factions, generation contract, Rebalance Register | Built; later extended by 06, 09, 12, 18, 19, 21, 22, 23 |
| 05 | 2026-07-04 | [Character build and progression](ltg_design_update_05_character_build.md): points-buy, Power as a bought stat | Built; archetype presets removed by Update 17 |
| 06 | 2026-07-07 | [Enemy intelligence](ltg_design_update_06_enemy_intelligence.md): component vocabulary, counterspells, wards and smart support, enrage as a hard turn | Built |
| 07 | 2026-07-09 | [Errata and rebalance](ltg_design_update_07_errata_and_rebalance.md): records rules the code already enforced | Built (a record, not a design) |
| 08 | 2026-07-11 | [Tier One](ltg_design_update_08_tier_one.md): veiled intents, poison/regen/charge, Skill and Ultimate plus the gauge, smart auto-pass | Built; gauge payouts reworked 2026-08-29 (in code); auto-pass extended by Pass-All (Update 23) |
| 09 | 2026-07-11 | [Tier Two](ltg_design_update_09_tier_two.md): corpses and necromancy, stances, forced movement and row blasts, boss endgame | Built |
| 10 | 2026-07-11 | [Adventures](ltg_design_update_10_adventures.md): the three-phase run, carry-over, level-ups between phases | Built; the phase/act rename came in Update 17 |
| 11 | — | "Balance Update 11": exists in code only, recorded in Update 12 §D12-0 | Built (`tests/test_balance_update_11.py`) |
| 12 | 2026-07-16 | [Roadmap Tier One](ltg_design_update_12_roadmap_tier_one.md): objectives, enemy insight, the autoplay balance harness | Built; CI (§D12-3.7) and the full content soak (§D12-3.6) not done ([roadmap](../roadmap.md) M0.3, M10.3) |
| 13 | 2026-07-16 | [The Autoplay Tester](ltg_design_update_13_autoplay_tester.md): probes, gauntlets, verdicts | Built; verdicts don't go stale on policy changes, and some Tester features are partial (M10). The owner doesn't trust its absolute numbers. |
| 14 | 2026-07-18 | [Enemy kit floor](ltg_design_update_14_enemy_kit_floor.md): the two-component minimum / punching-bag rule for generation | Built |
| 15 | 2026-07-18 | [Live movement](ltg_design_update_15_live_movement.md): real rows, the lunge, interposition | Built; haste price amended by Update 23; the §L-7 measurement of positional play never ran (M10.7) |
| 16 | 2026-08-17 | [Panel animations](ltg_design_update_16_panel_animations.md) | Built; per-trigger clips added 2026-09-06 (in code); stance-loop clips and clip export not built (M2.22, M8.11) |
| 17 | 2026-08-19 | [Scenario mode](ltg_design_update_17_scenario_mode.md): towns, arcs and acts, dialogue, gear and economy, runs and branching saves, level from points spent, the price curve; §D17-13 "the town speaks first" | Built through Phase 2; Phase 3 "dressing" (narrator, party lines) not built; Everquest retired by Update 24; run content leaks into tracked `content/` (M1.15); economy never validated (M3.10) |
| 18 | 2026-08-22 | [Enemy pressure](ltg_design_update_18_enemy_pressure.md): ability damage lift, party-scaled enrage, taunt-with-teeth, attack cadence, row shapes aim at ground | Built |
| 19 | 2026-08-22 | [Corpse fuel and intent validity](ltg_design_update_19_corpse_fuel_and_intent_validity.md): `consume_corpse`, re-validating intents before the stack, hexproof pricing | Built |
| 20 | 2026-08-22 | [The town as an RPG](ltg_design_update_20_town_rpg.md): `knows_*` gating and the reachability check, arc cast and places, town-only library scenarios | Built; the scenario library it describes has since been deleted (M3.5) |
| 21 | 2026-08-22 | [Types and classes](ltg_design_update_21_enemy_types.md) | Built; grudge targeting (Update 23) not yet taught to the generator (M4.7); legacy enemies untagged (M3.11) |
| 22 | 2026-08-30 | [Counters and countdowns](ltg_design_update_22_counters_and_countdowns.md): readable charge, poison/regen as clocks, self-terminating enchantments, trigger countdowns | Built |
| 23 | 2026-09-05 / 06 | [Turn groups, reach, and fight shape](ltg_design_update_23_turn_groups_and_reach.md): the turn as groups, freed verbs, no ranged shots from Front, interposition for combat abilities, boss and objective fixes, less-solved AI, rules corrections, Pass-All, the action bar | Built 2026-09-06 (8a40137), except that a leftover save check vetoes Phase III objectives (M1.4); T-74 recalibration skipped on purpose |
| 24 | 2026-09-06 | [Campaigns, the interlude, and the worldbook](ltg_design_update_24_campaigns_and_the_worldbook.md), plus character layers; Everquest retired | Built 2026-09-06 (3cee7bc); three bugs on the continue path (M1.5–M1.7); the loop has never been playtested (M3.6) |

## Rulings recorded only in code

These decisions were made during playtest rounds and live in code comments and commit history, not in a design update. GDD v2 includes all of them.

| Date | Ruling | Where it lives |
|---|---|---|
| 2026-08-21 | **Combat Abilities** (`§M-A.7`): a damaging ability is derived as a combat-lane action, answerable by Mitigate when single-target | `engine._announce_combat_ability`, `tests/test_combat_ability.py` |
| 2026-08-21 | **Resource attacks** (forced discard, Silence `prevent cast`, `sap`), the `defender` keyword, Defend = base Power, action modifiers (`modify_action`), the party-size lockdown budget | `schema.ACTION_MODIFIERS`, `llm._lockdown_budget`, `tests/test_silence_and_sap.py`, `tests/test_defender_and_defend.py`, `tests/test_action_modifiers.py` |
| 2026-08-29 | **Gauge rework**: Mitigate and control credits, level-scaled charge cost (`100 + 20·(level−1)`), percent-based tempo payouts; amends §D8-3.3 | `state.GAUGE_LEVEL_STEP`, `tests/test_gauge_rework.py` |
| 2026-08-29 | Playtest fixes: Ultimates countered with `"filter": "ability"` (T-70 guardrail), copy-spell rules, death permanence | `tests/` (see GDD v2 §5.4, §4.3) |
| 2026-08-30 | The Deckbuilder became custom-cards-only (MTG import UI removed; legacy fields load and are pruned) | `apps/deckbuilder` (`pruneLoadout`, `_prune_loadout_dict`) |
| 2026-09-06 | A channel's own `channel_break` resolves beneath its own pending triggers; per-trigger panel animations | `engine._sink_break_under_own_triggers`, `Card.trigger_animations` |
| 2026-09-06 | Lore became a plain-text field (`character.lore`) with derived keys; `combat_lore` feeds deck-flavour generation | recorded as an amendment in Update 24 §D24-7.3 |

## Working documents (not history)

- [../panel_animation_prompt_guide.md](../panel_animation_prompt_guide.md) and [../panel_animation_prompts.md](../panel_animation_prompts.md): the approved MiniMax H3 image-to-video prompt set.
- [../reviews/2026-09/](../reviews/2026-09/README.md): the 2026-09-02 whole-game review briefs. Their open items are tracked in [../roadmap.md](../roadmap.md).

## Writing the next design update

1. Write `ltg_design_update_25_<topic>.md` here in the house shape: Part A rules (canon), Part B implementation notes, Part C documents to update, Part D tests, Part E order.
2. Once it is implemented, fold its rules into [`../game_design.md`](../game_design.md) and its magnitudes into [`../balance_register.md`](../balance_register.md), update this table, and tick its objectives in [`../roadmap.md`](../roadmap.md).
3. Code comments cite the new `§D25-…` sections as usual.
