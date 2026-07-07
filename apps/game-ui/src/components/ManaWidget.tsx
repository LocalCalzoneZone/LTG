import type { CharacterView } from "../lib/types";
import { canPickMana, castIndexFor, useGame } from "../lib/store";
import { Pips } from "./Pips";
import { IconX } from "./Icons";

const WUBRG = ["W", "U", "B", "R", "G", "C"];

export function ManaWidget({ char, manaChoices }: {
  char: CharacterView;
  manaChoices: { color: string; index: number; label: string }[];
}) {
  const submit = useGame((s) => s.submitIndex);
  const manaSelect = useGame((s) => s.manaSelect);
  const pickMana = useGame((s) => s.pickMana);
  const pending = char.mana.pending_capacity_choice;
  const choiceByColor: Record<string, number> = {};
  for (const m of manaChoices) choiceByColor[m.color] = m.index;

  // A cast by THIS character is paying its full cost here.
  const selecting = manaSelect && manaSelect.actorId === char.id ? manaSelect : null;

  const colorSet = new Set<string>([
    ...char.mana.identity_colors,
    ...char.mana.by_color.map((m) => m.color),
  ]);
  const colors = WUBRG.filter((c) => colorSet.has(c));
  const byColor = Object.fromEntries(char.mana.by_color.map((m) => [m.color, m]));

  const symbol = "clamp(26px, 4.4vh, 40px)";

  // Paying a cast: the player clicks the ENTIRE cost (coloured pips included) —
  // nothing is set aside behind their back; the pool reads exactly as shown.
  // An {X} cast (xByCount set) accepts extra pips past the base cost to raise X.
  const count = (arr: string[], c: string) => arr.filter((x) => x === c).length;
  const poolRecord: Record<string, number> = Object.fromEntries(
    colors.map((c) => [c, byColor[c]?.pool ?? 0]));

  return (
    // The pane's footprint never changes: paying a cast only lights the frame,
    // makes the symbols clickable, and counts the pool down live. Everything
    // about the payment itself (card, cost, Cast/reset) lives in the floating
    // ManaPayPopup above — nothing is crammed in here.
    <div
      className={`flex h-full w-max shrink-0 flex-col justify-between border bg-black/25 px-3 py-2 ${
        selecting || pending ? "border-brass/70 shadow-[0_0_14px_rgba(233,204,130,0.15)]" : "border-line"
      }`}
    >
      <div className="caps-label text-center text-[9px] tracking-[0.3em]">
        {pending ? (
          <span className="text-brass-hi">Pick +1 Capacity</span>
        ) : (
          <span className="text-brass">Mana</span>
        )}
      </div>

      {/* one column per colour: symbol · pool numeral · capacity ticks */}
      <div className="flex items-stretch justify-center gap-3.5">
        {colors.map((color) => {
          const m = byColor[color] ?? { pool: 0, capacity: 0, channel_occupied: 0 };
          const capacityClickable = pending && choiceByColor[color] != null;
          const manaClickable = !!selecting && canPickMana(selecting, color, poolRecord);
          const clickable = capacityClickable || manaClickable;
          const onClick = () => {
            if (capacityClickable) submit(choiceByColor[color]);
            else if (manaClickable) pickMana(color);
          };
          const picked = selecting ? count(selecting.picked, color) : 0;
          // While paying, the pool counts DOWN live — you always see the mana
          // you'd have left if you cast right now.
          const shown = (m.pool ?? 0) - picked;
          const title = capacityClickable
            ? `Lock +1 capacity as ${color}`
            : selecting
              ? `Spend ${color} (${shown} left in pool)`
              : `${color} — pool ${m.pool}, capacity ${m.capacity}${m.channel_occupied ? `, ${m.channel_occupied} channelled` : ""}`;
          return (
            <div key={color} className="flex flex-col items-center justify-between gap-1">
              <div className="relative">
                <button
                  disabled={!clickable}
                  onClick={onClick}
                  title={title}
                  style={{ width: symbol, height: symbol, backgroundImage: `url(/assets/mana/${color}.svg)` }}
                  className={`rounded-full bg-cover bg-center transition ${
                    clickable
                      ? "cursor-pointer ring-2 ring-brass-hi ring-offset-2 ring-offset-ink-0 hover:scale-110"
                      : ""
                  } ${selecting && !manaClickable ? "opacity-40" : ""}`}
                />
                {picked > 0 && (
                  <span className="font-display absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-brass-hi text-[10px] text-ink-0">
                    {picked}
                  </span>
                )}
              </div>
              <span
                className={`font-display text-[clamp(16px,3vh,26px)] leading-none ${
                  picked > 0 ? "text-brass-hi" : shown === 0 ? "text-dimmed" : "text-parch"
                }`}
              >
                {shown}
              </span>
              <div className="flex gap-1.5">
                {Array.from({ length: m.capacity }).map((_, i) => {
                  const channelled = i >= m.capacity - m.channel_occupied;
                  return (
                    <span
                      key={i}
                      className={`h-2 w-2 rotate-45 ${
                        channelled ? "bg-aether shadow-[0_0_4px_rgba(179,157,219,0.6)]" : "border border-line2 bg-brass"
                      }`}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div className="text-center text-[8px] font-light tracking-wide text-dimmed">
        pool · ticks = capacity{colors.some((c) => (byColor[c]?.channel_occupied ?? 0) > 0) ? " · violet = channelled" : ""}
      </div>
    </div>
  );
}


/** The floating payment panel for a cast that needs its cost paid by hand ({X},
 *  or an ambiguous generic). Names the card and shows the FULL casting cost;
 *  the mana is spent by clicking the pane's mana symbols as usual, with the
 *  pool counting down live. Floats above the bottom bar so the pane itself
 *  keeps its exact everyday footprint. */
export function ManaPayPopup() {
  const manaSelect = useGame((s) => s.manaSelect);
  const confirmMana = useGame((s) => s.confirmMana);
  const resetMana = useGame((s) => s.resetMana);
  const cancelArm = useGame((s) => s.cancelArm);
  if (!manaSelect) return null;
  const isX = !!manaSelect.xByCount;
  const baseCost = manaSelect.colored.length + manaSelect.generic;
  const xSoFar = isX ? Math.max(0, manaSelect.picked.length - baseCost) : 0;
  const castIndex = castIndexFor(manaSelect);
  return (
    <div className="absolute -top-10 left-3 z-20 flex items-center gap-3 border border-brass bg-gradient-to-b from-brass-hi to-brass px-4 py-1.5 text-sm text-ink-0 shadow-[0_8px_20px_rgba(0,0,0,0.5)]">
      <span className="flex items-center gap-1.5 font-normal">
        <span className="caps-label text-[10px] tracking-[0.14em]">Pay</span>
        {manaSelect.cardName}
        <Pips cost={manaSelect.cost} size={15} />
        {isX ? <span>· X = {xSoFar}</span> : null}
        <span className="text-xs font-light">— click mana below</span>
      </span>
      <button
        onClick={confirmMana}
        disabled={castIndex == null}
        className="caps-label bg-ink-0 px-3 py-0.5 text-[10px] tracking-[0.14em] text-brass-hi hover:bg-ink-2 disabled:opacity-40"
      >
        {isX ? `Cast (X=${xSoFar})` : "Cast"}
      </button>
      <button
        onClick={resetMana}
        disabled={manaSelect.picked.length === 0}
        className="caps-label bg-black/15 px-2 py-0.5 text-[10px] tracking-[0.14em] hover:bg-black/30 disabled:opacity-40"
      >
        Reset
      </button>
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
