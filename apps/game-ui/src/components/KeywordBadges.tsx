import type { KeywordInfo } from "../lib/types";
import { KEYWORD_ICONS } from "./Icons";

const BADGE =
  "flex h-[clamp(14px,2.2vh,20px)] w-[clamp(14px,2.2vh,20px)] items-center justify-center " +
  "border bg-ink-0/75 leading-none";

/** Vertical stack of engraved keyword sigils plus a (+X) counters chip.
 * Presentation only: names and glosses arrive pre-labelled from the server.
 * Unknown or future keywords fall back to a small-caps initial, so nothing
 * renders blank. */
export function KeywordBadges({ keywords, counters }: { keywords: KeywordInfo[]; counters: number }) {
  if (keywords.length === 0 && counters <= 0) return null;
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
    </div>
  );
}
