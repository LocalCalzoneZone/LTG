# Langelier Tactical Game (LTG) — Design Update 16: Panel Animations

**Status:** IMPLEMENTED 2026-08-17 (`core/ltg_core/schema.py` — `PanelAnimation`, `Character.animations`, `Card.animation`, `StanceReplacement.animation`; `apps/combat/ltg_combat/engine.py` + `state.py` — presentation tags on the `resolve` log entry; `apps/deckbuilder` — upload/delete/serve routes and the Panel animations UI; `apps/game-server` — `/anim` route, `char_anims` bundle, `anims` on the character snapshot; `apps/game-ui` — `lib/fx.ts` `panel` events, `components/PanelAnim.tsx` player).

**Scope:** presentation only. **No rule reads any of this**; a loadout with no clips plays exactly as before. The companion working doc — generation settings and the per-action prompt set for Lasarre — is `ltg_panel_animation_prompts.md`; `ltg_panel_animation_prompt_guide.md` is the self-contained brief to hand an LLM (with a portrait + loadout JSON) to author the prompt set for any character.

---

## A-1. What a panel animation is

A **panel animation** is a short pre-generated clip (MiniMax H3 image-to-video, made from the character's panel portrait as its first — and last — frame) that the character's panel plays *over* the static portrait when a matching action **resolves**, then swaps back. Because frame 0 is the portrait, the swap in is invisible; because the clip returns to the opening pose, the swap out is too. Clips are authored per character in the deckbuilder and travel with the loadout.

## A-2. The data (schema)

```
PanelAnimation { id, title, file, trigger, alternate, speed, duration_s, impact_s }
Character.animations: [PanelAnimation]           # the character's clip list
Card.animation: anim_id | null                    # per-card pick (deck, Skill, Ultimate)
StanceReplacement.animation: anim_id | null       # per-stance pick for a replaced attack
```

- `trigger` ∈ `attack | cast | channel | defend | mitigate | skill | ultimate | hit | death` — the action type the clip plays for **by default**.
- `alternate = true` removes the clip from the defaults; it is offered as an explicit pick on cards and stance attacks (e.g. Lasarre's *Crystal darts* stance attack vs her default *crystal blade slash*).
- `speed` is the video playback rate, default 1.0 — clips are delivered at their final length and played as authored (retime before upload if needed). Animated images (WebP/GIF) cannot be retimed by browsers, so for those `duration_s` says how long the panel shows the clip before swapping back. WebM/VP9 is the recommended format.
- `file` is a URL path (`/anim/<char_slug>/<file>`). Clips are **never inlined** into the loadout JSON (the JSON rides every game snapshot); the bytes live at `apps/deckbuilder/loadouts/anim/<char_slug>/` (gitignored, beside the loadout), with `content/anim/` as a tracked fallback for clips shipped with the repo.

## A-3. Which clip plays (resolution order)

For a resolving action by a party character:

1. An explicit pick — the card's `animation`, or for a stance-replaced attack the replacement's `animation` — wins if it names an existing clip (alternates included).
2. Otherwise the first **non-alternate** clip whose `trigger` matches: `attack` (basic attack *and* a stance-replaced attack with no pick), `cast` (non-channeled card), `channel` (channeled card), `skill`, `ultimate`, `defend` / `mitigate` (the free actions *and* their stance replacements), `hit` (the character takes damage), `death` (incapacitated).
3. A Skill with no clip falls back to `channel`/`cast` by its timing; an Ultimate falls back to `cast`.
4. Nothing matches → the panel stays static.

## A-4. When it plays (engine → client)

The engine's `resolve` log entry now carries `kind`, `side`, `card`, `heroic` (`skill`/`ultimate`), `stance_slot` and `channeled` — presentation tags read off the resolving `StackItem` (two new tag fields, `heroic` and `stance_slot`, no rules read them). The client's FX layer (`fxFromLog`) maps `resolve` (party side), `defend`, `mitigate`, `damage` (target = hero) and `incapacitated` onto a `panel` effect carrying the chosen clip id, scheduled on the existing choreography beats. **The clip leads:** when a batch opens with a hero's clip, the presentation queue **pre-rolls** — the clip plays over the *previous* board state and the new snapshot (HP, deaths, the lunge, hit flash and damage numbers) is held until the clip's `impact_s` (default 1.5 s — *when the blow lands in the clip*), so the world changes WITH the blow rather than before it. A later resolution in the same batch shifts by the same lead. Hit and death clips land on the impact beat of the enemy's action.

## A-5. Playback rules (client)

- Every video clip stays mounted (hidden, preloaded) so playback starts on the beat, not after a fetch; only the active one is visible, laid over the portrait with the same cover/top fit.
- **Collisions on one panel:** death > ultimate > everything else > hit. A newcomer of equal or higher priority replaces the current clip; a lower one is skipped (a flinch never interrupts a cast). Death is terminal and holds its final frame until the hero is revived.
- A watchdog clears a clip whose `ended` never fires (a browser suspends muted video in hidden tabs), so a panel can never stick.
- Enemies have no loadouts and therefore no panel animations (creature art is unchanged).

## A-6. Authoring flow

Deckbuilder → **Animations** button under the portrait opens the clip modal: *+ Add clip* (WebM/MP4/WebP/GIF) → title, *plays on*, *alternate*, speed / duration; the thumbnail previews on click; × deletes the file and clears any picks that named it. Card editor → *Panel animation* select on every card (blank = default). Stance editor → *animation* select on the `attack — replacement` row. Save / Update Game Character as usual — the picks and clip list ride the loadout.

## A-7. Deferred

Looping the `channel` clip for as long as the stance is held (today it plays once when the channel begins); bundling clip files into loadout export/import for sharing between installs; per-enemy clips.
