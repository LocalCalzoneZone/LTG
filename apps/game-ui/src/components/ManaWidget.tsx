import type { CharacterView } from "../lib/types";
import { useGame } from "../lib/store";

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
  const resetMana = useGame((s) => s.resetMana);
  const pending = char.mana.pending_capacity_choice;
  const choiceByColor: Record<string, number> = {};
  for (const m of manaChoices) choiceByColor[m.color] = m.index;

  // An ambiguous cast by THIS character is picking its generic mana here.
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

  // How many of each colour are still free to spend on the generic portion:
  // pool minus the mandatory coloured pips minus what's already picked.
  const count = (arr: string[], c: string) => arr.filter((x) => x === c).length;
  const genericLeft = selecting ? selecting.generic - selecting.picked.length : 0;
  const freeForGeneric = (c: string) =>
    (byColor[c]?.pool ?? 0) - count(selecting?.colored ?? [], c) - count(selecting?.picked ?? [], c);

  return (
    <div className={`flex h-full w-max shrink-0 flex-col justify-between rounded-lg bg-black/40 p-2.5 ring-1 ${
      selecting ? "ring-yellow-400" : "ring-white/10"
    }`}>
      <div className="text-center text-[11px] font-bold uppercase tracking-wide text-gray-300">
        {selecting ? (
          <span className="text-yellow-300">
            Pay {selecting.cardName} — pick {genericLeft} mana
          </span>
        ) : pending ? (
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
              return (
                <div
                  key={color}
                  title={`${color} ${row.label.toLowerCase()}`}
                  style={{
                    width: circle,
                    height: circle,
                    background: "#000",
                    border: `2px solid ${RING[color] ?? "#c2c2c2"}`,
                    fontSize: "clamp(13px, 2.3vh, 22px)",
                  }}
                  className={`flex items-center justify-center rounded-full font-black leading-none text-white ${
                    value === 0 ? "opacity-45" : ""
                  }`}
                >
                  {value}
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
          const manaClickable = !!selecting && genericLeft > 0 && freeForGeneric(color) > 0;
          const clickable = capacityClickable || manaClickable;
          const onClick = () => {
            if (capacityClickable) submit(choiceByColor[color]);
            else if (manaClickable) pickMana(color);
          };
          const picked = selecting ? count(selecting.picked, color) : 0;
          const title = capacityClickable
            ? `Lock +1 capacity as ${color}`
            : selecting
              ? `Spend ${color} (${freeForGeneric(color)} free)`
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

      {selecting && (
        <button
          onClick={resetMana}
          disabled={selecting.picked.length === 0}
          className="mt-1 text-center text-[10px] font-semibold text-gray-400 hover:text-white disabled:opacity-40"
        >
          reset picks
        </button>
      )}
    </div>
  );
}
