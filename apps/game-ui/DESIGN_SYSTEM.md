# LTG Game UI — Design System

**"Brasswork & Ink"** — the visual language of the LTG game client (`apps/game-ui`).
Approved 2026-07-06. This document is the reference for keeping every future
screen, modal, and state on-theme.

> The one-sentence version: **a dark table lit for the art** — near-black ink
> surfaces, thin brass hairlines instead of filled boxes, Optima small-caps for
> everything ceremonial, and one gold accent that always means "you can act on
> this."

---

## 1. Principles

1. **Art draws focus.** Character portraits, future creature art, card art, and
   scene backdrops are the brightest, most saturated things on screen. UI chrome
   stays at hairline weight (~13–30% opacity lines) and never boxes over a
   portrait's face — overlays use gradient scrims, stats bleed off the card
   edges.
2. **Fantasy through restraint.** The MTG/fantasy feel comes from thin brass
   lines, chamfered banners, diamond motifs, Roman-numeral levels, and engraved
   sigils — never from heavy textures, ornament, or skeuomorphism.
3. **One accent owns interaction.** Anything glowing **brass-gold** is clickable
   or awaiting the player. No other element may use brass as decoration-only
   emphasis. All other hues carry fixed meanings (§3).
4. **No emoji, ever.** All pictograms come from the stroke-icon set (§5).
5. **Sharp corners.** No `rounded-*` on panels, cards, buttons, or chips
   (exceptions: mana symbols and pips, which are inherently circular).
6. **Reserved slots for future art.** Creature cards, hand-card art boxes, and
   the battlefield scene layer all have placeholder layers (engraved sigil /
   gradient glow) that art drops into without moving any other element.

---

## 2. Surfaces & Structure

Tokens live in [`tailwind.config.js`](tailwind.config.js); global CSS
(keyframes, chrome helpers) in [`src/index.css`](src/index.css).

| Token | Hex | Use |
|---|---|---|
| `ink-0` | `#07090c` | page background, deepest wells (stat gems, inputs) |
| `ink-1` | `#0b0e14` | battlefield stage |
| `ink-2` | `#10131b` | panels (side panel, modals) |
| `ink-3` | `#161a24` | raised surfaces (ribbon, card backs) |
| `line` | `rgba(214,197,160,.13)` | default hairline border |
| `line2` | `rgba(214,197,160,.30)` | emphasized hairline (card frames, corner ticks) |

Structural chrome (classes in `index.css`):

- **`.panel-ticks`** — brass corner ticks (top-left + bottom-right) on major
  panels. Recipe: `panel-ticks border border-line bg-black/25`.
- **`.chamfer-x` / `.chamfer-x-sm`** — chevron-cut clip path. Reserved for the
  primary CTA of a surface (End Turn, Start Game) and the Your Move / Waiting
  card banners.
- **`.field-scene`** — the battlefield's layered background: scene-tinted
  radial glow + warm side glow + vignette over `ink-1`. Scene art will be added
  as a `background-image` on this same element, behind the glows.
- **Hairline dividers** — `h-px`/`w-px` in `line`, often as
  `bg-gradient-to-b from-transparent via-line2 to-transparent`. The battlefield
  centre divider carries a single rotated-square brass diamond.

### Layout skeleton

```
┌────────────────────────── TopRibbon (42px) ──────────────────────────┐
│ ◆ LTG · conn dot        Turn N + phase tracker        seats · ⚙ · +  │
├──────────────────────────────────────────────┬— Splitter (drag) ——┤
│  Battlefield (.field-scene)                  │  Side panel        │
│  players 40% | ◆ divider | enemies 60%       │  The Stack         │
│  rows: rear/mid/front (captions at bottom)   │  Chronicle (log)   │
├───────────────────────— Splitter (drag) —────┴────────────────────┤
│  Command console: who/zones · Mana · Actions · Hand               │
└───────────────────────────────────────────────────────────────────┘
```

- Side panel: default **450px**, console height: default
  `clamp(200px, 27vh, 320px)`. Both are user-resizable via the `Splitter`
  component in [`src/App.tsx`](src/App.tsx) (drag = resize, double-click =
  reset, sizes persist in `localStorage` under `ltg_side_w` / `ltg_console_h`).
- Battlefield cards size against viewport *height* (`clamp(…, Nvh, …)` in
  [`src/lib/layout.ts`](src/lib/layout.ts)) so both axes of resize behave.

---

## 3. Colour Semantics

Four meanings, four hues — used identically everywhere. Never repurpose them.

