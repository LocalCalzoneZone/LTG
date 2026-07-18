# Langelier Tactical Game (LTG) — Game Design Document

**Status:** canonical design reference. **Audience:** anyone building or extending LTG, assuming *zero* prior context. This is a precise rules specification, not marketing copy. Rules still being tuned are marked **[OPEN]**; systems designed but not yet built are marked **[PLANNED]**.

---

## 0. How to read this

LTG borrows the *grammar* of trading-card games — cards, mana, a resolution stack, keyword abilities — but defines its own rules and its own numbers. You do **not** need to know Magic: The Gathering (MTG) to read this; every concept is defined here in LTG's own terms. MTG appears only as the *source material* player cards are translated from (§2), never as a rule the engine follows.

A note on words: a **player** is a human. A **player-character** is one of the characters a player controls. One player may control several player-characters, and the rules below operate **per character** — turns, the action economy, and priority are all per-character.

---

## 1. What LTG is

LTG is a single-player / small-co-op tactical RPG. Players control a small **party** of characters who fight **enemies** in turn-based combat. Presentation is a painterly, static-asset CRPG in the spirit of *Disco Elysium*, *Slay the Spire*, and *Darkest Dungeon*. It is a personal/playgroup project, not a commercial product.

The defining idea is that LTG is **AI-native, with a hard wall between generation and resolution:**
- **Generation** — enemies, encounters, flavour, art — is produced by AI (an LLM), at authoring time and eventually at runtime. This is where the game's variety comes from.
- **Resolution** — the rules of combat — is **always pure deterministic code**. An LLM **never** adjudicates a rule, computes a number, or decides a legal move at runtime.

The bridge across the wall is a **bounded vocabulary of effects** (§11): a finite set of mechanical "verbs" an LLM can compose freely (infinite content) but code can execute exactly (deterministic rules). The motto: **borrow the grammar, own the numbers; infinite nouns, finite verbs.**

---

## 2. Architecture & content pipeline (where everything comes from)

A player's abilities are **real MTG cards translated into LTG's effect vocabulary**, ahead of time, in an authoring tool. The combat engine only ever sees the translated LTG result.

