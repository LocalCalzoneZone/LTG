# Langelier Tactical Game (LTG) — Transcription Engine + Deck Builder

A locally-run tool for authoring LTG character **loadouts**: search real MTG cards
on Scryfall, watch them get translated into LTG's bounded effect vocabulary, edit
flavour text by hand, and save/load the result as JSON.

The **Pydantic schema is the single source of truth.** The frontend never invents
shape — it round-trips exactly what the backend validates. Effects *declare*
intent (`destroy` + a target); no game-state logic lives in them. All
interpretation is left to the future resolver. Translation is deterministic and
manual — **no LLM in this build.**

## Run it (clickable)

Double-click **`start.command`** in Finder. On first run it creates the virtual
environment, installs dependencies, then serves the app and opens your browser at
<http://localhost:8000>. (macOS may ask you to confirm running it the first time.)

## Run it (one command)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

Then open <http://localhost:8000>. The FastAPI server serves both the API and the
static frontend, so that single `uvicorn` command is the whole app.

**Access from other devices on your network:** `--host 0.0.0.0` (above) binds all
interfaces, so any device on the same LAN can reach it at
`http://<your-machine-ip>:8000` (find your IP with `ipconfig getifaddr en0` on
macOS). If a firewall prompts you, allow incoming connections for Python.

End-to-end flow: **Create New → set name/colours/mana → search a card → add it →
edit flavour name / translated text → Save → reload the page → Load.**

> The frontend is intentionally a dependency-free vanilla SPA (`frontend/`), so
> there is no Node/Vite build step — "built to static" is already static. Keeping
> it lean was an explicit goal of the brief.

## Run the tests

```bash
source .venv/bin/activate
python -m pytest -q
```

Covers: the four fixtures validate; card↔JSON round-trips losslessly; malformed
cards are rejected; and the Scryfall→Card mapping via a **mocked** fetch.

## Layout

```
backend/
  schema.py     Pydantic models — effects, Card, Character, Loadout, deck_status
  mappings.py   translation registry + effects→text renderer + Scryfall→Card builder
  scryfall.py   throttled Scryfall client (User-Agent, ~100ms between calls)
  app.py        FastAPI: search / add / validate / save / load / schema + static serve
frontend/       index.html, app.js, styles.css  (no build step)
examples/       four fixture cards + one full sample loadout
tests/          pytest
loadouts/        created at runtime by Save
```

