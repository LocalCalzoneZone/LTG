# Work brief 2 — Immersion, UI and polish

Source: whole-game review of 2026-09-02 (hands-on playtest plus thirteen subsystem code reads; their findings are folded into this brief). Line numbers were checked at commit `1fba7f4`; re-grep before editing. Item 2.3 of the original review (onboarding, town ambience, audio) was not selected and is omitted here.

## Session kickoff (read first)

- Client: `apps/game-ui/src/` (React 18 + Zustand + Tailwind, Vite). Design language: `apps/game-ui/DESIGN_SYSTEM.md` ("Brasswork & Ink"): no emoji, brass is the ONLY interaction accent, tide = player, blood = enemy, vigor = heal/buff, aether = channel/ability, sharp corners, Optima small-caps for labels, art draws focus. Reuse `panel-ticks`, `chamfer-x`, `caps-label`, the existing FX chip vocabulary (`fx-intent-chip`) and motion keyframes in `src/index.css` / `src/styles/fx-*.css`.
- The client computes no rules; it renders the snapshot built by `apps/game-server/ltg_game_server/snapshot.py` over `apps/combat/ltg_combat/serialize.py`. Types are hand-mirrored in `src/lib/types.ts`.
- Run: `.claude/launch.json` has `game` (built dist on :8020) and `game-ui` (Vite dev on :5173 proxying to :8020). After client changes run `npm --prefix apps/game-ui run build` and commit `dist/` (the Windows install serves it).
- `prefers-reduced-motion` is honoured everywhere today; keep it that way for anything new.

## Item 2.1 — Let the board narrate its own beats

### Problem (verified)
- **Chronicle shows the oldest lines.** `snapshot.py` ~434-438 emits the visible log tail newest-first (`reversed(visible[-LOG_TAIL:])`, in place since the first UI build). `SidePanel.tsx` ~62-69 later added pin-to-bottom (`el.scrollTop = el.scrollHeight`, commit 347dfa7). Net: the pinned view shows the TURN 1 header at the bottom while new events append at the top out of view. Reproduced on every screenshot. Also `LOG_TAIL = 60` means the story can never be scrolled back, and rows are keyed by index on a newest-first list so every row remounts per snapshot (~251).
- **Objective and boss beats are visually mute.** `fx.ts`'s event switch (~255-477) has no case for `guards_down`, `wave_deployed`, `reinforcements`, `escalation`, `objective_complete`, `withdraw`, `neglect`, `redeploy`; `SidePanel.tsx` tint tables (~28-47) do not name them either, so "The last guard falls" renders in the same grey as a mana refresh. The engine logs each with structured data (`engine.py` ~655, ~670, ~742, ~806, ~2086, ~6734, ~699).
- **Boss state is not on the card.** The creature snapshot (`snapshot.py` ~282-291) ships `is_boss`, `in_execute_window`, `doom_clock` but no `enraged` flag, no neglect tally, no `guarded_by`; after the 1.8 s enrage chip fades nothing says the boss is in fury, and a timed enrage at full HP shows nothing at all. The objective banner disappears when status leaves "active" (`SidePanel.tsx` ~208), exactly when it has something to say.
- **Threat is text, not board.** Intents link enemy to target only while hovered (`CharacterCard.tsx` ~51, ~88-90: a 1 px blood ring on `hoverIntent`); row assaults get a persistent `row-threat` wash (`Battlefield.tsx` ~343-352, ~440-447) so the vocabulary exists. Update 15 promised visible arrows; there is no persistent mark, no "threatened by 2", and a redirect is visible only as a log line.
- **Status effects are hidden.** `status_tags` (silenced, pacified, sapped, prevent/protection, acted mode) are built in `serialize.py` ~375-421 and read only by `InspectModal.tsx` ~86-99; `CharacterCard` shows none, and `CreatureView` has no status field at all (`types.ts` ~249-295), so a taunted or silenced enemy looks healthy.
- **FX key mismatches.** The stun animation has never rendered: `fx.ts` ~406-407 reads `d.target` while the engine logs stun with `enemy=` / `character=` (`engine.py` ~5175-5183). A channel-suspend exile logs `level=` so it plays the permanent-banish implosion (~469-473); the regen grant glows like a heal (~341-343). Damage FX mode is guessed from a label→mode map of the previous snapshot (~106-115, ~293-301) and collides on duplicate labels.
- **No entrances.** `useFlip` skips first-seen cards (`motion.ts` ~54) and `fxFromLog` has no arrival cases, so waves, summons, raised undead and risen corpses pop in; the exit side (crumble, implode, slip away) is lavish.
- Also: the sap debuff is invisible in the mana widget (`snapshot._mana_block` ~138-152 forwards only `by_color`); the veiled-intent classifier files enemy forced `move`, corpse `control` and `consume_corpse` as "support" (`serialize.py` ~114-133, ~151-192), so a shove or a raise-dead reads as a buff.

