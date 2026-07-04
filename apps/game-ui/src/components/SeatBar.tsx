import { useGame } from "../lib/store";

export function SeatBar() {
  const snapshot = useGame((s) => s.snapshot);
  const seats = useGame((s) => s.seats);
  const you = useGame((s) => s.you);
  const clientId = useGame((s) => s.clientId);
  const claim = useGame((s) => s.claim);
  const release = useGame((s) => s.release);
  const connected = useGame((s) => s.connected);
  if (!snapshot) return null;

  const youSet = new Set(you);
  const unclaimed = snapshot.characters.map((c) => c.id).filter((id) => seats[id] == null);

  return (
    <div className="flex items-center gap-2 border-b border-white/10 bg-black/40 px-3 py-1.5 text-xs">
      <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-red-500"}`} title={connected ? "connected" : "disconnected"} />
      <span className="font-bold text-gray-300">Seats:</span>
      {snapshot.characters.map((c) => {
        const owner = seats[c.id];
        const mine = youSet.has(c.id);
        const taken = owner != null && owner !== clientId;
        return (
          <button
            key={c.id}
            disabled={taken}
            onClick={() => (mine ? release([c.id]) : claim([c.id]))}
            className={`rounded px-2 py-0.5 font-medium transition ${
              mine
                ? "bg-emerald-600 hover:bg-emerald-500"
                : taken
                  ? "cursor-not-allowed bg-slate-800 text-gray-500"
                  : "bg-slate-700 hover:bg-slate-600"
            }`}
            title={mine ? "Release" : taken ? "Claimed by another player" : "Claim"}
          >
            {c.name}
            {mine ? " ✓" : taken ? " 🔒" : ""}
          </button>
        );
      })}
      {unclaimed.length > 0 && (
        <button
          onClick={() => claim(unclaimed)}
          className="rounded bg-blue-600 px-2 py-0.5 font-semibold hover:bg-blue-500"
        >
          Claim all
        </button>
      )}
      <button
        onClick={() => navigator.clipboard?.writeText(location.href)}
        className="ml-auto rounded bg-slate-700 px-2 py-0.5 hover:bg-slate-600"
        title="Copy the shareable session URL"
      >
        🔗 Copy invite
      </button>
    </div>
  );
}
