# Langelier Tactical Game (LTG) — Design Update 15: Live Movement

**Status:** IMPLEMENTED 2026-07-18 (`apps/combat/ltg_combat/engine.py`, `state.py`, `scenario.py`, `serialize.py`, `core/ltg_core/schema.py`; `tests/test_design_update_15.py`, `tests/test_movement_mitigate.py`).

**Supersedes:** Update 02 §M-B (the position model) and the movement clauses of §M-C (haste) **in full**. Update 02 §M-A (Mitigate) survives with amended adjacency wording (§L-2.2). Update 01 §R-1 (rows/reach) survives with one amendment (§L-4). Where this document and any prior document disagree, **this document wins.**

**The repeal.** Update 02 built the movement system around one guarantee — *"movement can never dodge a declared attack"* — and spent its entire apparatus (dual `current`/`committed` positions, the `pending_voluntary` quarantine, End-step catch-up) enforcing it. This update repeals that guarantee and replaces it with a better one: **movement never *negates* an attack — it can only change who takes it.** A melee intent dodged is a melee intent *redirected onto a legal body that stepped between*; a positional intent dodged is a row vacated at the price of the mover's turn. Damage avoided is always paid for in action economy or in a teammate's HP. In exchange, the game gets: a Move action worth taking, a live board where formation is a per-turn puzzle, haste at full thematic strength, and MMO-style row-nuke telegraphs. The dual-position model — the hardest rule in the game to teach — is deleted outright.

---

## L-1. The single-position model  *(replaces Update 02 §M-B.1, §M-B.5)*

Every combatant (character, enemy, token) has **one** row value: `row`, its physical position. There is no `committed`, no `pending_voluntary`, and no End-step movement catch-up — those fields and rules are deleted. **A move resolves live**: the body relocates at the moment defined in §L-2, and everything in the game — reach, Mitigate adjacency, the wall, intent targeting — reads the one true `row`.

"You move when you move; attacks hit whoever is there when they land." That is the whole model.

## L-2. When moves resolve  *(replaces Update 02 §M-B.3, §M-B.4)*

### L-2.1 Action-bound (forced) moves — at declaration
A move that is a built-in consequence of an action applies **the moment that action hits the stack**, before any reaction window opens:

