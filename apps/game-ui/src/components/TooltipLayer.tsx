import { useEffect, useRef, useState } from "react";

// The themed tooltip (roadmap M2.18): one layer for the whole app, driven by a
// `data-tip` attribute on any element — so a component swaps `title=` for
// `data-tip=` and gets the Brasswork plate instead of the OS tooltip. Text is
// shown as written, line breaks included.

const SHOW_DELAY_MS = 280;
const MAX_W = 300;
const GAP = 8;

type Tip = { text: string; left: number; top: number; above: boolean };

export function TooltipLayer() {
  const [tip, setTip] = useState<Tip | null>(null);
  const timer = useRef<number | null>(null);
  const current = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const clear = () => {
      if (timer.current != null) window.clearTimeout(timer.current);
      timer.current = null;
      current.current = null;
      setTip(null);
    };
    const onOver = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest?.<HTMLElement>("[data-tip]") ?? null;
      if (el === current.current) return;
      clear();
      const text = el?.getAttribute("data-tip");
      if (!el || !text) return;
      current.current = el;
      timer.current = window.setTimeout(() => {
        if (!el.isConnected) return;
        const r = el.getBoundingClientRect();
        const above = r.top > 120;
        const left = Math.max(GAP, Math.min(r.left + r.width / 2 - MAX_W / 2,
                                            window.innerWidth - MAX_W - GAP));
        setTip({ text, left, top: above ? r.top - GAP : r.bottom + GAP, above });
      }, SHOW_DELAY_MS);
    };
    window.addEventListener("mouseover", onOver);
    window.addEventListener("mousedown", clear, true);
    window.addEventListener("scroll", clear, true);
    window.addEventListener("keydown", clear, true);
    return () => {
      clear();
      window.removeEventListener("mouseover", onOver);
      window.removeEventListener("mousedown", clear, true);
      window.removeEventListener("scroll", clear, true);
      window.removeEventListener("keydown", clear, true);
    };
  }, []);

  if (!tip) return null;
  return (
    <div
      role="tooltip"
      className="pointer-events-none fixed z-[90] flex"
      style={{
        left: tip.left,
        width: MAX_W,
        top: tip.top,
        transform: tip.above ? "translateY(-100%)" : undefined,
        justifyContent: "center",
      }}
    >
      <div className="anim-tip-in whitespace-pre-line border border-line2 bg-ink-0/95 px-2.5 py-1.5 text-[11.5px] font-light leading-snug text-parch shadow-[0_8px_20px_rgba(0,0,0,0.55)]">
        {tip.text}
      </div>
    </div>
  );
}
