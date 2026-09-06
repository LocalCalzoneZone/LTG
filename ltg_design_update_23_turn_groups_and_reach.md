# Langelier Tactical Game (LTG) — Design Update 23: Turn Groups, Reach, and Fight Shape

**Status:** APPROVED 2026-09-05 (design settled with the owner; not yet implemented). Supersedes the "Move as a half-action" and "Defend/Mitigate retune" sketches in `reviews/2026-09/01-gameplay-mechanics.md` §1.2, and the Update 15 §L-6.1 haste price. Where this document and any prior document disagree, this document wins.

**Origin.** The 2026-09 review found the turn economy collapsing to "cast or swing", ranged heroes with no positional stake, bosses that shelve, an enemy AI that is solved once learned, and a handful of rules bugs that break authored intent. This update fixes those in one pass. It deliberately does NOT touch Defend and Mitigate scaling with Power: that scaling is the tank's second axis and is intended.

Line numbers in the implementation notes were checked at commit `1fba7f4` and will drift; re-grep the named functions.

---

## Part A — Rules (canon)

### §D23-1 The turn: two groups

A character's turn is EITHER one **turn-spending verb** OR the **pair**:

- **Turn-spending verbs:** Attack (the basic attack), Cast (any sorcery-speed play: sorceries, channel starts; several sorceries may ride one Cast as today), Skill, Ultimate. Taking one of these is your turn.
- **The pair:** Defend and Move. Either one, or both together, in either order, is also a full turn.

Instants, Mitigate, Pass and Delay are reactions and are unaffected. Per-verb limits still apply on top (one basic Attack, one Defend, one Move a turn; one Skill and one Ultimate an encounter).

The Ultimate is an ordinary turn-spending verb. The old rule "the Ultimate opens the turn or not at all" (Update 08 §D8-3, amended) is repealed.

### §D23-2 Keywords free one verb

A freed verb does not count toward the turn. After using a freed verb the character may take **exactly one more verb**, from either group (not the pair).

- **Vigilance** frees Attack. Attack, then one of Cast / Defend / Move / Skill / Ultimate.
- **Defender** frees Defend. Defend, then one of Cast / Move / Skill / Ultimate. A Defender still **cannot basic-attack**. The "rooted" clause is repealed in full: a Defender may take the voluntary Move and the reactive ally-Mitigate dash like anyone else. (Decision recorded here; flipping the dash back is one line in the Mitigate offers.)
- **Haste** frees Move. Move, then one of Attack / Cast / Defend / Skill / Ultimate. The move keeps its Update 15 timing: own turn, stack empty, never while your own action is unresolved. **Price: 20 → 15 points** (T5 table and every mirror).

Order independence: a freed verb may be taken only while at most one non-free verb has been taken this turn; once a freed verb has been taken, at most one non-free verb in total. So Defend + Move + free Attack is illegal in either order, while free Attack + Defend, or Defend + free Attack, are both legal.

### §D23-3 Ranged cannot fire from the Front row

A **ranged basic attack** (and any attack-type intent whose mode is ranged, including row-aimed ranged volleys) is illegal while the attacker stands in the Front row. This applies to heroes, allied tokens and enemies alike. Spells are not attacks and are unaffected: a caster in Front still casts.

Consequences, intended: a ranged hero who dashes into Front to Mitigate for the tank pays with next turn's shot unless they spend the turn moving out; an enemy forced-move that shoves an archer into Front is a real punishment; the melee lunge (§L-2.1) is unaffected because heroes own one attack mode.

Enemy side: a ranged-primary enemy standing in Front with nothing legal to shoot declares a **Move to Mid** (replacing the vestigial "Advance"); a melee enemy with nothing reachable declares nothing, as today.

### §D23-4 Interposition covers melee combat abilities

Update 15 §L-3 let a nominal melee **basic swing** redirect onto a legal body that steps in front of its target. This now also covers a **melee, single-target combat ability** (the §M-A.7 derived class: an ability whose verbs deal damage) from a ground, non-relentless attacker. Ranged intents, flying attackers, positional (row-aimed) intents and non-damage abilities never redirect, as before. Riders follow the damage exactly as §M-A.7 already rules: the interposer who eats "Battering Ram, deal 5 and stun" eats the stun.

The veiled telegraph carries a **redirectable** bit: the intent line reads as a "swing" (it can be walled) or "pursues" (it follows its target).

### §D23-5 Bosses and objectives

