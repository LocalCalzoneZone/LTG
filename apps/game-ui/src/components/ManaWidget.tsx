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
  const pending = char.mana.pending_capacity_choice;
  const choiceByColor: Record<string, number> = {};
  for (const m of manaChoices) choiceByColor[m.color] = m.index;

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

  return (
    <div className="flex h-full w-max shrink-0 flex-col justify-between rounded-lg bg-black/40 p-2.5 ring-1 ring-white/10">
      <div className="text-center text-[11px] font-bold uppercase tracking-wide text-gray-300">
        {pending ? <span className="text-yellow-300">Pick +1 Capacity</span> : "Mana"}
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

      {/* Mana symbols along the bottom. At the start of a new turn the +1 capacity
          choice is made here — click the symbol of the colour to lock. */}
      <div className="flex justify-center gap-2 pt-0.5">
        {colors.map((color) => {
          const clickable = pending && choiceByColor[color] != null;
          return (
            <button
              key={color}
              disabled={!clickable}
              onClick={() => clickable && submit(choiceByColor[color])}
              title={clickable ? `Lock +1 capacity as ${color}` : color}
              style={{ width: circle, height: circle, backgroundImage: `url(/assets/mana/${color}.svg)` }}
              className={`rounded-full bg-cover bg-center transition ${
                clickable ? "cursor-pointer ring-2 ring-yellow-400 ring-offset-2 ring-offset-black hover:scale-110" : ""
              }`}
            />
          );
        })}
      </div>
    </div>
  );
}
