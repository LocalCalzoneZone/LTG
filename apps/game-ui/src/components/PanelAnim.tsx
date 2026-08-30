import { useEffect, useRef, useState } from "react";
import { useGame } from "../lib/store";
import type { PanelAnimBundle, PanelAnimation } from "../lib/types";

// The panel-animation player (Update 16): a hero's portrait swaps for a
// pre-generated clip when the matching action resolves, then swaps back.
// Every clip is generated from the panel PNG as its first (and last) frame, so
// the swaps are invisible — the video is simply laid over the portrait with the
// same cover/top fit and shown while it plays.
//
// Trigger events arrive as `panel` fx (label = animation id) from lib/fx.ts.
// This component owns the clip's lifetime; the fx entry itself is a short
// pulse. Priority when clips collide on one panel: death / victory > ultimate >
// the rest > hit — a higher-or-equal-priority newcomer replaces the current
// clip; a lower one is skipped (a flinch never interrupts a cast). Victory sits
// at the top because the fight is over: nothing that follows should cut the
// celebration short. Death still wins — it is terminal, so a hero who fell on
// the last exchange keeps their held final frame instead of cheering.
//
// Death and victory both HOLD their final frame rather than dropping back to
// the portrait: the fight is over either way, and the panel should stay in its
// ending pose. A held death frame releases on revive; a held victory frame
// releases when the next encounter begins.
//
// Revive is the one thing allowed to break death's terminal hold: the clip is
// authored to open on the death clip's final frame and end on the portrait
// pose, so it plays over the held frame and hands back to the portrait when it
// ends (normal clear — revive does not hold).

const PRIORITY: Record<string, number> = { hit: 0, death: 3, ultimate: 2, revive: 3, victory: 3 };
const prio = (a: PanelAnimation) => PRIORITY[a.trigger] ?? 1;
const holds = (a: PanelAnimation) => a.trigger === "death" || a.trigger === "victory";
const isVideo = (a: PanelAnimation) => /\.(webm|mp4)(\?|$)/i.test(a.file);

interface Playing {
  anim: PanelAnimation;
  key: string; // the fx key — a new firing of the same clip restarts it
}

interface Props {
  charId: string;
  bundle: PanelAnimBundle | null | undefined;
  incapacitated: boolean;
}

const NONE: PanelAnimation[] = [];

