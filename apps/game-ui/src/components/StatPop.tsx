import { useEffect, useRef, useState } from "react";

// Floating combat numeral: watches an entity's current HP and pops the delta
// (crimson for damage, green for healing) when it changes. Card components stay
// mounted across snapshots (stable React keys), so a ref-diff is all we need —
// no log parsing, no engine knowledge.
export function StatPop({ hp }: { hp: number }) {
  const prev = useRef<number | null>(null);
  const [pop, setPop] = useState<{ delta: number; key: number } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    const before = prev.current;
    prev.current = hp;
    if (before == null || before === hp) return;
    seq.current += 1;
    setPop({ delta: hp - before, key: seq.current });
  }, [hp]);

  // Clear after the 1.6s statpop animation so re-hits of the same size re-fire.
  useEffect(() => {
    if (!pop) return;
    const t = window.setTimeout(
      () => setPop((p) => (p && p.key === pop.key ? null : p)),
      1700,
    );
    return () => window.clearTimeout(t);
  }, [pop]);

  if (!pop) return null;
  const dmg = pop.delta < 0;
  // The numeral scales with the blow: a 1-point chip whispers, a 12-point
  // haymaker shouts (size and glow both grow, capped so it stays on the card).
  const mag = 1 + Math.min(11, Math.abs(pop.delta) - 1) * 0.09;
  const glow = Math.round(10 + Math.min(11, Math.abs(pop.delta)) * 2.2);
  return (
    <div
      key={pop.key}
      className="anim-statpop pointer-events-none absolute left-1/2 top-1/3 z-20 font-display"
      style={{
        fontSize: `calc(clamp(18px, 3vh, 30px) * ${mag.toFixed(2)})`,
        color: dmg ? "#ff9e8f" : "#a9e6b6",
        textShadow: dmg
          ? `0 0 ${glow}px rgba(194,60,45,.95), 0 1px 2px #000`
          : `0 0 ${glow}px rgba(90,180,110,.85), 0 1px 2px #000`,
      }}
    >
      {dmg ? `−${-pop.delta}` : `+${pop.delta}`}
    </div>
  );
}
