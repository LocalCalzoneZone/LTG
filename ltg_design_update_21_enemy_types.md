# Langelier Tactical Game (LTG) — Design Update 21: Types & Classes

**Status:** IMPLEMENTED 2026-08-22 (`core/ltg_core/schema.py`, `core/ltg_core/translation.py`, `apps/combat/ltg_combat/state.py`, `scenario.py`, `engine.py`, `apps/game-server/ltg_game_server/llm.py`, `art.py`, `snapshot.py`, `apps/deckbuilder/`, `apps/game-ui/`, `tests/test_design_update_21_enemy_types.py`).

Every creature now carries a **type line** (renamed same-session: "supertype" → **class**, the MTG class wording):

- **TYPE — what the creature IS** (race / nature), up to 2:
  `human, elf, dwarf, goblin, orc, giant, troll, merfolk, fae, undead, spirit, demon, dragon, beast, bird, serpent, vermin, insect, spider, plant, fungus, elemental, construct, ooze, horror`
- **CLASS — what it DOES** (profession / role), up to 2:
  `warrior, knight, soldier, brute, berserker, archer, hunter, scout, rogue, assassin, wizard, shaman, necromancer, druid, cleric, cultist, ritualist, healer, warlord, artificer, noble, bard`

The registries are **closed** (`CREATURE_TYPES` / `CREATURE_CLASSES` in the core schema): the generation gate, the card-condition validation, and the deckbuilder dropdowns all read the same lists, so a card and an enemy can never disagree on spelling.

## D21-1. Authoring & generation

- Enemy JSON: `"types": ["undead"]`, `"classes": ["archer"]` (the loader reads `"supertypes"` as a same-session legacy spelling) — **required on every generated enemy**, 1–2 each. `llm._type_problems` rejects missing / unknown / >2 with repair-friendly messages (wired beside the §D14 kit floor in both `generate_encounter` and `generate_adventure`); the prompt carries the vocabularies (baked into `DEFAULT_INSTRUCTIONS` at import — the template is stored verbatim in settings, so there is no render-time substitution path) and the instruction to pick *the tags a player would guess from looking at the creature*. All twelve gold-example enemies are tagged (tested).
- The **engine stays permissive**: legacy content with no tags loads and plays unchanged (empty lists). The loader (`_clean_tags`) slugs, dedupes, caps at 2, and tolerates a lone string.

## D21-2. Art anchoring

`art.enemy_prompt` appends the type line — *"It is: undead, knight."* — to every enemy portrait prompt, between the physical description and the scene hint. The painter is told what the creature is and does, so a "necromancer" cannot drift into a generic monster and an "undead archer" keeps its bow. Untagged legacy enemies get no stray line.

## D21-3. The engine: cards that care

`target_property` gains two properties (`class` is a Python keyword, so the model field is `class_` aliased both ways — authored JSON and dumps alike read `"class"`):

```json
{"kind": "conditional",
 "condition": {"kind": "target_property", "property": "type", "type": "undead"},   // or "property": "class", "class": "wizard"
 "effects": [{"kind": "deal_damage", "amount": 5,
              "target": {"mode": "chosen", "side": "enemy", "targeted": true}}]}
```

— rendered *"Deal 5 damage to an enemy that is an undead."* (`type`/`supertype` join the qualifier properties, so the natural noun-phrase form is used; the value is registry-validated at authoring). Evaluation reads the target's tag lists, and:

- a **corpse keeps its body's tags** (`Corpse.types/.supertypes` delegate to the dead state), so "if the target is an undead" answers over a corpse pick;
- a **dominated enemy keeps its tags** across the control flip;
- a **raised corpse** rises as `["undead", <what it was>]` (cap 2 — a risen goblin is an undead goblin; a risen undead is just undead), supertypes inherited.

## D21-4. Surfaces

- The enemy snapshot ships `types` / `supertypes`; the inspect panel's subtitle reads *"Level III enemy · melee · undead · necromancer"*.
- The deckbuilder's conditional builder offers **"is a type (race)"** / **"is a class (role)"** with dropdowns fed from `/api/effect-specs` (`creature_types` / `creature_classes`).

## D21-4b. The hero's type line

Player characters carry the same type line, chosen on the **deckbuilder sheet** right under Name/Level: two chip-style pickers (Type / Class), up to 2 each from the same registries. Pure identity — no points cost. `Character.types/.classes` validate against the registries (dedupe + cap 2), thread through `party_entry_from_loadout` → `CharacterState`, ship on the character snapshot, and show in the inspect panel's subtitle ("human · cleric · knight") — so enemy components and ally cards can condition on a hero's type exactly as cards condition on an enemy's.

## D21-5. Non-goals

- No pricing change: tags cost nothing and add no budget; they are identity, not power.
- Ally tokens may carry tags via token defs or inheritance, but nothing requires it.
- No retro-tagging sweep of shipped content — legacy enemies stay untagged until regenerated; every NEW generation is gated.
