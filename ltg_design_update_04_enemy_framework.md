# Langelier Tactical Game (LTG) — Design Update 04: Enemy Framework

**Status:** canonical framework for defining, generating, and running enemies. Assumes the base GDD and Updates 01–03. Amends §9 (enemies), §5.3 (priority — enemy reactions now exist). Where this document and prior documents disagree, **this document wins.**

**Purpose.** A generative framework: hand-authored test encounters now, LLM-generated encounters later. The LLM composes **thematic nouns from finite verbs** — it fills the schema in §F-1; the engine resolves everything deterministically. Nothing here adds new resolution logic: enemy abilities reuse the §11 primitive verbs, enemy movement uses the Update-02 position model, enemy zones use Update 03.

**Every number in this document is a playtest starting value.** Each carries a register ID (`[T-nn]`) and is collected in the Rebalance Register (§F-10) for post-playtest review. Mechanisms are canonical; magnitudes are provisional.

---

## F-1. The generative object

An enemy is fully defined by:

```
enemy = {
  name, flavor,
  faction_id,                      # must exist; constrains all palettes (§F-8)
  level: L,                        # derived: smallest L whose budget covers total cost (§F-6)
  chassis: <chassis_id + upgrades>,        # the body (§F-2)
  keywords: [ ... ],               # static properties, from the enemy-eligible set (§F-5)
  components: [ ... ],             # the mind: blended behaviors, both timings (§F-3)
  is_boss: false                   # boss hooks in §F-9
}
```

**Blends, not classes.** There is no fixed enemy taxonomy. "A tanky fighter that heals himself when hurt" or "an evasive hexer that debuffs from the shadows" are *compositions* — chassis + components + keywords. Named presets exist as conveniences (§F-2, §F-8), never as limits. Complexity self-prices: more components cost more budget, so intricate enemies are automatically higher level (§F-6).

---

## F-2. Chassis (the body)

A chassis sets the physical baseline: HP, Power, attack profile, home row. Chassis are **preset stat packages** (pre-spent budget) that upgrades can extend.

**Stat prices:** +1 HP = **1 pt** `[T-01]` · +1 Power = **3 pts** `[T-02]` · ranged attack (primary or fallback) = **2 pts** `[T-03]` · melee attack = free (default).

| chassis | HP | Power | attack | home row | cost |
|---|---|---|---|---|---|
| **Husk** | 2 | 1 | melee | front | 5 `[T-04]` |
| **Bruiser** | 4 | 2 | melee | front | 10 `[T-05]` |
| **Skirmisher** | 2 | 2 | melee + ranged fallback | mid | 10 `[T-06]` |
| **Artillery** | 2 | 2 | ranged | rear | 10 `[T-07]` |
| **Caster-frame** | 2 | 1 | ranged | rear | 7 `[T-08]` |

- **Upgrades:** any chassis may buy more HP/Power/attack modes at the listed prices.
- **Attack profile & fallback rule:** the basic attack deals **Power**. If the primary mode has no reachable target (melee vs. an unreachable row, per Update 01 §R-1), the enemy uses its **ranged fallback** if it has one; if neither reaches, it **Moves** toward reach (§F-7.3). Melee-preferred is the default posture.
- **Home row** is the spawn/redeploy row and the row its Move behavior regresses toward. Enemies use the player position model (current/committed, End-step resolution — Update 02 §M-B.7).

*(Anchor: the Level-1 Goblin Fighter from the UI schema — 2 Power / 3 HP — is Husk + 1 HP + 1 Power = 9 pts, inside the Level-1 budget of 10. The framework reproduces existing content.)*

---

## F-3. Components (the mind)

A component is one instantiated behavior. An enemy has any number, budget permitting. Each component contributes one or more **rules** to the enemy's single merged priority list (§F-7).

```
component = {
  archetype,                 # Burst | Evasive | Drain | Swarm | Fortify | Debilitate | Punish | Escalate  (§9.2)
  timing: proactive | reactive,
  trigger,                   # reactive only — from the trigger vocabulary (§F-3.2)
  condition,                 # optional gate, e.g. self_hp < 50%, turn >= 3, ally_count < 2
  cooldown,                  # turns between uses: 1 | 2 | 3 | once_per_encounter
  priority,                  # integer; lower = evaluated first (§F-7.1)
  verbs: [ ... ],            # §11 primitives only; magnitudes from §F-4
  target_rule,               # e.g. self | lowest_hp_ally | valuation (§F-7.2) | channeling_player
  telegraph                  # the intent text shown in the Intents list (proactive only)
}
```

