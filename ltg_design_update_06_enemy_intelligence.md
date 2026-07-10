# Langelier Tactical Game (LTG) — Design Update 06: Enemy Intelligence, Counterplay & Encounter Scaling

**Status:** canonical extension of the enemy framework. Assumes the base GDD and Updates 01–05; amends Update 04 (§F-3 vocabulary, §F-7 heuristics, §F-9 bosses) and the encounter-generation contract. Where this document and prior documents disagree, **this document wins.**

**All numbers are playtest starting values.** Mechanisms are canonical; magnitudes are provisional.

---

## E6-0. The core idea

Update 04 gave enemies a *mind* (components on a merged priority list). This update makes that mind **cunning** and the encounter **elastic**:

1. Enemies now act on every player-facing axis the engine supports — including the stack (**counterspells**), shields (**wards**), and held ongoing effects (**channels**, already landed in Update 04's runtime and now first-class in generation).
2. The targeting brain stops wasting actions: heals skip the unwounded, control spreads instead of stacking, assassins read threat.
3. Enrage is a **hard turn**, and bloodied *moments* generalize to minions.
4. An encounter carries **one design, four rosters** — a layout per party size (1–4), resolved when the game starts.

Nothing here adds new resolution logic on the player side: enemy verbs remain §11 primitives resolved by the same handlers.

---

## E6-1. New component vocabulary (amends §F-3)

**Triggers (reactive components)** — added to the §F-3.2 vocabulary:

| trigger | phase | fires when |
|---|---|---|
| `on_attack` | pre | a hero's attack action sits on the stack (the duellist's window) |
| `on_self_below_N` | post | THIS enemy was hit this resolution and now sits below N% max HP — the minion-grade enrage; pair with `once_per_encounter` |
| `on_hero_downed` | post | a hero was incapacitated by this resolution (the pack surges) |
| `on_hero_healed` | post | a hero regained HP / closed a wound this resolution (`trigger_source` = the healer) |

**Conditions** — added to the §F-3 gate vocabulary:

| kind | reads |
|---|---|
| `hero_count` | living (up) heroes — anti-party cleaves, desperation gates |
| `hero_channeling` | heroes currently holding a channel — arms ritual-breakers only when relevant |
| `self_channeling` | this enemy's own held channels — defend-the-ritual behaviour |

**Target rules** — added to §F-7.2:

| rule | picks |
|---|---|
| `wounded_ally` | the most-hurt fellow enemy, or **nobody** (rule skips) when the warband is untouched |
| `highest_threat` | the hardest-hitting reachable hero (ties: caster/ranged role, then lowest HP) |

**Archetypes** — added to the §F-6 price list: **Ward** (prevent/protection shields, base 3) and **Counter** (reactive-only, base 3 + the reactive +2 = net 5).

---

## E6-2. Enemy counterspells (new counterplay axis)

A **reactive component whose verbs include `counter`** answers the stack action that tripped its trigger — the engine aims it at that action's `#uid` handle, exactly the handle a player's Negate uses. Rules:

- **Pre-resolution triggers only** (`on_spell_cast` for a counterspell, `on_attack` for a parry); there is nothing to counter post-resolution. The verb carries no target field.
- The counter **sits on the stack itself** and reopens the party's window: the party can respond to it (including countering the counter, if they hold one that answers its kind — `spell`-classed counters stack as spells).
- `_r_counter` is now side-symmetric: a counter cancels any hostile stack action matching its filter; **you can never counter your own side's action.**
- Design guidance (encoded in the generation prompt): at most **one** counter-piece per encounter, always on a cooldown (2–3). Scarce = thrilling; spammed = miserable.

## E6-3. Wards & smart support (stop wasting actions)

- `prevent` / `protection` verbs are now first-class enemy tools (Ward archetype): a bodyguard shields the channeler or the boss, layering kill-priority.
- A support rule whose verbs are **pure heals** skips allies at full HP (under `lowest_hp_ally`), and `wounded_ally` is the strict form that only fires when someone is actually hurt — the healer attacks instead of wasting its turn.
- **Control spreads**: a stun rule skips already-stunned heroes; a taunt rule skips already-taunted heroes. Two control pieces no longer overwrite each other; emptying the candidate list makes the rule skip (first-match-wins moves on).

## E6-4. Enrage as a hard turn (amends §F-9)

Crossing 25% now does three things at once, on top of opening the execute window:

1. **Shakes off control** — any stun charges and taunt on the boss drop. Fury does not sit out a turn.
2. **Resets component cooldowns** — the post-enrage kit opens at full aggression. `once_per_encounter` firings stay spent (the drama never repeats).
3. **Fires the Enrage component** as before (`on_enrage`, once) — now expected to be a **multi-verb eruption** (permanent counters + an AoE + a summon/heal/keyword), not a single pump.

