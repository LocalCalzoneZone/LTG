import { useEffect, useRef, useState } from "react";
import { createGame } from "../lib/api";
import { actionModeColor } from "../lib/format";
import { SPLASH_HOLD_MS, useAfterHold } from "../lib/hooks";
import { useGame } from "../lib/store";
import type { LegalAction, StackRow } from "../lib/types";
import { HandCard } from "./Hand";

function Backdrop({ children, onClose, wide = false }: {
  children: React.ReactNode; onClose: () => void; wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-[2px]"
      onClick={onClose}
      onContextMenu={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div
        className={`panel-ticks max-h-[80vh] overflow-y-auto border border-line2 bg-ink-2 p-4 shadow-2xl ${
          wide ? "w-fit min-w-[320px] max-w-[min(94vw,1080px)]" : "w-[min(90vw,560px)]"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function ModalTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="caps-label mb-3 flex items-center gap-3 text-[12px] tracking-[0.25em] text-brass">
      {children}
      <span className="h-px flex-1 bg-line" />
    </h2>
  );
}

const CHOICE_BTN =
  "border border-line bg-white/[0.02] px-3 py-2 text-left text-sm font-light text-parch transition " +
  "hover:border-brass/70 hover:bg-brass/10";

/** §4.8 "Choose one" modal for a modal card. */
export function ChooseModeModal() {
  const choice = useGame((s) => s.chooseModeFor);
  const pickMode = useGame((s) => s.pickMode);
  const cancel = useGame((s) => s.cancelArm);
  if (!choice?.modes) return null;
  return (
    <Backdrop onClose={cancel}>
      <ModalTitle>Choose a mode</ModalTitle>
      <div className="flex flex-col gap-2">
        {choice.modes.map((m) => (
          <button key={m.key} onClick={() => pickMode(m)} className={CHOICE_BTN}>
            {m.label}
          </button>
        ))}
      </div>
      <button onClick={cancel} className="caps-label mt-3 text-[9px] tracking-[0.2em] text-dimmed hover:text-parch">
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
          <div className="text-sm font-light italic text-dimmed">no active channels</div>
        ) : (
          char.channels_summary.map((ch) => {
            const dropIdx = dropByCard[ch.card_id];
            return (
              <div key={ch.card_id} className="flex items-start gap-2 border border-aether/30 bg-aether/5 p-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-normal text-parch">{ch.card_name}</div>
                  {ch.target_name && <div className="text-xs text-mist">on {ch.target_name}</div>}
                  <div className="text-xs font-light text-mist">{ch.text}</div>
                  {ch.break_text && (
                    <div className="mt-0.5 text-xs font-light text-brass">
                      When this channel ends: {ch.break_text}.
                    </div>
                  )}
                </div>
                {dropIdx != null && (
                  <button
                    onClick={() => {
                      submit(dropIdx);
                      onClose();
                    }}
                    title={`Drop ${ch.card_name}`}
                    className="caps-label shrink-0 self-center border border-blood/60 bg-blood/15 px-2.5 py-1 text-[9px] tracking-[0.14em] text-blood transition hover:bg-blood hover:text-parch"
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
            className="caps-label border border-blood/60 bg-blood/15 px-3 py-2 text-[10px] tracking-[0.16em] text-blood transition hover:bg-blood hover:text-parch"
          >
            Drop all channels
          </button>
        )}
      </div>
    );
  }

  return (
    <Backdrop onClose={onClose}>
      <ModalTitle>{title}</ModalTitle>
      {body}
      <button onClick={onClose} className="caps-label mt-3 text-[9px] tracking-[0.2em] text-dimmed hover:text-parch">
        Close (Esc)
      </button>
    </Backdrop>
  );
}

function CardList({ cards }: { cards: { id: string; name: string; type: string; cost: string }[] }) {
  if (!cards.length) return <div className="text-sm font-light italic text-dimmed">empty</div>;
  return (
    <div className="grid grid-cols-2 gap-1">
      {cards.map((c, i) => (
        <div key={`${c.id}-${i}`} className="border border-line bg-white/[0.02] px-2 py-1 text-sm">
          <span className="font-normal text-parch">{c.name}</span>
          <span className="ml-1 text-xs font-light text-dimmed">{c.type}</span>
        </div>
      ))}
    </div>
  );
}

/** §4.6 mandatory mid-resolution pick (move_card / scry / trigger target /
 * trigger mode) — a blocking prompt. Card picks (scry / tutor / discard) show
 * the FULL cards in a horizontal, scrollable row — the whole card is the
 * information the choice needs — with the placement buttons under each one.
 * Target/mode picks (no cards involved) keep the simple button list. */
export function CardPickPrompt() {
  const snapshot = useGame((s) => s.snapshot);
  const submit = useGame((s) => s.submitIndex);
  const you = useGame((s) => s.you);
  if (!snapshot) return null;
  if (snapshot.priority.kind !== "card_choice") return null;
  const holder = snapshot.priority.holder_character_id;
  if (!holder || !you.includes(holder)) return null; // only the controlling client acts
  const picks = snapshot.legal_actions.filter(
    (a) =>
      a.kind === "choose_card" || a.kind === "choose_scry" || a.kind === "choose_target" ||
      a.kind === "choose_mode",
  );
  if (!picks.length) return null;

  const pending = snapshot.pending_choice;
  const cardPicks = picks.filter((a) => a.kind === "choose_card" || a.kind === "choose_scry");
  if (pending && pending.candidates.length && cardPicks.length === picks.length) {
    // Group the actions by the candidate they act on.
    const byChoice: Record<number, LegalAction[]> = {};
    for (const a of cardPicks) if (a.choice != null) (byChoice[a.choice] ||= []).push(a);
    const isScry = pending.kind === "scry";
    return (
      <Backdrop wide onClose={() => {}}>
        <ModalTitle>
          {isScry ? "Scry — place each card on top or bottom" : "Choose a card"}
        </ModalTitle>
        <div className="scroll-thin flex overflow-x-auto pb-2">
          <div className="mx-auto flex items-stretch gap-3">
          {pending.candidates.map((card, i) => {
            const acts = byChoice[i] ?? [];
            const single = acts.length === 1 ? acts[0] : null;
            return (
              <div key={`${card.id}-${i}`} className="flex w-44 shrink-0 flex-col gap-1.5">
                <div className={`h-64 ${single ? "" : "pointer-events-none"}`}>
                  <HandCard
                    card={card}
                    playable
                    active={false}
                    onClick={() => single && submit(single.index)}
                  />
                </div>
                {single ? (
                  <button
                    onClick={() => submit(single.index)}
                    className={`${CHOICE_BTN} py-1.5 text-center text-xs`}
                  >
                    {single.label}
                  </button>
                ) : (
                  acts.map((a) => (
                    <button
                      key={a.index}
                      onClick={() => submit(a.index)}
                      className={`${CHOICE_BTN} py-1.5 text-center text-xs`}
                    >
                      {a.target_id === "top"
                        ? `Top${(a.label.match(/\(draw #\d+\)/) ?? [""])[0] && ` ${(a.label.match(/\(draw #\d+\)/) ?? [""])[0]}`}`
                        : a.target_id === "bottom"
                          ? "Bottom"
                          : a.label}
                    </button>
                  ))
                )}
              </div>
            );
          })}
          </div>
        </div>
      </Backdrop>
    );
  }

  return (
    <Backdrop onClose={() => {}}>
      <ModalTitle>Make a choice</ModalTitle>
      <div className="flex flex-col gap-2">
        {picks.map((p) => (
          <button key={p.index} onClick={() => submit(p.index)} className={CHOICE_BTN}>
            {p.label}
          </button>
        ))}
      </div>
    </Backdrop>
  );
}

