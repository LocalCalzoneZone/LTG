import type { StatusChip } from "../lib/types";

// How many chips a card shows before folding the rest into "+N".
const MAX_SHOWN = 3;

/** A card's condition chips (roadmap M2.8): a small right-aligned stack in
 * the intent-chip vocabulary — blood for a hostile condition, vigor for a
 * boon. Lockdown comes first (the server orders them). */
export function StatusChips({ chips }: { chips: StatusChip[] }) {
  if (!chips.length) return null;
  const shown = chips.slice(0, MAX_SHOWN);
  const rest = chips.slice(MAX_SHOWN);
  return (
    <div className="pointer-events-auto flex flex-col items-end gap-0.5">
      {shown.map((c) => (
        <span
          key={c.label}
          data-tip={c.tip}
          className={`caps-label whitespace-nowrap border bg-ink-0/85 px-1 py-px text-[clamp(8px,1.1vh,10px)] tracking-[0.12em] ${
            c.tone === "bane" ? "border-blood/60 text-blood" : "border-vigor/50 text-vigor"
          } ${c.pulse ? "neglect-pending" : ""}`}
        >
          {c.label}
        </span>
      ))}
      {rest.length > 0 && (
        <span
          data-tip={rest.map((c) => `${c.label}: ${c.tip}`).join("\n")}
          className="caps-label border border-line2 bg-ink-0/85 px-1 py-px text-[clamp(8px,1.1vh,10px)] tracking-[0.12em] text-mist"
        >
          +{rest.length}
        </span>
      )}
    </div>
  );
}
