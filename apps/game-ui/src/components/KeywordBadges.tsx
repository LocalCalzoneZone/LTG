import type { KeywordInfo } from "../lib/types";

// One glyph per registry keyword (core/ltg_core/schema.py KEYWORDS). Unknown or
// future keywords fall back to their first letter, so nothing renders blank.
const KEYWORD_GLYPHS: Record<string, string> = {
  flying: "🕊",
  reach: "↗",
  first_strike: "⚡",
  double_strike: "⚔",
  vigilance: "👁",
  haste: "💨",
  trample: "⇶",
  deathtouch: "☠",
  lifelink: "❤",
  hexproof: "⊘",
  indestructible: "🪨",
  protection: "🛡",
};

const BADGE =
  "flex h-[clamp(14px,2.2vh,22px)] w-[clamp(14px,2.2vh,22px)] items-center justify-center " +
  "rounded-full text-[clamp(8px,1.3vh,13px)] leading-none shadow ring-1 ring-white/25";

/** Vertical stack of circular keyword icons plus a (+X) counters badge.
 * Presentation only: names and glosses arrive pre-labelled from the server. */
export function KeywordBadges({ keywords, counters }: { keywords: KeywordInfo[]; counters: number }) {
  if (keywords.length === 0 && counters <= 0) return null;
  return (
    <div className="flex flex-col items-center gap-0.5">
      {keywords.map((kw) => (
        <span key={kw.id} title={kw.gloss ? `${kw.name}: ${kw.gloss}` : kw.name} className={`${BADGE} bg-indigo-600/90 text-white`}>
          {KEYWORD_GLYPHS[kw.id] ?? kw.name.charAt(0).toUpperCase()}
        </span>
      ))}
      {counters > 0 && (
        <span
          title={`+${counters}/+${counters} counters: permanently +${counters} Power and +${counters} HP (already included in the stats shown)`}
          className={`${BADGE} bg-emerald-600/90 font-bold text-white`}
        >
          +{counters}
        </span>
      )}
    </div>
  );
}
