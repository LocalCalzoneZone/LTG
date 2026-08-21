# LTG Panel-Animation Prompt Guide (for an LLM)

You are writing **MiniMax H3 image-to-video prompts** for one character in the
Langelier Tactical Game (LTG). You will be given:

1. **This guide.**
2. **The character's panel portrait** (a 9:16 image). Every clip starts on this
   exact frame.
3. **The character's loadout JSON** (the deckbuilder export). It tells you who
   the character is, how they fight, and what their signature abilities look like.

Your job: produce a **complete, ready-to-paste set of prompts** — one per action
type below, plus any alternates the JSON calls for — following the rules here
exactly. The prompts are fed to H3 as I2V (image-to-video) generations with the
portrait as the first frame; the resulting 5-second clips play over the
character's panel in the game when that action resolves.

---

## 1. What a panel animation is (why the rules exist)

The game shows the static portrait; when an action resolves it swaps in the clip,
plays it, and swaps back. Two facts make the swap invisible:

- **Frame 0 of the clip is the portrait** (H3 I2V treats the input image as the
  literal first frame).
- **The clip ends back on the portrait pose and framing** (the generation is run
  with the portrait as both the first AND last keyframe — H3's `fl2va`
  first-and-last-frame conditioning — so the return is guaranteed by the model,
  not by your prose).

So every prompt must describe **a single continuous shot that erupts into motion
and returns to the opening pose in its final second**. The exception is `death`,
which ends on its own final image and holds there.

The game also **delays the board's reaction (hit flash, damage, enemy death)
until the clip's impact moment**, so you will state, per clip, the second at
which the action lands (`impact_s`).

---

## 2. Read the loadout JSON — what to extract

The JSON is `{ "ltg_version", "character": {...}, "cards": [...] }`. Read these:

| Field | Use it for |
|---|---|
| `character.name`, `character.description` | Who they are (e.g. "Crystal Mage"). Sets the visual language of every clip. |
| `character.colors` (W/U/B/R/G) | Magic school palette hints — W light/gold, U blue/water/arcane, B violet/shadow/blood, R fire/orange, G green/nature. Blend for multicolour. Use to colour spells, glows, particles. |
| `character.attack_mode` (`melee` / `ranged`) | Melee = a swing/lunge toward frame-right; ranged = a projectile leaving frame-right. |
| `character.ability_flavor.attack/defend/mitigate` — `{name, text}` | **The single most important field.** These are the author's own descriptions of the default Attack, Defend and Mitigate. Depict exactly what `text` says (e.g. "flashes a crystal blade from the end of her sceptre and slashes"). If absent, invent something consistent with the description/colours and say so. |
| `character.skill` — a card object: `name`, `flavor_text`, `translated_text`, `timing`, `effects` | The Skill clip. `flavor_text` is the author's in-character description — depict it. `translated_text` is the rules text — read it for what visibly happens (damage, buff, stance). `timing == "channeled"` means it is a held state — the Skill clip is a *power-up/ignition* and there should also be a looping `channel` clip. |
| `character.skill.effects[]` with `kind: "stance"` | A stance rewires attack/defend/mitigate/move while channeled. Each replaced slot is `{name, effects, animation}`. **A replaced `attack` gets its own alternate clip** (e.g. "Crystal darts" instead of the default blade slash). Replaced defend/mitigate may too if visually distinct. |
| `character.ultimate` — card object | The Ultimate clip. `flavor_text` describes it; `translated_text` gives scale (e.g. "Deal 20 damage to a target and its row plus adjacent rows" = huge). |
| `cards[]` — each `{name, timing, flavor_text, translated_text, ...}` | Context for the generic `cast` clip: skim the flavour texts to see how this character's spells *look* (erupting rings of crystal? shadow tendrils? beams of light?). Do NOT write a clip per card unless asked; the generic `cast` covers them. Also: any card with `timing == "channeled"` supports the `channel` clip's look. |
| `character.animations[]` (may be present) | Clips that already exist. If non-empty, only write prompts for **missing** triggers unless asked to redo. |

Ignore everything else (costs, HP, mana, ids).

---

## 3. Fixed generation facts (state these once at the top of your output)

- **Format:** 9:16 portrait, 5 s, 24 fps, 768×1344 (H3 native canvas). Video
  only — audio is stripped in game.