### What to build
1. **Chronicle fix (first, tiny):** either reverse the tail on the server (oldest-first) and keep pin-to-bottom, or keep newest-first and pin to the top; key rows by `seq`; raise or page `LOG_TAIL` so the fight can be re-read.
2. **Beat FX and tints:** add `fx.ts` cases and Chronicle tints for the objective events above; a row-level or full-screen wash for guards-down / wave / escalation; a one-line banner flash reusing `PhaseBanner`.
3. **Card state chrome:** ship `enraged`, `neglect_stacks`, `guarded_by` on the creature snapshot; render an ENRAGED plaque (blood), a swelling badge for neglect, a shield hairline for a warded race target; keep the objective banner visible with its outcome line after resolution (`serialize.objective_block` ~793-832 already writes it).
4. **Persistent threat marks:** a blood chevron with a count on each targeted hero card driven by `creature.intent.target_id`; while an enemy is "surfaced" draw a hairline from enemy to hero; animate the mark moving on `intent_redirect` (`engine.py` ~1669, ~1691). Add the `redirectable` bit from brief 1 item 1.2 and stamp "swing" vs "pursues".
5. **Status chips** on both card types as a second row of intent-chip-style stamps; add `status_tags` to `CreatureView`.
6. **Fix the FX contract:** correct the stun/exile/regen keys now; then have the engine tag `damage` with `mode` (or the resolving item uid) so the label map can be deleted. (Brief 3 item 3.3 turns this into a typed event registry.)
7. **Entrances:** a board mount animation (rise + brass shimmer for allies, crimson for enemies) for `token_created`, `raised`, `risen`, `reinforcements`, `wave_deployed`, `redeploy`; a "next round: 2 Raiders" preview from a new `next_arrival` field on the survive/waves objective block.
8. Small: sapped capacity in the mana widget; classify forced `move` as interference and corpse `control` / `consume_corpse` as summon in the veiled classifier.

### Acceptance
- Screenshot check: after a kill, the Chronicle's bottom line is the kill; an enraged boss wears the plaque until death; each hero card shows how many enemies aim at it without hovering; a stunned enemy shows the rings.
- Add a client test (see brief 3 item 3.2 for the harness) that renders `fx.ts` against a recorded engine log and asserts every event type in the snapshot has a handler or an explicit ignore.

## Item 2.2 — Fix the hand and the reaction strip