### F-3.1 Component base costs (proactive, cooldown 2–3)
| archetype (typical verbs) | base cost |
|---|---|
| **Punish** (telegraphed retaliation: deal_damage on condition) | 3 `[T-09]` |
| **Fortify** (heal / pump / protection, self or ally) | 3 `[T-10]` |
| **Evasive** (repositioning behavior; pairs with flying/hexproof) | 2 `[T-11]` |
| **Burst** (ability damage above the basic attack) | 4 `[T-12]` |
| **Debilitate** (wound / stun / taunt-us / prevent) | 4 `[T-13]` |
| **Escalate** (recurring self-pump / +1/+1 counters) | 4 `[T-14]` |
| **Drain** (deal_damage + heal self, coupled) | 5 `[T-15]` |
| **Swarm** (create_token) | 6 `[T-16]` |

**Cost modifiers (multiplicative, round up):**
- Cooldown **1** (usable every turn): **×1.5** `[T-17]`
- Cooldown **2–3**: ×1.0 (baseline)
- **Once per encounter**: **×0.5** `[T-18]`
- **Reactive timing**: **+2 flat** after multipliers `[T-19]` (reactions deny player tempo; they price higher)

### F-3.2 Trigger vocabulary (reactive components)
`on_targeted` (this enemy is targeted by a spell/attack) · `on_hit` (damage resolved on this enemy) · `on_ally_hit` · `on_ally_death` · `on_spell_cast` (any player spell goes on the stack) · `on_ally_below_X%` · `on_incoming_lethal` (a resolving action would kill this enemy). Additions to this list are schema changes and need a design update.

### F-3.3 Reaction pacing (hard rules)
- **One reaction per trigger window per enemy** — when a window opens, the enemy fires at most the single top-priority eligible reactive rule.
- Cooldowns and conditions gate eligibility exactly as for proactive rules.
- **Player-only keywords stay player-only:** first strike, vigilance, haste (turn-economy keywords) never appear on enemies.

---

## F-4. Verb magnitudes by level

Component effects scale with the enemy's Level L. Standard magnitudes (a generated component uses these unless it explicitly buys an off-schedule value — not allowed in Phase 1):

| verb | magnitude at Level L |
|---|---|
| deal_damage (Burst/Punish) | **L + 1** `[T-20]` |
| Drain (damage & self-heal, each) | **ceil(L/2) + 1** `[T-21]` |
| heal (Fortify) | **L + 2** `[T-22]` |
| pump / wound | **±ceil(L/3) / ±ceil(L/3)** `[T-23]` |
| counters (+1/+1, Escalate) | **+1/+1 per firing** `[T-24]` |
| stun / taunt / strip_intent | no magnitude (binary) |
| prevent [param] | duration **1 turn** `[T-25]` |
| create_token | token = Husk chassis at level **ceil(L/2)** `[T-26]`, max **2 alive per creator** `[T-27]` |
| grant_keyword | from the enemy-eligible set; the keyword's min-level (§F-5) still applies to the *recipient's* level |

---

## F-5. Enemy-eligible keywords

| keyword | min level | cost |
|---|---|---|
| reach | 1 | 1 `[T-28]` |
| trample | 2 | 2 `[T-29]` |
| flying | 2 | 4 `[T-30]` |
| lifelink | 3 | 3 `[T-31]` |
| deathtouch | 3 | 4 `[T-32]` |
| protection | 4 | 3 `[T-33]` |
| hexproof | 4 | 4 `[T-34]` |
| indestructible | 6 | 6 `[T-35]` |

**Never on enemies:** first strike, vigilance, haste (player action-economy only). Keyword meanings per Update 01 §R-1/§R-7 and GDD §7.

---

## F-6. Budget & level

**Budget:** `B(L) = 5·L + 5` `[T-36]` → L1 = 10, L2 = 15, L3 = 20, L5 = 30, L8 = 45, L10 = 55.

**Total cost** = chassis (incl. upgrades) + keywords + components (after modifiers).
**Level is derived:** the enemy's Level is the smallest L with `B(L) ≥ total cost`. Underspending is legal (a simple high-level enemy); overspending is impossible. This is what makes complexity self-balancing: a three-component conditional enemy *cannot exist* at level 2 — the budget won't cover it.

**Encounter budget:** an encounter's total enemy Levels ≈ **2 × (party size) × (average party level)** `[T-37]`, scaled by difficulty: easy ×0.75, standard ×1.0, hard ×1.5 `[T-38]`. (Soren + Ys at level 1 → standard encounter ≈ 4 total enemy Levels.) Boss encounters use §F-9 instead.

---

## F-7. The heuristic (merged priority list)

