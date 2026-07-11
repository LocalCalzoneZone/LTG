# Langelier Tactical Game (LTG) — Design Update 09: Tier Two — Corpses & Necromancy, Stances, Forced Movement & Row Blasts, and the Boss Endgame

**Status:** canonical design, **not yet built**. Where this document and prior documents (GDD, Updates 01–08) disagree, this document wins. Update 08 (Tier One) is implemented and this document assumes it: veiled intents, poison/regen/charge, infect, Skills & Ultimates, and auto-pass are live rules here, including the playtest ruling that healing sheds poison counters (§D8-2.1).

**Purpose.** Four systems from the Tier Two review, plus one recorded deferral:

1. **Corpses & the necromancy suite** (§D9-1) — the dead stay on the battlefield; `destroy` and `exile` finally differ; corpses become targets; a new `control` primitive covers both mind control and raise-dead; and the generator gains an undead faction archetype.
2. **Stances** (§D9-2) — a channeled effect that *replaces* the four main abilities (attack, Defend, Mitigate, Move) while held: each is unchanged, removed, or swapped for an authored action.
3. **Forced movement & row blasts** (§D9-3) — a `move` effect that shoves creatures between rows, and row-scoped area targeting (a row, a target plus its row, a target plus adjacent rows). Position becomes a live, every-round decision for both sides.
4. **The boss endgame** (§D9-4) — after enrage, a boss declares and executes **two intents per round**.
5. **Deferred:** alternate encounter objectives (§D9-5) — reviewed and explicitly held for a later update.

**All magnitudes remain playtest starting values**, collected in the Rebalance Register deltas (§D9-8).

---

## D9-1. Corpses & the necromancy suite

### D9-1.1 The corpse rule

When a **non-token enemy dies** — by damage, poison, a `destroy`, a boss executed in its window — it leaves a **corpse** on the row where it died. A corpse is an **object, not a creature**:

- It has an identity (name, Level, Power at death, max HP, row) but no HP, no intents, no keywords in effect, and it never acts.
- It cannot be attacked, damaged, healed, pumped, stunned, or taunted — creature-facing effects cannot resolve on it. Only **corpse-legal** effects touch it: `control` (§D9-1.4), `exile` (burn the body), and enemy necromancy verbs (§D9-1.6).
- It persists for the rest of the encounter unless consumed (raised) or exiled.
- **Who leaves corpses:** non-token enemies only. **Tokens never leave corpses** (either side — this is the anti-loop rule: raised undead cannot be re-raised). **Player-characters never die** (they are incapacitated, GDD §4.3) and so never leave one. **Bosses do leave a corpse** — but boss corpses are inert to `control`, absolutely (§D9-1.4).

### D9-1.2 `destroy` vs `exile`, at last

This is the differentiation the two verbs have been waiting for:

| verb | result |
|---|---|
| **destroy** (and death by damage/poison) | defeated → **leaves a corpse**; death triggers fire; necromancy can find it |
| **exile** | defeated → **no corpse, ever**; no death triggers; nothing to raise |

**Exile also works on corpses**: an `exile` effect may target a corpse to remove it permanently — denying the necromancer, cancelling a stirring rise (§D9-1.5). Against an undead faction, exile stops being a luxury and becomes the hygiene spell.

**Victory is unchanged**: a corpse is a **defeated** enemy (zone `graveyard`, now with a battlefield marker). The fight ends over a field of bodies just fine. The exceptions that keep a fight alive are the *stirring* corpse (§D9-1.5) and the *controlled* enemy (§D9-1.4) — both are "not yet defeated" states, listed in the zone-table amendment (§D9-1.7).

### D9-1.3 Corpses as targets (schema)

Creature-class target descriptors gain a **state** axis:

```
target: { class: "creature", mode, side, exclude_self?, targeted?,
          state: "living" | "corpse" | "any" }    # default "living"
```

- `state` defaults to `"living"` — every existing card is unchanged.
- Validation: damage/heal/pump/wound/poison/regen/stun/taunt and other living-creature verbs require `living`; `control` accepts any state; `exile` accepts any state.
- **Corpses are never hexproof or shrouded** (keywords belong to the living), but a `targeted` corpse effect still re-checks at resolution and **fizzles** if the corpse was consumed or exiled in response.

The **conditional container** (§X-2 / Update 07) gains a matching `target_property`:

```
conditional: { condition: { kind: "target_property", property: "is_dead" }, ... }
```

