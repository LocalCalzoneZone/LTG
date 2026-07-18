# Langelier Tactical Game (LTG) — Design Update 14: The Enemy Kit Floor

**Status:** IMPLEMENTED 2026-07-18 (`apps/game-server/ltg_game_server/llm.py`, `tests/test_enemy_kit_floor.py`).

**Origin (playtest).** In the generated adventure *The Hollow Bell Foundry* the party met enemies that would ONLY "escalate" — turn after turn of +1/+1 counters on themselves and nothing else. The mechanics of the bug: the §F-7.1 proactive pass picks an enemy's top READY component every turn and only falls through to the basic attack when none is ready, so a lone proactive self-pump with cooldown 1 fires forever and the basic attack never lands. The enemy stacks power it never spends — a punching bag. The generation prompt's own Example C ("Emberling") modelled exactly this shape.

## D14-1. The rules (generation-side; the engine stays permissive for hand-authored/legacy content)

1. **Two-component minimum.** Every generated enemy carries at least TWO components — two abilities, two spells, or ability + spell; proactive + reactive is the classic pairing. Cheap fodder affords the second via a reactive or `once_per_encounter` component (×0.5 cost).
2. **The punching-bag rule.** A proactive component whose verbs only develop the enemy itself (`counters` / `pump` / `regen` / `heal` / `prevent` / `protection` / `amplify` / `double_next` aimed at self) must carry **cooldown ≥ 2**, so the off-turn swings spend what the pump builds. Alternatives that satisfy the rule: make it reactive or `once_per_encounter`, or aim it at OTHERS (an anthem / ally pump is a real turn). Exempt: verbless Evasive (pure repositioning), Enrage (auto-fires once, parsed reactive), and CHARGE gathers —
3. **— but a gather needs its payoff.** Any enemy with a `charge` verb must also carry an `on_charge_full` detonation component (§D8-2.4 windup), or the windup pays off nothing.

## D14-2. Enforcement

- **Gate:** `llm._design_problems(encounter)` returns repair-friendly problem strings; wired into the `generate_encounter` problems block and per-act into `generate_adventure`, so a violating reply is rejected and fed back for self-repair like a missing scene/description.
- **Prompt:** `DEFAULT_INSTRUCTIONS` gains "The two-component minimum & the punching-bag rule (HARD REQUIREMENTS)" after the component cost table; the ESCALATE-clock pattern bullet now prescribes cooldown 2 (never 1) plus a paired second component.
- **Gold examples** updated to obey their own rules (tested): Example A's Grave Thrall (was a bare statline) → L3 taunt wall with a reactive wound; Bloodbat gains a reactive shriek (L3); Example B's Broodmother gains a once-per-encounter on-ally-death Escalate (still exactly B(3)=20); Example C's Emberling is now the canonical CORRECT escalate clock — cooldown-2 stoke so it swings with its stacked counters on off-turns, plus a reactive Flare-Snap (L3, weight annotation 20 → 21).

## D14-3. Non-goals

- No engine or `content._validate_encounter` change: hand-authored encounters, tokens, and legacy plain-chassis enemies stay legal at the engine gate — the kit floor is a *generation quality* bar, not a data-model constraint.
- No pricing change: the §D4 cost tables and `enemy_analysis.py` mirrors are untouched; the rules only constrain component *shapes*, which self-price into level as before.
