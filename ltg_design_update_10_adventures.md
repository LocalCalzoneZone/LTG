# Langelier Tactical Game (LTG) — Design Update 10: Adventures — the Three-Act Run

**Status:** canonical design, **not yet built**. Where this document and prior documents (GDD, Updates 01–09) disagree, this document wins. Updates 08 and 09 (Tiers One and Two) are implemented and assumed throughout: veiled intents, afflictions and charge, Skills & Ultimates and the gauge, corpses and `control`, stances, forced movement, and boss fury are live rules here.

**Purpose.** One system: the **Adventure** — a three-act run against a single theme, with HP as the currency that spans the whole thing and an ephemeral level-up between acts. Adventures run **alongside** Encounters; the Encounter (one party, one fight) remains exactly as it is. Nothing in this update changes single-encounter play.

**Terminology.** An adventure's segments are **Acts** (Act I, II, III). The word *round* remains reserved for the combat turn cycle (GDD §4.2) — an act *contains* many rounds. This document never uses "round" to mean an act.

**All magnitudes are playtest starting values**, collected in the Rebalance Register deltas (§D10-8).

---

## D10-1. What an adventure is

An **adventure** is three thematically linked encounters — the **acts** — fought in sequence by one party, representing progress through a place: guards at the gate, knights in the courtyard, the tyrant in his throne room. One faction, one arc, escalating stakes.

- **Difficulty escalates by design**: act N is budgeted against a party of **level N** (§D10-4.2), so the standard encounter budget formula does the ramping.
- **Scenes progress**: each act carries its own `scene` (the battle backdrop) and the three must read as movement through one location, not three unrelated arenas.
- **Act III always ends in the boss** — exactly one `is_boss` enemy, the adventure's highest-level enemy. **Acts I and II may each field one mini-boss** (§D10-4.3) — the generator's wiggle room, never an obligation.
- **The party carries forward** — HP, hand, library, and half the ultimate gauge cross act boundaries (§D10-2); everything else resets.
- **Between acts, every character levels up** — +30 points on the same points-buy the Deckbuilder uses, bankable, irreversible, and local to this adventure (§D10-3).
- **Defeat ends the adventure.** No checkpoints, no mid-act retries: the run is over, with an immediate offer to restart from Act I. Adventures are persistent content — pick the party and try the whole thing again, any time. (Mid-run save/resume is explicitly deferred: these are single-sitting, rogue-like runs; persistence is a later, longer build.)
- **Victory** is winning Act III.

The combat engine is untouched by all of this: each act is an ordinary encounter to the engine. The adventure — act sequencing, carry-over, level-ups — lives entirely in the game server's session layer and the content pipeline (§D10-7).

---

## D10-2. Carry-over: what crosses an act boundary

Applied when an act is won, in this order: end-of-encounter cleanup first, then the carry rules, then the level-up (§D10-3), then the next act's setup.

| what | across acts |
|---|---|
| **HP** | carries — then every character starts the act at **max(current HP, 25% of max HP)**. One rule for everyone: the incapacitated stand back up at the floor, and the barely-alive are lifted to it. There is no other healing between acts. |
| **Hand** | does **not** carry as a hand *(amended after the first playtest — carrying the literal hand let cards accumulate)*: it is shuffled into the library at the boundary, and the next act opens on a fresh hand (below). |
| **Library** | carries; the **hand and graveyard are shuffled into it** — the full deck, reassembled. |
| **Graveyard** | emptied into the library (above). Spent cards, countered cards, dropped channels — all come back. |
| **Player-exiled cards** | stay exiled. Exile is forever, even for your own cards. |
| **Held channels** | **all drop at act end** — no break event, no break triggers, no released-mana window; the cards go to the graveyard (and thus shuffle back). |
| **Skill / Ultimate uses** | **reset** — once per encounter means once per act. |
| **Ultimate gauge** | carries at **50%**: `floor(gauge × 0.5)`. A 100-gauge finish opens the next act at 50. |
| **Encounter-duration statuses** | all clear: poison, regen, and ±1/±1 counters; encounter-duration keyword grants; taunts, stuns, wounds, temp HP (most of these expire naturally anyway). |
| **Mana** | pool and capacity **reset to base** — the base the level-up may just have raised — and the curve-up restarts at turn 1 of the act. Ramp gains are gone; reserved mana is moot (channels dropped). |
| **The fresh hand** | at each act's start, every character **shuffles up completely and draws a new hand equal to their starting-cards stat**. This is what keeps the starting-cards stat alive mid-adventure (§D10-3.2): buying it raises every future act's opening hand. |

Corpses, stirring corpses, controlled enemies: none can exist at act end (victory requires every enemy defeated; stirring and controlled enemies block victory by rule, D9-1), so nothing crosses.

