# Langelier Tactical Game (LTG) — Design Update 01

**Status:** canonical resolutions and errata against *LTG Game Design Document*. Each entry names the original section(s) it amends. Where this document and the original GDD disagree, **this document wins**. Items previously marked `[OPEN]` that are resolved here should have their tags removed in the next GDD revision; a short list of edges still genuinely open appears in §R-13.

---

## R-1. Rows, attack modes, and reachability  *(amends §4.1, §6, §7)*

LTG attacks now carry an explicit **mode**: `melee` or `ranged`. This replaces the single under-specified melee-reach rule and absorbs the §4.1 `[OPEN]`.

**Melee.** A melee attacker may strike only the **front-most occupied enemy row** — i.e. it may hit a creature in a given row only if **no creatures occupy any row ahead of it** (priority Front > Mid > Rear). An empty front row exposes the row behind it.

**Ranged.** A ranged attacker may strike **any row**, ignoring the front-line shield. Ranged attacks may also strike **flyers**.

**Flying.** A flyer may itself attack as melee or ranged (its mode is fixed per the profile in §R-7). On **defense**, a flyer can be struck **only** by: (a) ranged attacks, (b) other flyers, or (c) a creature with **reach**. A non-flying melee attacker without reach cannot hit a flyer at all.

**Reach.** Reach does two things, both keyed to melee + flyers:
1. It lets the reach creature **strike flyers with its own melee attacks** — but normal melee row restrictions still apply to that strike (the flyer must be in the front-most occupied row to be hit).
2. It **re-imposes row restrictions on an attacking enemy melee-flyer**: a melee-flyer cannot strike rows *behind* a reach creature. (Reach does **not** affect ranged attackers, flyers or otherwise.)

**Enemy attacks are likewise classified `melee` or `ranged`** and obey all of the above.

The §7 keyword table entries for `flying` and `reach` should be rewritten to match this; the previous "reach = flyers can't hit behind it" wording is incomplete and is superseded.

---

## R-2. lifelink confirmed  *(amends §7)*

`lifelink` heals its source for **the amount of damage it deals**. Remove the `[OPEN — confirm]` tag.

---

## R-3. Power is a base stat; archetypes gain an attack profile  *(amends §4.7, §10)*

Every character has an **attack profile** = `(mode, power)`, sitting alongside HP / hand / mana in §10. Basic-attack damage = Power. Defaults:

| archetype | attack profile |
|---|---|
| **Fighter** | melee, Power **3** |
| **Tactician** | **ranged Power 1** *or* **melee Power 2** — chosen at character creation |
| **Channeler** | **ranged Power 1** *or* **melee Power 2** — chosen at character creation |
| **Caster** | **ranged Power 2** *or* **melee Power 1** — chosen at character creation |

For the optioned archetypes the choice is **fixed at creation** and static thereafter.

**Test party (§10):** Soren (Fighter) = melee/3; **Ys (Tactician) = ranged/1**.

**Power on the curve:** Power joins HP / hand / mana / rarity-caps as a `[PLANNED]` per-archetype growth stat. **For now, all balance is done at level 1.**

---

## R-4. Turn / step / round terminology  *(amends §4.2, §4.6, §13)*

- **Turn** = the entire sequence from Upkeep through End.
- **Step** = each sub-phase of a turn.
- **Round** = a cycle *within the Player step*: characters act in rounds until all have taken their action / passed.

**Canonical step order:**
**Upkeep → Draw → Intents → Player → Ally → Enemy → End.**

The **Intents** step covers both enemies **and** allies (see §R-5). Replace every overloaded use of "turn" in §4.6 and the glossary accordingly: "once per round" abilities reset at Upkeep and recur each round of the Player step; per-turn things (draw, curve-up, intent declaration) happen once per turn.

---

## R-5. Autonomous allies get their own step  *(amends §4.2, §9.3, §9.6)*

The **Ally step** runs **after the Player step and before the Enemy step**. Allied tokens **declare their intents during the Intents step** (alongside enemies) and **execute in the Ally step**. Allies select moves with the **same deterministic heuristics as enemies (§9.3)** — never an LLM at runtime — applied on the party's side.

