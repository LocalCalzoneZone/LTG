# Langelier Tactical Game (LTG) — Transcription Engine + Deck Builder

A locally-run tool for authoring LTG character **loadouts**: search real MTG cards
on Scryfall, watch them get translated into LTG's bounded effect vocabulary, edit
flavour text by hand, and save/load the result as JSON.

The **Pydantic schema is the single source of truth.** The frontend never invents
shape — it round-trips exactly what the backend validates. Effects *declare*
intent (`destroy` + a target); no game-state logic lives in them. All
interpretation is left to the future resolver. Translation is deterministic and
manual — **no LLM in this build.**

## Run it (one command)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Then open <http://localhost:8000>. The FastAPI server serves both the API and the
static frontend, so that single `uvicorn` command is the whole app.

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
| POST | `/api/cards/add` `{source_name}` | fetch + map + best-effort translate → Card |
| POST | `/api/loadout/validate` `{loadout}` | `{valid, errors[], status}` |
| GET  | `/api/loadouts` | list saved names |
| GET  | `/api/loadout/{name}` | load one |
| POST | `/api/loadout/save` `{loadout}` | write `./loadouts/<slug>.json` |
| GET  | `/api/schema` | exported JSON Schema of `Loadout` |

The UI also supports raw JSON **Export** (download) and **Import** (file picker via
the Load button → Cancel).

## Data model (summary)

- **Loadout** = `ltg_version`, `character`, `cards[]`.
- **Character** = `name`, `description`, `colors` (1–3 of WUBRG), `starting_mana`
  (exactly 2; a colour outside `colors` *warns*, never blocks).
- **Card** = id, flavour `name`, `source_name`, `rarity`, `level` (cmc), `type`,
  `cost {generic, colors}`, `timing` (instant/sorcery/channeled — enchantment →
  channeled), `reactive`, `original_text`, `translated_text`, `effects[]`,
  `needs_translation`.
- **Effect** = discriminated union on `kind` (deal_damage, heal, destroy, bounce,
  counter_intent, pump, wound, … see `schema.py`). `Value = int | "all" | {ref}`.

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
    target: Target

Effect = Annotated[Union[..., Silence], Field(discriminator="kind")]

# mappings.py
RENDERERS["silence"] = lambda e: f"Silence {_tgt(e.target)}."
```

## How to add a translation mapping

One `@register` call in `backend/mappings.py` — regex → effect builder:

```python
@register(r"gain (\d+) life")
def _(m, ctx):
    return [Heal(amount=int(m.group(1)), target=Target.an_ally)]
```

On **Add card**, every registered rule is run over the oracle text; matched
effects fill `effects` and render `translated_text`. If nothing matches, the card
is flagged `needs_translation` for you to author by hand.

## Out of scope (later phases)

LLM-assisted translation; hard deck-building enforcement (status only warns); the
game engine / resolver; enemy generation; art/assets.
