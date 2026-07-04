import { useGame, focusedChoices } from "../lib/store";
import { ActionBar } from "./ActionBar";
import { ArmingHint } from "./ArmingHint";
import { Hand } from "./Hand";
import { ManaWidget } from "./ManaWidget";

export function BottomBar() {
  const snapshot = useGame((s) => s.snapshot);
  const focusedId = useGame((s) => s.focusedId);
  const choices = useGame(focusedChoices);
  const openZone = useGame((s) => s.openZone);
  if (!snapshot) return null;

  const char = snapshot.characters.find((c) => c.id === focusedId) ?? null;
  if (!char) {
    return (
      <div className="flex h-40 items-center justify-center border-t border-white/10 bg-black/40 text-sm text-gray-500">
        Select one of your characters to act.
      </div>
    );
  }

  const reaction = snapshot.priority.kind === "reaction" && snapshot.priority.holder_character_id === char.id;

  return (
    <div
      style={{ height: "clamp(200px, 27vh, 320px)" }}
      className="relative flex shrink-0 items-stretch gap-3 border-t border-white/10 bg-black/40 p-3"
    >
      <ArmingHint />
      <ManaWidget char={char} manaChoices={choices?.mana ?? []} />

      {/* Zones — a vertical column of the controlled character's hidden zones. */}
      {char.controlled && (
        <div className="flex w-[92px] shrink-0 flex-col gap-2">
          <ZoneBtn label="Library" count={char.library_count} onClick={() => openZone({ kind: "library", charId: char.id })} />
          <ZoneBtn label="Grave" count={char.graveyard_count} onClick={() => openZone({ kind: "graveyard", charId: char.id })} />
          <ZoneBtn
            label="Channel"
            count={char.channels_summary.length}
            disabled={!char.is_channeling}
            onClick={() => openZone({ kind: "channel", charId: char.id })}
          />
        </div>
      )}

      <div className="flex w-[240px] shrink-0 flex-col">
        <ActionBar choices={choices} reaction={reaction} />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-1 shrink-0 text-[11px] font-bold uppercase tracking-wide text-gray-400">
          {char.name}'s hand
        </div>
        {char.hand ? (
          <div className="min-h-0 flex-1">
            <Hand hand={char.hand} choices={choices} />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center text-sm italic text-gray-600">hidden</div>
        )}
      </div>
    </div>
  );
}

function ZoneBtn({ label, count, onClick, disabled }: {
  label: string;
  count: number;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex min-h-0 flex-1 flex-col items-center justify-center rounded-lg py-1 leading-tight transition ${
        disabled ? "cursor-not-allowed bg-slate-800/40 text-gray-600" : "bg-slate-700 hover:bg-slate-600"
      }`}
    >
      <span className="text-[11px] font-semibold">{label}</span>
      <span className={`text-lg font-bold ${disabled ? "" : "text-sky-300"}`}>{count}</span>
    </button>
  );
}