## Backend API

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/scryfall/search?q=` | name → match list |
| POST | `/api/cards/add` `{source_name}` | fetch + map + best-effort translate → Card (rejects Land / Planeswalker / Creature / Artifact with 422) |
| POST | `/api/loadout/validate` `{loadout}` | `{valid, errors[], status}` (deck status) |
| POST | `/api/cards/import` `{names[]}` | bulk import a deck list → `cards[]` (+ `lints`) + `not_found[]`; never blocks |
| POST | `/api/cards/validate` `{card}` | structural-validate one card → re-derived text + `lints[]` |
| GET  | `/api/effect-specs` | per-primitive param descriptors + target modes/sides (powers the editor) |
| GET  | `/api/archetypes` | archetype → stats table (Fighter/Tactician/Caster) for the picker |
| POST | `/api/loadout/export` `{loadout}` | engine loadout of validated cards + `omitted[]` report |
| GET  | `/api/schema` | exported JSON Schema of `Loadout` |

Save/Load are handled client-side via the browser File System Access API (see
**Save / Load / Import / Export** below), so the loadout JSON lives wherever you
choose rather than in a server folder.

## Editing & validating effects (the source of truth)

The game engine reads **`effects`** only — `translated_text` is player-facing
flavour it never reads. So effects are canonical, and the card detail panel is a
**guided editor** for them:

- **Add / remove / reorder** effects. Each effect has a **`kind` dropdown**
  (known primitives only); the param inputs **update to match the kind** (typed:
  ints, enums, and the target builder below). Edits are valid by construction.
- A **raw-JSON escape hatch** (`{ } raw JSON`) for power editing — re-validated
  against the schema on Apply.
- The editor is data-driven from `GET /api/effect-specs`, which is derived from
  the Pydantic models — so adding a primitive in `schema.py` surfaces in the
  editor automatically (no JS change).

### The target descriptor

Targeting is a **mechanical property, not a label** — an effect that *targets*
can be stopped by (future) hexproof/shroud; one that doesn't is immune. So every
effect's `target` is a structured descriptor, not a flat name:

```
target: {
  mode:         "self" | "chosen" | "all",
  side:         "ally" | "enemy" | "any",   // omitted for mode:self
  exclude_self: bool,                        // "another ..." excludes you
  targeted:     bool                         // uses the targeting mechanic; chosen-only
}
```

`targeted` is set whenever the word **"target"** appears in the source text
(e.g. "target creature you control" is friendly *and* targeted) and is editable.
The editor's **target builder** offers **mode** (You / Choose one / All) →
**side** (Ally / Enemy / Either, hidden for You) → toggles **another** and
**targets** (shown only for Choose-one). Validation: `targeted` is rejected on
`self`/`all`; `side` is required unless `self`; `draw`/`scry` can't resolve to an
enemy (no library).

### Shared targets

Some cards apply several effects to the **same** chosen target (e.g. Sign in
Blood — one player both draws and loses life). Declare a **chosen** descriptor as
a **slot** in the card's `targets` map and reference it from each effect with a
`$`-prefixed string (only `chosen` targets can be shared):

```json
"targets": { "T1": { "mode": "chosen", "side": "ally", "targeted": true } },
"effects": [
  { "kind": "draw",      "amount": 2, "target": "$T1" },
  { "kind": "lose_life", "amount": 2, "target": "$T1" }
]
```

The engine resolves each slot **once** and applies it to every referencing
effect. In the editor you never type `$T1`: the target builder offers
**＋ New shared slot** and **↪ link to an existing slot**; the editor manages the
slot map. `translated_text` then auto-renders the shared wording
("Choose an ally: they draw 2, then lose 2 HP."). See
[examples/sign_in_blood_corrected.json](examples/sign_in_blood_corrected.json).

### Text, validation & ratification

- `translated_text` **auto-derives from effects** (toggle **manual override** to
  hand-write it). Text and effects never silently drift.
- **Structural validation on every save**: known kinds, typed params, coherent
  target descriptors (targeted⇒chosen, side required unless self), slots are
  chosen-only and references resolve, `draw`/`scry` never resolve to an enemy.
  Malformed cards are rejected with a clear message.
- **Editing any effect or slot resets `validated` → false.** Use **Mark
  validated** to ratify a card's effects. Editing un-ratifies it.
- **Validation lints** (non-blocking warnings, shown in the detail panel, run on
  add and edit): no effects extracted, `draw`/`scry` resolving to *either* side,
  `exclude_self` on an enemy-only target (no-op), a `counter` that isn't an
  instant, zero/negative amounts, unused slots, and a channeled effect that is
  neither continuous nor recurring. All lints live in one place — `LINT_RULES`
  in `mappings.py`.

### Granting & removing keywords

Effects can attach evergreen keywords to a creature. The **keyword registry**
(`KEYWORDS` in `schema.py`) is the source of truth for each keyword's identifier,
display name, gloss, grantability, and params — a grant *references* a keyword by
name, it doesn't redefine it.

- **`grant_keyword`** — `{kind, keywords:[…], params?, target, duration}` attaches
  one or more keywords. Renders "An ally gains Flight until end of turn." /
  (channeled) "While channeled: all allies have Trample."
- **`remove_keyword`** — same shape; removes them, or `["all"]` for "loses all
  abilities."

Both use the existing **target descriptor** and **duration**, and **compose**
with other effects (`pump` + `grant_keyword` = "+2/+2 and first strike"). The
grantable set: flying, reach, first_strike, vigilance, trample, deathtouch,
lifelink, hexproof, indestructible, protection (optional `from` param). **Retired**
keywords (menace, ward, convoke) are rejected for granting with a clear error;
unknown keywords too. The editor shows the grantable list as labelled checkboxes.
See [examples/grant_flying.json](examples/grant_flying.json),
[examples/trample_anthem.json](examples/trample_anthem.json).

### Lands & mana (ramp / rituals)

LTG has **no land cards** — mana is a colour-locked *capacity* that curves up
+1/turn. Lands survive only as references inside spells, translated to capacity
(the land names are dropped: Forest→G, Island→U, Swamp→B, Plains→W, Mountain→R,
"a basic land"→`choice`).

- **`ramp`** raises capacity above the curve: `{kind:"ramp", amount, color, availability}`.
  `availability` ∈ `immediate` (capacity + pool now) / `tapped` (capacity now,
  pool next refresh) / `deferred` (capacity at the start of your next turn).
  Renders e.g. "Add 1 green mana capacity (usable this turn)." /
  "(not usable this turn)." / "At the start of your next turn, add …".
- **`add_mana`** is a ritual — a one-time burst into your *current pool* this
  turn, no capacity change: `{kind:"add_mana", amount, color}` →
  "Add 3 black mana to your pool this turn."

`color` ∈ {W,U,B,R,G,`choice`}; a non-`choice` grant outside the deck identity is
flagged in deck-status (folded into the off-colour warning). Auto-translation
handles Rampant Growth (→ tapped ramp) and Dark Ritual (→ add_mana); see
[examples/rampant_growth.json](examples/rampant_growth.json),
[examples/cultivate.json](examples/cultivate.json),
[examples/dark_ritual.json](examples/dark_ritual.json).

**Other land references** translate to the capacity model too:
- *"for each land you control"* → a capacity value-ref `{"ref":"mana_capacity"}`
  (any amount field can hold it — in the editor pick **mana capacity** in the
  value dropdown). Renders e.g. "Draw a card **for each point of mana
  capacity**." See [examples/for_each_land.json](examples/for_each_land.json).
- *landfall / "whenever a land enters"* → a **`capacity_increase`** trigger on a
  channeled card. Renders "**Whenever your mana capacity increases:** …". See
  [examples/landfall.json](examples/landfall.json).

### Actions, intents & counters (the stack vocabulary)

Everything that resolves is an **action** with two orthogonal axes — `type`
(`spell` | `ability`) and **speed** (`active` | `reactive`). Speed is *derived,
never stored*: a player card is always a `spell` whose speed comes from `timing`
(instant→reactive, sorcery→active, channeled→sustained); abilities derive theirs
from `ability_kind`. See `spell_speed` / `ability_speed` in `schema.py`.

An enemy action is first a telegraphed **intent** (pre-stack), then the same
action **on the stack**. Two surfaces, two targets:

- **Intent** — reached by targeting the *enemy that owns it* (a `creature`-class
  target). Player tools: **`strip_intent`** ("Remove the chosen enemy's
  telegraphed intent.") and **`stun`** ("The chosen enemy skips its next
  intent."). Type-agnostic.
- **Action on the stack** — reached by targeting the *action itself* (an
  `action`-class target). This is where **counters** operate.

**Counter** (replaces the old `counter_intent`) is one filtered effect:
`{ "kind":"counter", "filter":<node>, "target":{"class":"action","side":"enemy"} }`.
The `filter` is a node in the lattice `action ⊃ {spell, ability ⊃ {attack,
activated, triggered}}` (matching a node also matches its descendants — resolution
is the engine's job):

| filter | renders |
|---|---|
| `action` | Cancel an enemy action (spell or ability). |
| `spell` | Cancel an enemy spell. |
| `ability` | Cancel an enemy ability (including attacks). |
| `triggered` | Cancel an enemy triggered ability. |

The target descriptor gains a **`class`**: `creature` (default — the existing
mode/side/exclude_self/targeted descriptor) or `action`. Only counters target
`class: action`; the type system rejects a creature target on a counter and an
action target on any other effect. A counter card should be `timing: instant`
(instant ⟹ reactive, so it can respond — lint otherwise). See
[examples/counterspell.json](examples/counterspell.json),
[examples/negate.json](examples/negate.json), [examples/stifle.json](examples/stifle.json).

### Channeled effects (enchantments)

MTG enchantments become **`channeled`** cards — sustained effects that persist
while the caster holds them. An effect on a channeled card is one of two shapes:

- **Continuous** — `duration: "while_channeled"` (applies the whole time it's
  channeled). The default for static enchantment effects.
- **Recurring** — `trigger: "upkeep"` (fires once at the start of each of your
  turns while channeled). A discrete event; carries no `while_channeled`.

`while_channeled` and `trigger: upkeep` are valid **only** on channeled cards
(rejected elsewhere), and an effect can't be both. Auras ("Enchant creature …")
target the enchanted entity with a `chosen`, `targeted` descriptor, fixed at cast.

The renderer makes the ongoing nature explicit on every line:

| effects | rendered |
|---|---|
| `pump {all, ally}` continuous | **While channeled:** all allies gain +1 attack and +1 temp HP. |
| `disable` on `{chosen, enemy}` continuous | **While channeled:** the chosen enemy can't attack. |
| `create_token` + `lose_life {self}`, both upkeep | **At the start of each of your turns while channeled:** create a Faerie ally and lose 1 HP. |
| `wound {all, enemy}` continuous | **While channeled:** all enemies have -1 attack and -1 HP. |

Convention: power → "+X attack", toughness → "+X temp HP" (buff) / "-X HP"
(debuff). See [examples/anthem.json](examples/anthem.json),
[examples/pacifism.json](examples/pacifism.json),
[examples/bitterblossom.json](examples/bitterblossom.json). The *engine* behaviour
for channeling (mana reservation, break-on-hit, release) is out of scope here —
this layer only types the card and renders correct text.

### Save / Load / Import / Export

- **Load** opens a native file picker and reads a savegame JSON, remembering the
  file handle.
- **Save** overwrites that open file; with no file open it prompts for a location
  (Save As). (Uses the File System Access API; browsers without it fall back to a
  file-input for Load and a download for Save.)
- **Import** opens a modal where you paste a deck list — one card per line, e.g.
  `1 Akroma's Will (CMR) 3`. Quantity, set code, and collector number are ignored;
  only the name is used, resolved on Scryfall (exact, then fuzzy) via
  `POST /api/cards/import`. The import is **non-blocking**: wrong types, off-colour
  cards, or going over 40 all import anyway and are **flagged in the list** to fix
  (a creature shows "⛔ fix: Creature"); names Scryfall can't resolve are reported.
