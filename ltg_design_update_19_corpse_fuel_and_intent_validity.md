# Langelier Tactical Game (LTG) — Design Update 19: Corpse Fuel & Intent Validity

**Status:** IMPLEMENTED 2026-08-22 (`core/ltg_core/schema.py`, `core/ltg_core/translation.py`, `apps/combat/ltg_combat/engine.py`, `apps/combat/ltg_combat/state.py`, `apps/game-server/ltg_game_server/items.py`, `apps/game-server/ltg_game_server/llm.py`, `apps/game-ui/src/components/InspectModal.tsx`, `tests/test_design_update_19_corpse_and_intents.py`).

**Origin (playtest).** Four reports from the same session: corpse-explosion effects had no proper way to spend their body and "adding an exile corpse effect seems inconsistent"; a boss inspected showed one of its two intents; Warded gear was an auto-include; and enemies announced telegraphs that had stopped making sense — buffing an ally who had since died, casting at a hero who had since warded — only to evaporate on resolution.

## D19-1. `consume_corpse` — a corpse is a COST, not a second target

Corpse-fuel components were written as an `exile` of a corpse sitting beside the payload. Three problems, one of them a live bug.

**The bug.** A component aims its *payload* with `target_rule` — usually `valuation`, at a hero — and the corpse verb rode along on the same binding. `_lookup_target` fell back to a corpse only when the id named one, so on the shipped *Corpse-Fuel Blast* (`the_sunken_vault_of_brass__phase3`) the `exile` bound to the **hero** and set them to 0 HP. Its sibling *Galvanic Reanimation* tried to raise a living hero as an undead token.

**The inconsistency.** An `exile` written *before* the payload removed the body before the payload could read it; written *after*, it read as an afterthought the author had to remember. Nothing in the data said which was intended.

**The fix.** A first-class verb, `consume_corpse` (schema, translation, resolver, corpse-legal set):

- **It resolves LAST**, whatever order it is authored in (`_cost_last`, applied beside `_damage_first`). "Devour a fallen kin and blast the front row" is one action: the blast happens, then the body is spent.
- **It gates the action.** A component carrying any corpse verb is not declared while no legal corpse is on the battlefield, so a Corpse Feast never burns a turn chewing air; a player card carrying it is offered corpses only, and no corpses means no cast.
- **The body binds on its own.** `Intent.corpse_id` / `StackItem.corpse_id` carry the corpse from declaration to resolution, and **any** corpse-state descriptor resolves against it rather than against the action's living target. That fixes the shipped `exile` shapes too — no content rewrite.
- It consumes the body only: no death trigger (nothing died), and a `rises` corpse loses its return (§D9-1.5).

`llm._corpse_problems` asks generated content for the new verb whenever an `exile`-on-corpse sits beside another verb; a lone corpse-burn (the anti-necromancy tool) stays legal. The prompt's CORPSE-BURST recipe is rewritten around it and notes that `target_rule` is now free to aim the payload.

## D19-2. A boss shows both its intents everywhere

`InspectModal.creatureLines` read the **legacy singular** `intent` field, which is slot 1 only. A boss declares two a round on Standard/Hard and after Enrage (§D9-4), so half its telegraph was invisible in the one panel a player opens to study it. It now reads the `intents` list, labels the slots when there is more than one, and falls back to the singular field for an older snapshot.

## D19-3. Hexproof is priced like what it turns off

Hexproof shuts off the **entire targeted enemy suite** — every curse, stun, silence, sap, drain and snipe — for the rest of an encounter, leaving only basic attacks and the area shapes of §D18-4. Indestructible, by contrast, turns off *removal*, which matters much less in a game where the party is whittled down by damage. Yet Warded was the cheaper affix.

| | before | after |
|---|---|---|
| **Warded** gear affix (`items.AFFIXES`) | rare · L4 · 25 pts | **mythic · L6 · 40 pts** |
| enemy keyword (§D4 table, prompt) | min level 4 · cost 4 | **min level 5 · cost 6** |

40 points puts it above Unbroken (indestructible, 35) and makes it the dearest rider in the table — a boss-drop centrepiece rather than a routine accessory. `worn_points` feeds `effective_level_bonus`, so a party wearing it is now correctly read as stronger and meets scaled encounters. The §F-8 Mistveil Hexer worked example moves to L5 to stay legal at its own cost.

Hexproof itself is unchanged: creation-banned (§P-3), gear-only, and it still never stops a basic attack (§D6).

## D19-4. An intent is re-validated before it is announced

MTG never puts an ability with no legal target onto the stack — it is not announced at all. The engine announced anyway and let the item die at resolution, so the party watched a Fortify heal a corpse and a curse crawl onto a warded hero purely to evaporate. Worse, the enemy's whole activation went with it.

`_intent_spoiled` runs at the one honest moment — the intent entering the stack, after everything the telegraph gave the party a turn to do:

- the target left play, or was never aimed while the payload is targeted;
- the target is now a **corpse** and no verb here has business with a body (the dead-ally buff);
- the target has **Hexproof** and the intent is a targeted hostile spell/ability (attacks are exempt — §D6);
- the **body it would spend** is gone (the party burned the corpse in response).

When it is spoiled, `_swing_instead` strikes with the basic attack: the telegraph is marked `fizzled` (it genuinely did not happen), the log says what came to nothing and why, and the swing is a real stack action with its own reaction window, so the party still gets to answer it. It also resets the §D18-3 cadence — this counts as the sword landing. With nothing to swing at (pacified, or nothing in reach) the activation is simply lost, as before.

