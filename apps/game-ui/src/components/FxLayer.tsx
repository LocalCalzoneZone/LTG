import { useGame } from "../lib/store";
import type { FxEvent } from "../lib/fx";

// The per-card combat-FX layer: renders every live one-shot effect aimed at
// this entity, absolutely over the card art. Pure presentation — each effect
// is a couple of divs driven by the fx-* keyframes in index.css, mounted for
// FX_TTL and pruned by the store.

/** Effect intensity from a damage/heal amount: 1 (chip) → ~1.8 (haymaker). */
function magnitude(amount?: number): number {
  return 1 + Math.min(10, Math.max(0, (amount ?? 3) - 1)) * 0.08;
}

function Chip({ text, tone }: { text: string; tone: "brass" | "blood" | "poison" | "tide" }) {
  const cls =
    tone === "brass"
      ? "border-brass/70 bg-ink-0/90 text-brass-hi"
      : tone === "blood"
        ? "border-blood/70 bg-ink-0/90 text-blood"
        : tone === "tide"
          ? "border-[#82b4c9]/70 bg-ink-0/90 text-[#a9cbd9]"
          : "border-[#7da05a]/70 bg-ink-0/90 text-[#a5c97a]";
  return (
    <div
      className={`caps-label fx-chip absolute left-1/2 top-[12%] z-30 whitespace-nowrap border px-1.5 py-0.5 text-[9px] tracking-[0.14em] ${cls}`}
    >
      {text}
    </div>
  );
}

