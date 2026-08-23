import type { Ward } from "../lib/types";

// The ward aura: a standing shield reads as a ring inscribed around the card
// plus a soft edge glow, held for as long as the shield is up. It borrows the
// vocabulary of the one-shot `ward` FX (the ring drawn when protection is
// GRANTED) so the two read as the same idea — that one announces, this one
// persists.
//
// The colour names the LANE the shield answers, never the creature's side, so a
// warded hero and a warded enemy look alike and the player reads what is blocked
// rather than who is blocking:
//   combat -> tide      a steel shield turning blades (the existing ward hue)
//   spell  -> aether    the arcane lane, warded
//   all    -> vigor     nothing at all is getting through
// Colour never carries the meaning alone: the card's tooltip spells each shield
// out in words, which is also where the counts and reach live.

const LANE_COLOR: Record<Ward["lane"], string> = {
  combat: "130, 180, 201", // tide  #82b4c9
  spell: "179, 157, 219", // aether #b39ddb
  all: "132, 199, 147", // vigor  #84c793
};

// Strongest lane first: a card warded against everything shows the "all" ring
// outermost, and a narrower shield rides inside it.
const LANE_ORDER: Ward["lane"][] = ["all", "spell", "combat"];

// Two forms, because the shields read differently: a standing shield turns
// everything of a kind ("prevent attacks"), while a one-shot names a single
// incoming thing ("prevent the next attack").
const LANE_WORD: Record<Ward["lane"], string> = {
  combat: "attacks",
  spell: "spells",
  all: "all damage",
};
const LANE_ONE: Record<Ward["lane"], string> = {
  combat: "attack",
  spell: "spell",
  all: "damage of any kind",
};

/** The distinct lanes warded on this combatant, strongest first. */
export function wardLanes(wards: Ward[] | undefined): Ward["lane"][] {
  if (!wards || !wards.length) return [];
  const seen = new Set(wards.map((w) => w.lane));
  return LANE_ORDER.filter((lane) => seen.has(lane));
}

/** One line per shield for the card's tooltip — the words behind the colours.
 * Identical shields are counted rather than repeated ("protection ×2"), which is
 * how protection charges usually arrive. */
export function wardTitle(wards: Ward[] | undefined): string {
  if (!wards || !wards.length) return "";
  const counts = new Map<string, number>();
  for (const w of wards) {
    const reach = w.lane === "combat" && w.reach !== "all" ? `${w.reach} ` : "";
    const line =
      w.kind === "protection"
        ? `protection — negates the next ${reach}${LANE_ONE[w.lane]}`
        : w.uses == null
          ? `prevent ${reach}${LANE_WORD[w.lane]}`
          : w.uses === 1
            ? `prevent the next ${reach}${LANE_ONE[w.lane]}`
            : `prevent the next ${w.uses} ${reach}${LANE_WORD[w.lane]}`;
    counts.set(line, (counts.get(line) ?? 0) + 1);
  }
  const lines = [...counts].map(([line, n]) => `· ${line}${n > 1 ? ` ×${n}` : ""}`);
  return `\nWarded:\n${lines.join("\n")}`;
}

/** The aura itself: one ring per warded lane, drawn inside the card's frame.
 * Renders nothing when no shield is up, so every card can mount it
 * unconditionally. Purely decorative — the words live in the card's tooltip. */
export function WardAura({ wards }: { wards: Ward[] | undefined }) {
  const lanes = wardLanes(wards);
  if (!lanes.length) return null;
  return (
    <div className="fx-ward-aura" aria-hidden>
      {lanes.map((lane, i) => (
        <span
          key={lane}
          className="fx-ward-aura-ring"
          style={
            {
              "--ward-color": LANE_COLOR[lane],
              // Each further lane sits one step inside the last, so two shields
              // read as two rings rather than one thick smear.
              "--ward-inset": `${i * 5}%`,
              animationDelay: `${i * 320}ms`,
            } as React.CSSProperties
          }
        />
      ))}
      {/* The edge glow takes the strongest lane — one wash, however many rings. */}
      <span
        className="fx-ward-aura-glow"
        style={{ "--ward-color": LANE_COLOR[lanes[0]] } as React.CSSProperties}
      />
    </div>
  );
}
