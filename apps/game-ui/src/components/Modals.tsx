import { useEffect, useRef, useState } from "react";
import { useGame } from "../lib/store";
import type { StackRow } from "../lib/types";

function Backdrop({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60"
      onClick={onClose}
      onContextMenu={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="max-h-[80vh] w-[min(90vw,560px)] overflow-y-auto rounded-xl bg-slate-800 p-4 shadow-2xl ring-1 ring-white/10" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

/** §4.8 "Choose one" modal for a modal card. */
export function ChooseModeModal() {
  const choice = useGame((s) => s.chooseModeFor);
  const pickMode = useGame((s) => s.pickMode);
  const cancel = useGame((s) => s.cancelArm);
  if (!choice?.modes) return null;
  return (
    <Backdrop onClose={cancel}>
      <h2 className="mb-3 text-lg font-bold">Choose a mode</h2>
      <div className="flex flex-col gap-2">
        {choice.modes.map((m) => (
          <button
            key={m.key}
            onClick={() => pickMode(m)}
            className="rounded-lg bg-slate-700 px-3 py-2 text-left text-sm hover:bg-blue-600"
          >
            {m.label}
          </button>
        ))}
      </div>
      <button onClick={cancel} className="mt-3 text-xs text-gray-400 hover:text-white">
        Cancel (Esc)
      </button>
    </Backdrop>
  );
}

/** §4.14 read-only zone modals (library / graveyard / channel). */
export function ZoneModal() {
  const zone = useGame((s) => s.zoneModal);
  const snapshot = useGame((s) => s.snapshot);
  const close = useGame((s) => s.openZone);
  const choices = useGame((s) => s.snapshot ? s.snapshot.legal_actions : []);
  const submit = useGame((s) => s.submitIndex);
  if (!zone || !snapshot) return null;
  const char = snapshot.characters.find((c) => c.id === zone.charId);
  if (!char) return null;

  const onClose = () => close(null);

  let title = "";
  let body: React.ReactNode = null;

  if (zone.kind === "library") {
    title = `${char.name} — Library (${char.library_count})`;
    // Sorted by name so we don't leak the shuffled draw order (brief §4.14).
    const cards = [...(char.library ?? [])].sort((a, b) => a.name.localeCompare(b.name));
    body = <CardList cards={cards} />;
  } else if (zone.kind === "graveyard") {
    title = `${char.name} — Graveyard (${char.graveyard_count})`;
    body = <CardList cards={char.graveyard ?? []} />;
  } else {
    title = `${char.name} — Channels`;
    // Voluntary drop: one legal action per channel (matched by card_id), plus a
    // "drop all" (card_id === null) when more than one is held.
    const drops = choices.filter((a) => a.kind === "drop_channels" && a.actor_id === char.id);
    const dropByCard: Record<string, number> = {};
    let dropAllIdx: number | undefined;
    for (const a of drops) {
      if (a.card_id == null) dropAllIdx = a.index;
      else dropByCard[a.card_id] = a.index;
    }
    body = (
      <div className="flex flex-col gap-2">
        {char.channels_summary.length === 0 ? (
          <div className="text-sm italic text-gray-500">no active channels</div>
        ) : (
          char.channels_summary.map((ch) => {
            const dropIdx = dropByCard[ch.card_id];
            return (
              <div key={ch.card_id} className="flex items-start gap-2 rounded bg-white/5 p-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{ch.card_name}</div>
                  {ch.target_name && <div className="text-xs text-gray-400">on {ch.target_name}</div>}
                  <div className="text-xs text-gray-300">{ch.text}</div>
                </div>
                {dropIdx != null && (
                  <button
                    onClick={() => {
                      submit(dropIdx);
                      onClose();
                    }}
                    title={`Drop ${ch.card_name}`}
                    className="shrink-0 self-center rounded bg-red-700 px-2.5 py-1 text-xs font-semibold hover:bg-red-600"
                  >
                    Drop
                  </button>
                )}
              </div>
            );
          })
        )}
        {dropAllIdx != null && (
          <button
            onClick={() => {
              submit(dropAllIdx);
              onClose();
            }}
            className="rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold hover:bg-red-600"
          >
            Drop all channels
          </button>
        )}
      </div>
    );
  }

  return (
    <Backdrop onClose={onClose}>
      <h2 className="mb-3 text-lg font-bold">{title}</h2>
      {body}
      <button onClick={onClose} className="mt-3 text-xs text-gray-400 hover:text-white">
        Close (Esc)
      </button>
    </Backdrop>
  );
}

function CardList({ cards }: { cards: { id: string; name: string; type: string; cost: string }[] }) {
  if (!cards.length) return <div className="text-sm italic text-gray-500">empty</div>;
  return (
    <div className="grid grid-cols-2 gap-1">
      {cards.map((c, i) => (
        <div key={`${c.id}-${i}`} className="rounded bg-white/5 px-2 py-1 text-sm">
          <span className="font-medium">{c.name}</span>
          <span className="ml-1 text-xs text-gray-400">{c.type}</span>
        </div>
      ))}
    </div>
  );
}

/** §4.6 mandatory mid-resolution pick (move_card / scry) — a blocking prompt. */
export function CardPickPrompt() {
  const snapshot = useGame((s) => s.snapshot);
  const submit = useGame((s) => s.submitIndex);
  const you = useGame((s) => s.you);
  if (!snapshot) return null;
  if (snapshot.priority.kind !== "card_choice") return null;
  const holder = snapshot.priority.holder_character_id;
  if (!holder || !you.includes(holder)) return null; // only the controlling client acts
  const picks = snapshot.legal_actions.filter(
    (a) => a.kind === "choose_card" || a.kind === "choose_scry",
  );
  if (!picks.length) return null;
  return (
    <Backdrop onClose={() => {}}>
      <h2 className="mb-3 text-lg font-bold">Make a choice</h2>
      <div className="flex flex-col gap-2">
        {picks.map((p) => (
          <button
            key={p.index}
            onClick={() => submit(p.index)}
            className="rounded-lg bg-slate-700 px-3 py-2 text-left text-sm hover:bg-blue-600"
          >
            {p.label}
          </button>
        ))}
      </div>
    </Backdrop>
  );
}

/** §4.16 game-over overlay (board stays visible behind). */
export function GameOverOverlay({ onNewGame }: { onNewGame: () => void }) {
  const result = useGame((s) => s.gameOver ?? s.snapshot?.result ?? null);
  if (!result) return null;
  const win = result === "victory";
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50">
      <div className="rounded-2xl bg-slate-800 px-10 py-8 text-center shadow-2xl ring-1 ring-white/10">
        <div className={`text-4xl font-black ${win ? "text-emerald-400" : "text-red-500"}`}>
          {win ? "Victory" : "Defeat"}
        </div>
        <button
          onClick={onNewGame}
          className="mt-5 rounded-lg bg-blue-600 px-5 py-2 font-semibold hover:bg-blue-500"
        >
          New Game
        </button>
      </div>
    </div>
  );
}

/** Transient error toast (§2.3 error). */
export function Toast() {
  const error = useGame((s) => s.error);
  if (!error) return null;
  return (
    <div className="fixed bottom-44 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold shadow-lg">
      {error}
    </div>
  );
}

// A banner is either a new-turn/phase note (plain title + optional sub) or a new
// stack item, which renders in the same style as the Stack/Intents list rows.
type Banner =
  | { id: number; kind: "plain"; title: string; sub?: string }
  | { id: number; kind: "stack"; row: StackRow };

/** Transient banner announcing a new turn / phase, or a new effect entering the
 *  stack. Watches the snapshot and flashes a centred pill on each change, then
 *  fades out. A stack push takes precedence over the (redundant) "reaction
 *  window" phase change it triggers. */
export function PhaseBanner() {
  const turn = useGame((s) => s.snapshot?.turn ?? null);
  const phase = useGame((s) => s.snapshot?.phase_label ?? null);
  const stack = useGame((s) => s.snapshot?.stack ?? null);
  const [banner, setBanner] = useState<Banner | null>(null);
  const prev = useRef<{ turn: number | null; phase: string | null; maxUid: number } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (turn == null || phase == null) return;
    const before = prev.current;
    const top = stack && stack.length ? stack[0] : null;
    const topUid = top ? top.uid : null;
    const maxUid = Math.max(before?.maxUid ?? -1, topUid ?? -1);
    prev.current = { turn, phase, maxUid };
    if (!before) return; // don't announce the very first snapshot (game just loaded)
    const id = seq.current + 1;
    if (top && topUid != null && topUid > before.maxUid) {
      // A new effect just entered the stack — announce it (not the "reaction
      // window" phase label the same push produces).
      seq.current = id;
      setBanner({ id, kind: "stack", row: top });
    } else if (turn !== before.turn) {
      seq.current = id;
      setBanner({ id, kind: "plain", title: `Turn ${turn}`, sub: phase }); // e.g. "enemy intents"
    } else if (phase !== before.phase && phase !== "reaction window") {
      seq.current = id;
      setBanner({ id, kind: "plain", title: phase });
    }
  }, [turn, phase, stack]);

  // Auto-dismiss after the animation (matches the 2s .phase-banner keyframe).
  useEffect(() => {
    if (!banner) return;
    const t = window.setTimeout(
      () => setBanner((b) => (b && b.id === banner.id ? null : b)),
      2000,
    );
    return () => window.clearTimeout(t);
  }, [banner]);

  if (!banner) return null;
  return (
    <div
      key={banner.id}
      className="phase-banner pointer-events-none fixed left-1/2 top-20 z-50 flex flex-col items-center"
    >
      <div className="rounded-full bg-slate-900/90 px-6 py-2 text-center shadow-xl ring-1 ring-white/15">
        {banner.kind === "stack" ? (
          // Same phrasing as a Stack row: coloured source · label (mode) → target.
          <div className="text-base font-medium leading-tight text-white">
            <span className={`font-bold ${banner.row.source_side === "enemy" ? "text-rose-300" : "text-emerald-200"}`}>
              {banner.row.source_name}
            </span>
            <span className="text-gray-300"> · {banner.row.label}</span>
            {banner.row.mode && <span className="text-sky-300/90"> ({banner.row.mode})</span>}
            {banner.row.target_name && <span className="text-gray-300"> → {banner.row.target_name}</span>}
          </div>
        ) : (
          <>
            <div className="text-lg font-bold capitalize tracking-wide text-white">{banner.title}</div>
            {banner.sub && (
              <div className="text-xs font-semibold capitalize text-blue-300">{banner.sub}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
