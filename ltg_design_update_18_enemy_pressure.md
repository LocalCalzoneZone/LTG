# Langelier Tactical Game (LTG) — Design Update 18: Enemy Pressure

**Status:** IMPLEMENTED 2026-08-22 (`apps/combat/ltg_combat/engine.py`, `apps/combat/ltg_combat/serialize.py`, `apps/game-server/ltg_game_server/content.py`, `apps/game-server/ltg_game_server/llm.py`, `apps/game-ui/src/components/Battlefield.tsx`, `tests/test_design_update_18_enemy_pressure.py`).

**Origin (playtest).** One session, four complaints, one root: enemies were spending their turns on gestures. Taunts that moved no number. "Combat abilities" that hit for less than the creature's own sword — and fired every turn instead of it, so the balance register's Power bump was dead weight. A boss reaching its climax and awarding itself +2/+2 in front of a four-hero party. Row assaults that fizzled to Hexproof, told the party an attack was coming at "a row" without saying which, and lit the board only sometimes.

## D18-1. A taunt never fires alone

A taunt on its own is a **skipped turn**: the enemy points a hero's sword somewhere, no number moves, and a whole activation evaporates. Stun is different — losing a turn *is* the payload — but taunt only redirects an attack the hero was going to make anyway.

- **Engine** (`_taunt_with_teeth`): any enemy verb list carrying `taunt` and no damage gains a `deal_damage` for the enemy's **current** Power (register and stacked counters included), aimed at the same body the taunt drags. Applied on both the proactive intent and the reactive path, so the 22 taunt components already in `content/` bite without a content rewrite.
- **Generation**: `llm._taunt_problems` rejects a taunt component that deals no damage, wired into the `generate_encounter` and `generate_adventure` problem blocks beside the §D14 kit floor. The prompt states the rule and both gold examples now pair the grab with the blow.
- Player-side taunt (Lure, the continuous channel form) is untouched: it is a *card* the player spent, not an activation the enemy wasted.

## D18-2. The balance register carries the abilities, and the Enrage sees the party

The §D4 magnitude table is keyed to `L` — **the individual enemy's own level**. It is not the party's level and not a cumulative one. Party size was answered only at the *encounter* level: the budget is `2 × party_size × avg_party_level × difficulty` (the sum of enemy levels) plus `_min_enemies = 2 × party_size` bodies. So a bigger party met *more and higher-level bodies*, while every individual ability still hit one hero for `L+1`. Per-enemy pressure was flat while the party's action economy grew.

Worse, the T-64 balance register lifted **only** the basic swing (+2 Power, +4 boss). Component magnitudes stayed on the authored curve, so a bumped enemy's "special" hit for less than its own sword and every ability read as a downgrade.

The register (`content._bump_enemy_power`, mirrored in `autoplay/runner.py`) now covers:

| lift | value |
|---|---|
| chassis Power + attack templates | `+2` (`+4` boss) — unchanged (T-64) |
| hostile component `deal_damage` / `lose_life` | `+2` (`+4` boss) |
| …on a row/blast shape | `+2` more — it is **dodgeable**, so it lands harder |
| boss `Enrage` | scaled by party size instead (below) |

Heals, self-pumps and support magnitudes are left alone outside an Enrage: the register is about the pressure the party feels, not enemy bookkeeping.

**Enrage scaling** (`content.enrage_scale`) returns `(lethality, padding)` for a party of `n`:

- **lethality = `n`** — the Power half of a `counters`/`pump`. A four-hero party brings four times the damage and four times the actions to the same climax; the fury has to threaten a board that size.
- **padding = `1 + (n−1)/2`** — the toughness half, the AoE, the heal. An enrage should hit *much* harder, not merely last much longer.
- `create_token` count gains `n−1` bodies.

An authored `+2/+2 and burn 3` reads `+2/+2, 3` solo and `+8/+5, 8` against four heroes. The Enrage takes the party scale **instead of** the flat ability bonus, never both.

