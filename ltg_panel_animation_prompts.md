# Character Panel Animations — MiniMax H3 I2V Working Notes

Working doc for generating panel animations offline (MiniMax H3, I2V workflow) and
pre-loading them per character. First test case: Lasarre.

## Generation settings

| Setting | Recommendation | Why |
|---|---|---|
| Aspect ratio | 9:16, portrait | Game-ui panels render at `aspect-[9/16]` with `background-size: cover / top`; Lasarre's source portrait is 905×1600 (native 9:16). |
| Resolution | 768×1344 (H3 native canvas, 768 short edge) | Panels render small in the UI; the 2K upscale pass is wasted pixels. Native canvas is faster and the 32-px grid rounds 9:16 to 768×1344. |
| Duration | Generate 5 s; play full clip (speed up via `playbackRate` if needed) | H3 outputs 5–15 s at 24 fps on a 17-frame block grid. Never trim the action out of the middle — that cuts off the pose return. See "Getting back to the default pose" below. |
| FPS | 24 (H3 native) | Don't retime; panel motion should feel breath-slow anyway. |
| Model (ComfyUI) | `minimax_h3_fl2va_pruned_int8_convrot` | The FL2VA weights are the T2V/I2V variant; ref2va is for R2V only. |
| Delivery format | WebM (VP9), **audio stripped**, ~1–2 MB/clip | Plays in the web UI via `<video muted autoplay>`. H3 bakes stereo audio into every clip — drop it; SFX should come from the engine, not per-character video files. |
| Storage | `content/anim/<char_slug>/<action>.webm` | `content/` is tracked and ships through the Update button, and these are pre-generated content, not runtime data. |

Post-process encode (strip audio + VP9; only ever shave the static tail — see below):

```bash
ffmpeg -i raw.mp4 -t 4.0 -an -c:v libvpx-vp9 -crf 32 -b:v 0 -pix_fmt yuv420p attack.webm
```

## The two rules that make panels work

1. **First frame = the panel PNG.** H3's I2V treats the supplied image as the literal
   frame at 0.00 s. That means the static-portrait → video swap in the UI is invisible:
   start the `<video>` on action resolve, and frame 0 is pixel-identical to the panel.
2. **Last frame = first frame.** Every clip (except `death`) must end back on the
   default pose so the video → static-portrait swap at the end is also invisible.

One structural constraint in every prompt: **a single continuous shot, no hard cuts,
returning to the opening framing by the final second.** Within that envelope, dynamic
motion — the character moving, the camera pushing, jolting, or drifting — is what
makes the clips feel alive. Do NOT prompt for stillness: test runs showed that
"static camera, locked framing, subtle, restrained" language turns the character
into a statue. The endpoint keyframes handle the return; the prompt's job is the
action in between.

## Getting back to the default pose

Three mechanisms, layered strongest-first:

1. **Feed the panel PNG as both the first AND last keyframe.** The I2V model is
   literally `fl2va` — first-and-last-frame conditioning. Supplying the same image
   at both endpoints makes the pose return a model guarantee instead of a prompt
   hope. Use this for every clip except `death` (which holds its own final frame).
2. **One return line in the prompt, nothing more.** End each timeline with a beat
   like "she recovers into the pose of the opening frame" and leave it at that.
   Don't reinforce it with stillness language ("holds nearly still", "exact pose",
   "locked") — that bleeds backward into the whole clip and freezes the action
   (learned in testing). Never cut a beat out of the middle of a clip in post —
   that severs the pose return.
3. **Speed at playback, not at the cutting board.** If 5 s reads too slow for an
   attack resolve, set `video.playbackRate = 1.5–2.0` in the UI — a 5 s clip lands
   in 2.5–3.3 s with the return intact, and 24 fps motion at 2× still looks clean
   for subtle panel movement. Worth one experiment: local ComfyUI's duration input
   aligns to the 17k+5 frame grid, so it may accept ~3 s generations even though
   hosted endpoints floor at 5 s — if that works, no speedup is needed at all.

## Prompting practices (distilled from the guides)

- **Assign the image a job explicitly**: "Use the input image as the exact opening frame."
  Don't re-describe or redesign the first frame in prose — describe forward from it.
- **List the identity anchors.** H3 doesn't assume a character persists; name the
  defining features you need preserved (hair, outfit, props, background character).
- **Use a bracketed timeline** — `[0–1.5 s] … [1.5–3 s] …` — instead of one run-on
  description. This is the single biggest quality lever for H3.
- **Cinematography vocabulary reads directly** ("punchy push-in", "camera jolt",
  "motion blur", "soft highlight halation") — use it to *direct* dynamic camera
  work, not to forbid it. A push-in on the strike and an ease-back on the recovery
  reads great in a panel as long as the shot resolves to the opening framing.