---

## R-6. Deterministic ordering  *(amends §4.2, §5.3)*

Wherever multiple actors resolve in one step, and for reaction-window priority, the order is fixed:
**row (Front > Mid > Rear) → Level (low to high) → name (alphabetical).**
Incapacitated player-characters are **skipped** in both action sequencing and reaction windows.

---

## R-7. HP, damage, wounds, incapacitation — unified model  *(amends §4.3, §4.9, §7)*

Model every combatant as:

- `max_hp` — base maximum (raised by persistent `+1/+1` counters).
- `hp` — current base HP; persists across turns within an encounter.
- `temp_mod` — net of end-of-turn temporary HP modifiers: **+X** from `pump`, **−X** from `wound`. Can be positive or negative. **Expires (→ 0) at End step.**
- `effective_hp = hp + temp_mod`.

**Lethality** is always checked on `effective_hp`. **`effective_hp ≤ 0`** → a creature/token **dies** (permanent, *even if indestructible*); a player-character is **incapacitated**.

**Damage** is first absorbed by any **positive** `temp_mod` (the Defend / pump
buffer soaks the blow, down to 0 — GDD §4.9 "a buffer that absorbs a blow"); the
remainder reduces `hp` directly. A **negative** `temp_mod` (a wound) never absorbs
damage. HP loss persists across turns; the temp buffer expires at End step.
- Creatures/tokens at `hp ≤ 0` die.
- **Player-character `hp` floors at 0** — no negative tracking, overkill is discarded. (At 1 HP, hit for 5 → 0 and incapacitated; the extra 4 is lost.)
- *Shield example:* PC at `hp 15`, Defend `+3` (eff 18), takes 3 → temp HP soaks all 3 → `hp 15`, `temp_mod 0` (eff 15). A blow larger than the buffer spills over: `+3` buffer, take 5 → `temp_mod 0`, `hp −2` → `hp 13`.
- On-damage triggers (lifelink/deathtouch) and concentration breaks key off the blow that **connected** (soaked temp HP + HP lost), not just the HP removed.

**Wound (`−X/−X`)** = temporary **−X Power** and **−X to `temp_mod`**. If this drives `effective_hp ≤ 0` it kills/incaps immediately, including through `indestructible`. For a creature this is permanent death even though the modifier was "temporary"; for a PC see recovery below.

**Pump (`+X/+X`)** = temporary **+X Power** and **+X to `temp_mod`** (a buffer that absorbs a blow, then expires).

**Healing priority:** a heal **fills an outstanding negative `temp_mod` first** (cancels the wound toward 0), and only **then** restores `hp`, never above `max_hp`.
- *Wound example:* `temp_mod = −5`, heal 3 → `temp_mod = −2`; at End step it expires → back to start.
- *Damage example:* PC at `hp 1`, takes 5 damage → `hp 0` (incap); heal 3 → `hp 3`, revived.

**Player-character recovery:** a PC returns from incapacitation the **instant `effective_hp > 0`** — via healing, via `revive`, or via a wound's `temp_mod` expiring at End step. Incapacitated PCs **cannot act or react** but **can be healed or revived**. `revive` restores an incapacitated ally to **half max HP** (§R-11).

**Deleted:** the old §4.9 parenthetical "a wound on a life-draining enemy cancels its lifegain" — the new wound model does not interact with healing that way.

**`indestructible` (§7) rewrite:** "cannot be reduced below 1 HP by **damage**; can still be killed by **exile** or by a `−X/−X` driving `effective_hp ≤ 0`."

**`counters` primitive** must always name its kind (e.g. `+1/+1`); never bare `counters`.

---

## R-8. Casting an enchantment is casting a spell  *(amends §4.6, §5.1, §8)*

Casting a `channeled` enchantment **is** a Cast action: it is an **active spell** and **consumes the proactive action** for that turn, exactly like a sorcery. Update §4.6's Cast clause and the §5.1 active/spell cell to include `channeled` alongside `sorcery`.

---

## R-9. Enchantment zones on cast and break  *(amends §8, §13)*

