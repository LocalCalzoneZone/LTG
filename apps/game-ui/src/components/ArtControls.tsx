import { useState } from "react";
import { generateArt, removeArt } from "../lib/api";
import { IconCanvas, IconRedraw, IconX } from "./Icons";

const btn =
  "pointer-events-auto flex h-6 w-6 items-center justify-center border border-line bg-ink-0/85 text-mist transition hover:border-brass/60 hover:text-brass disabled:cursor-not-allowed disabled:opacity-40";

/** The generate / regenerate / remove cluster for one art slot (the scene
 * backdrop or one enemy's portrait). Owns the whole call lifecycle: busy state
 * (the canvas pulses brass while the model paints) and the error tooltip.
 *
 * In-game callers can omit `onChanged` — the server re-broadcasts the snapshot
 * to every seated client after a change; the editor passes it to update its
 * local (unsaved) copy. */
export function ArtControls({
  encounterId,
  kind,
  enemyId,
  text,
  hasImage,
  subject,
  onChanged,
  disabled,
  disabledTitle,
}: {
  encounterId: string;
  kind: "scene" | "enemy";
  enemyId?: string; // POOL enemy id (a clone's base_id); enemy art only
  text?: string; // live prompt-subject override (the editor's textarea)
  hasImage: boolean;
  subject: string; // tooltip subject, e.g. "battlefield backdrop" / the enemy name
  onChanged?: (url: string) => void; // "" on remove
  disabled?: boolean;
  disabledTitle?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const generate = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy || disabled) return;
    setBusy(true);
    setErr(null);
    try {
      const { url } = await generateArt(encounterId, kind, enemyId, text);
      onChanged?.(url);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy || disabled) return;
    setBusy(true);
    setErr(null);
    try {
      await removeArt(encounterId, kind, enemyId);
      onChanged?.("");
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  };

  const genTitle = disabled
    ? disabledTitle ?? "Unavailable"
    : busy
      ? `Painting ${subject}…`
      : hasImage
        ? `Repaint ${subject}`
        : `Paint ${subject}`;

  return (
    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={generate}
        disabled={disabled || busy}
        title={genTitle}
        className={`${btn} ${busy ? "animate-pulse border-brass/60 text-brass" : ""}`}
      >
        {hasImage && !busy ? <IconRedraw size={13} /> : <IconCanvas size={13} />}
      </button>
      {hasImage && !busy && (
        <button
          type="button"
          onClick={remove}
          disabled={disabled}
          title={`Remove ${subject} art`}
          className={btn}
        >
          <IconX size={13} />
        </button>
      )}
      {err && (
        <span
          title={err}
          className="caps-label cursor-help border border-blood/60 bg-blood/15 px-1 text-[9px] leading-4 tracking-[0.1em] text-blood"
        >
          !
        </span>
      )}
    </div>
  );
}
