# Langelier Tactical Game (LTG) — Design Update 05: Character Build & Progression

**Status:** canonical framework for player-character construction and progression. Assumes the base GDD and Updates 01–04. Amends §10 (archetypes → presets) and §4.7 (Power as a bought stat). Where this document and prior documents disagree, **this document wins.**

> **SCOPE NOTICE — read before implementing.**
> Only **§P-1 through §P-4 (level-1 character creation)** are **scheduled for implementation now**. Everything from **§P-5 onward (leveling, XP, progression loop) is `[DESIGNED — NOT SCHEDULED]`**: fully specified so the design isn't lost, but **not to be built** until enemy/encounter generation and multi-encounter progression exist. A creation-only Deckbuilder must not surface any escalating cost, XP value, or level-up affordance — those costs do not appear in a level-1 tool.
>
> **All numbers are playtest starting values**, collected in the Rebalance Register (§P-8). Mechanisms are canonical; magnitudes are provisional.

---

## P-0. The core idea

Character build is a **points-buy against a budget**, mirroring the enemy budget system (Update 04 §F-6). Complexity self-prices: the same 70-point creation budget produces a simple tank or a fragile flying specialist, and the four GDD archetypes become **named 70-point presets**, not a closed taxonomy. There is no separate "custom" archetype — *custom* is simply not choosing a preset and spending your own 70. Progression (deferred) is the same buy repeated: leveling grants points, spent against a cost curve that escalates after a flat band.

---

## P-1. Creation baseline & budget  *(scheduled)*

**Baseline (free):** every character starts with
- **8 HP**
- **1 mana capacity**
- **1 starting card**
- **one attack mode** — either **melee Power 2** or **ranged Power 1** (chosen; the other mode is not owned).

**Creation budget: 70 points** `[T5-01]`.

Melee's higher free base (2 vs. ranged's 1) is its compensation for being row-restricted (Update 01 §R-1); marginal Power costs the same in either mode.

---

## P-2. Creation cost table  *(scheduled — flat costs only)*

At **creation**, all tracks are **flat** (the escalating cliff of §P-6 applies only to *earned leveling points*, never to creation):