### Problem (verified)
- **Hand cards clip their rules text** at 8-11 px with `overflow-hidden` and no expansion; the only fallback is the native `title` tooltip (`Hand.tsx` ~78, ~108-110; console height clamp in `BottomBar.tsx` ~61). A full-size card popup already exists for Stack and Chronicle hovers (`SidePanel.tsx` ~175-178, ~256-262).
- **"Not castable" is opacity alone.** `playable = !!choices.casts[card.id]`, else `opacity-40` (`Hand.tsx` ~48-49, ~84). The client has the pool and cost (`choices.ts` ~20-42, `castPayment`), the card timing and `priority.kind`, so "2 short" / "sorcery" / "no target" are labelable locally; "not your priority" needs the server to ship a reason or candidates even when empty.
- **The reaction strip explains nothing.** "Reaction Window" + lit Pass/Mitigate; the threat sits in the fixed stack banner at the top and the Stack panel on the right, three regions away (`ActionBar.tsx` ~100-104; banner in `Modals.tsx` ~426-445). `mitigate_value` (`types.ts` ~170) is never rendered on the Mitigate cell.
- **No keyboard beyond Escape** (`App.tsx` ~58-77 is the only key handler); cards are `div onClick` with no `role`/`tabIndex`. **End Turn has no guard** when castable cards, unspent mana or an unused Attack remain (`ActionBar.tsx` ~133-145; mana refreshes every upkeep so the waste is invisible). **Mana payment** for X casts clicks every pip including fixed coloured ones (`store.ts` ~26-44, ~526-578; `ManaWidget.tsx` ~163-204); the ambiguous-generic picker opens for most two-colour hands.
- **No damage preview while aiming** although `power.current`, target `hp.current`, `wards` and `break_threshold` are all in the snapshot (`CreatureCard.tsx` ~102-119 sends no hover payload when `isTarget`; `serialize._stack_mechanics` ~706-717 already computes the prose for stack rows).
- **Any snapshot cancels arming.** `_applySnapshot` nulls `armed`, `chooseModeFor`, `manaSelect` on every state (`store.ts` ~351-353); broadcasts arrive for a teammate's seat claim, a disconnect, art landing (`app.py` ~583-589, ~949-955). In co-op a friend clicking their seat resets your half-paid X cast.
- Small: the global right-click `preventDefault` (`App.tsx` ~67-70) kills paste in Options textareas; native `title` tooltips carry most of the rules glossary (`KeywordBadges.tsx`, `ActionBar.tsx`, `CreatureCard.tsx`).

### What to build
1. **Hover-enlarge for the hand:** reuse the `h-72 w-48` HandCard popup on hover/focus, positioned above the console; 150 ms delay; also on keyboard focus.
2. **Why-not chips:** a small caps-label chip on unplayable cards: "2 short", "sorcery", "no target", "holding" (priority elsewhere). Server side: add `unplayable_reason` per card to the hand block in `snapshot.py` for the cases the client cannot compute.
3. **Reaction strip rewrite:** put the top-of-stack line inside the strip ("Pollen Mite · Basic Attack → Bones, 3 dmg"), show the Mitigate X on its cell ("Mitigate −2"), and when the strip is for someone else's threat say so ("Bones is struck"). Add the standing-order controls from brief 1 item 1.1 here.
4. **Keyboard:** Space/Enter = Pass or End Turn (context), 1-9 = hand cards, A/D/M/V = Attack/Defend/Mitigate/Move, Esc = cancel; a `tabIndex` and `role="button"` on cards; Enter to confirm Cast in the mana picker.
5. **End Turn guard:** a count on the button ("End Turn · 2 cards, 3 mana") and a one-click confirm when something castable remains; a Settings toggle to disable.
6. **Mana payment:** auto-pay the coloured/base pips; clicks add X; a "max X" button; only prompt for generic colour when the remaining hand actually cares.
7. **Damage preview:** on a hovered legal target while Attack is armed show "→ 4 · kills" / "→ 4 · breaks ritual" / "→ 4 · ward eats 2"; basic attacks only (X and conditional spells stay silent).
8. **Preserve arming across unrelated broadcasts:** keep `armed`/`manaSelect` when the new `legal_actions` are deep-equal, or re-map by card id + target ids; clear only when the actor's options changed.
9. Small: scope the right-click cancel to the battlefield and console; a single themed tooltip component replacing `title` on badges, cells and cards.

### Acceptance
- Two clicks still cast a single-target spell; an X spell needs card + target + X clicks + Cast, no coloured-pip clicks.
- A teammate claiming a seat mid-targeting leaves your brackets in place.
- Every hand card's full text is readable without the OS tooltip; every dimmed card says why.

## Suggested order
2.1 step 1 (minutes) → 2.2 steps 1-3 and 8 (a day) → 2.1 steps 2-6 (two days, includes small server snapshot additions) → 2.2 steps 4-7 → 2.1 steps 7-8.