- **Model / conditioning:** H3 I2V (`fl2va`), portrait as **first and last
  keyframe** for every clip except `death` (I2V only, no last keyframe).
- **Delivery:** WebM (VP9), audio stripped, played at ×1. Never trim a beat out
  of the middle of a clip (it severs the pose return); if a clip must be shorter,
  retime the whole thing uniformly.

---

## 4. Prompt construction rules

Every prompt = **shared preamble** + **action block**. Write the preamble once,
then one action block per clip.

### 4.1 The shared preamble
Written **from the portrait**, not from your imagination. Look at the image and
list the identity anchors H3 must preserve — H3 does not assume the character
persists, so name what matters: hair, eyes, skin, distinctive garments and their
colours, armour, jewellery, weapon/prop, the visible magic (colour, form,
where it is), the background. Then two structural sentences:

> Use the input image as the exact opening frame at 0.00 seconds. Preserve the
> character's identity throughout: [anchors…], in [background]. One continuous
> shot with no cuts. By the final second, the character and camera return to
> the pose and framing of the opening frame.

Do NOT re-describe or redesign the first frame in the action blocks — describe
forward from it.

### 4.2 The action block
- **Bracketed timeline**, three or four beats: `[0–1 s] … [1–2.5 s] … [2.5–5 s] …`.
  This is the biggest quality lever for H3.
