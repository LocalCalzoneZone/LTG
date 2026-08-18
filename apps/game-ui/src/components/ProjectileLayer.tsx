import { useEffect, useRef, type RefObject } from "react";
import type { FxEvent } from "../lib/fx";
import { rectOf } from "../lib/motion";
import { useGame } from "../lib/store";
import { schoolTint } from "./FxLayer";

// Projectiles: every live "bolt" FX event flies a spark from its source card
// to its target card, over the battlefield. Aim comes from the motion
// registry's real on-screen rects; flight is WAAPI (arc keyframes), so
// nothing here re-renders mid-flight.
//
// The two flavours read differently on purpose, and both finish inside the
// 600ms TTL for "bolt":
//   arrow  — 220ms, all but flat, a streak with a muzzle-flare at the bow.
//   arcane — 200ms, a flashing arc of magic FIRED at the target (no lob),
//            tinted with the caster's school, bursting on arrival.
// Both land just after fx.ts BEAT_IMPACT (180ms), so the projectile arrives
// WITH the target's impact effect instead of trailing it.

const ARROW_MS = 220;
const ARCANE_MS = 200;
const FLARE_MS = 200;
const IMPACT_MS = 260;

function Bolt({ fx, field }: { fx: FxEvent; field: RefObject<HTMLDivElement | null> }) {
  const ref = useRef<HTMLDivElement>(null);
  const flareRef = useRef<HTMLDivElement>(null);
  const impactRef = useRef<HTMLDivElement>(null);
  const arrow = fx.variant === "arrow";

  useEffect(() => {
    const el = ref.current;
    const flare = flareRef.current;
    const impact = impactRef.current;
    const root = field.current;
    const s = rectOf(fx.sourceId ?? "");
    const t = rectOf(fx.entityId);
    if (!el || !root || !s || !t) {
      if (el) el.style.display = "none";
      if (flare) flare.style.display = "none";
      if (impact) impact.style.display = "none";
      return;
    }
    const fr = root.getBoundingClientRect();
    const x0 = s.left + s.width / 2 - fr.left;
    const y0 = s.top + s.height * 0.42 - fr.top;
    const x1 = t.left + t.width / 2 - fr.left;
    const y1 = t.top + t.height * 0.45 - fr.top;
    // Both fly FLAT — an arrow barely off the sightline, spellfire a shallow
    // arc of light fired straight at its mark (the lob is gone).
    const mx = (x0 + x1) / 2;
    const my = arrow
      ? (y0 + y1) / 2 - Math.min(10, Math.abs(x1 - x0) * 0.03)
      : (y0 + y1) / 2 - Math.min(14, Math.abs(x1 - x0) * 0.05);
    const angle = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI;
    // The blow's weight scales the whole projectile: a chip shot flies near
    // base size, a haymaker half again as large (matches FxLayer magnitude).
    const mag = 1 + Math.min(10, Math.max(0, (fx.amount ?? 3) - 1)) * 0.07;
    const sc = (x: number, y = x) => `scale(${(x * mag).toFixed(2)}, ${(y * mag).toFixed(2)})`;
    el.animate(
      arrow
        ? [
            { transform: `translate(${x0}px, ${y0}px) rotate(${angle}deg) ${sc(0.8)}`, opacity: 0 },
            { transform: `translate(${x0}px, ${y0}px) rotate(${angle}deg) ${sc(1)}`, opacity: 1, offset: 0.08 },
            { transform: `translate(${mx}px, ${my}px) rotate(${angle}deg) ${sc(1)}`, opacity: 1, offset: 0.5 },
            { transform: `translate(${x1}px, ${y1}px) rotate(${angle}deg) ${sc(1)}`, opacity: 1, offset: 0.9 },
            { transform: `translate(${x1}px, ${y1}px) rotate(${angle}deg) ${sc(1.2)}`, opacity: 0 },
          ]
        : [
            { transform: `translate(${x0}px, ${y0}px) rotate(${angle}deg) ${sc(0.4, 1)}`, opacity: 0 },
            { transform: `translate(${x0}px, ${y0}px) rotate(${angle}deg) ${sc(1.3, 1)}`, opacity: 1, offset: 0.14 },
            { transform: `translate(${mx}px, ${my}px) rotate(${angle}deg) ${sc(1.15, 1)}`, opacity: 1, offset: 0.5 },
            { transform: `translate(${x1}px, ${y1}px) rotate(${angle}deg) ${sc(1, 1)}`, opacity: 1, offset: 0.88 },
            { transform: `translate(${x1}px, ${y1}px) rotate(${angle}deg) ${sc(0.5, 1)}`, opacity: 0 },
          ],
      {
        duration: arrow ? ARROW_MS : ARCANE_MS,
        easing: arrow ? "cubic-bezier(0.15, 0.6, 0.4, 1)" : "cubic-bezier(0.2, 0, 0.55, 1)",
        fill: "forwards",
      },
    );
    // The report at the bow: blooms and dies while the shot is still in the
    // air. Nothing else marks where a ranged attack came FROM.
    if (flare) {
      const at = `translate(${x0}px, ${y0}px)`;
      flare.animate(
        [
          { transform: `${at} ${sc(0.35)}`, opacity: 0 },
          { transform: `${at} ${sc(1)}`, opacity: 1, offset: 0.28 },
          { transform: `${at} ${sc(1.5)}`, opacity: 0 },
        ],
        { duration: FLARE_MS, easing: "ease-out", fill: "forwards" },
      );
    }
    // Spellfire BURSTS on arrival — a ring-and-flash at the point of impact,
    // starting as the bolt lands, sized to the blow.
    if (impact) {
      const at = `translate(${x1}px, ${y1}px)`;
      impact.animate(
        [
          { transform: `${at} ${sc(0.3)}`, opacity: 0 },
          { transform: `${at} ${sc(1)}`, opacity: 1, offset: 0.3 },
          { transform: `${at} ${sc(2)}`, opacity: 0 },
        ],
        {
          duration: IMPACT_MS,
          delay: ARCANE_MS - 40,
          easing: "cubic-bezier(0.2, 0.8, 0.4, 1)",
          fill: "both",
        },
      );
    }
  }, [fx, field, arrow]);

  // School tinting: spellfire wears its caster's colour; an arrow is steel and
  // brass whatever cast it. The CSS reads these off custom properties.
  const school = arrow ? undefined : schoolTint(fx.tint);
  const tinted = school
    ? ({
        "--bolt-core": school.core,
        "--bolt-glow": school.glow,
        "--bolt-trail": school.ring,
      } as React.CSSProperties)
    : undefined;

  return (
    <>
      <div
        ref={ref}
        style={tinted}
        className={`fx-bolt ${arrow ? "fx-bolt-arrow" : "fx-bolt-arcane"}`}
      />
      {arrow && <div ref={flareRef} className="fx-muzzle" />}
      {!arrow && <div ref={impactRef} style={tinted} className="fx-impact-flare" />}
    </>
  );
}

/** Mounts once inside the battlefield's relative root. */
export function ProjectileLayer({ field }: { field: RefObject<HTMLDivElement | null> }) {
  const fx = useGame((s) => s.fx);
  const bolts = fx.filter((e) => e.kind === "bolt");
  if (!bolts.length) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-30">
      {bolts.map((b) => (
        <Bolt key={b.key} fx={b} field={field} />
      ))}
    </div>
  );
}
