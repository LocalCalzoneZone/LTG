import type { Row } from "../lib/types";
import { armedTargetIdSet, useGame } from "../lib/store";
import { ArtControls } from "./ArtControls";
import { CharacterCard } from "./CharacterCard";
import { CorpseMarker, CreatureCard, TokenCard } from "./CreatureCard";

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
    <div className="field-scene relative isolate flex h-full w-full gap-2 px-3 pb-1 pt-4">
      {/* Generated scene backdrop, behind the cards; a scrim keeps them legible.
          (-z ordering needs the container's own stacking context — `isolate`.) */}
      {snapshot.scene_image && (
        <>
          <img
            src={snapshot.scene_image}
            alt=""
            className="pointer-events-none absolute inset-0 -z-10 h-full w-full object-cover"
          />
          <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(120%_90%_at_50%_45%,rgba(6,8,12,0.28)_0%,rgba(6,8,12,0.62)_78%,rgba(6,8,12,0.82)_100%)]" />
        </>
      )}

      {/* Scene art controls — paint / repaint / remove the backdrop */}
      {snapshot.encounter_id && (
        <div className="absolute right-2 top-1.5 z-10 opacity-60 transition hover:opacity-100">
          <ArtControls
            encounterId={snapshot.encounter_id}
            kind="scene"
            hasImage={!!snapshot.scene_image}
            subject="the battlefield backdrop"
          />
        </div>
      )}

      {/* Player area (~40%) */}
      <div className="flex min-w-0 basis-2/5 gap-1.5">
        {PLAYER_ROWS.map((row) => {
          const chars = snapshot.characters.filter((c) => c.row === row);
          const toks = snapshot.tokens.filter((t) => t.row === row);
          const pickable = isMovePicker && ROW_IDS.includes(row) && targetIds.has(row);
          return (
            <div
              key={row}
              onClick={() => pickable && pickTargetId(row)}
              className={`relative flex flex-1 flex-col items-center justify-center gap-3 ${
                pickable ? "brackets cursor-pointer bg-brass/5" : ""
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
              <div className="flex flex-wrap justify-center gap-1.5">
                {toks.map((t) => (
                  <TokenCard key={t.id} token={t} isTarget={targetIds.has(t.id)} />
                ))}
              </div>
              <span className="caps-label pointer-events-none absolute bottom-0.5 left-1/2 -translate-x-1/2 text-[9px] tracking-[0.3em] text-dimmed/70">
                {row}
              </span>
            </div>
          );
        })}
      </div>

      {/* Centre divider — hairline with a brass diamond */}
      <div className="relative flex w-3 flex-none items-center justify-center self-stretch">
        <div className="absolute inset-y-[8%] left-1/2 w-px bg-gradient-to-b from-transparent via-line2 to-transparent" />
        <div className="z-[1] h-[7px] w-[7px] rotate-45 border border-brass bg-ink-1" />
      </div>

      {/* Creature area (~60%) */}
      <div className="flex min-w-0 basis-3/5 gap-1.5">
        {CREATURE_ROWS.map((row) => {
          const creatures = snapshot.creatures.filter((c) => c.row === row);
          const corpses = (snapshot.corpses ?? []).filter((c) => c.row === row);
          return (
            <div
              key={row}
              className="relative flex flex-1 flex-col items-center justify-center gap-3"
            >
              {creatures.map((c) => (
                <CreatureCard key={c.id} creature={c} isTarget={targetIds.has(c.id)} />
              ))}
              {corpses.length > 0 && (
                <div className="flex flex-wrap justify-center gap-1.5">
                  {corpses.map((c) => (
                    <CorpseMarker key={c.id} corpse={c} isTarget={targetIds.has(c.id)} />
                  ))}
                </div>
              )}
              <span className="caps-label pointer-events-none absolute bottom-0.5 left-1/2 -translate-x-1/2 text-[9px] tracking-[0.3em] text-dimmed/70">
                {row}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
