# Langelier Tactical Game (LTG) — Game Design (GDD v2)

**Status:** the canonical rules reference, written 2026-09-24. It consolidates the v1 Game Design Document and Design Updates 01–24 (now kept as history in [design/](design/README.md)), checked against the code. **This document wins over all of them.** Where it and the code disagree, the code is what players get: fix whichever is wrong and don't let the two drift again.

**Audience:** anyone building or extending LTG, human or coding agent. It is a precise rules specification, not marketing copy.

---

## Contents

- §0 How to read this · §1 What LTG is · §2 Architecture & content pipeline
- §3 Cards
- §4 The combat model
- §5 The stack
- §6 Targeting
- §7 Keywords & terms
- §8 Channeling & stances
- §9 Enemies
- §10 Characters
- §11 The effect vocabulary
- §12 Encounters, objectives & adventures
- §13 Progression & economy
- §14 Scenario mode & campaigns
- §15 Glossary

---

## §0 How to read this

- **Current rules only.** This document says what the game does now, not how it got here. Each subsection ends with a source line naming the design `§` where the rule was decided and the main code symbol that implements it. Follow the `§` into [design/](design/README.md) for the rationale.
- **Numbering.** §1–§11 keep the v1 GDD's section numbers, because code comments cite "GDD §8" and similar. Sections after §11 cover systems added since.
- **Numbers.** Magnitudes are playtest starting values. Each `T-NN` is a row in [balance_register.md](balance_register.md), which holds the current value and the constant that implements it.
- **What isn't here.** Designed-but-unbuilt features, open questions, and owed playtests are in [roadmap.md](roadmap.md). Generation (who writes content, when, and under which gates) is in [generation.md](generation.md). The code layout is in [architecture.md](architecture.md).
- **Words.**
  - A **player** is a human. A **player-character** (hero) is one of the characters a player controls, and one player may control several. Turns, priority, and reactions are all per player-character.
  - The time ladder is round → encounter → phase → adventure → act → scenario → campaign (§14.1).
  - Glossary: §15.

---

## §1 What LTG is

LTG is a single-player / small-co-op **tactical RPG played as turn-based card combat**. A small party of player-characters (1–4) fights generated enemies on a three-row battlefield. Each hero owns a hand-built 20-card deck and a points-bought stat line. Outside combat, the party lives in **scenario mode**: a town with residents, shops, and quests, a three-act story against one villain, and **campaigns** that carry a fixed party from scenario to scenario. Presentation is a painterly, art-forward browser client in the spirit of *Darkest Dungeon*, *Slay the Spire* and *Disco Elysium*. It is a personal/playgroup project, not a commercial product.

The defining idea is a **hard wall between generation and resolution**:

- **Generation**: enemies, encounters, adventures, towns, residents, quests, dialogue, interludes, flavour, and art are produced by an LLM (and image models) at authoring or generation time. This is where the variety comes from.
- **Resolution**: the rules are always pure, deterministic code. An LLM never adjudicates a rule, computes a number, or decides a legal move at runtime. Town dialogue is authored as closed-vocabulary trees and walked deterministically.

The bridge across the wall is a set of **bounded vocabularies**: effect verbs for cards and enemies (§11), dialogue hooks (§14.4), and objective kinds (§12.2). An LLM can compose them freely, code can execute them exactly, and validators reject anything outside them. The motto: **borrow the grammar, own the numbers; infinite nouns, finite verbs.** LTG borrows the grammar of trading-card games (cards, mana, a stack, keywords) but defines its own rules and numbers. No knowledge of any other card game is assumed.

---

## §2 Architecture & content pipeline

| Component | What it is | Status |
|---|---|---|
| **The vocabulary** (`core/ltg_core`) | The shared schema: effect verbs, target descriptors, keywords, cards, characters, items, encounters, objectives, progression tables, and the renderer that turns effects into card text. Every app speaks it. | Built |
| **The Deckbuilder** | The authoring tool. Build a character with points-buy (§10), author custom cards in the effect vocabulary, assemble the 20-card deck, and write the brief, lore, and panel animations. It emits the **loadout JSON**, the contract with the game. | Built (custom cards only) |
| **The engine** (`apps/combat`) | A headless, deterministic resolver: `legal_actions(state)` / `apply_action(state, action)`. No I/O, no LLM, no presentation. | Built |
| **The game** (`apps/game-server` + `apps/game-ui`) | The server is the authority and relay. It owns sessions and seats (a player claims player-characters), filters hidden information, runs scenario mode, saves, and generation jobs, and computes no combat rules. The client renders snapshots and sends back choices. | Built |
| **The writers** | LLM generators that run at generation time only: the encounter designer, the adventure writer, the town generator, the arc and act writers, the interlude planner, and the deck-flavour writer. Each is gated by validators. See [generation.md](generation.md). | Built |
| **The worldbook** (`content/world/`) | Brief, append-only pages of what a traveller knows about each town and region (§14.7). | Built |
| **The narrator** | An LLM that turns the engine's event log into prose. It reads events and never changes them. | Not built (roadmap) |
| **The autoplay harness & tester** | Scripted policies that play the engine for crash and anomaly detection and A/B comparisons. The owner does not treat their absolute numbers as balance evidence. | Built |

**Three durable scopes** (§D24-2): **identity** lives on the character file (deck, skills, art, brief, lore, all read live); **history** lives on the campaign (levels, gear, purse, chronicle, ledger, town state); **geography** lives in the worldbook. Shared content (encounters, adventures, towns, the worldbook, the equipment catalogue, art) lives in the git-tracked `content/` folder. Characters and settings are per-install.

*Sources: v1 GDD §1–§2, §D17-3, §D24-2, §D24-8.3 · `engine.legal_actions` / `apply_action`.*

---

## §3 Cards

A character's spells are **cards**. Player cards are only instants, sorceries and enchantments (an enchantment is a `channeled` card). There are no creature, land or artifact cards: allied creatures exist only as tokens that cards create (§9.6), and "land" survives only as mana capacity (§4.4).

**The card object.**

| field | meaning |
|---|---|
| `name` | display name; also the singleton key |
| `cost` | `generic` + `colors` (pips per W/U/B/R/G) + `x` (the caster picks X at cast, §4.4). An empty cost is free |
| `timing` | `instant`: reactive, castable whenever the caster holds priority, never part of the turn. `sorcery`: active, cast in the caster's own main phase with an empty stack, as the Cast verb (§4.6). `channeled`: cast like a sorcery, then held as a channel that reserves its mana (§8) |
| `rarity` | common / uncommon / rare / mythic: power tier and deck quota; kept as a balance lever |
| `level` | converted cost (generic + pips; X counts 0), kept in sync by the Deckbuilder; read by card-level filters |
| `type` | display type line (Instant / Sorcery / Enchantment / Consumable). On the stack a player card is a **spell**; a consumable is an **ability** |
| `effects` | ordered effect primitives (§11), including `modal` and `conditional` containers. `targets` declares shared slots (`$T1`, …) when several effects must hit one pick (§6) |
| `translated_text` | rules text, re-rendered from `effects` on every edit unless `text_override` is set |
| `flavor_text` | optional in-character description of how the effect works; never rules |
| `validated` | a human has ratified the effects; any edit clears it |

Presentation fields and gear markers (`consumable_id`, `granted_by`) also sit on the card. Legacy MTG-lineage fields (`source_name`, `ignore_source`, `original_text`, `needs_translation`) still load but are pruned on save and export.

**The library.** A loadout is a **singleton** library of **at least 20 cards** (T-42) with rarity quotas (T-43):

| rarity | quota | rule |
|---|---|---|
| mythic | 1 | exact (floor = cap) |
| rare | 3 | exact |
| uncommon | 6 | exact |
| common | 10 | floor only: only commons may take the deck past 20 |

