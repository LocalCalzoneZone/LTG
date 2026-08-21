// The battlefield pane's own camera: zoom, pan, reset. Presentation only — it
// moves the viewer, never the board. A crowded field (four rows of cards, a
// swarm of tokens, a boss card) can outgrow the pane; this lets the player pull
// back to take it all in, push in on a scrum, and snap back to the default
// framing.
//
// The transform lives on ONE stage element inside the pane. Everything that
// measures card positions off the DOM (the FLIP slide, projectile aiming) reads
// the stage's live scale with `scaleOf` and divides its viewport deltas by it,
// so a zoomed board animates and aims exactly like an unzoomed one.

import { useCallback, useEffect, useRef, useState } from "react";

export const MIN_ZOOM = 0.45;
export const MAX_ZOOM = 2.4;
const STEP = 1.2; // one button press / wheel notch, multiplicative
const SLACK = 48; // px of pan allowed even when the board already fits
const DRAG_THRESHOLD = 4; // px before a press becomes a pan (so clicks survive)
const CLICK_GUARD_MS = 250; // how long after a pan a trailing click is swallowed

const KEY = "ltg.field.view";

export interface FieldView {
  scale: number;
  x: number;
  y: number;
  panning: boolean;
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
  canZoomIn: boolean;
  canZoomOut: boolean;
  isDefault: boolean;
  onWheel: (e: React.WheelEvent) => void;
  onPointerDown: (e: React.PointerEvent) => void;
  onClickCapture: (e: React.MouseEvent) => void;
}

/** The rendered scale of a transformed element (1 when untransformed). Derived
 * from the element itself — measured width over layout width — so no caller has
 * to be told what the camera is doing. */
export function scaleOf(el: HTMLElement | null | undefined): number {
  if (!el) return 1;
  const layout = el.offsetWidth;
  if (!layout) return 1;
  const s = el.getBoundingClientRect().width / layout;
  return s > 0.01 ? s : 1;
}

const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** Hold the pan inside the overflow the zoom actually creates (plus a little
 * slack), so the board can never be shoved off the pane and lost. */
function clampPan(x: number, y: number, scale: number, el: HTMLElement | null) {
  const w = el?.clientWidth ?? 0;
  const h = el?.clientHeight ?? 0;
  const maxX = Math.max(0, (w * scale - w) / 2) + SLACK;
  const maxY = Math.max(0, (h * scale - h) / 2) + SLACK;
  return {
    x: Math.min(maxX, Math.max(-maxX, x)),
    y: Math.min(maxY, Math.max(-maxY, y)),
  };
}

interface Saved {
  scale: number;
  x: number;
  y: number;
}

function load(): Saved {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "");
    if (raw && typeof raw.scale === "number") {
      return { scale: clampZoom(raw.scale), x: Number(raw.x) || 0, y: Number(raw.y) || 0 };
    }
  } catch {
    /* no saved camera — the default framing */
  }
  return { scale: 1, x: 0, y: 0 };
}

/** The pane's camera. `viewport` is the element the stage sits in — its box
 * bounds the pan and anchors pointer-centred zoom. */
export function useFieldView(viewport: React.RefObject<HTMLElement | null>): FieldView {
  const [view, setView] = useState<Saved>(load);
  const [panning, setPanning] = useState(false);
  // The live view, so the pointer handlers never close over a stale one.
  const ref = useRef(view);
  ref.current = view;
  // When the last real pan ended — the trailing click of a drag is swallowed,
  // so dragging the board never also picks a target. It EXPIRES on its own:
  // a drag that ends off-window (no trailing click) must not eat the next
  // genuine click minutes later.
  const pannedAt = useRef(0);

  useEffect(() => {
    if (view.scale === 1 && view.x === 0 && view.y === 0) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, JSON.stringify(view));
  }, [view]);

  /** Re-zoom about a point (viewport coordinates), keeping whatever sits under
   * that point where it is — the pointer stays on the card it was over. */
  const zoomAbout = useCallback(
    (factor: number, clientX?: number, clientY?: number) => {
      const el = viewport.current;
      setView((v) => {
        const scale = clampZoom(v.scale * factor);
        const k = scale / v.scale;
        if (k === 1) return v;
        let { x, y } = v;
        if (el && clientX != null && clientY != null) {
          const r = el.getBoundingClientRect();
          // Offset of the anchor from the pane's centre (the transform origin).
          const ax = clientX - (r.left + r.width / 2);
          const ay = clientY - (r.top + r.height / 2);
          x = ax - k * (ax - x);
          y = ay - k * (ay - y);
        } else {
          x *= k;
          y *= k;
        }
        return { scale, ...clampPan(x, y, scale, el) };
      });
    },
    [viewport],
  );

  const zoomIn = useCallback(() => zoomAbout(STEP), [zoomAbout]);
  const zoomOut = useCallback(() => zoomAbout(1 / STEP), [zoomAbout]);
  const reset = useCallback(() => setView({ scale: 1, x: 0, y: 0 }), []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      if (!e.deltaY) return;
      zoomAbout(e.deltaY < 0 ? STEP : 1 / STEP, e.clientX, e.clientY);
    },
    [zoomAbout],
  );

  // Drag to pan. The press only becomes a pan once it has travelled past the
  // threshold, so clicking a card (arming a target, focusing a character) is
  // untouched — and the click that ends a real pan is swallowed.
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0 && e.button !== 1) return;
      const el = viewport.current;
      const start = { cx: e.clientX, cy: e.clientY, x: ref.current.x, y: ref.current.y };
      let live = false;

      const move = (ev: PointerEvent) => {
        const dx = ev.clientX - start.cx;
        const dy = ev.clientY - start.cy;
        if (!live) {
          if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
          live = true;
          setPanning(true);
        }
        setView((v) => ({ ...v, ...clampPan(start.x + dx, start.y + dy, v.scale, el) }));
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
        if (!live) return;
        setPanning(false);
        pannedAt.current = performance.now();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
    },
    [viewport],
  );

  const onClickCapture = useCallback((e: React.MouseEvent) => {
    if (performance.now() - pannedAt.current > CLICK_GUARD_MS) return;
    pannedAt.current = 0;
    e.stopPropagation(); // the click that closed a pan — not a target pick
  }, []);

  return {
    ...view,
    panning,
    zoomIn,
    zoomOut,
    reset,
    canZoomIn: view.scale < MAX_ZOOM - 0.001,
    canZoomOut: view.scale > MIN_ZOOM + 0.001,
    isDefault: view.scale === 1 && view.x === 0 && view.y === 0,
    onWheel,
    onPointerDown,
    onClickCapture,
  };
}