- **Export engine loadout** emits a loadout containing **only cards that are
  structurally valid AND `validated: true`** (incl. resolved character `stats`);
  unvalidated/malformed cards are **omitted and reported**. `POST /api/loadout/export`.

## Data model (summary)

- **Loadout** = `ltg_version`, `character`, `cards[]`.
- **Character** = `name`, `description`, `portrait`, **`archetype`** (required —
  Fighter / Tactician / Caster), `level` (int ≥ 1, default 1), `colors` (1–3 of
  WUBRG), `starting_mana`. Archetype drives derived stats (HP / hand / mana
  amount) from `ARCHETYPE_STATS` — the single source of truth; the builder shows
  them read-only and the engine export includes the resolved `stats`.
  `starting_mana` length **==** the archetype's mana amount (2, or 3 for Caster),
  each colour picked from `colors`; a colour outside `colors` *warns*, never blocks.
- **Card** = id, flavour `name`, `source_name`, `rarity`, `level` (cmc), `type`,
  `cost {generic, colors}`, `timing` (instant/sorcery/channeled — enchantment →
  channeled; **derives `speed`**: instant→reactive, sorcery→active,
  channeled→sustained), `original_text`, `translated_text`, `effects[]`,
  `targets {slot: descriptor}`, `needs_translation`, `text_override`, `validated`.
