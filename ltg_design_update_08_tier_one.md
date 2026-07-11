# Langelier Tactical Game (LTG) — Design Update 08: Tier One — Veiled Intents, Afflictions & Charge, Heroic Actions, and Flow

**Status:** canonical design, **not yet built**. Where this document and prior documents (GDD, Updates 01–07) disagree, this document wins. Mechanisms below are canonical; magnitudes are playtest starting values, collected in the Rebalance Register (§D8-7).

**Purpose.** Four systems, chosen as the highest-leverage set from the 2026-07 design review:

1. **Veiled intents** (§D8-1) — the middle ground between the original fully-open telegraphs (too solvable) and the current fully-hidden build (guts the pre-stack disruption game). Enemy intents reveal a *generic category and a target*, never text or numbers.
2. **Afflictions & charge** (§D8-2) — three typed counters: **poison** (ticking −0/−1), **regen** (ticking +0/+1), and enemy-only **charge** (a visible gauge that detonates a hidden ability at a threshold — the windup mechanic). Plus one new keyword, **infect** — the creature's damage also poisons.
3. **Heroic actions** (§D8-3) — two new per-character abilities authored in the Deckbuilder: a once-per-encounter **Skill** (instant speed) and a once-per-encounter **Ultimate** (an action, gated behind a 0–100 **ultimate gauge** charged by play). Plus optional flavour for the evergreen abilities.
4. **Smart auto-pass & auto end-turn** (§D8-4) — the engine-truth version: a character with nothing meaningful to do is passed for, silently.

These systems interlock: veiling makes charge dramatic ("it's gathering power — for *what*?"), poison is the anti-turtle clock, the gauge makes taking hits and defending *earn* something, and auto-pass pays the click-tax the new reactive options would otherwise raise.

---

## D8-0. Drift note: intent visibility

The GDD (§4.2, §5.2, §9.3) and README describe intents as fully visible — text, amount, and target, declared before the player acts. Playtest found this too solvable: full text + locked target + deterministic numbers let the party compute the exact answer every round. The current build swung to **fully hidden**, which broke different things: `strip_intent` became a blind gamble, Mitigate became guesswork, and the GDD's "disrupt the intent (pre-stack)" surface lost its meaning. Additionally, the current build only hides intents *in the UI* — `snapshot.py:_intents` still ships full intent text, amounts, and targets to every client, so the information is one devtools-tab away.

§D8-1 replaces both extremes. GDD §4.2/§5.2/§9.3 and the README's intent passages are amended to match.

---

## D8-1. Veiled intents

### D8-1.1 The rule

An enemy intent, while declared and not yet on the stack, reveals exactly **two things**: a **category** (one of a small closed set, rendered as a generic line) and its **locked target** (a named character, a row, the whole party, or a fellow enemy). It never reveals ability names, verbs, magnitudes, keywords, or whether it is a channel.

**The stack is honest.** Veiling applies *only* to the intent phase. When the enemy executes and the action goes on the stack, the party sees the real action in full — name, effects, amounts — exactly as today. Counters and reactions are therefore always chosen against complete information; only *pre-stack* play (Mitigate planning, strip/stun decisions, positioning) works under uncertainty.

