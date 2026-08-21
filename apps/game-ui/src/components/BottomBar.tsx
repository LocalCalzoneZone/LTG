import { useEffect, useRef, useState, type Ref } from "react";
import { useGame, focusedChoices } from "../lib/store";
import { ActionBar, UltimateColumn } from "./ActionBar";
import { ArmingHint } from "./ArmingHint";
import { Hand } from "./Hand";
import { ManaPayPopup, ManaWidget } from "./ManaWidget";
import { IconChannel, IconGrave, IconLibrary } from "./Icons";

export function BottomBar({ height }: { height?: number | null }) {
  const snapshot = useGame((s) => s.snapshot);
  const focusedId = useGame((s) => s.focusedId);
  const setSheetFor = useGame((s) => s.setSheetFor);
  const choices = useGame(focusedChoices);
  const openZone = useGame((s) => s.openZone);
  // The resolution hold: while the board's choreography is still landing —
  // or newer states are still queued behind it — the whole action surface
  // waits: you watch the resolution finish, THEN you are prompted.
  // `_holdTick` re-renders this open at expiry.
  const holdUntil = useGame((s) => s.holdUntil);
  const queued = useGame((s) => s._snapQueue.length);
  useGame((s) => s._holdTick);
  const holding = queued > 0 || Date.now() < holdUntil;

  const char = snapshot?.characters.find((c) => c.id === focusedId) ?? null;

  // Library counter tick: a quick pulse + numeral pop when it decreases.
  const prevLibraryRef = useRef<{ id: string; count: number } | null>(null);
  const [libraryPulse, setLibraryPulse] = useState(0);
  useEffect(() => {
    if (!char) return;
    const prev = prevLibraryRef.current;
    if (prev && prev.id === char.id && char.library_count < prev.count) {
      setLibraryPulse((k) => k + 1);
    }
    prevLibraryRef.current = { id: char.id, count: char.library_count };
  }, [char?.id, char?.library_count]);

  // (The library→hand card-sliver flight was tried and cut — at HUD scale it
  // read as a glitch, not a flourish. The draw moment belongs to the hand's
  // own glimmer; the library counter still ticks below.)
  const libraryBtnRef = useRef<HTMLButtonElement | null>(null);
  const handAreaRef = useRef<HTMLDivElement | null>(null);

  if (!snapshot) return null;
  if (!char) {
    return (
      <div className="flex h-40 items-center justify-center bg-gradient-to-b from-ink-2 to-ink-0 text-sm font-light text-mist">
        Select one of your characters to act.
      </div>
    );
  }

  const reaction = snapshot.priority.kind === "reaction" && snapshot.priority.holder_character_id === char.id;
  // The sheet exists only when a party sheet rides the snapshot (scenario /
  // adventure runs); a bare authored encounter has none to open.
  const hasSheet = !!snapshot.party_sheet?.some((r) => r.id === char.id);

  return (
    <div
      // A dragged height (from the splitter above) overrides the responsive default.
      style={{ height: height ? `${height}px` : "clamp(200px, 27vh, 320px)" }}
      className="relative flex shrink-0 items-stretch gap-2.5 bg-gradient-to-b from-ink-2 to-ink-0 p-2.5"
    >
      <ArmingHint />
      <ManaPayPopup />

      {/* who am I acting as + hidden zones — one block. The name opens the
          character sheet (stats, build, gear — read-only in combat). */}
      <div className="flex w-[150px] shrink-0 flex-col gap-1.5">
        <button
          onClick={() => hasSheet && setSheetFor(char.id)}
          disabled={!hasSheet}
          title={hasSheet ? `${char.name} — character sheet` : undefined}
          className={`flex items-center justify-center border border-line bg-black/25 px-2 py-2 transition ${
            hasSheet ? "hover:border-brass/60 hover:bg-brass/5" : "cursor-default"
          }`}
        >
          <div className={`caps-label min-w-0 truncate text-[14px] tracking-[0.14em] text-parch ${
            hasSheet ? "underline decoration-line2 decoration-dotted underline-offset-4" : ""
          }`}>
            {char.name}
          </div>
        </button>

        {char.controlled ? (
          <>
            <ZoneBtn Icon={IconLibrary} label="Library" count={char.library_count}
              innerRef={libraryBtnRef} pulseKey={libraryPulse}
              onClick={() => openZone({ kind: "library", charId: char.id })} />
            <ZoneBtn Icon={IconGrave} label="Grave" count={char.graveyard_count}
              onClick={() => openZone({ kind: "graveyard", charId: char.id })} />
            <ZoneBtn Icon={IconChannel} label="Channel" count={char.channels_summary.length}
              lit={char.is_channeling} disabled={!char.is_channeling}
              onClick={() => openZone({ kind: "channel", charId: char.id })} />
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-xs font-light italic text-dimmed">
            not your seat
          </div>
        )}
      </div>

      <ManaWidget char={char} manaChoices={choices?.mana ?? []} />

      {/* The Ultimate (D8-3.2): icon + vertical gauge between mana and actions. */}
      <UltimateColumn choices={choices} char={char} />

      <div className="flex w-[225px] shrink-0 flex-col">
        <ActionBar choices={choices} reaction={reaction} char={char} />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {char.hand ? (
          <div ref={handAreaRef} className="min-h-0 flex-1">
            <Hand hand={char.hand} choices={choices} />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center text-sm font-light italic text-dimmed">
            hidden
          </div>
        )}
      </div>

      {/* The resolution hold: a click-catcher over the action surface while
          the board's effects land (≤ ~2s). Dim, not dark — the prompt is
          coming, the world is just still moving. */}
      {holding && (
        <div
          className="absolute inset-0 z-30 cursor-wait bg-ink-0/25"
          aria-hidden
        />
      )}
    </div>
  );
}

function ZoneBtn({ Icon, label, count, onClick, disabled, lit, innerRef, pulseKey }: {
  Icon: typeof IconLibrary;
  label: string;
  count: number;
  onClick: () => void;
  disabled?: boolean;
  lit?: boolean;
  innerRef?: Ref<HTMLButtonElement>;
  pulseKey?: number;
}) {
  return (
    <button
      ref={innerRef}
      onClick={onClick}
      disabled={disabled}
      className={`flex min-h-0 flex-1 items-center justify-between border border-line bg-black/20 px-2.5 transition ${
        disabled
          ? "cursor-not-allowed opacity-40"
          : "hover:border-line2 hover:bg-brass/5"
      }`}
    >
      <span className="caps-label flex items-center gap-1.5 text-[11px] tracking-[0.14em] text-mist">
        <Icon size={14} className="text-dimmed" />
        {label}
      </span>
      <span
        key={pulseKey ?? 0}
        className={`font-display text-[18px] ${lit ? "text-aether" : "text-parch"} ${pulseKey ? "hud-counter-pulse" : ""}`}
      >
        {count}
      </span>
    </button>
  );
}