| Buy | Cost |
|---|---|
| +2 HP | 5 `[T5-02]` |
| +1 mana capacity | 15 `[T5-03]` |
| +1 starting card | 15 `[T5-04]` |
| +1 Power (above your mode's base) | 10 `[T5-05]` |
| 1 keyword (max one) | per §P-3 |

HP is bought in **2-point steps** (so total HP is always even). Mana, cards, and Power are bought per single unit.

---

## P-3. Keywords at creation  *(scheduled)*

- **Maximum ONE keyword** per character at creation `[T5-06]`. Additional keywords must come from gear/spells in play, not the build.
- Allowed set (costs provisional):

| keyword | cost | | keyword | cost |
|---|---|---|---|---|
| reach | 5 `[T5-07]` | | haste | 15 `[T5-11]` |
| trample | 10 `[T5-08]` | | vigilance | 20 `[T5-12]` |
| first strike | 15 `[T5-09]` | | flying | 25 `[T5-13]` |
| lifelink | 15 `[T5-10]` | | | |

- **Banned at creation (hard stop):** protection, hexproof, indestructible, deathtouch. (These may still exist on enemies per Update 04 §F-5 and could appear via gear/spells later, but are not player-buildable.)
- **Player-only availability:** first strike, vigilance, haste — enemies can never have these (Update 04 §F-3.3), so the points system is the *only* place they appear. Keyword meanings per Update 01 §R-1/§R-7 and GDD §7.

---

## P-4. Guardrails  *(scheduled)*

A linear points-buy invites degenerate min-maxing; these floors and caps bound it:

- **Floors:** HP ≥ 8, mana ≥ 1, cards ≥ 1, at least one attack mode.
- **Power cap at creation:** melee ≤ 4, ranged ≤ 3 (i.e. **at most +2 Power** bought) `[T5-14]`. Without this, 70 points into melee Power buys a Power-9 basic attack (Mitigate 5), which is degenerate.
- **Keyword cap:** 1 (§P-3).

*(Note for later: under the §P-6 leveling curve the Power cliff makes extreme Power dumps economically self-limiting, so this hard cap may be reviewed once leveling exists. At creation it stays.)*

---

## P-4b. The four archetypes as presets  *(scheduled — validation)*

The GDD archetypes are pre-spent 70-point builds. **Each costs exactly 70 from baseline** — the proof the points system generalizes the archetypes rather than replacing them. (HP shown is re-baselined to even values ~20% below the old GDD numbers, the unique set that preserves 70-point equality under the new 8-HP base.)

| | HP | mana | cards | attack profile | Mitigate | build (from baseline) |
|---|---|---|---|---|---|---|
| **Fighter** | 20 | 2 | 2 | Melee, Power 3 | 2 | +12 HP (30) + 1 mana (15) + 1 card (15) + 1 Pwr (10) = **70** |
| **Tactician** | 12 | 2 | 4 | Ranged 1 *or* Melee 2 | 1 | +4 HP (10) + 1 mana (15) + 3 cards (45) = **70** |
| **Caster** | 8 | 3 | 3 | Ranged 2 *or* Melee 1 | 1 | +2 mana (30) + 2 cards (30) + 1 Pwr (10) = **70** |
| **Channeler** | 12 | 4 | 2 | Ranged 1 *or* Melee 2 | 1 | +4 HP (10) + 3 mana (45) + 1 card (15) = **70** |

For optioned attack profiles, the mode is chosen at creation and fixed. Mitigate value = ceil(current Power / 2) (Update 02 §M-A.2), shown at base Power.

**Reference custom build — "Ys the fae" (flying glass cannon):** flying (25) + 3 cards (45→ i.e. +2 cards = 30) ... = flying (25) + 2 cards (30) = 55, +15 → +1 mana. Result: **8 HP, 2 mana, 3 cards, Ranged 1, Flying = 70.** An honest trade vs. canonical Ys: flying is expensive enough that a flying character is genuinely fragile.

---

## P-4c. Engine integration seam  *(scheduled — verify before building UI)*

The Deckbuilder's build step outputs a **resolved stat block** — `{ hp, mana_capacity, starting_cards, attack_profile: {mode, power}, keywords[] }` — and the combat engine must **consume that stat block**, not instantiate characters by archetype name. If the engine currently hardcodes Fighter/Tactician/etc., converting it to take a stat block is the **first** task (before the Deckbuilder UI), because the points system depends on that seam existing. Archetypes then become preset stat blocks the Deckbuilder can load.

---

---

# `[DESIGNED — NOT SCHEDULED]` — everything below is captured for later, not built now

## P-5. Progression model (overview)

Leveling is the creation buy, repeated: each level grants points, spent on the same tracks, against a cost curve that is flat for a while then cliffs. This means **no per-archetype leveling trees** — the cost curves shape every character's path, and rounding-out becomes the economically optimal play without authored guidance.

**Grant: 20 points per level `[T5-15]`, bankable** (unspent points carry forward with no cap).

---

## P-6. Leveling cost curve (flat-then-cliff)

Applies to **earned leveling points only** (creation stays flat, §P-2). Cost depends on how many steps you already own in a track (**"step #" counts purchased steps, base is free**). HP stays flat forever — the always-affordable survival valve.

| step # (already owned) | +1 Power | +1 mana | +1 card | +2 HP |
|---|---|---|---|---|
| 1st | 10 | 15 | 15 | 5 |
| 2nd | 10 | 15 | 15 | 5 |
| 3rd | 10 | 15 | 15 | 5 |
| 4th | 25 `[T5-16]` | 30 `[T5-18]` | 25 `[T5-20]` | 5 |
| 5th | 40 `[T5-17]` | 50 `[T5-19]` | 40 `[T5-21]` | 5 |
| 6th+ | +20 each | +25 each | +20 each | 5 |

- **Flat band = the first 3 purchased steps** at base cost, so a character can reach its *defining* specialization (Tactician's 4 cards = 3 bought, Channeler's 4 mana = 3 bought) without penalty. The cliff bites only on the **4th purchased step onward** — i.e. *over*-specialization beyond role identity.
- **Cost attaches to your current total, permanently:** banking points to afford a later step does not dodge escalation; it just lets you save toward an expensive one.
- **Self-limiting extremes:** buying Power to +7 costs 235 earned points, so the cliff enforces sanity economically (the §P-4 hard Power cap may be relaxed post-level-1 in light of this).
- Unified curve: because no archetype reaches the 4th step in any track at creation, the same curve can govern creation and leveling with no special-case boundary; creation is simply the region below the first cliff.

---

## P-7. XP & the run loop

### P-7.1 XP award (per encounter)
- **Per enemy:** `XP = 10 × enemy level` `[T5-22]`, summed across the encounter.
- **Per boss:** `XP = 20 × boss level` `[T5-23]`.

### P-7.2 Per-character XP (party-size normalization)
Encounter XP is **split evenly per character** (`encounter_total ÷ party_size`), so each character earns ~`20 × level` per standard fight **independent of party size** — a 4-player party kills a 4×-bigger encounter (Update 04 §F-6, T-37) and splits a 4×-bigger award, netting the same per head. All party members in an encounter receive an **equal share** (lockstep), so no character desyncs. *(In the standalone single-party run of P-7.4, lockstep is automatic — the whole party fights every encounter.)*

### P-7.3 Cost to level
`XP to reach next level = (30 + 7 × party_size) × current_level` `[T5-24]`.
Award scales with level and cost scales with level, so **pace is constant across the whole game**; party size shifts it deliberately (solo ≈ 1.9 fights/level, four ≈ 2.9 fights/level — the intended 2-to-3 spread). Party-size changes re-evaluate the formula from that point forward; no retroactive recompute.

### P-7.4 Standalone run structure (the eventual harness → game)
`character select → [ encounter → resolve → XP / level-up review → (save?) → next encounter ] repeat until party wipe → run summary.`
- **Save/Load** serializes the whole run as one blob (party builds + XP + unspent points + current encounter/depth). **Save points are between encounters only** (at the level-up review), never mid-combat — avoids serializing the stack, pending reactions, positions, and cooldowns.
- **Harness-first defaults** (each flippable later): fixed authored encounter sequence (deterministic, for balancing) before depth-scaling generation; **full heal between encounters** (test each encounter in isolation) before attrition-carry. These are the biggest run-feel levers and are deferred decisions, not locked.

---

## P-8. Rebalance Register

| ID | value | sets |
|---|---|---|
| T5-01 | 70 | creation budget |
| T5-02 | 5 / +2 HP | HP step cost (creation & all levels) |
| T5-03 | 15 | +1 mana (creation, flat) |
| T5-04 | 15 | +1 card (creation, flat) |
| T5-05 | 10 | +1 Power (creation, flat) |
| T5-06 | 1 | max keywords at creation |
| T5-07..13 | 5/10/15/15/15/20/25 | keyword costs (reach/trample/first strike/lifelink/haste/vigilance/flying) |
| T5-14 | +2 (melee≤4, ranged≤3) | creation Power cap |
| T5-15 | 20 | leveling points per level (bankable) |
| T5-16,17 | 25, 40 | Power 4th/5th step (cliff) |
| T5-18,19 | 30, 50 | mana 4th/5th step |
| T5-20,21 | 25, 40 | card 4th/5th step |
| T5-22 | 10 × enemy level | XP per enemy |
| T5-23 | 20 × boss level | XP per boss |
| T5-24 | (30 + 7×size) × level | XP to next level |

---

## P-9. Glossary deltas  *(amends §13)*

- **Creation budget** — the 70 points spent at character creation against flat costs (§P-2).
- **Preset** — a named full-budget build (the four archetypes); a starting point, not a class.
- **Leveling curve** — the flat-then-cliff cost schedule (§P-6) governing earned points; flat for 3 purchased steps per track, then escalating.
- **Stat block** — the resolved output of a build (`hp, mana_capacity, starting_cards, attack_profile, keywords`) that the engine consumes in place of an archetype name.
- **Run** *(deferred)* — a chained sequence of encounters played by one party until wipe, saved/loaded as a single blob.