1. **The effect vocabulary** (the contract, §11) — the finite set of typed effect primitives every part of the system speaks.
2. **LTG Deckbuilder** *(built)* — the authoring tool: import an MTG card by name (Scryfall), translate its text to LTG effect JSON, review/edit/validate it, build a character, export a **validated loadout JSON**. Nothing it produces is trusted until a human marks it validated.
3. **LTG Combat** *(being built now — this document's primary consumer)* — the runtime: ingests a validated loadout JSON plus an encounter, executes the rules deterministically, emits a structured event log. No Scryfall, no editing, no translation, **no LLM at runtime.**
4. **Generation engine** *(planned)* — produces enemies/encounters at runtime within the bounded schema.
5. **Narrator** *(planned)* — an LLM that turns the engine's event log into prose; it reads events, never changes them.

The **validated loadout JSON is the contract** between Deckbuilder and Combat. Code is a **monorepo**: a shared `core` package owns the effect vocabulary, the translation/keyword registry, and the validator; the apps (`deckbuilder`, `combat`) each depend on `core`, never on each other.

---

## 3. What cards exist

LTG uses only **three** MTG card types. Player cards are exclusively:
- **Instants** → reactive spells (`instant` timing).
- **Sorceries** → active spells (`sorcery` timing).
- **Enchantments** → channeled effects (`channeled` timing, §8).

Everything else is **excluded** and never appears in a loadout: **creatures, artifacts, lands, planeswalkers, battles, and double-faced / modal-dual-face cards** (and any other type). Two consequences:
- **There are no creature cards.** Allied creatures exist only as **tokens** that instants/sorceries/enchantments may *create* (§9.6). You never play a creature.
- **There are no land cards.** "Lands" survive only as *references inside ramp/ritual spells*, which translate to mana capacity (§4.4, §7).

There are no permanents to play, no mana rocks, no equipment. A loadout is 40 spells across those three types.

---

## 4. The combat model

### 4.1 Participants and the battlefield
On one side is the **party**: the player-characters plus any **ally tokens** they create. On the other are the **enemies**: **minions** and **bosses** (§9).

The battlefield has **three rows per side** — **front, mid, and rear** — for both the ally side and the enemy side. Positioning is abstract (rows, not a grid). Rows govern melee reach and a few keywords (flying, reach, trample — §7). **[OPEN]** The precise default melee reachability (which rows a non-flying attacker may strike) is still to be finalised; the keywords in §7 define the *exceptions* to that baseline.

### 4.2 Turn and round structure
Combat proceeds in rounds. Each turn runs these steps in order:
1. **Upkeep** — each player-character **draws one card**; mana **refreshes**; from the start of **turn 2 onward**, mana capacity rises by **+1** (the curve-up — **no increase on turn 1**); per-round ability uses reset; recurring channeled effects fire (§8).
2. **Enemy Intents** — each enemy **declares** the intent it will execute this turn. Intents are visible *before* the player acts.
3. **Player actions** — each player-character may take its turn (§4.6).
4. **Enemy actions** — each enemy **executes** its declared intent (§9.3).
5. **End step** — end-of-turn effects resolve and expire (temporary HP/pumps fade, etc.).

Win/loss is checked continuously: all enemies defeated → the party wins; all player-characters incapacitated → the party loses.

### 4.3 HP, damage, incapacitation
Every character and enemy has **HP**. **Damage is deterministic** — attacks and damaging effects always land for their stated amount; there is no to-hit roll and no damage variance. Defence is *answering the action*, never avoidance (§4.8).

A **player-character** at 0 HP is **incapacitated** (out of the fight) — it does **not** "die" and triggers no death effects. **Enemies and tokens** do **die** at 0 HP (and may have death triggers). HP **persists across turns within an encounter** (the attrition currency of a fight); HP, mana, and hand reset between encounters.

### 4.4 Mana
Mana is a **curve-up resource; there are no lands.**
- A character starts each encounter at its archetype's **base mana capacity** (§10), available on **turn 1**. From the start of **turn 2** onward, capacity rises by **+1** each turn. There is **no increase on turn 1**.
- Each point of capacity is **colour-locked** when added — the player chooses its colour from the character's identity, at most **3 distinct colours** total. Locked colours **refresh** (become spendable) each upkeep.
- Mana **resets fresh** at the start of every encounter.
- **Ramp** (from translated land-fetch cards) raises capacity *above* the curve, with three availabilities: **immediate** (usable this turn), **tapped** (capacity now, usable next refresh), **deferred** (arrives at the start of next turn).
- **Rituals** (`add_mana`) are a one-time burst into the **current pool this turn only**; they do not raise capacity.
- **Channeled enchantments reserve mana**: their cost stays locked while held (§8).

### 4.5 Cards, library, hand
A character's deck is its **loadout**: a **40-card singleton library** (no duplicates). Rarity is capped at **2 mythic / 6 rare / 12 uncommon / 20 common**; rarity is the card's power tier and a future leveling dial.
- The library is **draw-and-keep** — your hand is what you draw from it.
- **Starting hand** size is set by **archetype** (§10).
- **Each upkeep, every player-character draws one card.**

Each card carries: a reflavoured **name** and its **source** name; a **mana cost** (coloured); a **timing** (`instant` / `sorcery` / `channeled`); a **rarity**; a **level** (its mana value, used by level-gated effects); a **type** (player cards are always `spell`); and its **effects** (the LTG effect JSON, §11).

### 4.6 Actions, reactions, and what a character can do
**An action** is something a character does proactively on its own turn; taking it spends the character's single **proactive action** for that turn. **A reaction** is something a character does in response to another action, outside the normal flow of its turn; reactions are **free** (they don't spend the proactive action) and are limited only by mana.

**Every character has three free abilities, usable once per round each:**
- an **offensive ability** — its **basic attack**, dealing damage equal to its Power (§4.7);
- a **defensive action** — *Defend* (placeholder name; character/gear-flavoured later) — grants the character temporary HP;
- a **defensive reaction** — *Parry* — reduces an incoming hit.

**The proactive action.** On its turn, a character takes exactly **one** of:
- **Attack** — make an attack (its basic attack, or an attack granted by a card); afterwards it may act only at instant speed;
- **Cast** — cast `sorcery`-speed spells, limited only by mana; **no attack** this turn;
- **Defend** — use its defensive action (temporary HP).

**Free, any time (not the proactive action):** casting **instants** (limited only by mana) and using **reactions** (Parry, triggered responses). These may be done on the character's own turn or in response to others' actions, and never consume the proactive action.

The **vigilance** keyword (§7) lifts the attack-vs-cast restriction, letting a character cast **and** attack in one turn.

