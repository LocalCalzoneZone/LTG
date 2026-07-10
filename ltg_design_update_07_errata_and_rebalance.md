# Langelier Tactical Game (LTG) — Design Update 07: Errata & Rebalance

**Status:** canonical errata against the base GDD and Updates 01–06. Where this document and prior documents disagree, **this document wins.**

**Purpose.** The engine, the Deckbuilder, and the generation layer moved ahead of the design documents in several places. Nothing here is a new design decision — every entry **records a rule the code already enforces** and names the file that enforces it, so the documents describe the game as built. Two `[OPEN]` items from the GDD are also resolved by observation, and three keywords the GDD lists as pending are confirmed shipped.

**All magnitudes remain playtest starting values.** Mechanisms are canonical; numbers are provisional and collected in §X-7.

---

## X-0. The drift, in one table

| # | topic | documents say | code does | §  |
|---|---|---|---|---|
| 1 | deck size & rarity | 40 cards; caps 2/6/12/20 | **20 cards; minimums 1/3/6/10, commons uncapped** | X-1 |
| 2 | effect vocabulary | 24 verbs incl. `disable` | **25 verbs; `disable` gone, `fight` + `move_card` added** | X-2 |
| 3 | `double_strike` | not mentioned anywhere | **a shipped, grantable keyword** | X-3 |
| 4 | `lifelink` | `[OPEN — confirm]` | **resolved: heals for damage that connects** | X-3 |
| 5 | `trample` / `first strike` / `scry` | flagged deferred or inert | **all three fully implemented** | X-4 |
| 6 | encounter difficulty | ×0.75 / ×1.0 / ×1.5 | **×1.0 / ×1.5 / ×2.5, plus a post-generation HP multiplier** | X-5 |

---

## X-1. Deck construction  *(amends §4.5)*

A loadout is a **20-card singleton library**, not 40. Rarity is a set of **minimums**, not caps:

| rarity | quota | capped? |
|---|---|---|
| mythic | 1 | yes (quota is exact) |
| rare | 3 | yes |
| uncommon | 6 | yes |
| common | 10 | **no — a floor only** |

**Reading the quotas.** The non-common rarities are *exact*: the minimum is also the cap. Common is a floor with no ceiling. So a deck may exceed 20 cards **only** by adding commons — the power tiers stay fixed while the filler grows. This is what makes rarity a meaningful power dial (and, later, a leveling dial) rather than a budget you can spend anywhere.

**Everything in deck status is advisory.** It warns; it never blocks save, export, or play. That was already true of the 40-card rules and is unchanged.

The singleton rule (no duplicate source cards), the draw-and-keep library, the archetype-set starting hand, and the one-card-per-upkeep draw are all unchanged.

*Enforced by:* `DECK_MINIMUM`, `RARITY_MINIMUMS`, `UNCAPPED_RARITIES`, and `deck_status()` in `core/ltg_core/schema.py`.

---

## X-2. The effect vocabulary  *(amends §11; extends Update 01 §R-11)*

The vocabulary is **25 primitives**. Update 01 §R-11 already retired `disable`; the GDD §11 list was never updated to match, and two primitives have since been added. The current, complete set:

```
deal_damage  heal      lose_life  destroy   exile
bounce       fight     counter    strip_intent  stun
pump         wound     counters   prevent   protection
draw         scry      move_card  create_token  taunt
revive       grant_keyword  remove_keyword  ramp  add_mana
```

The cardinal rule is unchanged and remains the whole point of the vocabulary: **effects declare intent; they never execute logic.**

### X-2.1 `fight` *(new)*

Two creatures fight: **each deals damage equal to its Power to the other, simultaneously.** It carries **two** target descriptors — `target` (the creature you control) and `other` (the creature it fights) — rather than the single target every other creature-facing primitive takes.

Both are chosen at cast, so a card authors them as **two shared target slots** (`T1` ally, `T2` enemy) and links each target field to its slot. Simultaneity matters: a `fight` that kills both creatures kills both, and neither death trigger pre-empts the other.

### X-2.2 `move_card` *(new)*

The **general card-logistics primitive**. `draw` survives as its common special case, and both remain in the vocabulary — a card that only draws should keep saying `draw`.

```
move_card {
  count, source, destination,
  filter_type?,                       # instant | sorcery | channeled
  filter_level_compare, filter_level, # comparator 'any' disables the level filter
  shuffle_after,
  target                              # always self — you move your own cards
}
```

`source` ∈ `drawn` · `library_top` · `library_bottom` · `library` · `hand` · `graveyard` · `exile`.
`destination` ∈ `hand` · `library_top` · `library_bottom` · `library_shuffle` · `graveyard` · `exile`.

This is what expresses a tutor (`library` → `hand`, filtered, `shuffle_after`), a graveyard recursion (`graveyard` → `hand`), a self-mill (`library_top` → `graveyard`), and the bottom half of `scry`, without a primitive apiece. Because a target with no library is nonsense, `move_card` — like `draw` and `scry` — is rejected by validation if it resolves to an enemy.