`is_dead` is true iff the resolved target is a corpse. This is what lets one card read "…if the target is dead, do X instead" — and it is exposed in the **Deckbuilder's effect editor** beside `has_keyword` and `side`.

### D9-1.4 The `control` primitive

One new leaf effect, the heart of the suite:

```
control { target,                      # creature, state "any" typical; enemies only
          duration: {turns: X} | "encounter" }
```

`control` makes the target into an **allied token** on the caster's side. Its flavour is its target's state:

- **On a living enemy — mind control.** The enemy leaves the enemy side and fights for the caster's party for the duration. It keeps its current HP, max HP, Power, and keywords; it **loses its components and intents** — a dominated mind is a blunt instrument. While controlled it is a full party-side combatant: enemies may attack it, allies may heal and pump it.
- **On a corpse — raise dead.** The corpse is **consumed** and an **undead token** rises on its row, on the caster's side: the corpse's Power and attack mode, **half its max HP** (rounded down, min 1 — the same 0.5 default as `revive`, register T-52). When the duration ends the undead **crumbles** (dies; being a token, it leaves no corpse).

**The controlled brain** is deliberately simple: each round it declares a basic attack for its Power against the **closest reachable enemy** — nearest row first, then lowest effective HP, then the standard deterministic tiebreak. If nothing is reachable it moves toward reach, exactly as an enemy with no target does (Update 04 §F-3). It is autonomous, like every ally token: you can help it, never command it.

**Duration and ending.** `{turns: X}` expires at the End Step of the Xth round after resolution; `"encounter"` holds until the fight ends. When mind control ends, the living enemy **returns to the enemy side** at that End Step — current HP intact (damage it took while yours stays), on the row it occupies, declaring fresh intents next round. When a raise ends, the undead crumbles.

**Hard rules:**

