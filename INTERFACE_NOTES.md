# INTERFACE_NOTES.md — LTG-Game (Play UI, Phase 1)

Reconciliation of the coding brief's assumptions (§3.3, §2.x) against the **actual**
combat engine in `apps/combat/ltg_combat`. This is the §0.1 deliverable: read this
before coding the server/UI. "Gap" = something the brief expects that the engine does
**not** currently expose; those are dependencies to raise, not things to fake.

Source of truth read: `engine.py`, `state.py`, `serialize.py`, `scenario.py`,
`server.py` (the existing cockpit). Nothing below re-implements rules — the plan is to
reuse `serialize.py`'s accessors wherever possible and add a thin seat-filtering
serializer on top.

---

## 1. The engine contract (what actually exists)

The whole engine is two pure functions plus a read-only view helper
(`engine.py:69-107`):

- `legal_actions(state) -> [Action]` — the legal choices **for whoever must decide
  right now** (`state.priority`), and **only** that one character. It is *not*
  per-character; at any instant exactly one character (or none) has priority.
- `apply_action(state, action) -> (state', events)` — validates the action against the
  current legal set by `Action.key()` identity, applies it, then auto-runs the
  automatic flow (upkeep → intents → enemy/ally execution → end step) until the next
  player decision. Deep-copies; treats state as an immutable value.
- `settle(state) -> state` — read-only advance to the next decision point, log
  cleared. Use this to produce the *display* state (post-upkeep hand, etc.). The
  cockpit renders `settle(stored)` and computes `legal_actions(stored)` — we do the
  same (`server.py:118-149`).

**Priority holder = `state.priority`** (a character id, or `None`). This is the single
field the brief §2.5 flagged as "the most important gap if missing." **It exists.** The
engine sets it as it walks the turn structure (`engine.py:113-183`). Good — the
multiplayer `prompt` can be built directly from it.

Setup path: `state_from_dict(spec, seed)` builds a pre-upkeep `GameState`
(`scenario.py:160`). For character+encounter composition use
`compose_spec(loadouts, scenario, overrides)` + `state_from_dict`, exactly as the
cockpit's `Session.start()` does (`server.py:65-75`). Seed with
`random.randrange(2**31)` per game for a shuffled opening hand.

---

## 2. `prompt` / `priority.kind` — DERIVED, not a native field

The brief wants `kind ∈ {main_action, reaction, mana_choice, move_choice, card_choice}`
(§2.3). The engine has no single `kind` field, but it is cleanly derivable from state
(mirrors the dispatch in `_legal`, `engine.py:1897-1905`):

| Condition on the settled state                     | `kind`        |
|----------------------------------------------------|---------------|
| `pending_choice is not None`                       | `card_choice` |
| `phase == "capacity"` and `not stack`              | `mana_choice` |
| `stack` non-empty (reaction window open)           | `reaction`    |
| otherwise (a character's main phase)               | `main_action` |

Note: **`move_choice` has no distinct engine pause.** "Move" is just one option in the
main-phase legal set (`kind == "move"` actions, one per legal destination row,
`engine.py:1970-1975`). The §4.9 Move row-picker is therefore a pure client-side
arming flow over those `move` actions — not a separate prompt kind. `pending_choice`
covers both `move_card` picks and `scry` (`pending_choice.kind ∈ {"move","scry"}`),
and **both** surface to the UI as `card_choice`.

---

## 3. §3.3 snapshot field mapping

`characters[]` (per party member — `serialize._character_dict`, `state.CharacterState`):

| Brief field                          | Engine source                                              |
|--------------------------------------|-----------------------------------------------------------|
| `id`, `name`, `row`                  | `char.id`, `char.name`, `char.row` (current physical row) |
| `power {current, base, modifier}`    | `char.current_power`, `char.power`, `char.power_bonus`     |
| `hp {current, base, modifier}`       | `char.hp`, `char.max_hp`, `char.temp_mod`                 |
| `incapacitated`                      | `not char.alive` (i.e. `effective_hp <= 0`)               |
| `is_channeling` + channeled summary  | `bool(char.channels)`; summary already in `_character_dict["channels"]` |
| `mana.capacity_by_color`             | `Counter(char.mana_colors)` (see `_mana_by_color`)        |
| `mana.pool_by_color`                 | `Counter(char.pool)`                                       |
| `mana.channel_occupied_by_color`     | `Counter(char.reserved)` (`char.reserved` = channel-locked mana) |
| `mana.identity_colors`               | `char.identity`                                            |
| `mana.pending_capacity_choice?`      | **Derived** — true iff `phase=="capacity"` & `priority==char.id` & `len(distinct identity)>1`. See §4.1. |
| `is_active_focusable`                | **Server/seat concept** — true iff this client controls the char AND it's up. See §5. |
| `hand`, `legal_actions`              | `char.hand` (→ `card_dict`); legal actions **only for the priority holder** (§4.2). Both **seat-filtered**. |

`creatures[]` (enemies **in play** — `serialize._enemy_dict`, `state.EnemyState`):

| Brief field                       | Engine source                                          |
|-----------------------------------|--------------------------------------------------------|
| `id`, `name`, `row`, `level`      | direct                                                 |
| `power {current, base, modifier}` | `enemy.current_power`, `enemy.power`, `enemy.power_bonus` |
| `hp {current, base, modifier}`    | `enemy.hp`, `enemy.max_hp`, `enemy.temp_mod`           |
| `is_boss`                         | **GAP** — no boss concept in engine (see §4.3)         |
| `is_channeling`                   | **GAP** — enemies never channel; always `false` (§4.4) |
| `in_execute_window`               | **GAP** — boss-only mechanic, not modeled (§4.3)       |

`stack[]` — `serialize._stack_list` already yields `{source_name, action_name(label),
target_name, ...}`, **top-first**. Brief §3.3/§4.13 want "bottom = resolves last," so
the UI renders this list reversed (or the server flips it). Purely presentational.

`intents[]` — no top-level list; derive from `enemy.intent` per living enemy
(`_enemy_dict["intent"]` already gives `{name, amount, target_id, target_name}`).
Map to `{creature_name, intent_text, target_name}`.

`log[]` — `state.log` is a list of `Event` (oldest-first). Server tails last N and
reverses to newest-first (brief §3.3/§4.13).

`priority` — `{holder_character_id: state.priority, kind: <derived §2>}`.

`game_over?` — `state.result ∈ {None, "victory", "defeat"}` → `{result}`.

---

## 4. Gaps & reconciliations (raise these)

### 4.1 `pending_capacity_choice` is derived, add a serializer flag
Not a stored field. The engine pauses at `phase=="capacity"` with `priority==char.id`
only when the character's identity has >1 distinct colour (`engine.py:138-150`,
`_legal_capacity` at `1944`). Single-colour identities are auto-locked (no prompt).
Server adds a per-character boolean derived from the settled state.

