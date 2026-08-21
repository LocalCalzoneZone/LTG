import { useEffect, useRef, useState } from "react";
import type { CreatureView, GameSnapshot, Row, TokenView } from "../lib/types";
import { DEPART_MS, type DepartKind, type FxEvent } from "../lib/fx";
import { useFieldView, type FieldView } from "../lib/fieldView";
import { lungeVars, useFlip } from "../lib/motion";
import { useSceneTint } from "../lib/sceneTint";
import { armedTargetIdSet, useGame } from "../lib/store";
import { ArtControls } from "./ArtControls";
import { CharacterCard } from "./CharacterCard";
import { CorpseMarker, CreatureCard, TokenCard } from "./CreatureCard";
import { IconFitView, IconZoomIn, IconZoomOut } from "./Icons";
import { useScreenShake } from "./FxLayer";
import { ProjectileLayer } from "./ProjectileLayer";

const PLAYER_ROWS: Row[] = ["rear", "mid", "front"]; // left → right
const CREATURE_ROWS: Row[] = ["front", "mid", "rear"]; // mirror: front faces centre
const ROW_IDS = ["front", "mid", "rear"];

type Dying =
  | { kind: "creature"; view: CreatureView; depart: DepartKind; grand?: boolean }
  | { kind: "token"; view: TokenView; depart: DepartKind; grand?: boolean };

const DEPART_CLASS: Record<DepartKind, string> = {
  death: "anim-death", // hold, flash, drain to black-and-white, crumble
  exile: "anim-exile", // banished — white flare, implosion
  bounce: "anim-bounce", // returned / suspended — slips away upward
};

// A GRAND death — a boss, or the encounter's last creature — holds the stage
// longer and gets the ceremonial treatment (fx-combat.css).
const GRAND_DEATH_MS = 2400;

const departClass = (d: Dying) =>
  `${DEPART_CLASS[d.depart]}${d.grand ? " anim-death-grand" : ""}`;

/** The just-departed: combatants present in the previous snapshot, gone from
 * this one for a reason the log named (death / exile / bounce, via the store's
 * fx departures — with a corpse on the field as the death fallback). Each is
 * held for its treatment's duration, then dropped. */
function useDeparting(snapshot: GameSnapshot | null): Dying[] {
  const departures = useGame((s) => s.departures);
  const prev = useRef<Map<string, Omit<Dying, "depart">>>(new Map());
  const [dying, setDying] = useState<Map<string, Dying>>(new Map());

  useEffect(() => {
    if (!snapshot) {
      prev.current = new Map();
      setDying(new Map());
      return;
    }
    const now = new Map<string, Omit<Dying, "depart">>();
    for (const c of snapshot.creatures) now.set(c.id, { kind: "creature", view: c });
    for (const t of snapshot.tokens) now.set(t.id, { kind: "token", view: t });
    const corpses = new Set((snapshot.corpses ?? []).map((c) => c.id));
    const newly: [string, Dying][] = [];
    for (const [id, entry] of prev.current) {
      if (now.has(id)) continue;
      const depart = departures[id] ?? (corpses.has(id) ? "death" : null);
      if (!depart) continue; // left for a reason with no send-off (board swap …)
      const view = depart === "death"
        ? { ...entry.view, hp: { ...entry.view.hp, current: 0 } }
        : entry.view;
      const grand = depart === "death" && entry.kind === "creature"
        && ((entry.view as CreatureView).is_boss
            || snapshot.creatures.length === 0);
      newly.push([id, { ...entry, view, depart, grand } as Dying]);
    }
    prev.current = now;
    if (!newly.length) return;
    setDying((m) => {
      const next = new Map(m);
      for (const [id, e] of newly) if (!next.has(id)) next.set(id, e);
      return next;
    });
    // Deliberately NOT cleaned up on re-run: the next snapshot must never
    // cancel a pending prune, or a finished ghost would linger forever.
    for (const [id, e] of newly) {
      window.setTimeout(() => {
        setDying((m) => {
          if (!m.has(id)) return m;
          const next = new Map(m);
          next.delete(id);
          return next;
        });
      }, e.grand ? GRAND_DEATH_MS : DEPART_MS[e.depart]);
    }
  }, [snapshot, departures]);

  return [...dying.values()];
}

