# Langelier Tactical Game (LTG) — Design Update 02

**Status:** canonical rules addition. Defines the **Mitigate** reaction, the **Movement** system, and the **Haste** keyword. Self-contained: assumes only the base GDD and Design Update 01. Keyed to the original sections it amends. Where this document and the GDD disagree, **this document wins.**

**Terminology change (applies document-wide, amends §4.6, §4.8, §13, and Update 01 §R-12):** the evergreen defensive reaction formerly called **Parry** is renamed **Mitigate**. Every prior reference to "Parry" now reads "Mitigate." The name "block" is deliberately avoided (it means something unrelated in the source material).

---

## M-A. The Mitigate reaction  *(amends §4.6, §4.8; supersedes all prior Parry rules)*

**What it is.** Mitigate is one of a character's three evergreen abilities (Attack / Defend / Mitigate). It is a **defensive reaction**: free (no mana), usable **once per turn**, that responds to an incoming **attack**. It has two modes — **self** and **ally** — and the single per-turn use is spent on **one or the other**, never both.

### A.1 What it can answer
- Mitigate targets **one `attack`-type action on the stack** (§5.1). It does **not** answer `spell`-type actions, and it does **not** answer non-attack ability damage (triggered/activated damage). Those require a counter (§5.4) or `prevent`. Stating the rule positively: **Mitigate applies to attack-type actions only**, which is why enemy spells and non-attack damage fall outside it automatically.
- It is a reaction (`reactive` timing, §5.1): declared in a reaction window after the attack is on the stack, before that attack resolves.