- **Negative direction is for scene integrity, not motion suppression.** "One
  continuous shot, no cuts" — yes. "Static camera, locked framing, no movement,
  subtle, restrained" — no: that stacks into a statue. Prompt bold verbs (whips,
  lunges, erupts, slams) and let the endpoint keyframes handle the return.
- **Reserve "subtle/gentle" language for the `channel` loop only**, where continuous
  cyclical motion (orbiting, pulsing, floating cloth) is the goal — and even there,
  keep the motion continuous rather than still.
- Prompt capacity is ~7,000 characters — these panel prompts are deliberately short;
  don't pad them.
- Audio fields exist (`soundscape` / music); keep them minimal since we strip audio,
  but a plausible soundscape line helps H3's motion timing, so leave one in.

## Which actions get an animation

Recommended starter set (5 clips per character, reused across all their cards):

| Action | Trigger in engine | In-game playback | Loop? |
|---|---|---|---|
| `attack` | basic/stance attack resolves | full clip at 1.5–2× (~2.5–3.3 s) | no |
| `cast` | any spell resolves (generic) | full clip at 1.5–2× (~2.5–3.3 s) | no |
| `defend` | Defend action resolves (gain temp HP) | full clip at 1.5× (~3.3 s) | no |
| `mitigate` | Mitigate reaction applies to an incoming hit | full clip at 2× (~2.5 s) | no |
| `channel` | channeled skill begins / while channeling | full clip at 1× | yes — end matches start |
| `hit` | takes damage | full clip at 2× (~2.5 s) | no |
| `death` | HP reaches 0 | full clip at 1×, hold last frame | no |

Deferred: `victory`, per-color big-spell variants, `idle` (the CSS `idle-sway`
already covers idle well and costs nothing).

Directionality note: player panels sit on the left facing enemies to the right, so
projectiles/impacts are prompted frame-right (outgoing) and from frame-right
(incoming). If a panel ever renders mirrored, flip the clip at encode time
(`-vf hflip`), not at generation time.

---

## Lasarre — test prompts

Shared preamble (paste at the top of every prompt, then append the action block):

> Use the input image as the exact opening frame at 0.00 seconds. Preserve the
> character's identity throughout: a pale young woman with long black hair and
> blue-grey eyes, gold star earrings, an indigo hooded cloak with gold
> embroidery, black leather corset armor with gold clasps, brown leather belts, a
> crystal-pommeled dagger at her hip, blue arcane flame magic, and glowing blue
> crystal shards that float around her, in a dark smoky arena with drifting
> orange embers. One continuous shot with no cuts. By the final second, the
> character and camera return to the pose and framing of the opening frame.

### 1. `attack` — Crystal darts (stance attack)

> [0–1 second] The crystal shards above her head whip into a fast orbit, trailing
> blue light; she pivots her shoulders and draws her raised hand back, the flame
> flaring bright, her cloak swinging with the coiled motion. [1–2.5 seconds] She
> lunges a half step forward and hurls her palm toward the upper right of frame; a
> volley of crystal darts rips off-screen with blazing trails and motion blur, the
> camera giving a short punchy push-in with the throw as smoke blasts outward from
> the recoil. [2.5–5 seconds] The camera eases back out, fresh shards condense
> from the darkness and swing back into their arc, and she recovers into the
> raised-hand pose of the opening frame.
>
> Soundscape: a rising crystalline whine, three sharp glassy whooshes with a bass
> impact, then soft resonant ringing.

### 2. `cast` — generic spell resolve

> [0–1.5 seconds] She sweeps both arms upward and the blue arcane flame erupts
> from her palm into spiraling ribbons of light that wrap around her body; her
> cloak billows and her hair lifts on the magical updraft as the crystal shards
> spin into a wide, fast orbit. [1.5–3 seconds] With a full arm gesture she
> carves a blazing sigil into the air; it detonates in a burst of blue-white
> light with soft highlight halation washing over her face and the gold
> embroidery, the camera drifting in on the flash. [3–5 seconds] The sigil
> collapses into a swarm of sparks that stream back into her palm, the shards
> settle into their arc, the camera returns to its original framing, and she
> lands back in the pose of the opening frame.
>
> Soundscape: a low hum building fast, a deep resonant boom at the sigil burst,
> then crackling embers and a fading shimmer.

### 3. `defend` — crystal barrier (temp HP)

