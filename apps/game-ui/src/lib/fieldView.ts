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

/** The BOARD's own size in unscaled px — the union of the cards on the stage.
 *
 * This is not the stage's box: the stage is `inset-0` (so its box is exactly the
 * pane) while the cards inside it routinely spill past it — a crowded row runs
 * off the top and bottom even at scale 1, and `scrollHeight` does not see it
 * because the overflow goes both ways. Measuring the cards is what makes the pan
 * limits describe the board the player is actually looking at.
 *
 * Never reported smaller than the pane, so a board that comfortably fits still
 * counts as "no overflow" and keeps the tight nudge-only slack below. */
function measureBoard(stage: HTMLElement | null, viewport: HTMLElement | null,
                      scale: number) {
  const w = viewport?.clientWidth ?? 0;
  const h = viewport?.clientHeight ?? 0;
  const cards = stage?.querySelectorAll<HTMLElement>("[data-fid]");
  if (!cards || !cards.length) return { w, h };
  let top = Infinity, bottom = -Infinity, left = Infinity, right = -Infinity;
  cards.forEach((c) => {
    const r = c.getBoundingClientRect();
    if (!r.width && !r.height) return;      // a card mid-mount measures empty
    top = Math.min(top, r.top);
    bottom = Math.max(bottom, r.bottom);
    left = Math.min(left, r.left);
    right = Math.max(right, r.right);
  });
  if (!Number.isFinite(top)) return { w, h };
  const s = scale > 0.01 ? scale : 1;       // rects come back scaled; undo the camera
  return { w: Math.max(w, (right - left) / s), h: Math.max(h, (bottom - top) / s) };
}

interface BoardSize {
  w: number;
  h: number;
}

/** Hold the pan inside what the board actually needs, so it can never be shoved
 * off the pane and lost — but far enough that no card is stuck against the frame.
 *
 * Reaching the spill alone only parks the outermost card AGAINST the edge of the
 * pane; another half-pane of travel is what lets the player pull it into the
 * middle to read it. So a board that overflows gets `spill + half the pane` on
 * that axis, and a board that already fits keeps the old nudge-only slack (there
 * is nothing off-screen to go and find, and a fitting board should stay framed). */
function clampPan(x: number, y: number, scale: number, el: HTMLElement | null,
                  board?: BoardSize) {
  const w = el?.clientWidth ?? 0;
  const h = el?.clientHeight ?? 0;
  const bw = board?.w ?? w;
  const bh = board?.h ?? h;
  const spillX = Math.max(0, (bw * scale - w) / 2);
  const spillY = Math.max(0, (bh * scale - h) / 2);
  const maxX = spillX > 0 ? spillX + w / 2 : SLACK;
  const maxY = spillY > 0 ? spillY + h / 2 : SLACK;
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
 * anchors pointer-centred zoom; `stage` is the transformed board inside it,
 * measured so the pan limits follow the CARDS rather than the pane's own box. */
export function useFieldView(viewport: React.RefObject<HTMLElement | null>,
                             stage?: React.RefObject<HTMLElement | null>): FieldView {
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
      const board = measureBoard(stage?.current ?? null, el, ref.current.scale);
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
        return { scale, ...clampPan(x, y, scale, el, board) };
      });
    },
    [viewport, stage],
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
      // Measured once per gesture: the board cannot change size mid-drag, and
      // this keeps the pointermove handler off the layout path.
      const board = measureBoard(stage?.current ?? null, el, ref.current.scale);
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
        setView((v) => ({ ...v, ...clampPan(start.x + dx, start.y + dy, v.scale, el, board) }));
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
    [viewport, stage],
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