**Reactive components do not telegraph at all.** An enemy reaction is invisible until it fires onto the stack. (This codifies the current build; the GDD's "telegraphed trigger" phrasing is retired.)

### D8-1.2 Categories and template lines

The category is **derived deterministically** from the declared intent — from its verbs, `action_type`, and target descriptor — never authored. The engine emits the category + target; the template text below is presentation (a client-side registry, freely rewordable without touching the engine).

| category | derivation | template line |
|---|---|---|
| **threat** | hostile non-spell action at one hero (attacks, physical abilities, ability-class control) | "The Spore Husk threatens Soren." |
| **spellcraft** | any `action_type: "spell"` action, including channels; with the locked target if it has one | "The Myconid Mother begins casting a spell at Soren." / "… begins casting a spell." |
| **row assault** | damage or hostile effects aimed at a row | "The Archer prepares an assault on the front of your party." |
| **party assault** | hostile `mode: all` on the hero side | "The Ashen Tyrant prepares an assault on your whole party." |
| **gathering** | the intent's verbs include `charge` (§D8-2.4) | "Orgen the Dungeonmaster gathers its power." |
| **support** | heal / pump / protection / ward aimed at the enemy side; self-target reads reflexively | "The Cinderpriest turns its attention to the Bonechanter." / "The Warleader steels itself." |
| **summon** | `create_token` | "The Broodmother calls for reinforcements." |
| **manoeuvre** | a pure reposition (Evasive `move_home`, movement toward reach) | "The Gull-Shade shifts its footing." |

Notes:

- A stun or taunt delivered as an ability reads as **threat**; delivered as a spell it reads as **spellcraft**. The ambiguity is deliberate — "threatens" promises *hostility*, not damage.
- Multi-verb intents classify by their **first hostile verb**; a `charge` verb anywhere classifies as **gathering** (the windup dominates the fiction).
- Category-with-target is the *entire* pre-stack information contract. In particular Mitigate is now planned knowing *who* is in danger but not *how hard* the blow lands.

### D8-1.3 Disruption under the veil

`strip_intent`, `stun`, kill, and debuff all work unchanged — the party simply acts on partial information. One reward rule: **stripping an intent reveals it.** The log line names what was prevented ("Ys unravels what would have been *Cinder Breath — deal 7*"). Paying a card buys the information along with the tempo; it also teaches the enemy's kit across a fight.

### D8-1.4 Information enforcement (the seam that must move)

Veiling is a **server contract, not a UI courtesy.** The seat-filtered snapshot (`apps/game-server/ltg_game_server/snapshot.py:_intents`) must emit only `{enemy_id, category, target_id, target_name, line}` — never the intent's name, verbs, or amounts. `serialize.py`'s full `_enemy_dict["intent"]` remains for the **cockpit**, which is a debugger and sees everything. The `telegraph` authoring field on components is retained: it is no longer shown pre-stack, but it names the action when it hits the stack, feeds the strip-reveal line (§D8-1.3), and is narrator fodder later.

### D8-1.5 UI: the intents window

A dedicated panel in the side column, **below the stack and above the combat log**, listing one line per living enemy for the current round, in enemy board order. Behaviour:

- Lines appear at the Enemy Intents step and persist through the round.
- A stripped intent's line is struck through and annotated with the reveal (§D8-1.3); a stunned enemy's line reads "The Spore Husk reels — it has no intent."
- Hovering a line highlights the enemy and its target on the battlefield, and vice versa.
- When an intent executes, its line is struck; the real action appears on the stack panel above as usual.

---

## D8-2. Afflictions & charge (typed counters)

Three new counter types join the existing persistent `+1/+1` counters. All counts are **public information** on both sides — the pips are visible; for charge, what the pips *feed* is not. The registry is deliberately closed: poison, regen, charge, and nothing else without a design update.

### D8-2.1 Poison

**A poison effect**, when it resolves on a creature, places one poison counter per point of its `amount` immediately, then places the same again **at the start of each Upkeep step**, until it **concludes**. Each poison counter is a persistent **−0/−1**: −1 maximum HP and −1 current HP as it lands. Lethality is checked as always on effective HP — poison kills.

- **Poison is not damage.** It does not trigger `on_hit` or Punish, cannot be Mitigated or `prevent`ed, does not feed lifelink or deathtouch, and — because no single *hit* is landing — **never breaks a channel**. It is the answer to turtles and to channelers alike: a clock that ignores the shield wall.
- **Stacking.** Multiple poison effects on one creature each tick independently: two active effects of `amount: 1` place −0/−2 total each Upkeep.
- **Concluding.** A poison effect ends when: (a) the creature dies; (b) the creature **receives healing** — any resolved `heal` or lifelink event on it, even one that restores 0 HP, ends *all* poison effects on it (an antidote is an antidote); or (c) its optional bound expires: an effect authored with `turns: X` ticks at the next X Upkeeps and then concludes on its own.
- **Healing sheds the counters** *(playtest ruling, supersedes the original "counters persist")*. Concluding by **healing** (case b) does more than stop the ticking: it also **removes the accumulated poison counters**, reversing each one's −0/−1 (+1 maximum HP and +1 current HP, current clamped to the restored maximum — the exact inverse of how they landed). A healed creature is rid of the venom entirely, counters and all; the heal that cures then fills current HP on top. The other conclusion causes (death, the `turns` bound) leave the counters in place — they persist like any counters until removed, annihilated by regen, or the encounter ends. **A regen tick is the exception:** although it counts as healing and cures the ticking, it does **not** shed poison counters — regen's counter interaction is the separate 1:1 annihilation (§D8-2.2), not a wholesale purge.

### D8-2.2 Regen

The mirror. **A regen effect** places `amount` regen counters on resolution and again at each Upkeep until it concludes. Each regen counter is a persistent **+0/+1**: +1 maximum HP and +1 current HP as it lands.

- **A regen tick counts as healing.** It fires `on_hero_healed`-class triggers, fills wounds, and — per §D8-2.1 — **cures poison**. Regen is the over-time antidote.
- **Concluding.** A regen effect ends when: (a) the creature is **dealt damage that connects** (≥1 after mitigation/prevention — a fully absorbed hit does not break regen); or (b) its optional `turns: X` bound expires. Counters remain either way.
- **Annihilation.** A poison counter and a regen counter on the same creature **annihilate 1:1** as a state-based action, exactly as ±1/±1 counters would. Net state is always one type or neither.

### D8-2.3 Poison and regen as effect primitives

Two new leaf effects in the vocabulary (§X-2 grows to 27):

```
poison { amount, turns?, target }     # counters placed now and per Upkeep
regen  { amount, turns?, target }     # turns absent = until concluded by rule
```

Both take the standard target descriptor; both are legal on either side (an enemy Debilitate poisons a hero; a translated Wither/Infect-style card poisons an enemy; a hero enchantment grants an ally regen). Translation sources: infect/wither/poison-counter text and "regenerate"/"gains +0/+1"-over-time text map naturally; exact regex mappings are Deckbuilder work.

Upkeep ticks are **state-based, not stack events** — they do not open reaction windows (the counters are the drama; the tick is bookkeeping). Deaths from a poison tick fire death triggers normally. Tick order within Upkeep: after mana refresh and draw, before recurring channel effects, party side then enemy side, each in board order — deterministic.

### D8-2.4 Charge (enemy-only, for now)

Charge counters are the **windup mechanic**: a visible gauge on an enemy that detonates a hidden ability.

- **Gaining charge.** A new verb, `charge { amount }`, targets self and places `amount` charge counters. It is **enemy-only** (validation rejects it in a loadout, like `draw` on an enemy). A proactive component whose verbs include `charge` telegraphs as **gathering** (§D8-1.2) — "…gathers its power."
- **The trigger.** A reactive component with `trigger: "on_charge_full"` and a `charge_threshold: Y` fires **the moment the enemy's charge reaches Y** — immediately, mid-step, going **on the stack** like any enemy reaction, where the party may respond in full view of what it now is.
- **The reset.** Charge resets to 0 **when the triggered ability hits the stack** — not when it resolves. Countering the detonation still consumes the charge. This is the counterplay contract: eat it, counter it, or prevent it from ever filling (kill, stun the gatherer, strip the gather intent).
- **Visibility.** The charge count and threshold pips are public (the party watches the gauge fill); the triggered component's content is hidden until it fires (§D8-1.1).
- **Magnitude & pricing.** A charge-triggered component may spend verb magnitudes up to **2× the level schedule** (Update 04 §F-5) — the multi-turn delay, full visibility of the gauge, and disruptability are the price. Component costing: the gather component prices as **Escalate (4)**; the triggered component prices at its archetype's base with the usual reactive +2, no further modifier. Threshold must require **at least two gather resolutions** (Y ≥ 2 × the gather's amount) — a one-turn "windup" is just a Burst and must be priced as one.

