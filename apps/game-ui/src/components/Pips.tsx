import { parsePips } from "../lib/format";

export function Pips({ cost, size = 16 }: { cost: string; size?: number }) {
  const pips = parsePips(cost);
  if (!pips.length || (pips.length === 1 && pips[0].value === "0")) {
    return <span className="text-xs text-gray-400">0</span>;
  }
  return (
    <span className="inline-flex items-center gap-0.5">
      {pips.map((p, i) =>
        p.kind === "generic" ? (
          <span
            key={i}
            className="inline-flex items-center justify-center rounded-full bg-gray-500 font-bold text-gray-900"
            style={{ width: size, height: size, fontSize: size * 0.7 }}
          >
            {p.value}
          </span>
        ) : (
          <img
            key={i}
            src={`/assets/mana/${p.value}.svg`}
            alt={p.value}
            title={p.value}
            style={{ width: size, height: size }}
            className="inline-block rounded-full"
          />
        ),
      )}
    </span>
  );
}

export function ManaIcon({ color, size = 18, dimmed = false }: { color: string; size?: number; dimmed?: boolean }) {
  return (
    <img
      src={`/assets/mana/${color}.svg`}
      alt={color}
      title={color}
      style={{ width: size, height: size, opacity: dimmed ? 0.35 : 1 }}
      className="inline-block rounded-full"
    />
  );
}
