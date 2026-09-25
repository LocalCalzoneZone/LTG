# Rebalance Register

Every tunable magnitude in LTG carries a register ID, a **T-number** (`T-57`), so that a number can be found again, argued about, and changed in one place. The register began in Update 04 §F-10. Later design updates amended it in their own "Rebalance Register deltas" sections (§P-8, §X-7, §D8-7, §D9-8, §D10-8, §D12-5, §D13-5, §D17-11) and sometimes only in body text. This page consolidates all of it as of 2026-09-24.

**Every value is a playtest starting value.** Mechanisms are canonical. Magnitudes are provisional and expected to move.

**The code is authoritative.** Where documents disagree, the later one wins. Where a document and the code disagree, *Current value* shows the code and the row is flagged `doc≠code`. Some rulings exist only in code comments.

**To add a tunable:** take the next free ID (**T-89**), implement it as a named constant (not a bare literal or prompt prose), cite `T-NN` in a comment beside it, and add a row here with the § that decided it. **To change one:** edit the constant and its row in the same commit.

## Register

**Decided in** uses the design-history citations, which [design/README.md](design/README.md) resolves: §F = Update 04 · §P = U05 · §E6 = U06 · §X = U07 · §D8…§D24 = U08…U24 · §L = U15 · §M = U02.
**Code** paths: `schema` = `core/ltg_core/schema.py` · `engine`, `state`, `combat/scenario` = `apps/combat/ltg_combat/` · `runner`, `report`, `soak` = `apps/combat/ltg_combat/autoplay/` · `content`, `llm`, `adventure`, `scenario`, `items`, `loot`, `session`, `snapshot` = `apps/game-server/ltg_game_server/` · `probes` = `apps/autoplay-tester/ltg_autoplay_tester/probes.py`.
**prompt** = the enemy-generation prompt (`llm.DEFAULT_INSTRUCTIONS` / `ADVENTURE_EXTENSION`). The model is taught these values, but no code computes or checks them. A saved Options → LLM override replaces the prompt; none was saved on the dev machine as of 2026-09-24.
`T5-nn` is Update 05's separate character-build series. It is listed after T-87.

