import { useGame } from "../lib/store";
import { IconX } from "./Icons";

/** A slim banner shown while a target selection is in progress — surfaces the
 *  per-site progress for independent multi-target casts and where to click for a
 *  stack-targeting counter. */
export function ArmingHint() {
  const armed = useGame((s) => s.armed);
  const cancelArm = useGame((s) => s.cancelArm);
  if (!armed) return null;

  // The effect this site feeds (e.g. "weaken −0/−3"), when the server named it.
  const siteLabel = armed.targetLabels[armed.site] ?? null;
  const progress = armed.numSites > 1 ? ` (${armed.site + 1} of ${armed.numSites})` : "";
  const step = siteLabel
    ? ` — choose target to ${siteLabel}${progress}`
    : armed.numSites > 1
      ? ` — select target ${armed.site + 1} of ${armed.numSites}`
      : " — select a target";
  const stackFacing = armed.kind === "cast" && [...(armed.candidates[0]?.targets ?? [])].length === 0 &&
    (armed.candidates[0]?.target_id ?? "").startsWith("#");
  // A copy re-aims a single-target spell as it resolves; any other copy keeps
  // the original's targets — say so BEFORE the pick, not after (playtest).
  const counterHint = !stackFacing
    ? ""
    : siteLabel === "copy"
      ? " (click a spell on the Stack — a single-target copy is re-aimed as it resolves; any other copy keeps the original's targets)"
      : " (click an action on the Stack)";

  return (
    <div className="absolute -top-9 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 border border-brass bg-gradient-to-b from-brass-hi to-brass px-4 py-1 text-sm font-normal text-ink-0 shadow-[0_8px_20px_rgba(0,0,0,0.5)]">
      <span>
        {armed.label}
        {step}
        {counterHint}
      </span>
      <button
        onClick={cancelArm}
        title="Cancel (Esc)"
        className="flex items-center bg-black/15 px-2 py-1 hover:bg-black/30"
      >
        <IconX size={11} />
      </button>
    </div>
  );
}
