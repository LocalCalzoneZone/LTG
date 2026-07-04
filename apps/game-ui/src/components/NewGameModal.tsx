import { useEffect, useState } from "react";
import { createGame, fetchSetupOptions, generateEncounter } from "../lib/api";
import type { SetupOptions } from "../lib/types";
import { ManaIcon } from "./Pips";

// Sentinel encounter id for the "generate a new one" choice.
const GENERATE = "__generate__";
const DIFFICULTIES = ["easy", "standard", "hard"];

export function NewGameModal({ onClose, onStarted }: {
  onClose: (() => void) | null; // null == not dismissable (first launch)
  onStarted: (sessionId: string) => void;
}) {
  const [opts, setOpts] = useState<SetupOptions | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [encounter, setEncounter] = useState<string>("");
  const [difficulty, setDifficulty] = useState("standard");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null); // busy sub-status
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchSetupOptions()
      .then((o) => {
        setOpts(o);
        if (o.encounters[0]) setEncounter(o.encounters[0].id);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      let encounterId = encounter;
      if (encounter === GENERATE) {
        setStatus("Generating encounter… (this can take up to a minute)");
        const meta = await generateEncounter(picked, difficulty, note);
        encounterId = meta.id;
      }
      setStatus("Starting game…");
      const sid = await createGame(picked, encounterId);
      onStarted(sid);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
      setStatus(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="max-h-[85vh] w-[min(92vw,720px)] overflow-y-auto rounded-xl bg-slate-800 p-5 shadow-2xl ring-1 ring-white/10">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold">New Game</h2>
          {onClose && (
            <button onClick={onClose} className="text-gray-400 hover:text-white">
              ✕
            </button>
          )}
        </div>

        {!opts && !err && <div className="text-gray-400">Loading options…</div>}
        {err && <div className="mb-3 rounded bg-red-900/50 px-3 py-2 text-sm text-red-200">{err}</div>}

        {opts && (
          <>
            <section className="mb-4">
              <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-gray-400">
                Characters ({picked.length} selected)
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {opts.characters.map((c) => {
                  const on = picked.includes(c.id);
                  return (
                    <button
                      key={c.id}
                      onClick={() => toggle(c.id)}
                      className={`overflow-hidden rounded-lg text-left ring-1 transition ${
                        on ? "bg-blue-600/30 ring-blue-400" : "bg-slate-700/50 ring-white/10 hover:ring-white/30"
                      }`}
                    >
                      {c.portrait && (
                        <img src={c.portrait} alt={c.name} className="aspect-[3/2] w-full object-cover object-top" />
                      )}
                      <div className="p-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold">{c.name}</span>
                          <span className="flex gap-0.5">
                            {c.identity.map((col, i) => (
                              <ManaIcon key={i} color={col} size={14} />
                            ))}
                          </span>
                        </div>
                        <div className="text-xs text-gray-400">{c.archetype}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="mb-5">
              <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-gray-400">Encounter</h3>
              <div className="flex flex-col gap-1">
                {/* Generate a fresh encounter via the LLM, scoped to the picked party. */}
                <label
                  className={`flex cursor-pointer flex-col gap-2 rounded-lg p-2 ring-1 transition ${
                    encounter === GENERATE
                      ? "bg-violet-600/30 ring-violet-400"
                      : "bg-slate-700/50 ring-white/10"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="encounter"
                      checked={encounter === GENERATE}
                      onChange={() => setEncounter(GENERATE)}
                    />
                    <span className="font-medium">✨ Generate new encounter</span>
                    <span className="ml-auto text-xs text-gray-400">scaled to your party</span>
                  </div>
                  {encounter === GENERATE && (
                    <div className="flex flex-col gap-2 pl-6" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-2">
                        <span className="text-xs uppercase tracking-wide text-gray-400">Difficulty</span>
                        <div className="flex gap-1">
                          {DIFFICULTIES.map((d) => (
                            <button
                              key={d}
                              type="button"
                              onClick={() => setDifficulty(d)}
                              className={`rounded px-3 py-1 text-xs font-semibold capitalize transition ${
                                difficulty === d
                                  ? "bg-violet-600 text-white"
                                  : "bg-slate-900 text-gray-300 hover:text-white"
                              }`}
                            >
                              {d}
                            </button>
                          ))}
                        </div>
                      </div>
                      <input
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        maxLength={140}
                        placeholder="Optional theme, e.g. “undead pirates besieging a lighthouse”"
                        className="rounded bg-slate-900 px-2 py-1.5 text-sm ring-1 ring-white/10 focus:outline-none focus:ring-violet-400"
                      />
                    </div>
                  )}
                </label>

                {opts.encounters.map((e) => (
                  <label
                    key={e.id}
                    className={`flex cursor-pointer items-center gap-2 rounded-lg p-2 ring-1 transition ${
                      encounter === e.id ? "bg-blue-600/30 ring-blue-400" : "bg-slate-700/50 ring-white/10"
                    }`}
                  >
                    <input
                      type="radio"
                      name="encounter"
                      checked={encounter === e.id}
                      onChange={() => setEncounter(e.id)}
                    />
                    <span className="font-medium">{e.name}</span>
                    <span className="ml-auto text-xs text-gray-400">{e.enemy_names.join(", ")}</span>
                  </label>
                ))}
              </div>
            </section>

            {busy && status && (
              <div className="mb-3 rounded bg-violet-900/40 px-3 py-2 text-sm text-violet-200">{status}</div>
            )}

            <button
              disabled={busy || picked.length === 0 || !encounter}
              onClick={start}
              className="w-full rounded-lg bg-blue-600 py-2.5 font-bold hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-600"
            >
              {busy ? "Working…" : encounter === GENERATE ? "Generate & Start" : "Start Game"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