- **Effect** = discriminated union on `kind` (deal_damage, heal, destroy, bounce,
  counter, pump, wound, ramp, add_mana, grant_keyword, remove_keyword, … see
  `schema.py`). `Value = int | "all" | {ref}`.
  `target` = a creature TargetDescriptor (mode/side/exclude_self/targeted) or a
  `$slot` ref; **counters** instead target `{class:"action", side:"enemy"}`.

## Deck status (advisory only — never blocks)

card count `X/40`; rarity `mythic X/2, rare X/6, uncommon X/12, common X/20`;
duplicate source names (singleton); cards whose colours fall outside the
character's identity; count of untranslated cards; starting-mana outside identity.

## How to add a new effect primitive

One localized change in `backend/schema.py`:

1. Add a model class with a `Literal` `kind` and its params/defaults.
2. Add the class to the `Effect` union.
3. Add a one-line renderer to `RENDERERS` in `backend/mappings.py` so it produces
   translated text.

```python
# schema.py
class Silence(BaseModel):
    kind: Literal["silence"] = "silence"
    target: TargetOrSlot

# add Silence to EFFECT_CLASSES (the Effect union is built from it)

# mappings.py
RENDERERS["silence"] = lambda e: f"Silence {_tgt(e.target)}."
```

## How to add a translation mapping

One `@register` call in `backend/mappings.py` — regex → effect builder. Targets
are descriptors; use the `t_self` / `t_chosen` / `t_all` constructors:

```python
@register(r"gain (\d+) life")
def _(m, ctx):
    return [Heal(amount=int(m.group(1)), target=t_chosen("ally"))]
```

On **Add card**, every registered rule is run over the oracle text; matched
effects fill `effects` and render `translated_text`. If nothing matches, the card
is flagged `needs_translation` for you to author by hand.

## Out of scope (later phases)

LLM-assisted translation; hard deck-building enforcement (status only warns); the
game engine / resolver; enemy generation; art/assets.