- **Neglect counts every party-sourced HP drop.** Poison ticks, life loss and wounds landed by the party count as "hurting" the boss for the neglect check; a poison deck is no longer punished for killing the boss.
- **One-beat enrage.** A timed enrage (`enrage_round`) lands its component in the same beat as its announcement, at Upkeep, rather than after the next unrelated resolution.
- **Late bosses count from arrival.** A boss deployed from reserve (waves) evaluates `enrage_round` and `neglect` relative to the turn it arrived.
- **Objectives may modify the boss fight.** The adventure's single objective may now sit on Phase III as a modifier: guards on the boss until its lieutenants fall, a reinforcement schedule during the boss phase, or a deadline. "At most one objective per adventure" stands. Phase III without an objective remains the standard boss kill.
- Boss dials (`enrage_round`, `neglect`) remain REQUIRED for generated bosses (the existing gate). Old content is left as it is.

### §D23-6 Enemies are less solved

- **Seeded tiebreak.** Proactive components at the same priority are ordered by the fight's `rng_seed` rather than authoring order. Same seed, same fight; different fights differ. (A per-enemy `temperament` that permutes bands is a permitted later extension, not part of this update.)
- **New conditions:** `hero_in_row` (row + op), `hero_hp_pct` (any hero at or under a threshold), `corpse_count`, `turn_mod` (turn parity or every-Nth-turn rotations).
- **Grudges:** target rules `hero_class:<class>` and `hero_type:<type>` (Update 21 vocabulary) so generation can write "the undead hunt the cleric".
- **Cadence exemption.** The attack-cadence force (Update 18 §D18-3) never overrides a component in the emergency band (priority 10–19).
- **Cooldowns spend on declaration, for every slot and every enemy.** A stripped component still goes on cooldown, so strip is a one-round answer, not a lock.
- **Vocabulary in generation.** The enemy prompt teaches `conditional` inside a component, `redirect` (a bodyguard that turns a blow onto itself), `fight` (a duellist that forces a trade), `amplify` (a visible gathering alternative to `charge`) and `remove_keyword` (an anti-flyer net); ranged designs are placed Mid or Rear and a ranged enemy in Front is a layout fault the gate rejects.

### §D23-7 Rules corrections (bugs that broke authored intent)

1. Silence (`prevent cast`) does not gate the Skill or the Ultimate. They are not casts.
2. Slot-referenced targets (`$T1`…) are checked at resolution exactly like inline targets: a target that left the board fizzles the effect, and hexproof gained in response protects.
3. A body is killed once: an enemy or token already off the board is never re-killed, re-logged, or given a second corpse.
4. A card whose value reference names an unknown `ref` is rejected at authoring (schema), never at resolution.
5. A taunt's bite (taunt-with-teeth) reads the taunter's Power at execution, like a basic swing, so a wound landed after the telegraph blunts it.
6. A hero downed by a continuous enemy aura is downed through the normal path: the incapacitation is logged, the ally-down gauge credit is paid, the death event fires.
7. The `channeling_player` and fixed-id target rules honour reach like every other rule; the enemy's ranged fallback never rewrites its standing attack mode.

### §D23-8 Reaction windows

- **Pass-All.** A toggle in the reaction row: "pass for the rest of this enemy phase". While set, the server passes that seat automatically; it clears at the next player phase. Logged as "Pass (pass-all)".
- **The reaction strip names the threat.** It shows the top-of-stack line ("Pollen Mite · Basic Attack → Bones, 3 dmg") and the Mitigate value on the Mitigate cell ("Mitigate −2"), so each window is a one-glance decision.

Standing orders and relevance heuristics were considered and rejected.

### §D23-9 The action bar

Layout, top to bottom, two cells per row:

```
Attack      | Defend
Skill       | Move
Mitigate    | Pass / Delay
[Pass-All]  | End Turn
```

- The left column of the first two rows (Attack, Skill; the Ultimate takes the Skill cell when primed) and the right column (Defend, Move) each get a brass hairline bracket. A single small diamond sits over the left pair, two half-diamonds over the right pair. Tooltips say it in words: "one of these is your turn" / "these two go together". The words "action" and "half action" are never used (an action is a thing on the stack).
- The hand carries the left group's marker on castable sorceries and channel cards (they spend the turn); instants carry none.
- A disabled Attack explains itself: "point-blank: ranged can't fire from the Front row"; a cell closed by the turn rule says "your turn is spent" or "pair with Defend/Move only".

---

## Part B — Implementation notes

