/** The "made at" difficulty flag on generated encounters / adventures — a
 * small engraved chip (easy = vigor, standard = mist, hard = blood). Renders
 * nothing for unstamped (hand-authored or pre-flag) content. Display only:
 * difficulty shapes generation budgets, never live rules. */
const TONE: Record<string, string> = {
  easy: "border-vigor/50 text-vigor",
  standard: "border-line2 text-mist",
  hard: "border-blood/60 text-blood",
};

export function DifficultyTag({ difficulty, className = "" }: {
  difficulty?: string;
  className?: string;
}) {
  const d = (difficulty ?? "").trim();
  if (!d) return null;
  return (
    <span
      title={`Generated at ${d} difficulty (budgets and enemy HP were scoped to it)`}
      className={`caps-label shrink-0 border px-1.5 py-0.5 text-[8px] tracking-[0.14em] ${
        TONE[d] ?? "border-line2 text-mist"
      } ${className}`}
    >
      {d}
    </span>
  );
}