- **Never bosses.** A boss cannot be controlled — not alive, not in its execute window, not as a corpse. No exceptions. The engine never offers a boss (or boss corpse) as a legal `control` target, and validation lints any authored attempt.
- **Control never wins.** A controlled enemy is **not defeated**. If the victory check ever finds every enemy defeated *except* controlled ones, **all control ends immediately** — each controlled enemy snaps back to the enemy side, and the fight continues. Like bounce, control buys actions, never the win (Update 03's principle, extended).
- **Side symmetry, asymmetric targets.** Enemies may use `control` too — but **only on corpses** (their necromancers raise the fallen, §D9-1.6). Enemies never mind-control a living hero or hero token; player agency is not a puppet string. Player-side `control` may target living enemies and enemy corpses both.
- **Stack behaviour.** `control` is a targeted effect; hexproof on a living enemy blocks it (corpses, per §D9-1.3, have no hexproof). Gaining control fires no death trigger and no `on_ally_death` — nobody died.

**Translation sources** (Deckbuilder): *Act of Treason* → `control {turns: 1}` on a living enemy; *Mind Control* → `control "encounter"`; *Raise Dead / Animate Dead / Reanimate* → `control` on a corpse. This one primitive covers the whole theft-and-necromancy shelf.

### D9-1.5 Rises — the stirring corpse

An enemy trait for the undead shelf: `rises: {turns: X}` (once per encounter).

- When the enemy dies, it leaves its corpse as normal — but the corpse is visibly **stirring**, and the enemy is **not defeated** while it stirs.
- After X Upkeeps, the corpse revives as the enemy at **half max HP** (T-52 fraction), on its row, with fresh intents. The rise is once per encounter — kill it again and it stays down (an ordinary corpse).
- **Counterplay writes itself:** `exile` the stirring corpse and the enemy is defeated on the spot; **raise it yourself** with `control` and the rise is cancelled — the body is yours now.
- Priced as an enemy trait at **min level 2, cost 3** (T-56); the stirring state is public (the veil hides intents, not bodies).

### D9-1.6 The generator's undead shelf

The enemy framework (Update 04) gains one component archetype and two blessed patterns, all taught to the generation prompt (§D9-6):

- **Necromancy** *(new archetype, base cost 5)* — proactive; verb `control` on a **fellow-enemy corpse** (`target_rule: "corpse"` — nearest own-side corpse, deterministic tiebreak). Raises the fallen minion as an enemy-side undead token at the T-52 fraction. No corpse in reach → the rule doesn't fire and the priority list falls through, so a Necromancer never wastes a turn. Telegraph category: **spellcraft** (it is `action_type: "spell"` — counterable, and Negate-bait).
- **Corpse-burst** *(Burst variant)* — consume (exile) an own-side corpse to damage the row it lay on, using the blast shapes of §D9-3.2. The faction that eats its own dead.
- **Rises** minions (§D9-1.5) — the shambling tide that gets back up.

Faction guidance: an undead encounter runs on **body economy** — cheap corpse-leaving Husks up front, one Necromancer feeding on the fallen (kill-priority incarnate), a riser or two, and exile/`control` as the party's trump cards. At most **one Necromancer** per encounter; necromancy that outpaces the party's removal is a treadmill, not a fight.

### D9-1.7 Zone-table amendment *(amends Update 03 §E-A)*

| zone / state | on the field? | defeated? | notes |
|---|---|---|---|
| in play | yes | no | unchanged |
| in hand (bounced) | no | no | unchanged |
| **graveyard — corpse** | **marker on its row** | **yes** | targetable by corpse-legal effects only |
| **graveyard — stirring** | marker on its row | **no** | revives in X Upkeeps unless exiled or raised |
| **controlled** | yes — party side | **no** | snaps back if it would be the last enemy |
| exile | no | yes | unchanged; now also where burned corpses go |

**UI note:** corpses render small and dim on their row — information, not spectacle (the stroke-icon skull, low opacity, per the design system). A stirring corpse carries a subtle pulse and a chronicle line ("The Grave Thrall's corpse stirs…").

---

## D9-2. Stances

### D9-2.1 The rule

A **stance** is a channeled effect that reshapes its holder's four main abilities — **attack, Defend, Mitigate, Move** — for as long as it is held. It is **replace-only**: a stance never adds a fifth ability; it rewires the four you have. For each of the four, a stance declares one of:

- **`unchanged`** — the ability works as normal (the default);
- **`removed`** — the ability is not legal at all while in the stance;
- **`replace`** — the ability is swapped for an authored action: a name plus a list of **leaf effects** (same rule as modal/conditional branches — no nested containers).

### D9-2.2 Schema

A new effect, legal **only on `channeled` cards**, always continuous (implicitly `while_channeled`; a recurring stance is a contradiction and is rejected):

```
stance {
  attack?:   "unchanged" | "removed" | { name, effects: [leaf…] },
  defend?:   …,
  mitigate?: …,
  move?:     …,
}          # omitted slot = unchanged; at least one slot must not be "unchanged"
```

The Deckbuilder's effect editor renders this as four labelled slots, each with the three-way choice and, on `replace`, the standard effect-list editor.

### D9-2.3 Semantics

- **The slot's economy is inherited.** A replaced **attack** is an action, once per round, and satisfies the Attack proactive choice. A replaced **Defend** is an action. A replaced **Move** is the Move action. A replaced **Mitigate** stays a **reaction**, once per turn, fired in the same window (an incoming attack-type action on the stack) — its authored effects resolve *instead of* the reduction.
- **Replacements are activated abilities**, not attacks and not spells: they do not trip `on_attack` triggers, an enemy counter filtered to `attack` or `spell` cannot answer them, a broad `ability`/`action` counter can. A replaced attack does not feed keywords that read attacks (double strike, first strike's held attack — see below).
- **`removed` is total.** Remove **Move** and the character cannot take the Move action *nor* the haste free move. Remove **attack** and the basic attack is gone in every form, including the first-strike held reaction. Remove **Mitigate** and the character guards nobody, including themself.
- **Casting is untouchable.** The Cast action, instants, Skills, and the Ultimate are never stance-modified — a stance rewires your body, not your spellbook.
- **One stance at a time.** A character may hold at most one stance channel; casting a second while one is held is illegal (drop the first, at instant speed as ever, and the mana releases to help pay).
- **Breaking is ordinary channel law** (GDD §8): one hit ≥25% of max HP, incapacitation, or a voluntary drop — and it breaks *all* channels, stance included, all-or-nothing. Being knocked out of a stance mid-round removes the replaced abilities immediately; anything already on the stack resolves.
- **Stances are player-only.** Enemies have no evergreen abilities to rewire; validation rejects `stance` in enemy verbs.

### D9-2.4 Two worked stances (authoring reference)

- *Meditative Trance* (Channeler, 2 mana reserved) — attack: **removed** · Defend: **replace** "Soothing Palm — heal 3, chosen ally" · Mitigate: unchanged · Move: unchanged. The healer stops fighting and starts mending; break the trance and the mending stops.
- *Stoneskin* (Fighter, 2 mana reserved) — Move: **removed** · Defend: **replace** "Living Bulwark — grant self indestructible until end of turn" · attack: unchanged · Mitigate: unchanged. Rooted, immovable, nearly unkillable — and the enemy's answer is written on it: one big hit breaks the stone.

These are content sketches, not shipped cards; they document the intended shape (a stance's power should live in the replacement, its cost in the removal and the reserved mana).

---

## D9-3. Forced movement & row blasts

### D9-3.1 The `move` effect

A new leaf effect (the *effect* `move`, distinct from the Move *action*):

```
move { direction: "forward" | "back" | "to_front" | "to_mid" | "to_rear",
       target }                        # living creatures, either side
```

- **Directions are side-relative:** `forward` is toward that side's front row, `back` toward its rear. `forward` from front (or `back` from rear) is a no-op; `to_X` places the creature on that row directly.
- **The shove is physical and immediate.** Unlike voluntary movement (pending until End Step, Update 02), a `move` effect updates the target's **current and committed rows the moment it resolves**. The body moves *now* — shove the front-line Bruiser back at instant speed and the wall is open **this turn**: your melee reaches the Artillery behind it.
- **Forced movement never invalidates a declared intent.** Intents lock at declaration and re-check nothing (Update 02's no-dodge guarantee, extended to reach): a melee enemy shoved to the rear still lands the attack it declared — it lunges. Pushing is **positional play**, not a soft stun: it shapes your own reach this round and the enemy's declarations next round. (Answering the declared attack remains the job of Mitigate, counters, and prevention.)
- **Both sides.** Player cards shove enemies (open the wall, drag the healer forward into melee reach) and reposition allies ("get the caster out" — as an instant, since the effect is immediate). Enemy components shove heroes — the hook that drags your channeler to the front row is legal, fair, and terrifying: it can't break the channel by itself, but next round the wall's melee can.
- **Bosses can be shoved.** Movement affects a boss *in place* — it is not removal, so the Update 04 triage ("removes from board → blocked; affects in place → works") says it works. Repositioning the mountain is half the fun of fighting one.
- **Targeted as authored:** hexproof blocks a targeted shove of a living enemy; fizzle rules are standard.

**Translation sources** are thin (MTG rarely moves creatures between ranks) — expect `move` to be authored content and enemy kit more than Scryfall imports; lint nothing.

### D9-3.2 Row-scoped area targeting

Two extensions to the creature target descriptor, giving every damaging or hostile verb a row vocabulary:

```
# (a) a whole row, no creature picked:
target: { class: "creature", mode: "all", side, rows: ["front"] }

# (b) splash around a picked creature:
target: { class: "creature", mode: "chosen"|…, side, targeted?, scope: "row" | "blast" }
```

- **`rows` filter** on `mode: "all"` — "all enemies in the front row", "every hero in mid or rear". Not targeted, like every `all`.
- **`scope`** on a single-creature pick — the effect resolves on the picked creature **plus**:
  - `"row"` — every other creature on the picked creature's row (same side);
  - `"blast"` — every creature on its row **and all adjacent rows** (same side). Adjacency is the standing rule: front↔mid, mid↔rear, **front and rear are not adjacent**. So a blast on a front-row enemy catches front + mid; a blast on a **mid-row** enemy catches everything — mid sits adjacent to both. The centre of the formation is the splash magnet; standing there is a choice.
- **Only the pick is targeted.** Hexproof and shroud protect a creature from being the *pick*; splash victims are caught incidentally (the trample-carry precedent). If the pick is illegal at resolution the **whole effect fizzles** — no pick, no blast.
- **The veil already speaks this language:** enemy row and party AoEs render as the D8-1.2 **row assault** / **party assault** categories ("…prepares an assault on the front of your party"). This section is what makes those lines common instead of rare.

Positioning consequences, by design: spreading the party across rows blunts blasts but thins the wall; stacking the front feeds them. Combined with `move` on both sides, where everyone stands is renegotiated every round — which was the point.

### D9-3.3 Generation guidance & magnitudes

Enemy verbs gain the shapes above verbatim. Magnitude schedule (register T-55): a **row** hit deals **L** per creature; a **blast** or party-wide hit deals **ceil(L/2) + 1** (the existing AoE convention) — wider is shallower, always. New blessed pattern for the prompt: the **Hooker** (Debilitate variant: `move` a hero `to_front`, cooldown 2 — pairs with a front-row biter), and the **Line-breaker** (a shove `back` on the party's wall, opening their own melee lanes). At most one forced-mover per encounter at standard; two only at hard.

---

## D9-4. The boss endgame: two intents post-enrage

*(amends Update 04 §F-8 / Update 06; the enrage rules there are otherwise unchanged)*

Once a boss has **enraged** (crossed ≤25% max HP), from the next Enemy Intents step onward it **declares two intents per round** and executes both.

- **Declaration:** the proactive pass runs **twice**. Cooldowns spend as they are picked, so the first pick can exclude itself from the second; the guaranteed default Attack rule backstops the second slot, always. Each intent is veiled separately, each locks its own target — two lines in the intents window.
- **Execution:** both intents execute during the boss's slot in the Enemy Actions step, **in declaration order**, each as its own stack action with its own reaction windows.
- **Disruption scales with it:** `strip_intent` removes **one declared intent of the player's choice** (the legal-action expansion offers one strip per declared intent); a **stun** charge suppresses **one** of the two (the boss declares one intent that round, not zero) — fury is never fully silenced by a single stun, which keeps the post-enrage phase from being turned off with one card.
- **No budget change.** The 2.5× boss budget (T-39) already prices the enrage package; the second intent is a standing boss rule, not a component. Its cost to the party is action economy — exactly the resource the endgame was leaking when a whittled boss stood alone taking four hero turns to its one.

The fight's final act now *feels* final: the enrage eruption, then a boss that is executable but **twice as loud** — race it down or answer two threats a round.

---

## D9-5. Deferred: alternate objectives

Alternate encounter objectives (survive N turns, kill-before-N, protect the NPC, reinforcement waves) were reviewed for Tier Two and are **deliberately deferred** — no schema, no engine hooks, no prompt language in this update. Recorded here so the deferral is a decision, not an omission. When they return, the ritual-with-a-fight-sized-timer shape should be built on the charge machinery (§D8-2.4) rather than a parallel system.

---

## D9-6. Generation prompt updates (`llm.py`)

- **Necromancy** component archetype (base 5) with the corpse `target_rule`, the raise semantics, and the one-per-encounter guidance (§D9-1.6).
- **Corpse-burst** and **Rises** patterns (§D9-1.5/1.6), with `rises` priced min level 2 / cost 3 (T-56).
- **`move` verb** shapes and the Hooker / Line-breaker patterns (§D9-3.3), with the one-per-encounter-at-standard cap.
- **Row/blast target shapes** (§D9-3.2) added to the verb-target convention block, with the T-55 magnitude schedule.
- **Boss section** gains one line: after enrage the engine grants the boss two intents per round — design the post-enrage kit knowing it fires twice as often (this is engine-enforced; the prompt teaches it only so the model designs for it).
- **Prohibited-verb list** updated: `control` is enemy-legal **only on corpses** (the prompt shows the corpse-target shape and nothing else); `stance` joins the never-on-enemies list.

---

## D9-7. Engine & schema touchpoints (for the implementation pass)

| system | where |
|---|---|
| corpse state | `apps/combat/ltg_combat/state.py` — dead non-token enemies stop being deleted (`engine.py:_kill_enemy` currently removes them from `st.enemies`); they transition to zone `graveyard` with a corpse record `{row, power, max_hp, level, stirring?}`; new accessor beside `living_enemies()` / `bounced_enemies()` |
| corpse targeting + `is_dead` | `core/ltg_core/schema.py` — `state` axis on creature targets, `is_dead` target_property; Deckbuilder effect editor (`apps/deckbuilder/frontend`) exposes both; validation matrix per §D9-1.3 |
| `control` primitive | schema leaf effect + renderer + `engine.RESOLVERS`; controlled-combatant state (a token-like party-side actor with `controlled_by`, `duration_left`, revert data); the controlled brain in the ally-intent pass; the last-enemy snap-back inside the continuous victory check; boss exclusion in target legality |
| `rises` trait | enemy schema field; stirring corpses tick at Upkeep; revive path reuses the redeploy machinery (`_redeploy_bounced` precedent); exile/raise cancellation |
| `stance` effect | schema (channeled-only, slot validation) + a dedicated Deckbuilder sub-editor; engine: ability-slot resolution reads the holder's active stance when building legal actions (attack/Defend/Mitigate/Move), replacement actions resolve as activated abilities; removal semantics incl. haste-move and first-strike-hold |
| `move` effect | schema + resolver writing `current` **and** `committed` immediately (the one exception to Update 02's End-Step rule — document it in `engine.py` where rows are written); no intent re-checks |
| row/blast targeting | target-resolution layer in `engine.py` (splash expansion mirrors `_trample_cleave`'s adjacency walk); `rows` filter on all-mode; fizzle-on-pick rule |
| boss double intent | the Enemy Intents pass runs twice for enraged bosses; per-intent strip expansion in legal actions; stun consumes one declaration |
| snapshots & UI | corpse markers + stirring pulse on the battlefield; two veiled lines for an enraged boss; controlled enemies render on the party side with a control chip and remaining duration; cockpit shows everything raw |

Regression spine: the §A/§C scripted scenarios contain no corpses, stances, shoves, or enraged bosses — they must replay byte-identical. The one structural risk is `_kill_enemy` no longer deleting enemies: §A kills minions, so the accessor changes (`living_enemies` etc.) must keep every existing read-path's behaviour exactly.

---

## D9-8. Rebalance Register deltas *(amends Update 04 §F-10, Updates 07 §X-7, 08 §D8-7)*

| ID | value | sets |
|---|---|---|
| T-52 | 0.5 (floor, min 1) | HP fraction for raised undead (`control` on a corpse) and for a `rises` revival — mirrors T-44 |
| T-53 | base cost 5 | Necromancy component archetype |
| T-54 | 2 | boss intents per round, post-enrage |
| T-55 | row = L · blast / party-wide = ceil(L/2) + 1 | enemy AoE magnitude schedule by scope (single stays L + 1) |
| T-56 | min level 2 / cost 3 / rises after 2 Upkeeps | the `rises` enemy trait |

---

## D9-9. Glossary deltas *(amends GDD §13)*

- **Corpse** — the battlefield remains of a dead non-token enemy: an object on its death row, defeated for victory purposes, targetable only by corpse-legal effects (`control`, `exile`, necromancy). Exile leaves and takes no corpse; tokens leave none.
- **`control`** *(new primitive)* — make an enemy creature or corpse into an allied token for a duration (`turns: X` or `encounter`): mind control on the living, raise-dead on a corpse (T-52 HP). Never legal on bosses; enemies may use it only on corpses; ends immediately if its target would be the last undefeated enemy — control buys actions, never the win.
- **Dominated / raised** — the two flavours of a controlled combatant. Both run the simplest brain: basic attack against the closest reachable enemy, every round.
- **Stirring** — a corpse under the `rises` trait: not yet defeated, revives after X Upkeeps at T-52 HP unless exiled or raised first.
- **Stance** *(new effect)* — a channeled, continuous, player-only effect that sets each of attack / Defend / Mitigate / Move to unchanged, removed, or an authored replacement action. Replace-only; one stance held at a time; Cast is never affected; breaks like any channel.
- **`move`** *(new effect)* — forcibly reposition a living creature (`forward` / `back` / `to_front` / `to_mid` / `to_rear`); relocates current **and** committed row immediately; never invalidates a declared intent.
- **Row / blast scope** — area shapes on a single pick: the pick's row, or its row plus adjacent rows (front↔mid↔rear; front and rear are not adjacent). Only the pick is targeted; splash is incidental; the effect fizzles with its pick.
- **Boss fury** — the post-enrage standing rule: two veiled intents declared and executed per round (T-54); a stun suppresses one, a strip removes a chosen one.

---

## D9-10. Open questions

- **[OPEN] Corpse rows and shoves.** Corpses currently sit where they fell and cannot be moved (`move` requires a living target). If a dragging-bodies mechanic is ever wanted (pull the corpse out of the Necromancer's reach instead of exiling it), it is a one-line target-state relaxation — deferred until a card asks for it.
- **[OPEN] Controlled enemies and the ultimate gauge.** Damage dealt by a creature you control charges nobody's gauge (it is a token, and tokens never charge, §D8-3.3). Revisit if control decks feel gauge-starved.
- **[OPEN] Stance count.** One stance at a time is the launch rule. A future Channeler identity ("stance-dancer") could relax this to one *per slot* — priced content, not a rules change.
- **[OPEN] Alternate objectives** — deferred (§D9-5).
