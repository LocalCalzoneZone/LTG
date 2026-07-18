# Langelier Tactical Game (LTG)

LTG is a single-player / small-co-op **tactical RPG**, played as turn-based card combat.
You control a small party of characters who fight generated enemies on a three-row
battlefield, spending a curve-up mana resource to cast spells translated from real
Magic: the Gathering cards.

The defining idea is a **hard wall between generation and resolution**:

- **Generation** — enemies, encounters, flavour, and art — is produced by an LLM.
  This is where the game's variety comes from.
- **Resolution** — the rules of combat — is **always pure deterministic code**. No LLM
  ever adjudicates a rule, computes a number, or decides a legal move at runtime.

The bridge across the wall is a **bounded vocabulary of effects** (see
[Effects](#effects-the-verbs)): a finite set of mechanical verbs an LLM can compose
freely but code can execute exactly. The motto: *borrow the grammar, own the numbers;
infinite nouns, finite verbs.*

You do **not** need to know Magic to play or read this. MTG is the *source material*
player cards are translated from, never a rule the engine follows.

> **Canonical rules reference:** [ltg_game_design_document.md](ltg_game_design_document.md)
> plus Design Updates [01](ltg_design_update_01.md) (rows & HP), [02](ltg_design_update_02.md)
> (movement & Mitigate), [03](ltg_design_update_03.md) (zones & the win condition),
> [04](ltg_design_update_04_enemy_framework.md) (the enemy framework),
> [05](ltg_design_update_05_character_build.md) (character points-buy),
> [06](ltg_design_update_06_enemy_intelligence.md) (enemy intelligence & encounter
> scaling), and [07](ltg_design_update_07_errata_and_rebalance.md) (errata &
> rebalance). Later updates win where they disagree with earlier ones. This README
> summarises all of them; the documents are the authority.

---

## Table of contents

- [Run it](#run-it)
- [How the game is played](#how-the-game-is-played)
- [Building a character](#building-a-character)
- [Building a deck](#building-a-deck)
- [Effects — the verbs](#effects-the-verbs)
- [Enemies](#enemies)
- [Encounters & generation](#encounters--generation)
- [The apps](#the-apps)
- [Developing](#developing)

---

## Run it

> Installing on a plain Windows machine (no dev tools)? Follow
> [WINDOWS_INSTALL.md](WINDOWS_INSTALL.md) instead.

Everything installs into one virtual environment from the repo root.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # editable-installs core + all three apps
```

Then pick a surface. The main apps are also double-clickable launchers that create
the venv on first run: `.command` files in Finder (macOS), `.bat` files in
Explorer (Windows).

| Command | Launcher | Port | What it is |
|---|---|---|---|
| `ltg-start` | `LTG-Start.command` / `.bat` | 8020 + 8000 | **The whole table:** game + deckbuilder in one window; in-app Quit stops both |
| `ltg-game` | `LTG-Game.command` / `.bat` | 8020 | **The game.** React client, multiplayer seats, LLM generation |
| `ltg-deckbuilder` | `LTG-Deckbuilder.command` / `.bat` | 8000 | Authoring: import MTG cards, translate, build characters |
| `ltg-autoplay-tester` | `LTG-Autoplay-Tester.command` / `.bat` | 8030 | The playtest lab: probes, gauntlets, balance verdicts |
| `ltg-combat-cockpit` | — | 8001 | The playtest cockpit — a debugger, not a game |
| `ltg-combat repl` | — | — | The text UI, for playing a fight in a terminal |

All the servers take `--port`, `--host`, `--reload`, and `--no-browser`. They bind
`0.0.0.0`, so other devices on your LAN can reach them at `http://<your-ip>:<port>`
(find your IP with `ipconfig getifaddr en0` on macOS).

`ltg-game` builds the React client automatically on first run (`--skip-build` to serve
whatever is already in `apps/game-ui/dist`, `--dev` to serve API/WebSocket only while
you run `npm run dev` yourself).

---

## How the game is played

### The battlefield

Two sides — the **party** (your characters plus any ally tokens they create) and the
**enemies** — each occupying **three rows: front, mid, and rear**. Position is abstract
(rows, not a grid) and it is a live, consequential resource, not a one-time setup.

Rows create a free passive defence called **the wall**: melee attacks strike only the
**front-most occupied row**, so a character standing in front shields everyone behind it
from melee, at no cost. Ranged and flying attacks ignore the wall and reach any row.
That split is the engine of positional play — the wall answers melee for free, so the
only threat left for active defence is what the wall *can't* stop.

### The round

Every round runs these five steps in order:

1. **Upkeep** — each character **draws one card**; mana refreshes; from **turn 2 onward**
   mana capacity rises by **+1** (the *curve-up* — no increase on turn 1); per-round
   ability uses and enemy cooldowns reset; recurring channeled effects fire.
2. **Enemy intents** — each enemy **declares** what it will do this turn. Intents are
   visible *before* you act, and they lock their target at declaration.
3. **Player actions** — each character takes its turn, in a fixed initiative order rolled
   once at setup and constant for the whole fight.
4. **Enemy actions** — each enemy **executes** its declared intent.
5. **End step** — end-of-turn effects expire (temporary HP and pumps fade), and every
   pending movement resolves.

**Victory:** the party wins when **every enemy in the encounter's roster is in the
graveyard or exiled**. **Defeat:** the party loses when all characters are incapacitated.
Both are checked continuously.

### What a character can do on its turn

A character takes exactly **one proactive action**:

- **Attack** — its basic attack (damage equal to its **Power**), or an attack granted by
  a card. Afterwards it may still act at instant speed.
- **Cast** — cast `sorcery`-speed spells, limited only by mana. No attack this turn.
- **Defend** — the free defensive action; grants temporary HP (currently +3, a
  documented placeholder).
- **Move** — reposition to any row. Costs no mana.

**Free, at any time, on anyone's turn:** casting **instants** (limited only by mana) and
using **reactions**. These never consume the proactive action.

Two keywords lift these restrictions. **Vigilance** lets a character attack *and* cast in
the same turn. **Haste** lets it take its proactive action *and* make a free voluntary
move.

### Damage, HP, and death

**Damage is deterministic.** Attacks and damaging effects always land for their stated
amount — there is no to-hit roll and no damage variance. Defence therefore never means
*avoidance*; it means answering the action.

`effective_hp = hp + temp_mod`. Damage reduces `hp` directly; `pump` and `wound` move
`temp_mod`, which expires at End step; a heal fills a wound before it heals. Lethality is
checked on `effective_hp`.

HP persists across turns within an encounter — attrition is the currency of a fight — and
resets between encounters, along with mana and hand.

A **player-character** at 0 HP is **incapacitated**: out of the fight, no death trigger,
and it recovers the instant it climbs back above 0. **Enemies and tokens die** at 0 HP,
and may have death triggers.

### The five ways to answer a threat

Because damage always lands, defence is about answering the action rather than dodging it:

| | how |
|---|---|
| **Reduce** the hit | the **Mitigate** reaction, or `prevent` effects |
| **Absorb** it | temporary HP from **Defend**, or the toughness half of a `pump` |
| **Cancel** the action | a **counter**, while it's on the stack |
| **Disrupt** it first | `strip_intent` or `stun` the enemy before it acts |
| **Remove** the attacker | kill, exile, or bounce it (bosses resist until their execute window) |

### Mitigate — the defensive reaction

**Mitigate** is free, usable **once per turn**, and answers exactly one **attack**-type
action on the stack. It does not answer spells or non-attack ability damage — those need
a counter or a `prevent`.

Its value is **X = ceil(the mitigator's current Power ÷ 2)**, read at the moment the
attack resolves, not when Mitigate was declared. A `pump` on the mitigator therefore
raises X. Each hit in the answered action is reduced by the full X independently — the
shield doesn't tire between blows — so `damage = max(0, hit − X)` and any hit of `X` or
less is fully negated.

Mitigate has two modes, and the single per-turn use goes to one or the other:

- **Self** — reduce each hit aimed at you.
- **Ally (interception)** — every hit the action aimed at one chosen ally is **redirected
  onto you** and reduced by X. It's all-or-nothing (you can't take hit 1 and leave hit 2),
  the ally must be in your row or an adjacent one (front and rear are *not* adjacent), and
  on-hit triggers like lifelink now fire against **you**.

Interception is never free: declaring it immediately **moves your committed position to
the protected ally's row**. Covering a backline ally pulls the tank off the front line,
so the melee the wall was holding reaches the backline next round. Every interception is
a trade — *who do I save, and what do I expose by leaving?*

### Movement, and why you can never dodge

Every combatant tracks **two** row values:

- **`current`** — its physical row. This is what enemy and ally **intents** read. It
  changes **only at End step**.
- **`committed`** — the row it has committed to occupy. This is what its **own** actions
  and reactions read for reach and legality. It can change during the turn.

Separating these resolves the "two places at once" problem: your *reach* updates the
instant you commit to a move, but your *body* does not relocate until End step.

**Forced moves** write `committed` immediately: making a melee attack commits you to the
front; intercepting for an ally commits you to their row. **Voluntary moves** (the Move
action, or a free haste move) write a separate pending slot and do not touch `committed` at
all — so a planned destination never grants reach mid-turn.

Since intents lock their target at declaration and never re-check, and bodies only move at
End step (after the enemy step), **no movement can dodge a declared attack**. That is the
guarantee the whole model exists to provide.

### The stack

Everything that resolves goes on **the stack** and resolves last-in-first-out. Each action
has two orthogonal properties:

| | **spell** | **ability** |
|---|---|---|
| **active** (costs your proactive action) | sorcery | attack, activated, Defend |
| **reactive** (free) | instant | triggered, Mitigate |

Speed is **derived, never stored**: a player card is always a spell whose speed comes from
its timing (instant → reactive, sorcery → active, channeled → sustained).

**Reaction windows are not timed.** Before any action resolves, each player-character in
turn may respond or pass. When a player puts an action on the stack, that player holds
priority first (they may even respond to their own action), then priority moves through
the party in turn order. Once every player has passed, **eligible enemy reactions** fire —
at most one per enemy per window — and each enemy reaction is a new stack action that
**re-opens** the party's priority. The stack top resolves only when everyone has passed
and no enemy reaction fires.

Targeted effects **re-check legality at resolution and fizzle** if the target is gone or
has become illegal.

### Intents, and the two ways to answer an enemy action

An enemy action has **two lives**. While **declared** (step 2) it is an **intent** —
telegraphed, visible, not yet on the stack. When the enemy **executes** it (step 4) that
same action goes on the stack. Two surfaces, two targets:

- **Disrupt the intent (pre-stack)** by targeting the *enemy that owns it*. `strip_intent`
  removes its current intent; `stun` makes it skip its next one. Type-agnostic.
- **Answer the action (on the stack)** by targeting the *action itself*. This is where
  **counters** operate.

A **counter** is one effect carrying a **filter**, a node in this lattice — matching a node
matches all of its descendants:

```
action  (any)
├── spell
└── ability
    ├── attack
    ├── activated
    └── triggered
```

There is no blocking mechanic in LTG, so countering an attack is a legitimate full answer
to it, paid for with a card. Counters are reactive (`instant` timing) and side-symmetric:
enemies have them too, and you can never counter your own side's action.

### Mana

Mana is a **colour-locked capacity that curves up. There are no lands.**

- A character starts each encounter at its **base mana capacity**, available on turn 1.
  From turn 2 onward capacity rises by **+1** each turn.
- Each point of capacity is **colour-locked when added** — you choose its colour from the
  character's identity (at most 3 distinct colours). Locked colours **refresh** each upkeep.
- **Ramp** raises capacity *above* the curve, with three availabilities: **immediate**
  (usable now), **tapped** (capacity now, usable next refresh), and **deferred** (arrives
  at the start of your next turn).
- **Rituals** (`add_mana`) are a one-time burst into your *current pool this turn only*;
  they do not raise capacity.
- **Channeled enchantments reserve mana**: their cost stays locked while you hold them.
- Mana resets fresh at the start of every encounter.

### Channeling

An **enchantment** becomes a `channeled` card: a sustained effect a character actively
holds — concentration, not a permanent on a board.

- **Cost:** casting it **reserves** its mana for as long as it's held. Bigger enchantments
  lock more, so you can't stack endlessly.
- **Persistence:** its effects are either **continuous** (`while_channeled` — anthems,
  auras) or **recurring** (`trigger: upkeep` — a token engine that fires each turn).
- **Breaking concentration** ends *every* channel the character holds, at once. It happens
  when the channeler takes a single hit of **≥25% of its maximum HP**, is incapacitated, or
  voluntarily drops it. The breaking hit resolves first; the break is then a stack event,
  and **all reserved mana releases at once** as a respondable trigger.
- Because the break keys off the **hit's size**, the defensive game is to keep every
  incoming hit *under* the threshold. Damage **reduction** protects a channel; raw temp-HP
  **absorption** may not, since the hit still lands at full size.
- A channel may be **voluntarily dropped at instant speed** whenever its holder has
  priority — main phase or any reaction window, including the turn it was cast. The
  reserved mana releases straight to the pool, so a drop inside a reaction window can
  immediately pay for a different instant.

### Zones, bounce, and why you can't win by bouncing

Every enemy in an encounter belongs to a fixed **roster**, and always occupies exactly one
zone:

| zone | means | defeated? | on the battlefield? | targetable? |
|---|---|---|---|---|
| **in play** | active; declares intents and acts | no | yes | yes |
| **in hand** | bounced; pending redeploy | **no** | no | no |
| **graveyard** | died (effective HP ≤ 0) | **yes** | no | no |
| **exile** | exiled | **yes** | no | no |

Victory reads **zone state**, not board presence. A **bounced** enemy goes to *in hand*,
which is neither graveyard nor exile, so bouncing the last enemy does not win the fight —
it will redeploy at the start of its next turn, on its original row, with a fresh intent,
having lost exactly one action cycle. It keeps its accumulated damage (bounce doesn't
heal), sheds its temporary modifiers and attachments, and while in hand it **cannot be
targeted, killed, bounced again, or caught by your board-wide sweeps**. Removal ends
fights; bounce buys tempo.

### Tokens and allies

Created tokens are **autonomous allied creatures** — they run their **own** intents rather
than being puppets you micromanage. The unifying principle: *the player is a character
among autonomous allies, not a hand controlling a board.* You can **help** an ally but not
**command** or **consume** one (no sacrificing your own tokens), and allies die where
player-characters are merely incapacitated.

---

## Building a character

A character is a **points-buy against a 70-point budget**, mirroring the enemy budget
system. There is no "custom" archetype — *custom* is simply not choosing a preset and
spending your own 70.

**Free baseline:** 8 HP · 1 mana capacity · 1 starting card · **one** attack mode, either
**melee Power 2** or **ranged Power 1** (you own only the mode you pick). Melee's higher
free base compensates for being row-restricted.

**Creation costs** (all flat — the escalating leveling curve applies only to earned points,
which are designed but not yet built):

| buy | cost |
|---|---|
| +2 HP (bought two at a time) | 5 |
| +1 mana capacity | 15 |
| +1 starting card | 15 |
| +1 Power above your mode's base | 10 |
| 1 keyword (**max one**) | reach 5 · trample 10 · first strike 15 · lifelink 15 · haste 15 · vigilance 20 · flying 25 |

**Guardrails:** HP ≥ 8, mana ≥ 1, cards ≥ 1, at least one attack mode; at most **+2 Power**
bought (melee ≤ 4, ranged ≤ 3); at most **one** keyword. Protection, hexproof,
indestructible, and deathtouch are **banned at creation** — they exist on enemies and may
arrive later via gear or spells, but are never buildable. First strike, vigilance, and
haste are **player-only**; enemies can never have them.

**The four archetypes are pre-spent 70-point presets**, not classes — proof the points
system generalises them rather than replacing them:

| | HP | mana | cards | attack | Mitigate | the build |
|---|---|---|---|---|---|---|
| **Fighter** | 20 | 2 | 2 | Melee, Power 3 | 2 | +12 HP (30) + 1 mana (15) + 1 card (15) + 1 Power (10) |
| **Tactician** | 12 | 2 | 4 | Ranged 1 *or* Melee 2 | 1 | +4 HP (10) + 1 mana (15) + 3 cards (45) |
| **Caster** | 8 | 3 | 3 | Ranged 2 *or* Melee 1 | 1 | +2 mana (30) + 2 cards (30) + 1 Power (10) |
| **Channeler** | 12 | 4 | 2 | Ranged 1 *or* Melee 2 | 1 | +4 HP (10) + 3 mana (45) + 1 card (15) |

Each totals exactly 70. Power is a bought stat, and because Mitigate is `ceil(Power ÷ 2)`,
buying a tank's offence also buys its guard — the halving keeps that coupling in check.

The build resolves to a **stat block** — `{hp, mana_capacity, starting_cards,
attack_profile: {mode, power}, keywords[]}` — and **the engine consumes the stat block, not
an archetype name.**

A character also carries a **colour identity** (1–3 of W/U/B/R/G), which constrains the
colours its mana capacity can be locked to and flags off-colour cards in its deck.

---

## Building a deck

A character's deck is its **loadout**: a **singleton library** (no duplicate source cards),
drawn one card per upkeep and kept in hand.

**Deck status is advisory. It never blocks saving, exporting, or playing.** It warns on:

- **Card count** below the 20-card minimum.
- **Rarity quotas** — 1 mythic, 3 rare, 6 uncommon, 10 common. The non-common rarities are
  *exact* (minimum equals cap); commons are a floor with no cap, so going over 20 is fine
  as long as the excess is all commons.
- Duplicate source names, cards whose colours fall outside the character's identity,
  untranslated cards, and starting mana outside identity.

### Where cards come from

LTG uses only **three** MTG card types, and player cards are exclusively:

- **Instants** → reactive spells
- **Sorceries** → active spells
- **Enchantments** → channeled effects

Everything else is excluded and never appears in a loadout: creatures, artifacts, lands,
planeswalkers, battles, and double-faced cards. Two consequences follow:

- **There are no creature cards.** Allied creatures exist only as **tokens** that spells
  may create. You never play a creature.
- **There are no land cards.** "Lands" survive only as *references inside ramp and ritual
  spells*, which translate to mana capacity.

### The authoring flow

In the **Deckbuilder** (`ltg-deckbuilder`, port 8000):

**Create character → set name / colours / mana → search a card on Scryfall → add it →
review and edit its translated effects → mark it validated → Save → Export engine loadout.**

Adding a card fetches it from Scryfall and runs every registered translation rule over its
oracle text. Matched rules fill in the card's `effects` and render its `translated_text`.
If nothing matches, the card is flagged `needs_translation` for you to author by hand.
Translation is **deterministic and manual — no LLM in this pipeline.**

You can also **Import** a whole deck list (one card per line, e.g. `1 Akroma's Will (CMR) 3`
— quantity, set code, and collector number are ignored). Import is non-blocking: wrong
types, off-colour cards, and going over the count all import anyway and are flagged in the
list to fix.

**The engine reads `effects` only.** `translated_text` is player-facing flavour it never
reads, and it auto-derives from the effects unless you toggle manual override — so text and
effects can never silently drift.

**Editing any effect resets `validated` → false.** **Export engine loadout** emits only
cards that are structurally valid *and* marked validated; anything else is omitted and
reported. That validated loadout JSON is the contract between the Deckbuilder and the
engine.

---

## Effects — the verbs

Cards and enemy abilities are ordered lists of **effect primitives**. The cardinal rule:

> **Effects *declare* intent; they never *execute* logic.**

A `destroy` effect carries a target and nothing else. Whether that means "kill a minion" or
"execute a boss inside its window" is the **engine's** decision, not the card's. The
vocabulary stays pure data and every rule lives in one resolver.

### The 25 primitives

The engine implements one handler per primitive, and executes **every primitive, container,
and keyword the Deckbuilder can emit** — a card that validates can be played end-to-end.

```
deal_damage  heal      lose_life  destroy   exile
bounce       fight     counter    strip_intent  stun
pump         wound     counters   prevent   protection
draw         scry      move_card  create_token  taunt
revive       grant_keyword  remove_keyword  ramp  add_mana
```

Notable semantics:

- **`pump` (+X/+X, until end of turn)** — +X Power *and* +X temporary HP: a buffer that
  absorbs a blow, then fades.
- **`wound` (−X/−X, until end of turn)** — −X Power and a temporary wound of X that absorbs
  the next *healing* the target would receive, then closes. A wound on a life-draining enemy
  cancels its lifegain.
- **`counters` (+1/+1, persistent)** — a permanent buff (more Power, more max HP), lasting
  until removed or the encounter ends.
- **`prevent`** nullifies a **named parameter** (e.g. `prevent combat_damage`). The old
  `disable` primitive was retired in its favour.
- **`counter`** carries a `filter` and targets an action on the stack, not a creature.
- **`move_card`** is the general card-logistics primitive (`draw` is its common special
  case): move cards between zones, optionally filtered by type or level, optionally
  shuffling after. It expresses a tutor, a graveyard recursion, and a self-mill without a
  primitive apiece.
- **`fight`** is the one primitive with **two** target descriptors — `target` (your creature)
  and `other` (the one it fights). Each deals damage equal to its Power to the other,
  simultaneously, so a fight that kills both kills both.

### Containers

Two effects wrap other effects. Their branches hold **leaf** effects only — no nesting a
modal inside a modal.

- **`modal`** — a "Choose one" card. The mode is **chosen at cast**: the engine offers one
  legal cast per mode, and only that mode resolves.
- **`conditional`** — an extra effect gated by a condition, either **`cast_mode`**
  (`action`/`reaction` — the speed it was cast at) or **`target_property`** (`has_keyword`
  or `side`). It composes with the card's other effects.

### Targeting

Targeting is a **mechanical property, not a label** — it decides what hexproof can stop and
what can fizzle. An effect's reach over creatures is one of:

- **all** — every creature in a set ("creatures you control"); **not** targeted.
- **chosen** — you pick one, but it is **not** targeted mechanically ("a creature you
  control").
- **targeted** — you pick one **and** it uses the targeting mechanic ("target creature").

**The rule that sets it:** an effect is targeted **iff its source text contains the word
"target."** Hexproof bites only on `targeted` effects, which is why the distinction must be
preserved even for friendly ones.

Every target is a structured descriptor, not a flat name:

```
target: {
  class:        "creature" | "action",     // counters target actions; everything else creatures
  mode:         "self" | "chosen" | "all",
  side:         "ally" | "enemy" | "any",  // omitted for mode:self
  exclude_self: bool,                      // "another …" excludes you
  targeted:     bool                       // chosen-only
}
```

Validation rejects `targeted` on `self`/`all`, requires `side` unless `self`, forbids
`draw`/`scry` resolving to an enemy (they have no library), and enforces that only counters
carry an action-class target.

**Shared targets.** When several effects on one card must hit the **same** chosen target
(Sign in Blood: one player both draws and loses life), the card declares a **slot** in its
`targets` map and each effect references it with a `$`-prefixed string. The engine resolves
each slot **once** and applies it to every referencing effect.

```json
"targets": { "T1": { "mode": "chosen", "side": "ally", "targeted": true } },
"effects": [
  { "kind": "draw",      "amount": 2, "target": "$T1" },
  { "kind": "lose_life", "amount": 2, "target": "$T1" }
]
```

### Keywords

The **keyword registry** in `core/ltg_core/schema.py` is the single source of truth for each
keyword's identifier, display name, gloss, grantability, and params. `grant_keyword` and
`remove_keyword` reference a keyword by name for a duration; they never redefine it.

| keyword | LTG meaning |
|---|---|
| **flying** | on defence, struck only by ranged, other flyers, or reach |
| **reach** | its melee may strike flyers, and pins an enemy melee-flyer |
| **first strike** | may hold its attack and use it as a reaction (strikes first) |
| **double strike** | the basic attack strikes twice |
| **vigilance** | may attack **and** still cast or act |
| **haste** | may take its proactive action **and** make a free voluntary move |
| **trample** | excess damage overflows to the same or an adjacent row |
| **deathtouch** | its damage can **execute** a minion outright |
| **lifelink** | heals equal to the damage it deals |
| **hexproof** | can't be **targeted** by enemy spells and abilities — but **basic attacks still land**, in both directions |
| **indestructible** | damage can't drop it below 1 HP; exile or a −X/−X to effective HP ≤ 0 still kills it |
| **protection** | prevents the next spell or attack against it (optional `from` param) |

**Retired** (menace, ward, convoke) are rejected for granting with a clear error, as are
unknown keywords.

**Trample** cleaves precisely: when the primary target *falls*, the excess spills onto
**exactly one** further creature on the felled target's own side — its row or an adjacent
one, lowest effective HP first, and only if the attacking mode can legally strike it (a
ground melee swing can't cleave onto a flyer). The carry is combat damage, goes through
that creature's own mitigation, and never cleaves again. No legal carry target and the
excess is lost.

**Lifelink and deathtouch read damage that *connects*** — what survives mitigation and
prevention and actually lands. A hit fully absorbed by Mitigate heals a lifelinker for
nothing; a hit reduced from 4 to 2 heals for 2.

### Translated MTG terms

| MTG term | LTG |
|---|---|
| discard (targeting an enemy) | strip its current telegraphed intent |
| mill | no effect on enemies (they have no library) |
| return to hand / bounce | send a minion to the *in hand* zone; it redeploys a turn later |
| land | not a card; a reference inside ramp/ritual spells → mana capacity |
| mana value / CMC | the card's or enemy's **Level** |
| tap | the enemy skips its next intent (`stun`) |
| sacrifice | the source loses half its remaining HP |
| exile | remove permanently; minions always, bosses only in their execute window |

Land references translate to the capacity model: *Forest* → G, *Island* → U, *Swamp* → B,
*Plains* → W, *Mountain* → R, *"a basic land"* → `choice`. *"For each land you control"*
becomes a capacity value-ref `{"ref": "mana_capacity"}`. *Landfall* becomes a
**`capacity_increase`** trigger on a channeled card, firing on both the +1/turn lock and on
`ramp`.

---

## Enemies

Enemies are **asymmetric** — no deck, no hand, no mana. An enemy has HP, a **Level** (its
inherent power tier, fixed and independent of current HP), and one or more intents. Level
gates read the Level; HP-based executes read current HP. The two are distinct.

### The generative object

**Blends, not classes.** There is no fixed enemy taxonomy. "A tanky fighter that heals
himself when hurt" and "an evasive hexer that debuffs from the shadows" are *compositions*.
Named presets exist as conveniences, never as limits.

```
enemy = {
  name, flavor, description,   # description feeds art generation
  faction_id,                  # constrains every palette
  level,                       # DERIVED from total cost — never authored
  chassis,                     # the body: HP, Power, attack profile, home row
  keywords: [...],             # static properties
  components: [...],           # the mind: blended behaviours, both timings
  is_boss: false
}
```

### Chassis — the body

Preset stat packages (pre-spent budget) that upgrades extend.

| chassis | HP | Power | attack | home row | cost |
|---|---|---|---|---|---|
| **Husk** | 2 | 1 | melee | front | 5 |
| **Bruiser** | 4 | 2 | melee | front | 10 |
| **Skirmisher** | 2 | 2 | melee + ranged fallback | mid | 10 |
| **Artillery** | 2 | 2 | ranged | rear | 10 |
| **Caster-frame** | 2 | 1 | ranged | rear | 7 |

Upgrade prices: **+1 HP = 1 pt · +1 Power = 3 pts · adding a ranged attack = 2 pts** (melee
is free). If the primary attack mode has no reachable target, the enemy falls back to its
ranged mode; if neither reaches, it **moves** toward reach.

### Components — the mind

A component is one instantiated behaviour, contributing rules to the enemy's single merged
priority list.

```
component = {
  archetype, timing (proactive|reactive), trigger, condition,
  cooldown, priority, verbs[], target_rule, telegraph, channel?
}
```

**Archetypes and base costs:** Evasive 2 · Punish 3 · Fortify 3 · Ward 3 · Counter 3
(reactive-only) · Burst 4 · Debilitate 4 · Escalate 4 · Drain 5 · Swarm 6.

**Cost modifiers** (multiplicative, round up): cooldown 1 = **×1.5** · cooldown 2–3 = ×1.0 ·
once-per-encounter = **×0.5** · **reactive timing = +2 flat** after multipliers (reactions
deny the player tempo, so they price higher).

**Verb magnitudes scale with Level L**, and a generated component uses these unless it buys
an off-schedule value (not currently allowed):

| verb | magnitude |
|---|---|
| `deal_damage` (Burst/Punish) | L + 1 |
| Drain (damage and self-heal, each) | ceil(L/2) + 1 |
| `heal` (Fortify) | L + 2 |
| `pump` / `wound` | ±ceil(L/3) |
| `counters` (Escalate) | +1/+1 per firing |
| `lose_life` (unpreventable) | ceil(L/2) |
| `stun` / `taunt` / `strip_intent` | binary, no magnitude |
| `create_token` | a Husk at level ceil(L/2), max 2 alive per creator |

**Triggers** (reactive components): `on_hit` · `on_ally_hit` · `on_ally_death` ·
`on_targeted` · `on_spell_cast` · `on_attack` (a hero's attack is on the stack — the
duellist's window) · `on_incoming_lethal` · `on_ally_below_N` · `on_self_below_N` (the
minion-grade "bloodied roar" — pair with once-per-encounter) · `on_hero_downed` (the pack
surges) · `on_hero_healed` (punish the medic).

**Conditions** gate any component: `self_hp_pct` (bloodied behaviour) · `turn` (an escalation
timer) · `ally_count` (desperation) · `hero_count` (anti-party cleaves) · `hero_channeling`
(arms a ritual-breaker only when relevant) · `self_channeling` (defend-the-ritual).

**Enemy-eligible keywords** each carry a min level and cost: reach (1/1) · trample (2/2) ·
flying (2/4) · lifelink (3/3) · deathtouch (3/4) · protection (4/3) · hexproof (4/4) ·
indestructible (6/6). **Never on enemies:** first strike, vigilance, haste — the
action-economy keywords stay player-only.

### Budget and derived Level

**`B(L) = 5·L + 5`** → L1 = 10, L2 = 15, L3 = 20, L5 = 30, L10 = 55.

**Total cost** = chassis (with upgrades) + keywords + components (after modifiers), and
**Level is derived**: the smallest L whose budget covers the total. Underspending is legal
(a simple high-level enemy); overspending is impossible.

This is what makes **complexity self-balancing**. A three-component conditional enemy
*cannot exist* at level 2 — the budget won't cover it.

### The AI — a merged priority list

Move selection is **deterministic code heuristics**, never an LLM at runtime. All rules from
all components merge into **one priority-ordered list** (lower number first), evaluated
**first-match-wins** in two passes:

- **Proactive pass** (the Intents step) — the top rule whose condition holds, cooldown is
  ready, and target exists declares as this turn's telegraphed intent.
- **Reactive pass** (whenever a trigger window opens) — the top eligible rule whose trigger
  matches fires as a reaction, at most one per enemy per window.

Priority bands, by convention: **10–19** emergencies (self-preservation, `on_incoming_lethal`)
· **20–49** tactical opportunities · **90** the default basic attack. Every enemy's list must
terminate in that default Attack rule, so the proactive pass always produces an intent. Ties
resolve by authoring order. Fully deterministic.

### Target valuation — the default-attack brain

When a rule targets by `valuation`, candidates are first filtered by **reachability**, then
ranked:

1. **Finishable** — effective HP ≤ this hit's damage.
2. **Channel-breakable** — the target is channeling and this hit is ≥25% of its max HP.
3. **Role value** — actively-casting and support targets first, then ranged, then melee.
4. **Lowest current HP.**
5. **Deterministic tiebreak** — row order, then alphabetical name.

This is what makes an archer snipe the exposed channeler and a brute finish the wounded
frontliner **without scripting either**.

Other target rules sharpen it: `highest_threat` (the assassin's read — cut the sword arm) ·
`lowest_hp_ally` and `wounded_ally` (support that skips the unwounded, so a healer never
wastes a turn) · `channeling_player` (the ritual-breaker) · `trigger_source` (whoever caused
the trigger) · `self`. **Control spreads:** a stun rule skips already-stunned heroes and a
taunt rule skips already-taunted ones, so two control pieces no longer overwrite each other.

### Bosses, enrage, and bloodied moments

A **minion** is removable — destroy, exile, and bounce all work. A **boss** is
"player-class": **immune to removal** until its execute window. You can still damage, attack,
counter, debuff, stun, and strip a boss — anything that affects it *in place* works; only
effects that would *remove it from the board* are blocked.

A boss has one threshold at **≤25% of maximum HP**, which is both its **enrage line** and its
**execute window**. Crossing it does four things at once:

1. **Fires its Enrage component** — a free, once-per-encounter, multi-verb eruption you
   always eat.
2. **Shakes off control** — stun charges and taunt drop. Fury does not sit out a turn.
3. **Resets component cooldowns** — the post-enrage kit opens at full aggression.
   Once-per-encounter firings stay spent; the drama never repeats.
4. **Opens the execute window** — removal now works.

Mitigating or dodging the enrage is **fair play**; the lever is making the answer *cost*
enough, not forbidding prevention. Bosses get **2.5× the normal budget** for their level, and
their components may carry a phase gate (`pre_enrage` / `post_enrage`).

Minions get their own dramatic moments through `on_self_below_N` + once-per-encounter — the
"bloodied roar" pattern — so fights stay dynamic away from the boss.

### Enemy channels and counterspells

Enemies use the same channel machinery you do: a proactive component marked `channel: true`
starts a held ongoing effect (continuous `while_channeled` auras, or `upkeep` ritual ticks)
that the party breaks by hitting the channeler for ≥25% of its max HP in one blow, or by
removing it. The channel enters play **through the stack**, so it can be countered before it
exists. Channels are the strongest decision-generators in the design: a visible, growing
threat with a clear answer. Standard difficulty and above must field at least one channeler.

A reactive component whose verbs include `counter` answers the stack action that tripped its
trigger — aimed at the same `#uid` handle a player's Negate uses. It sits on the stack
itself and reopens the party's window, so you can counter the counter. Design guidance
encoded in the generation prompt: **at most one counter-piece per encounter, always on a
cooldown.** Scarce is thrilling; spammed is miserable.

### Factions

An encounter draws **all** of its enemies from **one faction**. The faction manifest is the
contract handed to the LLM — cohesion by construction, since no frost giant can appear in the
vampire coven if the palette doesn't contain one.

```
faction = { id, name, flavor, colors[≤3], allowed_chassis[], allowed_keywords[],
            allowed_components[], role_presets[], boss_hooks[] }
```

Worked example — **The Crimson Coven** (B/R vampires), in
[examples/encounter_crimson_coven.json](examples/encounter_crimson_coven.json):

| | **Grave Thrall** | **Bloodbat** | **Vampire Adept** |
|---|---|---|---|
| Level (budget) | 1 (10) | 2 (15) | 4 (25) |
| Chassis | Husk +4 HP → 6 HP / 1 Pwr | Skirmisher → 2 HP / 2 Pwr | Caster-frame +4 HP → 6 HP / 1 Pwr |
| Keywords | — | flying | lifelink |
| Components | — (default Attack only) | Evasive: reposition when melee-threatened | Drain (cd 2): deal 3, heal 3 · **reactive** Debilitate: `on_spell_cast` → wound the caster |
| Plays like | a wall that shambles forward | a dodging harasser only ranged/reach answers cleanly | the piece you must answer |

And the two blends that motivated the whole framework:

- **Ironhide Warleader** — *"a tanky fighter that heals when hurt"* (L5, 29/30): Bruiser
  +6 HP +1 Pwr · trample · **Fortify-self** at priority 10 gated on `self_hp < 50%` · a
  reactive **Punish** that hits back `on_hit`. Healthy, it swings; bloodied, the heal rule's
  condition flips true and outranks the attack. **The condition *is* the arbitration.**
- **Mistveil Hexer** — *"an evasive magic rogue"* (L4, 25/25): Skirmisher +3 HP · hexproof ·
  a cooldown-1 **Debilitate** · **Evasive** repositioning. Hard to pin, chips your action
  economy every turn.

---

## Encounters & generation

### The encounter file

An encounter is a **design pool** of enemies plus **four rosters** — one per party size —
resolved when the game starts.

```json
"enemies": [ … the design pool … ],
"layouts": {
  "1": ["wolf", "shaman"],
  "2": ["wolf", "wolf", "shaman", "alpha"],
  "3": ["wolf", "wolf", "shaman", "shaman", "alpha", "alpha"],
  "4": ["wolf", "wolf", "wolf", "shaman", "shaman", "alpha", "alpha", "alpha"]
}
```

**One pool, four rosters.** Each layout lists pool ids; **repeats clone** the design with
unique runtime ids (`wolf`, `Wolf 2`). At game start, `scale_encounter(scenario, party_size)`
fields the layout matching the starting party, clamping to the nearest defined size. An
encounter with no `layouts` key is a fixed roster, so all hand-authored content is unchanged.

**Validation on save:** layout ids must exist in the pool, a boss must appear in **every**
layout, and every per-size roster must actually build in the engine (clones included).

### Encounter budget

**Total enemy Levels ≈ 2 × party size × average party level × difficulty**, where difficulty
multiplies **easy ×1.0 · standard ×1.5 · hard ×2.5**. A boss counts double.

Independently of budget, an encounter must field **at least 2× the party size in bodies** at
every layout — the party is always outnumbered. And after the model produces an encounter,
every enemy's HP is multiplied in code by **easy ×1.0 · standard ×1.2 · hard ×1.5**: the
chassis baselines are low enough that one removal plus a chip effect would clear them, and
scaling in code guarantees that floor regardless of what the model returns or how you've
edited the prompt. The multiplier is kept shallow on purpose — HP buys a fight *length*,
not *difficulty*, so the challenge is meant to come from the budget and from being
outnumbered.

Both of these are playtest-tuned in [`llm.py`](apps/game-server/ltg_game_server/llm.py)
(`DIFFICULTY`, `ENEMY_HP_MULT`, `_min_enemies`). The budget multipliers were raised from
Update 04's original numbers because the base fight ran too easy; the HP multiplier was
then lowered again because it made hard fights a slog rather than a challenge — see
[Design Update 07 §X-5](ltg_design_update_07_errata_and_rebalance.md). One consequence worth
knowing: **the old "hard" is roughly the new "standard,"** so an encounter authored against
the Update 04 values reads a band easier than its label.

Note that HP is scaled *after* Level is derived from budget, so the multiplier never feeds
back into cost. The budget prices an enemy's **complexity**; the multiplier tunes the fight's
**length**. Every number in the enemy framework is a **playtest starting value** with a
register ID, collected in a Rebalance Register. Mechanisms are canonical; magnitudes are
provisional.

### LLM generation

From the game's **Options → LLM** panel you set an **OpenRouter API key**, pick a model, and
edit the system instructions. Then **New Game → Generate encounter** produces a fresh fight
scoped to the party you picked.

The generation loop:

1. Read the picked party — size, average level, colours — and the chosen difficulty.
2. Send the (editable) system prompt, which teaches the entire framework above: the chassis
   table with prices, component archetypes and cost modifiers, verb magnitudes by level, the
   full trigger/condition/target-rule vocabulary, channel-first design, multi-verb enrages,
   and the layouts contract. Followed by a per-request block with the concrete party and
   **four budget lines** (one per party size), so a single generation serves any party.
3. Parse the reply as JSON (tolerating code fences and stray prose), scale enemy HP, and
   check the layout shape.
4. Require the art/narration data: a top-level `scene` and a `description` for every enemy.
5. Feed the result through `content.save_encounter` — **the exact same validation and persist
   path a hand-authored encounter takes.**
6. **On any validation failure, re-prompt the model with the engine's own error message** so
   it can repair its output, up to a retry limit.

The LLM never touches resolution. It fills a schema; the engine executes it.

Models are selectable (GLM, Gemini, Claude); the slugs live in `MODELS` in `llm.py` and are
easy to edit when OpenRouter's drift. The API key and instructions persist to a single
gitignored JSON file under `loadouts/`, so the key never enters version control.

### Art generation

The same encounter prose drives image generation: the top-level `scene` becomes a battle
backdrop, and each enemy's `description` becomes its portrait. Two backends:

- **OpenRouter (cloud)** — calls a fixed image model with your stored key.
- **ComfyUI (local workstation)** — queues your own workflow against a local ComfyUI server,
  injecting `%prompt%`, `%width%`, and `%height%` placeholders.

Every prompt is composed of an **editable aesthetic wrapper** (Options → LLM → Art
Generation) + per-image task framing + the encounter's own prose. Images are written under
`loadouts/art/<encounter_id>/` and referenced from the encounter JSON by server-relative URL,
so a saved encounter replays with its art and the JSON stays small. Enemy art is keyed by the
**pool** id, so layout clones share the base design's image. Art can be regenerated mid-game
and re-broadcasts to every connected client.

---

## The apps

A monorepo with a **shared core** and separate apps. Every app depends on `core`; the apps
never depend on each other. The validated **loadout JSON is the contract**: the Deckbuilder
*emits* it, everything else *consumes* it.

```
core/                     shared library — the single source of truth
  ltg_core/
    schema.py       Pydantic models — effects, target descriptors, keyword registry,
                    Card, Character (points-buy), Loadout, deck_status
    translation.py  translation registry (text→effects) + effects→text renderer
    lints.py        advisory, non-blocking validation lints
apps/
  deckbuilder/            authoring app  →  ltg-deckbuilder :8000
    ltg_deckbuilder/
      app.py        FastAPI: search / add / validate / export / schema + static serve
      ingest.py     Scryfall→Card builder (uses core's translation registry)
      scryfall.py   throttled Scryfall client
    frontend/       vanilla SPA, no build step
  combat/                 the engine    →  ltg-combat-cockpit :8001
    ltg_combat/
      state.py      the GameState value: party, enemies, stack, phase, event log
      engine.py     the pure engine: legal_actions / apply_action, resolver, stack,
                    turn loop, enemy AI, win-loss (one handler per effect primitive)
      scenario.py   encounters as inputs + the loadout→engine adapter
      harness.py    the scripted-scenario proof — drives §A/§C, asserts every step
      repl.py       the text UI
      server.py     the cockpit backend: state + history + load/step/raw
      serialize.py  state → JSON for the cockpit
    frontend/       the cockpit web GUI, no build step
  game-server/            the game      →  ltg-game :8020
    ltg_game_server/
      app.py        REST lobby + per-session WebSocket + static client
      session.py    authoritative engine state + seats + connected clients
      snapshot.py   seat-filtered state (hidden information)
      content.py    character/encounter registries, validation, persistence
      llm.py        OpenRouter client, the generation prompt, generate/validate loop
      art.py        image generation (OpenRouter or local ComfyUI)
  game-ui/                the React client (Vite + Tailwind), built into dist/
examples/                 fixture cards, loadout_*.json + encounter_*.json
tests/                    pytest — covers core + all three apps
```

### The engine

**LTG Combat** is a headless, deterministic combat runtime. Its entire contract is two pure
functions over a single `GameState` value:

- **`legal_actions(state) -> [Action]`** — the legal choices for whoever must decide right
  now. At any instant exactly one character (or none) holds priority.
- **`apply_action(state, action) -> (state', events)`** — the next state plus a structured
  event log. Between player decisions it auto-runs the automatic flow (upkeep, enemy intents
  and execution, end step) and **pauses at every reaction window**.

No I/O, no presentation, no LLM. State is treated as an immutable value — `apply_action`
never mutates its input, which is what makes time-travel debugging and the scripted harness
possible. `settle(state)` is a read-only *view* of the same advance, so a UI can render the
exact decision-point without computing a single rule.

Every client drives the engine through *only* those functions and owns **zero** rules.
Adding an effect handler is a localized change in `engine.RESOLVERS`.

### The game (`ltg-game`, port 8020)

One FastAPI app serves the built React client, the REST lobby, and a per-session WebSocket.
The server is **authority and relay only** — every action flows through the engine via
`Session.apply_index`, and this layer computes no rules.

A **session** owns exactly one authoritative `GameState` plus a **seat map**
(`character_id → client_id`). Seats are a pure server concept; the engine is seat-unaware.
The session enforces the two things the engine does not:

- **Hidden information** — a client only ever receives hands and legal actions for the
  characters it controls.
- **Action gating** — a client may only act for characters it controls.

Legality itself is always the engine's. Clients claim and release seats over the WebSocket
and receive a filtered state broadcast after every action. Sessions are in-memory (a restart
drops games).

The client is a React + Vite + Tailwind app following the **"Brasswork & Ink"** design system
([apps/game-ui/DESIGN_SYSTEM.md](apps/game-ui/DESIGN_SYSTEM.md)): a dark table lit for the
art, near-black ink surfaces, thin brass hairlines instead of filled boxes, one gold accent
that always means "you can act on this," and no emoji, ever.

### The playtest cockpit (`ltg-combat-cockpit`, port 8001)

A **cockpit, not a game** — a local web GUI for playtesting combat and debugging the engine.
It optimises for visibility and control: every number, intent, and rule-trace on screen,
every situation reachable fast. It is a thin client that owns zero rules; rewriting its front
end changes no outcome.

- **Load a fight from separate files** — up to 4 character loadouts (the exact Deckbuilder
  export JSON) plus one scenario JSON holding only the encounter. Mix and match any
  characters against any encounter. Built-in buttons load the §A and §C reference fights.
- **Play** — enemies across the top with their declared intents, the party across the bottom
  with mana by colour (reserved mana shown distinctly) and held channels as attached tags,
  the active character highlighted with their hand and the engine's legal actions as buttons,
  the stack when non-empty, and a filterable event log. **Targeting is two-click:** click an
  action, the engine returns its legal targets, click one. The UI never guesses.
- **Inspect** — any character's full kit, or the **raw** underlying state of any character,
  enemy, token, channel, or stack item. The "why did the engine do that" tool.
- **Time-travel** — the backend keeps the deterministic list of past states, so **Back** and
  **Forward** step the exact state. Rewinding to the move before a bug is first-class.
- **Quick setup** — tweak starting HP, Power, mana, or an enemy's intent value, hit **Apply**,
  and the fight rebuilds from turn 1. There is **no RNG and no shuffle** in the cockpit:
  library order is the loadout's card order, so every fight is reproducible.

Ready-made examples:

```
examples/loadout_soren.json  examples/loadout_ys.json  examples/loadout_mira.json
examples/encounter_a.json    examples/encounter_c.json
```

Load Soren + Ys + `encounter_a.json` to play §A; Mira + `encounter_c.json` for §C. These
reproduce the scripted traces exactly, and a test asserts it.

---

## Developing

### Run the tests

```bash
source .venv/bin/activate
python -m pytest -q
```

The suite covers the fixtures validating, card↔JSON round-tripping losslessly, malformed
cards being rejected, the Scryfall→Card mapping (against a **mocked** fetch), the full effect
and keyword vocabulary resolving end-to-end, the enemy framework and its intelligence layer,
encounter layouts (including validating the generation prompt's own gold examples through the
full save gate), and the **scripted scenarios**.

### The scripted scenarios (the proof, and the regression spine)

Two fully hand-traced fights are asserted state-by-state, deterministically, with zero input:

- **§A — the minions fight:** the turn loop, the stack, reaction windows, mana, removal.
- **§C — channeling:** multi-channel casting, mana reservation, a continuous aura, a recurring
  upkeep token engine, the reduced-below-threshold no-break rule, and an all-or-nothing break
  that releases reserved mana as a respondable trigger.

```bash
python -m ltg_combat harness                       # a PASS/FAIL trace for §A and §C
python -m pytest tests/test_combat_scenario.py -q  # the same proofs, under pytest
python -m ltg_combat repl examples/scenario_a.json # play §A yourself in the text UI
python -m ltg_combat validate examples/sample_loadout.json
```

A human making the §A choices reaches the same deterministic victory the harness proves —
entirely through the engine interface.

### Deckbuilder API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/scryfall/search?q=` | name → match list |
| POST | `/api/cards/add` | fetch + map + best-effort translate → Card (rejects Land / Planeswalker / Creature / Artifact with 422) |
| POST | `/api/cards/import` | bulk import a deck list → `cards[]` + `lints` + `not_found[]`; never blocks |
| POST | `/api/cards/validate` | structural-validate one card → re-derived text + `lints[]` |
| POST | `/api/loadout/validate` | `{valid, errors[], status}` (deck status) |
| POST | `/api/loadout/export` | engine loadout of validated cards + `omitted[]` report |
| GET | `/api/effect-specs` | per-primitive param descriptors + target modes/sides (powers the editor) |
| GET | `/api/schema` | exported JSON Schema of `Loadout` |

Save and load are client-side via the browser File System Access API, so loadout JSON lives
wherever you choose rather than in a server folder. Browsers without it fall back to a file
input and a download.

### Game-server API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/setup-options` | characters + encounters available to pick |
| POST | `/api/games` | build a session from `{character_ids, encounter_id}` |
| GET | `/api/games/{id}` | session status: seats, connected clients |
| POST/DELETE | `/api/characters`, `/api/characters/{id}` | save / hide a loadout |
| GET/POST/DELETE | `/api/encounters/…` | read / save / hide an encounter |
| POST | `/api/encounters/generate` | LLM-generate an encounter for a party + difficulty |
| POST/DELETE | `/api/encounters/{id}/art` | generate / clear scene or enemy art |
| GET/PUT | `/api/llm/settings` | API key, model, instructions, art backend |
| WS | `/ws/{session_id}` | `claim_seat` · `release_seat` · `submit_action` → `state` · `seats` · `prompt` · `game_over` |

### Adding an effect primitive

One localized change in `core/ltg_core/schema.py`, plus a renderer:

```python
# core/ltg_core/schema.py
class Silence(EffectBase):
    kind: Literal["silence"] = "silence"
    target: TargetOrSlot

# add Silence to LEAF_EFFECT_CLASSES (the Effect union is built from it)

# core/ltg_core/translation.py
RENDERERS["silence"] = lambda e: f"Silence {_tgt(e.target)}."
```

The Deckbuilder's effect editor is data-driven from `GET /api/effect-specs`, which derives
from the Pydantic models — so a new primitive surfaces in the editor with **no JS change**.
Then add its handler to `engine.RESOLVERS`.

### Adding a translation mapping

One `@register` call in `core/ltg_core/translation.py` — a regex mapped to an effect builder.
Targets are descriptors; use the `t_self` / `t_chosen` / `t_all` constructors:

```python
@register(r"gain (\d+) life")
def _(m, ctx):
    return [Heal(amount=int(m.group(1)), target=t_chosen("ally"))]
```

On **Add card**, every registered rule runs over the oracle text.

### Validation lints

Non-blocking warnings, shown in the Deckbuilder's detail panel, all living in one place
(`LINT_RULES`): no effects extracted · `draw`/`scry` resolving to *either* side ·
`exclude_self` on an enemy-only target (a no-op) · a `counter` that isn't an instant ·
zero or negative amounts · unused slots · a channeled effect that is neither continuous nor
recurring.

---

## Scope & status

**Built:** the effect vocabulary and `core` schema · the Deckbuilder (Scryfall import,
translation, character points-buy, effect editor, validation, loadout export) · the
deterministic combat engine, proven against scripted reproductions of hand-run paper
playtests · the enemy framework with its intelligence layer · LLM encounter generation with
art · the playable multiplayer game client with seats and hidden information.

The full keyword set is live, including `first_strike`'s held-attack reaction, `trample`'s
cleave, `double_strike`, and `scry`'s leave-or-bottom choice.

**Deferred:** `Defend`'s magnitude is a documented placeholder, and the ordering between the
continuous loss-check and pending stack items on simultaneous total-party incapacitation is
still an open edge (Design Update 01 §R-13). Leveling, XP,
and the multi-encounter run loop are **designed but deliberately not built** (Design Update 05
§P-5 onward) — a creation-only Deckbuilder must not surface an escalating cost or a level-up
affordance. Also deferred: off-schedule verb magnitudes, multi-faction encounters, the LLM
narrator (events are shown plainly), gear and inventory, exploration modes around combat, and
saving an in-progress game.