When an enchantment is cast, **the card immediately goes to the graveyard**; the **channeled effect persists on the character independent of card zone** (enchantments are concentration, not board permanents). On **break**, the **channel simply ends** — the card is already in the graveyard. Drop the word "spent"; reword §8/§13 to "the channel ends (the card is already in the graveyard)." The interaction where self-mill/delve consumes the card of a still-held channel is an accepted niche and is not adjudicated specially.

---

## R-10. Boss death vs enrage ordering  *(amends §9.5)*

The **`effective_hp ≤ 0` death-check precedes the enrage trigger.** A single hit large enough to take a boss from above 25% straight to ≤ 0 **kills it outright and skips enrage** (and never opens the execute window — irrelevant, since damage-to-0 is a kill path independent of removal gating). The execute window still gates only the **removal** verbs (destroy/exile/bounce).

---

## R-11. Vocabulary changes  *(amends §11)*

- **`disable` — removed for now.** Re-add later if a real need appears.
- **`taunt`** — redirects enemy intent(s) onto the taunter; **target or all**, per the card. A taunted hit **overrides reach/row restrictions and lands regardless of the taunter's row.**
- **`revive`** — returns an **incapacitated ally to half max HP**.
- **`scry`** — look at the **top card of your library**; choose to leave it on top or move it to the **bottom**.
- **`prevent`** — always carries a parameter: **`prevent [parameter]`**; it nullifies the named thing. Scope is defined by that parameter, and a **`uses`** field fixes *how long the shield lasts* so an "all turn" effect never reads the same as a one-shot:
  - **`uses: all`** (default) — nullify **every** matching instance until the shield's `duration` ends; a hit does **not** spend it. *Fog:* `prevent combat_damage` (all, this turn) = "prevent all combat damage this turn."
  - **`uses: next`** — a one-shot shield that nullifies only the **next** matching instance, then wears off. *Gods Willing:* `prevent combat_damage` (next) = "prevent the next combat damage" to a creature.
  - **Action parameters** (e.g. **`prevent attack`**) forbid the actor from taking that action rather than nullifying incoming damage — they are inherently "all" for their duration. *Pacifism:* channeled `prevent attack` = the enchanted creature **can't attack** while the channel holds (casting it also cancels a swing already telegraphed). This is distinct from `prevent combat_damage`, which only stops damage the target would *receive*.

---

## R-12. First strike  *(amends §7)*

`first strike` lets a character **act or cast on its turn instead of attacking**, then **hold its basic attack as a reaction** — used either to **strike the creature attacking it** (a reaction targeting that attacker) **or** as a mitigation reaction. It still **consumes the once-per-round basic attack**. Chief advantages: you keep your proactive action for a spell, and your reactive strike **may kill the attacker before its attack resolves**. This is narrower than `vigilance` (which grants a free extra action and isn't restricted to your attacker).

---

## R-13. Library exhaustion, token placement, and remaining open edges

**Library exhaustion (§4.5):** an empty library does **nothing** on Draw — you simply don't draw and are limited to your basic attack and other free actions. No fatigue/deck-out penalty.

**Token entry row (§9.6):** created tokens default to the **front** row; a creating effect may name a different row.

**Still genuinely open — flagged, not resolved:**

1. **PC incapacitated by a wound that then expires.** Under §R-7 the PC's `effective_hp` returns above 0 at End step, so it **auto-recovers** with no `revive` needed — a wound functions as a *temporary downing*. Confirm this is intended (vs. incapacitation being "sticky" once entered). Note that any on-incapacitation consequences — most importantly **channel break (§8)** — have already fired and do **not** rewind.
2. **Simultaneous total-party incapacitation.** Win/loss is checked continuously (§4.3). If the last standing PC and another drop to `effective_hp ≤ 0` in the same resolution, does the **loss check fire immediately**, or can an in-flight heal/reaction on the stack rescue the party first? Needs an explicit ordering between the continuous loss-check and pending stack items.
3. **Taunt onto an unreachable target across modes** is resolved for the lands-anyway case (§R-11); only flagged in case you later want a card that *can't* override reach.