## D19-5. Non-goals

- No content rewrite. The corpse binding fixes every shipped `exile`-on-corpse shape in place; only newly generated content is held to `consume_corpse`.
- No change to what hexproof *does* — only what it costs.
- Re-validation does **not** re-aim. A spoiled intent takes the sword; it does not hop its curse onto a different hero. Targets are locked at the telegraph, which is the whole point of telegraphing.

## D19-5. Playtest follow-ups (2026-08-22, second session)

- **The register retells its numbers.** §D18-2 lifted a component's verb amounts and left the authored `telegraph` prose alone, so the log read *"deal 2 damage to the attacker"* while the hit landed for 4 — which read as "Mitigate isn't working". `_retell_numbers` (in `content._bump_enemy_power` and the autoplay mirror) rewrites the moved numbers in the telegraph: a scaled Enrage's `+P/+T` pattern first (its halves scale differently), then bare numbers on word boundaries — guarded against ambiguity (a number that also sits on an untouched heal/stun swaps only in damage-marked positions: "deal(s) N", "N damage", "for N"). Swept across shipped content: 396 telegraphs accurate, 0 stale.
- **Mitigate floors at 1.** The sweep for the report above found a real adjacent bug: a hero wounded to 0 Power was offered the Mitigate, spent the once-per-turn reaction, and reduced nothing (X = ceil(0/2) = 0). `_mitigate_value` now floors at 1 — raising a guard always turns at least a point.
- **`channel_start` picks its target at cast.** Triggered effects deliberately pick targets when the trigger fires — but `channel_start` fires INLINE as the cast resolves and never routed through the pick machinery, so a chosen-target start effect ("when this channel begins: strip an intent") fell back to the card's primary target and silently no-opped. Its fire moment IS the cast's resolution, so it is now a cast-time target site (`_target_sites` / `_target_options_for` exception), and `_start_channel` resolves the start list with the cast's ctx (site bindings included).
- **A strip with nothing to strip lingers.** The other half of the reported card — `upkeep: strip_intent` — resolved during the intents window, BEFORE the enemy declared, and no-opped in silence every turn. A strip landing on an enemy with no declared intent now sets `strip_pending`: the next intent is smothered AS IT IS DECLARED (slot 1 first, then a boss's second), logged both when it clings and when it lands.
- **Base stat references.** The deckbuilder's value dropdown gains `caster_base_power` / `target_base_power` (printed Power, no bonuses or counters) and `caster_base_hp` / `target_base_hp` (max HP — base toughness), beside the live `*_power` / `*_hp` refs. Registry → engine resolver (`_base_stat`) → translation, so the editor picks them up from `/api/effect-specs` with no frontend change.
- **Corpse-exclusive targeting in the editor.** The target builder shows a **"corpse only"** checkbox on chosen targets of corpse-legal verbs (`control` / `exile` / `consume_corpse`, shipped as `corpse_kinds` in `/api/effect-specs`). Checked, it authors `state: "corpse"` (§D9-1.3): the cast offers corpses on the battlefield only — it cannot name a living enemy — and fizzles if the body is gone by resolution. This replaces the "conditional: if target is a corpse" workaround for cards that should be corpse-exclusive outright.

## D19-6. The corpse-anchored blast (Corpse Explosion)

**Origin (playtest).** A player card "consume a corpse, blast its row" could not be authored: a shared target slot cannot be both `state: "corpse"` (what `consume_corpse` needs) and living (what `deal_damage` demands) — the §D9-1.3 corpse axis made the two verbs mutually exclusive on one pick.

**The rule.** A `deal_damage` whose chosen target is a corpse **and which carries a splash `scope`** is legal: the body is the **blast point**, not a victim. It takes nothing (it is already dead; a sibling `consume_corpse` spends it, resolving last per §D19-1), and the damage lands on every living enemy in the footprint — the corpse's row for `scope: "row"`, plus adjacent rows for `"blast"`. The splash victims are incidental, never targeted, exactly as in §D9-3.2. An *unscoped* damage verb still may not aim at a corpse — there is nothing for it to do there.

Mechanics threaded through:
- **Schema**: the corpse-axis check admits the exception (and its error message teaches it).
- **Enumeration**: `state: "corpse"` now means *corpses only* whatever verb owns the pick — the schema has already vetted who may author it — so the cast offers bodies and never the living.
- **Resolution**: the §D19-1 corpse-binding intercept resolves `$slot` refs too (player cards author the shared corpse slot); the splash guard admits a corpse anchor for `deal_damage`, `_splash_targets` treats a corpse as the enemy-side body it is, and the corpse is dropped from the victims list. An empty footprint logs a fizzle.
- **Translation**: reads as ground — *"Choose an enemy corpse — the blast covers every enemy on its row: they take 4 damage, then the corpse is consumed."*
- **Deckbuilder**: the "corpse only" checkbox now also appears on `deal_damage` (checking it seeds `scope: "row"`), and shared target slots gain the same checkbox beside their existing scope select.

**The canonical card:**

```json
{
  "name": "Corpse Explosion", "type": "Sorcery", "timing": "sorcery",
  "targets": {"T1": {"mode": "chosen", "side": "enemy", "targeted": true,
                      "state": "corpse", "scope": "row"}},
  "effects": [
    {"kind": "deal_damage", "amount": 4, "target": "$T1"},
    {"kind": "consume_corpse", "target": "$T1"}
  ]
}
```

One pick serves both verbs; the engine guarantees the blast resolves before the body is spent, whatever order the effects are authored in.
