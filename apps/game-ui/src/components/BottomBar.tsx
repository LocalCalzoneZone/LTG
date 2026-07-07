import { useGame, focusedChoices } from "../lib/store";
import { ActionBar } from "./ActionBar";
import { ArmingHint } from "./ArmingHint";
import { Hand } from "./Hand";
import { ManaPayPopup, ManaWidget } from "./ManaWidget";
import { IconChannel, IconGrave, IconLibrary } from "./Icons";

export function BottomBar({ height }: { height?: number | null }) {
  const snapshot = useGame((s) => s.snapshot);
  const focusedId = useGame((s) => s.focusedId);
  const choices = useGame(focusedChoices);
  const openZone = useGame((s) => s.openZone);
  if (!snapshot) return null;

  const char = snapshot.characters.find((c) => c.id === focusedId) ?? null;
  if (!char) {
    return (
      <div className="flex h-40 items-center justify-center bg-gradient-to-b from-ink-2 to-ink-0 text-sm font-light text-mist">
        Select one of your characters to act.
      </div>
    );
  }

  const reaction = snapshot.priority.kind === "reaction" && snapshot.priority.holder_character_id === char.id;

  return (
    <div
      // A dragged height (from the splitter above) overrides the responsive default.
      style={{ height: height ? `${height}px` : "clamp(200px, 27vh, 320px)" }}
      className="relative flex shrink-0 items-stretch gap-2.5 bg-gradient-to-b from-ink-2 to-ink-0 p-2.5"
    >
      <ArmingHint />
      <ManaPayPopup />

      {/* who am I acting as + hidden zones — one block */}
      <div className="flex w-[150px] shrink-0 flex-col gap-1.5">
        <div className="flex items-center justify-center border border-line bg-black/25 px-2 py-2">
          <div className="caps-label min-w-0 truncate text-[14px] tracking-[0.14em] text-parch">
            {char.name}
          </div>
        </div>

        {char.controlled ? (
          <>
            <ZoneBtn Icon={IconLibrary} label="Library" count={char.library_count}
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

      <div className="flex w-[225px] shrink-0 flex-col">
        <ActionBar choices={choices} reaction={reaction} />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {char.hand ? (
          <div className="min-h-0 flex-1">
            <Hand hand={char.hand} choices={choices} />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center text-sm font-light italic text-dimmed">
            hidden
          </div>
        )}
      </div>
    </div>
  );
}

function ZoneBtn({ Icon, label, count, onClick, disabled, lit }: {
  Icon: typeof IconLibrary;
  label: string;
  count: number;
  onClick: () => void;
  disabled?: boolean;
  lit?: boolean;
}) {
  return (
    <button
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
      <span className={`font-display text-[18px] ${lit ? "text-aether" : "text-parch"}`}>{count}</span>
    </button>
  );
}