export function PanelAnim({ charId, bundle, incapacitated }: Props) {
  const anims = bundle?.animations ?? NONE;
  const [playing, setPlaying] = useState<Playing | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const videos = useRef<Map<string, HTMLVideoElement>>(new Map());
  const imgTimer = useRef<number | null>(null);

  // The trigger pulses aimed at this panel (filtered inside the effect: a
  // filtered selector would hand back a fresh array on every store change).
  const fx = useGame((s) => s.fx);
  // The fight this panel belongs to — when it changes (the next adventure
  // phase, a new encounter in the same session) a held victory frame releases.
  const encounterId = useGame((s) => s.snapshot?.encounter_id);

  useEffect(() => {
    const pulses = fx.filter((e) => e.kind === "panel" && e.entityId === charId);
    for (const p of pulses) {
      if (seen.current.has(p.key)) continue;
      seen.current.add(p.key);
      const anim = anims.find((a) => a.id === p.label);
      if (!anim) continue;
      setPlaying((cur) => {
        // Death is terminal — nothing but a revive replaces it once it has begun.
        if (cur && cur.anim.trigger === "death" && anim.trigger !== "revive") return cur;
        if (cur && prio(anim) < prio(cur.anim)) return cur;
        return { anim, key: p.key };
      });
    }
    // Forget pulses the store has already pruned, so the set stays small.
    if (seen.current.size > 64) {
      const live = new Set(pulses.map((p) => p.key));
      seen.current = new Set([...seen.current].filter((k) => live.has(k)));
    }
  }, [fx, charId, anims]);

  // Drive playback: start the chosen clip from frame 0 at its speed; when it
  // ends, drop back to the portrait (death and victory clips hold their final
  // frame instead).
  useEffect(() => {
    if (imgTimer.current != null) {
      window.clearTimeout(imgTimer.current);
      imgTimer.current = null;
    }
    if (!playing) return;
    const { anim } = playing;
    if (isVideo(anim)) {
      const el = videos.current.get(anim.id);
      if (!el) return;
      const clear = () => setPlaying((cur) => (cur?.key === playing.key ? null : cur));
      el.currentTime = 0;
      el.playbackRate = anim.speed > 0 ? anim.speed : 1;
      el.onended = holds(anim) ? null : clear; // death/victory hold their last frame
      el.onerror = clear;
      // A play() interrupted by pause() (React StrictMode re-running the effect,
      // or a higher-priority clip taking over) rejects with AbortError — that is
      // not a broken clip, so only a real failure drops back to the portrait.
      void el.play().catch((err: unknown) => {
        if ((err as { name?: string })?.name !== "AbortError") clear();
      });
      // Watchdog: a browser may suspend a muted video (hidden tab, throttled
      // pane) so `ended` never fires — never leave the panel stuck on a clip.
      const speed = anim.speed > 0 ? anim.speed : 1;
      const budget = ((Number.isFinite(el.duration) && el.duration > 0 ? el.duration : 10) / speed) * 1000 + 1500;
      const watchdog = holds(anim) ? null : window.setTimeout(clear, budget);
      return () => {
        el.onended = null;
        el.onerror = null;
        if (watchdog != null) window.clearTimeout(watchdog);
        if (!holds(anim)) el.pause();
      };
    }
    // Animated image: browsers can't retime or signal the end, so the panel
    // shows it for the authored duration and swaps back (holding triggers stay).
    if (!holds(anim)) {
      imgTimer.current = window.setTimeout(
        () => setPlaying((cur) => (cur?.key === playing.key ? null : cur)),
        Math.max(300, (anim.duration_s || 5) * 1000),
      );
    }
    return undefined;
  }, [playing]);

  // A revived hero drops the held death frame. With a revive clip authored,
  // the drop waits for the revive pulse to replace the frame instead — an
  // instant swap to the portrait would jump the pose the clip is about to
  // stand up from. The timeout is the safety net for a revival that never
  // fires the pulse (e.g. a between-phases heal): it outlasts the fx
  // scheduler's delay cap, and by then either the revive clip is playing (the
  // conditional clear is a no-op) or the frame must release regardless.
  useEffect(() => {
    if (incapacitated) return;
    const drop = () =>
      setPlaying((cur) => (cur && cur.anim.trigger === "death" ? null : cur));
    if (!anims.some((a) => a.trigger === "revive" && !a.alternate)) {
      drop();
      return;
    }
    const t = window.setTimeout(drop, 4000);
    return () => window.clearTimeout(t);
  }, [incapacitated, anims]);

  // A new fight drops the held victory frame — the celebration lasts exactly
  // until the next round begins.
  useEffect(() => {
    setPlaying((cur) => (cur && cur.anim.trigger === "victory" ? null : cur));
  }, [encounterId]);

  if (!anims.length) return null;
  const media = "pointer-events-none absolute inset-0 h-full w-full object-cover object-top";
  return (
    <>
      {/* Every video clip stays mounted (preloaded, hidden) so playback starts
          on the frame the action lands, not after a fetch. Only the active one
          is visible. */}
      {anims.filter(isVideo).map((a) => (
        <video
          key={a.id}
          ref={(el) => {
            if (el) videos.current.set(a.id, el);
            else videos.current.delete(a.id);
          }}
          src={a.file}
          muted
          playsInline
          preload="auto"
          aria-hidden
          className={media}
          style={{ visibility: playing?.anim.id === a.id ? "visible" : "hidden" }}
        />
      ))}
      {playing && !isVideo(playing.anim) && (
        // Re-keyed per firing so the animated image restarts from its first frame.
        <img key={playing.key} src={playing.anim.file} alt="" aria-hidden className={media} />
      )}
    </>
  );
}
