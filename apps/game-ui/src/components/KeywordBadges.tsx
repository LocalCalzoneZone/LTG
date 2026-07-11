import type { KeywordInfo } from "../lib/types";
import { KEYWORD_ICONS } from "./Icons";

const BADGE =
  "flex h-[clamp(14px,2.2vh,20px)] w-[clamp(14px,2.2vh,20px)] items-center justify-center " +
  "border bg-ink-0/75 leading-none";

/** Vertical stack of engraved keyword sigils plus a (+X) counters chip and the
 * typed-counter chips (poison −0/−1, regen +0/+1 — Design Update 08 §D8-2).
 * Presentation only: names and glosses arrive pre-labelled from the server.
 * Unknown or future keywords fall back to a small-caps initial, so nothing
 * renders blank. */
export function KeywordBadges({ keywords, counters, poison = 0, regen = 0 }: {
  keywords: KeywordInfo[];
  counters: number;
  poison?: number;
  regen?: number;
}) {
  if (keywords.length === 0 && counters <= 0 && poison <= 0 && regen <= 0) return null;
  return (
    <div className="flex flex-col items-center gap-0.5">
      {keywords.map((kw) => {
        const Icon = KEYWORD_ICONS[kw.id];
        return (
          <span
            key={kw.id}
            title={kw.gloss ? `${kw.name}: ${kw.gloss}` : kw.name}
            className={`${BADGE} border-line2 text-brass`}
          >
            {Icon ? (
              <Icon className="h-[70%] w-[70%]" />
            ) : (
              <span className="caps-label text-[clamp(7px,1.1vh,10px)] tracking-normal">
                {kw.name.charAt(0).toUpperCase()}
              </span>
            )}
          </span>
        );
      })}
      {counters > 0 && (
        <span
          title={`+${counters}/+${counters} counters: permanently +${counters} Power and +${counters} HP (already included in the stats shown)`}
          className={`${BADGE} border-vigor/50 font-display text-[clamp(7px,1.1vh,10px)] text-vigor`}
        >
          +{counters}
        </span>
      )}
      {poison > 0 && (
        <span
          title={`${poison} poison counter(s): −0/−${poison} (already in the stats shown). Any healing cures the ticking; the counters remain.`}
          className={`${BADGE} border-[#a9bf5e]/60 font-display text-[clamp(7px,1.1vh,10px)] text-[#a9bf5e]`}
        >
          −{poison}
        </span>
      )}
      {regen > 0 && (
        <span
          title={`${regen} regen counter(s): +0/+${regen} (already in the stats shown). Broken by damage that connects.`}
          className={`${BADGE} border-vigor/60 font-display text-[clamp(7px,1.1vh,10px)] text-vigor`}
        >
          ~{regen}
        </span>
      )}
    </div>
  );
}
