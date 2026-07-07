import type { CharacterView } from "../lib/types";
import { canPickMana, castIndexFor, useGame } from "../lib/store";
import { Pips } from "./Pips";

const WUBRG = ["W", "U", "B", "R", "G", "C"];

// Ring colours for the number circles — the mana palette, nudged brighter so each
// outline reads on the black fill / dark widget.
const RING: Record<string, string> = {
  W: "#efe7b0",
  U: "#4f92e0",
  B: "#9b86a8",
  R: "#e0584a",
  G: "#5cae70",
  C: "#c2c2c2",
};

type RowKey = "pool" | "channel_occupied" | "capacity";
const ROWS: { key: RowKey; label: string }[] = [
  { key: "pool", label: "Pool" },
  { key: "channel_occupied", label: "Channeled" },
  { key: "capacity", label: "Capacity" },
];

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

  // Hide the Channeled row entirely when nothing is channelled.
  const anyChanneled = colors.some((c) => (byColor[c]?.channel_occupied ?? 0) > 0);
  const rows = ROWS.filter((r) => r.key !== "channel_occupied" || anyChanneled);

  const circle = "clamp(28px, 4.8vh, 46px)";

  // Paying a cast: the player clicks the ENTIRE cost (coloured pips included) —
  // nothing is set aside behind their back; the pool reads exactly as shown.
  // An {X} cast (xByCount set) accepts extra pips past the base cost to raise X.
  const count = (arr: string[], c: string) => arr.filter((x) => x === c).length;
  const poolRecord: Record<string, number> = Object.fromEntries(
    colors.map((c) => [c, byColor[c]?.pool ?? 0]));

  return (
    // The pane's footprint never changes: paying a cast only lights the ring,
    // makes the symbols clickable, and counts the Pool down live. Everything
    // about the payment itself (card, cost, Cast/reset) lives in the floating
    // ManaPayPopup above — nothing is crammed in here.
    <div className={`flex h-full w-max shrink-0 flex-col justify-between rounded-lg bg-black/40 p-2.5 ring-1 ${
      selecting ? "ring-yellow-400" : "ring-white/10"
    }`}>
      <div className="text-center text-[11px] font-bold uppercase tracking-wide text-gray-300">
        {pending ? (
          <span className="text-yellow-300">Pick +1 Capacity</span>
        ) : (
          "Mana"
        )}
      </div>

      {rows.map((row) => (
        <div key={row.key} className="flex flex-col items-center gap-1">
          <div className="text-center text-[10px] font-semibold uppercase tracking-wide text-gray-400">
            {row.label}
          </div>
          <div className="flex justify-center gap-2">
            {colors.map((color) => {
              const m = byColor[color] ?? { pool: 0, capacity: 0, channel_occupied: 0 };
              const value = m[row.key];
              // While paying, the Pool row counts DOWN live — you always see the
              // mana you'd have left if you cast right now.
              const spent = row.key === "pool" && selecting
                ? count(selecting.picked, color) : 0;
              const shown = value - spent;
              return (
                <div
                  key={color}
                  title={`${color} ${row.label.toLowerCase()}${spent > 0 ? ` (${spent} being spent)` : ""}`}
                  style={{
                    width: circle,
                    height: circle,
                    background: "#000",
                    border: `2px solid ${RING[color] ?? "#c2c2c2"}`,
                    fontSize: "clamp(13px, 2.3vh, 22px)",
                  }}
                  className={`flex items-center justify-center rounded-full font-black leading-none ${
                    spent > 0 ? "text-yellow-300" : "text-white"
                  } ${shown === 0 ? "opacity-45" : ""}`}
                >
                  {shown}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* Mana symbols along the bottom. Two interactive modes light them up:
          the +1 capacity lock at the start of a turn, and picking which colours
          pay an ambiguous cast's generic mana. Otherwise they're a static legend. */}
      <div className="flex justify-center gap-2 pt-0.5">
        {colors.map((color) => {
          const capacityClickable = pending && choiceByColor[color] != null;
          const manaClickable = !!selecting && canPickMana(selecting, color, poolRecord);
          const clickable = capacityClickable || manaClickable;
          const onClick = () => {
            if (capacityClickable) submit(choiceByColor[color]);
            else if (manaClickable) pickMana(color);
          };
          const picked = selecting ? count(selecting.picked, color) : 0;
          const free = (byColor[color]?.pool ?? 0) - picked;
          const title = capacityClickable
            ? `Lock +1 capacity as ${color}`
            : selecting
              ? `Spend ${color} (${free} left in pool)`
              : color;
          return (
            <div key={color} className="relative">
              <button
                disabled={!clickable}
                onClick={onClick}
                title={title}
                style={{ width: circle, height: circle, backgroundImage: `url(/assets/mana/${color}.svg)` }}
                className={`rounded-full bg-cover bg-center transition ${
                  clickable ? "cursor-pointer ring-2 ring-yellow-400 ring-offset-2 ring-offset-black hover:scale-110" : ""
                } ${selecting && !manaClickable ? "opacity-45" : ""}`}
              />
              {picked > 0 && (
                <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-yellow-400 text-[10px] font-black text-black">
                  {picked}
                </span>
              )}
            </div>
          );
        })}
      </div>

    </div>
  );
}


/** The floating payment panel for a cast that needs its cost paid by hand ({X},
 *  or an ambiguous generic). Names the card and shows the FULL casting cost;
 *  the mana is spent by clicking the pane's mana symbols as usual, with the
 *  Pool counting down live. Floats above the bottom bar so the pane itself
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
    <div className="absolute -top-10 left-3 z-20 flex items-center gap-3 rounded-full bg-yellow-500 px-4 py-1.5 text-sm font-semibold text-black shadow-lg">
      <span className="flex items-center gap-1.5">
        Pay {manaSelect.cardName}
        <Pips cost={manaSelect.cost} size={16} />
        {isX ? <span>· X = {xSoFar}</span> : null}
        <span className="text-xs font-normal">— click mana below</span>
      </span>
      <button
        onClick={confirmMana}
        disabled={castIndex == null}
        className="rounded bg-black px-3 py-0.5 text-xs font-bold text-yellow-400 hover:bg-black/80 disabled:opacity-40"
      >
        {isX ? `Cast (X=${xSoFar})` : "Cast"}
      </button>
      <button
        onClick={resetMana}
        disabled={manaSelect.picked.length === 0}
        className="rounded bg-black/20 px-2 py-0.5 text-xs hover:bg-black/40 disabled:opacity-40"
      >
        reset
      </button>
      <button onClick={cancelArm} className="rounded bg-black/20 px-2 py-0.5 text-xs hover:bg-black/40">
        Esc ✕
      </button>
    </div>
  );
}
