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

## D19-7. Channeled action modifiers

**Origin (playtest).** Turin's *Divine Aura* — a channeled Skill: "While channeled: you have Defender, your Mitigate reduces by full Power" — granted the keyword and silently dropped the modifier. `_apply_static`, the dispatcher for a channel's continuous effects, had branches for keywords, stat auras, taunt, prevent, and exile, but none for `modify_action`: the `mitigate_full` half fell into "(continuous 'modify_action' not modelled this milestone)".

**The fix.** A `modify_action` with `duration: while_channeled` now rides `action_mods` with that duration for as long as the channel holds and lifts on the break (voluntary drop, breaking hit, or incapacitation — all routes go through the same `_remove_continuous`). Attack-mode modifiers re-sync reach on apply and lift. Characters only (enemies have no evergreen actions), and the INSTANT modifiers (`refresh_skill` / `charge_ultimate` / `drain_ultimate`) have no standing form — they resolve once or not at all, and a channeled one logs itself as unhandled rather than ticking every turn for free.

Verified with the shipped skill: X = full Power while the channel holds, back to `ceil(Power/2)` the moment it drops.

## D19-8. Per-use splash on a shared slot

**Origin (playtest).** "One effect should hit the target; another should hit the target and its row." Impossible to author: `scope` lived on the shared slot's descriptor, so every `$T1` use inherited the splash — pinpoint-plus-area cards forced two independent picks.

**The rule.** Scope belongs to the USE, not the pick. A slot reference may carry a splash suffix:

- `"$T1"` — the shared pick only;
- `"$T1+row"` — the pick and its whole row;
- `"$T1+blast"` — the pick, its row, and the adjacent rows.

All uses share ONE pick (sites key on the base name, so no combinatorial cast explosion); each effect resolves with its own footprint. `slot_name`/`slot_scope` are the single parse pair — every raw `[1:]` ref parse in the engine now routes through them — and `resolved_target`/`_effect_desc`/translation `_resolve` merge the use's scope into the descriptor they return, so validation (including the §D19-6 corpse-blast exception), the splash machinery, and the card text all see what each use covers. Scope authored on the slot itself still works (every use inherits it — the pre-§D19-8 behaviour).

Card text names the difference: *"Choose an enemy: they suffer −1/−1, then take 2 damage (and so does its whole row)."*

**Deckbuilder:** an effect linked to a slot gains a footprint select — "the pick only / + its whole row / + row & adjacent" — writing the suffix; removing a slot materializes each use's own scope inline.

**The cleaner Corpse Explosion** (§D19-6 composed with §D19-8): a scopeless corpse slot, the damage carrying its own footprint —

```json
"targets": {"T1": {"mode": "chosen", "side": "enemy", "targeted": true, "state": "corpse"}},
"effects": [
  {"kind": "deal_damage", "amount": 4, "target": "$T1+row"},
  {"kind": "consume_corpse", "target": "$T1"}
]
```

## D19-9. The ground survives its anchor

**Origin (playtest).** "Deal 4 to a target; if you are channeling, deal 3 to it **and its whole row**" lost its blast entirely when the first 4 killed the anchor: the row-mates took nothing. Reordering is not a fix — the splash half sits inside a conditional, which would capture every effect placed after it.

**The rule.** A **scoped** (row/blast) effect is aimed at GROUND, not at a name — the same principle §D18-4 established for enemy row shapes, now applied to player cards. The (side, row) of every target site is **pinned as the resolution begins** (`_new_ctx` → `ctx["ground"]`). If a scoped effect's anchor is gone by the time that effect runs, `_ground_victims` resolves the blast over the pinned footprint instead of fizzling. The body falling first does not un-aim the blast.

Deliberately preserved:

- **Killing the target in RESPONSE still fizzles the whole action.** Nothing is pinned until the resolution starts, so a removal or bounce cast into the window works exactly as before — the counterplay is untouched, and only a card killing its *own* anchor mid-resolution is covered.
- **Only scoped effects are ground.** "Deal 4, then wound it" still loses the wound when the 4 kills — there is no area to fall back on, and a pinpoint rider was never aimed at a place.
- Ground victims are splash: incidental, never targeted, so hexproof does not shelter them — consistent with §D9-3.2.

The log distinguishes the case: *"Lance bursts across the row its target stood in: …"* (`ground: true`), beside the ordinary splash and the §D19-6 corpse-anchored line.

## D19-10. The whole-side corpse sweep

**Origin (playtest).** "Restore 2 HP to all allies; remove all enemy corpses" reported *"finds no corpse to consume"* with bodies plainly on the board. The `consume_corpse` half was authored `{"mode": "all", "side": "enemy"}` — and the corpse axis (`state: "corpse"`) was missing, because the editor only kept `state` on **chosen** targets. So the sweep resolved over the LIVING enemies, and every one of them fizzled the verb.

**The rule.** `consume_corpse` has no domain but bodies, so a whole-side sweep means the corpses — there is nothing else it could have meant. Three layers, so the shape is honest everywhere:

- **Schema normalization**: a `consume_corpse` effect with an *inline* descriptor that omits the axis is stamped `state: "corpse"` at Card validation. The card text, the pick enumeration and the resolver then all read the same shape, and the saved JSON is self-describing. A **`$slot` ref is left alone** — the slot is shared, and narrowing it would narrow its other uses; tick "corpse only" on the slot instead (§D19-6).
- **Resolver backstop**: `_creatures_on_side` reads the corpses whenever the verb is `consume_corpse`, so enemy components — which never pass through Card validation — get the same rule. `exile` / `control` stay explicit: a mode:all sweep over the living is meaningful for them, so they still need `state: "corpse"` to narrow.
- **Editor**: the corpse axis now survives `normTarget` on a **mode:all** target, and the "corpse only" checkbox is offered there for corpse-legal verbs (the §D19-6 corpse-anchored *blast* remains a chosen pick only, since it needs a splash scope).

Card text reads *"Restore 2 HP to all allies. Consume all enemy corpses."*

## D19-11. `break_channel` — the deliberate answer to a ritual

Until now a held channel could only be ended by a **breaking hit** (≥25% of max HP), the holder's incapacitation, or a voluntary drop. There was no verb for "end that rite", so neither side could build the clean answer to a channel-centred threat.

**The verb.** `{"kind": "break_channel", "target": {…}}` — breaks every channel the target is holding. All-or-nothing, exactly like a breaking hit (GDD §8):

- the holder's channels end **together** — a break was never per-channel;
- **reserved mana returns to the pool** (§8), which matters: breaking a hero's aura hands them their mana back that turn;
- every ending channel fires its **`channel_break` trigger** as a respondable stack item, so a ritual's dying sting still springs — the answer is not a free out;
- only creatures channel; a token or a corpse caught by a side-wide target is passed over, and a holder with nothing held logs `no_channel` rather than fizzling noisily.

**Both sides of the table.** It is a plain leaf effect, so the deckbuilder offers it automatically (`effect_specs` is derived from the schema) — a hero's Dispel, or a rider chained on a shared slot (*"Choose an enemy: they take 3 damage, then have their channels broken."*). On the enemy side it is legal as a component verb or as a rider on a hit; the prompt pairs it with `"target_rule": "channeling_player"` and the `hero_channeling` gate so a ritual-breaker never fires into a party holding nothing, and prices it as a Debilitate. An intent carrying it classifies as **interference** (the lockdown family) in the veiled telegraph.