### 4.7 Power and attacks
A character's **Power** is its attack value: its basic attack deals damage equal to its Power. **Pump** effects (§4.9) add temporary Power, increasing that turn's attack. (Power = attack; there is no separate gear stat at this time.)

### 4.8 Defence
Because damage always lands, defence means answering the action:
- **Reduce** the hit — the defensive reaction (Parry), prevention/"fog" effects.
- **Absorb** it with temporary HP — the defensive action (Defend), or the toughness half of a pump.
- **Cancel** the action on the stack — counters (§5.4).
- **Disrupt** it before it happens — strip or stun the enemy's intent (§5.2).
- **Remove** the attacker — kill/exile/bounce a minion (bosses are protected until their execute window, §9).

### 4.9 Temporary HP, temporary wounds, and counters
- **`pump` (+X/+X, until end of turn):** **+X Power** and **+X temporary HP** — a buffer that absorbs a blow, then fades at end of turn.
- **`wound` (−X/−X, until end of turn):** **−X Power** and a **temporary wound** of X — it absorbs the next *healing* the target would receive, then closes. (A wound on a life-draining enemy can cancel its lifegain.)
- **`counters` (+1/+1, persistent):** a permanent buff (more Power, more max HP) lasting until removed, reset, or the encounter ends.

---

## 5. The stack (how actions resolve)

### 5.1 Actions: the two axes
Everything that resolves goes on **the stack** as an **action**, with two orthogonal properties:
- **type:** `spell` (instants/sorceries/enchantments, plus enemy "spell" actions) or `ability` (attacks, activated, triggered, the evergreen abilities, enemy non-spell actions).
- **timing:** `active` (initiated proactively, costs the turn-action — sorceries, attacks, Defend, activated abilities) or `reactive` (response-capable or auto-firing, free — instants, triggered abilities, Parry).

| | **spell** | **ability** |
|---|---|---|
| **active** | sorcery | attack, activated, Defend |
| **reactive** | instant | triggered, reaction (Parry) |

`instant`-vs-`sorcery` timing *is* the active/reactive axis for spells.

### 5.2 Intents (the pre-stack form of an enemy action)
An enemy action has **two lives**. While **declared** (the Enemy Intents step, §4.2) it is an **intent** — telegraphed and visible, not yet on the stack. When the enemy **executes** it (the Enemy actions step), that same action goes on the stack and can be answered. Two interaction surfaces:
- **Disrupt the intent (pre-stack)** by targeting the **enemy that owns it**: `strip_intent` removes its current intent; `stun` makes it skip its next intent; killing/debuffing it also works. Type-agnostic.
- **Answer the action (on the stack)** by targeting the **action itself** — what counters do, filtered by type.

### 5.3 Stack resolution
- Actions resolve **last-in-first-out**.
- **Only player-characters hold reactive priority.** Enemies never respond to the player; an enemy "reaction" is a telegraphed trigger that, when it fires, goes on the stack as its own action a player-character may respond to.
- **Reaction windows are not timed.** Before any action resolves, each **player-character** in turn is given the chance to react (add an instant/reaction) or pass. The action resolves only once every player-character has passed. (Priority is per-character because one player may control several.)
- **Targeted effects re-check legality at resolution and fizzle** if the target is gone or has become illegal (e.g. it gained hexproof/shroud).

### 5.4 Counters
A **counter** is one effect with a **filter**. It targets an enemy **action on the stack** and cancels it if it matches; a filter node matches its descendants:
```
action  (any)
├── spell
└── ability
    ├── attack
    ├── activated
    └── triggered
```
A universal counter uses `action`; a spell-only counter uses `spell`; a broad ability counter uses `ability` (which **includes attacks** — with no blocking mechanic, countering is a legitimate full answer to an attack, paid with a card). Counters are reactive (`instant` timing).

---

## 6. Targeting

Targeting is a mechanical property, not a label — it decides what hexproof and shroud can stop and what can fizzle.

**The distinction.** An effect's reach over creatures is one of:
- **all** — every creature in a set ("creatures you control"); **not** targeted;
- **chosen** — you pick one, but it is **not** "targeted" mechanically ("a creature you control");
- **targeted** — you pick one **and** it uses the targeting mechanic ("target creature").

**The rule that sets it:** an effect is **targeted** **iff its source text contains the word "target".** So "target creature you control" is a **targeted** ally (alias `targeted_ally`); "a creature you control" is a **chosen** ally (alias `chosen_ally`) and is **not** targeted.

