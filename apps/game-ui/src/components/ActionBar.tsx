import { useGame } from "../lib/store";
import type { Choice, Choices } from "../lib/choices";

const CORE: { key: keyof Choices; icon: string; label: string }[] = [
  { key: "attack", icon: "⚔", label: "Attack" },
  { key: "defend", icon: "🛡", label: "Defend" },
  { key: "mitigate", icon: "🩹", label: "Mitigate" },
  { key: "move", icon: "➜", label: "Move" },
];

export function ActionBar({ choices, reaction }: { choices: Choices | null; reaction: boolean }) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);

  const coreBtn = ({ key, icon, label }: { key: keyof Choices; icon: string; label: string }) => {
    const choice = choices?.[key] as Choice | undefined;
    const enabled = !!choice;
    const active = armed?.kind === choice?.kind && armed?.cardId == null;
    return (
      <button
        key={label}
        disabled={!enabled}
        onClick={() => choice && select(choice)}
        title={label}
        className={`flex flex-col items-center justify-center gap-0.5 rounded-lg text-xs font-semibold transition ${
          enabled
            ? active
              ? "bg-yellow-500 text-black shadow"
              : "bg-slate-700 hover:bg-slate-600"
            : "cursor-not-allowed bg-slate-800/40 text-gray-600"
        }`}
      >
        <span className="text-xl leading-none">{icon}</span>
        {label}
      </button>
    );
  };

  return (
    <div className="flex h-full flex-col gap-2">
      {reaction && (
        <div className="rounded bg-amber-500/20 py-0.5 text-center text-[10px] font-bold uppercase tracking-wide text-amber-300">
          reaction
        </div>
      )}
      {/* 2×2 core actions — fill the available height */}
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-2">
        {CORE.map(coreBtn)}
      </div>
      {/* Drop Channel sits ABOVE Pass / End Turn so those two stay anchored at the
          bottom in their usual spot — otherwise it appears where Pass normally is and
          invites a mis-click when you mean to pass. */}
      {choices?.dropChannels && (
        <TextBtn choice={choices.dropChannels} label="Drop Channel" />
      )}
      {/* Pass / End Turn — prominent, always the bottom-most controls */}
      <div className="grid grid-cols-2 gap-2">
        <TextBtn choice={choices?.pass} label="Pass" />
        <TextBtn choice={choices?.endTurn} label="End Turn" />
      </div>
    </div>
  );
}

function TextBtn({ choice, label }: { choice?: Choice; label: string }) {
  const select = useGame((s) => s.selectChoice);
  const enabled = !!choice;
  return (
    <button
      disabled={!enabled}
      onClick={() => choice && select(choice)}
      className={`rounded-lg py-1.5 text-sm font-semibold transition ${
        enabled ? "bg-slate-700 hover:bg-slate-600" : "cursor-not-allowed bg-slate-800/40 text-gray-600"
      }`}
    >
      {label}
    </button>
  );
}