### A.2 The mitigation value X
- **X = ceil(the mitigator's current Power / 2)**, read **at the moment the attack resolves**, not when Mitigate was declared. Because Power scales with temporary modifiers, a `pump` on the mitigator raises X and a `wound` lowers it for that resolution. Default X by archetype (current Power in parentheses): **Fighter 2** (Power 3); **melee Tactician/Channeler 1** (Power 2); **ranged profiles 1** (Power 1) — so heavier frontliners mitigate harder, glass cannons mitigate weakest but never for 0.
- **Why half, not full:** at full Power, a frontliner's Mitigate plus the wall would mean a same-Power melee enemy deals **0** — every fight against your-tier melee would stall unless one side out-stats the other. Halving restores attrition: a same-Power hit now chips for roughly half rather than nothing.
- Rounding is `ceil`, not `floor`, so a Power-1 ranged character still mitigates for **1**, not 0 — a usable-but-weak reaction rather than a literally null button.
- Reusing Power for mitigation is intentional: one stat governs both offense and active defense, so buffing a tank's Power also buffs its guard. The halving softens that coupling (a +2 `pump` on a Fighter raises X by only +1: ceil(5/2)=3 vs ceil(3/2)=2), which keeps the offense-plus-defense swing from a single pump in check.

### A.3 Per-hit application
- An attack action may carry **one or more hits** (e.g. a 2-hit Burst, a 4-hit Swarm). Mitigation applies to **each hit in the action independently, at the full value X** — the hits "bounce off the shield" one at a time; the shield does not tire between blows.
- For each hit of amount `h`: **damage dealt = max(0, h − X)**.
- **Small hits fully negate:** any hit with `h ≤ X` deals 0. The negation threshold is now low (a Fighter at X=2 eats only hits of ≤2), so frontliners still shrug off the smallest multi-hit chip but no longer absorb a moderate Swarm wholesale — a 3-damage Swarm now leaks 1 per hit instead of being fully absorbed. This is intended rock-paper-scissors: Swarm threatens the backline and pressures the front, while a tank still blunts the weakest of it.

### A.4 Self mode
Reduce each hit of the answered attack that targets the mitigator by X, per A.3. The mitigator takes the post-mitigation remainder.

### A.5 Ally mode (interception)
- **Choose one allied character the attack targets.** Every hit of that action directed at the chosen ally is **redirected onto the mitigator** and reduced by X per A.3; the mitigator takes the remainder. Hits in the same action aimed at *other* targets are unaffected.
- **All-or-nothing for the protected ally:** you take *every* hit the action aimed at that ally; you cannot cherry-pick hit 1 and leave hits 2–3.
- **Identity is preserved:** a redirected hit is still that attack, now landing on the mitigator. On-hit and on-damage triggers (e.g. `lifelink`) fire against the **mitigator**, not the original target — and only on damage that actually lands (a fully negated hit triggers nothing).
- **Adjacency requirement:** ally mode is legal only if the chosen ally is in the **same row as, or a row adjacent to, the mitigator's committed position** (§M-B). Rows are Front / Mid / Rear; **Front and Rear are not adjacent** (Mid sits between them). Adjacency is measured against **committed position**, not current position (§M-B.2), so a character who has committed to a melee attack this turn measures reach from the **front** row.

### A.6 Consequence of interceding for an ally
- Declaring an ally-Mitigate is a **forced move (§M-B.3):** it immediately writes the mitigator's **committed position = the protected ally's row.** Like all physical movement, the body does not relocate until End step (`current ← committed`, §M-B.5).
- This is the cost that keeps interception from being a free delete: covering a backline ally pulls the tank **off the front line**, so the melee the wall (§M-B.6) was holding can reach the backline **next round**. Every interception is a trade — *who do I save, and what do I expose by leaving?*

### A.7 Engine summary (resolution of an answered attack)
```
on resolve(attack A) with declared Mitigate M by character C:
  X = ceil(current_power(C) / 2)              # read now, not at declaration
  if M.mode == SELF:
    for each hit h in A targeting C:
      deal max(0, h.amount - X) to C          # triggers fire only if > 0
  elif M.mode == ALLY(target T):
    # legality (adjacency vs C.committed) was checked when M was declared
    for each hit h in A targeting T:
      redirect h onto C
      deal max(0, h.amount - X) to C           # lifelink/etc. fire off C, only if > 0
    # C.committed was already set to T.row at declaration (forced move)
  # hits in A aimed at other creatures resolve normally
```

---

## M-B. Movement  *(amends §4.1, §4.6; introduces the position model)*

Movement repositions a character between the three rows (Front / Mid / Rear). The system exists so that position is a **live, consequential resource** rather than a one-time setup, and it is built so that **movement can never dodge a declared attack.**

### B.1 The two positions
Every character (and enemy/token) tracks **two** row values:
- **`current`** — its **physical** row. This is what enemy and ally **intents** read when deciding what they hit. It changes **only at End step.**
- **`committed`** — the row the character has **committed to occupy.** This is what the character's **own** actions and reactions read for reach and legality (melee row-reach, Mitigate adjacency). It can change **during the turn.**

Separating these is what resolves the "two places at once" problem: your *reach* updates the instant you commit to a move, but your *body* (what can be hit) does not move until End step.

### B.2 What reads which
- **Intents read `current`.** An intent locks its target/row **at declaration** (the Intents step, §4.2) and **does not re-check at resolution.** This is the no-dodge guarantee, stated positively: because the intent already has its target and never looks again, no later movement can break it.
- **Your own actions/reactions read `committed`.** Melee row-reach (§4.1) and Mitigate adjacency (§M-A.5) measure from `committed`. So committing to a melee attack (which sets `committed = Front`, §B.3) constrains what you can then reach: a fighter who has lunged to the front can guard Front and Mid, but is out of position to intercept for a Rear ally that same turn.

### B.3 Forced moves (immediate writes to `committed`)
Some actions move you as a built-in consequence. These write `committed` **immediately**, when the triggering action is taken:
- **Making a melee attack** → `committed = Front`. (You stepped up to swing; you are committed to the front line for the rest of the turn.)
- **Mitigating for an ally** (§M-A.6) → `committed = the protected ally's row`.

When multiple forced moves occur in one turn, **last write wins** for `committed`. (Example: melee attack sets Front, then an ally-Mitigate sets the ally's row — the Mitigate, being later, governs `committed` from that point.)

### B.4 Voluntary movement (the Move action, and haste)
A **voluntary** move is one the player chooses, as opposed to a forced consequence:
- **Move as a proactive action:** Move is a fourth option for the turn's single proactive action, alongside Attack / Cast / Defend (§4.6). It **costs the proactive action**, costs **no mana**, and lets the character pick **any row** as a destination ("move to the row you choose" — not limited to an adjacent row).
- **Haste** grants a voluntary move as a **free rider** on top of the normal action (§M-C).

**Voluntary moves are quarantined from `committed`.** A voluntary/haste move writes a **separate `pending_voluntary` slot** and does **nothing** to `committed` during the turn. Therefore a planned destination **never** grants reach mid-turn — you can act/react only from where you have *committed* (forced) or where you started, never from where you intend to *end up*. (This is what makes the line "attack to Front, haste-move toward Mid, then try to Mitigate a Rear ally" illegal: reach is still measured from the committed Front row, so the Rear interception fails.)

### B.5 Sync points (the full state machine)
Three fields, three sync points, applied in this order:

1. **Upkeep:** `committed ← current`. Each turn begins committed to where the character physically stands. (Without this, a stale commitment from a prior turn could leak into this turn's reach checks.)
2. **During the turn:** forced moves overwrite `committed` immediately (last-write-wins, §B.3). Voluntary/haste moves write `pending_voluntary` only (§B.4); they do not touch `committed`.
3. **End step:** `current ← (pending_voluntary if it was set this turn, else committed)`; then clear `pending_voluntary`.

The End-step rule also settles forced-vs-voluntary precedence cleanly: **if the player made any voluntary/haste move this turn, that destination wins** (it was the deliberate choice); **otherwise the body catches up to wherever forced commitments left it.** Because the voluntary slot was kept out of `committed` all turn, it can grant no reach — it only decides the final physical destination.

### B.6 Passive defense (the wall) — why position matters
Position already provides passive defense, independent of any active ability, and this is the baseline that makes the rest meaningful:
- **Melee** attacks (enemy or ally) strike only the **front-most occupied row** (§4.1, Update 01 §R-1). A character in Front therefore **shields** every ally behind it from melee, for free — the line cannot be walked past.
- **Ranged and flying** attacks ignore the wall and reach any row (Update 01 §R-1). The wall does nothing against them.

This split is the engine of positional play: the wall answers melee for free, so the **only** job left for the active Mitigate-interception (§M-A.5) is the threat the wall *can't* stop — ranged/flying at the backline — and Move (§B.4) is how a party re-forms or re-positions the wall as a fight develops (e.g. when the frontliner is removed, or to bring a tank into interception adjacency of an incoming volley).

### B.7 Scope
This model applies symmetrically to **enemies and ally tokens.** They, too, resolve any movement at End step and lock their intents at declaration; no movement creates a new mid-step timing exception.

---

## M-C. The Haste keyword  *(amends §7)*

**Haste lifts the act-vs-move restriction.** A character with haste may take its normal proactive action (Attack / Cast / Defend / Move) **and also make a voluntary move in the same turn, for free** — the move does not consume the proactive action.

- The free move is a **voluntary** move: it writes `pending_voluntary` and resolves at **End step** like any other voluntary move (§M-B.4–B.5). **Haste does not enable dodging** — the body still relocates only at End step, after the Enemy step, and intents are already locked (§M-B.2).
- Haste is the **sister of `vigilance`** (§7): vigilance unlocks *attack-and-cast* on the action axis; haste unlocks *act-and-move* on the movement axis. Each grants a second thing in one turn.
- **Uses for haste:** (a) attack from the Front, then free-move back to a safer row at End step ("hit hard, don't stay exposed"); (b) intercept off-position for an ally, then free-move back to the front line the same turn, paying the repositioning cost a non-hasted character could not.
- **Scope:** applies symmetrically to enemies and ally tokens (a hasted enemy executes its intent and repositions, with no new timing exception).

§7 should gain a `haste` row beside `vigilance`: *"may take its proactive action **and** make a free voluntary move this turn (the move still resolves at End step)."*

---

## M-D. Worked examples

**1. The caster-interception case (why committed ≠ current).**
Soren starts in Mid. He makes a melee attack → forced move writes `committed = Front` (his body is still physically in Mid). An enemy ranged attack is declared against Ys in the Rear. Soren wants to intercept. Adjacency is checked against his **committed** row (Front); Front is not adjacent to Rear → **the interception is illegal.** Committing to the swing committed him to the front line, so he cannot also guard the back. At End step, with no voluntary move queued, `current ← committed = Front`.

**2. Haste hit-and-retreat.**
A hasted, lightweight melee attacker in Mid attacks → `committed = Front`. It then uses its free haste move, choosing Mid → `pending_voluntary = Mid` (this does **not** change `committed`, which stays Front, so it could not reach-check from Mid this turn). It takes no further reactions. At End step, `current ← pending_voluntary = Mid`. It struck from the front and ended safe in Mid before the next Intents step.

**3. Multi-hit interception (the soak fantasy, and its cost).**
A 3-hit enemy action (4 / 4 / 4) targets Ys in Mid; Soren (current Power 3, so X = ceil(3/2) = **2**) is in Mid (adjacent — same row). Soren ally-Mitigates: all three hits redirect to him, each reduced to `max(0, 4−2) = 2`, so Ys takes 0 and **Soren takes 6** off one reaction. `committed = Mid` (no change here). The threat was answered but not deleted — it landed on a body and attrited it — and against a bigger Swarm a multi-hit intent can genuinely threaten to drop the tank, which is the counterplay that keeps interception honest.

**4. Negation threshold (and where it now sits).**
A 4-hit Swarm of 2s targets Soren (Power 3, X=2, self-Mitigate): each hit `max(0, 2−2) = 0`, so he still fully negates the *smallest* Swarm. But raise the Swarm to 3s and it leaks: `max(0, 3−2) = 1` per hit → **4 through** off the same reaction, where full-Power mitigation would have absorbed it entirely. Halving X is exactly what moves Swarm from "bounces off tanks" to "tanks blunt it but still bleed" — the intended attrition.

---

## M-E. Cross-references and glossary deltas  *(amends §13)*

- **Parry → Mitigate** everywhere, including Update 01 §R-12 (first strike's "mitigation reaction" now reads "Mitigate reaction").
- **Mitigate** *(new glossary entry)* — the free, once-per-turn defensive reaction answering an attack-type action; reduces each hit by **ceil(the mitigator's current Power / 2)**; in ally mode redirects the protected ally's hits onto the mitigator and moves the mitigator's committed position to that ally's row.
- **Move** *(new)* — repositioning between rows; a voluntary Move costs the proactive action (no mana, any destination row) and resolves at End step.
- **Current position / committed position** *(new)* — physical row (what intents hit, changes only at End step) vs. committed row (what the character's own actions/reactions read, changes immediately on forced moves).
- **Forced move / voluntary move** *(new)* — a move that is a built-in consequence of an action (writes `committed` immediately) vs. a chosen move (writes `pending_voluntary`, resolves at End step).
- **Haste** *(new)* — proactive-action-plus-free-voluntary-move; sister of vigilance; never dodges (move resolves at End step).
- **Wall** *(informal)* — the passive melee shielding provided by occupying the front-most row.