### X-2.3 `revive` carries a fraction  *(amends §R-11)*

Update 01 §R-11 fixed `revive` at **half** max HP. It is now a parameter: `to_fraction`, **defaulting to 0.5**, so the R-11 behaviour is the default rather than the rule. The restored HP is `max(1, floor(max_hp × to_fraction))`, and reviving clears the target's `temp_mod` — a revived character comes back clean, not carrying the wound that downed it.

---

## X-3. Keywords  *(amends §7)*

### X-3.1 `double_strike` *(new — was undocumented)*

**`double_strike` — the basic attack strikes twice.** It is a full member of the keyword registry: grantable by `grant_keyword`, removable by `remove_keyword`, and honoured by the engine on both the ordinary attack and the `first strike` held-attack reaction (a character with both strikes twice, as a reaction).

It appears in **no** prior design document. It should have; it is shipped, tested, and player-facing. Add a `double strike` row to the §7 table.

It is **not** buyable at creation (Update 05 §P-3's keyword list is unchanged and does not include it) and it is **not** enemy-eligible (Update 04 §F-5 is unchanged). Today it reaches the board only by being granted.

### X-3.2 `lifelink` — `[OPEN — confirm]` resolved

GDD §7 flagged lifelink's meaning as open. **Resolved as written:** the source **heals equal to the damage it deals** — specifically, equal to the damage that actually **connects**.

The distinction is load-bearing. A hit reduced to 0 by Mitigate, or fully absorbed by a `prevent`, heals the lifelinker for **nothing**. A hit reduced from 4 to 2 heals for **2**, not 4. Damage that a shield swallows never happened, so it feeds neither lifelink nor deathtouch.

This interacts with Update 02 §M-A.5 exactly as that section states: when an ally-Mitigate redirects a hit, lifelink fires off **the mitigator's** post-mitigation damage, because that is where the damage landed.

### X-3.3 `trample` — the cleave rule, made precise

GDD §7 says excess damage "overflows to another target on the same or an adjacent row." The engine's rule is narrower than that phrasing permits, and this is the canonical form:

- Trample triggers only when the primary target **falls** (damage exceeds its HP). The excess is `damage − hp`.
- The excess spills onto **exactly one** further creature — not a spread, not a chain. That creature is picked from the felled target's **own side**, on its row or an adjacent row (front and rear are not adjacent), by **lowest effective HP**, then row order, then name. Fully deterministic.
- The carry target must be **legally strikable by the attacking mode**: a ground melee swing cannot cleave onto a Flying creature.
- The carried damage is **combat damage** and goes through the carry target's **own** mitigation. It does not bypass a shield, and it **does not cleave again** — a single carry, always.
- **No legal carry target → the excess is lost.**

*Enforced by:* `_trample_cleave()` in `apps/combat/ltg_combat/engine.py`.

---

## X-4. Three deferrals that are no longer deferred

Update 01 §R-11/§R-12 and the project's status notes flagged these as stored-but-inert, pending a decision point. **All three are implemented.** No design document should describe them as pending.

- **`first strike`** — implemented per §R-12. The character may spend its proactive action on Move / Defend / Cast and **hold its basic attack as a reaction** during the enemy step, where it stacks above the answered action and so **resolves first, and may kill the attacker before its attack lands**. It still consumes the once-per-round basic attack, and a `prevent attack` still forbids it.
- **`trample`** — implemented; see §X-3.3 for the exact cleave rule.
- **`scry`** — implemented per §R-11, including the **leave-on-top or move-to-bottom choice**. It is a genuine mid-resolution decision point: the engine raises a pending choice and pauses, exactly as it does for a `move_card` pick.

The only keyword-adjacent item still genuinely unbuilt is the one Update 01 §R-13 flagged: the **ordering between the continuous loss-check and pending stack items** on simultaneous total-party incapacitation. That remains open.

---

## X-5. Encounter difficulty & enemy durability  *(amends Update 04 §F-6, T-37/T-38)*

Playtest found the base fight far too easy: chassis HP baselines (Husk 2, Bruiser 4, Caster-frame 2) are low enough that **one removal spell plus a chip effect clears an enemy**, and the old difficulty band topped out below the party's actual throughput. Two changes, both landed in code.

### X-5.1 Difficulty multipliers, raised  `[T-38, amended]`

The encounter Level budget formula is unchanged — **`2 × party_size × avg_party_level × difficulty`**, a boss counting double — but the multipliers are:

| difficulty | was | **is** |
|---|---|---|
| easy | ×0.75 | **×1.0** |
| standard | ×1.0 | **×1.5** |
| hard | ×1.5 | **×2.5** |

Note the consequence: **the old "hard" is roughly the new "standard."** An encounter authored against the Update 04 numbers will read as one band easier than its label.

### X-5.2 Post-generation HP multiplier  `[T-40, new; lowered]`

Every generated enemy's HP is multiplied **in code, after the model returns**, by:

| difficulty | was | **is** |
|---|---|---|
| easy | ×1.5 | **×1.0** |
| standard | ×2.0 | **×1.2** |
| hard | ×2.5 | **×1.5** |

**Why lowered.** The first pass overcorrected. Playtest read on the raised numbers: a "hard" fight was not harder to *solve*, only longer to *finish* — the party's line of play was unchanged and each enemy simply absorbed more turns of it. HP is the one knob that buys duration without buying decisions. Difficulty should come from the encounter Level budget (§X-5.1) and from being outnumbered (§X-5.3), both of which add enemy actions the party must answer. Note easy is now ×1.0 — a deliberate no-op, kept in the table so the knob stays uniform.

**Why in code and not in the prompt.** The multiplier is applied outside the model's control on purpose. It guarantees the beef regardless of what the model returns, and regardless of how a user has edited the (fully editable) system instructions. A prompt instruction can be ignored, drifted from, or edited away; a multiplier cannot.

**This does not re-price the enemy.** HP is scaled *after* Level is derived from budget (§F-6), so the multiplier does not feed back into cost, and a scaled enemy keeps the Level its components earned. The budget prices an enemy's **complexity**; the multiplier tunes the fight's **length**. Keeping them separate is what lets durability be retuned without re-levelling every enemy in the game.

### X-5.3 Minimum bodies  `[T-41, formalised]`

Independent of budget, every layout must field **at least 2 × party size** enemies (duplicates count) — **the party is always outnumbered.** Update 06 §E6-6 states this as a generation gate; it is restated here as a standing property of every encounter, authored or generated.

### X-5.4 Where these live

`DIFFICULTY`, `ENEMY_HP_MULT`, and `_min_enemies()` in `apps/game-server/ltg_game_server/llm.py`. All three are tuning knobs; they are expected to move again. Boss budget (`× 2.5 × B(L)`, `[T-39]`) is unchanged and is taught to the model in the generation prompt.

---

## X-6. A note on keeping these documents true

Every entry above is drift in the same direction: the code learned something and the documents did not. The three durable cross-checks, all cheap:

1. **The primitive list** is `LEAF_EFFECT_CLASSES` in `core/ltg_core/schema.py`. Adding a class there without adding a §11 row is how §X-2 happened.
2. **The keyword table** is `KEYWORDS` in the same file, and it carries a gloss per keyword. Adding a keyword there without a §7 row is how §X-3.1 happened.
3. **The tunables** are the Rebalance Registers (Update 04 §F-10, Update 05 §P-8, and §X-7 below). A magnitude that lives in code without a register ID is a number nobody will ever find again — which is how §X-5 happened.

The deck-size change (§X-1) escaped all three, because deck construction has no register. It does now.

---

## X-7. Rebalance Register deltas  *(amends §F-10)*

Amended:

| ID | was | **is** | sets |
|---|---|---|---|
| T-38 | 0.75 / 1.0 / 1.5 | **1.0 / 1.5 / 2.5** | encounter difficulty multipliers |

New:

| ID | value | sets |
|---|---|---|
| T-40 | 1.5 / 2.0 / 2.5 | post-generation enemy HP multiplier, per difficulty |
| T-41 | 2 × party size | minimum enemy bodies per layout |
| T-42 | 20 | deck minimum card count |
| T-43 | 1 / 3 / 6 / 10 | rarity quotas (mythic / rare / uncommon / common); commons uncapped |
| T-44 | 0.5 | `revive` default `to_fraction` |

Unchanged and reaffirmed: `B(L) = 5L + 5` `[T-36]`, encounter budget `2 × size × level` `[T-37]`, boss budget `× 2.5` `[T-39]`.

---

## X-8. Glossary deltas  *(amends §13)*

- **`fight`** *(new)* — a primitive in which two creatures simultaneously deal damage equal to their Power to each other; carries two target descriptors (`target`, `other`), authored as two shared slots.
- **`move_card`** *(new)* — the general card-logistics primitive: move *n* of your own cards between zones, optionally filtered by type and level, optionally shuffling after. `draw` is its common special case.
- **double strike** *(new)* — the basic attack strikes twice; grantable, honoured on the `first strike` held-attack reaction, not buyable at creation and not enemy-eligible.
- **Connects (damage)** *(new)* — damage that survives mitigation and prevention and actually lands. Lifelink, deathtouch, and every on-damage trigger read damage that **connects**, never damage as declared.
- **Carry target** *(new)* — the single further creature a trample cleave spills onto: same or adjacent row, same side as the felled target, lowest effective HP, legally strikable by the attacking mode.
- **Rarity quota** *(updated, §4.5)* — the per-rarity card count in a 20-card deck (1/3/6/10). Exact for mythic, rare, and uncommon; a floor for commons, which alone may exceed 20.
- **HP multiplier** *(new)* — the per-difficulty factor applied to every generated enemy's HP *after* Level is derived, tuning fight length without re-pricing complexity.
