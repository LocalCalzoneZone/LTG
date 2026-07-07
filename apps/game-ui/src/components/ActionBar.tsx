import { useGame } from "../lib/store";
import type { Choice, Choices } from "../lib/choices";
import { IconMend, IconMove, IconShield, IconSword } from "./Icons";

const CORE: { key: keyof Choices; Icon: typeof IconSword; label: string }[] = [
  { key: "attack", Icon: IconSword, label: "Attack" },
  { key: "defend", Icon: IconShield, label: "Defend" },
  { key: "mitigate", Icon: IconMend, label: "Mitigate" },
  { key: "move", Icon: IconMove, label: "Move" },
];

export function ActionBar({ choices, reaction }: { choices: Choices | null; reaction: boolean }) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);
  const startPassAll = useGame((s) => s.startPassAll);
  const passAllFor = useGame((s) => s.passAllFor);
  // Active only when THIS character (the one holding priority for `pass`) is the one
  // auto-passing — not when a different party member armed Pass All.
  const passActor = choices?.pass?.candidates[0]?.actor_id;
  const passAllActive = passAllFor != null && passAllFor === passActor;

  const coreBtn = ({ key, Icon, label }: (typeof CORE)[number]) => {
    const choice = choices?.[key] as Choice | undefined;
    const enabled = !!choice;
    const active = armed?.kind === choice?.kind && armed?.cardId == null;
    return (
      <button
        key={label}
        disabled={!enabled}
        onClick={() => choice && select(choice)}
        title={label}
        className={`caps-label flex flex-col items-center justify-center gap-1 border text-[11px] tracking-[0.14em] transition ${
          enabled
            ? active
              ? "border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0 shadow-[0_0_14px_rgba(233,204,130,0.3)]"
              : "border-line bg-white/[0.02] text-parch hover:border-brass hover:bg-brass/10 hover:shadow-[0_0_14px_rgba(233,204,130,0.12)]"
            : "cursor-not-allowed border-line/50 text-dimmed/60 opacity-60"
        }`}
      >
        <Icon size={19} className={enabled ? (active ? "text-ink-0" : "text-brass") : "text-dimmed/60"} />
        {label}
      </button>
    );
  };

  return (
    <div className="flex h-full flex-col gap-1.5">
      {reaction && (
        <div className="caps-label border border-brass/40 bg-brass/10 py-0.5 text-center text-[10px] tracking-[0.3em] text-brass-hi">
          Reaction Window
        </div>
      )}
      {/* 2×2 core actions — fill the available height */}
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-1.5">
        {CORE.map(coreBtn)}
      </div>
      {/* Pass / Pass All — Pass All keeps passing until the stack fully resolves.
          When passing is an option it's usually THE decision, so both light brass. */}
      <div className="grid grid-cols-2 gap-1.5">
        <button
          disabled={!choices?.pass}
          onClick={() => choices?.pass && select(choices.pass)}
          className={`caps-label border py-1.5 text-[11px] tracking-[0.16em] transition ${
            choices?.pass
              ? "border-brass/60 bg-brass/10 text-brass hover:bg-brass hover:text-ink-0"
              : "cursor-not-allowed border-line/50 text-dimmed/60"
          }`}
        >
          Pass
        </button>
        <button
          disabled={!choices?.pass}
          onClick={startPassAll}
          title="Pass every reaction window until the stack fully resolves"
          className={`caps-label border py-1.5 text-[11px] tracking-[0.16em] transition ${
            !choices?.pass
              ? "cursor-not-allowed border-line/50 text-dimmed/60"
              : passAllActive
                ? "border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0"
                : "border-brass/60 bg-brass/10 text-brass hover:bg-brass hover:text-ink-0"
          }`}
        >
          Pass All
        </button>
      </div>
      {/* End Turn — prominent, always the bottom-most control */}
      <button
        disabled={!choices?.endTurn}
        onClick={() => choices?.endTurn && select(choices.endTurn)}
        className={`chamfer-x caps-label py-2 text-[12px] tracking-[0.3em] transition ${
          choices?.endTurn
            ? "bg-gradient-to-b from-brass/15 to-brass/5 text-brass ring-1 ring-inset ring-brass/40 hover:from-brass-hi hover:to-brass hover:text-ink-0"
            : "cursor-not-allowed bg-white/[0.02] text-dimmed/60"
        }`}
      >
        End Turn
      </button>
    </div>
  );
}