### 4.2 `legal_actions` is single-holder, not per-character — **design reconciliation**
The brief §3.3 phrases `legal_actions` as a per-controlled-character field. In reality
the engine offers legal actions to **exactly one** character at a time (the priority
holder). So in the snapshot, `legal_actions` is non-empty for **at most one**
character — the one `state.priority` points at (if this client controls it). Every
other controlled character carries an empty legal set even in single-player. This is
correct engine behaviour (strict turn/priority order), not a limitation to work
around. The UI's "who must act" highlight (§4.7) and enabling of action buttons key
off this single holder.

### 4.3 Boss support absent — `is_boss` / `in_execute_window`
`EnemyState` (`state.py:169-220`) has no boss flag, no execute-window concept; the
module docstring says "bosses are out of scope this milestone." Serializer will emit
`is_boss=false`, `in_execute_window=false` constant. The UI should build the boss
visual hooks (§4.5: ~1.5× size, special border, execute glow) but they stay dormant
until the engine grows a boss. **Dependency to raise if bosses are wanted in Phase 1.**

### 4.4 `is_channeling` on creatures is always false
Only `CharacterState` has `channels`. `EnemyState`/`TokenState` do not channel. So the
§4.12 "creature channeling indicator" has no data source and will never light up under
the current engine. Build the badge; it stays off for enemies/tokens.