**Why it matters — shroud vs hexproof:**
- **Shroud** — can't be **targeted** by *any* effect, even friendly ones.
- **Hexproof** — can't be **targeted** by *enemy* effects (friendly targeting is fine).
- Both bite **only** on `targeted` effects; `chosen` and `all` ignore them. This is why the targeted/chosen distinction must be preserved even for friendly effects.

**The descriptor (canonical form, as the Deckbuilder emits it).** Each target has a **class**: `creature` or `action`. A creature target carries **mode** (`self`/`chosen`/`all`), **side** (`ally`/`enemy`/`any`), **exclude_self** ("another …"), and **targeted** (the flag above). An action target carries a **filter** (§5.4). Readable aliases (`targeted_ally`, `chosen_ally`, `all_enemies`, …) map onto this structured form.

**Fizzle.** A targeted effect re-checks its target at resolution and does nothing if the target is gone or illegal.

**Shared targets.** When multiple effects on one card must hit the **same** chosen target, the card declares one shared target slot they reference.

**Mapping** (MTG phrasing → descriptor): "you" = self; "creatures you control" = all ally; "a creature you control" = chosen ally (not targeted); "target creature you control" = targeted ally; "another creature" = chosen any, exclude_self; "target creature" = targeted any; "target enemy" = targeted enemy.

---

## 7. The translation glossary

A **keyword/translation registry** is the single source of truth for the meanings below; effects can **grant** or **remove** keywords (`grant_keyword` / `remove_keyword`).

**Execute (defined).** To **execute** is to destroy/remove an enemy outright (not merely damage it). **Minions** can always be removed/executed. A **boss** can be executed only within its **execute window** (≤25% of max HP, §9.5). Some effects execute conditionally: **deathtouch** lets any of its damage execute a minion; **level-gates** ("destroy an enemy of Level ≤ N") execute by Level.

**Keywords** (kept; LTG meaning):

| keyword | LTG meaning |
|---|---|
| flying | can melee-attack **any** target regardless of the target's row |
| reach | flyers **cannot** hit targets in rows behind the Reach creature with melee attacks |
| first strike | may hold its attack and use it as a reaction (strikes first) |
| vigilance | may attack **and** still cast/act (lifts the attack-vs-cast restriction) |
| trample | excess damage overflows to another target on the **same or an adjacent row** |
| deathtouch | its damage can **execute** a minion (a boss only in its execute window) |
| lifelink | heal equal to the damage it deals **[OPEN — confirm]** |
| hexproof | can't be **targeted** by enemy effects (attacks still hit) |
| indestructible | can't be reduced below 1 HP by damage (killed only by exile or a −X/−X to 0) |
| protection | prevents the next spell or attack against it |
| **retired** (no analogue) | menace, ward, convoke, "can't win/lose the game", and similar |

**Non-keyword terms** (completing the translation):

| MTG term / action | LTG |
|---|---|
| discard (targeting an enemy) | strip its current telegraphed intent (§5.2) |
| mill | no effect on enemies (no library); self-mill moves your cards to your graveyard zone |
| return to hand / bounce | remove a minion; it re-enters after a reset, a few turns later |
| land | not a card; a reference inside ramp/ritual spells → mana capacity (§4.4) |
| mana value / CMC | the card's or enemy's **Level** |
| tap | the enemy skips its next intent (`stun`) |
| sacrifice | the source loses half its remaining HP |
| graveyard | a per-character zone of spent cards (fuels effects like Delve) |
| exile | remove permanently (no graveyard); minions always, bosses only in the execute window |

---

## 8. Channeling & enchantments

An **enchantment** is a `channeled` card: a **sustained effect a character actively holds**, anchored to that caster — concentration, not a permanent on a board.
- **Cost:** casting it **reserves** its mana for as long as it is held; that mana is unavailable while channeling. (Bigger enchantments lock more, so you can't stack endlessly.)
- **Persistence:** a channeled card's effects are either **continuous** (apply the whole time it's held — anthems, auras, disables) or **recurring** (fire once each upkeep — e.g. spawn-each-turn engines).
- **Breaking concentration** ends the channel(s). It happens when the channeler (a) takes a single hit of **≥25% of its maximum HP** (e.g. 4+ at 15 max HP), (b) is incapacitated, or (c) **voluntarily drops** it. The breaking hit resolves first; the break is then a stack event.
- **Break is all-or-nothing:** a breaking hit drops **every** channel the character holds at once — high risk, high reward. On break the card(s) are **spent**, and **all reserved mana is released at once** as a stack trigger that can be responded to.
- Because the break keys off the **hit's size**, the defensive game is to keep every incoming hit **under** the threshold (damage *reduction* protects channels; raw temp-HP *absorption* may not, since the hit still lands at full size).

