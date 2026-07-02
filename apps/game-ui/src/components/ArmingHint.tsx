import { useGame } from "../lib/store";

/** A slim banner shown while a target selection is in progress — surfaces the
 *  per-site progress for independent multi-target casts and where to click for a
 *  stack-targeting counter. */
export function ArmingHint() {
  const armed = useGame((s) => s.armed);
  const cancelArm = useGame((s) => s.cancelArm);
  if (!armed) return null;

  const step =
    armed.numSites > 1 ? ` — select target ${armed.site + 1} of ${armed.numSites}` : " — select a target";
  const counterHint = armed.kind === "cast" && [...(armed.candidates[0]?.targets ?? [])].length === 0 &&
    (armed.candidates[0]?.target_id ?? "").startsWith("#")
    ? " (click an action on the Stack)"
    : "";

  return (
    <div className="absolute -top-8 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-full bg-yellow-500 px-4 py-1 text-sm font-semibold text-black shadow-lg">
      <span>
        {armed.label}
        {step}
        {counterHint}
      </span>
      <button onClick={cancelArm} className="rounded bg-black/20 px-2 py-0.5 text-xs hover:bg-black/40">
        Esc ✕
      </button>
    </div>
  );
}