/** Wraps a card for the motion layer: `data-fid` is the FLIP/aim anchor; a
 * live "strike" fx lunges the whole card at its target; a landing hit gives
 * the target a recoil punch. The wrapper (not the card) carries motion, so
 * card transforms never fight the cards' own frame states. */
function MotionWrap({
  id,
  strikes,
  impacts,
  acts,
  side,
  children,
}: {
  id: string;
  strikes: Map<string, FxEvent>;
  impacts: Set<string>;
  acts: Set<string>;
  side: "party" | "enemy";
  children: React.ReactNode;
}) {
  const strike = strikes.get(id);
  return (
    <div
      data-fid={id}
      className={`${strike ? "fx-lunge" : ""} ${impacts.has(id) ? "fx-recoil" : ""} ${
        acts.has(id) ? (side === "enemy" ? "fx-stepforward-w" : "fx-stepforward-e") : ""
      }`}
      style={strike ? lungeVars(id, strike.targetId, side === "party" ? 22 : -22) : undefined}
    >
      {children}
    </div>
  );
}

/** Full-field phase heralds — the round's heartbeat, made visible. Only the
 * two phases the player FEELS get one: your phase (brass) and the enemy
 * phase (crimson wash sweeping the whole board). Presentation only — input
 * is never blocked; the herald plays over the top of whatever you're doing. */
function PhaseHerald() {
  const phase = useGame((s) => s.snapshot?.phase ?? null);
  const prev = useRef<string | null>(null);
  const [show, setShow] = useState<"players" | "enemies" | null>(null);
  useEffect(() => {
    const before = prev.current;
    prev.current = phase;
    if (!phase || before === phase || before == null) return;
    const kind = phase === "enemy" ? "enemies" : phase === "player" ? "players" : null;
    if (!kind) return;
    setShow(kind);
    const t = window.setTimeout(() => setShow(null), 1250);
    return () => window.clearTimeout(t);
  }, [phase]);
  if (!show) return null;
  const enemies = show === "enemies";
  return (
    <div className="pointer-events-none absolute inset-0 z-40" aria-hidden>
      <div className={enemies ? "phase-herald-wash-blood" : "phase-herald-wash-brass"} />
      <div className="absolute inset-x-0 top-[38%] flex justify-center">
        <span
          className={`caps-label phase-herald-word font-display text-[clamp(16px,3vh,26px)] tracking-[0.5em] ${
            enemies ? "text-blood" : "text-brass-hi"
          }`}
        >
          {enemies ? "Enemy Phase" : "Your Phase"}
        </span>
      </div>
    </div>
  );
}

const VIEW_BTN =
  "flex h-6 w-6 items-center justify-center border border-line bg-ink-0/85 text-mist " +
  "transition hover:border-brass/60 hover:text-brass disabled:cursor-not-allowed " +
  "disabled:opacity-30 disabled:hover:border-line disabled:hover:text-mist";

/** The battlefield camera's controls: pull back, push in, reset framing. Sits
 * over the field (never inside the stage, so it neither zooms nor pans away).
 * The zoom reading only appears off the default, so the default board carries
 * no chrome it doesn't need. */
function ViewControls({ view }: { view: FieldView }) {
  return (
    <div
      className="absolute bottom-1.5 right-2 z-20 flex items-center gap-1 opacity-45 transition hover:opacity-100"
      onPointerDown={(e) => e.stopPropagation()}
      onWheel={(e) => e.stopPropagation()}
    >
      {!view.isDefault && (
        <span className="caps-label mr-0.5 text-[9px] tracking-[0.2em] text-dimmed">
          {Math.round(view.scale * 100)}%
        </span>
      )}
      <button
        type="button"
        className={VIEW_BTN}
        onClick={view.zoomOut}
        disabled={!view.canZoomOut}
        title="Zoom out (scroll wheel)"
      >
        <IconZoomOut size={13} />
      </button>
      <button
        type="button"
        className={VIEW_BTN}
        onClick={view.zoomIn}
        disabled={!view.canZoomIn}
        title="Zoom in (scroll wheel)"
      >
        <IconZoomIn size={13} />
      </button>
      <button
        type="button"
        className={VIEW_BTN}
        onClick={view.reset}
        disabled={view.isDefault}
        title="Reset view — drag the field to pan"
      >
        <IconFitView size={13} />
      </button>
    </div>
  );
}