### F-7.1 One list, two passes
All rules from all components merge into **one priority-ordered list** (lower number first). The engine evaluates it **first-match-wins** in two passes:

- **Proactive pass** — Intents step: evaluate `proactive` rules; the top rule whose condition holds, cooldown is ready, and target exists **declares** as this turn's intent (telegraphed). Executes in the Enemy step.
- **Reactive pass** — whenever a trigger window opens (§F-7.4): evaluate `reactive` rules whose trigger matches; the top eligible rule fires as a reaction.

**Priority band conventions** (authoring guidance, not engine rules): 10–19 emergencies (self-preservation, `on_incoming_lethal`), 20–49 tactical opportunities (conditions/cooldown abilities), 90 the default basic attack. Every enemy's list **must terminate in the default Attack rule at priority 90** (with Move-toward-reach as its built-in fallback), so the proactive pass always produces an intent.

Ties: equal priority resolves by component list order (authoring order). Fully deterministic.

### F-7.2 Target valuation (the default-attack brain)
When a rule's target_rule is `valuation`, candidates are first filtered by **reachability** (Update 01 §R-1: melee = front-most occupied row + flyer rules; ranged = any row), then ranked:

1. **Finishable** — effective HP ≤ this hit's damage → highest such target.
2. **Channel-breakable** — target is channeling and this hit ≥ 25% of its max HP (GDD §8) → break it.
3. **Role value** — actively-casting/support targets first (Caster-frame equivalents, Menders), then ranged, then melee.
4. **Lowest current HP.**
5. **Deterministic tiebreak** — row order (front > mid > rear), then alphabetical name.

This is what makes an archer snipe the exposed channeler and a brute finish the wounded frontliner without scripting either.

### F-7.3 Movement rule
If no target is reachable by primary or fallback attack, the proactive pass emits **Move** toward the nearest row that grants reach (End-step resolution, Update 02). Evasive components may inject higher-priority repositioning rules (e.g. "if targeted by melee last turn, move away from front").

### F-7.4 Priority loop (players first, enemies answer)  *(amends §5.3)*
Enemy reactions now exist. The stack loop, applied recursively:

1. An action goes on the stack (player play, enemy intent execution, or enemy reaction).
2. **Players** receive priority in order (Update 01 §R-6); each may respond or pass.
3. When **all players pass**, eligible **enemy reactions** evaluate (one per enemy per window, top-priority first across enemies in §R-6 order).
4. Any enemy reaction is a **new stack action → return to step 2** (players may answer it).
5. When all players pass **and** no enemy reaction fires, the top stack item resolves.

**Termination guarantee:** every enemy reaction consumes a cooldown/once-per-window eligibility, so each window strictly reduces the eligible set; the loop cannot ping-pong indefinitely. (Implementation note: assert progress — a window that fires no new reaction must resolve the stack top.)

---

## F-8. Faction manifest (thematic cohesion)

