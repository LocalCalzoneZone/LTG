// Board motion: FLIP-slides combatant cards between layout positions and
// keeps a live registry of their on-screen rects. Pure presentation — the
// engine already moved the piece; this makes the move VISIBLE instead of a
// teleport between flex columns. The registry doubles as the aiming source
// for lunges and projectile bolts (rectOf).

import { useLayoutEffect, useRef, type RefObject } from "react";

import { scaleOf } from "./fieldView";

const rects = new Map<string, DOMRect>();

/** Last measured on-screen rect of a combatant card (by entity id). */
export function rectOf(id: string): DOMRect | undefined {
  return rects.get(id);
}

const reducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** FLIP pass over every `[data-fid]` card under `root`, re-run per snapshot:
 * a card whose layout position changed starts at its OLD position and glides
 * to the new one. WAAPI, so it composes with (and never dirties) the cards'
 * own classes and inline styles. */
export function useFlip(root: RefObject<HTMLElement | null>, dep: unknown) {
  const prev = useRef<Map<string, DOMRect>>(new Map());
  const prevRoot = useRef<[number, number, number] | null>(null);

  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    // The board may be zoomed (the pane's camera). Measurements come back in
    // VIEWPORT pixels while the FLIP transform is applied inside the scaled
    // stage, so every delta is converted back to stage-local pixels.
    const scale = scaleOf(el);
    // If the CAMERA moved (zoom, pan) or the pane itself was resized since the
    // last pass, every stored rect is stale: re-baseline them and animate
    // nothing. The board did not move — the viewer did.
    const box = el.getBoundingClientRect();
    const now: [number, number, number] = [box.left, box.top, box.width];
    const before = prevRoot.current;
    const moved =
      before !== null && now.some((v, i) => Math.abs(v - before[i]) > 0.5);
    prevRoot.current = now;
    const seen = new Set<string>();
    el.querySelectorAll<HTMLElement>("[data-fid]").forEach((node) => {
      const id = node.dataset.fid;
      if (!id) return;
      const r = node.getBoundingClientRect();
      seen.add(id);
      const p = prev.current.get(id);
      prev.current.set(id, r);
      rects.set(id, r);
      if (!p || moved || reducedMotion()) return;
      const dx = (p.left - r.left) / scale;
      const dy = (p.top - r.top) / scale;
      if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
      node.animate(
        [
          { transform: `translate(${dx}px, ${dy}px)` },
          { transform: "translate(0, 0)" },
        ],
        { duration: 460, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
      );
    });
    // Departed cards must not leave stale aim points behind.
    for (const id of [...rects.keys()]) {
      if (!seen.has(id)) {
        rects.delete(id);
        prev.current.delete(id);
      }
    }
  }, [root, dep]);
}

/** CSS vars aiming a melee lunge from `sourceId` toward `targetId` — a fixed-
 * length nudge along the real on-screen vector (flattened vertically so it
 * reads as a step, not a leap). Falls back to a horizontal jab. */
export function lungeVars(
  sourceId: string,
  targetId: string | undefined,
  fallbackDx: number,
): React.CSSProperties {
  const s = rectOf(sourceId);
  const t = targetId ? rectOf(targetId) : undefined;
  if (!s || !t) {
    return { "--lx": `${fallbackDx}px`, "--ly": "0px" } as React.CSSProperties;
  }
  const dx = t.left + t.width / 2 - (s.left + s.width / 2);
  const dy = t.top + t.height / 2 - (s.top + s.height / 2);
  const len = Math.hypot(dx, dy) || 1;
  return {
    "--lx": `${((dx / len) * 22).toFixed(1)}px`,
    "--ly": `${((dy / len) * 12).toFixed(1)}px`,
  } as React.CSSProperties;
}