export function Battlefield() {
  const snapshot = useGame((s) => s.snapshot);
  const armed = useGame((s) => s.armed);
  const you = useGame((s) => s.you);
  const focusedId = useGame((s) => s.focusedId);
  const pickTargetId = useGame((s) => s.pickTargetId);
  const fx = useGame((s) => s.fx);
  const dying = useDeparting(snapshot);
  const shaking = useScreenShake();
  const viewRef = useRef<HTMLDivElement>(null);   // the pane (fixed): backdrop + chrome
  const fieldRef = useRef<HTMLDivElement>(null);  // the stage (zoomed/panned): the board
  const view = useFieldView(viewRef);
  // FLIP pass: any card whose layout position changed with this snapshot
  // glides from where it stood — movement is a slide, never a teleport.
  useFlip(fieldRef, snapshot);
  // The motes borrow the scene's own light (brass until sampled).
  const moteTint = useSceneTint(snapshot?.scene_image);
  if (!snapshot) return null;

  const holder = snapshot.priority.holder_character_id;
  const controlled = new Set(you);

  // Legal target ids for the current armed site: entity ids highlight cards; row
  // ids (front/mid/rear) drive the Move row-picker. "#<uid>" stack refs are the
  // Stack panel's concern (a counter's target).
  const targetIds = armedTargetIdSet(armed);
  const isMovePicker = armed?.kind === "move";
  // While a slain enemy's card plays its send-off, hold its corpse marker back
  // — the skull takes the card's place only once the card has crumbled out.
  const dyingIds = new Set(dying.map((d) => d.view.id));

  // Live motion cues, read off the fx store: attackers mid-lunge, targets
  // recoiling under a landed attack blow, enemies stepping forward as their
  // declared intent hits the stack.
  const strikes = new Map(
    fx.filter((e) => e.kind === "strike").map((e) => [e.entityId, e]),
  );
  const impacts = new Set(
    fx.filter((e) => e.kind === "hit").map((e) => e.entityId),
  );
  const acts = new Set(
    fx.filter((e) => e.kind === "enemyact").map((e) => e.entityId),
  );

  // Positional intents (§L-5): a declared row assault marks its ground on the
  // board itself, not only as a line in the intents window.
  const threatenedRows = new Set(
    (snapshot.intents ?? [])
      .filter((i) => i.status === "declared" && i.target_row)
      .map((i) => i.target_row as string),
  );

  // A live melee strike gives the whole field a 2px directional kick toward
  // the blow — the small cousin of the big screen shake. Enemy blows win.
  const creatureIds = new Set(snapshot.creatures.map((c) => c.id));
  const kick = [...strikes.keys()].some((id) => creatureIds.has(id))
    ? "fx-kick-w"
    : strikes.size
      ? "fx-kick-e"
      : "";

  return (
    <div
      ref={viewRef}
      onWheel={view.onWheel}
      onPointerDown={view.onPointerDown}
      onClickCapture={view.onClickCapture}
      className={`field-scene relative isolate h-full w-full overflow-hidden ${
        view.panning ? "cursor-grabbing" : ""
      } ${shaking ? "fx-shake" : kick}`}
    >
      {/* Generated scene backdrop, behind the cards; a scrim keeps them legible.
          (-z ordering needs the container's own stacking context — `isolate`.) */}
      {snapshot.scene_image && (
        <>
          <img
            src={snapshot.scene_image}
            alt=""
            className="anim-kenburns pointer-events-none absolute inset-0 -z-10 h-full w-full object-cover"
          />
          <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(120%_90%_at_50%_45%,rgba(6,8,12,0.28)_0%,rgba(6,8,12,0.62)_78%,rgba(6,8,12,0.82)_100%)]" />
          {/* Drifting motes — dust in the scene's own light, behind the cards. */}
          <div
            className="motes pointer-events-none absolute inset-0 -z-10"
            style={moteTint ? ({ "--mote-c": moteTint } as React.CSSProperties) : undefined}
            aria-hidden
          >
            {Array.from({ length: 7 }, (_, i) => (
              <span key={i} />
            ))}
          </div>
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

      {/* The stage — everything the camera moves. The backdrop and the chrome
          above stay put; zooming/panning re-frames the BOARD. */}
      <div
        ref={fieldRef}
        className="absolute inset-0 flex gap-2 px-3 pb-1 pt-4"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          transformOrigin: "50% 50%",
        }}
      >
        {/* Player area (~40%) */}
        <div className="flex min-w-0 basis-2/5 gap-1.5">
          {PLAYER_ROWS.map((row) => {
            const chars = snapshot.characters.filter((c) => c.row === row);
            const toks = snapshot.tokens.filter((t) => t.row === row);
            const pickable = isMovePicker && ROW_IDS.includes(row) && targetIds.has(row);
            const marked = threatenedRows.has(row);
            return (
              <div
                key={row}
                onClick={() => pickable && pickTargetId(row)}
                className={`relative flex flex-1 flex-col items-center justify-center gap-3 ${
                  pickable ? "brackets cursor-pointer bg-brass/5" : ""
                }`}
              >
                {marked && (
                  <>
                    <div className="row-threat pointer-events-none absolute inset-0" />
                    <span className="caps-label pointer-events-none absolute left-1/2 top-0.5 z-[1] -translate-x-1/2 text-[9px] tracking-[0.3em] text-blood/90">
                      marked
                    </span>
                  </>
                )}
                {chars.map((c) => (
                  <MotionWrap key={c.id} id={c.id} strikes={strikes} impacts={impacts} acts={acts} side="party">
                    <CharacterCard
                      char={c}
                      focused={focusedId === c.id}
                      isHolder={holder === c.id && controlled.has(c.id)}
                      waiting={holder === c.id && !controlled.has(c.id)}
                      isTarget={targetIds.has(c.id)}
                    />
                  </MotionWrap>
                ))}
                <div className="flex flex-wrap justify-center gap-1.5">
                  {toks.map((t) => (
                    <MotionWrap key={t.id} id={t.id} strikes={strikes} impacts={impacts} acts={acts} side="party">
                      <TokenCard token={t} isTarget={targetIds.has(t.id)} />
                    </MotionWrap>
                  ))}
                  {dying
                    .filter((d) => d.kind === "token" && d.view.row === row)
                    .map((d) => (
                      <div
                        key={`dying-${d.view.id}`}
                        className={`${departClass(d)} pointer-events-none`}
                      >
                        <TokenCard token={d.view as TokenView} />
                      </div>
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
            const corpses = (snapshot.corpses ?? []).filter(
              (c) => c.row === row && !dyingIds.has(c.id));
            return (
              <div
                key={row}
                className="relative flex flex-1 flex-col items-center justify-center gap-3"
              >
                {creatures.map((c) => (
                  <MotionWrap key={c.id} id={c.id} strikes={strikes} impacts={impacts} acts={acts} side="enemy">
                    <CreatureCard creature={c} isTarget={targetIds.has(c.id)} />
                  </MotionWrap>
                ))}
                {dying
                  .filter((d) => d.kind === "creature" && d.view.row === row)
                  .map((d) => (
                    <div
                      key={`dying-${d.view.id}`}
                      className={`${departClass(d)} pointer-events-none`}
                    >
                      <CreatureCard creature={d.view as CreatureView} />
                    </div>
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

        {/* Projectiles fly over everything on the board — inside the stage, so a
            bolt still lands on its target's chest at any zoom. */}
        <ProjectileLayer field={fieldRef} />
      </div>

      {/* Phase heralds sweep over the whole field on the big turns of the round. */}
      <PhaseHerald />
      <ViewControls view={view} />
    </div>
  );
}