All engine work in `apps/combat/ltg_combat/engine.py` unless stated. Keep the engine pure: no presentation logic, no LLM calls.

### B.1 Turn groups (§D23-1, §D23-2)

- `_proactive_allowance` (~2549) and `_proactive_open` (~2557): replace the count with groups.
  - `TURN_VERBS = {"attack", "cast", "skill", "ultimate"}`, `PAIR_VERBS = {"defend", "move"}`.
  - `_freed(actor, mode)`: `attack` with `vigilance`, `defend` with `defender`, `move` with `haste`.
  - `_proactive_open(actor, mode)`: open if `mode in actor.proactive_modes` (a Cast underway); else if `_freed`: open iff the non-free modes taken ≤ 1; else if any freed mode has been taken: open iff no non-free mode taken; else if `mode in TURN_VERBS`: open iff no non-free mode taken; else (pair): open iff every non-free mode taken is a pair verb and fewer than two are taken.
- `_spend_proactive` (~2565) is unchanged (it records the mode). `_do_move` (~2702): delete the haste special case; the spend happens unconditionally and `_freed` makes it not count. Keep `used_move`.
- Labels: the `{free}` suffix at ~7049 becomes "(free, <keyword>)" for any freed verb; Defend's label likewise (`_legal_main` ~7020).
- `_heroic_actions` (~7188): drop `and not actor.proactive_modes` on the Ultimate; route the Ultimate through `_proactive_open(actor, "ultimate")` and spend `"ultimate"`.
- Defender: in `_legal_main` keep the `not _has_kw(actor, "defender")` exclusion on the basic Attack (~7011); delete any exclusion of Move for defenders; in the Mitigate offers (~7120-7150) delete the defender no-dash clause (§D23-2 decision).
- `state.py`: no new fields needed (`proactive_modes` list stays). `serialize.py` `_character_dict`: keep shipping `acted_mode`; add `turn_open: {attack, cast, defend, move, skill, ultimate: bool}` derived from `_proactive_open` so the client can grey cells with a reason without recomputing rules.
- `core/ltg_core/schema.py` `KEYWORDS`: haste cost 20 → 15; rewrite the vigilance / defender / haste glosses to §D23-2 wording. Check `tests/test_keywords.py` price pins and the README T5 mirror.

### B.2 Ranged from Front (§D23-3)

- `_reachable_targets` (~6789): after resolving `mode`, `if mode == "ranged" and getattr(attacker, "row", None) == "front": return []`. This covers `_legal_attack_targets`, `_choose_enemy_attack`, `_pickable`, and allied tokens (they carry `row`).
- `_declare_default_attack` (~930): in the positional-template branch, when the template mode is ranged and `e.row == "front"`, treat as "no target". In the nominal branch, when `_choose_enemy_attack` returns nothing and the enemy's primary mode is ranged and it stands in Front, declare `_move_intent("Fall back", "mid", None)` (reuse the live enemy move path); delete `_move_toward_reach` ("Advance") and its docstring claims. Update `tests/test_design_update_15.py` (the Advance test) accordingly.
- Client: `ActionBar` disabled-reason for Attack when the hero is ranged and in Front (needs `turn_open` or a `reach_blocked: "front"` flag on the character snapshot).

### B.3 Interposition for combat abilities (§D23-4)

- `_redirectable` (~1626): accept `intent.kind == "action"` with `action_type == "attack"` OR `intent.combat_ability and single-target (target_id set, target_row None) and attack_mode == "melee"`, still excluding flying and relentless attackers. `Intent.attack_mode` must be populated for component intents (check `_pick_enemy_intent` ~902 sets it from the component or the enemy).
- `_recheck_intents` (~1642) and `_swing_instead` need no change if they read `_redirectable`.
- `serialize.py` `_veiled_entry` (~190): add `redirectable: bool`; client `IntentLine` stamps "swing" / "pursues" (`SidePanel.tsx` ~284).
- Tests: extend `tests/test_movement_mitigate.py` and `tests/test_combat_ability.py` with an ability that redirects onto an interposer and one (ranged / relentless / positional) that does not; a rider test (the interposer eats the stun).

### B.4 Bosses and objectives (§D23-5)

