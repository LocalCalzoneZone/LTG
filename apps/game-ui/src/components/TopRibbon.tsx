import { useState } from "react";
import { roman } from "../lib/format";
import { inviteUrl } from "../lib/settings";
import { useGame } from "../lib/store";
import { IconGear, IconLink, IconPlus } from "./Icons";

// The turn tracker, keyed off the engine's raw phase ids (serialize.py
// _PHASE_LABEL vocabulary). Intents are not broadcast to players, so the
// engine's intents phase reads as part of Upkeep here.
const STEPS = ["Upkeep", "Players", "Allies", "Enemies", "End"];
const STEP_OF: Record<string, string> = {
  upkeep: "Upkeep",
  capacity: "Upkeep",
  draw: "Upkeep",
  intents: "Upkeep",
  player: "Players",
  allies: "Allies",
  enemy: "Enemies",
  end: "End",
};

/** One 42px ribbon: wordmark · turn tracker · seats · invite / options / new game.
 *  Always rendered, so an empty battlefield can still reach New Game / Options. */
export function TopRibbon({ onNewGame, onOptions }: {
  onNewGame: () => void;
  onOptions: () => void;
}) {
  const snapshot = useGame((s) => s.snapshot);
  const sessionId = useGame((s) => s.sessionId);
  const seats = useGame((s) => s.seats);
  const you = useGame((s) => s.you);
  const clientId = useGame((s) => s.clientId);
  const claim = useGame((s) => s.claim);
  const release = useGame((s) => s.release);
  const connected = useGame((s) => s.connected);
  const [copied, setCopied] = useState(false);

  const youSet = new Set(you);
  const unclaimed = (snapshot?.characters ?? [])
    .map((c) => c.id)
    .filter((id) => seats[id] == null);

  const stepNow = snapshot ? (STEP_OF[snapshot.phase] ?? null) : null;
  const nowIdx = stepNow ? STEPS.indexOf(stepNow) : -1;

  const copyInvite = () => {
    // The invite host comes from Options → Settings (e.g. a Tailscale IP);
    // unset, it falls back to however this window was opened.
    if (sessionId) navigator.clipboard?.writeText(inviteUrl(sessionId));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="relative z-10 flex h-[42px] flex-none items-center gap-3 border-b border-line bg-gradient-to-b from-ink-3 to-ink-2 px-4">
      {/* wordmark */}
      <div
        className="h-3.5 w-3.5 rotate-45 border border-brass bg-gradient-to-br from-brass/25 to-transparent"
        aria-hidden
      />
      <span className="caps-label text-[13px] text-brass">LTG</span>
      {sessionId && (
        <>
          <div className="h-4 w-px bg-line" />
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              connected ? "bg-vigor shadow-[0_0_6px_#84c793]" : "bg-blood shadow-[0_0_6px_#c25a50]"
            }`}
            title={connected ? "connected" : "disconnected"}
          />
        </>
      )}
      {snapshot?.adventure && (
        <span
          className="caps-label text-[10px] tracking-[0.18em] text-mist"
          title={`${snapshot.adventure.name} — ${snapshot.adventure.act_name}`}
        >
          Act {roman(snapshot.adventure.act)} / {roman(snapshot.adventure.acts_total)}
        </span>
      )}

      {/* turn tracker — centred */}
      {snapshot && (
        <div className="pointer-events-none absolute left-1/2 flex -translate-x-1/2 items-baseline">
          <span className="caps-label mr-4 text-[13px] tracking-[0.2em] text-parch">
            Turn {snapshot.turn}
          </span>
          {STEPS.map((step, i) => (
            <span
              key={step}
              className={`caps-label relative px-2.5 text-[10px] tracking-[0.18em] ${
                i === nowIdx ? "text-brass-hi" : i < nowIdx ? "text-mist" : "text-dimmed"
              }`}
            >
              {step}
              {i === nowIdx && (
                <span className="absolute -bottom-1.5 left-1/2 h-1 w-1 -translate-x-1/2 rotate-45 bg-brass" />
              )}
            </span>
          ))}
        </div>
      )}

      {/* seats + session controls */}
      <div className="ml-auto flex items-center gap-0.5">
        {snapshot &&
          snapshot.characters.map((c) => {
            const owner = seats[c.id];
            const mine = youSet.has(c.id);
            const taken = owner != null && owner !== clientId;
            return (
              <button
                key={c.id}
                disabled={taken}
                onClick={() => (mine ? release([c.id]) : claim([c.id]))}
                title={mine ? "Release seat" : taken ? "Claimed by another player" : "Claim seat"}
                className={`caps-label px-2 py-1 text-[10px] tracking-[0.12em] transition ${
                  mine
                    ? "border-b border-brass text-brass-hi"
                    : taken
                      ? "cursor-not-allowed text-dimmed/60"
                      : "text-mist hover:text-parch"
                }`}
              >
                {c.name}
              </button>
            );
          })}
        {unclaimed.length > 0 && (
          <button
            onClick={() => claim(unclaimed)}
            className="caps-label px-2 py-1 text-[10px] tracking-[0.12em] text-tide hover:text-parch"
            title="Claim every open seat"
          >
            Claim all
          </button>
        )}
        {snapshot && <div className="mx-2 h-4 w-px bg-line" />}
        {sessionId && (
          <button
            onClick={copyInvite}
            title={copied ? "Copied!" : "Copy the shareable session URL"}
            className={`flex h-[26px] w-[26px] items-center justify-center border border-line transition hover:border-line2 ${
              copied ? "text-vigor" : "text-mist hover:text-brass-hi"
            }`}
          >
            <IconLink size={13} />
          </button>
        )}
        <button
          onClick={onOptions}
          title="Options — characters, encounters, LLM"
          className="ml-1 flex h-[26px] w-[26px] items-center justify-center border border-line text-mist transition hover:border-line2 hover:text-brass-hi"
        >
          <IconGear size={13} />
        </button>
        <button
          onClick={onNewGame}
          className="caps-label ml-2 flex items-center gap-1.5 border border-line2 px-3 py-[5px] text-[10px] tracking-[0.16em] text-brass transition hover:border-brass hover:text-brass-hi hover:shadow-[0_0_12px_rgba(233,204,130,0.15)]"
        >
          <IconPlus size={10} />
          New Game
        </button>
      </div>
    </div>
  );
}