Minions get their own moments via `on_self_below_N` + `once_per_encounter` — the "bloodied roar" pattern — so fights stay dynamic away from the boss.

## E6-5. Enemy channels in generation

The Update-04 runtime (EnemyChannel: continuous `while_channeled` verbs + recurring `upkeep` ticks, broken by a ≥25%-max-HP hit or removal, counterable on the stack) is now a **required generation pattern**: standard difficulty and above must field at least one channeler. Recommended pairings: a `self_channeling` condition on the channeler's defensive rule, or a Ward bodyguard aimed at it.

---

## E6-6. Party-size layouts (encounter scaling)

An encounter file may carry:

```json
"layouts": {
  "1": ["wolf", "shaman"],
  "2": ["wolf", "wolf", "shaman", "alpha"],
  "3": ["wolf", "wolf", "shaman", "shaman", "alpha", "alpha"],
  "4": ["wolf", "wolf", "wolf", "shaman", "shaman", "alpha", "alpha", "alpha"]
}
```

- **One pool, four rosters.** `enemies` is the design pool; each layout lists pool ids. **Repeats clone** (`wolf`, `Wolf 2`) with unique runtime ids.
- **Resolution at game start:** `scale_encounter(scenario, party_size)` fields the layout matching the starting party, clamping to the nearest defined size (a party of 5 uses `"4"`; below every key, the smallest). No `layouts` key = fixed roster (all hand-authored content unchanged).
- **Validation (save gate):** layout ids must exist in the pool; a boss appears in **every** layout; every per-size roster must build in the engine (clones included).
- **Validation (generation gate):** layouts `"1"`–`"4"` are required; each must field at least **2× the party size** bodies (duplicates count) and target the per-size Level budget **2 × size × avg level × difficulty** (a boss counts double).
- The Options list and New Game modal badge scaling encounters ("scales 1–4"); the encounter editor round-trips layouts, pruning ids an edit removed (an emptied layout falls back to the full roster).

---

## E6-7. Playtest rulings (amend GDD §7 and §8)

**Hexproof does not stop basic attacks.** Hexproof wards off targeted **spells and abilities** only, in both directions: a hero's basic attack lands on a hexproof enemy, and an enemy's basic attack lands on a hexproof hero (declaration, taunt-forcing, and resolution all ignore hexproof for attack-kind actions). Targeted enemy *components* (Venom Spit, a curse) still fizzle on a hexproof hero, and players still can't aim targeted spells at a hexproof enemy. Consequences: a hexproof channeler can be broken by attrition with the sword, and a hexproof hero can taunt/lure freely (the forced action is an attack).

**Party turn order is a fixed initiative.** Rolled once at encounter setup (a seeded shuffle of the party; the authored order when unseeded) and constant for the whole fight — repositioning never reshuffles whose turn comes next. It lives on `GameState.party_order`, is announced in the turn-1 log (`turn_order` event), and drives main-phase order, the capacity-lock order, and the pass-around order in reaction windows. This replaces R-6's row-based ordering **for the party only**; enemies and ally tokens keep the row-canonical order.

**Priority starts with the caster.** When a player puts an action on the stack, that player holds priority first (they hit Pass first — and may respond to their own action), then priority moves through the other players in turn order. A responder's cast makes the responder the new first-speaker on the new top; when a nested item resolves, priority returns to the caster of the action now on top. Enemy-sourced stack tops seed at the top of the party's turn order.

**Channels drop at instant speed, any time.** A held channel may be voluntarily dropped whenever the holder has priority — main phase **or any reaction window**, including the turn it was cast (supersedes GDD §8's same-turn hold rule). The reserved mana releases straight to the pool, so a drop inside a reaction window can immediately pay for a different instant. The balance argument: the channel's ongoing effect stops the moment it drops, so an early drop forfeits value rather than banking it; `channel_break` riders still go on the stack and can be answered.

## E6-8. Generation contract changes (summary)

- The system prompt teaches: Ward + Counter archetypes, the four new triggers, three new conditions, two new target rules, channel-first design, multi-verb enrages, and the layouts contract with per-size budgets; all three gold examples carry layouts and the new patterns (a ritual channel, a counterspell sentinel, a bloodied moment, `wounded_ally` healing).
- The per-request block now emits **four budget lines** (sizes 1–4) instead of one, so a single generation serves any party. The `counter` verb moved off the forbidden list (reactive-only).
- Tests: `tests/test_enemy_counterspell.py`, `test_enemy_intelligence.py`, `test_enemy_bloodied.py`, `test_enrage_dynamics.py`, `test_encounter_layouts.py` (which also validates the prompt's gold examples through the full save gate).