- Neglect: set `hurt_this_round = True` wherever a party-sourced effect lowers an enemy's `hp` or `temp_mod`: `_tick_afflictions_one` (~6039), `_r_lose_life` (~4589), the wound path; or snapshot `effective_hp` at `_begin_turn` and compare in the End Step check (~2072). Test in `tests/test_boss_pressure.py`: a poisoned boss does not swell.
- One-beat enrage: at the timed crossing in `_begin_turn` (~288-298) push the Enrage component directly as a triggered stack item (the `_race_expire` pattern, ~793-801) instead of leaving it to the post-resolution `on_enrage` check (~2402). Keep `on_enrage` for the ≤25% path.
- Late bosses: record `deployed_turn` in `_deploy_reserve` (~676); evaluate `enrage_round` and the neglect grace relative to it.
- Objectives on Phase III: `llm.py` adventure contract (~1994-2000) and `_objective_problems` (~1628): allow the one objective on Phase III when it is a modifier shape (a `race` whose target is the boss with `guards`, a `waves`/reinforcement schedule, or a `deadline`); `content._validate_objective` (~734-805) accepts it; `_objective_shielded` (~719) already works on any enemy id. Tests in `tests/test_design_update_12.py` / `test_objectives_rework.py`.

### B.5 Enemy AI (§D23-6)

- Tiebreak: `_proactive_rules` (~996): sort by `(priority, seeded_key(comp.id))` where the key is derived from `st.rng_seed`, the enemy id and the turn, so it is deterministic per fight and varies per turn.
- Conditions: `_condition_met` (~1026): add `hero_in_row` (`row`, `op`, `value` count), `hero_hp_pct` (`op`, `value`; any living hero), `corpse_count`, `turn_mod` (`mod`, `value`). Validate the vocabulary at load in `scenario.py` `_component_from_dict` (~115) so a typo'd kind fails loudly instead of silently never firing. Add to the `llm.py` component vocabulary block.
- Grudges: `_component_target` (~1104): `hero_class:<x>` / `hero_type:<x>` pick the lowest-HP reachable hero with that class/type (through `_pickable`), else fall back to valuation. Add to the prompt.
- Cadence: in `_pick_enemy_intent` (~902), when `force_swing`, still evaluate components with `priority < 20` first; only if none is eligible does the forced swing apply.
- Cooldowns: `_start_cooldown` at declaration for every slot (`_declare_enemy_intent` ~861 already does slot 1; do it for slot 2 and for minions); remove the execution-time start (~1939) or make it idempotent; `_strip_slot` (~5035) leaves the cooldown in place. Test: a stripped one-trick minion declares something else next round.
- Prompt: teach the five verbs and the ranged-placement rule; add "ranged in Front" to `_check_layouts`.

### B.6 Rules corrections (§D23-7)

1. `_cast_actions` (~7228): skip `_silenced_for` when called from `_hero_ability_actions` (pass `heroic=True`). Test in `tests/test_silence_and_sap.py`.
2. `_is_targeted` (~4350): resolve through `_effect_desc(item, effect)` (~5608) so `$slot` refs read the slot's `targeted` flag. Tests in `tests/test_targeted_hexproof.py`: hexproof gained in response and bounce in response against a slot-ref card.
3. `_kill_enemy` (~6654) / `_remove_token` (~6697): early-return when the body is already gone; `_resolve_effect` victim loop (~4085) skips dead victims. Test: aura-lift chain kill produces one corpse and one death event.
4. `schema.Ref`: `field_validator("ref")` against `REF_VALUES ∪ {"$…"}`. Test in `tests/test_schema.py`.
5. `_taunt_with_teeth` (~1364): carry `attack_power` and let execution recompute from current Power, as `_declare_default_attack` does (~986-991).
6. `_reap_aura_kills` (~3455) / `_reap_dead` (~2095): route a PC at or below zero through `_after_damage`.
7. `_component_target`: `channeling_player` and fixed-id go through `_pickable`; `_declare_default_attack` (~976) stops assigning `e.attack_mode = mode` and passes the mode into the Intent only (`_pickable` → `_reachable_targets` then reads the standing mode). Test in `tests/test_enemy_intelligence.py`.

### B.7 Pass-All and the reaction strip (§D23-8)

- Server: a per-seat `pass_all_until_player_phase` flag on `Session`, set by a new ws message `pass_all {on: bool}`; the paced drain (`session.py` `_auto_advance` ~213 / `_drain_paced` ~244) submits `Action("pass", auto=True, label="Pass (pass-all)")` for that seat whenever it holds reactive priority; cleared when `st.phase` returns to the player phase. Ship the flag in `seats_payload`.
- Client: the toggle cell in `ActionBar.tsx`; the strip shows the top-of-stack line (data already in `snapshot.stack[0]`) and `mitigate_value` (`types.ts` ~170, currently unused) on the Mitigate cell.

