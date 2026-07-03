import { armedTargetIdSet, useGame } from "../lib/store";

export function SidePanel({ onNewGame, onOptions }: { onNewGame: () => void; onOptions: () => void }) {
  const snapshot = useGame((s) => s.snapshot);
  const armed = useGame((s) => s.armed);
  const pickTargetId = useGame((s) => s.pickTargetId);

  // A counter arms with stack-ref targets ("#<uid>"): those rows become clickable.
  const targetIds = armedTargetIdSet(armed);

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      {/* Game Options Bar — always available (so an empty battlefield can reach these) */}
      <div className="flex items-center gap-2">
        <button
          onClick={onNewGame}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-semibold hover:bg-blue-500"
          title="New Game"
        >
          ⊕ New Game
        </button>
        <button
          onClick={onOptions}
          className="rounded bg-slate-700 px-3 py-1.5 text-sm font-semibold text-gray-300 hover:bg-slate-600"
          title="Characters & import"
        >
          ⚙ Options
        </button>
        {snapshot && (
          <div className="ml-auto text-right text-xs text-gray-400">
            <div>Turn {snapshot.turn}</div>
            <div className="capitalize">{snapshot.phase_label}</div>
          </div>
        )}
      </div>

      {!snapshot && (
        <div className="flex flex-1 items-center justify-center px-2 text-center text-xs italic text-gray-600">
          No game loaded.
        </div>
      )}

      {snapshot && (
        <>
      {/* Stack + Intents */}
      <div className="grid grid-cols-2 gap-2">
        <Panel title="Stack">
          {snapshot.stack.length === 0 ? (
            <Empty>empty</Empty>
          ) : (
            snapshot.stack.map((s, i) => {
              const isTarget = targetIds.has(`#${s.uid}`);
              return (
                <div
                  key={i}
                  onClick={() => isTarget && pickTargetId(`#${s.uid}`)}
                  className={`rounded px-1.5 py-1 text-[11px] ${
                    isTarget
                      ? "cursor-pointer bg-yellow-400/20 ring-2 ring-yellow-400"
                      : s.top
                        ? "bg-amber-500/20"
                        : "bg-white/5"
                  }`}
                >
                  <span className="font-semibold">{s.source_name}</span>
                  <span className="text-gray-400"> · {s.label}</span>
                  {s.target_name && <span className="text-gray-400"> → {s.target_name}</span>}
                </div>
              );
            })
          )}
          <div className="mt-1 text-[9px] text-gray-500">bottom = resolves last</div>
        </Panel>

        <Panel title="Intents">
          {snapshot.intents.length === 0 ? (
            <Empty>none</Empty>
          ) : (
            snapshot.intents.map((it, i) => (
              <div key={i} className="rounded bg-white/5 px-1.5 py-1 text-[11px]">
                <span className="font-semibold text-rose-300">{it.creature_name}</span>
                <span className="text-gray-400"> · {it.intent_text}</span>
                {it.target_name && <span className="text-gray-400"> → {it.target_name}</span>}
              </div>
            ))
          )}
        </Panel>
      </div>

      {/* Game Log (fills the rest) */}
      <Panel title="Game Log" className="min-h-0 flex-1">
        <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto pr-1">
          {snapshot.log.length === 0 ? (
            <Empty>no events yet</Empty>
          ) : (
            snapshot.log.map((e, i) => (
              <div key={i} className="text-[11px] leading-snug text-gray-300">
                {e.msg}
              </div>
            ))
          )}
        </div>
      </Panel>
        </>
      )}
    </div>
  );
}

function Panel({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col rounded-lg bg-black/30 p-2 ring-1 ring-white/5 ${className}`}>
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-gray-400">{title}</div>
      <div className="flex min-h-0 flex-1 flex-col gap-1">{children}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] italic text-gray-600">{children}</div>;
}