The prompt's authored table also rises (`deal_damage = L+2`, `Escalate = +2/+2`, `pump/wound = ±(ceil(L/3)+1)`, `lose_life = ceil(L/2)+1`, `Drain = ceil(L/2)+2`), with the register on top.

## D18-3. The sword competes with the kit

The §F-7.1 proactive pass takes the top READY component every single turn and only falls through to the basic attack when none is ready. A kit with any short-cooldown rule therefore *never swung*.

Two rules, both in `_pick_enemy_intent`:

1. **Outclass** (`_outclassed_by_the_sword`). A **pure single-target damage** component that deals no more than the basic attack would is passed over, so the sword lands instead. Anything with a rider (a stun, a wound, a heal, a summon), anything row/blast-shaped, and anything aimed at itself or an ally is a different *kind* of turn and is never suppressed. A component earns its slot by hitting harder, hitting several bodies, or doing something the sword cannot.
2. **Cadence** (`ATTACK_CADENCE = 2`, `EnemyState.rounds_since_swing`). After two consecutive non-attack intents the basic attack is taken outright. A boss's second fury slot never forces — slot 1 has already satisfied the cadence, and two identical swings a round is the drum-beat §F-9 warns about.

The prompt states both, so generated kits are designed for the mix: an enemy shows its kit, then swings.

## D18-4. A row shape aims at GROUND, not at a name

A row assault is the game's movement pressure: telegraphed a full turn ahead, the board lights the row, and the party's answer is to **walk out of it**. §L-5 positional components (`target_row` on the component) already worked that way — but only 8 of the 318 shipped components used it. The other 26 row shapes were authored as §D9-3.2 "a chosen hero **and their whole row**" (`scope: "row"` on a targeted pick), which is a *targeted* effect. Three consequences, all reported from the table:

- **Hexproof fizzled the whole area** — the pick was warded, so the splash never happened; with an all-hexproof row the rule was skipped at declaration outright.
- **The telegraph named no row** — "prepares an assault on a row of your party". No reason to move.
- **The board lit nothing** — the client's highlight reads `target_row`, which such an intent never set.

`_row_shape_footprint` converts them at declaration: the valuation brain chooses the ground (blind to Hexproof — a hero who cannot be *targeted* still stands somewhere), the pick is discarded, and the verbs are normalised onto the row footprint (`row` = one row, `blast` = that row and its neighbours). The intent then carries `target_row` and no `target_id`, exactly like an authored positional one.

Guard: a component whose verbs are **not** all hero-side or self-aimed — a corpse-burst that also exiles a corpse, a rule that shields an ally — keeps its own pick and runs down the ordinary path. Discarding its target would silently drop half the ability.

**Hexproof generally.** `_pickable` now drops hexproof heroes from a component's candidate list **only when the component has a genuinely targeted verb**. An untargeted area piece, a corpse-raise, or an untargeted lockdown used to skip its whole rule against a hexproof party — the enemy stood there doing nothing.

**Telegraph and board.** `serialize.intent_rows` reads the footprint off `target_row` and, failing that, straight back off the verbs — so hand-authored and legacy shapes name their ground too. The veiled line reads "*Gore prepares an assault on your front row.*" (a blast names all three). The snapshot ships `target_rows` on both the intent and the stack item, and the client lights every row in the footprint **from declaration until the blow has actually resolved** — the old highlight dropped the moment the intent reached the stack, which read as a flicker.

## D18-5. Non-goals

- No pricing change: the §D4 cost tables and `enemy_analysis.py` mirrors are untouched. Archetype, not magnitude, sets a component's cost.
- No content rewrite. Every rule above lands on the 318 components already in `content/` through the engine and the register; the prompt and gate changes only govern what is generated next.
- `taunt` stays in the schema and in the player's toolkit (Lure). Only the *enemy authoring* of a bare taunt is closed.