Player-side charge does not exist; the **ultimate gauge** (§D8-3.3) is the player analogue, and keeping the two mechanics asymmetric is deliberate.

### D8-2.5 The `infect` keyword *(amends GDD §7)*

**`infect` — any damage this creature deals also applies a poison effect to the victim.** A cousin of MTG's infect, not a copy: the damage itself lands on HP as normal, *and* the victim gains one poison effect of `amount: 1`, unbounded, whose **first counter lands at the next Upkeep** (unlike the `poison` primitive, which places its first counter on resolution — a venomed blade wounds now and sickens later).

- **Infect reads damage that connects** (§X-3.2's rule): a hit fully absorbed by Mitigate or a `prevent` applies nothing; a hit reduced from 4 to 2 still applies the full effect. `lose_life` is not damage and never infects.
- **Each connecting hit applies its own poison effect**, and effects stack per §D8-2.1 — a victim struck twice by infected claws ticks −0/−2 per Upkeep until cured. Any received healing still ends all of them at once.
- **Registry:** a full keyword — grantable and removable via `grant_keyword`/`remove_keyword`, legal on enemies, tokens, and characters. **Banned at creation** (joining protection, hexproof, indestructible, deathtouch in Update 05 §P-3's exclusion list); it reaches a hero only by being granted. Enemy-eligible at **min level 3, cost 3** — priced beside lifelink and deathtouch as a damage-rider keyword.

---

## D8-3. Heroic actions: Skill and Ultimate

Every player-character gains two authored abilities beyond the evergreen three. Both are defined in the **Deckbuilder's character editor using the card schema** — the same effect editor, targets, modal/conditional containers, and validation a library card gets — with a name and flavour text. They are **not** library cards: they live on the character sheet, are never drawn, do not count toward the 20-card deck, rarity quotas, or the singleton rule.

### D8-3.1 Skill

- **Timing:** instant speed — a free reactive ability, castable in any window the character could cast an instant, on any turn. Does **not** consume the proactive action.
- **Uses:** **once per encounter.**
- **Cost:** may carry a mana cost (paid normally from the pool) or be free — author's choice.
- **Stack classification:** an **activated ability** (`ability`/`activated` on the two-axis taxonomy, §5.1). A spell-filter counter cannot answer it; an ability- or action-filter counter can.

### D8-3.2 Ultimate

- **Timing:** an **action** — sorcery speed, consumes the proactive action for the turn.
- **Uses:** **once per encounter**, and **only while the ultimate gauge is full** (§D8-3.3). Casting it spends the gauge to 0.
- **Cost:** **no mana cost, ever** — validation rejects an ultimate with a cost. The gauge is the cost.
- **Stack classification:** an activated ability, same as Skill. A Negate does not stop a limit break; a broad ability/action counter does.

### D8-3.3 The ultimate gauge

Each character carries a public gauge from **0 to 100**, starting each encounter at 0, clamping at 100. It fills from play:

| event | gauge |
|---|---|
| taking your proactive action (any of Attack / Cast / Defend / Move) | +2 |
| casting a spell | +1 per point of mana spent (generic + coloured; X counts; a channel charges its reserved cost once, at cast) |
| losing HP | +1 per point of current HP lost (damage that connects, `lose_life`, poison ticks — any reduction) |
| dealing damage | +1 per point of your damage that connects (attacks and your spells/abilities; not your tokens') |
| healing / shielding | +1 per point of HP you restore or temporary HP you grant as the source (heal, regen you applied as it ticks, Defend's temp HP, the toughness half of your pumps; overheal beyond max HP counts 0) |
| using your Skill | +5 |
| an ally is downed | +25 to **each other** living party member |

Incidental consequence, intended: **Defend now earns +5 gauge** (+2 action, +3 temp HP granted), which gives the placeholder Defend real texture — turtling charges your finisher, at the price of tempo.

The gauge persists through incapacitation (a revived character keeps its charge). It resets between encounters with everything else; whether a future run loop carries a fraction forward is deferred alongside the run loop itself.

### D8-3.4 Evergreen flavour fields

The character sheet gains **optional flavour** for the three evergreen abilities: for each of **basic attack**, **Defend**, and **Mitigate**, an optional display **name** and one-line **text** (e.g. Defend → "Dawnbreaker Stance — Soren plants the tower shield"). Purely presentational: the log and action buttons use the custom name when present; the mechanics are untouched. This delivers the GDD §4.6 "placeholder name; character-flavoured later" promise.

### D8-3.5 Schema and validation

`Character` gains:

```
skill:            Card?        # timing forced to "instant"
ultimate:         Card?        # timing forced to "sorcery"; zero mana cost enforced
ability_flavor:   { attack?: {name?, text?}, defend?: {name?, text?}, mitigate?: {name?, text?} }
```

Validation: a skill/ultimate may use the full effect vocabulary and containers; `channeled` timing is illegal for both; the ultimate's cost must be empty; both are exempt from deck lints. **Neither is priced by the 70-point creation budget for now** — like the loadout itself, they are authored content balanced by judgment, not stats bought with points. This is an explicit playtest stance, revisited when leveling lands (a natural future lever: gauge size, fill rates, or a second skill as level-up rewards).

Both abilities surface in the engine as new legal actions (`use_skill`, `use_ultimate`) with once-per-encounter flags on `CharacterState`, and in the UI as two buttons beside the evergreen abilities, the ultimate's rendered against its gauge.

---

## D8-4. Smart auto-pass and auto end-turn

The reaction-window pass-tax is the game's worst flow cost, and it compounds with party size and with the new instant-speed Skill. Both rules below are **presentation-layer** behaviour: the game server submits synthetic actions through the same `apply_action` path a click takes, each logged distinctly ("Soren passes (auto)"). The engine stays pure; the cockpit, being a debugger, never auto-passes. There are **no user-configurable stops** — the rule below is the whole feature.

### D8-4.1 Auto-pass (reaction windows)

When a character holds reactive priority and has **no meaningful option**, the server passes for it. "No meaningful option" is engine-truth, computed from the legal set:

- The legal set contains nothing beyond `pass` and `drop_channels`, **and**
- if `drop_channels` is present, releasing the reserved mana would still not make any instant in hand, or an unused Skill, castable (cost ≤ pool + reserved, colours respected). A drop that enables nothing is not a decision.

If a `pending_choice` exists (a scry, a `move_card` pick), the window always waits — choices are never auto-resolved.

### D8-4.2 Auto end-turn (main phase)

Whenever a character holds main-phase priority and its legal set — after the same drop-channels refinement — contains only `end_turn`, the server ends its turn. In practice: once the proactive action is spent and no instant, Skill, or free ability remains playable, the turn closes itself; a stunned or empty-handed character's turn closes immediately. The check re-runs every time the legal set changes (a draw mid-turn that yields a castable instant re-opens the turn normally).

### D8-4.3 What this preserves

Auto-pass never hides a real decision: any castable instant, usable Skill, ready Mitigate/first-strike hold, or mana-releasing drop keeps the window open. Because it is engine-truth rather than heuristic, it is also deterministic — the same state always auto-passes the same seats, so scripted scenarios and time-travel replay are unaffected.

---

## D8-5. Generation prompt updates (`llm.py`)

The enemy framework grows three tools; the prompt's component vocabulary and design-guidance sections are extended accordingly:

- **Poison** joins the Debilitate verb list: `{"kind": "poison", "amount": 1, "target": …}`, magnitude 1 per tick at any level (bounded `turns` optional). Guidance: poison is the anti-turtle, anti-channeler pressure — one poisoner per encounter reads as a clock the healer must answer.
- **Regen** joins Fortify: a regen'd elite must be *hit* to be whittled, making chip damage a real assignment.
- **Infect** joins the enemy-eligible keyword table (min level 3, cost 3). Guidance: an infected biter turns every landed hit into a healer assignment — pair it with pressure that punishes healing (`on_hero_healed`) for a genuinely nasty knot, and use at most one infect creature per encounter.
- **Charge** enters as the windup pattern, with its own guidance block: one gatherer per encounter at most; gather component (Escalate 4) + hidden detonation (`on_charge_full`, threshold ≥ 2 gathers, verbs up to 2× schedule); the drama is the visible gauge under a veiled kit. Pairs naturally with a Ward bodyguard.
- The `telegraph` field's description changes: it is the action's **on-stack name and strip-reveal text**, no longer shown while declared (§D8-1.4). Authors should still write it well.

Veiling itself requires **no generation change** — enemies are authored exactly as before; the veil is applied at serialization.

---

## D8-6. Engine & schema touchpoints (for the implementation pass)

| system | where |
|---|---|
| intent categories + veiled snapshot | derive category in `apps/combat/ltg_combat/serialize.py` (full data stays, for the cockpit); **filter** in `apps/game-server/ltg_game_server/snapshot.py:_intents` to `{enemy_id, category, target, line}`; strip-reveal in `engine.py`'s `strip_intent` resolver |
| intents window | `apps/game-ui` side panel, below stack / above log; hover-highlight wiring |
| poison / regen / charge state | `apps/combat/ltg_combat/state.py` — per-creature affliction lists `{amount, turns_left}` + counter totals; enemy `charge` int |
| ticks, annihilation, cure/break rules | `engine.py` Upkeep step + the heal / damage-connects paths; state-based annihilation check |
| `poison` / `regen` / `charge` primitives | `core/ltg_core/schema.py` (`LEAF_EFFECT_CLASSES`), renderers in `translation.py`, handlers in `engine.RESOLVERS`; validation: `charge` enemy-only |
| `infect` keyword | `KEYWORDS` registry in `schema.py` (grantable, not buyable at creation); damage-connects hook in `engine.py` beside lifelink/deathtouch; enemy keyword pricing table |
| `on_charge_full` trigger + threshold | enemy component model + reactive pass in `engine.py` |
| Skill / Ultimate / gauge / flavour | `schema.py` `Character` fields + validation; `CharacterState` gauge + used-flags; gauge accounting hooks in the action/cast/damage/heal paths; `use_skill` / `use_ultimate` legal actions; Deckbuilder character editor (card-schema sub-editors); UI buttons + gauge bar |
| auto-pass / auto end-turn | `apps/game-server/ltg_game_server/session.py` — synthetic `apply_index` submissions after every state change; distinct log annotation |

Scripted-scenario note: §A and §C traces predate all four systems and must replay unchanged — every addition here is opt-in content or presentation, except the Upkeep tick ordering, which inserts into a step those scenarios exercise; the harness assertion run is the regression gate.

---

## D8-7. Rebalance Register deltas *(amends Update 04 §F-10, Update 07 §X-7)*

| ID | value | sets |
|---|---|---|
| T-45 | −0/−1 per counter per tick | poison magnitude |
| T-46 | +0/+1 per counter per tick | regen magnitude |
| T-47 | 2× level schedule; threshold ≥ 2 gathers | charge-triggered verb ceiling and minimum windup |
| T-48 | 100 | ultimate gauge size |
| T-49 | +2 action · +1/mana · +1/HP lost · +1/damage dealt · +1/HP-or-temp granted · +5 skill · +25 ally downed | gauge fill rates |
| T-50 | 1 / 1 per encounter | Skill and Ultimate uses |
| T-51 | min level 3 / cost 3; 1 effect of amount 1 per connecting hit | `infect` enemy pricing and rider magnitude |

---

## D8-8. Glossary deltas *(amends GDD §13)*

- **Veiled intent** — the pre-stack form of an enemy action under §D8-1: a generic category plus its locked target, with names, verbs, and magnitudes hidden until the action reaches the stack.
- **Category (intent)** — one of the closed set threat / spellcraft / row assault / party assault / gathering / support / summon / manoeuvre, derived deterministically from the declared action.
- **Poison counter** — a persistent −0/−1 placed by a poison effect on resolution and at each Upkeep until the effect concludes (death, any received healing, or its turn bound). Not damage; never breaks a channel. **Healing sheds these counters** (reversing each −0/−1), so a healed creature is fully rid of the venom; death or a `turns` bound instead leaves them until removed or annihilated. A regen tick cures the ticking but does not shed them (its counter interaction is 1:1 annihilation).
- **Regen counter** — a persistent +0/+1 placed likewise; a regen tick counts as healing; concluded by any damage that connects. Annihilates poison counters 1:1.
- **Charge counter** — enemy-only counters placed by the `charge` verb; at a component's `charge_threshold` its hidden ability fires onto the stack and the charge resets.
- **infect** *(keyword, new)* — any damage this creature deals that connects also applies a poison effect to the victim, whose first counter lands at the next Upkeep. Grantable; banned at creation; enemy-eligible (T-51).
- **Skill** — a character's authored once-per-encounter instant-speed activated ability; may cost mana.
- **Ultimate** — a character's authored once-per-encounter action, castable only on a full ultimate gauge; never costs mana.
- **Ultimate gauge** — a public 0–100 per-character meter filled by acting, spending mana, taking and dealing damage, healing, Skill use, and downed allies (T-49).
- **Auto-pass / auto end-turn** — server-side synthetic pass/end submitted when a character's legal set holds no meaningful option (§D8-4); presentation-layer, engine-pure.

---

## D8-9. Open questions

- **[OPEN] Gauge persistence across a run.** Deferred with the run loop (Update 05 §P-5): whether the ultimate gauge carries a fraction between encounters of an expedition.
- **[OPEN] Points pricing for Skill/Ultimate.** Currently outside the 70-point budget (§D8-3.5). If playtest shows authored ultimates dominating stats, the lever is a creation-cost line item or gauge-size tiers.
- **[OPEN] Enemy AI reading the gauge.** Enemy valuation currently ignores hero gauges; a "spike the hero at 95 charge" target rule is a natural Update 09 candidate.
- **[OPEN] Player-facing charge counters.** Explicitly out of scope; revisit only if a card design demands it (the gauge covers the player-side fantasy).