| Token | Hex | Meaning |
|---|---|---|
| `brass` / `brass-hi` | `#c9b37e` / `#ecdcae` | **interaction & attention**: legal targets, armed controls, priority holder, panel titles, primary CTAs |
| `tide` | `#82b4c9` | **player/ally allegiance**: source names in stack/log, focus edge, ally tokens, open-seat hints |
| `blood` / `blood-deep` | `#c25a50` / `#571f1e` | **enemy allegiance & harm**: enemy names, acting-enemy ember, damage pops, destructive buttons, Defeat |
| `vigor` | `#84c793` | **heal / buff**: positive modifiers, +1/+1 counters, heal pops, success notes, Victory |
| `aether` | `#b39ddb` | **channelling & abilities**: channel chips/ticks/zone, ability lane tags, LLM-generation accents |
| `spell` | `#8fb8d8` | **spell lane** tags and card-name references in text |

Text neutrals: `parch` `#e8e4d8` (primary), `mist` `#98a0ae` (secondary),
`dimmed` `#59616e` (tertiary/disabled). Mana keeps the WUBRG SVG symbols
(`public/assets/mana/*.svg`) and the `mana.*` colours.

**Frame-state precedence** (one frame state at a time, highest stakes wins):
target brackets → execute-window (blood brackets + ember) → holder breathe /
acting ember → focus edge (tide) → plain `border-line2` hairline.

---

## 4. Typography

Two faces, no webfonts (all local system faces):

| Role | Stack | Usage |
|---|---|---|
| **Display** — `font-display` | Optima, Candara, Gill Sans, Segoe UI | names, stat numerals, labels, banners, buttons |
| **Body** — `font-sans` | -apple-system / SF Pro Text / Segoe UI / Roboto | rules text, log body, helper copy — always `font-light` (300) |

The workhorse class is **`.caps-label`** (`index.css`): Optima + uppercase +
default `letter-spacing: .25em`. The default tracking sits in a
`:where(.caps-label)` rule (zero specificity) so per-element `tracking-[…]`
utilities always win; the font/transform half has normal specificity because
Tailwind preflight resets `text-transform` on `<button>`. **Don't merge those
two rules back together** — both halves exist for a reason.

Tracking scale (wider = more ceremonial):
- `.3em` — panel titles, End Turn, section headers, Victory/Defeat
- `.14–.2em` — buttons, seat chips, phase steps, zone labels
- `.02–.1em` — names that must fit a card width
- **Mixed case** (no `.caps-label`): hand-card titles, rules text, log body.

Sizing: battlefield-card overlays clamp against viewport height
(`text-[clamp(9px,1.4vh,13px)]` etc.) so they stay legible at any window size.
Long creature names (>15 chars, non-boss) drop one notch instead of truncating
(`NAME_LONG` in `CreatureCard.tsx`). When a wide-tracked title must be optically
centred, compensate the trailing letter-space with `pl-[<tracking>]` (see the
Victory title).

---

## 5. Iconography

One family, defined in [`src/components/Icons.tsx`](src/components/Icons.tsx):
24×24 viewBox, `stroke="currentColor"`, **1.6px** stroke, round caps/joins.
Decorative engravings (skull, sigil) drop to **1.1px** and render at 40–50%
opacity. Colour is always inherited — brass on dark by default.

- Actions: `IconSword` `IconShield` `IconMend` `IconMove`
- Zones: `IconLibrary` `IconGrave` `IconChannel`
- Chrome: `IconLink` `IconGear` `IconPlus` `IconX` `IconUpload` `IconEdit`
- Placeholders: `IconSkull` (creature art slot), `IconSigil` (card art slot,
  empty portrait)
- Keywords: `KEYWORD_ICONS` maps every registry keyword id
  (flying/reach/first_strike/…) to a sigil; unknown ids fall back to a
  small-caps initial so nothing renders blank.

Keyword badges are 17px square chips (`KeywordBadges.tsx`): `bg-ink-0/75`,
`border-line2`, brass icon; the +N/+N counter chip uses vigor.

---

## 6. Component Recipes

Copy these class recipes rather than inventing variants.

**Ghost button** (default action):
`caps-label border border-line px-3 py-1.5 text-[10px] tracking-[0.16em] text-mist hover:border-line2 hover:text-parch`

**Brass button** (affirmative):
`caps-label border border-brass/60 bg-brass/10 text-brass hover:bg-brass hover:text-ink-0`
— when it's THE primary CTA of the surface, add `chamfer-x` and the
brass-gradient fill (see End Turn / Start Game).

**Armed/active state**: `border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0`.

**Danger button**: `caps-label border border-blood/60 bg-blood/15 text-blood hover:bg-blood hover:text-parch`.

**Disabled**: `cursor-not-allowed border-line/50 text-dimmed/60` (+ `opacity-60`
on icon buttons). Never grey fills.