---

## 9. Enemies

### 9.1 Statblocks
Enemies are **asymmetric** — no deck, no mana. An enemy has **HP**, a **Level**, and one or more **intents**. **Level** is the enemy's inherent power tier (from how it was generated), **fixed** and independent of current HP. Level-gates read this; HP-based executes read current HP. The two are distinct.

### 9.2 Intent archetypes
Behaviour is composed from a finite set: **Burst** (big single hit), **Evasive** (hard to pin/hit), **Drain** (damage + self-heal), **Swarm** (spawns/multi-hits), **Fortify** (shields/buffs), **Debilitate** (debuffs/disables), **Punish** (telegraphed retaliation), **Escalate** (ramps over time).

### 9.3 Enemy AI
Each enemy **declares** its intent in the Enemy Intents step and **executes** it in the Enemy actions step (§4.2). Move selection is done by **deterministic code heuristics** (the *Slay the Spire* pattern) — **never** an LLM at runtime. This keeps the engine deterministic and hand-runnable.

### 9.4 Minions vs bosses
- **Minions** are **removable** — destroy/exile/bounce all work.
- **Bosses** are "**player-class**": **immune to removal** (destroy/exile/bounce) until their execute window. You **can** still damage, attack, counter, debuff, tap, strip, and mill a boss — anything that affects it **in place** works; only effects that would **remove it from the board** are blocked. (Triage: *removes from board* → boss-immune; *affects in place* → works.)

### 9.5 Enrage & the execute window
A boss has one threshold at **≤25% of its maximum HP**, which is both its **enrage** line and its **execute window**. When a boss first drops to/below it: it **immediately triggers its enrage ability once** (you always eat this opening blow); it becomes **more dangerous** (escalated intents); and it becomes **executable** (removal now works). Mitigating or dodging the enrage is **fair play**; the lever is making the answer *cost* enough, not forbidding prevention.

### 9.6 Tokens & autonomous allies
Created tokens are **autonomous allied creatures** — they run their **own** intents, not puppets the player micromanages. The unifying principle: **the player is a character among autonomous allies, not a hand controlling a board.** So you can **help** an ally but not **command** or **consume** one (no sacrificing or "convoking" your own tokens), and allies/tokens **die** while player-characters are merely **incapacitated**.

---

## 10. Characters & archetypes

A character is defined by an **archetype**, a **colour identity** (1–3 of W/U/B/R/G), a **loadout** (§4.5), the three free abilities (§4.6), and a **level**.

Every character is one of four archetypes, which set starting stats:

| archetype | HP | hand | mana | identity |
|---|---|---|---|---|
| **Fighter** | 25 | 2 | 2 | tanky bruiser; leans on the basic attack + tricks |
| **Tactician** | 15 | 4 | 2 | cunning; the widest bag of tools |
| **Caster** | 10 | 3 | 3 | glass cannon; flexible burst + reaction mana |
| **Channeler** | 15 | 2 | 4 | sustained engine; stacks channeled effects, card-starved |

The Channeler's 15 HP is the **floor the channel-break threshold needs** (25% of 15 = a 4+ hit breaks concentration; lower HP would shatter channels to nearly any blow). Starting mana scales by archetype; its colours are chosen within identity, ≤3 distinct.

A character's strength is **stats *plus* loadout**, so a fragile sheet can pair with a stronger card pool; balance is judged across both.

**[PLANNED] Leveling:** a `level` field exists (default 1) with no effect yet. Each archetype will have its **own independent growth curve per stat** (HP, hand, mana, later rarity caps), plotted to **level 20** and cross-tuned so archetypes stay balanced at every level with no spikes. Stats are a function of `(archetype, level)`.

**The test party** (canonical example; full loadouts are separate fixture data): **Soren** — a **Fighter**, GW martial Herald (swordsman/statesman, no magic — strikes, combat-trick pumps, protection/parry, sustain, taunt, removal). **Ys** — a **Tactician**, UB fae trickster (counters, removal, debuffs, drain, card-draw-at-life-cost, conjured faeries). Soren bodyguards the fragile Ys — the protect-the-glass-engine dynamic the roster is built around.

