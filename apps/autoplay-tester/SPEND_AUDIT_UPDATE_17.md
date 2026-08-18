# Update 17 §D17-2.2 spend audit — result (2026-08-18)

**Gate:** "run the autoplay tester's spend audit and the four spend plans across levels 1–9 under the frozen `greedy-1.4.0` stick and adjust T-79 until no single spend plan dominates by more than the T-74 band."

**Instrument:** `ltg_autoplay_tester.spend_audit` — chains the baseline gauntlet's three-phase adventure three times on one loadout (earned points and the leveled build carry; HP refills between adventures), every phase level-up spent by the plan; enemy pressure climbs per stage (×1.0 / ×1.6 / ×2.2 over a 0.4–2.0 ladder) so a leveled party still meets a fight. Solo cells, 7 local loadouts, 12 seeds, stick `greedy-1.4.0`. Levels reached: 1→3 (stage 1), →4 (stage 2), →5 (stage 3) — the T-78 thresholds. Levels 6–9 need 210–480 earned points (7–16 phases); the fixed fixtures saturate before that even under the climb, so the audit covers levels 1–5.

```
.venv/bin/python -m ltg_autoplay_tester.spend_audit --seeds 12 --stages 3
```

## Default T-79 (10/10/15/20/25 Power · 15/15/20/25/30 mana & cards · 5/5/5/5/6/6… HP)

| plan | stage 1 (L1–3) | stage 2 (→L4) | stage 3 (→L5) |
|---|---|---|---|
| balanced | 24.7% | 12.8% | 10.4% |
| greedy-hp | 31.2% | 17.3% | 10.1% |
| greedy-power | **39.0%** | **28.2%** | **25.1%** |
| greedy-mana | 20.5% | 9.3% | 5.7% |

Spread 18.5 / 18.9 / 19.4 pp — **over the ±4 pp band at every stage**, greedy-power on top, greedy-mana at the bottom (same ordering as the flat-table audit that motivated the gate).

## What-ifs (4 seeds)

| override | spread (s1 / s2 / s3) | top plan |
|---|---|---|
| Power priced like mana (15/15/20/25/30) | 18.7 / 21.8 / 19.8 | greedy-power |
| Power 30 flat (one point per level-up) | 12.3 / 9.9 / 8.3 | greedy-hp, then greedy-power |
| mana 10/10/15/20/25 + Power 15/15/20/25/30 | 14.3 / 20.2 / 19.0 | greedy-power |

## Reading

The curve **cannot** close the gap: pricing Power at three times its listed cost merely hands the lead to greedy-hp, and pricing mana below Power barely lifts the mana plans. Every variant leaves balanced/greedy-mana at the bottom. The signal is the **stick, not the prices** — `greedy-1.4.0` converts Power directly (attacks + Mitigate = ½ Power) and wastes most extra mana (`mana_wasted` ≈ `mana_spent` in the telemetry), so any plan that buys mana looks bad under it regardless of price. A curve tuned to make the greedy stick's spends look equal would mis-price mana for a human who actually casts.

**Decision:** T-79 ships at the document's values (playtest starting values); the gate is recorded as **not met by the instrument** rather than forced by distorting the curve. Persistent leveling (Phase 0d onward) proceeds under that flag. Re-run this audit when the stick learns to sink mana (a `greedy-1.5.0` with a real casting plan) or when a party-of-two cell with the training ally is added to the harness.