An encounter draws **all** enemies from one faction. The manifest is the contract handed to the LLM — cohesion by construction (no frost giants in the vampire coven, because the palette doesn't contain them):

```
faction = {
  id, name, flavor,
  colors: [ ... ],                       # ≤3, like player identities
  allowed_chassis: [ ... ],
  allowed_keywords: [ ... ],             # subset of §F-5
  allowed_components: [ archetype+verb pairings ... ],
  role_presets: [ named example blends ... ],
  boss_hooks: [ ... ]                    # deferred, §F-9
}
```

### Example: **The Crimson Coven** (vampires)
Colors B/R. Chassis: Husk, Skirmisher, Caster-frame, Bruiser. Keywords: flying, lifelink, deathtouch, hexproof. Components: Drain (signature), Swarm (bats), Debilitate (curses), Fortify (blood rituals), Evasive. Presets: Grave Thrall, Bloodbat, Vampire Adept; boss hook: Vampire Lord.

**Worked statblocks (playtest-ready):**

| | **Grave Thrall** | **Bloodbat** | **Vampire Adept** |
|---|---|---|---|
| Level (budget) | 1 (10) | 2 (15) | 4 (25) |
| Chassis | Husk +4 HP → **6 HP / 1 Pwr**, melee, front (9) | Skirmisher-base → **2 HP / 2 Pwr**, melee, mid (10) | Caster-frame +4 HP → **6 HP / 1 Pwr**, ranged, rear (11) |
| Keywords | — | flying (4) | lifelink (3) |
| Components | — (default Attack only) | Evasive (2): *if hit by melee last turn, reposition* | Drain (5, cd 2, prio 30): deal **3**, heal self **3**, target = valuation · Debilitate **reactive** (6, cd 2, prio 20): `on_spell_cast` → wound **−1/−1** the caster |
| Spent | 9/10 | 16→ trimmed: Evasive at cd 3 ⇒ 15/15 | 25/25 |
| Plays like | a wall that shambles forward | a dodging harasser only ranged/reach answers cleanly | the piece you must answer: drains from safety, punishes your casting |

**The two blends that motivated this framework** (both legal, both priced honestly):

- **Ironhide Warleader — "tanky fighter that heals when hurt" (L5, 30):** Bruiser +6 HP +1 Pwr → 10 HP / 3 Pwr melee front (19) · trample (2) · **Fortify-self** (3, cd 2, **prio 10**, condition `self_hp < 50%`): heal **7** · **Punish reactive** (5, cd 2, prio 25): `on_hit` by melee → deal 2 to the attacker. Total 29/30. Healthy → it swings; bloodied → the heal rule's condition flips true and outranks the attack. The condition **is** the arbitration.
- **Mistveil Hexer — "evasive magic rogue" (L4, 25):** Skirmisher +3 HP → 5 HP / 2 Pwr (13) · hexproof (4) · **Debilitate** (4 ×1.5 cd-1 = 6, prio 30): stun or wound −1/−1, target = valuation · Evasive (2, prio 20): reposition when melee-threatened. Total 25/25. Hard to pin (hexproof + repositioning), chips your action economy every turn.

---

## F-9. Bosses & deferred hooks

**Bosses (deferred, hooks now):** `is_boss = true` grants the existing rules (removal-immune outside the execute window §9.4; enrage at ≤25% §9.5; bounce-resistant per Update 03 §E-E). Framework hooks already in the schema: boss budget = **B(L) × 2.5** `[T-39]`; components may carry a **phase gate** (`phase: pre_enrage | post_enrage`); the **enrage ability is a free once-per-encounter component** (not budget-priced) that auto-fires at the threshold. Full boss specs are a future update.

**Also deferred:** off-schedule verb magnitudes; new trigger events; enemy mana/resources (none — availability rules *are* the enemy economy); multi-faction encounters.

---

## F-10. Rebalance Register

Every tunable, in one place. Post-playtest, review this table — nothing else in the document needs to change unless a *mechanism* fails.

| ID | value | what it sets |
|---|---|---|
| T-01 | 1 pt | cost per +1 HP |
| T-02 | 3 pts | cost per +1 Power |
| T-03 | 2 pts | cost of a ranged attack mode |
| T-04..08 | 5/10/10/10/7 | chassis package costs (Husk/Bruiser/Skirmisher/Artillery/Caster-frame) |
| T-09..16 | 3/3/2/4/4/4/5/6 | component base costs (Punish/Fortify/Evasive/Burst/Debilitate/Escalate/Drain/Swarm) |
| T-17 | ×1.5 | cooldown-1 multiplier |
| T-18 | ×0.5 | once-per-encounter multiplier |
| T-19 | +2 | reactive-timing premium |
| T-20 | L+1 | Burst/Punish damage |
| T-21 | ceil(L/2)+1 | Drain damage & heal |
| T-22 | L+2 | Fortify heal |
| T-23 | ±ceil(L/3) | pump/wound size |
| T-24 | +1/+1 | Escalate counters per firing |
| T-25 | 1 turn | prevent duration |
| T-26 | ceil(L/2) | spawned-token level |
| T-27 | 2 | max live tokens per creator |
| T-28..35 | 1/2/4/3/4/3/4/6 | keyword costs (reach/trample/flying/lifelink/deathtouch/protection/hexproof/indestructible) — min levels 1/2/2/3/3/4/4/6 |
| T-36 | 5L+5 | budget per level |
| T-37 | 2×size×level | encounter Level budget |
| T-38 | 0.75/1.0/1.5 | difficulty multipliers |
| T-39 | ×2.5 | boss budget multiplier |

---

## F-11. Glossary deltas  *(amends §13)*

- **Chassis** — an enemy's physical baseline (HP, Power, attack profile, home row); a pre-priced stat package plus upgrades.
- **Component** — one instantiated behavior (intent archetype + timing + trigger/condition + cooldown + priority + verbs); enemies blend any number.
- **Merged priority list** — the single ordered ruleset formed from all of an enemy's components; evaluated first-match-wins in a proactive pass (intent declaration) and reactive passes (trigger windows).
- **Budget / Level (enemy)** — Level derives from budget spent (`B(L)=5L+5`); complexity self-prices into level.
- **Faction manifest** — the themed palette (colors, chassis, keywords, components, presets) that all enemies in an encounter draw from.
- **Trigger window** — the moment after all players pass priority in which at most one reaction per enemy may fire; an enemy reaction re-opens player priority.
