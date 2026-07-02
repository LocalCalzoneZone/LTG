import type { Row } from "../lib/types";
import { armedTargetIdSet, useGame } from "../lib/store";
import { CharacterCard } from "./CharacterCard";
import { CreatureCard, TokenCard } from "./CreatureCard";

const PLAYER_ROWS: Row[] = ["rear", "mid", "front"]; // left → right
const CREATURE_ROWS: Row[] = ["front", "mid", "rear"]; // mirror: front faces centre
const ROW_IDS = ["front", "mid", "rear"];

export function Battlefield() {
  const snapshot = useGame((s) => s.snapshot);
  const armed = useGame((s) => s.armed);
  const you = useGame((s) => s.you);
  const focusedId = useGame((s) => s.focusedId);
  const pickTargetId = useGame((s) => s.pickTargetId);
  if (!snapshot) return null;

  const holder = snapshot.priority.holder_character_id;
  const controlled = new Set(you);

  // Legal target ids for the current armed site: entity ids highlight cards; row
  // ids (front/mid/rear) drive the Move row-picker. "#<uid>" stack refs are the
  // Stack panel's concern (a counter's target).
  const targetIds = armedTargetIdSet(armed);
  const isMovePicker = armed?.kind === "move";

  return (
    <div className="flex h-full w-full gap-2 p-2">
      {/* Player area (~40%) */}
      <div className="flex min-w-0 basis-2/5 gap-1">
        {PLAYER_ROWS.map((row) => {
          const chars = snapshot.characters.filter((c) => c.row === row);
          const toks = snapshot.tokens.filter((t) => t.row === row);
          const pickable = isMovePicker && ROW_IDS.includes(row) && targetIds.has(row);
          return (
            <div
              key={row}
              onClick={() => pickable && pickTargetId(row)}
              className={`flex flex-1 flex-col items-center justify-center gap-2 rounded-lg ${
                pickable ? "cursor-pointer bg-yellow-400/10 ring-2 ring-yellow-400" : ""
              }`}
            >
              {chars.map((c) => (
                <CharacterCard
                  key={c.id}
                  char={c}
                  focused={focusedId === c.id}
                  isHolder={holder === c.id && controlled.has(c.id)}
                  waiting={holder === c.id && !controlled.has(c.id)}
                  isTarget={targetIds.has(c.id)}
                />
              ))}
              <div className="flex flex-wrap justify-center gap-1">
                {toks.map((t) => (
                  <TokenCard key={t.id} token={t} isTarget={targetIds.has(t.id)} />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Centre divider */}
      <div className="w-px shrink-0 self-stretch bg-white/10" />

      {/* Creature area (~60%) */}
      <div className="flex min-w-0 basis-3/5 gap-1">
        {CREATURE_ROWS.map((row) => {
          const creatures = snapshot.creatures.filter((c) => c.row === row);
          return (
            <div key={row} className="flex flex-1 flex-col items-center justify-center gap-2">
              {creatures.map((c) => (
                <CreatureCard key={c.id} creature={c} isTarget={targetIds.has(c.id)} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
