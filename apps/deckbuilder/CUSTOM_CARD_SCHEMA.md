# LTG Custom Card Import — JSON Schema

This document is a formatting guide for generating custom cards for the LTG
Deckbuilder's **Import Custom Cards** feature. Follow it exactly: paste-ready
JSON in, playable cards out.

## Top-level shape

Provide either a bare JSON **array** of card objects, or an object with a
`cards` key holding that array. Any number of cards is allowed.

```json
[
  { "...card 1..." },
  { "...card 2..." }
]
```

or

```json
{ "cards": [ { "...card 1..." }, { "...card 2..." } ] }
```

Imported cards are **added** to the currently open loadout. They never replace
or remove existing cards.

## Card object fields

| Field       | Required | Type   | Description |
|-------------|----------|--------|-------------|
| `name`      | yes      | string | The card's display name. Also used to derive its id. |
| `type`      | yes      | string | One of `"instant"`, `"sorcery"`, `"enchantment"` (case-insensitive). Enchantments become *channeled* cards in LTG (persistent, upkeep-paid effects). |
| `mana_cost` | yes      | string | The card's cost. Accepts MTG brace syntax `"{1}{R}"`, compact syntax `"1R"` / `"2GG"`, or a bare integer for pure generic costs. Colours are the five MTG letters W/U/B/R/G. An empty string means free. |
| `effect`    | yes      | string | The card's rules text, written **in Magic: The Gathering oracle wording** (see below). |
| `flavour`   | no       | string | An **in-character description of how the effect works** — what the spell physically/magically does in the game's fiction, not MTG-style flavour prose. Shown in the Deckbuilder's *"Flavour — how the effect works 'in character'"* field. Never parsed as rules. `flavor` is accepted as an alternate spelling. |
| `rarity`    | no       | string | One of `"common"`, `"uncommon"`, `"rare"`, `"mythic"`. Defaults to `"common"`. |

Unknown extra fields are ignored. A malformed card (missing `name` or
`effect`, unrecognized `type`) is rejected individually and reported; it does
not block the rest of the batch.

## Writing the `effect` text

The effect text is run through the same deterministic MTG-oracle translation
pass used when importing real Magic cards. **Write it exactly as MTG rules
text would read**, e.g.:

- `"Deal 3 damage to target enemy."` / `"Lightning Bolt deals 3 damage to any target."`
- `"Draw two cards."`
- `"Target creature gets +2/+0 until end of turn."`
- `"Counter target spell."`
- `"Choose one —\n• Draw a card.\n• Deal 2 damage to target creature."` (modal — every bullet must be translatable or the whole card is left for hand-authoring)

Notes for the translation pass:

- Phrases the translator recognizes become structured LTG effects and the
  card's in-game text is re-rendered from them.
- Text it can **not** parse does not fail the import: the card arrives flagged
  `needs_translation`, and a human finishes it in the card editor. Simpler,
  conventional oracle wording translates more reliably than novel phrasing.
- On enchantments, static effects become *while channeled* continuous effects,
  and `"whenever a land enters the battlefield"` / landfall wording becomes a
  mana-capacity trigger, matching real-card import behaviour.
- On enchantments, `"when <name> leaves the battlefield/dies, …"` or
  `"Sacrifice <name>: …"` wording becomes a **channel-break trigger**: the
  effect goes on the stack (respondable) when the channel ends — dropped or
  broken, for any reason.
- All imported cards start **unvalidated**; a human must ratify each card's
  effects in the Deckbuilder before it can be exported to the game engine.

## Writing the `flavour` text

`flavour` is not Magic-card flavour text (no poetic quotes or epigraphs). It is
a plain description of what the card's effect *is* inside the game's fiction —
how a spectator would describe the spell being cast. Write one or two sentences
grounding the mechanical effect in the character's magic. For example, for a
card named **Crystal Lance** that deals damage to a target:

> A shard of razor-sharp crystal, summoned and directed — deadly as a spear strike.

## Derived values (do not supply)

- **Level** is computed as the converted mana cost (generic + colour pips).
- **id** and **source_name** are derived from `name`.

## Complete example

```json
[
  {
    "name": "Crystal Lance",
    "type": "instant",
    "mana_cost": "{1}{W}",
    "effect": "Crystal Lance deals 3 damage to any target.",
    "flavour": "A shard of razor-sharp crystal, summoned and directed — deadly as a spear strike.",
    "rarity": "common"
  },
  {
    "name": "Tidal Recall",
    "type": "sorcery",
    "mana_cost": "2U",
    "effect": "Draw two cards.",
    "flavour": "A rushing wave of memory pulled from the deep, carrying forgotten knowledge back to the caster's mind."
  },
  {
    "name": "Wardsong",
    "type": "enchantment",
    "mana_cost": "{1}{W}{W}",
    "effect": "Creatures you control get +0/+1.",
    "flavour": "A sustained resonant hum that hardens the air around allies into a thin protective shell.",
    "rarity": "uncommon"
  }
]
```
