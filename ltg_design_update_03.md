# Langelier Tactical Game (LTG) — Design Update 03

**Status:** canonical rules addition. Redefines the **win condition** around enemy **zone state**, and specifies how **bounce** ("return to hand") and permanent removal interact with it. Self-contained: assumes the base GDD and Design Updates 01–02. Keyed to the sections it amends. Where this document and the GDD disagree, **this document wins.**

**The problem this fixes.** The win condition was effectively "no enemies on the battlefield." Bounce removes an enemy from the battlefield *temporarily*, so bouncing the last enemy satisfied that check and ended the match — turning a tempo tool into an undercosted kill spell. The fix is to count **permanent elimination**, not board absence: a bounced enemy is gone-for-now, not defeated, so it must not satisfy victory.

---

## E-A. Enemy roster as zones  *(amends §9, §4.3)*

Every enemy in an encounter is a member of a fixed **roster**, and at all times occupies exactly one **zone**:

| zone | meaning | counts as defeated? | on the battlefield? | targetable? |
|---|---|---|---|---|
| **in play** | active on the battlefield; declares intents and acts | no | yes | yes |
| **in hand** | bounced; removed from the field, pending redeploy | **no** | no | no |
| **graveyard** | died (effective HP ≤ 0) | **yes** | no | no |
| **exile** | exiled | **yes** | no | no |

The engine tracks zone per roster member, not board presence. "In play" / "in hand" / "graveyard" / "exile" mirror the card zones used everywhere else in LTG; an enemy is treated as a card moving between zones.

**Zone transitions:**
- `in play → graveyard` when its **effective HP ≤ 0** (Update 01 §R-7). Permanent. Fires any enemy death triggers.
- `in play → exile` when an **exile** effect resolves on it. Permanent.
- `in play → in hand` when a **bounce** effect resolves on it (§E-C). Temporary.
- `in hand → in play` on **redeploy**, at the start of the enemy's next turn (§E-C).

Only `in play → graveyard` and `in play → exile` are exits from the fight. `in hand` is a holding zone the enemy returns from.

---

## E-B. Win condition  *(supersedes the victory clause of §4.3)*

> **Victory:** the party wins when **every roster enemy is in the graveyard or in exile** (any combination of the two). If any enemy is **in play or in hand**, the encounter continues.

This is evaluated by the existing continuous win/loss check (§4.3), now reading **roster zone state** rather than the battlefield. The **loss** condition is unchanged: the party loses when all player-characters are incapacitated.

**Consequence — you cannot win by bouncing.** A bounced last enemy is `in hand`, which is not graveyard/exile, so victory stays false and the enemy will redeploy. Bounce can only *delay*. A player who bounce-locks the final enemy every turn neither wins nor loses; to win they must actually reduce it to 0 HP (→ graveyard) or exile it. This is the correct, permanent incentive: removal ends fights, bounce buys tempo.

```
def party_has_won(roster):
    return all(e.zone in (GRAVEYARD, EXILE) for e in roster)
# evaluated continuously, same hook as §4.3; reads zone, never board presence
```

---

## E-C. Bounce and redeploy  *(amends §6, §7; references Update 01 §R-10)*

**Bounce** = a removal effect that sends an `in play` enemy to the **in hand** zone. It is the tempo/protection tool: the enemy leaves the field, loses its upcoming action, and returns a turn later.

**Resolution of a bounce:**
1. The target enemy moves `in play → in hand` immediately.
2. While in hand it is **off the battlefield**: it declares no intent, takes no action, occupies no row, and **cannot be targeted** by anything requiring a battlefield target (§E-D).
3. Leaving play **clears temporary attachments and modifiers** on the enemy and **resets its pending intent** — it will declare fresh on redeploy. (Temporary HP modifiers from `pump`/`wound` would have expired at End step regardless, per Update 01 §R-7; enchantments/channels attached to it fall off when it leaves play.)
4. The enemy **retains its current (base) HP.** Bounce does not heal — accumulated damage persists across the bounce, consistent with the encounter-long attrition model (§4.3). This also preserves the bounce-then-finish line.

**Redeploy:** at the **start of the bounced enemy's next turn** (the Intents step, per Update 01 §R-4/§R-5), it moves `in hand → in play`, re-enters the battlefield, and **declares a fresh intent** that turn. Net effect: it loses exactly one action cycle (the turn it was bounced) — the intended one-turn tempo loss.

**Redeploy row:** the enemy returns to its **original row** by default. *(Open knob: returning it to the **rear** instead would reinforce the "sent away, must re-approach" feel and lean on the positioning layer — a melee enemy redeploying to the rear pays extra tempo re-closing distance. Low stakes, only matters in multi-enemy fights. Default original-row unless you want the rear flavor.)*

```
on resolve(bounce on enemy E):
    E.zone = IN_HAND
    E.clear_temp_modifiers()
    E.clear_attachments()
    E.pending_intent = None
    E.remove_from_battlefield()      # vacates its row
    # HP retained on E

at start of E.next_turn (Intents step), if E.zone == IN_HAND:
    E.zone = IN_PLAY
    E.place_on_battlefield(E.home_row)   # default: original row
    E.declare_intent()                   # fresh
```

---

## E-D. Targeting and interaction edges  *(amends §6)*

- **In-hand, graveyard, and exiled enemies are not legal targets** for anything that targets a battlefield creature. You **cannot kill a bounced enemy** — it must redeploy first. This is the symmetric cost of bounce: for one turn it shields the enemy from your removal exactly as it shields you from the enemy's action.
- **You cannot bounce an in-hand enemy** (it is already off-field and untargetable), so bounce cannot be chained to extend the lock beyond the normal redeploy clock — each bounce buys one turn, then the enemy is back and must be bounced again from in play.
- **Bounce is not death.** Moving to hand fires no death triggers (those are `graveyard`-only). Only HP ≤ 0 → graveyard triggers enemy death effects.
- **AoE / field effects skip in-hand enemies** — they are off the battlefield, so board-wide effects (damage, debuffs) do not reach them. A bounced enemy genuinely leaves; it cannot be caught by your sweep this turn.

---

## E-E. Bosses  *(confirmation; references Update 01 §R-10)*

No new rule needed. Update 01 §R-10 already places **bounce in the removal-verb set** (destroy / exile / bounce), and bosses are **immune to removal outside the execute window** (§9.4). Therefore bounce already cannot displace a boss except inside its execute window — the "stall a boss by bouncing it" concern is handled by existing rules. The kill-spell exploit this document fixes was always about *regular* enemies (or the last of several), which §E-B resolves.

---

## E-F. Glossary deltas  *(amends §13)*

- **Roster** *(new)* — the fixed set of enemies in an encounter; each occupies one zone (in play / in hand / graveyard / exile) at all times.
- **Bounce** *(new/updated)* — a removal effect that sends an in-play enemy to the **in hand** zone; it loses its next action, sheds temporary attachments and its pending intent, retains its HP, and redeploys (with a fresh intent) at the start of its next turn. Bounce never satisfies the win condition.
- **Win condition** *(updated, §4.3)* — the party wins only when **every** roster enemy is in the **graveyard or exile**; in-play and in-hand enemies keep the encounter live.
- **Redeploy** *(new)* — an in-hand enemy returning to play at the start of its next turn.