**Panel**: `panel-ticks border border-line bg-black/25 px-2.5 py-2` with a
`caps-label text-[10px] tracking-[0.3em] text-brass` title.

**Modal**: backdrop `bg-black/70 backdrop-blur-[2px]`; shell
`panel-ticks border border-line2 bg-ink-2 p-4+`; title = `ModalTitle` in
`Modals.tsx` (brass caps + trailing hairline). Choice rows use `CHOICE_BTN`.

**Stat gem** (cards): edge-bleed plaque —
`absolute -left-px / -right-px border border-line bg-ink-0/80 px-1.5 py-0.5 font-display`
with the flush edge's border removed (`border-l-0` / `border-r-0`). Power sits
bottom-left, HP bottom-right (MTG P/T position), creature level top-left in the
same chrome with a Roman numeral (`roman()` in `format.ts`).

**Scrims** (cards): top `h-1/5 from-black/50`; bottom
`h-[38%] from-black/90 via-black/50 to-transparent`. Nameplate text sits on the
bottom scrim — never on a solid bar.

**Inputs**: `border border-line bg-ink-0 px-2 py-1.5 text-sm font-light
focus:border-brass/60 focus:outline-none` (aether focus in LLM-generation
contexts). Labels: `caps-label text-[9px] tracking-[0.2em] text-mist`.

**Floating prompts** (arming hint, mana payment): solid brass pill —
`border border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0` —
floated above the console. These are the only solid-brass fills besides
armed/active buttons.

---

## 7. Motion

All keyframes live in `index.css`. Rules: ≤2.6s, `ease-in-out`, colour-coded to
§3. **Only "awaiting you / ongoing" states loop; event effects fire once.**

| Class | What | Loops? |
|---|---|---|
| `anim-breathe` | brass glow breath — priority holder's card | yes |
| `anim-ember` | crimson smoulder — enemy with an action on the stack; also the execute window | yes |
| `.brackets` | pulsing corner brackets on every legal target (colour via `--bracket-color`; blood for execute) | yes |
| `anim-stackglow` | next-to-resolve stack row | yes |
| `anim-statpop` | floating ±N combat numeral (`StatPop.tsx`, driven by HP diffs between snapshots) | once |
| `anim-banner` + `anim-banner-line` | transient turn/phase title card: letter-spacing condenses while hairlines draw out, holds, fades (2.4s, matched by a JS timer) | once |
| `anim-banner-in` | persistent top-of-stack banner: sweeps in, then **holds** until the effect resolves or is replaced (keyed by stack uid) | holds |

Micro-interactions: hand cards lift `-translate-y-1.5` with deepening shadow on
hover; armed card stays lifted with a brass edge; mana symbols `scale-110` when
clickable. While anything is armed, all non-targets dim to `opacity-40`.

---

## 8. Interaction Grammar

- **Brass = actionable.** Armed control lights solid brass; legal targets get
  brackets; everything else dims. Same grammar for cards, move-row picking, and
  stack-row counter targets.
- **Esc / right-click** cancels any arming or open zone modal, everywhere.
- **Banners**: the top of the stack is always mirrored in the persistent centre
  banner (what you'd be responding to); phase/turn changes get the transient
  title card. Phases in `SILENT_PHASES` (`reaction window`, `enemy intents`)
  are never announced — intents are not broadcast to players, so nothing in the
  UI may reveal them.
- **Tooltips** carry the full detail wherever text truncates (`title=` on
  cards, channels, intent-adjacent chips).
- **Log affordance**: card names in Chronicle/Stack rows are dotted-underlined
  in `spell`; hovering pops the full card at a fixed position.

---

## 9. Extending the System

Checklist for any new UI:

1. Reuse the tokens — no new hex values, no Tailwind default palette
   (`slate-*`, `gray-*`, `blue-*`… are all banned in this app).
2. No emoji; add to `Icons.tsx` if a new pictogram is needed (1.6px stroke).
3. No rounded corners; hairline borders; `panel-ticks` on major containers.
4. Labels are `.caps-label` Optima; body text `font-light`; sizes ≥10px for
   anything the player must read in play.
5. Brass only for things the player can act on right now.
6. New states animate with an existing keyframe if one fits the meaning;
   new keyframes go in `index.css` and follow §7's rules.
7. Anything that can hold future art gets a reserved placeholder layer, not a
   layout that will shift when art arrives.

Related docs: the approval mockup (self-contained HTML with the original visual
spec) was delivered in the 2026-07-06 design session; engine↔UI field contracts
are in [`INTERFACE_NOTES.md`](../../INTERFACE_NOTES.md).
