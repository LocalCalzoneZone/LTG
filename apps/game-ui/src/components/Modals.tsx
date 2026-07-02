import { useGame } from "../lib/store";

function Backdrop({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60"
      onClick={onClose}
      onContextMenu={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="max-h-[80vh] w-[min(90vw,560px)] overflow-y-auto rounded-xl bg-slate-800 p-4 shadow-2xl ring-1 ring-white/10" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

/** §4.8 "Choose one" modal for a modal card. */
export function ChooseModeModal() {
  const choice = useGame((s) => s.chooseModeFor);
  const pickMode = useGame((s) => s.pickMode);
  const cancel = useGame((s) => s.cancelArm);
  if (!choice?.modes) return null;
  return (
    <Backdrop onClose={cancel}>
      <h2 className="mb-3 text-lg font-bold">Choose a mode</h2>
      <div className="flex flex-col gap-2">
        {choice.modes.map((m) => (
          <button
            key={m.key}
            onClick={() => pickMode(m)}
            className="rounded-lg bg-slate-700 px-3 py-2 text-left text-sm hover:bg-blue-600"
          >
            {m.label}
          </button>
        ))}
      </div>
      <button onClick={cancel} className="mt-3 text-xs text-gray-400 hover:text-white">
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
    const dropIdx = choices.find((a) => a.kind === "drop_channels" && a.actor_id === char.id)?.index;
    body = (
      <div className="flex flex-col gap-2">
        {char.channels_summary.length === 0 ? (
          <div className="text-sm italic text-gray-500">no active channels</div>
        ) : (
          char.channels_summary.map((ch) => (
            <div key={ch.card_id} className="rounded bg-white/5 p-2 text-sm">
              <div className="font-semibold">{ch.card_name}</div>
              {ch.target_name && <div className="text-xs text-gray-400">on {ch.target_name}</div>}
              <div className="text-xs text-gray-300">{ch.text}</div>
            </div>
          ))
        )}
        {dropIdx != null && (
          <button
            onClick={() => {
              submit(dropIdx);
              onClose();
            }}
            className="rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold hover:bg-red-600"
          >
            Drop concentration (ends all)
          </button>
        )}
      </div>
    );
  }

  return (
    <Backdrop onClose={onClose}>
      <h2 className="mb-3 text-lg font-bold">{title}</h2>
      {body}
      <button onClick={onClose} className="mt-3 text-xs text-gray-400 hover:text-white">
        Close (Esc)
      </button>
    </Backdrop>
  );
}

function CardList({ cards }: { cards: { id: string; name: string; type: string; cost: string }[] }) {
  if (!cards.length) return <div className="text-sm italic text-gray-500">empty</div>;
  return (
    <div className="grid grid-cols-2 gap-1">
      {cards.map((c, i) => (
        <div key={`${c.id}-${i}`} className="rounded bg-white/5 px-2 py-1 text-sm">
          <span className="font-medium">{c.name}</span>
          <span className="ml-1 text-xs text-gray-400">{c.type}</span>
        </div>
      ))}
    </div>
  );
}

/** §4.6 mandatory mid-resolution pick (move_card / scry) — a blocking prompt. */
export function CardPickPrompt() {
  const snapshot = useGame((s) => s.snapshot);
  const submit = useGame((s) => s.submitIndex);
  const you = useGame((s) => s.you);
  if (!snapshot) return null;
  if (snapshot.priority.kind !== "card_choice") return null;
  const holder = snapshot.priority.holder_character_id;
  if (!holder || !you.includes(holder)) return null; // only the controlling client acts
  const picks = snapshot.legal_actions.filter(
    (a) => a.kind === "choose_card" || a.kind === "choose_scry",
  );
  if (!picks.length) return null;
  return (
    <Backdrop onClose={() => {}}>
      <h2 className="mb-3 text-lg font-bold">Make a choice</h2>
      <div className="flex flex-col gap-2">
        {picks.map((p) => (
          <button
            key={p.index}
            onClick={() => submit(p.index)}
            className="rounded-lg bg-slate-700 px-3 py-2 text-left text-sm hover:bg-blue-600"
          >
            {p.label}
          </button>
        ))}
      </div>
    </Backdrop>
  );
}

/** §4.16 game-over overlay (board stays visible behind). */
export function GameOverOverlay({ onNewGame }: { onNewGame: () => void }) {
  const result = useGame((s) => s.gameOver ?? s.snapshot?.result ?? null);
  if (!result) return null;
  const win = result === "victory";
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50">
      <div className="rounded-2xl bg-slate-800 px-10 py-8 text-center shadow-2xl ring-1 ring-white/10">
        <div className={`text-4xl font-black ${win ? "text-emerald-400" : "text-red-500"}`}>
          {win ? "Victory" : "Defeat"}
        </div>
        <button
          onClick={onNewGame}
          className="mt-5 rounded-lg bg-blue-600 px-5 py-2 font-semibold hover:bg-blue-500"
        >
          New Game
        </button>
      </div>
    </div>
  );
}

/** Transient error toast (§2.3 error). */
export function Toast() {
  const error = useGame((s) => s.error);
  if (!error) return null;
  return (
    <div className="fixed bottom-44 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold shadow-lg">
      {error}
    </div>
  );
}