| T-id | What it tunes | Current value | Code (symbol) | Decided in | Notes |
|---|---|---|---|---|---|
| T-01 | Enemy upgrade: +1 HP | 1 pt | prompt (Chassis) | §F-2 | prompt-only |
| T-02 | Enemy upgrade: +1 Power | 3 pts | prompt (Chassis) | §F-2 | prompt-only |
| T-03 | Enemy upgrade: add a ranged attack | 2 pts | prompt (Chassis) | §F-2 | prompt-only |
| T-04 | Chassis cost: Husk (2 HP / 1 Pow, melee, front) | 5 | prompt (Chassis table) | §F-2 | prompt-only |
| T-05 | Chassis cost: Bruiser (4 / 2, melee, front) | 10 | prompt (Chassis table) | §F-2 | prompt-only |
| T-06 | Chassis cost: Skirmisher (2 / 2, melee + ranged, mid) | 10 | prompt (Chassis table) | §F-2 | prompt-only |
| T-07 | Chassis cost: Artillery (2 / 2, ranged, rear) | 10 | prompt (Chassis table) | §F-2 | prompt-only |
| T-08 | Chassis cost: Caster-frame (2 / 1, ranged, rear) | 7 | prompt (Chassis table) | §F-2 | prompt-only |
| T-09 | Component base cost: Punish | 3 | prompt (Components) | §F-3.1 | prompt-only |
| T-10 | Component base cost: Fortify (heal / pump / regen) | 3 | prompt (Components) | §F-3.1 | prompt-only |
| T-11 | Component base cost: Evasive | 2 | prompt (Components) | §F-3.1 | prompt-only |
| T-12 | Component base cost: Burst | 4 | prompt (Components) | §F-3.1 | prompt-only |
| T-13 | Component base cost: Debilitate | 4 | prompt (Components) | §F-3.1 | Also prices Hamstring and strip-reach. Drain Ult costs 5 at amount ≥ 20 |
| T-14 | Component base cost: Escalate | 4 | prompt (Components) | §F-3.1 | Also prices a charge gather (T-47) |
| T-15 | Component base cost: Drain | 5 | prompt (Components) | §F-3.1 | prompt-only |
| T-16 | Component base cost: Swarm | 6 | prompt (Components) | §F-3.1 | prompt-only |
| T-17 | Cost multiplier: cooldown 1 | ×1.5 | prompt (Cost modifiers) | §F-3.1 | Cooldown 2–3 is ×1.0 |
| T-18 | Cost multiplier: once per encounter | ×0.5 | prompt (Cost modifiers) | §F-3.1 | prompt-only |
| T-19 | Reactive-timing premium | +2 flat, after multipliers | prompt (Cost modifiers) | §F-3.1 | Counter nets 3 + 2 = 5 |
| T-20 | Burst/Punish `deal_damage` magnitude | L+2 | prompt (Verb magnitudes) | §F-4; §D18-2 | **amended by §D18-2** (was L+1). The prompt's T-55 line still says L+1 (see T-55) |
| T-21 | Drain damage and self-heal, each | ceil(L/2)+2 | prompt (Verb magnitudes) | §F-4; §D18-2 | **amended by §D18-2** (was ceil(L/2)+1) |
| T-22 | Fortify heal | L+2 | prompt (Verb magnitudes) | §F-4 | unchanged |
| T-23 | Pump / wound size | ±(ceil(L/3)+1) | prompt (Verb magnitudes) | §F-4; §D18-2 | **amended by §D18-2** (was ±ceil(L/3)) |
| T-24 | Escalate counters per firing | +2/+2 | prompt (Verb magnitudes) | §F-4; §D18-2 | **amended by §D18-2** (was +1/+1) |
| T-25 | Enemy `prevent` duration | 1 turn | `schema.Prevent.duration` default `this_turn` | §F-4 | untagged in code |
| T-26 | Swarm token level | Husk chassis at ceil(L/2) | prompt (Verb magnitudes) | §F-4 | prompt-only. The engine reads the token definition's `level` |
| T-27 | Max live tokens per creator | 2 | `engine.TOKEN_CAP` (`_create_enemy_tokens`, `_swarm_at_cap`) | §F-4 | A boss's Enrage and a race escalation are exempt (`StackItem.uncapped_spawns`), so §D18-2's +n−1 wave spawns whole (ruled 2026-09-25, M1.22). A clipped spawn logs `token_cap` |
| T-28 | Enemy keyword reach (min level / cost) | L1 / 1 | prompt (Keywords) | §F-5 | prompt-only |
| T-29 | Enemy keyword trample | L2 / 2 | prompt (Keywords) | §F-5 | prompt-only |
| T-30 | Enemy keyword flying | L2 / 4 | prompt (Keywords) | §F-5 | prompt-only |
| T-31 | Enemy keyword lifelink | L3 / 3 | prompt (Keywords) | §F-5 | prompt-only |
| T-32 | Enemy keyword deathtouch | L3 / 4 | prompt (Keywords) | §F-5 | prompt-only. Since 2026-09-25 (M1.30) it downs a hero it connects with, so the prompt also asks for low Power, no area damage, at most one per encounter; the price is unreviewed for that |
| T-33 | Enemy keyword protection | — (was L4 / 3) | `schema.KEYWORDS["protection"]`, `grantable: False` | §F-5 | **retired** 2026-08-22 (code comment: author the `protection` effect instead). **doc≠code**: §F-5 and README still list it |
| T-34 | Enemy keyword hexproof | L5 / 6 | prompt (Keywords) | §F-5; §D19-3 | **amended by §D19-3** (was L4 / 4). The §F-5 body was edited in place, but the §F-10 row is stale |
| T-35 | Enemy keyword indestructible | L6 / 6 | prompt (Keywords) | §F-5 | prompt-only |
| T-36 | Enemy budget per level, B(L) | 5L + 5 | prompt (Budget → Level) | §F-6; reaffirmed §X-7 | prompt-only. An enemy's level is the smallest L whose budget covers its cost |
| T-37 | Encounter Level budget | round(2 × party size × avg level × T-38) | `llm._budget` | §F-6; §X-5.1 | A boss counts double toward it (prompt) |
| T-38 | Difficulty multipliers, easy / standard / hard | 1.0 / 1.5 / 2.5 | `llm.DIFFICULTY` | §F-6; §X-5.1 | **amended by §X-5.1** (was 0.75 / 1.0 / 1.5) |
| T-39 | Boss budget multiplier | 2.5 × B(L) | prompt (Bosses) | §F-9; reaffirmed §X-7 | prompt-only |
| T-40 | Post-generation enemy HP multiplier, easy / standard / hard | 1.0 / 1.2 / 1.5 | `llm.ENEMY_HP_MULT` (mirrored in `runner.ENEMY_HP_MULT`) | §X-5.2 | **doc≠code (row only)**: the §X-7 table lists 1.5 / 2.0 / 2.5 (the values before they were lowered), while §X-5.2 matches the code. Stacks with `ENEMY_STAT_BUFF` (no-T table) |
| T-41 | Minimum enemy bodies per layout | 2 × party size | `llm._min_enemies`; `content` adventure validation | §X-5.3 | `waves` spreads it across waves (T-66) |
| T-42 | Deck minimum | 20 cards | `schema.DECK_MINIMUM` | §X-1 | Advisory: it warns but never blocks |
| T-43 | Rarity quotas, mythic / rare / uncommon / common | 1 / 3 / 6 / 10 | `schema.RARITY_MINIMUMS`, `UNCAPPED_RARITIES` | §X-1 | Advisory. Commons are uncapped. Kept as a balance lever |
| T-44 | `revive` default `to_fraction` | 0.5 | `schema.Revive.to_fraction` | §X-2.3 | untagged in code |
| T-45 | Poison | Lose 1 life per counter each Upkeep. Any healing clears all counters | `engine._tick_afflictions_one`, `_cure_poison` | §D8-2.1; §D22-2 | **amended by §D22-2** (was −0/−1 per counter per tick). Hard-coded 1 |
| T-46 | Regen | Heal 1 per counter each Upkeep. Connecting damage clears all counters | `engine._tick_afflictions_one`, `_break_regen` | §D8-2.2; §D22-2 | **amended by §D22-2** (was +0/+1 per counter per tick) |
| T-47 | Windup: charge-triggered verb ceiling and minimum threshold | ≤ 2× the level schedule. Threshold ≥ 2 gathers | prompt (The windup) | §D8-2.4 | prompt-only, not validated |
| T-48 | Ultimate charge cost (gauge size) | 100 + 20·(level−1) raw points. The bar shows 0–100 % | `state.CharacterState.ultimate_charge_cost`, `state.GAUGE_LEVEL_STEP` | §D8-3.3; gauge rework 2026-08-29 (code) | **doc≠code**: §D8-3.3 and §D8-7 still say a flat 100 |
| T-49 | Gauge fill rates | see Schedules | `engine._gain_gauge`, `_gain_gauge_pct`, `_control_credit` | §D8-3.3; gauge rework 2026-08-29 (code) | **doc≠code**: tempo payouts are now a % of the cost, and Mitigate and control credits were added |
| T-50 | Skill / Ultimate uses | 1 / 1 per encounter | `state.CharacterState.skill_used` / `ultimate_used` | §D8-3.1, §D8-3.2 | The `refresh_skill` modifier can re-arm the Skill |
| T-51 | `infect`: enemy price and rider | L3 / cost 3. 1 poison counter per connecting hit | prompt (Keywords); `engine` | §D8-2.5; §D22-2 | **amended by §D22-2** (was one poison *effect* of amount 1) |
| T-52 | HP of raised and risen undead | ½ max HP, floor, min 1 | `max(1, max_hp // 2)` in `engine._raise_corpse` and `_tick_stirring` | §D9-1.4, §D9-1.5 | Bare literal. Mirrors T-44 |
| T-53 | Necromancy component base cost | 5 | prompt (Components) | §D9-1.6 | prompt-only |
| T-54 | Boss intents per round | 2 once enraged, on every difficulty. 2 from round 1 on standard and hard | `engine` proactive pass (`is_boss and (enraged or double_intent)`); `content.DOUBLE_INTENT_DIFFICULTIES` | §D9-4 | **doc≠code** (the code goes further than §D9-4): round-1 double intent is a code-only playtest ruling. A stun suppresses one of the two |
| T-55 | Enemy AoE magnitude by scope | Whole row = L per creature. Blast or party-wide = ceil(L/2)+1 | prompt (Forced movement & row blasts) | §D9-3.3; extended §L-5 | **doc≠code**: its "single target stays L+1" clause (in §D9-8 and the prompt's T-55 line) contradicts T-20's L+2. The register also adds +2 on row/blast shapes (no-T table) |
| T-56 | `rises` trait | Min L2 / cost 3. Revives after 2 Upkeeps, once | prompt; `combat/scenario` loader | §D9-1.5 | Price is prompt-only |
| T-57 | Points earned | +10 / +20 / +30 per phase won (60 per adventure) | `schema.PHASE_GRANTS`, `ADVENTURE_POINTS`; `adventure.phase_grant` | §D10-3.1; §D17-2.1, §D17-2.3 | **amended by §D17-2.3** (was 30 per level-up). Missing from the §D17-11 table |
| T-58 | Ultimate-gauge carry across phases | 50 % of raw points, floored | `adventure.GAUGE_CARRY` (mirrored in `runner`) | §D10-2 | Carries raw points, so after a level-up the carried half fills less of the larger bar |
| T-59 | Phase-start HP floor | max(current, ceil(25 % max HP)) | `adventure.HP_FLOOR_PCT` (mirrored in `runner`) | §D10-2 | — |
| T-60 | Bought-Power cap | 2 × character level (L1: +2, so melee ≤ 4 and ranged ≤ 3) | `schema.MAX_POWER_BOUGHT` (Character validator) | §D10-3.1; §D17-2.3 | Reads the level derived from points spent. Supersedes T5-14 |
| T-61 | Phases per adventure | 3 | `content.PHASE_COUNT` | §D10-4.1 | — |
| T-62 | Adventure difficulty ramp | Each phase is budgeted at the party's potential level when it opens (continuous, + T-81 gear). From L1: 1.0 / 2.0 / 2.4 | `llm.phase_budget_levels`; `scenario.ScenarioRun.phase_budget_levels` | §D10-4.2; §D17-2.3 | **amended by §D17-2.3** (was "phase N at level N"). Missing from the §D17-11 table |
| T-63 | Adventure-generation `max_tokens` | 64 000 | `llm.ADVENTURE_MAX_TOKENS` | §D10-5 | Kept below per-model ceilings. 48 000 truncated in 2026-08 |
| T-64 | Enemy Power bump | +2 minion / +4 boss | `content.ENEMY_POWER_BONUS`, `BOSS_POWER_BONUS` (mirrored in `runner`) | §D12-0 (Balance Update 11) | **amended by §D18-2**, which extends the lift to hostile ability damage (no-T table) |
| T-65 | `survive` timer | 4–6 rounds | prompt (objectives block) | §D12-1.2 | The range is prompt-only. A validator requires ≥ 2 reinforcement entries (2026-08-30) |
| T-66 | Wave body minimums | ≥ 1× party per wave, ≥ 2× in total | `content` adventure validation; prompt | §D12-1.3 | — |
| T-67 | Summed Level budget across waves | ≤ 1.5× the phase budget | prompt (objectives block) | §D12-1.3 | prompt-only |
| T-68 | `race` clock and escalation pricing | 3–5 rounds. The escalation (2–3 verbs) costs no budget | `llm._objective_problems`; prompt | §D12-1.4 | Also needs 1–2 guards (2026-08-30). May sit on Phase III as a modifier (U23) |
| T-69 | Primed-threat valuation | Gauge ≥ 80 %. A primed tag scores 2, the gauge 1 | `engine.PRIMED_GAUGE`, `engine._primed_score` | §D12-2.1 | Reads `ultimate_gauge_pct` (a % of the level-scaled cost, T-48) |
| T-70 | Ultimate-counter guardrail | Boss-only, once per encounter. The filter must match an activated ability | `combat/scenario._check_ultimate_answer_guardrail` | §D12-2.3 | Filter check added 2026-08-29 |
| T-71 | Autoplay round cap | 50 rounds | `runner.ROUND_CAP`; `soak` | §D12-5 | — |
| T-72 | Report outlier thresholds | Win rate 30–85 % (standard), mean rounds ≤ 12, damage share ≥ 10 % | `report.WIN_RATE_BAND`, `MEAN_ROUNDS_MAX`, `DAMAGE_SHARE_MIN` | §D12-3.5 | — |
| T-73 | Ablation filler card | "Practice Swing": {1} sorcery, deal 2, L1 common | `probes.FILLER_CARD` | §D13-1.2 | — |
| T-74 | Probe flag band | OVER > +4 pp, UNDER < −4 pp; z ≥ 2 is advisory | `probes.OVER_PP`, `UNDER_PP`, `OVER_Z` | §D13-1.1b, §D13-5 | **doc≠code**: U23 Part B asks for a recalibration after greedy-1.5.0. The owner skipped it on purpose (2026-09-06; see the comment in `probes`), so the band still dates from greedy-1.2.0 / baseline-2 |
| T-75 | Ultimate-dependence flag | 60 % of wins | `probes.ULT_DEPENDENCE` | §D13-1.3 | — |
| T-76 | Probe presets | quick: 8 seeds × ladder. thorough: 24 seeds × ladder + leave-one-out sweep | `probes.PRESETS` | §D13-1.1a | Party sizes 1–2, standard difficulty only |
| T-77 | Pressure ladder (enemy HP and Power multiplier) | ×0.5–×2.2 in steps of 0.1 (18 rungs) | `probes.PRESSURE_LADDER` | §D13-1.1a | untagged in code |
| T-78 | Level thresholds (cumulative points spent) | see Schedules (L2 = 10 … L20 = 2010) | `schema.LEVEL_THRESHOLDS`, `level_for_points` | §D17-2.1 | **doc≠code (row only)**: the §D17-11 row says L2 = 30. The §D17-2.1 table and the code say 10 |
| T-79 | Escalating price curve | see Schedules | `schema.PRICE_CURVE`, `PRICE_TAIL_STEP`, `stat_price` | §D17-2.2 | **doc≠code**: the code's HP pairs start 4/4/5/5; the doc says 5/5/5/5. Changed after the 2026-08-18 audit, identical from the 5th pair on |
| T-80 | Inventory | 3 unequipped gear + 3 unequipped consumables. Belt of 3 | `schema.INVENTORY_GEAR`, `INVENTORY_CONSUMABLES`, `BELT_SIZE` | §D17-4.1 | — |
| T-81 | Effective level for budgets and item tiers | Party average of (potential level + floor(worn points ÷ 30)), floored, min 1 | `scenario.ScenarioRun.effective_level`; `items.effective_level_bonus` | §D17-4.2; §D17-2.3 | **[OPEN]** (§D17-10). **doc≠code (row only)**: the §D17-11 row and glossary say "derived level". §D17-2.3 and the code use potential level, from points earned |
| T-82 | Base equipment catalogue | Floor of 6 weapons, 4 accessories, 6 consumables. 26 / 24 / 26 ship | `content/equipment/*.json` (76 files); floor pinned by `tests/test_design_update_17_economy.py` | §D17-4.3 | The §D17-11 row gives the floor only |
| T-83 | Phase III boss drops | (party + 1) gear, (party × 2) consumables | `loot.DROP_GEAR_PER_PARTY`, `DROP_CONSUMABLES_PER_MEMBER` | §D17-4.5 | Forged at the boss tier (act tier + 1) |
| T-84 | All-players confirmation timeout | 30 s, then yes | `session.CONFIRM_TIMEOUT_S` | §D17-4.5, §D17-5.2 | — |
| T-85 | Gold earning rate | 1 gold per point earned (10 / 20 / 30 a phase) | `scenario.GOLD_PER_POINT` | §D17-2.3, §D17-5.3 | — |
| T-86 | Merchant pricing | Buy at ×1.25 of `points_price` (rounded, min 1). Sell at ×0.5 (floored) | `schema.BUY_MULT`, `SELL_MULT`; `items.buy_price`, `sell_price` | §D17-5.3 | — |
| T-87 | Starting purse | 15 gold per character | `scenario.STARTING_GOLD` | §D17-5.3 | Missing from the §D17-11 table |
| T-88 | Default boss pressure dials | `enrage_round` 4, `neglect` 1, for a boss that carries neither (an authored value, 0 included, is kept) | `content.DEFAULT_BOSS_DIALS` / `apply_boss_dials` (in `build_state_from_loadouts`); mirrored in `autoplay.runner.DEFAULT_BOSS_DIALS` | §D23-5; roadmap M3.11 (ruled 2026-09-25) | The middle of the generated ranges. Every legacy boss in the library had none |
| T5-01 | Creation budget | 70 pts | `schema.CREATION_BUDGET` | §P-1 | — |
| T5-02 | Creation price: +2 HP | — (5 flat) | — | §P-2 | **retired**. Superseded by T-79 |
| T5-03 | Creation price: +1 mana | — (15 flat) | — | §P-2 | **retired**. Superseded by T-79, whose 1st purchase is still 15 |
| T5-04 | Creation price: +1 card | — (15 flat) | — | §P-2 | **retired**. Superseded by T-79, whose 1st purchase is still 15 |
| T5-05 | Creation price: +1 Power | — (10 flat) | — | §P-2 | **retired**. Superseded by T-79, whose 1st purchase is still 10 |
| T5-06 | Max keywords at creation | 1 | `schema.MAX_KEYWORDS` | §P-3 | — |
| T5-07 | Keyword price: reach | 5 | `schema.CREATION_KEYWORD_COST` | §P-3 | — |
| T5-08 | Keyword price: trample | 10 | `schema.CREATION_KEYWORD_COST` | §P-3 | — |
| T5-09 | Keyword price: first strike | 15 | `schema.CREATION_KEYWORD_COST` | §P-3 | — |
| T5-10 | Keyword price: lifelink | 15 | `schema.CREATION_KEYWORD_COST` | §P-3 | — |
| T5-11 | Keyword price: haste | 15 | `schema.CREATION_KEYWORD_COST` | §P-3; §L-6.1; §D23-2 | **amended twice**: 15, then 20 (§L-6.1), then back to 15 (§D23-2) |
| T5-12 | Keyword price: vigilance | 20 | `schema.CREATION_KEYWORD_COST` | §P-3 | — |
| T5-13 | Keyword price: flying | 25 | `schema.CREATION_KEYWORD_COST` | §P-3 | — |
| T5-14 | Creation Power cap | +2 (melee ≤ 4, ranged ≤ 3) | `schema.MAX_POWER_BOUGHT` × level 1 | §P-4 | Generalised as T-60 (this is its L1 case) |
| T5-15 | Leveling points per level | — (20) | — | §P-5 | **retired**. Superseded by T-57 |
| T5-16 | Power price, 4th step | — (25) | — | §P-6 | **retired**. Superseded by T-79 |
| T5-17 | Power price, 5th step | — (40) | — | §P-6 | **retired**. Superseded by T-79 |
| T5-18 | Mana price, 4th step | — (30) | — | §P-6 | **retired**. Superseded by T-79 |
| T5-19 | Mana price, 5th step | — (50) | — | §P-6 | **retired**. Superseded by T-79 |
| T5-20 | Card price, 4th step | — (25) | — | §P-6 | **retired**. Superseded by T-79 |
| T5-21 | Card price, 5th step | — (40) | — | §P-6 | **retired**. Superseded by T-79 |
| T5-22 | XP per enemy | — (10 × enemy level) | — | §P-7.1 | **retired**. Never built: points are paid per phase (T-57) |
| T5-23 | XP per boss | — (20 × boss level) | — | §P-7.1 | **retired**. Never built |
| T5-24 | XP to next level | — ((30 + 7 × party size) × level) | — | §P-7.3 | **retired**. Never built: T-78 replaces it |

## Schedules

### T-49: ultimate-gauge payouts

The payouts come from the gauge rework (2026-08-29), which amends §D8-3.3 in code only. "Raw" means points toward the T-48 charge cost. "%" means a percentage of that cost, converted with `_gain_gauge_pct`.

| Event | §D8-3.3 says | Code does |
|---|---|---|
| First proactive action of the turn | +2 | +2 % |
| Mana spent casting (generic + coloured, X counts) | +1 per mana | +1 raw per mana |
| HP lost (damage, `lose_life`, poison ticks) | +1 per point | +1 raw per point |
| Own damage that connects (not tokens') | +1 per point | +1 raw per point |
| HP restored or temp HP granted as the source (heal, Defend, a pump's toughness) | +1 per point | +1 raw per point |
| Skill used | +5 | +5 % |
| An ally is downed (paid to each other living hero) | +25 | +25 % |
| Mitigate | — | +1 raw per point actually mitigated |
| Counter | — | The cancelled item's damage, or its source's level if it dealt none |
| Stun | — | The enemy's current Power per skipped intent, or its level |
| `strip_intent` | — | The stripped intent's damage, or its level |
| destroy / exile / bounce / deathtouch / corpse exile | — | The target's level |
| Taunt, breaking an enemy channel | — | The target's level |
| `charge_ultimate` / `drain_ultimate` modifiers | — | Authored in % of the bar |

Scry and draw earn no gauge on purpose. Token and enemy sources never charge a hero's gauge.

### T-78: cumulative points spent to reach each level

| Level | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|
| Points | 10 | 60 | 105 | 150 | 210 | 300 | 390 | 480 | 570 | 690 |

| Level | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|---|---|---|---|
| Points | 810 | 930 | 1050 | 1200 | 1350 | 1500 | 1650 | 1830 | 2010 |

The character's level comes from points **spent**. Encounter budgets and item tiers instead read points **earned**, as a continuous level (`schema.level_progress`). At 60 points per adventure, a hero who spends as they earn reaches L3 after 1 adventure, L4 after 2, L5 after 3, and L7 after 5. `MAX_LEVEL` = 20.

### T-79: price of the *n*th purchase of a stat

Prices count from the free baseline. Creation and level-ups use the same curve.

| Stat | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | Beyond |
|---|---|---|---|---|---|---|---|---|---|---|---|
| +2 HP (one pair) | 4 | 4 | 5 | 5 | 6 | 6 | 7 | 7 | 8 | 8 | +1 every two purchases |
| +1 mana capacity | 15 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | 55 | +5 each (`PRICE_TAIL_STEP`) |
| +1 starting card | 15 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | 55 | +5 each |
| +1 Power | 10 | 10 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | +5 each |
| Keyword (one, ever) | the creation list, T5-07…T5-13 | | | | | | | | | | |

The doc's HP row (§D17-2.2, §D17-11) is 5 / 5 / 5 / 5 / 6 / 6 / 7 / 7 / 8 / 8. The code has used 4 / 4 / 5 / 5 since 2026-08-18. That change was made so a classic build of 20 HP, 2 mana, 2 cards and +1 Power costs exactly 30 + 15 + 15 + 10 = 70 (T5-01).

## Tuning constants without a T-number

| Constant | Value | Where | What it does |
|---|---|---|---|
| `GAUGE_LEVEL_STEP` | 20 | `state` | How much the ultimate charge cost grows per level past 1 (L4 = 160). From the gauge rework, 2026-08-29; implements T-48 |
| `ATTACK_CADENCE` | 2 | `engine` | An enemy takes its basic attack after 2 consecutive non-attack intents (§D18-3) |
| `EMERGENCY_BAND` | priorities 10–19 | `engine` | Emergency components exempt from the attack cadence (§D23-6) |
| `ENEMY_STAT_BUFF` / `BOSS_STAT_BUFF` | ×1.2 / ×1.3 | `llm` | A flat HP and Power buff on every *generated* enemy, on top of T-40. Tokens take ×1.2. Authored content is untouched. From beta playtest, 2026-08-30 |
| `ENEMY_ABILITY_BONUS` / `BOSS_ABILITY_BONUS` | +2 / +4 | `content` (mirrored in `runner`) | Lifts hostile component `deal_damage` / `lose_life` like T-64 lifts Power. Enrage is excluded (§D18-2) |
| `ROW_ABILITY_BONUS` | +2 | `content` (mirrored in `runner`) | A further lift on row and blast shapes, because they can be dodged (§D18-2) |
| `enrage_scale(n)` | Power half of a pump ×n. Toughness / AoE / heal ×(1 + (n−1)/2). Tokens +n−1 | `content` (mirrored in `runner`) | Scales a boss's Enrage to party size (§D18-2). At n = 4: ×4 / ×2.5 / +3 (the Enrage wave is exempt from T-27) |
| `DOUBLE_INTENT_DIFFICULTIES` | {standard, hard} | `content` | On these difficulties, bosses declare 2 intents from round 1 (see T-54) |
| `_lockdown_budget` | Party size 1 / 2 / 3 / 4 → 0 / 1 / 2 / 3 pieces. Easy −1 (min 0), hard +1 | `llm` | Lockdown pieces (stun, taunt, silence, hamstring, discard, sap, drain-ult, strip-reach) per layout. From 2026-08-21 |
| Variety floor / copy cap | ≥ party size + 1 distinct designs; ≤ 3 copies of one design | `llm` layout validation | Stops a layout outnumbering the party with clones (beta playtest, 2026-08) |
| Boss pressure dials | `enrage_round` 3–5 (the validator accepts 2–6). `neglect` 1–2 | `llm._boss_pressure_problems` | Required on generated bosses: a timed enrage fuse, and +N/+N for each round the boss goes unhurt (2026-08-30). A boss built without them takes T-88's defaults |
| Objective gates | `race` needs 1–2 guards. `survive` needs ≥ 2 reinforcements. `deadline` runs 4–6 rounds | `llm._objective_problems` | Generation-side requirements for objectives (2026-08-30) |
| `_break_threshold` | ceil(max HP / 4) | `engine` | A single hit of ≥ 25 % max HP breaks a channel (GDD §8) |
| `in_execute_window` | effective HP × 4 ≤ max HP | `state.EnemyState` | At ≤ 25 % HP a boss becomes removable and enrages (GDD §9.4 / §9.5, §F-9) |
| `_defend_value` | Base Power (×2 with `defend_double`) | `engine` | Defend's temp HP. It was a flat 3 before 2026-08-21 |
| `_mitigate_value` | max(1, ceil(current Power / 2)); full Power with `mitigate_full` | `engine` | Mitigate's X (§M-A.2; the minimum of 1 comes from §D19-5) |
| Channel multiplier | ×1.5 | prompt | The cost of a channelled component, for its ongoing value |
| Later archetype costs | Ward 3, Counter 3 (reactive only), Resource attack 4 (sap 5) | prompt | Base costs added after §F-3.1 (§E6, 2026-08-21) without T-ids |
| Unregistered verb magnitudes | `lose_life` ceil(L/2)+1, `sap` 1 (2 at L5+), `drain_ultimate` 10–25 | prompt | Enemy verb schedule entries that never got T-ids (§D18-2, 2026-08-21) |
| Merchant stock | 4 items per weaponsmith or artificer, 6 per apothecary. Tier = act tier − 1. Uncommon at most | `items.roll_stock` | What a shop shelf rolls (§D17-4.3) |
| Spoils tier | act tier + 1 | `scenario.ScenarioRun.spoils_tier` | The tier boss drops (T-83) are forged at |
| `items.AFFIXES` points | For example Sturdy (+2 HP) 5, Keen (+1 Power) 10, Unbroken 35, Warded (hexproof, mythic, L6) 40 | `items` | Gear-rider prices on the level-up points scale. Warded's price comes from §D19-3 |
| `LEVEL_UP_POINTS` | 30 | `schema` | "A level-up's worth": the T-81 divisor, `scenario.GOLD_PER_LEVEL_UP`, and the character sheet's unit. It is the old T-57 value |
| Free baseline | 8 HP, 1 mana, 1 card. Base Power: melee 2, ranged 1 | `schema.BASELINE_HP` / `_MANA` / `_CARDS`, `BASE_POWER` | Update 05 §P-1, untagged |
| Resolution pacer | Beat 1.1 s, hold 0.6 s, step 0.18 s | `session.PACE_BEAT_S` / `PACE_HOLD_S` / `PACE_STEP_S` | Server-side pauses between auto-advance steps |
| `_AUTO_CAP` | 200 | `session` | The longest chain of synthetic auto-passes allowed |
| `LOG_TAIL` | 60 | `snapshot` | How many recent log entries are shipped to clients |
| Generation budgets | Encounter 24 000 tokens. Scenario 64 000 tokens / 1 200 s. Adventure timeout 900 s. Default timeout 120 s | `llm.ENCOUNTER_MAX_TOKENS`, `SCENARIO_MAX_TOKENS`, `SCENARIO_TIMEOUT`, `ADVENTURE_TIMEOUT`, `_chat` | LLM ceilings. The adventure token budget is T-63 |
| Harness gates | `ACTION_CAP` 20 000. Saturation `CEILING` 0.85 / `FLOOR` 0.15. `FLAG_PP` 10 pp with `MIN_SIDE` 2 | `runner`, `probes`, `enemy_analysis` | The in-turn loop backstop, the saturation warning, and the enemy-feature flag |

## Retune watch-list

- **Shipped encounters got easier.** Combat Abilities (§M-A.7, a code ruling of 2026-08-21) made 72 shipped enemy components answerable by Mitigate. Shipped content did not get the 2026-08-30 generation stat buff. Source: `engine._announce_combat_ability`, `tests/test_combat_ability.py`.
- **Defend temp HP = base Power** (`engine._defend_value`, 2026-08-21). This is a buff to high-Power heroes, and their gauge also charges +1 per temp HP. The *shape* is intended (Update 23: "the tank's second axis"). The *magnitude* is unverified.
- **Enrage at party size 4** (`content.enrage_scale`, §D18-2) gives ×4 on the pump's Power and ×2.5 on toughness, AoE and heal. Check how steep that is.
- **Gauge cost step c = 20** (`state.GAUGE_LEVEL_STEP`, 2026-08-29) was chosen conservatively. The target is control casters within ±20 % of damage casters on the runner's `gauge_per_turn` metric.
- **T-79 price curve.** The 2026-08-18 spend audit (`apps/autoplay-tester/SPEND_AUDIT_UPDATE_17.md`) found greedy-power over the ±4 pp band at every stage (a spread of about 19 pp). It blamed the greedy stick rather than the prices, so the gate is recorded as not met. Re-run the audit once the stick can spend its mana.
- **T-74 band** (`probes.OVER_PP` / `UNDER_PP`, ±4 pp) was not recalibrated for greedy-1.5.0. That was deliberate (2026-09-06).
- **T-81 [OPEN]** (§D17-10): does a fully geared party at derived level N play like level N+1?
- **Lockdown budget** (`llm._lockdown_budget`). The owner read standard as too easy, especially with larger parties, and wants *more* control pressure. Do not tune it down.

The owner does not currently trust the autoplay harness's absolute numbers. It is used for crash and anomaly detection and for A/B deltas within one run, so the harness-based targets above are directional only.

## Open register issues

These need a decision or a fix, and each is tracked in [roadmap.md](roadmap.md):

- **About 40 values are prompt-only (M4.8, M4.10).** T-01–T-24, T-26, T-28–T-32, T-34–T-36, T-39, T-47, T-53, T-65, T-67 and the prices in T-51 and T-56 are taught to the enemy designer as prose. No code prices an enemy or checks its Level against B(L), and a saved Options → LLM override can replace them.
- **The prompt contradicts itself on single-target damage.** Its magnitude table says L+2 (T-20, §D18-2), but its T-55 line still says "single target = L+1". `enemy_analysis.LEVERS` also still quotes L+1 and Drain ceil(L/2)+1.
- **Literals without constants (M9.7).** T-52 (`// 2`, twice) and T-45/T-46 (1 per counter).
- **Tunables without T-ids (M9.7).** Updates 18–24 added none. Candidates for T-89 onward: the stat buffs, the ability and row bonuses, `enrage_scale`, `ATTACK_CADENCE`, `EMERGENCY_BAND`, `DOUBLE_INTENT_DIFFICULTIES`, the lockdown budget, `GAUGE_LEVEL_STEP`, the boss-dial ranges (their build-time default is T-88), the variety floor, `_defend_value`, the later archetype costs, and the `lose_life` / `sap` / `drain_ultimate` magnitudes.
- **The history's own register tables are stale** (T-40, T-78, T-79, T-81 rows in §X-7 and §D17-11). This page supersedes them.

