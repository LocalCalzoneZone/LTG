import { useEffect, useRef, useState } from "react";
import { artQueueStatus, startArtQueue } from "../lib/api";
import type { ArtQueueStatus } from "../lib/types";
import { IconCanvas } from "./Icons";

const POLL_MS = 2500;

/** "Generate all art" (§D10-6.4): queues every missing image — the backdrop
 * plus every undrawn enemy — and runs it sequentially server-side (an
 * adventure's queue covers its acts in order). Shows `n / m` while running;
 * pressing again queues only what is still missing. */
export function ArtQueueButton({ target, subject, disabled, disabledTitle, onImage }: {
  target: { encounterId?: string; adventureId?: string };
  subject: string; // tooltip subject, e.g. "this encounter" / "all three acts"
  disabled?: boolean;
  disabledTitle?: string;
  onImage?: () => void; // fires as progress lands, so editors can refetch art
}) {
  const [st, setSt] = useState<ArtQueueStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const lastDone = useRef(0);

  const schedule = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(poll, POLL_MS);
  };

  const poll = async () => {
    try {
      const s = await artQueueStatus(target);
      setSt(s);
      if (s.done !== lastDone.current) {
        lastDone.current = s.done;
        onImage?.();
      }
      if (s.running) schedule();
    } catch {
      /* transient poll failure — the next press re-syncs */
    }
  };

  // Pick up an already-running queue (e.g. the panel was reopened mid-paint).
  useEffect(() => {
    poll();
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.encounterId, target.adventureId]);

  const run = async () => {
    if (disabled) return;
    setErr(null);
    try {
      const s = await startArtQueue(target);
      setSt(s);
      lastDone.current = s.done;
      if (s.running) schedule();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    }
  };

  const running = !!st?.running;
  const label = running
    ? `Painting ${st!.done + st!.failed} / ${st!.total}`
    : "Generate all art";
  const title = disabled
    ? disabledTitle ?? "Unavailable"
    : running
      ? `Painting ${subject}${st?.current ? ` — ${st.current}` : ""}. ` +
        "Press again to queue anything newly missing."
      : `Queue every missing image for ${subject} — the backdrop plus every ` +
        "undrawn enemy — and paint them one by one.";

  return (
    <span className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={run}
        disabled={disabled}
        title={title}
        className={`caps-label flex items-center gap-1.5 border px-2.5 py-1 text-[9px] tracking-[0.14em] transition disabled:cursor-not-allowed disabled:opacity-40 ${
          running
            ? "animate-pulse border-brass/60 text-brass"
            : "border-line text-mist hover:border-brass/60 hover:text-brass"
        }`}
      >
        <IconCanvas size={11} />
        {label}
      </button>
      {!running && st != null && st.total > 0 && st.failed > 0 && (
        <span
          title={st.errors.join("\n") || `${st.failed} image(s) failed — press again to retry`}
          className="caps-label cursor-help border border-blood/60 bg-blood/15 px-1 text-[9px] leading-4 tracking-[0.1em] text-blood"
        >
          {st.failed} failed
        </span>
      )}
      {err && (
        <span
          title={err}
          className="caps-label cursor-help border border-blood/60 bg-blood/15 px-1 text-[9px] leading-4 tracking-[0.1em] text-blood"
        >
          !
        </span>
      )}
    </span>
  );
}