Singleton means no two cards share a name. Deck status is **advisory**: warnings for size, quotas, duplicates and off-colour cards (a cost pip, or a ramp or ritual colour, outside the character's colours) never block save, export or play. The Skill and Ultimate (§4.12) use the card schema on the character sheet but are not library cards. They are never drawn and sit outside the count, the quotas, the singleton rule and the lints.

**Authoring and validation.** Cards are authored from scratch in the Deckbuilder, in LTG's own vocabulary. "+ New Card" opens a blank card in the effect editor. Import Deck adds pasted JSON cards, parsing their rules text into effects where it can and flagging the rest for hand authoring. Cards pass three checks:
1. **Schema (hard).** The `Card` and `Character` models reject incoherent cards. For example: triggers and `while_channeled` only on channeled cards; `draw`, `scry`, `move_card` and `sap` never aimed at an enemy; only declared slots; only corpse-legal verbs on a corpse; unknown value refs; an Ultimate with a cost.
2. **Lints (advisory).** Examples: a counter that is not an instant, a zero amount, an unused slot, a channeled effect with neither a duration nor a trigger.
3. **Ratification.** Export and "Update Game Character" send only structurally valid, `validated` cards; the rest are left out and listed.

**Consumables** on the belt enter each encounter as extra, mana-free cards above the opening hand. They stack as **activated** abilities, so an `activated` counter answers them, and are exiled when used (§13.4; ruled 2026-09-25, M1.27c).

*Sources: GDD §3, §4.5 · §R-8, §R-9 · §X-1, §X-7 (T-42, T-43) · §D8-3.5 · §D17-4.4 · `schema.Card`, `Cost`, `deck_status`, `RARITY_MINIMUMS`; `lints.LINT_RULES`; deckbuilder `_build_engine_loadout`.*

---

## §4 The combat model

### §4.1 Battlefield & rows

Two sides face each other. The **party** is the player-characters, their ally tokens, and any enemy under the party's control. The **enemies** are minions, bosses and their tokens. Each side has three rows, **Front, Mid and Rear**; positions are rows, not a grid. Front and Rear are **not** adjacent.

Every combatant holds exactly one live `row` (§4.10). A hero starts on the row chosen on its sheet, an enemy on its layout row, and a token on Front unless its definition names a row. Corpses lie where the body fell (§9.7).

**The wall.** A ground **melee** attack may strike only the **front-most row that holds a grounded (non-flying) body** on the defending side. **Ranged** attacks strike any row, flyers included, but never from the Front row (§4.7). Flying and reach change the melee rule:
- A flyer is struck in melee only by an attacker with **flying** or **reach**. It never counts toward the wall row, never shields anyone and cannot interpose (it is *wall-transparent*).
- A **flying** melee attacker ignores the wall, but cannot strike rows behind a defender with **reach**.
- A **reach** melee attacker may also strike a flyer in the wall row, or the front-most flyers if the line is all flyers.

When an enemy aims at the party, heroes **and the party's tokens** count: grounded tokens form the wall like anyone, and enemies may single them out (ruled 2026-09-25, roadmap M1.27d).

Rows decide: melee reach; the ranged-from-Front ban; Mitigate adjacency (§4.8); interposition and positional intents (§4.10); row and blast splash shapes (§6); the trample carry (§4.7); and the fixed order of enemies and tokens: **row (Front first), then Level (low to high), then name**.

*Sources: GDD §4.1 · §R-1, §R-6, §R-13 · §M-B.6 · §L-1, §L-4 · §D23-3 · engine `_reachable_targets`, `_ordered`, `_r_create_token`.*

### §4.2 Round structure

A **round** has five steps, the turn tracker's `phase_step`: **Upkeep, Players, Allies, Enemies, End**. The engine splits Upkeep into four phases:

| step · phase | what happens |
|---|---|
| **Upkeep** · `upkeep` | per-round bookkeeping resets; the party turn order is announced on round 1; a boss whose `enrage_round` has come enrages (§9.5); **deferred ramp** arrives; stirring corpses count down (§9.7) |
| · `capacity` | **from round 2**, each standing character gains **+1 capacity** and locks its colour (the **curve-up**, §4.4) |
| · `draw` | each standing character's pool **refreshes**, it **draws 1** (round 1 included), and its per-round flags reset (Attack, Defend, Move and Mitigate used; turn verbs; Delay; an enemy taunt on it). Then **poison and regen tick** (§4.11). Then **recurring channel effects** fire (`upkeep` triggers and `after_turns` countdowns that fall due; party channels first), each pushed onto the stack as a triggered ability (§8) |
| · `intents` (Enemy Intents) | bounced enemies **redeploy**; objective waves and reinforcements deploy (§12.2); each enemy **declares** its intent(s), then each ally token declares its attack, in fixed order. Intents are veiled telegraphs (§9) |
| **Players** | each standing character takes its **turn** (§4.6), in party turn order |
| **Allies** | each ally token **executes** its attack |
| **Enemies** | each enemy **executes** its intent(s); a boss with two executes both, in order |
| **End** | End Step (below); objective timers tick; the round counter advances |

Anything put on the stack opens a reaction window (§5), in any step. Enemy cooldowns count in rounds (§9).

**Party turn order** is rolled once at encounter setup from the fight's seed and fixed for the encounter; moving rows never changes it. Delay (§4.6) moves a character to the end of the order. An incapacitated character gets no turn, no priority and no draw.

**End Step**, in order:
1. Any enemy or token at effective HP ≤ 0 dies (§4.3).
2. Temporary layers reset and turn-scoped effects expire (§4.9). Timed control counts down (§9).
3. A boss with `neglect` that went the round unhurt swells (§9.5).
4. Held channel auras re-apply (§8).
5. **Reaping.** Creatures at ≤ 0 die. A character still at ≤ 0 is incapacitated through the normal path, and its channels break. A character downed only by a turn-scoped wound stands back up.

*Sources: GDD §4.2 · §R-4, §R-5, §R-6 · §E-C · §D8-2.3 · §D22-2, §D22-4 · §D23-5, §D23-8 · engine `_advance`, `_begin_turn`, `_upkeep_draws`, `_fire_recurring`, `_declare_intents`, `_end_step`, `_reap_dead`; `serialize.phase_step`.*

### §4.3 HP, damage, incapacitation, death

**Damage is deterministic.** It lands for its stated amount: no to-hit roll, no variance. HP persists through an encounter. Between the phases of an adventure it carries over, floored at 25% of max (T-59, §12); otherwise each encounter starts fresh.

**Effective HP = `hp + temp_mod`** (§4.9). Every lethality check reads it, and a creature is alive exactly while effective HP > 0.

**How one hit resolves**, in order:
1. The source's primed `amplify`, if one matches (§11): the hit is multiplied first, and the tag is spent even if Mitigate then swallows the hit (ruled 2026-09-25, roadmap M1.27b).
2. Mitigate, if one was declared on the action and covers this hit; it may redirect the hit onto the guard (§4.8). So an amplified, mitigated hit deals h × m − X.
3. A matching `prevent` shield nullifies the hit (a `next` shield is spent).
4. A matching `protection` charge negates the hit (the charge is spent).
5. If what remains is ≥ ceil(max HP ÷ 4), the target's channels break after the resolution (§8).
6. Positive temp HP absorbs damage; a wound never absorbs.
7. The rest comes off `hp`, which floors at 0 (at 1 for `indestructible`). Overkill is lost unless trample carries it (§4.7).

Damage that **connects** = temp HP soaked + HP lost. Lifelink, infect, deathtouch, breaking regen, on-damage triggers and the gauge credit for dealing damage all read what connected. **Life loss** (`lose_life`, poison) is not damage: it skips steps 1–6.

**Falling.**
- An **enemy** at effective HP ≤ 0 **dies**. It leaves the board and its intents and stack items go with it. It leaves a corpse (§9.7), unless it was a token or was exiled. It fires death triggers. A body dies only once.
- An **ally token** dies and leaves no corpse.
- A **player-character** is **incapacitated**. It stays on its row but takes no turns, holds no priority and draws nothing. Its stack items are removed and its channels break. Each other standing character gains 25% gauge (§4.12). The **death event fires** (§8). Its counters stay. Harmful area effects pass it by and enemies never aim at it. Restorative verbs still reach it: heal, revive, pump, counters, grant_keyword, prevent, protection, amplify, double_next.
- A character **stands back up** the moment effective HP > 0. That can come from a heal (which fills any wound first), `revive` (to `max(1, floor(max_hp × to_fraction))`, default ½, temp layers cleared), a regen tick, or a turn-scoped wound expiring.

**Death is permanent.** Death removes the creature from the board. The End Step reaps creatures **before** resetting temporary layers, so an expiring −X/−X never hands back the toughness that killed them; characters are judged after the reset. Deathtouch executes any creature its damage connects with: an enemy (a boss only within its execute window, ≤ 25% HP; §9.5), a party token, or a hero, who is downed as by any blow to 0 (ruled 2026-09-25, M1.30). `indestructible` stops damage, life loss and poison at 1 HP and is immune to destroy and deathtouch; only exile, wounds and negative counters kill it (ruled 2026-09-25, M1.31).

*Sources: GDD §4.3 · §R-7, §R-10, §R-11 · §X-2.3, §X-3.2 · §D10-2 (T-59) · §D23-7.3, §D23-7.6 · engine `_deal_damage`, `_after_damage`, `_kill_enemy`, `_heal`, `_r_revive`, `_party_pool`, `_end_step`; `state.CharacterState.alive`.*

### §4.4 Mana

Each character has its own mana: a colour-locked **capacity** that curves up. There are no lands.

- **Starting capacity** is the character's starting-mana slots, one colour each, from the build (§10). Mana returns to this base every encounter; the pool fills at the round-1 refresh.
- **Curve-up.** From round 2, each Upkeep adds **+1 capacity** before the draw, spendable that same round. The player locks its colour from the character's colours (at most 3), whether or not the starting mana has that colour; a single-colour character locks automatically. Any capacity rise fires `capacity_increase` channel triggers.
- **Refresh.** At each Upkeep the pool becomes every capacity slot not reserved by a held channel. Unspent mana does not carry over.
- **Paying.** A coloured pip needs that colour; generic takes any. Payment is automatic (generic paid in W, U, B, R, G order) unless the player names the exact pips.
- **X costs.** The caster picks any X it can afford (0 upward) and pays X as extra generic mana. The `x` and `casting_cost` refs read it.
- **Ramp** (`ramp`) raises capacity above the curve. **Immediate:** capacity and pool now. **Tapped:** capacity now, spendable from the next refresh. **Deferred:** arrives at the next Upkeep. A `choice` colour (ramp or ritual) is picked at cast, one offer per colour of the character, like a mode or X; a single-colour character, or a choice fired by a trigger, takes the character's first colour.
- **Rituals** (`add_mana`) add to the current pool only, are lost at the next refresh, and never raise capacity.
- **Channel reservation.** A channeled card reserves exactly the pips paid for it. They are left out of every refresh while it is held, and return straight to the pool (not via the stack) when it ends (§8).
- **Sap** (`sap`) lowers capacity by N (never below 0), for `this_turn` or the `encounter`. Sap and channel reservation **stack**: the pool refreshes to capacity − sap − reserved pips. It trims the unspent pool to that at once and caps every later refresh; a held channel's reserved pips are never stripped. Cards cannot sap an enemy.

*Sources: GDD §4.4, §8 · §P-1, §P-4c · engine `_lock_capacity`, `_refreshed_pool`, `_pay`, `_cast_actions`, `_r_ramp`, `_r_add_mana`, `_end_channels`, `_r_sap` (code-only ruling, 2026-08-21); `state.CharacterState.capacity`.*

### §4.5 Library, hand & zones

**Setup.** Each character's library is its loadout, shuffled by the fight's seed. The **opening hand** is the top **`starting_cards`** cards (an integer from the build). Belt consumables and gear-granted cards are dealt on top of that hand and don't count toward the number (§13.3, §13.4). The library is **draw-and-keep**, and there is no hand limit.

**Draws.** Each standing character draws **1** at every Upkeep, including round 1, so the first turn opens with `starting_cards + 1` cards. An empty library yields nothing; there is no deck-out penalty.

**Card zones** (per character): library (top first), hand, graveyard, exile. A card goes to the **graveyard** the moment it is cast, even if countered; a channeled card's channel lives on without it (§8). A used consumable is **exiled**. `draw`, `scry` and `move_card` move a character's own cards between zones (§11); none of them can aim at an enemy.

**Enemy zones.** Every roster enemy is in exactly one zone:

| zone | how | on the board and targetable? | defeated? |
|---|---|---|---|
| in play | deployed | yes | no |
| in hand | **bounced** | no | no |
| suspended | **channeled** exile, while the channel holds | no | no, but never blocks victory |
| reserve | undeployed wave or reinforcement (§12.2) | no | no |
| graveyard | died (leaves a corpse, §9.7) | as a corpse only | yes, unless stirring |
| exile | exiled by a spell | no | yes |

**Bounce** sends a minion to hand. Its intents, stack items and channels go; it sheds temporary layers, shields, taunt and temporary keywords, but keeps its HP. It redeploys at the next Enemy Intents phase on the row it left, declaring afresh, so it loses one activation. While in hand it cannot be targeted, killed, bounced again or swept. A bounced ally token is destroyed. A **suspended** enemy returns when the channel ends, or is permanently exiled if the encounter ends first. Bosses are immune to bounce, exile and suspension above 25% HP (§9.5). Victory reads zones, not the board (§4.13): bounce delays a fight, never ends it.

*Sources: GDD §4.5 · §R-9, §R-13 · §E-A–§E-D · §X-2.2 · §D12-1 · §D17-4.4 · engine `_upkeep_draws`, `_draw`, `_do_cast`, `_bounce_enemy`, `_redeploy_bounced`, `_apply_static`; `scenario.state_from_dict`; `state.GameState.living_enemies`.*

### §4.6 The turn

A character's **turn** is its main phase in the Players step: it holds priority with an empty stack until it ends the turn.

**Two groups.** A turn is **either one turn-spending verb or the pair**:
- **Turn-spending verbs:** **Attack** (§4.7), **Cast** (sorcery-speed play: sorceries and channel starts; any number ride one Cast while mana lasts), **Skill** and **Ultimate** (§4.12). Taking one *is* the turn.
- **The pair:** **Defend** (§4.8) and **Move** (§4.10). Either one, or both in either order, is a full turn. Neither combines with a turn-spending verb.

**Freed verbs.** **Vigilance** frees Attack, **defender** frees Defend, **haste** frees Move; a defender never basic-attacks. A freed verb is not counted as part of the turn. It may be taken while at most one other verb has been taken. After it, exactly **one more** non-free verb is allowed, from either group but never the whole pair. So vigilant Attack + Defend is legal in either order; Defend + Move + a freed Attack is not. Two freeing keywords allow both freed verbs plus one more.

**Per-verb limits** also apply: one Attack, one Defend and one Move per round (reset at Upkeep); one Skill and one Ultimate per encounter.

**Free, never part of the turn:** instants (whenever the caster holds priority), Mitigate, Pass, dropping a channel (§8), and Delay.

**Restrictions.**
- A **stunned** character's main phase offers only End Turn, and each stunned turn it ends uses up one stun; its reactions stay open.
- `prevent attack` (Pacifism) forbids the basic attack.
- `prevent cast` (Silence) forbids casting cards other than consumables. It does not stop the Attack, Skill or Ultimate.
- An enemy **taunt** forces the character's basic attacks onto the taunter while that enemy lives and is reachable, through the character's next turn.
- A held **stance** may remove or replace Attack, Defend, Move and Mitigate (§8).

**Delay.** At the start of its turn a character may Delay: before any verb, once per round, not while stunned, and only if another character still has a turn this round. It moves to the end of the party turn order for the rest of the encounter.

**End Turn** closes the turn.

**Automatic passing** is done by the game server, never the engine, and each automatic action is logged.
- A reaction window whose only legal action is Pass is **auto-passed**.
- A main phase with only End Turn (and Delay) left is **auto-ended**.
- A channel holder is never auto-passed, and choices (including the capacity-colour pick) always wait for the player.
- **Pass-All** is a per-character toggle: it passes that character in every reaction window until the turn-tracker step changes. It never plays a main phase.

*Sources: GDD §4.6 · §R-12 · §D8-4 · §D9-2.3 · §D23-1, §D23-2, §D23-7.1, §D23-8 · engine `_proactive_open`, `_freed`, `_legal_main`, `_legal_attack_targets`, `_can_delay`, `_do_delay`, `_do_end_turn`, `auto_pass_action`, `pass_all_action`; server `Session.set_pass_all`.*

### §4.7 Power & attacks

**Power** is a combatant's attack value. A character's base Power is its attack mode's free base (melee 2, ranged 1) plus any Power bought with build points (§10), raised permanently by +1/+1 counters. **Current Power** = base + temporary bonus (pump +, wound −), never below 0.

**The basic attack.** Attack strikes one enemy the character can legally reach (§4.1). It deals the attacker's **current Power, read when it resolves**, so a pump or wound that lands while it waits changes what lands. It goes on the stack as an **attack** and opens a reaction window. If the attacker has left play by then, it fizzles. A race objective's guards can shield a marked enemy (§12.2).

**Melee vs ranged (`attack_mode`).** Each character has one mode; action modifiers (`make_ranged`, `make_melee`, `switch_mode`) can change it for a duration (§11).
- **Melee** reaches only the wall row. **The lunge:** a melee attacker outside Front moves to Front the moment the attack is declared, before the reaction window. The move stands even if the attack is countered, and the re-check runs at once (§4.10).
- **Ranged** reaches any row but **never from the Front row**: a ranged basic attack is illegal from Front. This applies to heroes, ally tokens and enemies, including an enemy's row-aimed volley. Spells are not attacks and are unaffected. Leaving Front restores the shot the same turn.

**Keywords in brief** (full glossary §7):
- **double strike:** the basic attack strikes twice, including a first-strike swing.
- **first strike:** during the Enemies step, a character that has not used its basic attack this round may make it as a reaction, at an enemy that has an action on the stack (ruled 2026-09-25, roadmap M1.28). It resolves before the action it answers and can kill the attacker first.
- **trample:** a killing blow's overkill carries to exactly one more creature. The carry target is on the victim's side, in the same or an adjacent row, and legally strikable; the lowest effective HP is chosen (then row, then name). The carry goes through that creature's defences and never carries again; with no legal target it is lost.
- **lifelink** heals by the damage that connects; **deathtouch** executes what it connects with, heroes included (§4.3); **hexproof** does not stop attacks.

**The combat-damage lane.** `prevent`, `protection` and `amplify` name a damage lane:
- **combat lane:** basic attacks, activated and enemy component abilities, fights, and triggered Combat Abilities (§4.8);
- **spell lane:** spells and other triggered abilities.

A combat-lane effect may be narrowed to **melee** or **ranged**, judged by the attack's declared mode, an ability's owner's mode, or melee for a fight.

*Sources: GDD §4.7 · §R-1, §R-3, §R-7, §R-12 · §P-1 · §X-3.1–§X-3.3, §X-4 · §L-2.1 · §D23-3 · engine `_do_attack`, `_r_deal_damage`, `_trample_cleave`, `_reachable_targets`, `_legal_react`, `_damage_lane`, `_prevent_match`, `_sync_attack_mode`.*

### §4.8 Defence

Because damage always lands, defence means answering the action:

| answer | tools |
|---|---|
| **Reduce** the hit | **Mitigate**. `prevent` shields nullify matching hits, all of them until End Step or just the next one. `protection` charges negate the next matching hit, whenever it comes |
| **Absorb** it | temporary HP: **Defend**, a `pump`'s toughness |
| **Cancel** it | a `counter` on the enemy action while it is on the stack (§5) |
| **Disrupt** it first | `strip_intent` removes and reveals a declared intent; `stun` makes the enemy skip one (§9) |
| **Remove** the attacker | destroy, exile or bounce a minion; a boss only within its execute window (§9.5) |

Movement adds a positional answer: put a body in the way, or step out of a targeted row (§4.10).

**Mitigate: the defensive reaction.**
- **Limit.** Free and never part of the turn; **once per round** per character (reset at Upkeep), and `mitigate_again` lifts the limit. Declaring it counts as that character's pass in the window.
- **What it answers.** The enemy action **on top of the stack**, if it is either of two things. First, any **attack**: a basic swing, an attack-classed component, or a positional row swipe. Second, a **Combat Ability** aimed at **one named victim**. A Combat Ability is an ability-class action (ability, activated or triggered) whose verbs deal damage; the class is worked out from the verbs, never authored (§M-A.7). Mitigate never answers spells, non-damaging abilities, Combat Abilities whose damage hits all of a side, a row or a splash, life loss, or poison.
- **Value.** **X = ceil(current Power ÷ 2), minimum 1**, read when the action **resolves**. `mitigate_full` makes X full Power, minimum 1.
- **Per hit.** Every hit aimed at the protected character is reduced separately: damage = max(0, hit − X).
- **Self mode:** available when the action targets you, or when you stand in the row a positional swipe strikes.
- **Ally mode:** available for a struck ally in your row or an **adjacent** row. Every hit aimed at that ally is redirected onto you and reduced by X: all of them or none.
- **The dash.** If the ally stands in another row, you move to it as you declare. This is an action-bound move, so the re-check runs (§4.10). Defenders dash too.
- **Riders (§M-A.7).** When a Mitigate is declared, a Combat Ability resolves its damage first, then its other effects on the protected character. If the Mitigate absorbed every hit, those riders **do not land**. If damage got through, they land on **whoever took the leftover damage**, which is the guard in ally mode: interpose against "deal 5 and stun" and you are the one stunned. On-hit effects such as lifelink fire off the damage that lands on the guard.
- **One guard per struck character.** Each character a stack item strikes may be covered by one Mitigate: their own, or one ally's interception. So every hero caught by a row swipe may blunt their own hit (§L-5). A character already covered is not offered again, so no Mitigate is wasted (ruled 2026-09-25, roadmap M1.17).
- The guard earns +1 gauge per point it prevents (§4.12).

**Defend: the defensive action.** Grants **temporary HP equal to base Power**. Pumps and wounds don't count; counters do; `defend_double` doubles it. The buffer soaks damage before HP and fades at End Step (§4.9). Defend is half of the pair, once per round, and earns +1 gauge per point. `defend_as_reaction` lets it be taken in a reaction window without touching the turn. **Defender** (hero-only; enemies ignore it) frees Defend and forbids the basic attack, first strike included (§4.6).

*Sources: GDD §4.8 · §M-A.1–§M-A.6 · §M-A.7 (code-only ruling: engine `_announce_combat_ability`, `tests/test_combat_ability.py`) · §R-11 · §L-2.1, §L-5 · §D19-5 · §D23-1, §D23-2 · engine `_legal_react`, `_mitigable`, `_is_combat_ability`, `_mitigate_value`, `_do_mitigate`, `_apply_mitigation`, `_mitigated_rider`, `_damage_first`, `_do_defend`, `_defend_value`.*

### §4.9 Temporary HP, wounds, counters & pumps

Every creature has a **temporary layer** on top of its base stats:
- `temp_mod`: net temporary HP, + from pump toughness and Defend, − from wound toughness;
- `power_bonus`: net temporary Power, + from pumps, − from wounds.

Each has an **encounter share**, and End Step resets the layer to that share (0 for turn-scoped effects).

| effect | Power | HP | lasts |
|---|---|---|---|
| **pump** +X/+X | +X | +X temp HP; soaks damage before `hp` and is gone once spent | `this_turn` (to End Step) or `encounter` |
| **Defend** | — | + base Power as temp HP | to End Step |
| **wound** −X/−X | −X | −X to `temp_mod`; never soaks damage, and the next healing fills it before restoring `hp` | `this_turn` or `encounter` |
| **counters** +X/+X | +X permanently | +X max HP and current HP | the encounter |

- A wound, negative pump or negative counters that bring effective HP to ≤ 0 kill or incapacitate **at once**, even through `indestructible`.
- Damage uses up an encounter buffer for good; healing closes an encounter wound for good.
- **Fades at End Step:** turn-scoped pump, wound and Defend layers; turn-scoped `sap`; every `prevent` shield, one-shots included; turn-scoped keywords and action modifiers. Channel auras re-apply straight after (§8). **Except** an enemy's turn-scoped lockdown on a hero (wound, sap, Silence/Pacify, a hostile modifier, a taunt), which holds through the hero's next turn (§9.9).
- **Persists:** encounter-scoped layers, +1/+1 counters, `protection` charges, `amplify` and `double_next` primings (until spent), typed counters (§4.11), stuns (until used up), and HP lost.

*Sources: GDD §4.9 · §R-7, §R-11 · engine `_r_pump`, `_r_wound`, `_r_counters`, `_do_defend`, `_reset_temp_layers`, `_sync_enc_temp`, `_expire_keywords`, `_expire_action_mods`, `_end_step`.*

### §4.10 Movement & interposition

**One live position.** Every combatant has a single `row`, and moves take effect immediately; reach, the wall, Mitigate adjacency and intent targeting all read that row. Movement never deletes an attack. It only changes who takes it.

**Kinds of move:**
- **Move (voluntary).** In the character's own main phase with the **stack empty**, so never while its own action is unresolved. It goes to any other row, costs no mana, and is limited to once per round. It is half of the pair and freed by haste (§4.6). It goes on the stack as a `move`: a reaction window opens, but nothing can counter it. The body relocates when it resolves.
- **Action-bound moves** happen the moment the action is declared: the melee **lunge** to Front (§4.7) and the ally-Mitigate **dash** (§4.8).
- **Forced movement** by the `move` verb (to a named row, or one row forward or back) is immediate. Enemies may shove heroes (§9.9); corpses never move.
- **Enemy movement:** a Move intent relocates the enemy as it executes, for example an Evasive retreat, or a ranged enemy in Front falling back to Mid (§9).

**The re-check (interposition).** Each **redirectable** enemy intent is checked again after every resolved Move, lunge, dash, forced move and enemy move. If its target hero is out of the attacker's reach, the intent **redirects** onto a reachable hero: a reachable taunter first, otherwise the enemy's own target valuation. It keeps its name, damage and riders. If the target is still reachable, or no one is, the intent holds. Stepping back with no one in front achieves nothing, and joining your target's row never steals a swing. At execution, a redirectable intent whose target is still out of reach fizzles. The death of an intent's target is handled at execution, not by a re-check (§9). Ally tokens' melee attacks are re-checked the same way.

**Redirectable** means: aimed at one living hero, **melee**, from a **non-flying, non-`relentless`** attacker, and either an **attack** or a **melee single-target Combat Ability**. **Never redirected:** ranged intents, flying attackers, `relentless` attackers (enemy-only: they pursue their target anywhere), positional intents, non-damaging abilities, and Moves. The veiled telegraph shows which it is: **"swing"** if it can be walled, **"pursues"** if it follows its target.

**Positional intents** aim at a **row**, not a name. Whoever stands in the row when the action resolves is hit; an empty row is a clean miss. They ignore taunt and never redirect, so leaving the row is the dodge, paid for with a turn. An attack-classed row swipe can still be Mitigated (§4.8).

*Sources: §L-1–§L-6 · §D9-3.1 · §D23-2, §D23-3, §D23-4 · engine `_do_move`, `_resolve_top`, `_do_attack`, `_do_mitigate`, `_r_move`, `_recheck_intents`, `_redirectable`, `_execute_intent`, `_fall_back_or_idle`; `serialize._veiled_entry`.*

### §4.11 Afflictions & typed counters

Three counter types can sit on any creature. All counts are public.

| counter | placed by | each Upkeep | removed by |
|---|---|---|---|
| **poison** | `poison` (N on resolution); **infect** (1 per hit that connects) | **loses 1 life per counter** | **any heal of 1 or more** removes **all** of them, even at full HP |
| **regen** | `regen` (N) | **heals 1 per counter**; this is real healing that fills wounds and fires life-gain triggers | **damage that connects** removes **all** of them |
| **charge** | `charge` (add N) | no tick | `charge` with `op: remove` (N, or `all` to defuse) |

- **Placing** counters changes no stats, and the count never grows or expires on its own.
- **Poison is not damage.** Prevention, Mitigate and temp HP don't apply, and it never breaks a channel. Its life loss still counts as HP lost for the gauge and as hurting a boss (§9.5), and deaths from it fire death triggers.
- **Poison and regen cancel** 1:1 as soon as they meet, so a creature never holds both.
- **Tick order** (Upkeep, after the draw, before recurring channel effects): party, then ally tokens, then enemies; poison before regen on each creature. Ticks open no reaction window. A downed character takes no poison tick but still regenerates, which can stand it back up.
- **Charge** is a plain resource on a hero. On an enemy it is the visible **windup**: reaching an `on_charge_full` component's threshold puts that hidden ability on the stack at once and resets charge to 0. Countering the ability still uses up the charge (§9). The `caster_charge` and `target_charge` refs read the count.
- **Infect** (keyword): each hit that connects places 1 poison counter, draining from the next Upkeep. Life loss never infects.

*Sources: §D8-2 as reworked by §D22-1, §D22-2 · §D23-5 · engine `_r_poison`, `_r_regen`, `_r_charge`, `_annihilate_typed_counters`, `_cure_poison`, `_break_regen`, `_tick_afflictions`, `_tick_afflictions_one`, `_check_charge_full`, `_deal_damage`.*

### §4.12 Heroic actions

Two abilities authored on the character sheet with the card schema (§3):
- **Skill:** `sorcery` or `channeled` timing (a legacy instant Skill loads as sorcery), and may cost mana. Once per encounter: `refresh_skill` restores it, and `lock_skill` (Hamstring) bars it. A channeled Skill starts a held channel, such as a stance.
- **Ultimate:** `sorcery` timing, **never a mana cost**. Once per encounter, only on a **full gauge**, which it empties.

Both are **turn-spending verbs** (§4.6); a freed verb can go with either, in either order. Both go on the stack as **activated abilities**: a spell counter cannot answer them, but an ability or action counter can. Neither counts as casting, so Silence does not stop them.

**The ultimate gauge** holds **raw points** toward a **charge cost of 100 + 20 × (level − 1)**: 100 at level 1, 160 at level 4. It starts each encounter at 0, is capped at the cost, and survives incapacitation. Clients read `ultimate_gauge_pct` = floor(points × 100 ÷ cost), capped at 100, and the Ultimate becomes available exactly at 100%. Between the phases of an adventure the raw gauge carries over at **50%, rounded down** (T-58, §12).

**Payouts.** *Magnitude* payouts are raw points and stay flat as levels rise. *Tempo* payouts are a percentage of the charge cost (rounded, minimum 1 point).

| source | payout |
|---|---|
| mana paid to cast a card (X included; a channel pays once, at cast) | +1 per pip |
| HP you lose (damage reaching HP, life loss, poison) | +1 per point |
| your damage that connects (attacks, spells, abilities, fights; not your tokens') | +1 per point |
| healing you give (wound closed + HP restored; overheal earns 0; lifelink included) | +1 per point |
| temp HP you grant (Defend, your pumps' toughness) | +1 per point |
| Mitigate | +1 per point it prevents; damage you still take pays as HP lost |
| countering an enemy action | the damage it would have dealt, or its source's level if none |
| stripping an intent | the intent's damage, or the enemy's level if none |
| stun | the enemy's current Power (or level if 0) for each intent it skips; paid to its last stunner |
| destroy / exile / bounce / deathtouch execute / exiling a stirring corpse | the target's level |
| taunting an enemy; breaking an enemy channel | the target's level |
| the first verb of your turn, unless it is the Skill or Ultimate | +2% |
| using your Skill | +5% |
| another party member is downed | +25% to each standing character, once per downing |
| `charge_ultimate` / `drain_ultimate` action modifiers | + or − the authored % |

Regen ticks pay the gauge of whoever placed the counters, as healing (+1 per point restored), and mana paid for the Skill earns +1 per point like a cast's, on top of the Skill's +5% (ruled 2026-09-25, roadmap M1.27a).

**Primed.** At **80% or more** (T-69) with the Ultimate unspent, or while holding an `amplify` or `double_next` priming, a hero counts as a **primed threat** for enemy targeting. Enemy rules can also read the gauge and react to an Ultimate on the stack (§9).

*Sources: §D8-3.1–§D8-3.3, §D8-3.5 (amended) · §D10-2 (T-58) · §D12-2.1, §D12-2.2 (T-69) · §D23-1, §D23-7.1 · gauge rework 2026-08-29 (code-only ruling) · engine `_do_use_skill`, `_do_use_ultimate`, `_heroic_actions`, `_gain_gauge`, `_gain_gauge_pct`, `_control_credit`, `_denied_value`, `_credit_strip`, `_credit_stun_denial`, `_primed_score`; state `GAUGE_LEVEL_STEP`, `ultimate_charge_cost`; server `adventure.GAUGE_CARRY`.*

### §4.13 Winning & losing

The end check runs before every automatic step and after every player action and stack resolution. It never runs mid-resolution.

**Victory:** no enemy is **in play**, **in hand**, **stirring** (§9.7) or in **reserve** (§12.2). Dead and exiled enemies are defeated; a suspended enemy never blocks the win and is permanently exiled when the fight ends. **Control never wins:** if only party-controlled enemies remain, all control ends and they return to the enemy side; raised undead crumble with the victory. Objectives can add endings: `survive` wins on its timer, and `deadline` or an expired `race` can lose (§12.2).

**Defeat:** all player-characters are incapacitated.

**Simultaneous ends.** Victory is checked first, so if the last enemy and the last standing hero fall in the same resolution, the party wins. When the last hero falls the fight ends at once and the stack is cleared. A pending heal cannot rescue the party, and a last hero downed by a turn-scoped wound loses even though the wound would have worn off at End Step.

*Sources: GDD §4.2, §4.3 · §E-B · §R-13 · §X-4 · §D9-1.4, §D9-1.5 · §D12-1 · engine `_check_end`, `_advance`, `_objective_tick`; `state.GameState.living_enemies`, `bounced_enemies`, `stirring_corpses`, `reserve_enemies`, `controlled_units`.*

---

## §5 The stack

Everything that resolves (casts, attacks, abilities, triggers, enemy actions) goes on one shared stack and resolves last-in-first-out. Only player-characters hold priority. Enemies answer through reactive components (§5.5).

### §5.1 Two axes

Every stack item has a **type** (spell or ability) and a **speed** (active or reactive). Both are derived, never stored: instant → reactive, sorcery → active, channeled → sustained; attack and activated → active, triggered → reactive.

| | **spell** | **ability** |
|---|---|---|
| **active** (spends the turn, §4.6) | sorcery · channeled card (§8) | basic attack · Skill · Ultimate · stance-replaced Attack, Defend or Move · voluntary Move |
| **reactive** (free) | instant | channel triggers · enemy reactions · the first-strike swing |

Defend takes effect at once, and Mitigate rides the item it answers, so neither is a stack item (§4.8).

**Filter lattice.** `counter`, `redirect` and `double_next` name a node; a node matches itself and everything below it.

```
action ─┬─ spell
        └─ ability ─┬─ attack
                    ├─ activated
                    └─ triggered
```

| stack kind | carried by | matched by |
|---|---|---|
| `spell` | hero card casts; copies (§5.4); spell-classed enemy actions | spell · action |
| `attack` | hero and token basic attacks; the enemy default swing; attack-classed row components | attack · ability · action |
| `activated` | hero Skill, Ultimate, stance replacement | activated · ability · action |
| `triggered` | channel and break triggers; enemy reactions, charge detonations, Enrage; objective escalations | triggered · ability · action |
| `ability` | an enemy's ability-classed proactive component; a consumable | ability · action |
| `move` | a hero's voluntary Move | nothing (it can't be countered) |

**Enemy classification.** An enemy component's `action_type` is thematic, but the engine enforces it:
- `"spell"` stacks as `spell`, so Negate answers it and Silence bars it.
- Otherwise a proactive component stacks as `ability`; a reactive component, detonation or Enrage stacks as `triggered`.
- The default swing is an `attack`. `"attack"` is honoured only on a row-aimed component.

**Combat Abilities (§M-A.7, derived).** An `ability`, `activated` or `triggered` item that deals damage (including through a modal or conditional) is a Combat Ability, unless it starts a channel. A Combat Ability:
- deals combat-lane damage (§5.5);
- trips on-attack triggers as it goes on the stack;
- can be answered by Mitigate when its damage names one victim;
- under a Mitigate, resolves its damage first, and its riders follow what got through (§4.8).

A melee, single-target one from a ground, non-relentless enemy can be interposed on (§5.2). Spells never are.

*Sources: GDD §5.1 · §R-8 · §D12-0 · §M-A.7 (code-only ruling) · §D23-4 · engine `_FILTER_MATCHES`, `_is_combat_ability`, `_mitigable`, `_damage_lane`, `_try_declare_component`, `_fire_reaction`; schema `FilterNode`.*

### §5.2 Intents

An enemy action lives twice: first as a veiled **intent**, off the stack, then as a fully visible **stack item** when it executes.

**Declaration.** In the Enemy Intents phase, bounced enemies redeploy and objective arrivals deploy. Each enemy then files one intent from its proactive pass (§9), in fixed order (row, Level, name). An enraged or `double_intent` boss files two (T-54). A component's cooldown is spent at **declaration**. Ally tokens then declare an attack on the reachable enemy with the lowest effective HP (controlled units: the closest), unveiled.

**Target lock.** The target is fixed at declaration. It moves only in three cases:
- **Interposition.** After any occupancy change, a *redirectable* intent whose target has left reach re-aims at the best reachable body (a reachable taunter first). Redirectable: a melee swing or melee single-target Combat Ability from a non-flying, non-relentless enemy, at a living hero.
- **Taunt.** A taunt re-aims the enemy's declared **hostile**, single-hero intents at the taunter, when the intent can reach them. It respects the wall: a melee body cannot be drawn onto a taunter behind grounded bodies, so its swing stays where it was aimed. Heals and buffs on the enemy's own side are never re-aimed, and row-aimed intents ignore taunt. While the taunt holds, the enemy's hostile rules and its basic swing declare at a reachable taunter (ruled 2026-09-25, roadmap M1.18 and M1.31).
- **Redirect.** Once the intent is on the stack, `redirect` can move it.

A **row-aimed** intent aims at ground: it hits whoever stands in the row at resolution, so leaving the row dodges it (§4.10).

**The veil.** Before the stack, players see only the category, template line, locked target (a name, rows, or none), status (declared · stripped · stunned · executed · fizzled), a stripped intent's reveal, the slot, and the redirectable bit. They never see names, verbs, amounts, keywords or channel status. Reactive components never telegraph. The seat snapshot carries only veiled lines, drops `intent_declared` log entries, and rewrites redirect and spoil lines without the intent's name. A teammate's draw or scry is logged without the card. The stack shows the action in full.

**Category.** The first match wins:
1. a Move intent → manoeuvre;
2. row-aimed → row assault;
3. any `charge` → gathering;
4. spell-classed → spellcraft;
5. any `create_token` → summon;
6. otherwise the first hostile verb decides:
   - a lockdown verb (`stun`, `taunt`, `strip_intent`, `remove_keyword`, `counter`, `sap`, `modify_action`, `break_channel`, or `prevent`/`move_card`/a forced `move` aimed at the party) → interference;
   - row- or blast-scoped → row assault;
   - `all` on the party → party assault;
   - anything else → threat;
7. nothing hostile, but corpse work (`control` — an enemy's only ever takes a corpse — or `consume_corpse`) → summon;
8. nothing hostile → support.

(Roadmap M2.13, 2026-09-25: a shove on a hero used to read as support, and a raise-dead as a buff.)

| category | chip | template line |
|---|---|---|
| threat | ATK | "X threatens T." |
| spellcraft | SPL | "X begins casting a spell at T / at your front row / on itself." |
| interference | FOIL | "X moves to foil T." |
| row assault | ROW | "X prepares an assault on your front and mid rows." |
| party assault | AOE | "X prepares an assault on your whole party." |
| gathering | GTH | "X gathers its power." |
| support | SUP | "X steels itself." / "X turns its attention to T." |
| summon | SMN | "X calls for reinforcements." |
| manoeuvre | MOV | "X shifts its footing." |

A stunned slot has no chip ("X reels — it has no intent."). Each declared line also carries a **swing** (redirectable) or **pursues** chip, and a boss's Inspect panel lists every declared intent.

**Execution.** In the Enemies step each enemy executes its intents in declaration order, each as its own stack item with its own windows.
- A Move intent relocates the body at once: no stack item, no window.
- A row-aimed intent goes straight onto the stack.
- Anything else is **re-validated** first (§D19-4). It is *spoiled* if:
  - its corpse is gone;
  - its target has left play, or is now a corpse the intent can't use;
  - its target gained hexproof against a targeted hostile spell or ability (attacks are exempt);
  - it has a targeted payload but never had a target.
- A spoiled intent is marked fizzled, never announced and never re-aimed. The enemy swings its basic attack instead: a real stack item that counts for cadence (§9). A pacified enemy, or one with nothing in reach, loses the activation.
- A redirectable swing with no reachable target fizzles.

Attacks and Combat Abilities fire on-attack triggers as they go on the stack. A swing's damage is read at resolution.

**Disruption.**
- **`strip_intent`** (aimed at the enemy) removes one declared intent and logs what it would have been. Against a two-intent boss the pick names the slot, and a side-wide strip clears both. The cooldown stays spent. With nothing declared, the strip lingers and smothers the next declaration.
- **`stun`** skips the enemy's next N declarations, but never cancels one already made. One stun suppresses one slot of a two-intent boss; Enrage clears stuns.
- **`prevent attack` / `prevent cast`** cancel matching declared intents and bar matching components.
- **Killing, exiling, bouncing or dominating** the enemy discards its intents.

*Sources: GDD §5.2 · §D8-1 · §D9-4 · §L-3, §L-5 · §D18-4 · §D19-4, §D19-5 · §D23-4, §D23-6 · T-54 · engine `_declare_enemy_intent`, `_redirectable`, `_recheck_intents`, `_intent_spoiled`, `_swing_instead`; serialize `intent_category`, `_veiled_entry`.*

### §5.3 Resolution & reaction windows

**Priority.** A hero who adds to the stack speaks first, and may answer their own item. Priority then passes around the living party in the fixed turn order. On an enemy's item, it starts with the first character in turn order. Downed characters are skipped; stunned ones still react. A window offers castable instants (Silence leaves only consumables), Mitigate (§4.8) or a stance replacement for it, the first-strike swing (Enemies step), `defend_as_reaction`, channel drops, and Pass. It never offers a sorcery, the Skill or the Ultimate.

**Closing a window.** Every addition resets the pass count. Once every living character has passed in a row:
1. The enemy side may make **one** reaction to the top item (§5.5). The reaction goes on the stack and opens a fresh window.
2. If none fires, the top item **resolves**. Pending channel breaks are processed (§8.1), and the enemy side may make **one** reaction to what just happened.

Each enemy reacts at most once per window, and every new top item opens a fresh window.

**Resolution.** The top item is popped and its effects resolve in authored order, with two exceptions: under a Mitigate, a Combat Ability resolves its damage first; and `consume_corpse` always resolves last. A top-level `scry`, a `move_card` with a real choice, or a triggered modal pauses for the pick and then resumes. A channeled cast starts its channel instead (§8.1).

**Fizzle** is per effect, never per card. An effect does nothing if:
- it needs a target and has none;
- it is **targeted** and its target has left the battlefield (dead, bounced, suspended) or its corpse was consumed;
- it is targeted and hostile, and its target now has hexproof (attacks exempt);
- it is an attack whose attacker has left play.

A scoped effect whose anchor fell to an earlier effect of the same card still hits the pinned ground (§6). When a creature leaves play or a hero is incapacitated, every stack item it originated is removed unresolved. That is how a first-strike kill cancels the blow.

**Trigger ordering.** Triggers stack as they fire. One fired mid-resolution waits until that resolution finishes. A hero's trigger has its mode, then target, chosen as it is pushed (topmost first), before anyone responds. Triggers from one event stack in watch order (party holders, each holder's channels in hold order), so the last pushed resolves first. The one exception is **the break sink**: a channel's own `channel_break` trigger is slipped beneath that card's waiting triggers, so its cleanup never pre-empts its own retaliation.

**One answer per episode (`reacted_episode`).** An *episode* is one stack item's life before resolving, or one resolution. A reaction's *signature* is its trigger, action type and verb shapes (kind at mode/side; amounts ignored). Once a signature has answered an episode, identical signatures on other bodies skip it, spend nothing and stay armed. Distinct reactions all still fire. The record resets each round.

**Server-side passing** (§4.6) is done by the game server, never the engine or the cockpit.
- **Automatic.** It passes when Pass is the only option, and ends the turn when only End Turn and Delay remain. It never does either for a channel holder, a pending choice or the capacity pick. These are logged "(auto)".
- **Pass-All** (§D23-8). A per-character toggle that passes the character's reaction windows until the turn-tracker step changes. It never plays a main phase. These are logged "(pass-all)".

There is no reaction strip, and the Mitigate cell carries no number; Mitigate's X is in its tooltip. **Delay** is a main-phase choice.

*Sources: GDD §5.3 · §F-7.4 · §E6-7 · §D8-4 · §D19-9 · §D23-8 · 2026-09-06 break-sink ruling · engine `_do_pass`, `_offer_reactions`, `_resolve_top`, `_resolve_effect`, `_purge_stack_from`, `_sink_break_under_own_triggers`, `auto_pass_action`, `pass_all_action`.*

### §5.4 Counters & copies

**Counter.** `counter {filter}` cancels an opposing stack item that matches its filter (§5.1); the item never resolves.
- A countered channel start never becomes a channel.
- A countered detonation has still spent its charge.
- A countered card is already in the graveyard.

A hero's counter picks an enemy item at cast. At resolution it re-checks that the item is still there, opposing and matching; if not, it does nothing. No side counters its own actions, and counters can be countered.

| filter | answers |
|---|---|
| action | any opposing item except a Move |
| spell | card casts, copies, spell-classed enemy actions |
| ability | attack, activated, triggered and plain ability items |
| attack | basic swings (hero, token, enemy) and attack-classed row components |
| activated | Skill, Ultimate, stance replacements |
| triggered | channel and break triggers, enemy reactions, detonations, Enrage |

An **Ultimate** stacks as `activated`. Negate (`spell`) never stops it; `action`, `ability` and `activated` do.

**Enemy counters** are reactive components with a `counter` verb and no target field. The engine aims them at the item that tripped a pre-resolution trigger. Typical pairings are `on_spell_cast` with `spell` (a counterspell) and `on_attack` with `attack` (a parry).

**T-70.** A counter on `on_ultimate_cast` is legal only on a boss, only `once_per_encounter`, and only with filter `action`, `ability` or `activated`. Anything else is rejected at load. Components that punish an Ultimate on that trigger are unrestricted.

**Wards.** A hero's trigger that answers the stack ("whenever an enemy attacks, cancel that attack") binds as it fires to the topmost opposing matching item below it. If there is none, it fizzles.

**Copy (`copy_spell`).** Targets a `spell` item of either side, never a channeled cast or an enemy channel start. It makes a new `spell` item owned by the copier.
- **Sides.** Crossing the table swaps the copy's ally and enemy sides; `any`, `self` and slot refs stay.
- **Carried over.** The copy keeps the original's X and mode, but takes the copier's cast mode.
- **Targets.** A hero copying a single-target spell picks the copy's target as it stacks, or keeps the original aim if no pick is possible. Multi-target copies keep the original targets.
- **Stack-facing copies.** A copied counter or redirect re-aims at the stack, so a copied counter can counter the counter.
- **Enemy copiers** send a single-target copy back at its caster.
- **No chaining.** Copies and echoes never consume `double_next` and never announce as attacks.

**Echo (`double_next`).** The tagged combatant's next matching item resolves twice: an exact copy is pushed and resolves next, after its own window. The echo doesn't carry the original's Mitigate. A channel start is never doubled.

*Sources: GDD §5.4 · §E6-2 · §D12-0 · §D12-2.3 · T-70 · playtest 2026-08-29 · engine `_r_counter`, `_bind_trigger_stack_target`, `_r_copy_spell`, `_stack_copyable`, `_flip_effect_sides`, `_queue_echo`; scenario `_check_ultimate_answer_guardrail`.*

### §5.5 Triggers

**Channel triggers** sit on a hero's channeled card or an enemy channel component (§8.1).

| trigger | fires |
|---|---|
| `channel_start` | once, inline as the channel starts; its targets are picked at cast |
| `upkeep` | every Upkeep while held |
| `after_turns: N` | once, at the Upkeep N rounds after the channel began (a visible countdown) |
| `capacity_increase` | whenever a hero's mana capacity rises (the +1 lock, ramp); heroes only |
| `channel_break` | once, when the channel ends for any reason (§8.1) |
| `{event, who, spell_type?}` | whenever the watched event happens |

| event | fires when |
|---|---|
| `attack` | an attack or Combat Ability goes on the stack (hero, token or enemy) |
| `damage_taken` | damage connects: temp HP soaked plus HP lost is more than 0 |
| `life_gain` | a heal restores HP or closes a wound |
| `spell_cast` | a hero casts a card, or an enemy's spell-classed rule goes on the stack (since 2026-09-25, M1.31); `spell_type` narrows it to instant, sorcery or channeled (an enemy spell has none, so it matches only an untyped trigger) |
| `card_draw` | a hero draws a card (once per card) |
| `death` | an enemy dies (not exile), a token is destroyed or crumbles, or a hero is incapacitated |

`who` is relative to the holder:
- `you`: the holder.
- `target`: the channel's chosen target.
- `ally`: the holder's side, including the holder.
- `other_ally`: the holder's side, excluding the holder.
- `enemy`: the opposing side.
- `any`: anyone.

A just-downed hero still hears their own fall before their channels break (a death rattle). Trigger chains stop at depth 8.

**On the stack.**
- A hero's channel pushes one `triggered` item per channel per firing.
- An enemy channel stacks its upkeep, countdown and break triggers the same way, but resolves **event** triggers at once, off the stack.

**Upkeep order.**
1. Capacity triggers resolve as capacity rises.
2. Draws push card-draw triggers.
3. Poison and regen tick; nothing is stacked for them.
4. Upkeep and countdown triggers are pushed, party holders first, then enemies.

The stack then resolves last-in-first-out.

**Trigger keys** (`trigger_key`: lifecycle name, `after_turns`, or `<event>:<who>`) can map to their own panel clip (`Card.trigger_animations`).

**Enemy reactive components** (§9) fire only when the enemy side is offered a reaction (§5.3). *Pre* means before the top item resolves; *post* means after a resolution.

| trigger | fires when |
|---|---|
| `on_spell_cast` (pre) | a party `spell` item is on top |
| `on_attack` (pre) | a party attack (hero or token) or party Combat Ability is on top |
| `on_targeted` (pre) | this enemy is the primary target of the party item on top |
| `on_incoming_lethal` (pre) | the top item's fixed damage at this enemy ≥ its effective HP |
| `on_ultimate_cast` (pre) | a hero's Ultimate is on top (T-70 governs counters) |
| `on_hit` / `on_ally_hit` (post) | this / another enemy took damage |
| `on_ally_death` (post) | another enemy died |
| `on_self_below_N` / `on_ally_below_N` (post) | this / another enemy was hit and is now below N% of max HP |
| `on_hero_downed` (post) | a hero was incapacitated |
| `on_hero_healed` (post) | a hero regained HP or closed a wound |
| `on_enrage` (post) | its boss has enraged (once per encounter; a timed Enrage fires at Upkeep) |
| `on_charge_full` | the instant charge reaches `charge_threshold`; the charge resets |

A reaction stacks as `triggered`, or as `spell` if spell-classed. It spends its cooldown and aims by `target_rule`; `trigger_source` means whoever sourced the triggering item.

**Damage lanes.** Attack, activated, ability and fight damage, and a triggered Combat Ability's, is **combat** damage. Spell and other triggered damage is **spell** damage. `prevent`, `protection` and `amplify` name a lane. `combat_kind` narrows combat damage by reach: a swing's own mode, an ability's owner's mode, and always melee for a fight.

*Sources: GDD §8 · §F-3.2 · §E6-2, §E6-4 · §D8-2.4 · §D12-2.2 · §D22-4 · §D23-5 · Update 16 amendment 2026-09 · schema `EventTrigger`, `TRIGGER_WHO`, `trigger_key`; engine `_fire_event`, `_fire_channel_effects`, `_trigger_matches`, `_check_charge_full`, `_prevent_match`.*

---

## §6 Targeting

Targeting is mechanical: it decides who may be named, what hexproof stops, and what fizzles.

**Classes.**
- A **creature** target is a descriptor with `mode`, `side`, `exclude_self`, `targeted`, `state`, `rows` and `scope`.
- An **action** target, `{"class": "action", side}`, names a stack item. Only `counter` (enemy side), `copy_spell` and `redirect` (either side) take one.
- A **corpse** target is a creature descriptor with `state: "corpse"` or `"any"`.

| mode | meaning |
|---|---|
| `self` | the source; no side; never targeted |
| `chosen` | one creature picked at cast; each effect is its own pick unless it shares a slot |
| `all` | every creature on the side, read at resolution; never targeted |

**Sides are fixed to the table**, not to the caster: `ally` is the party side (heroes, party tokens, controlled units), `enemy` is the enemy side, and `any` is both. Enemy components use the same frame, so their hostile verbs aim at `ally`. A copy that crosses the table swaps sides (§5.4). `all ally` reaches downed heroes only with a restorative verb: heal, revive, pump, counters, grant_keyword, prevent, protection, amplify or double_next.

**`targeted`** is valid only on `chosen`, and the Deckbuilder turns it on by default. For authors, "target …" is targeted and "choose a …" is not. A targeted pick can't name a hostile hexproof creature, and is re-checked at resolution (§5.3). An untargeted pick ignores hexproof and fizzles only if its creature no longer exists or has left the field (bounced to hand, or suspended by a channel; ruled 2026-09-25, M1.31). Card text doesn't show the difference.

**Hexproof** stops hostile targeted spells and abilities: a party effect on an enemy, or an enemy effect on a hero or party token. Friendly targeting is fine. Basic attacks ignore it both ways, so a hexproof hero can still taunt. It is checked at the pick, when an enemy aims, at intent re-validation (§5.2), and at resolution. Untargeted picks, `all`, splash and ground ignore it. Shroud doesn't exist.

**Pick rules.**
- Removal (destroy, exile, bounce) never offers a boss outside its execute window (§9.5).
- `control` never offers a boss or a boss corpse.
- `revive` offers only downed heroes.
- A guarded race target can't be picked while its guards stand (§12.2).
- `exclude_self` ("another") offers neither the caster nor a creature another pick on the card names. On `all ally` it drops the caster.

**Shared targets.** A card may declare `chosen` slots in `targets`, referenced as `"$T1"`.
- A slot is picked once, applies to every effect that references it, and is re-checked like an inline target.
- Every other top-level inline `chosen` descriptor is its own pick. A multi-pick card is offered once per legal combination, and can't be cast if any pick has no option.
- Conditional branches reuse the primary target.
- Triggered effects pick when they fire (§5.5), unless their slot is shared with an untriggered effect. `channel_start` effects pick at cast.
- A lint warns about two or more inline targeted picks on one card.

**Row shapes (§D9-3.2).**
- **`rows` on `mode: all`** takes everything of that side in the named rows, read at resolution. It is untargeted.
- **`scope` on a chosen pick** also hits every other same-side creature in the pick's row (`row`), or in that row plus the adjacent rows (`blast`). Rows adjoin front↔mid↔rear; front and rear are not adjacent. Only the pick is targeted. If it is illegal at resolution, the whole effect fizzles.
- **Per-use splash:** `"$T1+row"` / `"$T1+blast"` splash that use only.
- **Ground survives its anchor.** Picks' rows are pinned as resolution begins, so a scoped effect whose anchor fell to an earlier effect of the same card still lands there. A pick killed in response still fizzles.
- **Channels** pin their splash victims for life.
- **Enemy row and blast components** become row-aimed intents (§5.2).

**Corpses (§D9-1.3).** `state` is living (the default), corpse or any.
- Only `control`, `exile` and `consume_corpse` may aim at a body. A scoped `deal_damage` may also anchor its blast on one; the corpse takes nothing.
- `control` and `exile` offer corpses beside the living. `state: corpse` means corpses only.
- `consume_corpse` offers only corpses. If there are none, a card needing one can't be cast, and an enemy won't declare the rule. With `mode: all` it takes every corpse.
- Corpses are never hexproof. A targeted corpse effect fizzles if the body is consumed or exiled in response.
- An enemy action binds its corpse separately from its living target.

**Shapes.** The schema accepts descriptors only, never alias strings.

| phrase | descriptor |
|---|---|
| you | `{mode: self}` |
| target enemy | `{mode: chosen, side: enemy, targeted: true}` |
| an ally / another ally | `{mode: chosen, side: ally}` (+ `exclude_self: true`) |
| all enemies in the front row | `{mode: all, side: enemy, rows: [front]}` |
| an enemy corpse | `{mode: chosen, side: enemy, state: corpse}` |

*Sources: GDD §6 · §E6-7 · §D9-1.3, §D9-3.2 · §D18-4 · §D19-6, §D19-8 – §D19-10 · §D23-7.2 · schema `TargetDescriptor`, `ActionTarget`, `Card._check_targets`; engine `_resolve_effect`, `_creatures_on_side`, `_pick_options`, `_target_sites`, `_splash_targets`, `_ground_victims`.*

---

## §7 Keywords & terms

Keywords are static abilities, stored as `{keyword: duration}`. They come from a hero's build, gear, an enemy statblock, `create_token` or `grant_keyword`. The registry (`KEYWORDS`) holds each keyword's name, gloss and whether it can be granted. Unknown and retired keywords are rejected.

| keyword | LTG meaning | heroes | enemies (min level / cost) |
|---|---|---|---|
| flying | Struck only by ranged attacks, other flyers, or reach. Doesn't count for the melee wall, so it never shields the row behind or interposes. Its own melee ignores the wall, but a reach defender pins it to rows not behind that defender | buy 25 | L2 / 4 (T-30) |
| reach | Its melee may strike flyers within the front-most-row rule. Pins an attacking melee flyer | buy 5 · *Reaching* (weapon, uncommon, L1, 5 pts) | L1 / 1 (T-28) |
| first_strike | In the Enemies step, a hero with its basic attack unused this round may make it as a reaction, which resolves first. Not while stunned or pacified, not as a defender, and not with a stance-changed Attack | buy 15 · *Swift* (weapon or accessory, rare, L3, 15) | never |
| double_strike | The basic attack, including the first-strike swing, lands as two separate hits | grant only | no effect |
| vigilance | Frees the Attack (§4.6) | buy 20 · *Watchful* (accessory, rare, L4, 20) | never |
| defender | Frees the Defend. Can never basic-attack, even with first strike; moves and dashes as normal | grant only | ignored |
| haste | Frees the Move (own turn, empty stack) | buy 15 | never |
| trample | When a basic attack fells its target, the excess spills onto one creature on that side, in the same or an adjacent row: the lowest effective HP that the attack's mode can strike. The spill is combat damage and never spills again | buy 10 · *Trampling* (weapon, rare, L2, 10) | L2 / 2 (T-29) |
| deathtouch | Connecting damage executes the victim: an enemy (a boss only in its execute window), a party token, or a hero (downed) | creation-banned · *Venomed* (weapon, rare, L5, 25) | L3 / 4 (T-32) |
| lifelink | Heals its source by any damage it connects, spells included; temp-HP soak counts | buy 15 · *Thirsting* (weapon, rare, L3, 15) | L3 / 3 (T-31) |
| infect | Each connecting hit gives the victim 1 poison counter | banned · *Blighted* (weapon, mythic, L6, 30) | L3 / 3 (T-51); at most one per encounter |
| hexproof | Can't be picked or hit by a hostile targeted spell or ability. Attacks and untargeted, area or splash effects still land (§6) | banned · *Warded* (accessory, mythic, L6, 40) | L5 / 6 (T-34) |
| indestructible | Damage, life loss and poison can't take HP below 1; destroy and deathtouch fail. Exile and a lethal −X/−X still kill | banned · *Unbroken* (accessory, mythic, L6, 35) | L6 / 6 (T-35) |
| relentless | Its intents never redirect, and `redirect` can't turn them | n/a | enemy-only; not grantable; hand-authored only |
| protection, menace, ward, convoke | Retired; can't be granted. Use the `protection` effect | n/a | n/a |

A hero buys at most one keyword at creation (§10). Hexproof, indestructible, deathtouch and infect can't be bought then; a hero gets them only from boss-drop gear (§13) or `grant_keyword`. Enemy costs come out of the enemy's budget (§9).

**Card-game words for authors.** Cards are written in the effect vocabulary (§11). This table glosses familiar words; it is not a translation step.

| word | LTG meaning |
|---|---|
| target … / choose a … | a `chosen` pick with `targeted: true` / `false` (§6) |
| discard (an enemy's) | `strip_intent`: enemies have no hand, so their telegraphed intent goes |
| discard (a hero's) | `move_card` from hand to graveyard |
| tap | `stun`: the enemy skips its next intent (a hero, its next main phase) |
| destroy · exile | `destroy` (it dies, leaving a corpse) · `exile` (gone for good: no corpse, no death trigger) |
| return to hand | `bounce`: sent to hand for one round (§4.5) |
| enters / leaves the battlefield (enchantment) | a `channel_start` / `channel_break` trigger |
| land, "search for a land" · "add {B}{B}" | `ramp` (mana capacity) · `add_mana` (this round's pool) |
| mana value | a card's Level: generic + coloured pips (X counts 0) |
| mill yourself · tutor | `move_card` from library top to graveyard · from library to hand, then shuffle |
| fog · "the next time … would deal damage" | `prevent` · `protection` |
| can't attack · can't cast | `prevent attack` (Pacifism) · `prevent cast` (Silence) |

*Sources: GDD §7 · §R-1, §R-12 · §X-3 · §F-5 · §P-3 · §D8-2.5 · §L-4, §L-6 · §D19-3 · §D23-2 · T-28–T-35, T-51 · schema `KEYWORDS`, `CREATION_KEYWORD_COST`; items `AFFIXES`; engine `_reachable_targets`, `_trample_cleave`, `_deal_damage`.*

---

## §8 Channeling & stances

### §8.1 Channels

A channeled card (an enchantment) is **concentration** held by its caster, not a permanent on the board.

**Casting.** It is cast at sorcery speed within the Cast verb (§4.6). The card goes to the graveyard at once, and the colours actually paid (X included) are **reserved**. On resolution the caster holds a **channel**; countered first, none exists. A channeled Skill works the same way. The channel holds the card's effects (a top-level modal becomes the picked mode or modes), its X, and its target, which is the cast's primary pick. Reserved mana stays out of every Upkeep refresh while held, and `sap` never takes it.

**What it does.** On a hero's card, every effect must be **continuous** (untriggered, `while_channeled`) or **triggered** (§5.5). An untriggered one-shot does nothing (a lint warns). Neither form is legal on other cards, and no effect is both. Continuous forms:
- `pump`, `counters`, `wound`: auras, re-applied after every End Step.
- `taunt`: a Lure.
- `prevent`: re-applied each End Step. An action shield also cancels matching declared intents.
- `grant_keyword`, `modify_action`: channel tags.
- `exile`: suspends an enemy. It is off the board but not defeated; its channels break and its stack items go. It returns when the channel ends, or stays exiled for good if the encounter ends first.

`sap` and `remove_keyword` have no continuous form and are logged unhandled. A wound aura that takes a creature to effective HP ≤ 0 kills it. Losing an aura's target never breaks the channel.

| end cause | ends |
|---|---|
| one hit ≥ **ceil(max HP ÷ 4)**, measured after prevention, protection and Mitigate but **before** temp-HP soak | all the holder's channels |
| the holder is incapacitated | all |
| `break_channel` | all |
| voluntary drop: free, whenever the holder has priority, even the round it was cast | the named channel, or all |
| `channel_drop`, fired by the channel's own trigger (an enemy channel's event trigger included) | that channel only |

Life loss and poison never break a channel. Damage *reduction* protects a channel; temp-HP *absorption* doesn't.

**Ending, in order.** A break waits until the resolution that caused it finishes. Then, for each channel that ends:
1. Its continuous effects and nested `while_channeled` tags lift. A creature a lifted aura drops to ≤ 0 dies.
2. Its reserved mana returns **straight to the pool**, with no stack item and no window. It can pay for an instant in the same window.
3. Any `channel_break` effects go on the stack as one triggered item, slipped beneath the card's waiting triggers (§5.3). The holder picks the mode and target.

A channel holder is never auto-passed (§5.3).

**Enemy channels** work the same way, without mana (§9.9).
- The component's intent stacks first and can be countered.
- On resolution, its continuous verbs apply and its untriggered one-shots fire once. Its upkeep and countdown triggers then recur, but its event triggers resolve off the stack.
- It ends on a single hit of at least ceil(max HP ÷ 4), on `break_channel`, or when its holder dies, is bounced, suspended or dominated.
- Its break triggers stack as a hero's do.

*Sources: GDD §8 · §R-8, §R-9 · §E6-5, §E6-7 · §D19-7, §D19-11 · §D22-3 · engine `_start_channel`, `_apply_static`, `_deal_damage`, `_process_breaks`, `_end_channels`, `_fire_channel_break`, `_start_enemy_channel`, `_break_enemy_channels`.*

### §8.2 Stances

A **stance** rewires its holder's four main abilities (**Attack, Defend, Mitigate, Move**) while its channel is held. It replaces abilities; it never adds one.

**Schema.** `stance {attack, defend, mitigate, move}`. Each slot is `"unchanged"` (the default), `"removed"`, or a replacement `{name, effects, animation?}`, whose effects are leaves plus one level of conditional. At least one slot must change. A stance goes only on a channeled card or channeled Skill. It is always continuous (it can't take a trigger) and player-only (enemy verbs reject it).

**Semantics.**
- **Read live.** The stance is read from the holder's channels, so breaking or dropping the channel restores the defaults at once. Items already on the stack still resolve.
- **One at a time.** No stance card or stance Skill is offered while a stance is held.
- **Removed means every form.** A removed Attack takes the first-strike swing with it. Move takes the haste move, and Defend takes `defend_as_reaction`. A removed Mitigate guards nobody, the holder included.
- **A replacement keeps its slot's economy.**
  - Attack is a turn verb, once per round, freed by vigilance.
  - Defend and Move are pair verbs, freed by defender or haste.
  - Mitigate is the once-per-round reaction when an enemy item is on top. A counter replacement answers any enemy item its filter matches; any other replacement answers only items Mitigate could answer (§4.8). Its effects replace the reduction.
- **Replacements stack as `activated`,** not as attacks or spells. They don't feed double strike or first strike, and Pacifism doesn't bind them. A damaging replacement is a Combat Ability (§5.1). A replacement may use the stance card's slots and several picks.
- **Not affected:** casting, instants, the Skill and the Ultimate.

*Sources: §D9-2 · §D12-0 (skill-stances) · §M-A.7 · schema `Stance`, `StanceReplacement`; scenario `_check_enemy_verbs`; engine `_active_stance`, `_stance_actions`, `_legal_main`, `_legal_react`, `_do_stance_ability`, `_heroic_actions`.*

---

## §9 Enemies

Enemies are asymmetric. They have no deck, hand or mana, and no evergreen actions: they never Defend, Mitigate or make a voluntary Move, and `modify_action` does nothing to them. An enemy is a stat block plus a **mind**, a set of components merged into one priority list that deterministic code evaluates every round.

### §9.1 The enemy object

**Stat block** (the fields the engine reads):

| field | meaning |
|---|---|
| `id`, `name` | unique in the pool; clones become `<id>_<n>` / "Name n" (§12.1) |
| `hp`, `level` | starting (= max) HP; Level. Both positive integers, both authored |
| `power` | basic-attack damage |
| `attack_mode` | `melee` / `ranged`: reach for the swing **and** for every hero-aimed pick (§9.3) |
| `row`, `home_row` | starting row; `home_row` (defaults to `row`) is where a reserve body deploys and where an Evasive rule retreats |
| `keywords` | a list (permanent) or `{keyword: duration}` |
| `components` | the mind (below) |
| `types`, `classes` | §9.8 |
| `is_boss`, `enrage_round`, `neglect`, `double_intent` | §9.5 |
| `rises` | §9.7 |
| `intent`, `ranged_intent` | legacy: a basic-attack template (name, amount, mode, targeting, optional `target_row`), plus a weaker ranged fallback for a melee-primary enemy |

An enemy without a legacy `intent` gets a synthesised basic attack: "<Name> Attack", dealing its Power in its attack mode, aimed by valuation (§9.3).

**Chassis** are authoring presets with their budget already spent; the engine sees only the resulting stats. Upgrades: +1 HP = 1 pt, +1 Power = 3 pts, a ranged mode = 2 pts; melee is free.

| chassis | HP | Power | attack | home row | cost |
|---|---|---|---|---|---|
| Husk | 2 | 1 | melee | front | 5 |
| Bruiser | 4 | 2 | melee | front | 10 |
| Skirmisher | 2 | 2 | melee + ranged | mid | 10 |
| Artillery | 2 | 2 | ranged | rear | 10 |
| Caster-frame | 2 | 1 | ranged | rear | 7 |

**Components.** Each component is one rule on the merged list:

| field | meaning |
|---|---|
| `archetype` | pricing label (§9.2); the engine reads only `Enrage` |
| `timing` | `proactive` (declares an intent) or `reactive` (fires on a `trigger`); `charge_threshold` for `on_charge_full` |
| `condition` | optional gate (§9.3) |
| `priority` | lower is evaluated first. Default 90. By convention 10–19 is the emergency band and 20–49 tactical |
| `cooldown`, `once_per_encounter` | reuse gate; cooldown 0 or 1 = every turn |
| `verbs` | ordinary effect primitives (§11), same schema as cards |
| `target_rule` | whom it aims at (§9.3); default `valuation` |
| `action_type` | `ability` (default), `spell` (spell counters answer it), or `attack` (a positional swipe that lands as an attack) |
| `channel`, `target_row`, `move_home` | starts a held channel; aims at a row (§9.9); a verbless Move back to `home_row` |
| `phase` | `pre_enrage` / `post_enrage` gate on the encounter's boss (§9.5); a minion's reads its boss |
| `telegraph` | the on-stack name and strip-reveal text. Never shown while declared |

**Budget and Level.** B(L) = 5·L + 5 (L1 10, L2 15, L3 20, L4 25, L5 30, L8 45, L10 55). Total cost = chassis + upgrades + keywords + traits + components after modifiers (§9.2). An enemy's Level is the smallest L whose budget covers its cost. Underspending is legal; overspending is impossible, so complexity prices itself into Level. A boss spends up to 2.5 × B(L). Pricing happens at authoring: the engine takes `level` as written.

Enemy-eligible keywords (min Level / cost): reach 1/1 · trample 2/2 · flying 2/4 · lifelink 3/3 · infect 3/3 · deathtouch 3/4 · hexproof 5/6 · indestructible 6/6. The trait `rises` is 2/3. `relentless` is enemy-only and unpriced.

**Level is fixed and distinct from HP.** Damage, counters and neglect never change it. Level feeds level-gates (`target_property` level: exactly, or more, or less), `destroyed_target.level`, gauge credit for removal and denial, the canonical order, and budgets. The execute window, enrage and `self_hp_pct` read effective HP instead.

**Verb magnitudes** scale with the enemy's **own** Level L, never the party's. The authoring schedule:

| verb | magnitude |
|---|---|
| `deal_damage` (Burst, Punish) | L+2, and never below the enemy's Power |
| Drain (damage + self-heal) | ceil(L/2)+2 each |
| `heal` (Fortify) | L+2 |
| `pump` / `wound` | ±(ceil(L/3)+1) |
| `counters` (Escalate) | +2/+2 per firing |
| `lose_life` | ceil(L/2)+1 |
| `poison` | 1–2 counters |
| whole row / blast or party-wide | L per creature / ceil(L/2)+1 |
| `sap` · `drain_ultimate` | 1 (2 at L5+) · 10–25 |
| `create_token` | a Husk at Level ceil(L/2) |
| charge detonation | up to 2× the schedule |
| stun, taunt, silence, discard, strip | binary |

At build the balance register lifts damage further (§12.1).

*Sources: §F-1–§F-6, §E6-1, §D8-2.5, §D14-1, §D18-2, §D19-3, §L-6.2, T-01–T-08, T-26, T-28–T-36, T-39, T-51, T-55 · scenario `state_from_dict`, `_component_from_dict`, `_default_attack_template`; llm `DEFAULT_INSTRUCTIONS`.*

### §9.2 Intent archetypes & categories

Archetypes are the design vocabulary for what a rule is **for**, and they set its price. What the rule actually does comes from its verbs, timing and trigger.

| archetype | typical verbs | base cost |
|---|---|---|
| Burst | damage above the basic attack | 4 |
| Evasive | repositioning (`move_home`), paired with flying or hexproof | 2 |
| Drain | damage and self-heal, coupled | 5 |
| Swarm | `create_token` | 6 |
| Fortify | heal, pump or regen on self or an ally | 3 |
| Debilitate | wound, stun, taunt, poison, forced move, `break_channel`, hostile modifiers | 4 |
| Punish | telegraphed retaliation on a trigger | 3 |
| Escalate | self counters; charge gathering | 4 |
| Ward | `prevent` / `protection` onto self or an ally | 3 |
| Counter | reactive only: `counter` | 3 (+2 reactive) |
| Resource attack | forced discard, silence; sap | 4; sap 5 |
| Necromancy | `control` on an own-side corpse | 5 |
| Enrage | the boss's eruption (§9.5) | free |

**Modifiers** (multiply, round up, then add): cooldown 1 ×1.5 · cooldown 2–3 ×1.0 · once per encounter ×0.5 · channelled ×1.5 · reactive +2 flat. A charge gather prices as Escalate; its detonation prices at its archetype base +2, with no other modifier.

**The veil.** A declared intent shows only a **category** and its **locked target**. The target can be a hero, a fellow enemy, a row footprint or the whole party. The veil hides the intent's name, verbs, numbers and keywords, and whether it starts a channel. The category is derived from the intent, never authored; the first match wins:

| category | derived from | line |
|---|---|---|
| manoeuvre | a Move | "…shifts its footing." |
| row assault | a positional intent | "…prepares an assault on your front row." |
| gathering | any `charge` verb | "…gathers its power." |
| spellcraft | spell-classed | "…begins casting a spell at Ys." |
| summon | `create_token`; or, with nothing hostile, corpse `control` / `consume_corpse` | "…calls for reinforcements." |
| interference | first hostile verb is lockdown: stun, taunt, `strip_intent`, `remove_keyword`, `counter`, `sap`, `modify_action`, `break_channel`, or `prevent`/`move_card`/a forced `move` aimed at the party | "…moves to foil Soren." |
| row assault | first hostile verb is row- or blast-scoped | as above |
| party assault | first hostile verb is `mode: all` on the party | "…prepares an assault on your whole party." |
| threat | any other first hostile verb | "…threatens Soren." |
| support | verbs, none of them hostile | "…steels itself." |

A mixed intent reads by its first hostile verb, so "deal 5 and stun" is a threat. Each line also carries:
- a status: declared, stripped (with the reveal), stunned, executed or fizzled;
- a slot number (a boss shows two);
- the rows to light, from declaration until the intent resolves;
- a **redirectable** bit: "swing" when a body can step in front of it (§9.3), "pursues" when it cannot.

**What the party sees.** Everything else about an enemy is public: charge gauges, stirring corpses, held channels (by name), objectives and stats. An executed intent shows in full on the stack. Reactions never telegraph, and a strip reveals the intent it stopped.

*Sources: v1 GDD §9.2 · §F-3.1, §E6-1, §D8-1, §D8-2.4, §D9-1.6, §D18-4, §D19-11, §D23-4, T-09–T-19, T-53 · serialize `intent_category`, `_veiled_entry`; snapshot `_intents`.*

### §9.3 The AI

Deterministic code picks every enemy action.

**Timing.**
- **Intents step.** Bounced enemies redeploy and objective arrivals deploy (§12.2). Then every in-play enemy declares in canonical order (row Front→Rear, then Level low→high, then name), followed by ally tokens (§9.6).
- **Enemy step.** Each enemy executes in the same order, each intent as its own stack action with its own reaction window. The exception is a Move, which relocates the body at once, off the stack.

**The proactive pass** runs once per declaration slot:
1. A stunned enemy spends one stun charge and declares nothing. A two-intent boss loses its second slot instead. Stun never blocks reactions.
2. Otherwise the rules are walked in priority order. The first **eligible** rule that finds its target declares, spending its cooldown there and then.
3. If none does, the enemy declares its basic attack (the implicit priority-90 rule).
4. If nothing is in reach, a ranged-primary enemy standing in Front declares **Fall back** (a Move to Mid). Any other enemy declares nothing.

**Eligible** means all of these hold:
- the cooldown is ready;
- the condition holds;
- the boss phase gate is open;
- the rule's channel is not already held;
- it is not spell-classed while the enemy is silenced, nor attack-classed while it is pacified;
- it is not a Swarm at its token cap (§9.6);
- if it carries a corpse verb, a usable corpse is on the field (§9.7).

Moves and positional rules need no target. Any other rule whose non-`self` target rule finds nobody is skipped, even if its verbs need no pick.

**Conditions** take the form `{"kind", "op", "value"}`. The ops are `< <= > >= == !=`, and the default is `>=`. An unknown kind is rejected when content loads.

| kind | reads |
|---|---|
| `self_hp_pct` / `self_hp` | this enemy's effective HP, as % of max or raw |
| `turn` | the fight's turn number |
| `turn_mod` | turn modulo `mod` (default 2); default op `==`. A rhythm: "every 3rd turn" |
| `ally_count` / `hero_count` | other in-play enemies / standing heroes |
| `hero_in_row` | standing heroes in `row` (default front) |
| `hero_hp_pct` | the lowest standing hero's HP % (100 if none) |
| `hero_channeling` / `self_channeling` | heroes holding a channel / this enemy's held channels |
| `hero_gauge_pct` | the highest Ultimate gauge % among heroes with an unspent Ultimate |
| `hero_primed` | heroes holding a live `amplify` or `double_next` tag |
| `corpse_count` | corpses on the field |

**Target rules.** A hero-aimed pick draws from the **pickable** heroes and party tokens: those the enemy could strike with its own attack mode (§R-1 reach; tokens since 2026-09-25, M1.27d). Two consequences follow:
- A melee body's spells reach only the front-most occupied grounded row.
- A ranged body standing in Front reaches nobody with its attacks and abilities. Its **spells** are not attacks (§D23-3), so they reach as a ranged body's would.
- A rule whose verbs are all untargeted (`mode: all`, `self`) needs no pick: it declares even when nobody is pickable.

Two filters then remove heroes from that pool:
- **Hexproof** heroes, whenever any verb in the rule is targeted.
- **Locked or claimed** heroes, for control verbs. A hero is dropped if they already carry that control (stun, taunt, a persistent hostile modifier, or a drain on an empty gauge), or if an intent already declared this round has **claimed** them for it. This spreads a horde's locks across the party.

| rule | picks | if nobody |
|---|---|---|
| `valuation` (default) | the ranking below | skip |
| `highest_threat` | highest current Power (ties: role, HP, row, name) | skip |
| `primed_hero` | highest primed score | valuation |
| `channeling_player` | the lowest-HP pickable hero holding a channel | skip |
| `hero_class:<c>` / `hero_type:<t>` | a **grudge**: the lowest-HP pickable hero wearing the tag | valuation |
| `trigger_source` | reactive only: whoever caused the trigger | — |
| `self` | the enemy | — |
| `lowest_hp_ally` | the lowest-HP fellow enemy; a pure-heal rule skips allies at full HP | skip |
| `wounded_ally` | the most-hurt wounded fellow enemy | skip |
| `corpse` | the nearest usable corpse (§9.7) | skip |
| a fixed id | that combatant; a hero only if pickable | skip |

**Valuation** ranks candidates against a hit of known constant damage D, which is the rule's total `deal_damage` or the swing's amount:
1. **Finishable**: effective HP ≤ D; take the highest such HP.
2. **Channel-breakable**: holding a channel, and D ≥ ceil(max HP / 4).
3. **Primed**: score 2 for a live amplify or double_next tag, plus 1 for a gauge ≥ 80% with an unspent Ultimate.
4. **Role**: channelers, then ranged, then melee; then lowest effective HP.

Ties break by row (Front→Rear), then name. Ranks 1–2 apply only when D > 0.

**The basic attack.** A component-built enemy's swing targets by valuation over the heroes and party tokens (controlled units included) it can reach. Hexproof never shelters anyone from a basic attack. A taunted enemy swings at its taunter when it can reach them (a melee body is stopped by the wall, §4.1); otherwise it picks among the reachable as usual. Legacy templates may name `lowest_hp_party` (the lowest HP in reach, which enemy tokens and raised undead also use), `lowest_hp`, or a fixed hero. The swing carries its base Power, so a later wound or anthem changes what lands.

**The sword competes with the kit.**
- **Outclass.** A rule made only of single-target `deal_damage` at a hero, totalling no more than this turn's swing, is skipped. A rule with a rider, a row or blast shape, or a self or ally aim is never skipped.
- **Cadence** (ATTACK_CADENCE = 2). After two consecutive slots that were not the basic attack, only emergency-band rules (priority 10–19) may precede the swing; if none is eligible, the enemy swings. The cadence only forces a swing when one is available. It never applies to a boss's second slot. A spoiled intent's substitute swing resets it.

**Cooldowns and ties.** A fired rule is usable again `cooldown` whole turns later (minimum 1). A `once_per_encounter` rule never returns. The cost is paid at **declaration**, for every slot of every enemy, and also when a reaction or detonation fires. So a strip buys one round, not a lock. Rules at equal priority are ordered by a key seeded from the fight's `rng_seed`, the enemy id, the turn and the component id: replays are identical, while different fights and different turns differ. Reactive rules break ties by authoring order.

**Between declaration and execution.** Targets lock at declaration. Three things can still happen to an intent:
- **Re-check (interposition).** After every occupancy change, a **redirectable** intent whose target has left reach redirects to the best target in the front-most reachable row, with a reachable taunter first. With no legal interposer it fizzles. Redirectable intents are melee basic attacks and melee single-target Combat Abilities from a ground, non-relentless attacker, aimed at a hero.
- **Re-validation.** As an intent enters the stack, it **spoils** if:
  - its bound corpse is gone;
  - its targeted payload lost its aim;
  - its target left play or became a corpse its verbs cannot use;
  - its target gained Hexproof against a targeted hostile spell or ability (attacks are exempt).

  A spoiled intent fizzles and the enemy swings instead, as a real stack action. It is never re-aimed.
- **Disruption.** `strip_intent` clears a declared intent and reveals it. A strip that lands before anything is declared lingers and smothers the next declaration. A `prevent attack` or `prevent cast` on an enemy, channel-held or one-shot, cancels its matching declared intents (a one-shot shield is spent doing so; M1.25).

**The reactive pass.** Enemies answer only after every hero has passed. Each time a window closes, every in-play enemy that has not yet reacted in this window offers its top matching eligible rule. The lowest priority number fires; ties go by canonical order. It stacks as a triggered ability (or as a spell, if spell-classed) and reopens the party's window. An enemy reacts at most once per window. After a resolution, the whole enemy side answers with **one** post-resolution reaction, the best-ranked: an area hit on three `on_hit` enemies draws one punish (kept as-is, ruled 2026-09-25, M1.31).

**The pile-on rule.** A trigger episode (one stack item, before or after it resolves) is answered at most once per reaction signature: trigger, class, verb kinds and aims. Identical reactions on other bodies stay armed. `counter`, `copy_spell` and `redirect` reactions aim at the stack item that tripped them.

| trigger | window | fires when |
|---|---|---|
| `on_spell_cast` / `on_attack` | pre | a party spell / a party attack or Combat Ability is on top of the stack |
| `on_targeted` | pre | the party action on top targets this enemy |
| `on_incoming_lethal` | pre | the item on top would deal this enemy lethal constant damage |
| `on_ultimate_cast` | pre | a hero's Ultimate is on top |
| `on_hit` | post | this enemy took damage |
| `on_ally_hit` / `on_ally_death` | post | another enemy was hit / died |
| `on_ally_below_N` / `on_self_below_N` | post | another enemy / this enemy was hit and now sits below N% |
| `on_hero_downed` / `on_hero_healed` | post | a hero was incapacitated / regained HP or closed a wound |
| `on_enrage` | post | its boss has enraged (§9.5) |
| `on_charge_full` | immediate | charge reaches `charge_threshold` (§9.9) |

*Sources: v1 GDD §9.3 · §F-3, §F-7, §E6-1, §E6-3, §D12-2, §D18-3, §D19-4, §D23-3, §D23-4, §D23-6, §D23-7, §L-3, T-69 · engine `_declare_enemy_intent`, `_pick_enemy_intent`, `_condition_met`, `_component_target`, `_pickable`, `_rank_valuation`, `_recheck_intents`, `_intent_spoiled`, `_offer_reactions`.*

### §9.4 Minions & bosses

A **minion** is any enemy that is not a boss, and every removal works on it at any time. A **boss** (`is_boss`) is removal-immune until its execute window opens: ≤25% of max HP, measured by effective HP (§9.5). The triage: **what removes it from the board is blocked; what affects it in place works.**

| against a boss above its window | result |
|---|---|
| destroy, exile, bounce, channelled exile (suspension), deathtouch execution, a level-gated destroy | blocked. The boss is not even offered as a target. If it heals out of the window while the removal waits on the stack, it shrugs the removal off |
| `control` (mind control or raise) | never legal on a boss: alive, windowed, or dead |
| damage, attacks, counters, strip, stun, taunt, wound, poison, forced movement, `break_channel`, keyword removal | all work |

Inside the window, every removal works except `control`. An encounter holds at most one boss. A Phase I or II boss is a mini-boss (§12.3) and follows the same rules.

*Sources: v1 GDD §7, §9.4 · §F-9, §E-E, §D9-1.4, §D9-3.1, §D10-4.3 · engine `_boss_shrugs_removal`, `_removal_legal`, `EnemyState.in_execute_window`, `_r_control`; content `_validate_encounter`.*

### §9.5 Bosses

**The threshold.** A boss has one line at ≤25% of max HP, measured on effective HP. The line is both its enrage line and its execute window. The first time the boss is alive and at or below the line, three things happen:
- **It enrages** (one-way). Stun charges and taunt drop off. Every cooldown resets except spent once-per-encounter rules. `pre_enrage` rules retire and `post_enrage` rules wake, the boss's and its minions' alike (a minion's gate reads its encounter's boss). A wound that drops a boss to 25% enrages it at once (ruled 2026-09-25, roadmap M1.26).
- **Its Enrage component fires** as a reaction in the next post-resolution window, normally right after the blow that bloodied it. The party can answer it on the stack, and mitigating or dodging it is fair play.
- **Removal starts working** (§9.4).

A boss killed in one blow from above the line never enrages.

**The Enrage component.** A component with `archetype: Enrage` or `trigger: on_enrage` is forced at load to be reactive, on `on_enrage`, and once per encounter. It costs no budget. It is authored for a solo hero as a multi-verb eruption, such as counters, an AoE, a token wave, a heal or a keyword. At build, instead of the register bump (§12.1), it scales to party size n:
- Power half of `counters` / `pump`: × n.
- Toughness half, `deal_damage`, `lose_life` and `heal`: × (1 + (n−1)/2).
- `create_token` count: + (n−1).

All results round up, and the telegraph is rewritten to match. For example, "+2/+2 and burn 3" becomes "+8/+5 and 8" against four heroes.

**Two intents.** A boss runs the proactive pass twice per round:
- from turn 1, if it carries `double_intent` (set at build on Standard and Hard, from the run's difficulty or, for a standalone encounter, the one it was made at; Easy bosses start on one);
- always, once enraged.

The second pass never forces the cadence swing. Slot 1's spent cooldown stops the same rule firing twice, and the basic attack backstops slot 2. Both slots execute in order during the boss's turn, each as its own stack action. A stun suppresses one slot. A chosen strip removes the slot the player picks, and a side-wide strip removes both. The intents window and the inspect panel show both lines.


**Pressure dials** (required on generated bosses):
- **Timed enrage**, `enrage_round: R` (generated 3–5). If the boss has not enraged by the Upkeep of its own round R, it enrages there: the same hard reset, with its Enrage component on the stack in the same beat. This does not open the execute window, which stays HP-based.
- **Neglect**, `neglect: N` (generated 1–2), **bosses only**. At each End Step from the body's own round 2 onward, a boss that lost no HP to the **party** that round permanently gains +N Power, +N max HP and +N HP, as counters. Any party-caused HP drop counts as a hit: damage (even a blow soaked by temp HP), a poison tick, life loss, or a wound that eats toughness. An enemy's own blow, or its side's, does not (ruled 2026-09-25, roadmap M1.26).
- **Counted from arrival.** Both dials count from the turn the body arrived. A reserve body deployed on turn 6 treats turn 6 as its round 1.

**Placement.** A boss counts double toward a layout's Level total. It appears in every layout, except under `waves`, where it appears only in the final wave (§12.2).

**The Ultimate answer (T-70).** Any enemy may punish an Ultimate on `on_ultimate_cast`: damage, wound, or stun the caster. A `counter` on that trigger is more restricted:
- boss-only;
- once per encounter;
- filter `action`, `ability` or `activated` only, because an Ultimate stacks as an activated ability.

Load rejects anything else. The party can answer the counter.

*Sources: v1 GDD §9.5 · §F-9, §E6-4, §D9-4, §D12-2.3, §D18-2, §D19-2, §D23-5, T-39, T-54, T-70 · engine `_after_damage`, `_enrage_boss`, `_begin_turn`, `_end_step`, `_own_turn`; scenario `_check_ultimate_answer_guardrail`; content `enrage_scale`, `apply_boss_difficulty`.*

### §9.6 Tokens & autonomous allies

A created token is an **autonomous ally** with its own intent. The party can help it but never command or spend it; no verb sacrifices, convokes or directs a token. Tokens **die** at 0 effective HP: the token is removed and a death event fires, but it leaves no corpse. Heroes, by contrast, are only incapacitated.

- **Creation.** A party `create_token` uses the verb's Power, HP and keywords. Anything the verb leaves unset comes from the encounter's `tokens` definition, which also sets the row (default Front), attack mode (default melee) and Level.
- **Behaviour.** A token declares a basic attack for its Power at the lowest-HP enemy in reach. It executes in the Allies step, after the heroes and before the enemies. If its target is gone it re-picks, so a token made earlier in the round still acts that round. Its melee intents re-check on occupancy changes (§9.3).
- **Help, not command.** Heals, pumps, anthems and keyword grants reach tokens; bounce or exile removes one. Tokens charge no Ultimate gauge.
- **Out of the enemy's sights.** Enemies never pick an ordinary ally token as a single target or a swing target, and tokens do not form the melee wall. Tokens are hit only by party-side area, row and splash effects, and by reactions aimed at `trigger_source`. Controlled units (§9.7) are full bodies for enemy swings.

**Enemy-side tokens.** An enemy's `create_token` spawns full enemies:
- stats come from the verb or the token definition (Level 1 by default);
- a basic Strike at the lowest-HP body in reach, and no components;
- at most **2** alive per creator (T-27). Surplus spawns are lost (logged), and a Swarm rule at the cap is skipped. A boss's **Enrage** and a race **escalation** are exempt, so the party-size Enrage wave (§9.5) spawns whole (ruled 2026-09-25, roadmap M1.22);
- they first act the round after they arrive;
- they must be defeated to win, and they leave no corpse.

*Sources: v1 GDD §3, §9.6 · §R-5, §F-4, §D8-3.3, §D9-1.1, T-26, T-27 · engine `_create_enemy_tokens`, `_declare_ally_intent`, `_execute_ally`, `_choose_enemy_attack`, `_pickable`.*

### §9.7 Corpses & necromancy

**The corpse rule.** A non-token enemy that dies leaves a **corpse** on the row where it fell. This covers death by damage, poison, a wound, `destroy`, or a boss executed in its window.

A corpse is an object, not a creature. It keeps the body's name, Level, Power, max HP, attack mode and tags. It has no HP, intents or keywords, never acts, and cannot be shoved. It counts as a defeated enemy.

Tokens never leave corpses, so a raised body cannot rise again. That includes a dominated enemy that dies while under control. Heroes never die. A boss's corpse can never be raised.

| verb | on a living enemy | on the body |
|---|---|---|
| `destroy`, lethal damage or poison | dies; death triggers fire | leaves a corpse |
| `exile` | removed; no death triggers | no corpse, ever |
| `exile` a corpse | — | burns it; a stirring body is defeated on the spot |
| `consume_corpse` | — | spends it as fuel. No death trigger; a stirring body will not rise |
| `control` a corpse | — | raises it (below) |

**Corpse targeting.** Only `control`, `exile` and `consume_corpse` may aim at a corpse (`state: corpse`). There is one exception: a splash-scoped `deal_damage` may use a corpse as its blast point. Corpses are never Hexproof. A targeted corpse effect fizzles if the body is gone. `target_property is_dead` tests for a corpse. A whole-side `consume_corpse` means that side's corpses.

**Fuel is a cost.** `consume_corpse` always resolves last, wherever it is written, so the blast lands before the body is spent. An enemy rule with any corpse verb is not declared while no usable corpse is on the field. The rule binds its body at declaration (`corpse_id`), separately from its payload's target. If the party burns that body in response, the intent spoils (§9.3).

**Rises.** `rises: N` (2 by convention) makes the corpse **stir**. While it stirs, the enemy is not defeated. After N Upkeeps it revives on its row at half max HP (floor, min 1), with temporary effects, statuses and afflictions stripped, and declares that round. It rises once per encounter; killed again, it stays down. Exiling, consuming or raising the stirring corpse cancels the rise.

**Necromancy.** An enemy's `control` and `exile` are legal only on corpses. With `target_rule: corpse`, it takes the nearest usable corpse, never a boss's and never a stirring one. Nearest means the closest row to the necromancer, then front-most, then lowest Level, then name. The body rises on the enemy side as a **permanent** undead **enemy token** (kept as-is, ruled 2026-09-25, M1.26):
- half the corpse's max HP (floor, min 1);
- its Power, attack mode and Level;
- types `["undead", <what it was>]`;
- a swing at the lowest-HP body in reach.

**Party control** lasts `turns: X` or `encounter`. `turns: X` ends at the X-th End Step, where the End Step of the round it resolved in counts as the first.
- **On a corpse** it raises an ally undead token, which crumbles when the control ends.
- **On a living non-boss enemy** it is mind control. The enemy joins the party as a token. It keeps its HP, max HP, Power, keywords, tags and afflictions, and loses its components and intents. It swings at the closest enemy it can reach (nearest row, then lowest HP), or advances to Front if none is in reach. When control ends, it returns to the enemy side with its current HP, on its current row.

**Control never wins.** A controlled enemy is not defeated. If only controlled enemies remain, all mind control ends and the fight continues.

**Client events.** `enemy_died` plays the grand send-off for a boss or the last enemy. `corpse_stirring` pulses the corpse marker. The client also receives `corpse`, `risen`, `raised`, `corpse_consumed`, `rise_cancelled`, `crumbled`, `controlled`, `control_ended` and `control_snap`.

*Sources: §D9-1, §D19-1, §D19-6, §D19-10, §D21-3, §D23-7.3, T-52, T-56 · engine `_kill_enemy`, `_r_consume_corpse`, `_corpse_for`, `_tick_stirring`, `_raise_corpse`, `_mind_control`, `_check_end`; scenario `_check_enemy_verbs`.*

### §9.8 Types, classes & factions

Every creature carries a **type line**: up to 2 **types**, for what it IS, and up to 2 **classes**, for what it DOES. Both come from closed registries shared by cards, enemies, heroes and the Deckbuilder.

| | registry |
|---|---|
| **types** | human, elf, dwarf, halfling, goblin, orc, giant, troll, merfolk, fae, undead, spirit, demon, dragon, beast, bird, serpent, vermin, insect, spider, plant, fungus, elemental, construct, ooze, horror |
| **classes** | warrior, knight, soldier, brute, berserker, archer, hunter, scout, rogue, assassin, monk, wizard, shaman, necromancer, druid, cleric, cultist, ritualist, healer, warlord, artificer, noble, bard |

- **Required on every generated enemy:** 1–2 of each. The gate rejects missing, unknown or excess tags. The engine is permissive: legacy enemies load untagged, and the loader slugs, dedupes and caps tags, reading `supertypes` as `classes`.
- **Heroes** pick the same line on the character sheet, at no cost.
- **Rules read tags** through `target_property` `type`/`class` conditions on cards ("deal 5 to an undead") and through enemy **grudges** (`hero_class:<x>` / `hero_type:<x>`, §9.3).
- **Tags persist.** Corpses and dominated enemies keep their tags. A raised corpse rises as undead plus its first other type.
- **Presentation.** The art prompt and the inspect subtitle both show the line.

**Factions** are a generation convention, not data. An encounter's pool shares one theme and palette, and an adventure keeps one faction across its three phases. There is no faction field or manifest in code.

*Sources: §D21, §F-8, §D10-1, §D23-6 · schema `CREATURE_TYPES`, `CREATURE_CLASSES`; scenario `_clean_tags`; engine `_target_property_holds`, `_clean_tags_rise`; llm `_type_problems`.*

### §9.9 Pressure tools

**Combat Abilities.** Any ability-class action whose verbs deal damage is derived as a **Combat Ability**; it is never authored. This covers an enemy ability or reaction, a hero's activated ability, and damage nested inside a modal or conditional. A Combat Ability:
- lands in the combat-damage lane, even as an enemy's triggered punish;
- trips on-attack triggers as it hits the stack;
- can be answered by Mitigate when aimed at one named victim;
- can be interposed when melee (§9.3).

Row, blast and `mode: all` payloads stay unmitigable. Spell-classed and channel-starting actions are never Combat Abilities.

Under a declared Mitigate, damage resolves first and riders follow it:
- If the blow is absorbed whole, no rider lands.
- If a guard took the residual for an ally, the guard takes the rider.

**Taunt has teeth.** An enemy verb list with `taunt` and no damage gains a `deal_damage` equal to the enemy's Power **at execution**, aimed at the taunted hero. The taunt binds that hero's basic attacks to the taunter through the hero's next turn, as long as the taunter lives and can be reached.

**When lockdown lands.** Enemies act after the party, so an enemy's turn-scoped lockdown on a hero **holds through that hero's next turn** (ruled 2026-09-25, roadmap M1.25): a one-shot Silence or Pacify (`prevent cast` / `prevent attack`), a `this_turn` wound, sap or hostile action modifier, and a taunt. Each survives the End Step and the Upkeep, and lapses as the hero ends a turn in a later round than the one it landed in (a `lockdown_lapses` log line). Stun already works this way. `encounter` durations, instant discard and gauge drain, and channel-held auras last as before.

A hero's one-shot Pacify or Silence on an **enemy** also cuts short the intent that enemy already declared, if the shield forbids it; a one-shot shield is spent doing so.

**Resource attacks and lockdown.**
- **Forced discard:** `move_card` hand → graveyard, aimed at a hero, who picks the card. Enemy-legal only against a hero.
- **Silence** (`prevent cast`): the hero casts no cards, but keeps the basic attack, Skill, Ultimate and consumables. A silenced enemy loses its spell-classed rules. A pacified enemy (`prevent attack`) loses its attack-classed rules and its swing.
- **Sap:** −N mana capacity, authored to last the encounter. It bites the unspent pool at once, but never reserved mana, and it cannot affect an enemy.
- **Hostile action modifiers:** `lock_skill` (Hamstring), `drain_ultimate` and `make_melee` (strip reach) are the only `modify_action` forms an enemy uses.
- **Lockdown budget** (per layout, taught at generation): stun, taunt, silence, Hamstring, discard, sap, drain-ult and strip-reach pieces all count. Standard allows 0/1/2/3 pieces at party sizes 1–4; Easy one fewer (minimum 0), Hard one more. At most one resource attack per encounter. All of these read as **interference**.

**Forced movement.** `move` relocates a living creature immediately. `forward` and `back` are side-relative; `to_front`, `to_mid` and `to_rear` are absolute. A shove triggers the re-check (§9.3), so it can bend a melee intent by interposition, but it never cancels one. It works on bosses. Hexproof blocks a targeted shove, and corpses cannot be moved. Generation allows at most one forced-mover per encounter on Standard, two on Hard.

**Positional intents and row shapes.** A `target_row` rule aims at ground. It picks no target, ignores taunt, and declares even into an empty row. Its hero-side verbs are scoped to that row; self-riders stay on the enemy.

A §D9-3.2 row or blast shape on an ordinary rule is converted at declaration. Valuation, blind to Hexproof, picks the ground from the heroes in reach, and the verbs are scoped to that footprint: a row for a row shape, or a row and its neighbours for a blast. Front and Rear are not adjacent. Channel rules keep their own pick, and so do rules with any verb that is neither hero-side nor self-aimed.

Occupancy is read at resolution, so vacating the lit rows dodges the hit. Mitigate answers an `attack`-classed swipe; other row payloads are unmitigable. Row shapes take +2 from the register (§12.1).

**Enemy channels.** A `channel: true` rule enters through the stack, so it can be countered before it exists. Once it resolves, the rule sleeps while its channel holds, and the channel's verbs behave by kind:
- `while_channeled` verbs act as auras;
- one-shot verbs fire once;
- `trigger: upkeep` verbs recur each Upkeep, after party channels;
- `after_turns` verbs fire once, on schedule.

Any of these breaks all of the enemy's channels at once:
- a single hit ≥ ceil(max HP / 4);
- the channeler's death, bounce, suspension or domination;
- `break_channel`.

`channel_drop` ends only its own channel. Each channel that ends fires its `channel_break` verbs as a respondable stack item.

**Counterspells.** A reactive `counter` answers the stack item that tripped it, identified by `#uid`. So does `copy_spell`, which mirrors a spell back at its caster, and `redirect`, which turns an action back on its source. None can answer its own side, and the party can answer them in turn. Generation allows at most one counter-piece per encounter, on a 2–3 cooldown.

**The windup.** A self-`charge` rule reads as "gathering" and fills a public gauge. When the charge reaches a reactive `on_charge_full` rule's `charge_threshold`, that hidden rule goes on the stack immediately, mid-step, and spends its cooldown. Charge resets to 0 as the rule is pushed, so countering it still spends the charge. The threshold must take at least 2 gathers, and a gather is gated on having a detonation. Heroes can drain charge with `op: remove`, and `amount: all` defuses it completely. `caster_charge` and `target_charge` read the gauge.

**Relentless** (enemy-only): intents never redirect, whether by interposition or by `redirect`.

**Never on enemies.**
- **Keywords:** `first_strike`, `vigilance`, `haste`, and `defender` (ignored).
- **Verbs rejected at load:** `stance`, and `control` or `exile` except on corpses.
- **Verbs excluded at generation:** `destroy`, `bounce`, `strip_intent`, `revive`, `draw`, `scry`, `ramp`, `add_mana`.
- **At most one per encounter (taught):** a necromancer, a gatherer, a poisoner, an infect biter, a gauge-punisher, a counter-piece.

*Sources: §M-A.7, §F-3.3, §E6-2, §E6-5, §D8-2.4, §D9-3, §D18-1, §D18-4, §D19-11, §D22-1, §D22-3, §D23-3, §D23-4, §L-5, §L-6.2, T-47, T-55 · engine `_is_combat_ability`, `_mitigated_rider`, `_taunt_with_teeth`, `_r_prevent_only`, `_row_shape_footprint`, `_break_enemy_channels`, `_check_charge_full`; llm `_lockdown_budget`.*

---

## §10 Characters

A hero is a **loadout**: `{ltg_version, character, cards, gear?}`. `character` is the sheet plus the non-mechanical layers; `cards` is the deck (a 20-card singleton library, §3); `gear` exists only on a campaign's copy (§13.3). The Deckbuilder is creation-only: a character file is always level 1 with nothing earned or spent. A campaign plays an instanced copy of each hero that it levels, equips and pays (§14.6).

### §10.1 The character object

| field | rule |
|---|---|
| `name`, `description` | the name; a one-line summary (pickers, Inspect) |
| `colors` | colour identity: 1–3 distinct of W U B R G |
| `starting_mana` | colour pips; the count is the mana capacity (≥ 1); an off-identity pip is an advisory warning |
| `hp` | total HP: even, ≥ 8 |
| `starting_cards` | integer opening-hand size (≥ 1), also the fresh hand at every phase start |
| `attack_mode` | `melee` (free base Power 2) or `ranged` (free base Power 1); exactly one is owned |
| `power_bought` | Power above the mode's base, 0 … 2 × level (T-60) |
| `keyword` | at most one, from the creation list below; creation only |
| `row` | starting row: `front` / `mid` / `rear` |
| `types`, `classes` | up to 2 each from the closed creature registries (§D21); free |
| `skill`, `ultimate` | heroic abilities (full card schema), outside deck and budget; the Skill is never instant (coerced to sorcery); the Ultimate is sorcery and never costs mana |
| `ability_flavor` | optional `{name, text}` for the evergreen attack / defend / mitigate; display only |
| `portrait`, `animations` | portrait image; panel-animation clips (Update 16) |
| `brief`, `brief_situation`, `lore`, `combat_lore` | the character layers (§10.3) |
| `level`, `earned_points`, `spent_points` | 1 / 0 / 0 on the file; a campaign copy carries its own (§10.2) |

The engine never reads a class name: it consumes the resolved **stat block** `{hp, mana_capacity, starting_cards, attack_profile: {mode, power}, keywords}` (Power = mode base + `power_bought`), with worn gear folded in (§13.3). Fighter, Tactician, Caster and Channeler are descriptive words; there are no presets.

**Creation is a points-buy.** From a free baseline (8 HP, 1 mana, 1 starting card, +0 Power) every hero spends a **70-point** budget on one escalating price curve (T-79). Purchase *n* counts from the baseline and continues through every later level-up; creation is just the first steps.

| purchase *n* | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | beyond |
|---|---|---|---|---|---|---|---|---|---|---|---|
| +2 HP (one pair) | 4 | 4 | 5 | 5 | 6 | 6 | 7 | 7 | 8 | 8 | +1 every two |
| +1 mana capacity | 15 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | 55 | +5 each |
| +1 starting card | 15 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | 55 | +5 each |
| +1 Power | 10 | 10 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | +5 each |

Worked examples: 20 HP / 2 mana / 2 cards / +1 Power = 30 + 15 + 15 + 10 = **70**. 8 HP / 2 mana / 3 cards / flying = 15 + 30 + 25 = **70**.

**Keyword prices** (one, ever; meanings in §7): reach 5 · trample 10 · first strike 15 · lifelink 15 · haste 15 · vigilance 20 · flying 25. Any other keyword is refused; hexproof, indestructible, deathtouch and infect are banned outright and reach a hero only as worn gear (§13.3).

**Validation.** Hard errors: colours outside 1–3 or repeated; HP odd or below 8; starting cards or mana below 1; bought Power above 2 × level (at creation +2: melee ≤ 4, ranged ≤ 3); an off-list keyword; an Ultimate with a mana cost; an unknown type or class. **Over-spend is advisory:** a build's budget is 70 plus its earned points; a file that spends more loads and plays, flagged with its overage in the Deckbuilder's budget meter, the New Game picker ("Over by N") and Options → Characters. The Deckbuilder will not step a build past its budget; only the level-up screen hard-limits spending (§13.2).

*Sources: §P-1–§P-4c, §D8-3.1–§D8-3.5, §D17-2.2, §D21-4b, §D23-2 · schema `Character`, `creation_points`, `stat_price`, `CREATION_KEYWORD_COST`, `BANNED_CREATION_KEYWORDS`; deckbuilder `api_character_model`, `api_character_price`.*

### §10.2 Levels

Level is **derived from the points a hero has spent** since creation (T-78): committing points is what levels you; banked points are potential, not level. A campaign copy recomputes its level from `spent_points` whenever points move. Maximum level 20.

| level | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| points spent | 10 | 60 | 105 | 150 | 210 | 300 | 390 | 480 | 570 | 690 | 810 | 930 | 1050 | 1200 | 1350 | 1500 | 1650 | 1830 | 2010 |

At 60 points an adventure (§13.1), a hero who spends as they earn reaches level 3 after one adventure, 5 after three, 7 after five, 10 after ten and 20 after thirty-four.

**Power cap (T-60).** Bought Power ≤ 2 × the level the draft build reaches, not the level the pool could buy: +1 Power at the cap is legal only if the same spend lifts the level.

**Potential and effective level (T-81).** Enemy budgets and item tiers never read the displayed level. They read **potential**: the level each hero's *earned* points reach as a continuous number (`level_progress`: 4.6 = level 4, 60 % toward 5), plus a gear bonus of floor(worn `points_price` ÷ 30). The party average, floored (minimum 1), is the **effective level**: the act's item tier (§13.5–§13.6) and the adventure's base level. Each phase is budgeted, unfloored, at the potential the party will have when it opens (earned so far, then +10, then +30; §12). Banking never buys weaker enemies.

*Sources: §D10-3.1, §D17-2.1, §D17-2.3, §D17-4.2 · schema `LEVEL_THRESHOLDS`, `level_for_points`, `level_progress`; scenario `levels`, `effective_level`, `phase_budget_levels`; items `effective_level_bonus`; adventure `confirm_level_up`.*

### §10.3 Character layers

Identity sticks to the character file, history to the campaign, geography to the world (§14.7).

| layer | author | lives on | size |
|---|---|---|---|
| sheet | player (Deckbuilder) | character file; points-buy fields instanced per campaign | §10.1 |
| brief | player | character file | ~150 words, nothing required |
| lore, combat lore | player | character file (`lore`, `combat_lore`) | any length |
| situation | player | campaign, per hero (seeded from the file) | ≤ 80 words |
| chronicle | engine | campaign, per hero | append-only |

**Brief** (`character.brief`): `concept` (one line, ≤ 20 words; writers fall back to `description`), `appearance` (one sentence), `voice` (`register` + up to three `samples`), `wants`, `wont`, `tell` (one line each), `ties` (one line each: people, factions, places, other heroes). Every story writer sees it; the enemy designer sees `concept` only. A hero with no brief plays unchanged.

**Lore** (`character.lore`, Deckbuilder → Brief & Lore) is pasted plain text. A Markdown heading starts an entry and every blank-line paragraph is one; an entry's keys are its capitalised names plus its heading's words. An entry reaches the **act writer only**, when the world touches it: a key appears in the composed town (names, roles, personas, topics, scenes) or the arc (title, villain, stakes, cast, places, act outlines). At most **two entries per act across the party**, most keys matched first, each cut to 120 words for the writer (never for the player). Markdown files in `loadouts/lore/<character_id>/` are read alongside (front matter optional; `keys:` and `gate:` honoured, `mode:` ignored). The arc writer, interlude planner and enemy designer never receive lore: it colours a line, never a quest.

**Combat lore** ("Abilities & Combat"): how the hero fights. The Deckbuilder's *Generate deck flavour* reads it (with the concept and lore) and writes 2–3 flavour lines per card and heroic ability into their Flavour fields; nothing mechanical changes.

**Situation**: where the hero stands now in this campaign, ≤ 80 words (longer is cut); seeded from the file's `brief_situation` when the hero joins, edited on the rest screen between scenarios; read by the arc writer, act writer and interlude planner.

**Chronicle**: engine-written, append-only, per hero per campaign; entries `{scenario, act, day, kind, text}` (an exact repeat of the last line is dropped).

| kind | written when |
|---|---|
| `accepted` / `refused` | a quest is accepted: every hero logs the option taken and each option left |
| `met` | first talk with an NPC this scenario (residents met here earlier in the campaign are not re-met) |
| `fell` / `slew` | an adventure ends: a hero at 0 HP `fell`; on victory each standing hero `slew` the boss |
| `bought` | a shop purchase (the buyer) |
| `levelled` | an adventure ends with the hero's level higher than when it began |
| `spent`, `stance`, `scarred` | reserved; nothing writes them |

Writers see the ten most recent lines plus one summary per past scenario (the ledger's one-liner, §14.6); the player sees everything on the sheet's **Deeds** tab, grouped by scenario. Which writer reads which layer: docs/generation.md.

*Sources: §D24-2, §D24-7.1–§D24-7.7 (with the 2026-09-06 lore amendment) · schema `Brief`; content `lore_text_entries`, `select_lore`, `lore_in_play`; scenario `chronicle_add`, `chronicle_view`, `set_situation`, `_harvest`; deckbuilder flavour `generate_flavours`.*

---

## §11 The effect vocabulary

### §11.1 Principles

- **Effects declare; the engine decides.** `destroy` carries only a target. Whether that kills a minion (leaving a corpse) or bounces off a boss above its execute window is for the resolver to decide.
- **Closed vocabulary.** There are 40 leaf verbs (`LEAF_EFFECT_CLASSES`) and 3 containers (`modal`, `conditional`, `stance`). All 43 kinds are one union keyed on `kind`, and anything else is rejected at load. Enemy `verbs` parse through the same union, with extra load checks (§11.2).
- **One resolver per verb.** `RESOLVERS` holds 40 handlers. Containers expand in `_resolve_effect`, and a stance is read when legal actions are built. Any form the engine doesn't model is logged "unhandled"; it is never guessed and never silently dropped.
- **Deterministic.** Amounts are exact; there are no rolls. The only randomness is a seeded library shuffle.
- **Adding a verb** touches about ten places: the schema class, a renderer, a resolver, several engine classification sets, the serializer, and the generation prompt if enemies may use it. The checklist is in [architecture.md](architecture.md) §14. The Deckbuilder derives its editor from the schema.

*Sources: GDD §1, §11 · §X-2, §X-6 · schema `LEAF_EFFECT_CLASSES`, `EFFECT_CLASSES`, `effect_specs`; engine `RESOLVERS`, `_resolve_effect`.*

### §11.2 Verbs

Every verb takes a `target` (a descriptor or `$slot`, §6) unless noted. On a channeled card it may also carry a `trigger` (§5.5). The **Enemy** column:
- **yes**: legal for enemies.
- **R**: reactive only; there is no target field, and the engine aims it at the triggering item.
- **C**: corpses only (checked at load).
- **H**: hostile forms only.
- **D**: forced discard only.
- **—**: not an enemy verb (never taught; inert or party-only).

| verb | what it does | key params | Enemy | notes |
|---|---|---|---|---|
| `deal_damage` | Damage. It meets, in order: the source's `amplify`, Mitigate, `prevent`, `protection`, the break check, temp-HP soak, then HP | `amount` | yes | lane from the stack kind (§5.5); trample on attacks only |
| `heal` | Restores HP, closing a wound first; never above max; removes all poison, even when it heals 0 | `amount` | yes | reaches downed heroes; fires `life_gain` |
| `lose_life` | Removes HP directly; not damage | `amount` | yes | ignores Mitigate, shields, temp HP and indestructible; never breaks a channel |
| `poison` | N poison counters; each drains 1 life per Upkeep | `amount` (1) | yes | any heal removes all; cancels regen 1:1 |
| `regen` | N regen counters; each heals 1 per Upkeep | `amount` (1) | yes | damage that connects removes all |
| `charge` | Adds or removes charge counters | `op`, `amount` (`"all"` only when removing); target defaults to self | yes | on an enemy, reaching `on_charge_full` detonates |
| `destroy` | Kills an enemy: it leaves a corpse, and death triggers fire | — | — | a boss only in its execute window; no effect on heroes or tokens; ignores indestructible; records the target's Level |
| `set_reference` | Remembers a number as `$name` for this resolution | `name`, `value`; target defaults to self | yes | read at its own position; unset reads 0 |
| `exile` | Removes for good: no corpse, no death trigger. Can also burn a corpse, which defeats a stirring one | `duration` (none or `while_channeled`) | C | a boss only in its window; a token is destroyed; a hero drops to 0; `while_channeled` suspends (§8.1) |
| `consume_corpse` | Spends a corpse as a cost | target: a corpse | yes | resolves last; no corpse means no cast; stops a rise |
| `bounce` | Sends an enemy to hand; it redeploys at the next Enemy Intents phase | — | — | keeps its HP; loses its temporary layers, channels and stack items; a party token is destroyed; a boss only in its window |
| `fight` | Two creatures deal their Power to each other at once | `target`, `other` | yes | Power is read first; counts as melee combat damage |
| `counter` | Cancels a matching opposing stack item | `filter` | R | §5.4 |
| `strip_intent` | Removes and reveals an enemy's declared intent | — | — | §5.2 |
| `break_channel` | Ends every channel the target holds | — | yes | mana returns; break triggers fire |
| `channel_drop` | Ends its own channel | none | yes | channeled cards only; must carry a trigger |
| `stun` | An enemy skips its next N declarations; a hero loses its next N main phases | `intents` (1) | yes | never cancels a declared intent |
| `pump` | +P Power and +T temp HP | `power`, `toughness`, `duration` | yes | negative values can kill |
| `wound` | −P Power and −T temp HP | `power`, `toughness`, `duration` | yes | kills at effective HP ≤ 0, even through indestructible |
| `sap` | −N mana capacity; trims the unspent pool now | `amount`, `duration` | yes | heroes only; never takes reserved mana |
| `modify_action` | Changes an evergreen action (§11.4) | `action`, `modifier`, `amount`, `duration` | H | characters only |
| `counters` | Permanent +P Power and +T max HP | `power`, `toughness` | yes | negative values can kill |
| `prevent` | Nullifies a damage lane, or forbids an action | `parameter`, `combat_kind`, `uses`, `duration` | yes | cleared every End Step; `attack` = Pacifism; `cast` = Silence (the Skill, Ultimate, attack and consumables still work) |
| `protection` | A charge negating the next matching damaging hit | `parameter`, `combat_kind` | yes | charges stack and never expire |
| `amplify` | Primes the next matching outgoing damage or heal: × `multiplier` + `bonus` | `event`, `combat_kind`, `multiplier`, `bonus` | yes | one-shot; lasts until spent |
| `copy_spell` | Copies a stack spell for the copier | stack spell | R | §5.4 |
| `redirect` | Re-aims a single-target stack item | stack item, `filter`, `new_target` | R | never a relentless enemy's action; `new_target: self` = bodyguard; an enemy without it turns the action back on its caster |
| `double_next` | The next matching item resolves twice | `filter`; target defaults to self | yes | §5.4 |
| `draw` | Draws N | `amount` | — | heroes only |
| `scry` | Looks at the top N and orders them top or bottom | `amount` | — | the player chooses only at top level |
| `move_card` | Moves N of a hero's cards between zones | `count`, `source`, `destination`, filters, `shuffle_after` | D | the affected hero picks |
| `create_token` | Creates N autonomous allies | `token_id`, `count`, `power`, `hp`, `keywords` | yes | an enemy may have at most 2 tokens alive (T-27; an Enrage or escalation is exempt); tokens leave no corpse |
| `taunt` | By a hero: the enemy's declared hostile intents re-aim at the hero, if they can reach them, until the End Step. By an enemy: the hero's basic attacks must target it through the hero's next turn | `duration` | yes | an enemy taunt always comes with a hit for its Power at execution (§D18-1) |
| `revive` | Stands a downed hero up at a fraction of max HP | `to_fraction` (0.5, T-44) | — | downed heroes only |
| `control` | A living enemy fights for the caster, keeping its stats but not its kit; or a corpse rises as an undead token at half max HP (T-52) | `turns` (none = the whole encounter) | C | never bosses; control never wins; ends at the Nth End Step |
| `move` | A forced move, applied at once | `direction` | yes | relative to the target's side; corpses stay put; triggers the intent re-check |
| `grant_keyword` | Adds keywords | `keywords`, `duration` | yes | grantable keywords only |
| `remove_keyword` | Removes keywords, or `["all"]` | `keywords` | yes | permanent |
| `ramp` | Raises mana capacity | `amount`, `color`, `availability` | — | `choice` = first identity colour |
| `add_mana` | Adds mana to this round's pool | `amount`, `color` | — | no capacity |

*Sources: GDD §11 · §R-11 · §X-2 · §D8-2 · §D9-1, §D9-3.1 · §D12-0 · §D18-1 · §D19-1, §D19-11 · §D22-1–§D22-3 · schema effect classes; engine `RESOLVERS`; scenario `_check_enemy_verbs`; llm enemy verb block.*

### §11.3 Containers, durations & values

**Containers** nest at most modal → conditional → leaf. A modal never holds a modal, and there is no repeat container.
- **`modal`** has `modes` (at least 2, each a `label` plus effects), `choose` (default 1) and `or_more`. Modes are picked at cast: each mode or legal combination is offered as its own cast, and a combination runs its modes in order. A channeled modal holds the chosen mode. A triggered modal is picked as its trigger stacks, or inline for `channel_start`.
- **`conditional`** has a `condition` and leaf `effects`. The condition is checked at resolution; if it is false, the effects are skipped and the skip is logged.

| condition | true when |
|---|---|
| `cast_mode` (action / reaction) | the card was cast with an empty stack / into an open window |
| `target_property` (has_keyword · side · level ± compare · row · is_dead · type · class) | the primary pick has the property (a corpse keeps its types; `is_dead` is read as resolution begins) |
| `caster_property` (row · has_keyword · channeling) | the source, or a channel's holder, does |
| `self_hp` (percent, or_less / or_more) | the caster's HP against that % of max |
| `enemy_count` (more / equal / fewer) | living enemies compared with living heroes |
| `spells_cast` (count, compare) | spells the caster has cast this round, this one included |

On an item with no pick, a `target_property` condition (other than `is_dead`) filters its nested `all` effects creature by creature: "deal 3 to every undead". For enemies, `cast_mode` is always action and `spells_cast` is 0.

**Cast mode** is *action* for a card cast with an empty stack on the caster's own turn, and *reaction* for one cast into an open window. The Skill and Ultimate are always actions, and a copy takes its copier's cast mode. **X** is a cost, not a container: a card with `cost.x` is offered once per affordable X, reads it as `{"ref": "x"}`, and a channel remembers it.

| duration | lasts | used by |
|---|---|---|
| `this_turn` (default; `end_of_turn` is a legacy alias) | until the End Step; an enemy's lockdown on a hero (wound, sap, modify_action, prevent attack/cast, taunt) through that hero's next turn | pump, wound, sap, grant_keyword, modify_action, prevent, taunt |
| `encounter` | through every End Step | pump, wound and sap (as an encounter layer), grant_keyword, modify_action |
| `while_channeled` | while the channel holds (§8.1) | pump, wound and counters (as auras), grant_keyword, modify_action, prevent, taunt, exile |

Exceptions:
- `prevent` and `taunt` end at the End Step unless a channel re-applies them, except an enemy's Silence/Pacify or taunt on a hero, which holds through the hero's next turn.
- `counters` and `remove_keyword` are permanent.
- `protection`, `amplify` and `double_next` last until spent.
- Poison and regen counters last until removed.
- `control` counts `turns` at End Steps, and `stun` counts `intents`.
- Instant action modifiers (§11.4) have no duration.

**Values.** An amount is an int, `"all"`, or a reference `{ref, mult}`, with `mult` a whole number ≥ 1. `"all"` works only for removing charge; elsewhere it is logged and skipped. Stat fields and `set_reference` take an int or a reference. References are read at resolution: `target_*` reads the creature the effect is landing on (each member of an `all` set reads its own), and `caster_*` reads the source. An unknown `ref` is rejected at authoring.

| reference | value |
|---|---|
| `x` · `casting_cost` | X chosen · mana paid (generic + pips + X) |
| `target_power` / `caster_power` | current Power (≥ 0) |
| `target_base_power` / `caster_base_power` | printed Power: before pumps and wounds, and without +1/+1 counters (ruled 2026-09-25, M1.31) |
| `target_hp` / `caster_hp` | effective HP |
| `target_base_hp` / `caster_base_hp` | max HP |
| `target_charge` / `caster_charge` | charge counters |
| `target_last_damage` / `caster_last_damage` | the last hit that connected with it |
| `party_size` · `enemy_count` | heroes, downed ones included · enemies in play |
| `mana_capacity` | the caster's capacity |
| `destroyed_target.level` | the Level of the enemy destroyed or exiled earlier in this resolution |
| `$name` | a `set_reference` value from the same card |

Shared targets (`$T1`, `$T1+row`) are covered in §6.

*Sources: GDD §11 · §X-2 · §D12-0 · §D19-8 · §D21 · §D22-1 · §D23-7.4 · schema `Modal`, `Conditional`, `Duration`, `Ref`, `REF_VALUES`; engine `_condition_holds`, `_target_property_filter`, `_ref_value`, `_end_step`.*

### §11.4 Action modifiers

`modify_action {action, modifier, amount?, duration}` changes how one of a character's evergreen actions works. The action and modifier must be a matching pair from `ACTION_MODIFIERS`; a mismatch is rejected when authored.

| action | modifier | effect | kind |
|---|---|---|---|
| attack | `make_ranged` | the basic attack becomes ranged | lasting |
| attack | `make_melee` | the basic attack becomes melee | lasting · hostile |
| attack | `switch_mode` | the basic attack swaps between melee and ranged | lasting |
| defend | `defend_as_reaction` | Defend can be taken in a reaction window without spending the turn (still once per round) | lasting |
| defend | `defend_double` | Defend grants twice base Power | lasting |
| mitigate | `mitigate_again` | Mitigate is no longer once per round | lasting |
| mitigate | `mitigate_full` | Mitigate's X equals full current Power (minimum 1) | lasting |
| skill | `refresh_skill` | a used Skill becomes available again | instant |
| skill | `lock_skill` | the Skill can't be activated; the Ultimate is unaffected | lasting · hostile |
| ultimate | `charge_ultimate` | +`amount`% of the gauge | instant |
| ultimate | `drain_ultimate` | −`amount`% of the gauge, never below 0 | instant · hostile |

- **Lasting** modifiers stay for their `duration`.
- **Instant** ones resolve once, ignore duration, and have no channeled form. The two gauge modifiers need `amount` > 0.
- **Attack mode:** a switch applies first, then any absolute; `make_ranged` beats `make_melee`.
- **Hostile** modifiers are the only ones enemies use.
- Only characters are affected.

*Sources: §D12-0 · §D19-7 · schema `ACTION_MODIFIERS`, `INSTANT_ACTION_MODIFIERS`, `HOSTILE_ACTION_MODIFIERS`; engine `_r_modify_action`, `_sync_attack_mode`, `_mitigate_value`, `_defend_value`.*

### §11.5 Card text

Authors write effects, not rules text.
- **Rendering.** `translation.render_effects` renders a card's `effects` and `targets` into its `translated_text`, with one renderer per kind (`RENDERERS`, 43). The Deckbuilder re-renders it on every save unless `text_override` is set; then the author owns the text.
- **Readers.** The engine never reads text. The card face shows it, or renders it live if the card has none (a consumable).
- **Channeled cards** use lead-ins: "While channeled:", "When this channel begins:", "At the start of every turn while channeled:", "Whenever your mana capacity increases:", "When this channel ends (dropped or broken):", "After N turns:", "Whenever <who> <event> while channeled:".
- **Shared slots** read "Choose an enemy: they …, then …". A per-use splash adds "(and so does its whole row)".
- **Other uses.** The same renderer writes strip reveals (§5.2) and a held channel's break note (`channel_break_clause`).
- **Not shown:** the `targeted` flag.

*Sources: GDD §11 · §D8-1.3 · §D19-6, §D19-8 · schema `Card.translated_text`, `Card.text_override`; translation `render_effects`, `RENDERERS`, `channel_break_clause`; serialize `card_text`.*

---

## §12 Encounters, objectives & adventures

### §12.1 The encounter

An encounter is one fight: a design pool plus one roster per party size.

| field | meaning |
|---|---|
| `name` | the encounter's name |
| `enemies` | the design **pool** (§9.1); at most one boss |
| `layouts` | `{"1": [ids], …, "4": [ids]}`: pool ids per party size; a repeated id clones |
| `tokens` | token definitions by id (name, HP, Power, row, attack mode, keywords, Level, image) |
| `objective` | optional; at most one (§12.2) |
| `scene`, `scene_image` | 2–3 sentences of setting, used as the backdrop prompt and a narration source; and the painted backdrop |
| `difficulty` | the difficulty it was made at: a display flag, not a rules input |

Each enemy also carries `flavor` (a one-line hint), `description` (its look, used as the portrait prompt) and `image`. An adventure phase adds `narration` (§12.3).

**Rosters.** At game start the encounter fields the layout for the largest defined size ≤ the party size. A party smaller than every key gets the smallest defined layout. A repeated id clones as `<id>_<n>` ("Name n"), sharing the design's art. With no `layouts`, the whole pool is fielded. Wave and reinforcement rosters resolve at the same size.

**Budget** (per layout, at generation). The sum of enemy Levels is about 2 × party size × average party level × a difficulty factor: Easy 1.0, Standard 1.5, Hard 2.5. A boss counts double. In scenario mode, the party level is the run's effective level (§13). A layout also needs at least 2 × party size bodies, so the party is always outnumbered.

**Difficulty acts at two moments.**

*At generation:*
- the budget factor above;
- HP × 1.0 / 1.2 / 1.5 by difficulty, then × a flat stat buff (1.2, or 1.3 for bosses), rounded up;
- Power × the same stat buff (minimum 1);
- token HP and token-definition Power buffed the same way.

The prompt also asks for a boss on Hard, a channeler on Standard and up, and lean designs on Easy.

*At build, every game:*
1. The layout is picked.
2. The **balance register** applies:
   - every enemy's Power and attack templates +2 (+4 for a boss);
   - hostile component `deal_damage` / `lose_life` +2 (+4 for a boss), and +2 more on row, blast or positional shapes;
   - a boss's Enrage is party-scaled instead (§9.5);
   - telegraphs are rewritten to state the new numbers.

   The register never touches heals, self-pumps, support or spawned tokens.
3. Boss tempo is set (§9.5).
4. In an adventure run at a different difficulty than it was made at, enemy and token HP rescale by the ratio of the two HP multipliers.

**Content rules.**

| rule | checked |
|---|---|
| ≥1 enemy, each named with HP and Level > 0; a legacy `intent` is named; ≤1 boss | every save |
| layout keys are party sizes; rosters are non-empty and draw on the pool; the boss appears in every layout (in the final wave under `waves`) | every save |
| objective schema and ids; the race target and guards are fielded in every layout; the target is not a guard | every save |
| every roster builds in the engine: condition kinds, `target_row`, no `stance`, enemy `control`/`exile` only on corpses, T-70 | every save |
| layouts "1"–"4"; 2× bodies per size; every enemy described | adventure phases (hand-authored standalone encounters are exempt, kept as-is 2026-09-25, M1.26) |
| scene and descriptions; 2× bodies | generation |
| **variety floor:** at least party size + 1 distinct designs per layout; at most 3 copies of any design | generation |
| a ranged enemy standing in Front is a layout fault | generation |
| ≥2 components per enemy; a self-only proactive pump needs cooldown ≥2 (unless reactive, once per encounter, or a gather); a gather needs its detonation | generation |
| a taunt must deal damage; corpse fuel uses `consume_corpse`; 1–2 types and 1–2 classes | generation |
| no two enemies share a kit; 3 or more hero-aimed rules may not all use one `target_rule`; at least min(4, pool size) archetypes; a pool of 3+ spans 2 rows and both attack modes | generation |
| boss dials (`enrage_round`, `neglect`); objective ranges (§12.2) | generation |
| pool of 5–8 designs; Level budgets; lockdown budget; one-per-encounter pieces; forced-mover cap | taught, not checked |

*Sources: §F-6, §E6-6, §X-5, §D10-4.1, §D12-0, §D14, §D18-2, §D21-1, §D23-6, T-37, T-38, T-40, T-41, T-64 · scenario `scale_encounter`; content `_validate_encounter`, `_bump_enemy_power`, `build_state_from_loadouts`; llm `_scale_hp`, `_check_layouts`, `_design_problems`, `_sameness_problems`.*

### §12.2 Objectives

An encounter may carry one objective, an alternate win or loss condition. Objectives are fully public: a banner on the first line of the intents window, a doom-clock badge on the marked enemy, and a log line when the last guard falls. The engine owns objective state. Timers count rounds and tick as each End Step completes. A party wipe still loses. Wave and reinforcement bodies that have not deployed wait in the **reserve zone**: off the field, untargetable, and not defeated.

| kind | fields | win / loss |
|---|---|---|
| `survive` | `turns` N; `reinforcements`: `[{turn ≥ 2, layouts or ids}]` | win when round N's End Step completes; survivors withdraw with no kill credit and no death triggers. Killing everything fielded does not win early while reinforcements wait in reserve (kept as-is, ruled 2026-09-25, M1.26) |
| `waves` | `waves`: the later rosters (the top-level layouts are wave 1) | win when every wave is defeated |
| `race` | `target` (a pool id); `turns` N; `fail`: `escalate` (default) or `defeat`; `escalation` {telegraph, verbs}, required if and only if `fail` is `escalate`; `guards` (pool ids) | defeat the marked enemy in time and the clock vanishes while the fight goes on; if the clock expires, you lose or the escalation fires |
| `deadline` | `turns` N | lose when round N's End Step completes unless every enemy is dead |

- **Reinforcements** deploy on their home rows at the start of round k's Intents step, and declare in that same step. Until they arrive they block a kill-all victory, but never the survive timer.
- **Waves.** The next wave deploys at the start of the Intents step after the field is clear. Clear means no living, bounced or stirring enemy; a dominated one does not count. So an End Step and an Upkeep always separate waves. A mini-boss appears only in the final wave. Each wave fields at least 1× the party size in bodies, and at least 2× across all waves.
- **Race.**
  - Only the graveyard or exile satisfies the clock. Stun, strip, bounce, suspension, stirring and control do not.
  - While any body of a guard design stands, the party cannot target the marked enemy with a card pick or a basic attack. Area effects still land.
  - When the clock expires on `escalate`, the marked enemy first returns from bounce, suspension or control. Then the payload goes on the stack from it as a triggered ability, with targeted verbs aimed by valuation. It is answerable like an enrage and costs no budget.
- **Deadline** is a hard clock. It has no target, no payload and nothing that interacts with it. It takes no reinforcements, waves or guards.
- **Generated ranges.** Race: 3–5 rounds with 1–2 guards, `escalate` preferred. Survive: 4–6 rounds with ≥ 2 reinforcement entries. Deadline: 4–6 rounds. Waves: up to 1.5× the phase's Level budget. The standalone encounter generator writes no objectives.
- **Adventures.** At most one objective per adventure. Phases I–II take any kind. On Phase III an objective may only modify the boss fight, in one of three shapes: a guarded `race` that marks the boss, a `waves` schedule whose final wave fields the boss, or a `deadline`.

*Sources: §D12-1, §D23-5, T-65–T-68 · schema `EncounterObjective`; engine `_deploy_objective_arrivals`, `_objective_tick`, `_objective_shielded`, `_race_expire`, `_check_end`; content `_validate_objective`, `save_adventure`; llm `_objective_problems`.*

### §12.3 Adventures

An adventure is three encounters, **phases** I, II and III, fought in sequence by one party at one difficulty. The phases move through a single place: outside it, inside it, at its heart. Each phase is a complete encounter plus a `narration` of 2–4 paragraphs in second person, present tense; a generated narration needs at least 100 words. To the engine, each phase is an ordinary encounter.

**Shape rules.**
- Exactly three phases, each passing the save gate and the phase gate (§12.1).
- Every phase has a narration.
- At most one objective (§12.2).
- Phase III holds exactly one boss, and no enemy in the adventure outranks its Level.
- Phases I and II may each field one mini-boss, at a strictly lower Level than the Phase III boss.

**The ramp.** Each phase is budgeted for the level the party's earned points will have reached by the time it opens (a continuous level, plus gear), using the formula in §12.1. Difficulty therefore climbs by construction.

**Between phases:**
1. the victory splash;
2. the level-up screen, which every character must confirm (points are paid per phase won, §13.2);
3. the next phase's narration;
4. the next phase, built fresh, with this carry-over:

| what | across the boundary |
|---|---|
| HP | carries, plus any max HP bought at the level-up, then floored at ceil(25% of max HP). The incapacitated stand back up at the floor |
| hand, library, graveyard | shuffled together; a fresh hand of starting-cards is drawn, with unused consumables re-dealt on top |
| exile | stays exiled |
| Ultimate gauge | floor(gauge × 0.5) |
| everything else | resets: channels drop silently; statuses, counters, afflictions and granted keywords clear; mana returns to base; Skill and Ultimate refresh |

**Victory and defeat.** Winning Phase III wins the adventure. A lone adventure ends on defeat and offers a restart from Phase I with the same party and a fresh state. Inside a scenario, defeat returns the party to town to retry the quest against a freshly generated adventure, or ends a Hardcore run (§14).

*Sources: §D10-1, §D10-2, §D10-4, §D10-6.3, §D17-2.3, §D17-6.4, T-58, T-59, T-61, T-62 · content `save_adventure`, `_validate_phase`, `_validate_adventure`; adventure `AdventureRun._open_gate`, `advance`; llm `phase_budget_levels`, `_narration_problems`.*

---

## §13 Progression & economy

### §13.1 Earning

Points come only from winning phases. Each phase pays every hero the moment it is won, into the bankable pool (T-57):

| phase won | I | II | III | per adventure |
|---|---|---|---|---|
| points, each hero | +10 | +20 | +30 | 60 |
| gold, each hero (T-85) | 10 | 20 | 30 | 60 |

- Grants count toward `earned_points` (what budgets read, §10.2) at once; spending is a separate act (§13.2).
- **Gold** is one per point earned, credited to each hero's own purse when the adventure ends, won or lost: phases won before a defeat keep their points and gold.
- **Starting purse (T-87):** 15 gold per hero when the campaign is created; later scenarios add none.
- **Other gold:** the `give_gold` hook (every hero gets the amount) and selling (§13.6). Gold is per character; it moves between heroes only by trade.

*Sources: §D17-2.1, §D17-2.3, §D17-5.3 · schema `PHASE_GRANTS`; adventure `_grant_phase_points`; scenario `STARTING_GOLD`, `GOLD_PER_POINT`, `_harvest`.*

### §13.2 Spending & level-up

**When.** A level-up screen opens at every phase boundary (after Phases I and II) and, in scenario mode, after Phase III behind the spoils (§13.5), in every act including the closing one. A lone adventure has no screen after Phase III. A screen may spend any part of the pool (the grant just won plus anything banked) or nothing: an unchanged confirm is *Press On*. Phase carry-over (HP floor, gauge, fresh hand) is §12.

**The screen** is the Deckbuilder's points-buy panel in locked-baseline mode (§10.1): *Locked* (the entering build's spend), *To spend* (the pool), the level the draft reaches, one Confirm per hero; the gear tab works here (§13.3).

**Rules.**
- **Banking:** unspent points carry forward, uncapped, across phases, acts and scenarios.
- **Locked baseline:** nothing bought earlier is sold back; HP, starting cards and bought Power never go down; existing mana pips keep their colours, and new capacity appends pips coloured on the screen within the identity.
- **Power cap** at the level the draft reaches (T-60, §10.2); a spend beyond the pool is refused.
- **HP purchases heal:** +2 max HP is +2 current HP, at the next phase's start or, on the act-end screen, on the HP carried to town (then the 25 % floor, T-59).

**What cannot change in play.** Only HP, mana capacity, starting cards and bought Power move (gear aside, §13.3). The validator locks the deck, colours, keyword (creation only), attack mode, row, type line, Skill and Ultimate; on each campaign load these follow the character file instead (§14.6).

**Multiplayer gate.** Each player confirms every hero whose seat they hold and sees others only as confirmed / waiting. When all have confirmed the game auto-saves (§14.2) and composes the next phase (after the act-end screen, the act wraps up instead, §14.5).

*Sources: §D10-3.1, §D10-3.3, §D17-2.3, §D24-4 · adventure `validate_level_up`, `confirm_level_up`, `open_final_gate`; scenario `act_ends_on_screen`; session `confirm_level_up`.*

### §13.3 Gear

**Slots (T-80).** A campaign copy has three worn slots — **primary weapon**, **secondary weapon**, **accessory** — a **belt of 3** consumables and an **inventory** of 3 unworn gear + 3 unworn consumables; beyond that, sell, discard or trade.
- The **primary** sets the attack mode (it may grant one the build never bought; base Power follows the mode: melee 2, ranged 1) and adds its Power bonus and every other static. The **secondary** contributes only its non-mode, non-Power statics. The **accessory** contributes all its statics (it cannot carry mode or Power).
- Equip, unequip, belt moves and discard happen on the character sheet, in town or at a level-up screen, never in combat; equipping returns the old piece to the inventory, which must have room.
- New items land on the belt (consumables; else the consumable inventory) or in the gear inventory; a full destination refuses the purchase, trade or reward assignment.
- Gear keywords are worn, not bought: they join the keyword list outside the one-keyword rule, and are the only way a hero gets a creation-banned keyword.

**The item object.**

```
item = { id, name, slot: weapon | accessory | consumable,
         rarity: common | uncommon | rare | mythic, level_min ≥ 1,
         points_price ≥ 0,   # the balance handle, on the level-up points scale
         flavor, art_desc, art_url,
         statics: [ {kind: attack_mode | power_bonus | keyword | stat | ability, …} ],   # gear
         effects, targets, consumable: {timing: instant | sorcery},                       # consumables
         template?, affixes }
```

Gear carries statics, never effects; a consumable carries ≥ 1 card-vocabulary effect, never statics. `stat` riders are `hp`, `mana`, `cards`; an `ability` static grants a card; a `keyword` static may name any registry keyword.

**Composition.** At every encounter setup (every phase) the combat adapter folds worn gear into the stat block, as a level-up would: mode and Power from the primary; keywords appended; `hp` raises max HP; `mana` adds pips of the first starting-mana pip's colour; `cards` raises the opening (and phase-start) hand; each `ability` static deals its card above the opening hand every encounter, as belt consumables are (§13.4). The engine sees only the stat block.

**Worn points (T-81)** are the `points_price` total of the three worn slots (belt and inventory excluded); floor(worn ÷ 30) is the gear bonus to potential level (§10.2).

**The base catalogue** (`content/equipment/`, tracked) is the balance floor and the merchants' shelf: 26 weapons, 24 accessories, 26 consumables, `level_min` 1–6, common and uncommon (two rare weapons are never stocked). Options → Equipment edits it (user items in `loadouts/equipment/` shadow catalogue ids) and paints missing art.

*Sources: §D17-4.1–§D17-4.3 · schema `Item`, `ItemStatic`; items `equip`, `add_item`, `worn_points`, `effective_level_bonus`; combat scenario `fold_gear`, `compose_spec`; session `economy_verb`.*

### §13.4 Consumables

A belt consumable is an **always-in-hand card**: at every encounter (every phase) it is dealt above the drawn opening hand from turn 1 until used. It shows the item's name, art and flavour; its effects are the card vocabulary verbatim.

- **No mana cost**, no gauge. Speed is the item's: `instant` (whenever the hero could react) or `sorcery` (own turn, empty stack, spending the Cast verb).
- On the stack it is an **activated ability** (kind `activated`): a spell-filtered counter cannot stop it; an activated-, ability- or action-filtered counter can. Silence does not stop it.
- Using it **consumes** it, even if countered: the card is exiled (never reshuffled at a phase boundary) and the item leaves the belt when the adventure ends. Unused, it stays on the belt.
- Only the belt's three are dealt, never inventory consumables. Nothing is shared mid-encounter; trade in town (§13.6).

*Sources: §D17-4.4 · schema `Item.as_card`; combat scenario `fold_gear`; engine `_do_cast`, `_silenced_for`; items `consume_used`.*

### §13.5 Rewards & loot

**When.** The act's boss drops are **forged** at act materialization — arrival in town, when the stock is rolled — and frozen onto the act (`act.spoils`): a reload shows the same drops, the art queue paints them during the visit and the ride out (run-only art, `loadouts/art/spoils/`), and nothing is revealed until the Rewards modal. The interlude forges none.

**How many (T-83):** party size + 1 gear (weapon, accessory, weapon, …) and party size × 2 consumables. **Tier:** act tier + 1 (the effective level at arrival, §10.2), above anything the act's shops sell.

**Forging** — mechanics from code, words from the scenario:
- **Weapon:** melee or ranged at random; Power bonus at the tier step (+0 at tier 1, +1 at 2–5, +2 at 6+), a boss drop at least +1 and half the time one more; 15 points per Power.
- **Accessory:** one chassis rider: +4 HP (10 points), +6 HP (15, tier ≥ 2), +1 mana (15) or +1 starting card (15).
- **Affixes:** 1–2 from the table below (weighted 1 : 2), `level_min` ≤ tier, no two of a kind — including the banned-keyword affixes, which only boss drops roll.
- **Rarity:** the highest affix `rarity_min`; a +2 Power weapon is at least uncommon; a drop with affixes has a 50 % chance of one step higher. `points_price` = chassis + affixes + premium (rare +5, mythic +10).
- **Consumable:** a code recipe with `level_min` ≤ tier (heal, big heal, regen, ward, aegis, pump, counters, burn, bomb, venom, stun, strip, draw, scry, wings, quickness), effects and price scaling with tier; rarity by price (≤ 10 common, ≤ 18 uncommon, else rare).
- **Words:** names, flavour and art descriptions come from the scenario's **loot lexicon** (`arc.loot_lexicon`): forms, materials, epithets, "of the …" phrases and details, drawn in code from theme word-banks matched against the town and arc text, deterministic per arc; each new arc draws its own. No LLM call sits between a boss's death and its loot.

**The affix table** (shared with merchant stock, §13.6):

| affix | on | grants | points | rarity min | level min |
|---|---|---|---|---|---|
| Sturdy | both | +2 HP | 5 | common | 1 |
| of Vigour | both | +4 HP | 10 | uncommon | 2 |
| Attuned | accessory | +1 mana | 15 | uncommon | 2 |
| of Wits | accessory | +1 starting card | 15 | uncommon | 2 |
| Keen | weapon | +1 Power | 10 | uncommon | 2 |
| Reaching | weapon | reach | 5 | uncommon | 1 |
| Trampling | weapon | trample | 10 | rare | 2 |
| Swift | both | first strike | 15 | rare | 3 |
| Thirsting | weapon | lifelink | 15 | rare | 3 |
| Watchful | accessory | vigilance | 20 | rare | 4 |
| Venomed † | weapon | deathtouch | 25 | rare | 5 |
| Blighted † | weapon | infect | 30 | mythic | 6 |
| Unbroken † | accessory | indestructible | 35 | mythic | 6 |
| Warded † | accessory | hexproof | 40 | mythic | 6 |

"both" = weapon or accessory; † boss drops only.

**The Rewards modal** (after Phase III, before the act-end level-up): each item goes to a hero or *Discard* — a hero whose belt or inventory would overflow, counting the other assignments, shows *full*. Once all are assigned, any player presses **Accept** → all-players confirmation (§14.3) → items land → auto-save → the act-end level-up.

*Sources: §D17-4.3, §D17-4.5, §D19-3 · loot `forge_drops`, `forge_gear`, `forge_consumable`, `build_lexicon`; items `AFFIXES`; scenario `spoils_tier`, `open_rewards`, `assign_reward`, `accept_rewards`.*

### §13.6 Shops, selling & trading; rest

**Stock.** Rolled in code when the act materializes (interlude included): weaponsmith 4 weapons, artificer 4 accessories, apothecary 6 consumables, at **stock tier = act tier − 1** (minimum 1). Each entry is a catalogue template with `level_min` ≤ stock tier and rarity ≤ uncommon; weapons and accessories take 0–1 affix (weighted 1 : 2) from the affix table, capped at uncommon, never a banned keyword; consumables sell as catalogued; no two entries share a name.

**Fixed per act.** Stock is frozen onto the act (it survives reloads); a bought item leaves the shelf, and nothing restocks until the next act or a Normal-mode return re-materializes it. Sold items never join the stock.

**Buying** — at the shop, from its vendor (*See their wares*); per player, asynchronous, no confirmation. Price = `points_price` × 1.25, rounded, minimum 1 (T-86); the buyer needs gold and room (§13.3). Purchases are chronicled (`bought`) and logged on the ledger.

**Selling** — any item, anywhere in town, for floor(`points_price` × 0.5) (T-86).

**Trading** — town only, via the character sheet: an item and/or gold between two heroes. If another connected player holds the receiver, it becomes an offer that player accepts (either side may cancel); otherwise it is immediate. One offer pends at a time.

**Rest.** The inn's rest is a dialogue choice carrying `rest` (the innkeeper's "Take a room."). It is guaranteed: when no tree at the inn offers one this act, the inn's first resident gets "Take a room." on their opening node. Taking it is a party-wide confirmation, a **free full HP restore** for every hero, then a manual `inn` save. Mana, hand, gauge and uses reset at adventure start anyway; without rest, heroes keep the HP they returned with (floored at 25 % of max, T-59). In the interlude, rest opens the rest screen instead; the heal comes with the chosen hook (§14.6).

*Sources: §D17-4.3, §D17-5.3, §D17-5.5, §D24-5.3 · items `roll_stock`, `buy_price`, `sell_price`; scenario `_take_materialization`, `buy`, `sell`, `give`, `rest`; session `economy_verb`, `_fire_choice`.*

---

## §14 Scenario mode & campaigns

### §14.1 The ladder

| rung | word | means |
|---|---|---|
| 1 | **Round** | one combat turn cycle (§4) |
| 2 | **Encounter** | one fight, start to victory or defeat |
| 3 | **Phase** | one of an adventure's three fights (I gate, II courtyard, III throne room); level-ups sit between them |
| 4 | **Adventure** | three phases through one place, generated in one call; HP carries across its phases; no town inside it (§12) |
| 5 | **Act** | one town visit + one adventure: the story beat ("Act II: The Siege of Hollowmere") |
| 6 | **Scenario** | an arc of three acts against one villain, run from one town |
| 7 | **Campaign** | scenarios played by one fixed party in one continuity; between them the party rests in town (the interlude) and chooses where the story goes, here or elsewhere |

The party returns to town only between adventures, never between phases. Every scenario game is a campaign of length one until continued. The **worldbook** (§14.7) sits beside the ladder: what a traveller knows about each town.

*Sources: §D10-1, §D17-0, §D24-1 · content `PHASE_COUNT`; scenario_content `ACT_COUNT`.*

### §14.2 Runs, saves & the content store

A **run** is a party + immutable options + a branching tree of saves. A scenario game's run is a **campaign** (`kind: "campaign"`); the server can still play a lone adventure as a run (`kind: "adventure"`), but the client no longer offers it, since Load Game never listed those runs (ruled 2026-09-25, roadmap M1.37). **Options**, fixed at creation: difficulty (easy / standard / hard, applied to every adventure the run plays) and Normal / Hardcore (§14.5). Everything lives under `saves/<run_id>/` — gitignored runtime data, self-contained, portable as a directory:

```
saves/<run_id>/
  run.json                      # party, options, dates, dead, the campaign record (§14.6)
  content/<sha256>.json         # the immutable content store
  saves/<timestamp>_<seq>.json  # small snapshots: state + references into content/
```

**The content store.** Everything a save points at — the base town, each arc, act materialization, adventure and interlude, each hero's loadout copy — is written once, addressed by the SHA-256 of its canonical JSON, and never modified, regenerated or garbage-collected. A save is small: party and progression state plus hashes. Loading restores exactly what it pointed at; forks share what they have not diverged on. A generated adventure enters the store the moment it validates, so later saves reload it, never a re-roll.

**Saves are rows, not slots.** Each carries a timestamp, a kind, auto/manual, the seed of the phase about to compose, and a progression label ("Hollowmere · Scenario 1 · Act II · Town — the Inn", "… · Adventure, Phase 3"). Loading any save and playing on appends new rows — a fork; nothing is pruned. Deleting a save removes its snapshot only; deleting a campaign removes its directory (both confirmed).

| kind | written when |
|---|---|
| `act_start` | the act's town portion is ready (arrival, a Normal-mode return, a new scenario's Act I) |
| `quest_accept` | an accept fires, before the adventure job |
| `inn` (manual) | the inn's rest, outside the interlude |
| `town` / `interlude` (manual) | Save Game |
| `adventure_start` | the ride out (Phase I's seed) |
| `phase_boundary` | every level-up confirmed, before the next phase composes (its seed) |
| `adventure_end` | Phase III won |
| `rewards` | spoils accepted |
| `scenario_complete` | the closing act's wrap-up ends, before the scenario-end menu |
| `interlude` | the party enters the interlude |
| `hooks_chosen` | a hook is chosen |

**No mid-combat saves:** an adventure save restores a phase start (or the act's wrap-up, resuming at the spoils or the act-end screen); fighting since the last boundary is lost.

**Continue** is the newest save by timestamp, not the furthest progression: play on from an older save and Continue follows the new branch.

**Load Game** lists campaigns only (adventure runs are not listed), each with its party and state (in a scenario, between scenarios, victorious, fallen). Opening one loads its newest save: mid-scenario resumes; the interlude resumes in town; a campaign left at the scenario-end menu runs the continue path (§14.6). *Older saves* lists every save, oldest first, loadable (a fork) and deletable. A fallen Hardcore campaign cannot be loaded.

**Versions.** `run.json` is schema 2 (a schema-1 run loads as a campaign with an empty ledger and heroes seeded from its party); snapshots are schema 1, and a newer snapshot refuses to load.

*Sources: §D17-3.1–§D17-3.3, §D17-6.3, §D24-3, §D24-4 · runs `RunStore.put`, `RunManager.save`, `progression_label`, `newest_save`, `load_scenario_save`, `RUN_SCHEMA_VERSION`; app `continue_run`, `_open_save`; session `save_point`.*

### §14.3 Towns

A **town** is standalone content (`content/towns/<id>.json`), generated (with its worldbook entry, §14.7) or authored — the stage for many scenarios and campaigns.

```
town = { name, region_flavor, scene, art_url,
         locations: [ { id, name, function, description,
                        exterior_scene, exterior_art_url,   # the map card, 16:9
                        interior_scene, interior_art_url,   # the location backdrop, 16:9
                        npcs: [ { id, name, role, persona, portrait_desc, art_url,  # portrait 1:1
                                  topics: [ {ask, reply} ], vendor } ] } ] }
```

- **Required functions**, one location each: **inn**, **weaponsmith**, **artificer** (accessories), **apothecary** (consumables); plus 1–8 **flavour** locations (tavern, shrine, witch's hut, guard post, market, docks, library, graveyard, gate, manor, well, chapel, stables, warrens, generic). Generation writes 1–3; the editor's **+ Location** / **+ NPC** grow a town any time.
- Every location has an interior scene and 1–4 residents; every resident has persona prose and a portrait description. The persona is injected verbatim into every later generation, so a resident stays the same person across acts, scenarios and campaigns.
- **One counter per shop:** at a merchant location exactly one resident vends (the first marked `vendor`, else the first); the rest only talk.
- **Topics:** up to 4 scenario-agnostic `{ask, reply}` exchanges per resident; Options → Towns → *Write flavour topics* fills gaps.

**The town screen** reuses the battlefield shell. Arrival: a splash (town, "Act n — title" or "Between scenarios — the Interlude · day n", the arrival paragraph). The **map** shows one 16:9 card per location — name and frontage only, no quest, talk or wares badges: where the quest is, the party learns by asking. Location → inspect → **Visit** (a splash describing the room) → its residents; resident → inspect (persona) → **Talk**, or **See their wares** on the vendor. Console: *Character sheets · Save Game · Quest Log · Leave Location · Start Adventure* (*The road ahead* in the interlude).

**Party-wide confirmations (T-84).** Visit, Leave, Start Adventure, dialogue choices carrying a party-wide hook (§14.4), the spoils' Accept and the rest screen's hook choice open the **all-players confirmation**: every connected player answers; one "no" cancels; the initiator may cancel; 30 s unanswered counts as yes; one at a time; with one player connected the action simply runs. Inspecting, talking, shopping, gear and selling are per player and immediate; trades use the two-party offer (§13.6).

**The town as each act sees it.** The run never plays the town file directly: at every arrival, restore, art reload and town-state change it composes `town_for_act(base town, arc, act, town state)` — the arc's **places** present this act join as flavour locations, its **cast** present this act stand at a town location or place as ordinary residents (never vendors), then the campaign's **town state** overrides location descriptions and scenes (§14.6). Merged entries are stripped on recomposition, so a visitor leaves no trace once their acts are over. Everything downstream (screen, dialogue validation, journal, the "nobody is a closed door" rule) reads the composed town.

*Sources: §D17-5.1, §D17-5.2, §D17-13.1–§D17-13.3, §D17-13.6, §D20-2, §D24-8.2 · scenario_content `validate_town`, `vendor_of`, `town_for_act`; scenario `arrive`, `visit`, `town_snapshot`; session `town_verb`, `request_confirm`.*

### §14.4 Dialogue

Dialogue is authored at generation (act materialization, §14.5) and walked deterministically at runtime; there is no live LLM dialogue (`freeform` trees are rejected).

```
tree = { root, nodes: { id: { speaker: npc | party | narration, text,
                             choices: [ { label, next?, requires: [flag…], effects: [hook…] } ] } } }
```

- A choice without `next` ends the conversation. Writers are asked for 2–4 nodes deep and 2–3 choices; the validator allows up to 5 choices and depth 10, and rejects loops and dangling `next`s.
- `narration` nodes are unvoiced stage directions. A tree of 4+ nodes needs at least one (the questgiver's, two).
- The **initiating player chooses**; everyone sees the same transcript. Party lines are attributed to the initiator's own hero (first claimed seat in roster order); the initiator may re-attribute to any hero (cosmetic).

**Hooks** are a closed vocabulary; anything else fails validation.

| hook | what it does now |
|---|---|
| `set_flag {flag, value}` | sets a run flag; a `knows_*` flag also records what was learned on the act's ledger entry |
| `grant_quest {quest}` | takes that quest option (§14.5); party-wide |
| `unlock_adventure` | opens the act's Start Adventure gate (write-once per act); rides with every `grant_quest`; party-wide |
| `defer_quest` | "let us get back to you": marks the NPC as awaiting an answer; journalled |
| `advance_quest` | relabels an accepted quest's status as *advanced*; nothing else |
| `give_gold {amount}` | every hero gains the amount; journalled |
| `give_item {item}` | sets the flag `item_<id>` only; no item lands |
| `rest` | outside the interlude: free full heal plus the inn save; in the interlude: opens the rest screen; party-wide |
| `open_shop` | sets `_shop_open`, which nothing reads (shops open by location, §13.6) |
| `direct_to {npc?, location?}` | writes the Quest Log pointer and journals "We were told to seek …" |

**Party-wide choices** (carrying `grant_quest`, `unlock_adventure` or `rest`) open the all-players confirmation; an accept's prompt names the option ("Accept ‹title› as your next quest?"). Other choices fire at once.

**Flags.** `requires` lists flags that must all be true; there is no negation. Flags live on the run through a scenario; at its end all are cleared except what the campaign keeps (§14.6).
- **Standing flags**, set by the runtime: `defeated_once` (a Normal-mode defeat this act), `quest_accepted`, `act_1_complete` … `act_3_complete`; the prefixes `item_` (`give_item`) and `town:` (campaign town state) count as standing.
- **Bookkeeping**, never shown to a writer: `_met_<npc>`, `_offered_<quest>`, `_shop_open` and `deferred_<npc>`.

**Knowledge gating.** Writers follow a convention: the choice that hears an NPC explain something (the trouble, a name, a place) carries `set_flag knows_<thing>`; any choice or act topic elsewhere that presumes it `requires` it; root choices read as things a stranger could say; the questgiver's own tree is ungated. The **reachability check** enforces it: every flag required in the trees and act topics must be standing, already true in the run, or settable by a `set_flag` in this act's trees, or the act is rejected with an error written for the generator's repair loop. `knows_*` flags last one scenario; the ledger keeps what was learned as prose.

**Conversations.** An NPC with an authored tree this act speaks it. One without still holds a conversation: a greeting (the act's flavour line, else the persona's first sentence), up to four topics (the act's, then the town's; a gated act topic appears once its flag is true), then *Farewell*. An accept or defer that would end a conversation cold gets the NPC's closing line (authored per NPC, or a default).

**The journal** records only what the party has heard, in order: the arrival paragraph, each resident's persona card on first talk, every NPC line, each quest option once when first seen ("Available quest — …"), the accepted quest in the party's voice ("We took on …"), and events (deferrals, pointers, gold, ride-outs, defeats, completed acts, the bridge between scenarios).

*Sources: §D17-5.4, §D17-13.2, §D17-13.5, §D20-1, §D24-7.7 · dialogue `HOOKS`, `PARTY_WIDE_HOOKS`, `validate_dialogue`, `Conversation`, `check_flag_consistency`; scenario `_apply_hook`, `talk`, `_flavor_tree`, `add_journal`; session `town_verb`.*

### §14.5 Acts, arcs & quests

**The arc** is the scenario's spine, generated once per scenario (at New Game for Town + New; shipped with a pre-generated scenario; after the rest screen for a continuation) and passed verbatim to every later writer.

```
arc = { title, villain, stakes,
        acts: [ { title, hook, questgiver_npc, questgiver_location, handoff?,
                  adventure_theme, tone_notes } × 3 ],
        cast?:   [ { id, name, role, persona, portrait_desc, location, acts?, secret?, topics? } ],  # 0–4
        places?: [ { id, name, function, description, interior_scene, exterior_scene, acts? } ],  # 0–2
        loot_lexicon }
```

Each act's questgiver is a town resident or a cast member present that act (the location follows the NPC). **Cast** are people the scenario brings to town, optionally for certain acts only; a `secret` is one line only writers see (a betrayal set up in Act I, paid off in Act III). **Places** are flavour-only locations the scenario adds. Both are painted on the art queue and merged by `town_for_act` (§14.3).

**Act materialization — at arrival.** Under the entry splash one writer call produces the act's town portion; code rolls the stock (§13.6) and forges the spoils (§13.5); the act is frozen into the content store with an `act_start` save. It carries 2–4 **quest options** `{id, title, text, adventure_theme}`, the arrival paragraph, dialogue trees, flavour lines, act topics, optional per-NPC re-ask / accepted / declined / committed lines, and an optional `town_state_delta` (≤ 2 locations). Validation requires:
- a distinct `adventure_theme` per option — different troubles, or branches landing in different places with different objectives, never one objective by two roads;
- an accept choice for every option somewhere in town, carrying `grant_quest` (with its id) **and** `unlock_adventure`;
- a `defer_quest` beside every offer;
- a tree for the outline's questgiver, the narration floor and flag reachability (§14.4);
- **nobody a closed door:** every resident of the composed town has a tree, a topic or a flavour line.

A failed materialization shows an error in town; reloading the save resumes it.

**Choosing a quest.**
- **Defer** marks the NPC: the next talk opens on a re-ask ("Have you had time to consider what I asked?") carrying every offer they made plus another defer. Deferrals clear on arrival and on acceptance.
- **Accept** (party-wide, irreversible) fixes the act's quest (id, title, text, theme), sets `quest_accepted`, logs the option taken and every option refused on the ledger and in each hero's chronicle, journals "We took on …", opens the gate, auto-saves (`quest_accept`) and starts the **adventure job**.
- **One quest at a time:** while committed, every other accept in town becomes a refusal in the party's voice (with the NPC's reply), the sworn questgiver's re-offer becomes a reminder of the word given, and defers vanish. A party beaten back to town may choose again.

**The adventure job** generates the adventure only for the accepted option — so every option is equally real — with a context block (arc, town, quest, the option's theme) at the party's effective level and per-phase budget levels (§10.2, §12). States `idle → pending → ready | failed`, persisted on the run. The validated adventure enters the content store at once; its art queues Phase I first and keeps painting after the ride out. On failure the quest stays accepted and the console offers *Generation failed — Retry*; a reload resumes an unfinished job. A pre-generated scenario's Act I adventure is ready at once if the party takes the option it was written for (`act1.quest_id`); any other option generates its own.

**Start Adventure** — enabled when the gate is open and the adventure ready, from the town map with no conversation open, never in the interlude; a party-wide confirmation ("Ride out — ‹name›?"). Phase I composes from the run's hero copies (pools, levels, gear, carried HP); the day advances by 1; `adventure_start` is saved.

**Winning the act:** spoils (§13.5) → act-end level-up (§13.2) → the harvest returns builds, points, gold, used consumables and HP (floored at 25 %) to the run → `act_<n>_complete` set, `defeated_once` cleared → back to town and the next act materializes; after Act III the scenario ends (§14.6).

**Defeat.** The defeat splash holds until the party presses on ("forced to flee"); the phases won still pay.
- **Normal:** back to town, quest unadvanced, `defeated_once` set, defeat logged. The act's town portion **re-materializes** with that flag (a defeat-aware tree, fresh stock and spoils); the quests are offered again, and accepting generates a fresh adventure (the old one stays in the store).
- **Hardcore:** the campaign dies (`dead` on run.json); the end screen says so, and its saves are listed but cannot be loaded.

**The Quest Log** (console) is the journal panel: arc title, act (or *Between scenarios*) and day; the full journal (§14.4); the current `direct_to` pointer ("Seek ‹NPC› at ‹place›"); and the deeds done (each completed act and its quest). The quest's text reaches the player through the journal's accept entry; the side panel shows its title and status.

*Sources: §D17-5.4, §D17-5.6, §D17-6.1–§D17-6.4, §D17-13.4, §D17-13.5, §D20-2, §D20-3 · scenario_content `validate_arc`, `validate_materialization`, `_bind_quest_hooks`; scenario `_take_materialization`, `_apply_hook`, `_committed_tree`, `_reask_tree`, `start_adventure`, `on_adventure_complete`, `on_adventure_defeat`, `quest_log`; jobs `AdventureJobRunner`; session `_scenario_transitions`.*

### §14.6 Campaigns

A **campaign** is the unit of continuity: one party, fixed for its life, playing scenarios in one continuity. The same hero in two campaigns is one person with two unrelated histories; levels, gear and purse are per campaign (a hero starts each new campaign at level 1).

**The campaign record** rides `run.json` (for the Load list) and every save snapshot (so a fork keeps its own history; a load prefers the snapshot's copy).

| field | holds |
|---|---|
| `kind`, `state` | `campaign`; `in_scenario` / `interlude` / `between`, set from the newest save's kind |
| `scenario_count`, `current_scenario`, `current_town_name` | the scenario number and where the party is |
| `ledger` | one entry per completed scenario |
| `towns_visited`, `current_town_id` | the road so far |
| `town_state` | per town: `flags`, `overrides`, `met`, `talked` |
| `heroes` | per hero: `situation`, `chronicle` (§10.3) |
| `hooks` | the three proposed hooks, the one chosen, the note, the custom card |
| `day` | the day counter |

Build fields, points, level, gear, gold and carried HP live on the run's hero copies and pools (§13).

**The ledger** is the writers' memory: per scenario — number, title, villain, town, outcome, days, a one-line summary — and per act — title, option accepted, options refused, adventure, boss, the fallen, defeats, NPCs met, what was learned (`knows_*` as prose), gold spent per location, items bought. It is written when a scenario closes; writers see a provisional entry for the one in progress (reading rules: docs/generation.md).

**Town state** is the campaign's memory of a town. Writers' `town_state_delta` **overrides** (≤ 2 locations each) replace location descriptions and scenes from then on — the burned waystation stays burned. When a scenario ends, the run's custom flags (not standing, bookkeeping, `knows_*` or `deferred_*`) are stored under that town; a later scenario there restores them as `town:<flag>` and re-marks the residents already met. `talked` is reserved.

**The day counter** starts at 1 and advances by 1 per ride-out, by the interlude's `days` and by the chosen hook's `days`. Chronicle entries carry the day; each ledger entry records its scenario's days.

**Scenario end.** When Act III's boss falls, the ledger notes the boss and the fallen and the interlude planner is queued at once. Spoils → act-end level-up → the ledger entry closes as a victory → `scenario_complete` save (the campaign is now `between`) → the **scenario-end menu**: **New Game** / **Continue Campaign** / **Quit**. Quit leaves the campaign for Load to reopen; Continue Campaign waits for the planner (a failed one is re-queued).

**The interlude** is the victorious town, act-shaped with no quest. The planner's one call writes an arrival, dialogue trees, flavour and topics in the light of what happened (quest hooks forbidden, payment hooks such as `give_gold` allowed), a `town_state_delta`, the days since the victory, and **three hooks**. The party arrives in the closing act's town with the delta and days applied: shops open with fresh stock, no spoils, no Start Adventure, the quest card reading *Between scenarios*; an `interlude` save is written.

**Hooks** are `{kind: stay | neighbour | new, town_id | town_seed, narration, bridge, days, foreshadow}`. The narration is the rest-screen card (3–5 sentences, second-person narrator); the bridge is the arrival the next arc must honour; up to two `foreshadow` exchanges per hook join the interlude's NPC topics, so the party hears every road in town before the rest screen offers it. Only an NPC **without** an interlude tree may carry one, since an NPC with a tree speaks the tree and offers no topics (§D24-5.1; roadmap M5.3 would merge topics into trees). At least one hook stays and at least one leaves; a `neighbour` names one of this town's worldbook neighbours; a `new` hook carries a seed (a name and a line) anchored to a known town. The planner proposes premises, never outcomes, and never touches hero backstory (it receives no lore).

**The rest screen** opens from the inn's rest or the console's *The road ahead*: the three hook cards (narration, destination, days), a fourth card — "You decide to [stay in ‹town›] / [travel to ‹any worldbook town›] / [somewhere new: name + one line], but…" with a free-text note — and each hero's situation editor. *Not yet* returns to town; nothing is committed until a hook is chosen, as a party-wide confirmation ("Take this road — ‹destination›?"). Then:
1. full heal; the hook's days are added (the custom card covers 7); the bridge closes the scenario's journal; `hooks_chosen` is saved;
2. for `new`, the town generator writes the town and its worldbook entry beside the anchor;
3. the arc writer writes the next arc for the destination from the ledger, the party's layers, the world block, the hook and the note;
4. the scenario closes: custom flags stored as the left town's state, all flags cleared, the destination's town state applied, the old cast and places gone, a fresh loot lexicon, the scenario counter up;
5. Act I materializes as in a new game (`act_start` save); its writer also reads the hook, bridge and note, so the arrival honours the road. Levels, points, gold, gear and chronicles carry on.

**Live identity.** On every load of a campaign save (Load → Continue or an older save), and when an in-session Continue starts the next scenario, each hero's copy is refreshed from the character file first. **Replaced:** the deck and the identity fields — name, description, portrait, animations, colours, row, type line, Skill, Ultimate, ability flavour, brief, default situation, lore, combat lore. **Kept:** everything else (HP, starting mana, starting cards, bought Power, points, level, gear; purse, pools and HP live on the run), including the **keyword and attack mode**, which the points-buy prices (the keyword's cost; the mode's base Power). A file whose keyword or mode differs gets a splash notice, never a free respec (ruled 2026-09-25, roadmap M1.7). A starting-mana pip in a colour the file no longer has is re-rolled to its colours. The load splash names cards the deck lost or gained and any re-roll; a missing file leaves the copy untouched. Within play the validator still locks these (§13.2).

*Sources: §D24-1–§D24-6, §D24-7.4, §D24-8.1, §D24-8.2, §D24-10 · scenario `_ledger_entry`, `note_boss_death`, `begin_interlude`, `choose_hook`, `_custom_hook`, `begin_next_scenario`; scenario_content `validate_interlude`; jobs `InterludeJobRunner`; session `continue_campaign`; app `_continue_sync`; runs `load_scenario_save`; content `refresh_instance`.*

### §14.7 The worldbook

The worldbook is the shared book of what a traveller knows about each town: tracked content in `content/world/`, one JSON per town plus `regions.json`, read by every campaign.

```
content/world/<town_id>.json
{ kind: "world_entry", town_id, name, region_id,
  gist,                            # one paragraph, ≤ 160 words
  notable: [ … ],                  # ≤ 6 short lines
  neighbours: [ {town_id, how} ],  # ≤ 4 written by the entry itself
  added_by: generate_town | import | backfill | scenario:<run_id> }

content/world/regions.json  →  { regions: [ {id, name, gist} ] }
```

- **Every town has an entry.** The town generator writes town and entry in one step, placed beside an anchor (the region, the anchor and its neighbours are its only world input). A town without one is a warning row in Options → World, never a crash: writers get no neighbours for it, and the planner proposes only stay and new hooks.
- **Append-only in play.** Play never overwrites an entry; only Options → World edits one (name, region, gist, notable, neighbours).
- **Neighbours are symmetric:** a neighbour must already be in the book, and writing an entry adds the reverse edge (same `how`) to each neighbour.
- **A region is named once:** a new town joins a region or founds one with its gist; a region named but never founded is created with an "(unwritten)" gist.
- **Brief on purpose:** what a traveller knows — no history, no plot. What happened in a town lives on the campaign (§14.6).
- **Nobody reads the whole book:** the act writer gets this town's entry; the arc writer and interlude planner add its neighbours' one-liners; the town generator gets the region and the towns it is placed beside.

*Sources: §D24-8.3, §D24-9.1 · world `validate_entry`, `append_entry`, `update_entry`, `context_for`, `placement_context`; scenario_content `save_town`; scripts `backfill_worldbook.py`.*

---

## §15 Glossary

Current meanings only. The § points to the full rule.

| term | meaning |
|---|---|
| **Act** | One town visit plus one adventure: a scenario's story beat (§14.1). |
| **Action** | A thing on the stack: a spell or ability being resolved (§5). What a character *does* on its turn is a **verb** (§4.6). |
| **Adventure** | Three phases fought in sequence through one place. HP carries between phases, and the party levels up between them (§12.3). |
| **Adventure job** | The persisted generation job behind Start Adventure: `idle → pending → ready \| failed` (§14.5). |
| **Affix** | A rider on forged or stocked gear, from the affix table (§13.5). |
| **Affliction** | Poison or regen counters, which tick at Upkeep (§4.11). |
| **Ally token** | A created, autonomous allied creature with its own intent. You help it; you don't command it (§9.6). |
| **Arc** | A scenario's generated spine: villain, stakes, three act outlines, cast and places (§14.5). |
| **Attack mode** | `melee` or `ranged`. It sets reach and the free base Power (§4.7, §10.1). |
| **Basic attack** | The Attack verb: deal your current Power to one reachable enemy (§4.7). |
| **Boss** | An enemy immune to removal until its execute window. It enrages there and declares two intents per round (§9.4–§9.5). |
| **Boss dials** | `enrage_round` (a timed enrage) and `neglect` (grows while unhurt), required on generated bosses (§9.5). |
| **Break (concentration)** | Ending a held channel: a hit of ≥ 25% max HP, incapacitation, or a voluntary drop (§8.1). |
| **Bridge** | The prose that carries a campaign's party to its next scenario; Act I's arrival honours it (§14.6). |
| **Brief / lore / combat lore / situation / chronicle** | The character layers: player-written identity, player-written background, how the hero fights, where they stand in this campaign, and what the engine recorded them doing (§10.3). |
| **Campaign** | One fixed party playing scenario after scenario in one continuity (§14.6). |
| **Capacity** | A character's colour-locked mana slots (§4.4). |
| **Category** | The veiled label an intent shows: threat, row assault, party assault, spellcraft, interference, gathering, summon, support, manoeuvre (§9.2). |
| **Channel** | A sustained enchantment a character holds by reserving its mana (§8.1). |
| **Charge** | A typed counter. On an enemy it is the visible **windup** toward a hidden detonation (§4.11, §9.9). |
| **Chassis** | An enemy's body preset: HP, Power, attack, home row (§9.1). |
| **Combat Ability** | An ability whose verbs deal damage. It is derived from the verbs, never authored, lands in the combat lane, and can be Mitigated when single-target (§4.8, §9.9). |
| **Combat lane / spell lane** | The damage lanes that `prevent`, `protection` and `amplify` name (§4.7). |
| **Component** | One rule in an enemy's mind: archetype, timing, condition, priority, cooldown, verbs, target rule (§9.1). |
| **Consumable** | A belt item dealt as an extra, mana-free card every encounter until it is used (§13.4). |
| **Content store** | A run's immutable, hash-addressed store of everything it generated. Saves point into it (§14.2). |
| **Continue** | Load the newest save by timestamp (§14.2). *Continue Campaign*: go on to the interlude after a scenario (§14.6). |
| **Corpse** | What a dead non-token enemy leaves on its row. Only `control`, `exile` and `consume_corpse` touch it (§9.7). |
| **Counter** | A verb that cancels a matching stack item (§5.4). *Counters*: permanent +1/+1 (§4.9). *Typed counters*: poison, regen, charge (§4.11). |
| **Curve-up** | +1 mana capacity each Upkeep from round 2 (§4.4). |
| **Day** | The campaign day counter (§14.6). |
| **Defend** | Half of the pair: temporary HP equal to base Power (§4.8). |
| **Delay** | Move to the end of the party turn order for the rest of the fight (§4.6). |
| **Effective HP** | `hp + temp_mod`. Every lethality check reads it (§4.3). |
| **Effective level / potential** | The level budgets and item tiers read: *earned* points as a continuous level, plus a gear bonus (§10.2). |
| **Encounter** | One fight: an enemy pool plus a roster for each party size (§12.1). |
| **Enrage** | A boss's one-time eruption at ≤ 25% HP or at its `enrage_round` (§9.5). |
| **Execute / execute window** | Removing an enemy outright. A boss can be executed only at ≤ 25% effective HP (§9.4). |
| **Fizzle** | A targeted effect doing nothing because its target became illegal before it resolved (§6). |
| **Freed verb** | A verb a keyword lifts out of the turn: vigilance frees Attack, defender frees Defend, haste frees Move (§4.6). |
| **Gauge (ultimate gauge)** | Raw points toward the charge cost `100 + 20·(level−1)`. The Ultimate needs it full (§4.12). |
| **Grudge** | An enemy target rule that hunts a hero class or type (`hero_class:` / `hero_type:`) (§9.3). |
| **Hook** | Two meanings. A *dialogue hook* is a closed-vocabulary effect of a dialogue choice (§14.4). A *campaign hook* is one of the three proposed premises for the next scenario (§14.6). |
| **Incapacitated** | A player-character at 0 effective HP: out of the fight, not dead (§4.3). |
| **Interlude** | The victorious town after a scenario, before the next one is chosen (§14.6). |
| **Interposition** | Stepping into the reach of a melee "swing" so it redirects onto you (§4.10). |
| **Intent** | An enemy's declared, veiled next action (§5.2, §9.3). |
| **Keyword** | A named rule a creature carries: flying, reach, haste, hexproof… (§7). |
| **Layout** | An encounter's roster for one party size (§12.1). |
| **Ledger** | The campaign's structured memory of each scenario and act, shown to writers as `# PREVIOUSLY` (§14.6). |
| **Level** | For a card, its converted cost. For an enemy, its fixed power tier. For a character, the level derived from points spent (§3, §9.1, §10.2). |
| **Loadout** | A character plus its cards, and gear on a campaign's copy (§10). |
| **Lockdown** | Enemy control pieces (stun, taunt, silence, hamstring, discard, sap, drain-ult, strip-reach), budgeted per layout (§9.9). |
| **Materialization** | An act's generated town portion: quests, arrival, dialogue, flavour (§14.5). |
| **Minion** | Any non-boss enemy; every removal works on it (§9.4). |
| **Mitigate** | The free defensive reaction: reduce an incoming attack or single-target Combat Ability by ceil(Power ÷ 2), for yourself or an adjacent ally (§4.8). |
| **Move** | Half of the pair: reposition to any row (§4.10). |
| **Neglect** | A boss dial: +N/+N for each round the enemy goes unhurt (§9.5). |
| **Objective** | An alternate win or loss condition: survive, waves, race, deadline (§12.2). |
| **The pair** | Defend and Move. Either or both is a full turn (§4.6). |
| **Pass / Pass-All** | Decline a reaction window. Pass-All does it for one character until the turn-tracker step changes (§4.6, §5.3). |
| **Phase** | One of an adventure's three fights (§12.3). The engine also uses `phase` for the steps inside a round (§4.2). |
| **Player / player-character** | A human, and one of the heroes a human controls (§0). |
| **Positional intent** | An enemy intent aimed at a row, not a name. Dodge it by leaving the row (§4.10, §9.9). |
| **Power** | Attack value; the basic attack deals current Power (§4.7). |
| **Primed** | A hero at ≥ 80% gauge, or holding an amplify / double_next priming. Enemies value primed heroes highly (§4.12). |
| **Pump / wound** | Temporary +X/+X / −X/−X layers (§4.9). |
| **Quest option** | One of the 2–4 quests an act offers. Accepting one closes the others (§14.5). |
| **Reaction / reaction window** | A free response while something is on the stack. Each player-character gets a window before anything resolves (§5.3). |
| **Register** | The Rebalance Register of tunable numbers, `T-NN` ([balance_register.md](balance_register.md)). |
| **Relentless** | An enemy-only keyword: its intents never redirect (§7, §9.9). |
| **Reserve zone** | Where undeployed wave and reinforcement bodies wait (§12.2). |
| **Round** | One full cycle: Upkeep, Players, Allies, Enemies, End (§4.2). |
| **Row** | Front, Mid or Rear on each side (§4.1). |
| **Run** | A party, its options, and its branching save tree (§14.2). |
| **Scenario** | An arc of three acts against one villain, run from one town (§14.1). |
| **Skill** | A hero's authored once-per-encounter ability, sorcery or channeled (§4.12). |
| **Spoils** | Boss drops, forged at the act tier + 1 (§13.5). |
| **Stack** | Where actions resolve, last in first out, with per-character reaction windows (§5). |
| **Stance** | A channeled form that removes or replaces the evergreen verbs (§8.2). |
| **Standing flag** | A dialogue flag the runtime sets itself, such as `defeated_once` or `act_n_complete` (§14.4). |
| **Stirring** | A corpse under `rises` that has not yet revived (§9.7). |
| **Stun** | The enemy skips its next intent, or the hero's next main phase does nothing (§5.2, §4.6). |
| **Swing / pursues** | Whether a telegraphed intent can be walled (redirectable) or follows its target (§4.10). |
| **Targeted / chosen / all** | How an effect reaches creatures. Only *targeted* is stopped by hexproof and can fizzle (§6). |
| **Temp HP (`temp_mod`)** | The temporary layer: buffers soak damage first, wounds never soak (§4.9). |
| **Topic** | A resident's `{ask, reply}` exchange (§14.3). |
| **Town state** | The campaign's memory of a town: overrides, stored flags, who was met (§14.6). |
| **Turn** | A character's main phase: one turn-spending verb, or the pair (§4.6). |
| **Turn-spending verb** | Attack, Cast, Skill or Ultimate: taking one *is* the turn (§4.6). |
| **Ultimate** | A hero's authored once-per-encounter sorcery, usable on a full gauge (§4.12). |
| **Veil (veiled intent)** | An intent shows only its category and target until it executes (§5.2, §9.2). |
| **Vendor** | The one resident of a shop who sells (§14.3). |
| **Verb** | Two meanings. An *effect verb* is an effect primitive (§11). A *turn verb* is Attack, Cast, Skill, Ultimate, Defend or Move (§4.6). |
| **Worldbook** | The shared, append-only book of what a traveller knows about each town (§14.7). |
