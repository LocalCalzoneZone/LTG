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
| POST | `/api/cards/validate` `{card}` | structural-validate one card → re-derived text + `lints[]` |
| GET  | `/api/effect-specs` | per-primitive param descriptors + target modes/sides (powers the editor) |
| POST | `/api/loadout/export` `{loadout}` | engine loadout of validated cards + `omitted[]` report |
| GET  | `/api/loadouts` | list saved names |
| GET  | `/api/loadout/{name}` | load one |
| POST | `/api/loadout/save` `{loadout}` | write `./loadouts/<slug>.json` (drafts; no validation gate) |
| GET  | `/api/schema` | exported JSON Schema of `Loadout` |

The UI also supports raw JSON **Export** (download) and **Import** (file picker via
the Load button → Cancel).

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
  `exclude_self` on an enemy-only target (no-op), `counter_intent` without
  `reactive`, zero/negative amounts, unused slots, and a channeled effect that is
  neither continuous nor recurring. All lints live in one place — `LINT_RULES`
  in `mappings.py`.

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

### Export engine loadout

The **Export engine loadout** button emits a loadout containing **only cards that
are structurally valid AND `validated: true`**. Unvalidated/malformed cards are
**omitted and reported** (the normal **Save** keeps drafts as-is). Endpoint:
`POST /api/loadout/export`.

## Data model (summary)

- **Loadout** = `ltg_version`, `character`, `cards[]`.
- **Character** = `name`, `description`, `colors` (1–3 of WUBRG), `starting_mana`
  (exactly 2; a colour outside `colors` *warns*, never blocks).
- **Card** = id, flavour `name`, `source_name`, `rarity`, `level` (cmc), `type`,
  `cost {generic, colors}`, `timing` (instant/sorcery/channeled — enchantment →
  channeled), `reactive`, `original_text`, `translated_text`, `effects[]`,
  `targets {slot: descriptor}`, `needs_translation`, `text_override`, `validated`.
- **Effect** = discriminated union on `kind` (deal_damage, heal, destroy, bounce,
  counter_intent, pump, wound, … see `schema.py`). `Value = int | "all" | {ref}`.
  `target` = a TargetDescriptor (mode/side/exclude_self/targeted) or a `$slot` ref.

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