> [0–1.5 seconds] She sweeps her raised hand across her body in a sharp guarding
> arc; the crystal shards dive out of their orbit and multiply, snapping together
> in front of her into an interlocking lattice of glowing blue crystal panes,
> each pane locking in with a ripple of light across the growing wall. [1.5–3
> seconds] The finished barrier flares brilliant blue, refracting her silhouette
> behind it; she braces, cloak pressed back by the outrush of power, embers
> scattering off the crystal face as the camera pushes in slightly on the glow.
> [3–5 seconds] The lattice dissolves into bright motes that sink into her arms
> and shoulders with a lingering shimmer of shielding light, the shards climb
> back into their arc, and she recovers into the pose of the opening frame.
>
> Soundscape: rapid glassy clicks stacking into a chord as the panes lock, a
> deep hum at the flare, then a soft fading shimmer.

### 4. `mitigate` — snap deflection (incoming hit blunted)

> [0–1 second] A hostile streak of force lashes in from the right of frame; her
> eyes snap toward it and she twists, whipping her raised hand across her body
> as the crystal shards dive to intercept. [1–2.5 seconds] The shards flatten
> into a small angled pane that catches the blow with a hard flash — the strike
> glances away toward the upper left in a spray of blue splinters and orange
> sparks, the camera jolting with the parry while she holds her footing, cloak
> snapping around her. [2.5–5 seconds] The cracked pane shatters into harmless
> drifting glitter, the shards re-form and swing back into their arc, and she
> straightens into the pose of the opening frame with a defiant lift of her chin.
>
> Soundscape: a fast incoming whoosh, a hard glassy crack of deflection, sparks
> fizzing out, then a settling resonant hum.
>
> (Ally-mode Mitigate also dashes her to the protected ally's row — if that ever
> wants its own clip, add a variant where she blurs a step toward frame-left
> before the intercept. Start with this generic deflection.)

### 5. `channel` — Resonate (looping stance)

> Continuous cyclical motion for a seamless loop. The crystal shards lock into a
> slowly rotating ring above her head, pulsing with blue light in paired
> double-beats — two quick pulses, a pause, two quick pulses — while arcs of
> energy crackle between them and down into her raised hand. The arcane flame
> stretches and coils in rhythm with the pulses, her hair and cloak float on a
> steady magical updraft, and the smoke behind her churns in a slow vortex lit by
> ember light. Her eyes glow with rising blue light as she holds her stance with
> contained, humming intensity. The rotation and pulsing stay continuous and
> even, and the final frame matches the opening frame so the clip loops
> seamlessly.
>
> Soundscape: a sustained crystalline drone with a two-note pulse repeating in
> rhythm with the light, and low electric crackles.

### 6. `hit` — damage taken

> [0–1 second] A violent rush of force slams in from the right of frame: she is
> knocked a half step sideways, doubling slightly over, her cloak and hair
> whipping hard to the left as the crystal shards are blasted out of their arc
> with dimming light, and the camera jolts with the impact. [1–2.5 seconds]
> Orange embers burst through the churning smoke; she catches herself, plants
> her stance, and snaps her head back up with narrowed glowing eyes as the flame
> in her palm roars back to life. [2.5–5 seconds] The shards sweep back into
> their arc and rekindle, the camera settles back to its original framing, and
> she straightens into the pose of the opening frame.
>
> Soundscape: a hard impact thud with glassy clatter, a sharp intake of breath,
> then a low hum swelling as the glow returns.

### 7. `death` — defeat

> [0–1.5 seconds] The arcane flame flickers violently and dies to a fading
> spark; she staggers, catching herself on a lowered arm, as the crystal shards
> crack with spreading fracture lines and their light gutters. [1.5–3.5 seconds]
> The shards burst into slow-falling glittering dust around her; she sinks to
> one knee, cloak pooling around her, head bowing as the smoke closes in and the
> embers wink out one by one, the camera drifting down slightly with her fall.
> [3.5–5 seconds] Darkness settles until only a cold blue rim of light traces
> her kneeling silhouette, and the motion comes to rest on a still final frame.
> No fade to black.
>
> Soundscape: the hum unwinding downward in pitch, glassy crumbling like falling
> sand, then near-silence with a faint cold air tone.
>
> (I2V only — do not supply a last-frame keyframe for this clip; it ends on its
> own final image, which the UI holds.)

---

## Sources

- [MiniMax H3 Prompting Guide + 44 examples — fal.ai](https://fal.ai/learn/devs/minimax-h3-prompting-guide)
- [MiniMax H3 ComfyUI workflow — docs.comfy.org](https://docs.comfy.org/tutorials/video/minimax/minimax-h3)
- [MiniMax H3 prompt guide — RunDiffusion](https://www.rundiffusion.com/minimax-h3-prompt-guide)