- **Bold motion.** Verbs like *whips, lunges, erupts, slams, hurls, detonates,
  snaps, blasts*. The character moves; cloth and hair move; the magic moves.
  Test runs proved that stillness language ("static camera, locked framing,
  subtle, restrained, holds nearly still, exact pose") turns the character into
  a statue. **Never use it** — not even to "help" the return.
- **Dynamic camera is welcome and encouraged**: "a punchy push-in with the
  swing", "the camera jolts with the impact", "eases back out on the recovery".
  Direct it with cinematography vocabulary; do not forbid it. It must resolve to
  the opening framing in the last beat.
- **Exactly one return line**, as the last beat, plainly: "…and she recovers
  into the raised-hand pose of the opening frame." Nothing more about the pose.
- **Directionality:** the character's panel sits on the LEFT of the battlefield
  facing enemies on the RIGHT. Outgoing attacks/projectiles go **toward frame
  right (often upper right)**; incoming blows arrive **from frame right**.
- **Beat placement:** the visible *impact* of an attack/cast should land between
  ~1.5 s and ~2.5 s. Wind-up before it, recovery after it. Report that time as
  `impact_s`. For the ultimate the impact may be later (3–4 s of a 5 s clip).
- **Structural negatives only:** "no cuts" is fine; "no fade to black" for death
  is fine. Never negatives about motion.
- **A one-line soundscape** at the end of each block (audio is stripped, but it
  helps H3's motion timing). Keep it short.
- **Length:** ~90–150 words per action block. Do not pad.

### 4.3 What each clip must depict

| Trigger | The clip shows… | Derive from | `impact_s` guide |
|---|---|---|---|
| `attack` | The **default attack** exactly as `ability_flavor.attack.text` describes; melee = lunge/swing toward frame right, ranged = projectile leaves frame right. Camera push-in on the strike. | `ability_flavor.attack`, `attack_mode` | 1.5–2.0 |
| `cast` | A **generic spell resolve** in the character's school — magic swells, a gesture, a burst/flash toward frame right or around them, sparks return. Not any specific card. | `colors`, `description`, the flavour texts of `cards[]` | 1.5–2.5 |
| `defend` | The **Defend** action per `ability_flavor.defend.text` — a barrier/armour/ward forms on or in front of them, flares, then sinks in with a lingering shimmer (temp HP that persists). | `ability_flavor.defend` | 1.5–2.0 |
| `mitigate` | The **Mitigate** reaction per `ability_flavor.mitigate.text` — an incoming strike from frame right is **deflected/blunted** (parry, buckler, sidestep). Deliberately the counterpoint of `hit`: same incoming setup, but they hold their footing and deflect, then straighten defiantly. | `ability_flavor.mitigate` | 1.0–1.5 |
| `skill` | The **Skill** per `skill.flavor_text`. If the skill is channeled (a stance / held state) this is the *ignition*: a power-up that leaves them visibly charged (glowing eyes/veins/aura) on the return pose. If it is a one-shot action, depict its effect. | `skill.flavor_text`, `skill.translated_text`, `skill.timing` | 1.5–2.5 (if it deals damage) |
| `channel` | A **seamless loop** of the held/amplified state: continuous cyclical motion — orbiting, pulsing, floating cloth, crackling energy, churning smoke. Continuous, even, and the final frame matches the first. This is the only clip where "continuous / cyclical / even" language is right — but still *moving*, never still. | `skill` if channeled, else the character's channeled cards / colours | n/a (write 0) |
| `ultimate` | The **Ultimate** per `ultimate.flavor_text` at the scale `translated_text` implies. This is the one clip allowed to leave the panel framing for most of its length (camera tilts/whips to sell scale) and only return in the last second. | `ultimate.flavor_text`, `ultimate.translated_text` | 3.0–4.0 |
| `hit` | **Takes damage**: a rush of force slams in from frame right, they are knocked/staggered (not thrown), magic gutters, camera jolts; they catch themselves and recover. | portrait, colours | n/a (write 0) |
| `death` | **Incapacitated**: their magic dies, they stagger and sink (to a knee, slumped) as light drains, ending on a still dark final image with a cold rim light. I2V only — no last-frame keyframe. "No fade to black." | portrait, colours | n/a (write 0) |
| `victory` | **The fight is won**: the party's celebration, played on every standing hero's panel at once when the encounter ends. They straighten out of the fight and mark the win in their own register — a weapon raised or planted, a fist closed, magic flaring bright and settling, a breath let out, a grin or a cold nod — then return to the opening pose. Read it as *this one*'s victory, not a generic cheer, and keep it self-contained: it plays beside the others, so no gesture aimed at a teammate. | `description`, `colors`, `ability_flavor`, portrait bearing | n/a (write 0) |
| **alternates** | One extra clip per **stance-replaced attack** (`skill.effects[kind=stance].attack.name`) depicting that ability, marked `alternate: true`, trigger `attack`. Optionally, alternates for a signature card if the JSON's flavour text is spectacular and clearly distinct from the generic cast. | the stance replacement `name`/`effects`; card `flavor_text` | 1.5–2.0 |

If the JSON lacks the flavour for a slot, invent something on-theme, keep it
consistent with the other clips, and mark it `(invented — no flavour in JSON)`.

---

## 5. Output format (produce exactly this)

```
# <Character name> — panel animation prompts

Generation facts: 9:16 · 5 s · 24 fps · 768×1344 · H3 I2V (fl2va), portrait as first AND last
keyframe (death: I2V only) · deliver WebM (VP9), audio stripped, ×1.

## Shared preamble
> <preamble paragraph>

## Clips
| # | file | title | trigger | alternate | impact_s |
|---|------|-------|---------|-----------|----------|
| 1 | <slug>_attack.webm | <Name> attack | attack | no | 1.8 |
| … | | | | | |

### 1. `attack` — <short subtitle>
> <action block with [timeline], one return line, soundscape line>

### 2. `cast` — …
…
(one section per row of the table, in the table's order)

## Notes
- <anything invented for lack of JSON flavour; anything ambiguous; the fallback used>
```

Filenames: `<character_slug>_<trigger>.webm`, alternates `<character_slug>_<trigger>_alt.webm`
(or `_<abilityname>`). Titles: `<Name> <trigger>` / `<Name> <ability name>`.
`impact_s` is the number the user will type into the deckbuilder's "impact at" field.

The user pastes **preamble + action block** into H3 for each clip.

---

## 6. Quality checklist (run before you answer)

- [ ] Every action block starts with `[0–…]` and its last beat is the single return line (except `death`, which ends on a held still).
- [ ] No stillness words anywhere: *static, locked, still, subtle, restrained, gentle, exact pose, holds* — (the `channel` block may say *continuous / cyclical / even*).
- [ ] Bold verbs and at least one camera move per action clip.
- [ ] Outgoing action goes frame-right; incoming force comes from frame-right.
- [ ] Attack/defend/mitigate depict the JSON's `ability_flavor` texts, not generic moves.
- [ ] Skill/ultimate depict the JSON's `flavor_text`; scale matches `translated_text`.
- [ ] Every stance-replaced attack has an `alternate: true` clip.
- [ ] Preamble anchors come from the actual portrait (colours, garments, props, magic, background).
- [ ] The clip table's `impact_s` matches the second where the block's impact beat lands.
- [ ] Nothing pads: ~90–150 words per block.

---

## 7. Worked example (abridged) — Lasarre, "Crystal Mage", U/B/R, melee

From the JSON: `ability_flavor.attack.text` = "Lasarre flashes a crystal blade
from the end of her sceptre and slashes"; `skill` = *Resonate*, channeled,
flavour "tunes her magic to the shard's resonant modes, amplifying her
abilities", stance replacing attack with *Crystal darts*; `ultimate` = *Crystal
Obelisk*, "summons a massive crystal obelisk above an enemy, then brings it
crashing down", 20 damage to a row and adjacent rows.

**Preamble (from the portrait):**
> Use the input image as the exact opening frame at 0.00 seconds. Preserve the
> character's identity throughout: a pale young woman with long black hair and
> blue-grey eyes, gold star earrings, an indigo hooded cloak with gold
> embroidery, black leather corset armour with gold clasps, brown leather belts,
> a crystal-pommeled dagger at her hip, blue arcane flame magic, and glowing
> blue crystal shards that float around her, in a dark smoky arena with drifting
> orange embers. One continuous shot with no cuts. By the final second, the
> character and camera return to the pose and framing of the opening frame.

**`attack` — crystal blade slash (impact_s 1.8):**
> [0–1 second] The blue arcane flame in her raised hand stretches and hardens
> into a long, gleaming blade of faceted crystal, light rippling down its edge;
> the floating shards whip into a tight orbit and she drops into a fighting
> crouch, drawing the blade back across her body, cloak swinging with the
> wind-up. [1–2.5 seconds] She explodes forward in a diagonal slash toward the
> right of frame — the crystal blade carves a blazing arc of blue light with
> heavy motion blur, smoke splitting in its wake and embers scattering, the
> camera whipping a short punchy push-in with the swing. [2.5–5 seconds] She
> follows through, spins the blade once, and it fractures back into a swirl of
> glowing crystal dust that streams into her palm and re-ignites as the arcane
> flame; the shards resettle overhead, the camera eases back out, and she
> recovers into the raised-hand pose of the opening frame.
>
> Soundscape: a rising crystalline ring as the blade forms, a heavy sword whoosh
> with a glassy edge on the slash, then a shimmering fade.

**`attack` alternate — Crystal darts (stance attack; alternate: yes; impact_s 1.8):**
> [0–1 second] The crystal shards above her head whip into a fast orbit,
> trailing blue light; she pivots her shoulders and draws her raised hand back,
> the flame flaring bright, her cloak swinging with the coiled motion. [1–2.5
> seconds] She lunges a half step forward and hurls her palm toward the upper
> right of frame; a volley of crystal darts rips off-screen with blazing trails
> and motion blur, the camera giving a short punchy push-in with the throw as
> smoke blasts outward from the recoil. [2.5–5 seconds] The camera eases back
> out, fresh shards condense from the darkness and swing back into their arc,
> and she recovers into the raised-hand pose of the opening frame.
>
> Soundscape: a rising crystalline whine, three sharp glassy whooshes with a
> bass impact, then soft resonant ringing.

**`ultimate` — the crystal obelisk (impact_s 3.5):**
> [0–1 second] She thrusts her raised hand high overhead, fingers spread, and
> the arcane flame detonates into a pillar of blue light shooting straight up
> out of frame; her cloak whips violently in the updraft and every floating
> shard rockets skyward after it. [1–2.5 seconds] The camera tilts up to follow:
> high above her the sky tears open with blue-white light and a colossal
> obelisk of dark faceted crystal, veined with burning blue light, materialises
> point-down out of the rift, its facets grinding into place with rippling
> flashes. [2.5–4 seconds] Her hand clenches into a fist and slams down — the
> obelisk plummets with a corona of blue fire and heavy motion blur, and the
> camera whips back down with it as it crashes off-screen to the right of frame:
> a shockwave of dust, embers and crystal splinters blasts across the frame.
> [4–5 seconds] The debris drifts and settles, cold blue light throbbing from
> off-screen, the shards swing back into their arc, the flame re-lights in her
> palm, and she lowers her arm to recover into the raised-hand pose of the
> opening frame.
>
> Soundscape: a rising roar of energy, a vast low grinding tone as the obelisk
> forms, a whistling plunge, then a thunderous crash decaying into a soft
> crystalline ring.

(Write the remaining clips — cast, defend, mitigate, skill, channel, hit, death, victory —
in the same manner, each derived from the JSON fields named in §4.3.)