/** §4.16 game-over overlay (board stays visible behind). For an adventure
 * (Update 10) the finale's win reads "Adventure Complete", and a defeat offers
 * Restart from Act I — same party, fresh state, level 1. */
export function GameOverOverlay({
  onNewGame,
  onOptions,
  onStarted,
}: {
  onNewGame: () => void;
  onOptions: () => void;
  onStarted: (sessionId: string) => void;
}) {
  const result = useGame((s) => s.gameOver ?? s.snapshot?.result ?? null);
  const adventure = useGame((s) => s.snapshot?.adventure ?? null);
  // The objective outcome sentence (§D12-1.5): "You held the line" / "The doom
  // clock ran out" — null when the ending needs no objective framing.
  const objectiveLine = useGame((s) => s.snapshot?.game_over?.objective_line ?? null);
  const [restarting, setRestarting] = useState(false);
  const [restartErr, setRestartErr] = useState<string | null>(null);
  // Hold the splash back so the killing blow (and the death animation it
  // triggers) reads on the board before the screen changes.
  const show = useAfterHold(result != null, SPLASH_HOLD_MS);
  if (!result || !show) return null;
  const win = result === "victory";
  const advWin = win && !!adventure;

  const restart = async () => {
    if (!adventure || restarting) return;
    setRestarting(true);
    setRestartErr(null);
    try {
      onStarted(await createGame(adventure.character_ids, { adventureId: adventure.id }));
    } catch (e) {
      setRestartErr(e instanceof Error ? e.message : String(e));
      setRestarting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 backdrop-blur-[2px]">
      <div className="panel-ticks border border-line2 bg-ink-2/95 px-12 py-9 text-center shadow-2xl">
        <div className="flex items-center justify-center gap-5">
          <span className={`h-px w-16 bg-gradient-to-r from-transparent ${win ? "to-vigor/70" : "to-blood/70"}`} />
          {/* pl offsets the trailing letter-spacing after the last glyph, so the
              word sits optically centred between the hairlines */}
          <div
            className={`caps-label pl-[0.3em] text-4xl tracking-[0.3em] ${win ? "text-vigor" : "text-blood"}`}
            style={{ textShadow: win ? "0 0 30px rgba(132,199,147,.4)" : "0 0 30px rgba(194,90,80,.4)" }}
          >
            {advWin ? "Adventure Complete" : win ? "Victory" : "Defeat"}
          </div>
          <span className={`h-px w-16 bg-gradient-to-l from-transparent ${win ? "to-vigor/70" : "to-blood/70"}`} />
        </div>
        {objectiveLine && (
          <div className="mt-3 text-sm font-light text-parch">{objectiveLine}</div>
        )}
        <div className="mt-3 text-sm font-light text-mist">
          {advWin
            ? `${adventure.name} — all three acts, cleared.`
            : adventure
              ? `${adventure.name} ends in Act ${adventure.act}. No checkpoints — the run is the run.`
              : "Tweak your party, encounters, or generation settings, then start again."}
        </div>
        {restartErr && <div className="mt-2 text-xs font-light text-blood">{restartErr}</div>}
        <div className="mt-6 flex items-center justify-center gap-3">
          {adventure && !win && (
            <button
              onClick={restart}
              disabled={restarting}
              className="caps-label border border-brass/60 bg-brass/10 px-5 py-2 text-[10px] tracking-[0.2em] text-brass transition hover:bg-brass hover:text-ink-0 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {restarting ? "Restarting…" : "Restart from Act I"}
            </button>
          )}
          <button
            onClick={onOptions}
            className="caps-label border border-line px-5 py-2 text-[10px] tracking-[0.2em] text-mist transition hover:border-line2 hover:text-parch"
          >
            Options
          </button>
          <button
            onClick={onNewGame}
            className="caps-label border border-brass/60 bg-brass/10 px-5 py-2 text-[10px] tracking-[0.2em] text-brass transition hover:bg-brass hover:text-ink-0"
          >
            New Game
          </button>
        </div>
      </div>
    </div>
  );
}

/** Transient error toast (§2.3 error). */
export function Toast() {
  const error = useGame((s) => s.error);
  if (!error) return null;
  return (
    <div className="fixed bottom-44 left-1/2 z-50 -translate-x-1/2 border border-blood bg-ink-2/95 px-4 py-2 text-sm font-light text-[#f2ddd3] shadow-[0_8px_24px_rgba(0,0,0,0.6),0_0_16px_rgba(194,90,80,0.25)]">
      {error}
    </div>
  );
}

type PlainBanner = { id: number; title: string; sub?: string };

// Phases we never announce: reaction windows are already carried by the (more
// specific) stack banner, and enemy intents are not broadcast to players.
const SILENT_PHASES = new Set(["reaction window", "enemy intents"]);

/** Two banners share the centre-top slot, stack first:
 *  — While anything is on the stack, a PERSISTENT banner mirrors the top item
 *    (what you'd be responding to). It sweeps in when the top changes (keyed by
 *    uid) and holds until the effect resolves or another replaces it.
 *  — Otherwise, turn / phase changes flash a transient title card
 *    (letter-spacing condenses while hairlines draw outward, then fades). */
export function PhaseBanner() {
  const turn = useGame((s) => s.snapshot?.turn ?? null);
  const phase = useGame((s) => s.snapshot?.phase_label ?? null);
  const top: StackRow | null = useGame((s) => s.snapshot?.stack?.[0] ?? null);
  const [plain, setPlain] = useState<PlainBanner | null>(null);
  const prev = useRef<{ turn: number | null; phase: string | null } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (turn == null || phase == null) return;
    const before = prev.current;
    prev.current = { turn, phase };
    if (!before) return; // don't announce the very first snapshot (game just loaded)
    const id = seq.current + 1;
    if (turn !== before.turn && !SILENT_PHASES.has(phase)) {
      seq.current = id;
      setPlain({ id, title: phase, sub: `Turn ${turn}` });
    } else if (phase !== before.phase && !SILENT_PHASES.has(phase)) {
      seq.current = id;
      setPlain({ id, title: phase });
    }
  }, [turn, phase]);

  // Auto-dismiss the transient banner (matches the 2.4s banner-sweep keyframe).
  useEffect(() => {
    if (!plain) return;
    const t = window.setTimeout(
      () => setPlain((b) => (b && b.id === plain.id ? null : b)),
      2400,
    );
    return () => window.clearTimeout(t);
  }, [plain]);

  // Persistent top-of-stack banner — same phrasing as a Stack row.
  if (top) {
    return (
      <div
        key={top.uid}
        className="anim-banner-in pointer-events-none fixed left-1/2 top-[72px] z-50 flex items-center gap-4"
      >
        <span className="h-px w-[110px] bg-gradient-to-r from-transparent to-brass" />
        <div className="whitespace-nowrap border border-line bg-ink-0/80 px-5 py-1.5 font-display text-base font-normal leading-tight text-parch shadow-[0_6px_18px_rgba(0,0,0,0.5)]" style={{ letterSpacing: "0.06em" }}>
          <span className={top.source_side === "enemy" ? "text-blood" : "text-tide"}>
            {top.source_name}
          </span>
          <span className="text-mist"> · {top.label}</span>
          {top.mode && <span className={actionModeColor(top.mode)}> ({top.mode})</span>}
          {top.target_name && <span className="text-mist"> → {top.target_name}</span>}
        </div>
        <span className="h-px w-[110px] bg-gradient-to-l from-transparent to-brass" />
      </div>
    );
  }

  if (!plain) return null;
  return (
    <div
      key={plain.id}
      className="anim-banner pointer-events-none fixed left-1/2 top-[72px] z-50 flex items-center gap-4"
    >
      <span className="anim-banner-line h-px bg-gradient-to-r from-transparent to-brass" />
      <div className="text-center">
        {/* no explicit tracking here — the sweep keyframe animates the
            container's letter-spacing and the title inherits it */}
        <div
          className="whitespace-nowrap font-display text-xl uppercase text-brass-hi"
          style={{ textShadow: "0 0 24px rgba(233,204,130,.45)" }}
        >
          {plain.title}
        </div>
        {plain.sub && (
          <div className="caps-label mt-1 text-[9px] tracking-[0.3em] text-mist">{plain.sub}</div>
        )}
      </div>
      <span className="anim-banner-line h-px bg-gradient-to-l from-transparent to-brass" />
    </div>
  );
}
