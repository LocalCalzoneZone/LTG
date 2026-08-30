# LTG Design Update 22 — Counters & Countdowns

Four related mechanics changes: charge counters become *readable*, poison and
regen counters become *the clock itself*, enchantments gain a self-terminating
verb, and triggers gain an authorable turn countdown. Plus an editor pass on
the effect and reference dropdowns.

## §D22-1 — Charge counter references

Charge counters could be granted (the enemy-only `charge` windup verb, §D8-2.4)
but never *used*. Two new value references make the gauge readable, for both
sides of an effect:

- `{"ref": "caster_charge"}` — the caster's charge counters
- `{"ref": "target_charge"}` — the target's charge counters

Both resolve from the live combatant at resolution, mirror the existing
stat-reference pairs, and read 0 on anything that holds no charge.

**Charge opens to players.** Heroes can now hold charge counters too (a plain
resource on the character, distinct from the ultimate gauge), and the `charge`
verb is no longer enemy-only. It gains:

- `op: "add" | "remove"` (default `add`) — remove drains the gauge; with
  `amount: "all"` it empties it (a **defuse** — a windup is now answerable).
- `amount` widened from a plain int to a full Value (refs and multipliers work).
- an optional `target` defaulting to self — enemy components keep authoring it
  targetless; player cards may aim it anywhere (add to an ally, strip a
  gathering enemy).

On an enemy, adding still detonates `on_charge_full` at its threshold. Design
space: build-and-spend cards ("add 2 charge to yourself" … "deal damage equal
to your charge counters, then remove them all").

**Editor pass (same section):** the effect-kind dropdown lists alphabetically,
and the reference dropdown is now grouped and consistently labelled —
`REF_GROUPS` in the schema drives `<optgroup>` sections (This cast / Stats /
Counters / Damage taken / Battlefield / Stored values), with each stat's
(target)/(caster) pair adjacent: *Power (target), Power (caster), Base Power
(target), Base Power (caster), …*

## §D22-2 — Poison and Regen reworked: the counter is the clock

The old model (§D8-2.1/2.2) had two layers: a ticking Affliction *effect* that
re-placed counters each Upkeep, and counters that were folded stat changes
(−0/−1 / +0/+1). Both layers are gone. The counter itself is now the clock:

- **Poison** — each poison counter on a creature makes it **lose 1 life at
  every Upkeep**. Any healing (even a 0-restore heal) removes **all** poison
  counters. The tally never grows or expires on its own. The upkeep tick is
  life loss, not damage: no prevention, no mitigation, no channel break, and it
  never sheds regen. Explicitly *not* a temporary/cumulative −X — placement
  moves no stats.
- **Regen** — each regen counter makes the creature **heal 1 at every Upkeep**
  (real healing: it fires life-gain triggers and, being healing, would cure
  poison). Damage that **connects** (≥1 after prevention/mitigation) removes
  **all** regen counters.
- Poison and regen counters still annihilate 1:1 as a state-based action, so a
  creature never holds both.
- **Infect** now places 1 poison counter per connecting hit (the drain starts
  at the next Upkeep) instead of stacking an unbounded ticking effect.
- The `turns` field on `poison`/`regen` is retired — legacy JSON still loads
  (the field is ignored). Upkeep order is unchanged: party → tokens → enemies,
  poison before regen on each creature.

## §D22-3 — `channel_drop`: the self-terminating enchantment

A new verb that can only live on a channeled card and ends **that
enchantment's own channel** — never a sibling, never a whole creature's set
(that remains `break_channel`). Reserved mana returns to the pool and the
channel's `channel_break` trigger still fires, so a drop can spring a final
sting.

- Targetless and self-referential — the resolver finds the channel the trigger
  fired from.
- Validation: channeled cards only, and it **must carry a trigger** (the fuse);
  untriggered it would end the channel the moment it began. Any trigger works:
  `after_turns`, an event watch ("when an ally dies"), `upkeep` behind a
  conditional, etc.
- Works on enemy channels too (the component's rite drops itself).

## §D22-4 — The `after_turns` trigger

A new trigger form alongside the lifecycle literals and event watches:

```json
{"kind": "deal_damage", "amount": 5, "target": {...},
 "trigger": {"after_turns": 3}}
```

Fires **once**, at the Upkeep N turns after the channel began; the count goes
down one per Upkeep. The client channel summary carries a live `countdown`
field (Upkeeps until the soonest pending countdown), shown in the Channels
modal. The flagship combo with §D22-3:

```json
{"kind": "channel_drop", "trigger": {"after_turns": 3}}
```

— "After 3 turns: this enchantment drops."

## Touched surfaces

Schema (`REF_VALUES`/`REF_GROUPS`, `Poison`/`Regen`, `ChannelDrop`,
`AfterTurnsTrigger`, card validators), engine (`_ref_value`, the typed-counter
section, `_r_channel_drop`, `_due_channel_triggers`), translation (renderers +
the "After N turns:" lead-in), serialize (`countdown`, counter status tags),
game-ui (badges/inspector tooltips, Channels modal countdown), deckbuilder
editor (grouped reference dropdown, "after N turns…" trigger control), LLM
enemy-authoring prompt, loot recipes. Tests: `test_design_update_22.py`;
`test_design_update_08.py` rewritten to the new poison/regen semantics.