- **Melee basic attack** → the attacker's `row = front` *(the lunge — you must close the distance before the swing can be made)*.
- **Ally-Mitigate** (§M-A.6) → the mitigator's `row = the protected ally's row` *(the dash)*.
- Any future action documented as carrying a move uses the same timing.

Because the body is really there during the action's own reaction window, **the advancing attacker is exposed**: enemy reactions in that window can strike the lunger at its new row, and the intent re-check (§L-3) runs on the lunge — stepping to Front to attack can *pull a melee intent onto the attacker* (see Example 4). The move is part of the action's cost, not a rider: it happens even if the action is subsequently countered (you lunged; the swing was stopped).

### L-2.2 Voluntary moves — a stack action of their own
The **Move** proactive action (any destination row, no mana, costs the action — unchanged from §M-B.4) may be taken **only on your turn while the stack is empty**. It goes **onto the stack** as an action and the body relocates when it **resolves**:

- Move is **reactable but uncounterable**: it opens a normal reaction window (an enemy component may trigger on it — the *attack-of-opportunity* design lever, §L-6), but no `counter` effect, of any filter, can answer it. You cannot counter footwork.
- The **haste free move** (§L-6.1) is a voluntary move under the same rules: your turn, stack empty. In particular **you cannot take it while your own action is unresolved** — no attacking and skipping away before the swing lands. Attack, let it resolve, then move.
- **Mitigate adjacency** (§M-A.5) is measured against real `row` at the moment the Mitigate is declared. A character who has genuinely moved reacts from where it genuinely is; there is no quarantine, because there is no longer a phantom destination to quarantine. (The §M-B.4 "reach laundering" problem dissolves: post-move reach is legitimate — you are actually there.)

### L-2.3 Enemy and token movement — live at execution
Enemies and ally tokens use the same live model. An enemy **Move intent** (Advance, Evasive reposition, §F-7.3) relocates the body **when the intent executes** in the Enemy actions step — not at End step. This deletes the enemy-side deferred-move machinery along with the player side's, and opens the enemy-design avenue of *composite moving actions* (charge: move to front **then** strike; hit-and-fade: strike **then** fall back) as ordered effects within one intent. In practice live enemy movement rarely changes outcomes — enemies act last, just before End step — but the engine keeps **one** movement rule for all sides, and the intent re-check (§L-3) runs on enemy moves too (an enemy advancing can change what an ally token's telegraphed intent may legally hit).

## L-3. The intent re-check: dodging is interposition  *(replaces Update 02 §M-B.2)*

Intents remain **nominal** — declared against an individual, telegraphed by name ("Grukk will strike Soren for 6") — but they are no longer locked. One canonical routine, `recheck_intents`, runs **after every occupancy change**: any resolved move (voluntary, action-bound, or enemy), any forced-movement effect (push/pull spells now bend intents — a real buff to those cards), and any death. The last board state before the intent executes governs.

### L-3.1 The redirect rule (nominal melee)
A nominal **melee** intent on target T re-checks as follows:

1. If T still stands in the attacker's front-most legally-reachable row → **the intent stays on T.** Stepping back when no one covers you does nothing: the front-most occupied row is now wherever you stand, and the attack follows you (Example 2).
2. If a **legal interposer** now stands in a row in front of T — a non-flying combatant on T's side that the attacker could legally strike — the intent **redirects to the front-most legal row**, choosing among its occupants by the same deterministic valuation heuristic that declared it (§F-7.2), restricted to that row. Redirect is re-*selection*, never re-*design*: the intent keeps its name, damage, and shape; only the recipient changes.
3. A target that becomes **unreachable with no legal interposer** (edge case: everyone else dead or flying) → the intent **fizzles** at execution, logged as such.

**What this means at the table:** dodging a melee intent requires a teammate willing to eat it. The tank steps out and hands the ogre's swing to whoever now holds the line; the squishy steps behind the tank and feeds the tank the hit. Movement shapes damage; it never deletes it. This is the mirror of ally-Mitigate — redirect-toward-me as a free reaction with reduction, versus redirect-away-from-me at the cost of a full action with no reduction.

### L-3.2 Nominal ranged and flying intents never redirect
A ranged or flying-attacker intent ignores the wall going in, so no interposition exists against it: it stays locked on its declared target wherever that target stands. **Movement answers melee; Mitigate answers ranged** — the §M-B.6 doctrine, now dynamic. This is what keeps dodge from becoming a universal defense and preserves Mitigate's niche.

### L-3.3 Live telegraph UI
Because the re-check runs at move resolution (not at enemy execution), intent arrows update **immediately and visibly**: the player watches the ogre's gaze slide onto Soren the moment the dodge resolves, and plans the rest of the turn against the real assignment. Deterministic, no hidden state, no Enemy-step surprises. (Server/cockpit rendering work in §L-7.)

## L-4. Flying and the wall  *(amends Update 01 §R-1)*

Flying evasion is already canonical (R-1: on defence, a flyer is struck only by ranged, other flyers, or reach) and is unchanged. The amendment: **flyers are transparent to the melee wall.**

- A flyer **never counts** when computing the front-most occupied row: ground melee looks straight past it to the first row with a non-flying body ("the attacker just runs beneath them").
- A flyer **cannot interpose** (§L-3.1) — moving your flyer to Front redirects nothing.
- A flyer **cannot shield** allies behind it, in any row.

This closes an exploit the old computation permits: today (engine `_reachable_targets`) a flyer standing in Front *sets* the wall row and then filters itself out as untouchable — a flying frontliner is an **unhittable wall**, strictly better than a ground tank. Under this update the same flyer is simply not part of the line at all. Flying's defensive benefit to the *character* (melee immunity) is now paid for by a defensive cost to the *party* (one fewer body that can hold or reform the wall, one fewer legal dodge-enabler). Flying stays at 25 points; the evasion buff and wall-transparency nerf roughly offset, pending autoplay data.

## L-5. Positional intents: aimed at *there*, not at *you*  *(new enemy grammar)*

A new intent class alongside nominal intents. A **positional intent** targets a **row**, not a combatant: *"Gorehorn winds up a Cleave — 8 to every character in the Front row."* *"The ballista turns toward your back line — 6 to every character in the Rear row."*

- **Occupancy is read at execution.** Whoever stands in the row when the intent executes takes the hit; an empty row means a clean whiff, logged proudly. Positional intents are therefore **always dodgeable by vacating** — melee or ranged alike. The dodgeability split in this game is *not* melee-vs-ranged; it is **nominal vs positional**: aimed at you → tank it, Mitigate it, or (melee) feed it a wall; aimed at there → don't be standing there.
- **The telegraph is the floor circle.** The intents-step line names the row and the number. Counterplay is legible at a glance, MMO-raid style.
- **The real cost is the scatter.** Three characters vacating a row is up to three proactive actions burned dodging — a positional intent is a *turn-economy tax* whose damage is merely the punishment for greed. Tune numbers so a tank *can* choose to stand in it behind Defend/Mitigate: "everyone scatters — unless someone is brave enough to eat it" is the intended decision, not mandatory evacuation.
- **The aftermath is positional.** A Front-row swipe that empties the front line has dropped the party's wall for the next Intents step; a Rear-row volley that pushes the casters forward walks them into melee reach. The nuke reshapes formation even when it deals zero.
- **Component shape:** `target_row: front|mid|rear` on an attack-type component, priced per the T-55 row schedule (a whole row = L per creature). The engine **auto-scopes** the component's verbs onto the row footprint (`{"mode": "all", "side": "ally", "rows": [<row>]}`): whatever ally-side target the author wrote is normalised to the row, self-riders stay on the enemy, and hand-written footprints pass through unchanged. Positional intents ignore taunt (they aim at ground, not at a name) and interact with Mitigate normally (each struck character may self-Mitigate; ally-Mitigate redirects one ally's hit as usual).
- **Template shape:** a legacy chassis can be positional without components — `"intent": {"name": …, "amount": N, "target_row": <row>, "intent_type": "attack"}` aims the basic swing at that row every turn. It carries `attack_power`, so a wound landing after declaration still blunts what lands on every body in the row (R-7). The loader rejects any `target_row` outside front/mid/rear, in both forms.
- **Telegraph:** the veiled line names the ground — *"…prepares an assault on the front of your party"* (or *"begins casting a spell at the front of your party"* for a spell-classed barrage) — and the intent payload carries `target_row` for clients to render the row highlight.

## L-6. Keyword errata

### L-6.1 Haste — full strength, repriced  *(replaces Update 02 §M-C)*
Haste grants the proactive action **plus a free voluntary move**, per §L-2.2: **live**, own turn, stack empty, never while your own action is unresolved. The clause "haste does not enable dodging" is repealed — a hasted character genuinely acts *and* is genuinely somewhere else: strike from the front and fall back; dodge a melee intent onto the wall **and** still attack; reposition into Mitigate adjacency after casting. Haste is the action-economy sister of vigilance on the movement axis, and now pulls its weight. **Cost: 15 → 20 points** (T5 table and any mirrors), vigilance territory; revisit with autoplay data.

### L-6.2 `relentless` — new enemy keyword
*"This enemy's nominal intents never redirect: they pursue the declared target wherever it stands (the intent fizzles only if the target dies)."* The old locked-promise dread, reintroduced deliberately as a boss/elite signature — expressible only because the default became dodgeable. Enemy-only. Priced with the §D4 component tables at implementation.

### L-6.3 Unchanged
`reach` keeps its R-1 meaning (its melee strikes flyers; pins flying melee) and its price. `first_strike` (R-12) is unchanged in rules text and *strengthened* in practice by §L-2.1: the held-attack reaction now punishes a physically-present lunger, exactly as the fiction always claimed. Registry glosses touched by this update: `haste` (rewrite — the End-step parenthetical dies), `flying` (append wall-transparency), `relentless` (new).

## L-7. Engine & test migration

**Deleted:** `committed` and `pending_voluntary` fields (state, serialize, all reads); End-step catch-up in `_end_step`; the `committed = "front"` write in `_do_attack` becomes a real `row` write; `_do_move`'s queue-a-destination body becomes push-a-stack-item; enemy Move-intent queueing (`pending_voluntary` path in intent execution) becomes a live row write.

**Added:** `recheck_intents(st)` — one canonical routine, called after every occupancy change (move resolution, action-bound move at declaration, forced-move effect, death), implementing §L-3.1–3.2 via the existing §F-7.2 heuristic; a `move` StackItem kind (reactable, uncounterable); flyer-transparent front-most-row computation in `_reachable_targets` (compute `front` over non-flying defenders only); `target_row` positional-intent path through declaration, telegraph rendering (`translation.py`), and execution; `relentless` check inside `recheck_intents`.

**Tests:** rewrite the pinned old-world invariants in `test_movement_mitigate.py` — `test_voluntary_move_resolves_at_end_step` → resolves live on the stack; `test_move_does_not_dodge_a_locked_intent` → the new pair *redirects-with-interposer* / *follows-without-interposer*; `test_melee_attack_forces_committed_front` → physically lunges at declaration; `test_haste_allows_act_and_free_move` → live, plus the not-while-unresolved guard; `test_mitigate_ally_blocked_by_adjacency` → adjacency from real `row`. New coverage: flyer wall-transparency (including the old exploit as a regression test), flyer-cannot-interpose, redirect determinism, fizzle-when-unreachable, positional-intent hit/whiff/scatter, relentless, push/pull-triggered re-check, Move uncounterable, enemy live move.

**Autoplay:** the greedy policy never uses Move today, so an A/B of this update would measure nothing. Before balance conclusions, teach the policy a minimal positional layer: vacate a lethal positional row (cheapest mover first), interpose-dodge when it saves more HP than the forgone attack deals, and treat the haste free move as a free instance of both. Then run the encounter suite old-engine vs new and read the damage-taken / TTK deltas — expected: enemy nominal melee pressure drops (redirect), offset by positional intents and `relentless` where authored.

**UI:** intent arrows re-render on every re-check (§L-3.3); positional intents render as a row highlight with the number; the Move action gains stack presence in the log ("Soren moves to Rear (resolving)… resolved").

---

## Worked examples

**1. The dodge that works.** Soren (tank) and Ys (caster) both stand in Front; Grukk telegraphs melee 6 on Ys. Ys spends her action: Move → Rear. On resolution the re-check runs: Front still holds a legal body (Soren), so the intent redirects to the front-most legal row and lands on Soren. Ys traded her whole turn to convert 6-on-the-caster into 6-on-the-tank — and cast nothing. Fair price, real decision.

**2. The dodge that fails.** Same intent, but Soren has fallen. Ys Moves → Rear anyway. Re-check: no interposer; the front-most occupied row is now wherever Ys stands; the intent follows her. She spent her turn and gets hit regardless — running away from melee without a wall is just running.

**3. The flyer changes nothing.** As Example 2, but Kestrel (flying) swoops to Front "to cover" Ys. Re-check: flyers are wall-transparent and cannot interpose — Grukk runs straight beneath Kestrel and the intent stays on Ys.

**4. Attacking is interposing.** Brakka telegraphs melee 5 on Ys, who stands in **Mid** with Soren — the Front row is empty. Soren declares his melee basic attack — at declaration his body lunges to Front (§L-2.1) and the re-check runs *before his swing resolves*: the front-most grounded row is now Front = {Soren}, Ys is covered, and the intent redirects onto him. He walked into the hit on purpose, by attacking. (And in the same window, a First Strike-style enemy reaction may strike the physically-present lunger.) Note the boundary drawn by §L-3.1(1): if Ys had been standing in Front *beside* him, the intent would **stay on her** — joining your target's row never steals a swing (that is taunt's job); only *covering* the target from a row in front of them does.

**5. The raid mechanic.** Gorehorn winds up: *Cleave — 8 to every character in the Front row* (positional, executes next enemy step). Soren (Defend, stands in it behind Mitigate), Brakka Moves → Mid, hasted Fenn attacks **and** free-moves → Mid. The party spent one full action and one haste rider dodging, and its wall is now one body thin — which is the mechanic. The Cleave executes, reads Front = {Soren}, and he eats a mitigated 8 so the line holds.

## Glossary updates

- **Move** — repositioning between rows; a stack action (reactable, uncounterable) taken on your turn with the stack empty, resolving live; costs the proactive action, no mana, any destination row.
- **Live movement** — the body relocates when the move resolves (action-bound moves: when the action hits the stack). End-step movement no longer exists.
- **Interposition / redirect** — a nominal melee intent re-targets, by the declaring heuristic, onto the front-most legal row when a legal non-flying body stands in front of its target; with no interposer it follows its target. Ranged/flying nominal intents never redirect.
- **Positional intent** — an intent aimed at a row, not a combatant; reads occupancy at execution; dodged by vacating.
- **Wall-transparent** — flyers neither form, join, nor benefit the melee wall, and cannot interpose.
- **Relentless** *(enemy keyword)* — nominal intents that never redirect; they pursue the declared target.
- **Haste** — proactive action plus a free live voluntary move (never while your own action is unresolved); 20 points.
- **Current / committed position, pending voluntary move** — *deleted terms* (Update 02 §M-B); superseded by the single live `row`.