---

## 11. The effect vocabulary (the verbs)

Cards and abilities are ordered lists of **effect primitives**. The cardinal rule: **effects *declare* intent; they never *execute* logic.** A `destroy` effect carries a target and nothing else — whether that means "kill a minion" or "execute a boss in its window" is the engine's decision, not the card's. This keeps the vocabulary pure data and centralises all rules in the resolver.

Current primitives (each takes a target descriptor and, where relevant, a duration of `end_of_turn` / `while_channeled` / `encounter`; numeric values may be constants or dynamic references such as "the destroyed target's Level"):

`deal_damage`, `heal`, `lose_life`, `destroy`, `exile`, `bounce`, `counter` (filtered), `redirect` (turn a targeted stack action — spell, ability, or attack — onto a new target; relentless intents never redirect), `strip_intent`, `stun`, `pump`, `wound`, `counters`, `prevent`, `protection`, `draw`, `scry`, `create_token`, `taunt`, `disable`, `revive`, `ramp`, `add_mana`, `grant_keyword`, `remove_keyword`.

The set is **extensible** but deliberately small. The engine implements one handler per primitive.

---

## 12. Implementation status

- **Built:** the effect vocabulary and `core` schema; the LTG Deckbuilder (Scryfall import, translation, character builder, effect editor, validation, loadout export).
- **Current focus:** the LTG Combat engine — a headless, deterministic resolver that consumes a validated loadout JSON and runs combat, proven against scripted reproductions of hand-run paper playtests.
- **Planned:** runtime enemy/encounter generation; the narrator; leveling; gear/inventory; exploration/narrative modes around combat; the painterly UI with runtime-generated art.

---

## 13. Glossary

- **Action** — something a character does proactively on its turn, spending its one proactive action.
- **Reaction** — a free, mana-limited response made outside the normal turn flow; does not spend the proactive action.
- **Active / reactive** — whether an action costs the proactive turn-action (active) or is a free response/auto-trigger (reactive).
- **Archetype** — Fighter / Tactician / Caster / Channeler; sets starting HP, hand, mana.
- **Basic attack** — a character's free offensive ability, dealing damage equal to its Power.
- **Boss** — a "player-class" enemy, immune to removal until its execute window.
- **Break (concentration)** — ending channeled effect(s); from a ≥25%-max-HP hit, incapacitation, or voluntary drop; breaks *all* channels and releases reserved mana.
- **Capacity (mana)** — colour-locked mana slots; grows +1/turn from turn 2 (the curve-up) and via ramp; resets per encounter.
- **Channel / channeled** — a sustained enchantment effect held by a caster, paid by reserved mana.
- **Counter** — a filtered effect that cancels a matching enemy action on the stack.
- **Curve-up** — the automatic +1 mana capacity each turn from turn 2 onward.
- **Defend** — the free defensive *action* (placeholder name); grants temporary HP; costs the proactive action.
- **Effect / primitive** — a declarative mechanical verb (e.g. `deal_damage`); the unit cards are built from.
- **Execute / execute window** — to remove an enemy outright; a boss is executable only at ≤25% max HP.
- **Fizzle** — a targeted effect doing nothing because its target became illegal by resolution.
- **Incapacitated** — a player-character at 0 HP (out of the fight; no death trigger). Enemies/tokens *die*.
- **Intent** — an enemy's declared next action, before it reaches the stack.
- **Level** — for a card, its mana value; for an enemy, its fixed inherent power tier; for a character, its (planned) progression rank.
- **Loadout** — a character's 40-card singleton library plus its definition; the validated JSON the engine consumes.
- **Minion** — a removable enemy.
- **Parry** — the free defensive *reaction*; reduces an incoming hit.
- **Player / player-character** — a human / one of the characters a player controls. Rules operate per character.
- **Power** — a character's attack value; the damage of its basic attack.
- **Pump / wound / counters** — temporary +X/+X / temporary −X/−X / persistent +1/+1 stat changes.
- **Ramp / ritual** — raising mana capacity above the curve (ramp) / a one-time pool burst (ritual `add_mana`).
- **Row** — front / mid / rear; each side (ally, enemy) has all three; governs melee reach and some keywords.
- **Stack** — the last-in-first-out structure where actions resolve, with per-character reaction windows.
- **Targeted** — an effect using the targeting mechanic (text contains "target"); subject to hexproof/shroud and fizzling.
- **Token** — a created autonomous allied creature with its own intents.
