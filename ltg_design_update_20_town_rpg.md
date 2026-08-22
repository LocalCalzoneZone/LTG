# Langelier Tactical Game (LTG) — Design Update 20: The Town as an RPG

**Status:** IMPLEMENTED 2026-08-22 (`apps/game-server/ltg_game_server/dialogue.py`, `scenario_content.py`, `scenario.py`, `llm.py`, `art.py`, `app.py`, `tests/test_design_update_20_town_rpg.py`).

**Origin (playtest).** The town phase opened cold — which is the design — but the mystery leaked: the first dialogue option on a stranger could be *"What do you think about the impending orc attack?"* before anyone had mentioned orcs. Beyond that, every scenario dressed the same town in the same people, the act's "choice" was often the same dungeon by two roads, and the pre-generated Act I adventure quietly meant only one of the offered quests was real.

## D20-1. Knowledge is gated — `knows_*` flags

The machinery was already built (§D17-5.4: `requires` on choices, `set_flag` hooks, the walker filters on run flags — and `validate_dialogue` even carried an unused `flags_known` parameter). Nothing *used* it, because the generator was never told to and nothing checked.

- **The convention.** When an NPC explains a thing — the trouble, a name, a place — the choice that hears it carries `{"kind": "set_flag", "flag": "knows_<thing>"}`. Any choice elsewhere whose label presumes that knowledge carries `requires: ["knows_<thing>"]`. Root choices must read as things a stranger could say. The questgiver's own tree needs no gates — walking up and hearing them out IS how the party learns; the gates belong on everyone else's reactions.
- **Act topics gate too.** `clean_topics` accepts an optional `requires` list per exchange and `_flavor_tree` passes it into the conversation, so *"what the fisherman thinks of the orc camp"* only becomes askable once somebody has said there is one.
- **The reachability gate** (`dialogue.check_flag_consistency`, run inside `validate_materialization`): every flag gating a choice or a topic must be a standing runtime flag (`defeated_once`, `quest_accepted`, `act_N_complete`, `item_*`), already true in the run (`generate_act` passes the party's current flags — flags legitimately persist across acts), or settable by some `set_flag` hook in this act's trees. A gate nothing can open is rejected with a repair-friendly message, so the generation loop fixes it itself.
- **The prompt** (`ACT_INSTRUCTIONS`) teaches the whole pattern under "GATE KNOWLEDGE", including "an ungated question that names the trouble reads as the UI leaking the plot".

## D20-2. The scenario brings its own cast and places

A town is a stage many scenarios play on (§D17-5.1) — but every production used only the house troupe. The ARC now carries its own additions:

- **`cast`** (0–4): NPCs the scenario brings to town — `{id, name, role, persona, portrait_desc, location, acts?, secret?, topics?}`. They stand at a town location or an arc place, may be limited to certain acts (`acts: [2]` — the widow arrives in Act II), and may be an act's **questgiver** (`validate_arc` resolves questgivers against town ∪ cast, and refuses a questgiver not in town that act).
- **`secret`**: one line only the *writers* see — `_arc_block` shows it to the act generator ("SECRET (writers only — never reveal early)"), it never enters any player-facing surface. This is the betrayal mechanism: author Serel warm in Act I; the Act III writer reads the secret and turns the knife.
- **`places`** (0–2): locations the scenario adds — the wrecked barge, the plague tent — with interior/exterior scenes like any location, flavour functions only, present per act.

**One merge point, zero new cases.** The run always held its own deep copy of the town; that copy is now *composed*: `scenario_content.town_for_act(base_town, arc, act_index)` merges the act's cast and places in as ordinary NPCs/locations (marked `_scenario: True`; idempotent — recomposing strips and re-adds). Recomposition happens at `__init__`, `arrive`, `restore`, `reload_town_art`, and after cast art lands; `begin_next_arc` + the next arrival sends the old cast home. Because everything downstream — the town screen, `find_npc`, dialogue validation, the journal, the "nobody is a closed door" rule — reads the composed copy, cast members are automatically held to every town standard (they must have something to say each act they are present) and the client needed **no changes at all**.

**Art.** Cast portraits and place backdrops paint on the same sequential queue as the act's spoils (`art.scenario_cast_art_items` → `_queue_cast_art`, queued at run start, after materialization, on a new arc, and on reconnect). Content-addressed under `content/art/cast/` and `content/art/places/` by id + describing prose, so the first run of a scenario paints them and every later run adopts from disk. URLs land on the **arc** (`ScenarioRun.set_cast_art`), which every save re-puts — then the town recomposes so the merged copies show the picture.

## D20-3. The quests are real

- **Distinct rides, enforced.** Every quest option must carry its own `adventure_theme`, and no two options may share one (`_clean_quests` rejects both). The ACT prompt now allows only two shapes — *different troubles*, or *branches of one trouble landing in different places with different objectives* — and explicitly bans "the same objective by two roads" (same place, different door is a flavour choice, not a fork). The ARC prompt's "leave room for a choice" rule matches.
- **Pre-generated scenarios are town-only.** `pregenerate_scenario` writes the arc + Act I's town portion and **no adventure**; `save_scenario` makes `act1.adventure_id` optional (the materialization is what is required). The adventure generates on quest accept, exactly as every later act's does — so every offered option is equally real, at the cost of generation latency on accept (an optimization problem, owned separately). The old fast path is untouched: a scenario that *does* carry `act1.adventure_id` + `quest_id` (the three shipped ones) still boards instantly when the party takes the baked option.

## D20-4. Non-goals & notes

- No freeform/LLM-live dialogue — the closed hook vocabulary and authored trees stand.
- The three shipped scenarios predate all of this; they load and play unchanged (their materializations are stored validated and are not re-gated). Regenerating them picks up gating, cast, and town-only Act I.
- Cast members never vend (`vendor: False` forced) — the shop economy stays the town's.
- The town editor does not yet edit an arc's cast/places; they are generation-authored (and hand-editable in the scenario JSON).