---

## D10-3. The level-up

### D10-3.1 The rules

Between acts — after the victory splash, before the narrative splash (§D10-6.3) — **every character must level up**: Act I → level 2, Act II → level 3.

- **+30 points** per level, added to the character's unspent pool.
- **Banking is legal**: spend any amount including zero, keep the rest (spend 25 now, have 35 next level). Confirming the screen is what's mandatory, not spending.
- **Previous purchases are locked.** The build panel's floor is the character as it entered the screen — nothing bought at creation or a previous level can be sold back.
- **Colours are immutable.** Identity never changes mid-adventure. New mana capacity bought at level-up gets its colour lock chosen on this screen, within the existing identity.
- **Keyword: one, total, ever.** A character who took None at creation may buy their single keyword at a level-up; a character who has one may never buy another. The creation price list and the creation ban list (protection, hexproof, indestructible, deathtouch, infect) apply unchanged.
- **Power cap scales with level**: total bought Power ≤ **2 × character level** (creation = level 1 = the existing +2 cap; level 2 allows +4 bought; level 3, +6). Melee/ranged base values unchanged.
- **HP purchases heal**: +2 max HP is also +2 current HP, exactly as +1/+1 counters land. This is the adventure's only purchasable healing — ~2.5 points per HP, a deliberate knob.
- **Everything is adventure-local.** The leveled build exists only inside this run; the saved character profile never changes. The Deckbuilder remains creation-only (Update 05's stance is preserved — the escalating-progression UI lives in the game, not the authoring tool).

### D10-3.2 What the stats mean mid-run

All purchases take effect at the next act's setup: HP (immediately, per above), mana capacity (the new base the reset returns to), Power (and with it Mitigate, `ceil(Power ÷ 2)`), and starting cards — which mid-adventure is the **act-start hand**: the fresh hand drawn at each act's start (§D10-2). Buying it raises every future act's opening hand, not a dead number.

### D10-3.3 The level-up screen

Character portrait full-height on the left; on the right, the **same points-buy panel the Deckbuilder uses** (presets hidden — presets are a creation convenience), in **locked-baseline mode**: decrement stops at the entering build, colours read-only, and three numbers always visible — **locked** (the entering build's spend), **new** (+30), **banked** (carried remainder). A single Confirm per character.

**Multiplayer gate:** the game only starts with every character claimed, so there are no orphans. Each client confirms the level-up for **each character it controls** — a player running two characters confirms twice. The next act begins only when every character is confirmed. The screen is per-seat; you do not see or edit another player's build choices, only their confirmed/waiting status.

---

## D10-4. The adventure content object

### D10-4.1 Schema

```
adventure = {
  id, name,
  flavor,                       # one-line pitch, shown in the New Game list
  acts: [                       # exactly 3, in order
    {
      narration,                # 1 short paragraph, second person, present tense
      ...encounter              # the full standard encounter object:
                                # name, scene, enemies[], layouts{1–4}, tokens{}
    },
    …
  ]
}
```

Each act embeds a **complete, standard encounter** — same enemy schema, same per-party-size `layouts`, same `scene`, validated and persisted through the **same save gate** an encounter takes, act by act. The adventure adds only the wrapper (name, flavor) and per-act `narration`.

**Adventure-level validation** (on save, authored or generated):

- exactly 3 acts, each independently valid as an encounter (layouts 1–4, minimum bodies, every enemy described);
- **Act III contains exactly one `is_boss` enemy**, and it is the highest-level enemy in the adventure;
- **Acts I and II contain at most one `is_boss` enemy each** (the mini-boss), each strictly lower level than Act III's boss;
- every act's `narration` is present and non-empty.

### D10-4.2 Budgets: level is the ramp

Act N is budgeted as a standard encounter for a party of **average level N**: the unchanged formula `2 × party_size × N × difficulty` (T-37/T-38), with the adventure's single difficulty (easy / standard / hard) chosen at generation and applied to all three acts. The per-difficulty enemy-HP multiplier (T-40) applies per act as always. Minimum bodies (2 × party size, T-41) applies per act, per layout.

The ramp is therefore steep by construction — acts budget at 1× / 2× / 3× the level-1 number while the party's own growth is +30 points on a 70-point base per act, *and* the party carries its wounds. That compound escalation is the intended shape of a run; the per-act budget derivation is the tunable if playtest says otherwise (T-62).

### D10-4.3 Bosses and mini-bosses

A **mini-boss** is mechanically a boss, full stop: `is_boss: true`, removal-immune until the execute window, enrage, post-enrage fury (two intents, T-54), 2.5× budget at its level, counts double toward the act's Level total. The *only* differences are placement and scale: it appears in Act I or II, it is thematically distinct (the gate-captain, not the king), and its **level is strictly below the Act III boss's**. One per act, never required — variety, not formula.

---

## D10-5. LLM generation: one call, one arc

`POST /api/adventures/generate` mirrors the encounter path with these changes:

- **One request generates the entire adventure** — all three acts, their scenes, narrations, enemies, and layouts, in a single JSON reply. Coherence by construction: one faction, one location traversed, three scenes written together as a progression.
- **The request sets a very high `max_tokens`** (T-63; the current `_chat` sets none and inherits model defaults — three full encounters plus prose will truncate without it). Truncated JSON is treated as any other parse failure: repair loop.
- The prompt extends the encounter prompt with an **adventure block**: the act structure; per-act budget lines computed at party level 1 / 2 / 3 (each with the four party-size layouts, exactly as today's per-size lines); the boss constraints of §D10-4.1; scene-progression guidance ("three stations of one place — outside it, inside it, at its heart"); and the narration spec — **second person, present tense**, one short paragraph per act, describing the party arriving into that act's scene ("You push through the splintered gate. Beyond, the courtyard…"). Act I's narration is the adventure's opening.
- The existing repair loop applies whole: parse → per-act HP scaling → per-act layout checks → adventure-level validation (§D10-4.1) → save; any failure re-prompts the model with the engine's own error, up to the retry limit.
- Difficulty, party scoping, and the player's one-line theme note work exactly as encounter generation.

Standalone encounter generation is untouched.

---

## D10-6. UI & flow

### D10-6.1 Options → Adventure

A new Options panel, sibling to Encounters, mirroring its shape: the list of saved adventures (name, flavor, act names), **Generate adventure** (party, difficulty, theme note), hide/delete, and art controls (§D10-6.4). Acts open for inspection and editing in the **existing encounter editor**, one act at a time; adventure-level fields (name, flavor, the three narrations) are edited in the Adventure panel itself. Saving an edited act re-runs the act's save gate and the adventure-level validation.

### D10-6.2 The New Game modal

Three columns, one selection, one button:

- **Left — Characters:** full-height portraits in a scrollable pane; pick the party (order = seat order, as today).
- **Middle — Encounters:** the existing encounter list.
- **Right — Adventures:** the adventure list.
- Selecting an encounter deselects any adventure and vice versa — the selection *is* the mode. **Start Game** at the bottom starts whichever is selected. No other mode switch exists.

### D10-6.3 The between-acts flow

On winning Act I or II:

1. **Victory splash** — the act is won (the existing victory treatment, act-labelled: "Act I — clear").
2. **Level-up screen** (§D10-3.3) — gated on every character's confirmation.
3. **Narrative splash** — the next act's `narration` (second person, present tense) over that act's scene art as it exists so far; a single Continue.
4. **Next act's combat** begins: carry-over applied (§D10-2), fresh setup, turn 1.

On winning Act III: the adventure victory splash. On defeat in any act: the defeat splash, with **Restart from Act I** (same party, fresh state, level 1) beside the usual exit to the New Game modal.

### D10-6.4 "Generate all art" — the art queue

Beside the existing **Paint the Battlefield Backdrop** button, in both the Encounter and Adventure art controls, a new button: **Generate all art**.

- Pressing it builds a queue of every missing image — the backdrop (if absent) plus every enemy without a portrait — and runs it **sequentially**: one generation in flight; each completion (success or failure) fires the next. A failure is logged and skipped, never blocks the queue.
- **For adventures, the queue covers all three acts in order**: Act I's backdrop and enemies first, then Act II's, then Act III's — so a party can start playing Act I while Acts II and III paint in the background. Completed images broadcast to connected clients as they land, exactly as single-image generation does today.
- The button shows progress (`n / m`) while the queue runs, and is idempotent — pressing it again queues only what is still missing. Enemy art remains keyed by pool id (clones share their design's image).

---

## D10-7. Engine, server & schema touchpoints (for the implementation pass)

The **combat engine is not modified**. Every act is an ordinary encounter to it; adventures are a session-layer and content-layer feature.

| system | where |
|---|---|
| adventure schema + validation | `apps/game-server/ltg_game_server/content.py` — `save_adventure` wrapping the per-act `save_encounter` gate + the §D10-4.1 adventure checks; registry + hide list beside encounters |
| adventure session state | `session.py` — adventure id, act index, and the **carry-state builder**: on act victory, snapshot each character's `{hp, all cards (hand+library+graveyard), exiled, gauge, spent-points build}`; on next-act start, compose the new `GameState` via the existing `compose_spec`/`state_from_dict` path with the carried cards fully reshuffled, a fresh hand of starting-cards drawn, HP floor `max(cur, 25% max)`, gauge `floor(×0.5)`, and skill/ult flags fresh |
| level-up | server-side prompt state per character (entering build, +30, banked, confirmed flag); validation of the delta against §D10-3.1 (locked floor, colour immutability, keyword ≤ 1 total, Power ≤ 2×level, price list per Update 05); the engine consumes the resulting **stat block**, as it always has |
| generation | `llm.py` — adventure prompt block, per-act budget lines at levels 1/2/3, **explicit high `max_tokens` on the request** (T-63), adventure-level repair loop |
| art queue | `art.py` + the art API — a per-content sequential job queue (`generate_all`), skip-on-failure, progress events over the session/registry channel; adventure queue ordered Act I → II → III |
| New Game modal | `apps/game-ui` `NewGameModal.tsx` — three-column layout, exclusive selection, portrait pane |
| Options → Adventure | new panel beside the encounter management UI; acts open in the existing `EncounterEditor` |
| between-acts screens | victory splash variant, the level-up screen (portrait + the Deckbuilder points-buy panel in locked-baseline mode — port or share the component), the narrative splash |
| API | `POST /api/adventures/generate`, `GET/POST/DELETE /api/adventures…`, art endpoints per act, and the WS additions for the level-up gate (`level_up` prompt, `confirm_level_up`) and act transitions |

Regression spine: single-encounter play must be byte-identical — every adventure behaviour is gated on the session having an adventure, and the §A/§C scripted scenarios never do.

---

## D10-8. Rebalance Register deltas *(amends Update 04 §F-10 and successors)*

| ID | value | sets |
|---|---|---|
| T-57 | 30 | points granted per level-up |
| T-58 | 50% (floor) | ultimate-gauge carry across acts |
| T-59 | 25% of max HP | act-start HP floor, `max(current, floor)` |
| T-60 | 2 × character level | bought-Power cap (supersedes the flat +2, which is its level-1 case) |
| T-61 | 3 | acts per adventure |
| T-62 | act N budgets at party level N | the adventure difficulty ramp |
| T-63 | very high, explicit (e.g. the model's maximum) | `max_tokens` on adventure-generation requests |

Update 05's designed-but-unbuilt escalating leveling curve (§P-5 onward) is **superseded** by the flat T-57 grant for adventure-local leveling; profile-level character progression remains unbuilt and out of scope.

---

## D10-9. Glossary deltas *(amends GDD §13)*

- **Adventure** — a three-act run: three thematically linked encounters fought in sequence by one party, with carry-over (§D10-2) and between-act level-ups. Persistent, replayable content alongside Encounters.
- **Act** — one encounter within an adventure. Never called a "round" — that word belongs to the combat turn cycle.
- **Mini-boss** — a full-package boss (`is_boss`, enrage, fury, 2.5× budget) fielded in Act I or II, thematically distinct from and strictly lower level than the Act III boss.
- **Carry-over** — the act-boundary rules: HP floored at 25% of max, hand + library + graveyard shuffle up into one fresh library, a new hand of starting-cards is drawn, exile stays, channels drop silently, uses reset, gauge halves, encounter statuses clear, mana resets to (possibly upgraded) base.
- **Level-up (adventure-local)** — +30 bankable, irreversible points per act transition on the creation points-buy; colours immutable, one keyword ever, Power cap 2 × level; never saved to the character profile.
- **Act-start hand** — the mid-adventure meaning of the starting-cards stat: at each act's start, shuffle up completely and draw a fresh hand of that many cards. *(Supersedes the original "card floor" draw-up-if-below rule — first-playtest amendment.)*
- **Banked points** — level-up points deliberately left unspent, carried to the next level-up.
- **Narration (act)** — the act's second-person, present-tense opening paragraph, shown on the narrative splash before its combat.
- **Art queue** — the sequential generate-all-art job: every missing backdrop and portrait, one generation at a time, acts in order.

---

## D10-10. Open questions

- **[OPEN] Mid-run persistence.** Deferred by decision: adventures are single-sitting runs; a between-acts checkpoint is the natural first step when a longer build wants it.
- **[OPEN] Longer forms.** Five-act adventures, or chained adventures, are a content-shape question on top of this machinery — nothing here hard-codes 3 beyond T-61 and validation.
- **[OPEN] Card rewards.** Level-ups grant stats only. A between-acts card reward (add a card to the run's library) is the obvious future enrichment; it needs a rarity/power policy before it exists.
- **[OPEN] Profile-level progression.** Explicitly out of scope, again: leveling lives and dies with the adventure. If persistent character growth ever lands, it is a separate design update reconciling with Update 05.