### B.8 Action bar (§D23-9)

- `ActionBar.tsx`: re-layout per §D23-9; brackets from the existing `panel-ticks` / hairline vocabulary in `index.css`; diamonds as inline SVG in `Icons.tsx`; tooltips per cell; disabled reasons from `turn_open` and `reach_blocked`.
- `Hand.tsx`: outline treatment on castable sorceries and channel cards when the Cast verb is open; none on instants.
- Rebuild `apps/game-ui/dist` and commit it (the Windows install serves it).

### B.9 Autoplay

- `apps/combat/ltg_combat/autoplay/policies.py`: bump to `greedy-1.5.0`; add a positional layer (step out of Front when ranged with no target; vacate a lethal positional row; take the pair Defend + Move when no cast or swing is worth more); tally moves, redirects, and windows per round in `runner.py`; surface in `report.py`. Recalibrate the T-74 band after the bump (Update 13 §D13-1.1b).

---

## Part C — Documents to update

- `README.md`: "What a character can do" (turn groups, freed verbs), the keyword table (haste 15, new glosses, Defender wording), "Movement" (ranged-from-Front), the enemy AI paragraph (tiebreak, conditions).
- `ltg_game_design_document.md` §4.6 (actions) and §9.3 (enemy AI).
- `ltg_design_update_15_live_movement.md` §L-6.1: haste price and the freed-verb wording; §L-3 interposition scope (a one-line pointer to §D23-4).
- `ltg_design_update_08_tier_one.md` §D8-3: the Ultimate no longer opens the turn (pointer).
- `ltg_player_guide.html`: "The abilities every character owns" and the keyword glosses.
- `reviews/2026-09/01-gameplay-mechanics.md`: mark §1.2 and the quick fixes as superseded by this update (pointer at the top).

---

## Part D — Tests (new or extended)

- `test_keywords.py`: vigilance one-more rule in both orders; Defend + Move + free Attack illegal; Cast with several sorceries still one verb; haste price.
- `test_defender_and_defend.py`: Defender may Move, may dash, cannot Attack; Defend + one verb.
- `test_design_update_15.py`: haste free Move + one verb; Fall-back replaces Advance; a ranged hero in Front has no Attack targets; positional ranged volley from Front declares nothing.
- `test_movement_mitigate.py`: Defend + Move as a turn; ability interposition and its rider.
- `test_boss_pressure.py`: poison does not trigger neglect; one-beat enrage; reserve boss fuse from arrival; objective on Phase III accepted.
- `test_enemy_intelligence.py`: seeded tiebreak determinism; new conditions; grudge target rule; cadence exemption; cooldown on declaration; reach for `channeling_player` and fixed-id; standing attack mode untouched by the fallback.
- `test_silence_and_sap.py`, `test_targeted_hexproof.py`, `test_schema.py`, a death-idempotency test, an aura-downing test, a taunt-bite test.
- A server test for Pass-All through the paced drain.

---

## Part E — Suggested order

1. §D23-7 rules corrections (each small, each with a test).
2. §D23-1/2 turn groups + keyword changes + haste price (engine, schema, labels, `turn_open`).
3. §D23-3 ranged-from-Front + enemy fall-back.
4. §D23-9 action bar + §D23-8 Pass-All and strip (ship together; rebuild dist).
5. §D23-4 interposition for abilities + telegraph bit.
6. §D23-5 bosses and objectives.
7. §D23-6 enemy AI and prompt.
8. Autoplay layer and recalibration; then docs (Part C).

## Touched surfaces

Engine (`_proactive_open`, `_do_move`, `_heroic_actions`, `_legal_main`, Mitigate offers, `_reachable_targets`, `_declare_default_attack`, `_redirectable`, `_begin_turn`, `_deploy_reserve`, `_proactive_rules`, `_condition_met`, `_component_target`, `_pick_enemy_intent`, `_start_cooldown`, `_strip_slot`, `_cast_actions`, `_is_targeted`, `_kill_enemy`, `_remove_token`, `_taunt_with_teeth`, `_reap_aura_kills`, afflictions / lose_life for neglect), schema (`KEYWORDS`, `Ref` validator), serialize (`turn_open`, `redirectable`), scenario loader (condition vocabulary), server (`pass_all`), client (`ActionBar`, `Hand`, `SidePanel` intent line, `Icons`), llm prompt and gates, content validation, autoplay policy/runner/report, and the documents in Part C.