### 4.5 No enemy "graveyard" zone — killed enemies vanish from the roster
Brief §3.2 lists enemy zones `in_play | in_hand | graveyard | exile`. In the engine a
**killed** enemy is *removed from `state.enemies` entirely* (`_kill_enemy`,
`engine.py:1773-1786`) — there is no graveyard bucket for enemies. Only two off-field
states persist in the roster: `in_hand` (bounced, redeploys) and `exiled` (channel-
suspended). `serialize._enemy_dict` emits `zone ∈ {in_play, in_hand, exile}`. This
actually **satisfies** the brief's "enemy disappears on leave-play" requirement for
kills for free (it's gone from the list). Net effect for the UI: render only
`zone=="in_play"`; a killed enemy is simply absent; a bounced one is present-but-hidden
and reappears on redeploy (`_redeploy_bounced`, `engine.py:330`). No `graveyard` enemy
zone will ever appear — fine, just don't rely on it.

### 4.6 Tokens (autonomous allies) — placement decision needed
The engine has `TokenState` (e.g. the Wisp from Swarm Hex): an **ally** creature that
acts on its own and dies at 0 HP. The brief's `creatures[]` (with `is_boss`) clearly
means the enemy side; tokens are on the party's side. `serialize._token_dict` exists.
**Decision for the design owner:** render ally tokens in the *player* area (they share
the party's rows/side) as small non-focusable cards. Recommend: yes, small cards in
the player area, not focus-selectable (they're autonomous), shown for board truth.

### 4.7 Healing above base (`23/–/20`) confirmed not to occur
As the brief §4.4 flags: the engine caps `heal` at `max_hp` (never overheals) and only
`pump`/`wound` move `temp_mod` (the modifier). So `current > base` always comes with a
non-zero modifier; the `23/–/20` case (over-base, no modifier) will not be emitted.
Render straight from the three numbers; the case simply never arises. ✔ expected.

### 4.8 Action submission model — index into the legal list
`Action` is matched by `Action.key()` (`state.py:280-283`). The cockpit submits an
**index** into the freshly-computed `legal_actions` list (`server.py:239-249`); the
engine is deterministic so the index is stable for a given state. The new WS server
will do the same: each `state` snapshot carries the seat-filtered legal actions with
their engine indices (reuse `serialize.serialize_actions`), and `submit_action` sends
`{index}` (plus, for arming convenience, the resolved sub-selections are *already
baked into that indexed action* — mode/target/color/row are distinct legal entries, so
one index fully specifies the choice). Server re-validates: (a) client controls
`actions[index].actor_id`, (b) index in range of the current legal set. No client-built
rules.

### 4.9b Channel cancel is all-or-nothing
The brief §4.14 Channel modal says "cancel a **given** channel." The engine only
offers `drop_channels` (`_drop_actions` / `_do_drop_channels`, `engine.py:2015`,
`767`), which **ends all of the holder's channels at once** — there is no per-channel
drop. The UI's Channel modal therefore lists the held channels (read-only) with a
single "Drop concentration (ends all)" action. **Dependency to raise** if per-channel
cancel is wanted.

### 4.9 Modal / multi-target / choose-one cards
`_cast_actions` expands a modal card into one legal `Action` per mode, and a
multi-target card into one `Action` per target combination (`serialize.build_menu`,
`_target_tree` show the grouping). So the §4.8 "choose one" modal and §4.6 targeting
are **pure client grouping over already-distinct legal actions** — the client groups by
`(card_id, mode)` / target, then submits the single fully-specified index. Reuse the
grouping logic in `build_menu` as the reference.

---

## 5. Seats (server-only concept; engine is seat-unaware)

The engine has no notion of seats/clients. Seats live entirely in the server
(`character_id → client_id`). Enforcement:
- **Hidden info:** a client's `state` snapshot includes `hand` and `legal_actions`
  **only** for characters it controls (strip everything else server-side — never send
  a card a client shouldn't see). Everything else (enemy board, stack, log, opponents'
  stats/rows) is public.
- **Action gating:** `submit_action` is rejected unless the client controls
  `actions[index].actor_id` AND that index is in the current legal set.
- `is_active_focusable` per character = "this client controls it and it's not
  incapacitated." Purely a per-client serializer output.

---

## 6. `GET /api/setup-options` sourcing

No single content-registry endpoint exists today. Sources:
- **Characters:** Deckbuilder loadout JSON files (`apps/deckbuilder/loadouts/*.json`,
  e.g. `loadout_soren.json`, `loadout_ys.json`, `loadout_mira.json`). Validated via
  `core.schema.Loadout`; adapted by `scenario.party_entry_from_loadout`.
- **Encounters:** the built-in `SCENARIO_A` / `SCENARIO_C` dicts (`scenario.py`), plus
  enemies-only scenario JSON (`apps/deckbuilder/loadouts/scenario_a.json`,
  `scenario_c.json`, `encounter_*.json`; also `examples/scenario_*.json`,
  `encounter_*.json`).
- `POST /api/games` mirrors `Session.start()`: `compose_spec(loadouts, scenario)` →
  `state_from_dict(spec, seed)`.

**Dependency to raise:** if the design owner wants a curated, discoverable list rather
than "whatever JSON is on disk," the engine/content layer should expose a registry.
For Phase 1, scanning the loadouts dir + the two built-in scenarios is sufficient.

---

## 7. What we reuse vs. add (no rules in either)

Reuse from `apps/combat/ltg_combat/serialize.py`: `to_jsonable`, `card_dict`,
`cost_pips`, `_mana_by_color`, `_character_dict`, `_enemy_dict`, `_token_dict`,
`_stack_list`, `serialize_actions`, `build_menu` (as targeting-group reference).

Add (server, presentation-only): seat filtering of `hand`/`legal_actions`; the derived
`priority.kind`; the per-character `pending_capacity_choice` & `is_active_focusable`
flags; log tail+reverse; the `{power,hp}` nesting the brief wants (trivial reshape of
the flat fields the cockpit already emits). None of these compute rules.