function Effect({ fx }: { fx: FxEvent }) {
  const mag = magnitude(fx.amount);
  const scaled = { "--fx-mag": mag } as React.CSSProperties;
  switch (fx.kind) {
    case "hit":
      return (
        <div className="fx-wrap overflow-hidden" style={scaled}>
          <div className="fx-hit-flash" />
          <div className="fx-hit-slash" />
        </div>
      );
    case "arcane":
      return (
        <div className="fx-wrap" style={scaled}>
          <div className="fx-flash" style={{ background: "radial-gradient(60% 60% at 50% 50%, rgba(179,157,219,0.55), transparent 70%)" }} />
          <div className="fx-ring" style={{ borderColor: "rgba(179,157,219,0.9)" }} />
        </div>
      );
    case "heal":
      return (
        <div className="fx-wrap overflow-hidden" style={scaled}>
          <div className="fx-heal-glow" />
          <div className="fx-ring" style={{ borderColor: "rgba(132,199,147,0.8)" }} />
        </div>
      );
    case "pump":
      return (
        <div className="fx-wrap overflow-hidden">
          <div className="fx-diamonds fx-rise">
            {[0, 1, 2].map((i) => (
              <span key={i} className="fx-diamond border-vigor bg-vigor/30"
                    style={{ animationDelay: `${i * 0.12}s`, left: `${28 + i * 22}%` }} />
            ))}
          </div>
        </div>
      );
    case "wound":
      return (
        <div className="fx-wrap overflow-hidden">
          <div className="fx-diamonds fx-sink">
            {[0, 1, 2].map((i) => (
              <span key={i} className="fx-diamond border-blood bg-blood/30"
                    style={{ animationDelay: `${i * 0.12}s`, left: `${28 + i * 22}%` }} />
            ))}
          </div>
        </div>
      );
    case "keyword":
      return (
        <div className="fx-wrap">
          <div className="absolute inset-0 overflow-hidden">
            <div className="fx-shimmer" />
          </div>
          {fx.label && <Chip text={fx.label} tone="brass" />}
        </div>
      );
    case "stun":
      return (
        <div className="fx-wrap">
          <div className="fx-ring fx-ring-slow" style={{ borderColor: "rgba(194,90,80,0.9)" }} />
          <div className="fx-ring fx-ring-slow" style={{ borderColor: "rgba(194,90,80,0.6)", animationDelay: "0.25s" }} />
          <Chip text="stunned" tone="blood" />
        </div>
      );
    case "poison":
      return (
        <div className="fx-wrap">
          <div className="fx-flash" style={{ background: "radial-gradient(70% 70% at 50% 60%, rgba(125,160,90,0.5), transparent 72%)" }} />
          <Chip text="poisoned" tone="poison" />
        </div>
      );
    case "skill":
      return (
        <div className="fx-wrap">
          <div className="fx-flash" style={{ background: "radial-gradient(65% 65% at 50% 50%, rgba(233,204,130,0.45), transparent 70%)" }} />
          <div className="fx-sigil border-brass-hi" />
        </div>
      );
    case "ultimate":
      return (
        <div className="fx-wrap">
          <div className="fx-flash fx-flash-strong" style={{ background: "radial-gradient(70% 70% at 50% 50%, rgba(233,204,130,0.75), transparent 72%)" }} />
          <div className="fx-ring fx-ring-big" style={{ borderColor: "rgba(233,204,130,1)" }} />
          <div className="fx-ring fx-ring-big" style={{ borderColor: "rgba(233,204,130,0.7)", animationDelay: "0.22s" }} />
          <div className="fx-sigil border-brass-hi" />
        </div>
      );
    case "enrage":
      return (
        <div className="fx-wrap fx-shake">
          <div className="fx-flash fx-flash-strong" style={{ background: "radial-gradient(70% 70% at 50% 50%, rgba(194,90,80,0.7), transparent 72%)" }} />
          <div className="fx-ring fx-ring-big" style={{ borderColor: "rgba(194,90,80,1)" }} />
          <Chip text="enraged" tone="blood" />
        </div>
      );
    case "detonate":
      return (
        <div className="fx-wrap">
          <div className="fx-flash" style={{ background: "radial-gradient(65% 65% at 50% 50%, rgba(233,204,130,0.6), transparent 70%)" }} />
          <div className="fx-ring fx-ring-big" style={{ borderColor: "rgba(233,204,130,0.9)" }} />
        </div>
      );
    case "revive":
      return (
        <div className="fx-wrap overflow-hidden">
          <div className="fx-revive-sweep" />
          <div className="fx-diamonds fx-rise">
            {[0, 1, 2].map((i) => (
              <span key={i} className="fx-diamond border-brass-hi bg-brass/30"
                    style={{ animationDelay: `${i * 0.15}s`, left: `${28 + i * 22}%` }} />
            ))}
          </div>
        </div>
      );
    case "downed":
      return (
        <div className="fx-wrap fx-shake">
          <div className="fx-flash fx-flash-strong" style={{ background: "radial-gradient(80% 80% at 50% 50%, rgba(194,90,80,0.65), transparent 75%)" }} />
        </div>
      );
    case "countered":
      return (
        <div className="fx-wrap">
          <div className="fx-ring fx-ring-collapse" style={{ borderColor: "rgba(160,170,185,0.9)" }} />
          <Chip text="countered" tone="blood" />
        </div>
      );
    case "defend":
      return (
        <div className="fx-wrap">
          <div className="absolute inset-0 overflow-hidden">
            <div className="fx-sweep-up" style={{ background: "linear-gradient(to top, rgba(130,180,201,0.5), transparent 65%)" }} />
          </div>
          <div className="fx-bulwark" />
        </div>
      );
    case "mitigate":
      return (
        <div className="fx-wrap">
          <div className="fx-flash" style={{ background: "radial-gradient(60% 60% at 50% 50%, rgba(210,225,235,0.35), transparent 70%)" }} />
          <div className="fx-sigil fx-sigil-in" style={{ borderColor: "rgba(169,203,217,0.95)" }} />
          {fx.label && <Chip text={fx.label} tone="tide" />}
        </div>
      );
    case "absorb":
      return (
        <div className="fx-wrap">
          <div className="fx-flash" style={{ background: "radial-gradient(65% 65% at 50% 50%, rgba(130,180,201,0.45), transparent 72%)" }} />
          <div className="fx-ring fx-ring-collapse" style={{ borderColor: "rgba(169,203,217,0.85)" }} />
          {fx.label && <Chip text={fx.label} tone="tide" />}
        </div>
      );
    default:
      return null;
  }
}

/** Mounts inside an entity card (relative root): plays every live effect
 * aimed at that entity. */
export function FxLayer({ id }: { id: string }) {
  const fx = useGame((s) => s.fx);
  const mine = fx.filter((e) => e.entityId === id);
  if (!mine.length) return null;
  return (
    <>
      {mine.map((e) => (
        <Effect key={e.key} fx={e} />
      ))}
    </>
  );
}

/** Full-viewport treatments for the biggest moments (mount once, over the
 * battlefield, under the modals): an Ultimate's golden flash, a boss enrage's
 * crimson pulse. The battlefield itself shakes via useScreenShake. */
export function ScreenFx() {
  const fx = useGame((s) => s.fx);
  const screen = fx.filter((e) => e.screen);
  if (!screen.length) return null;
  return (
    <>
      {screen.map((e) => (
        <div key={`screen-${e.key}`} className="pointer-events-none fixed inset-0 z-20">
          {e.kind === "ultimate" ? (
            <div className="fx-screen-flash" style={{ background: "radial-gradient(90% 90% at 50% 45%, rgba(233,204,130,0.32), transparent 75%)" }} />
          ) : (
            <div className="fx-screen-pulse" />
          )}
        </div>
      ))}
    </>
  );
}

/** True while a screen-scale effect is live — the battlefield adds fx-shake. */
export function useScreenShake(): boolean {
  return useGame((s) => s.fx.some((e) => e.screen));
}
