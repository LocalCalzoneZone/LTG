import { useEffect, useState } from "react";
import { createGame, fetchSetupOptions, generateEncounter } from "../lib/api";
import type { SetupOptions } from "../lib/types";
import { ManaIcon } from "./Pips";
import { IconX } from "./Icons";

// Sentinel encounter id for the "generate a new one" choice.
const GENERATE = "__generate__";
const DIFFICULTIES = ["easy", "standard", "hard"];

const SECTION = "caps-label mb-2 text-[10px] tracking-[0.25em] text-brass";

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-[2px]">
      <div className="panel-ticks max-h-[85vh] w-[min(92vw,720px)] overflow-y-auto border border-line2 bg-ink-2 p-5 shadow-2xl">
        <div className="mb-4 flex items-center gap-3">
          <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">New Game</h2>
          <span className="h-px flex-1 bg-line" />
          {onClose && (
            <button onClick={onClose} className="text-mist hover:text-parch" title="Close">
              <IconX size={14} />
            </button>
          )}
        </div>

        {!opts && !err && <div className="font-light text-mist">Loading options…</div>}
        {err && (
          <div className="mb-3 border border-blood/60 bg-blood/10 px-3 py-2 text-sm font-light text-[#f2ddd3]">
            {err}
          </div>
        )}

        {opts && (
          <>
            <section className="mb-4">
              <h3 className={SECTION}>Characters · {picked.length} selected</h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {opts.characters.map((c) => {
                  const on = picked.includes(c.id);
                  return (
                    <button
                      key={c.id}
                      onClick={() => toggle(c.id)}
                      className={`overflow-hidden border text-left transition ${
                        on
                          ? "border-brass bg-brass/10 shadow-[0_0_14px_rgba(233,204,130,0.15)]"
                          : "border-line bg-white/[0.02] hover:border-line2"
                      }`}
                    >
                      {c.portrait && (
                        <img src={c.portrait} alt={c.name} className="aspect-[3/2] w-full object-cover object-top" />
                      )}
                      <div className="p-2">
                        <div className="flex items-center justify-between">
                          <span className="caps-label text-[11px] tracking-[0.1em] text-parch">{c.name}</span>
                          <span className="flex gap-0.5">
                            {c.identity.map((col, i) => (
                              <ManaIcon key={i} color={col} size={13} />
                            ))}
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="mb-5">
              <h3 className={SECTION}>Encounter</h3>
              <div className="flex flex-col gap-1">
                {/* Generate a fresh encounter via the LLM, scoped to the picked party. */}
                <label
                  className={`flex cursor-pointer flex-col gap-2 border p-2 transition ${
                    encounter === GENERATE
                      ? "border-aether/70 bg-aether/10"
                      : "border-line bg-white/[0.02] hover:border-line2"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="encounter"
                      className="accent-[#b39ddb]"
                      checked={encounter === GENERATE}
                      onChange={() => setEncounter(GENERATE)}
                    />
                    <span className="font-normal text-parch">Generate new encounter</span>
                    <span className="ml-auto text-xs font-light text-mist">scaled to your party</span>
                  </div>
                  {encounter === GENERATE && (
                    <div className="flex flex-col gap-2 pl-6" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-2">
                        <span className="caps-label text-[9px] tracking-[0.2em] text-mist">Difficulty</span>
                        <div className="flex gap-1">
                          {DIFFICULTIES.map((d) => (
                            <button
                              key={d}
                              type="button"
                              onClick={() => setDifficulty(d)}
                              className={`caps-label border px-3 py-1 text-[9px] tracking-[0.14em] transition ${
                                difficulty === d
                                  ? "border-aether bg-aether/20 text-aether"
                                  : "border-line text-mist hover:text-parch"
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
                        className="border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-aether/70 focus:outline-none"
                      />
                    </div>
                  )}
                </label>

                {opts.encounters.map((e) => (
                  <label
                    key={e.id}
                    className={`flex cursor-pointer items-center gap-2 border p-2 transition ${
                      encounter === e.id
                        ? "border-brass bg-brass/10"
                        : "border-line bg-white/[0.02] hover:border-line2"
                    }`}
                  >
                    <input
                      type="radio"
                      name="encounter"
                      className="accent-[#c9b37e]"
                      checked={encounter === e.id}
                      onChange={() => setEncounter(e.id)}
                    />
                    <span className="font-normal text-parch">{e.name}</span>
                    {e.scales && e.scales.length > 0 && (
                      <span className="caps-label shrink-0 text-[10px] tracking-[0.1em] text-brass">
                        scales {Math.min(...e.scales)}–{Math.max(...e.scales)}
                      </span>
                    )}
                    <span className="ml-auto truncate text-xs font-light text-mist">
                      {e.enemy_names.join(", ")}
                    </span>
                  </label>
                ))}
              </div>
            </section>

            {busy && status && (
              <div className="mb-3 border border-aether/50 bg-aether/10 px-3 py-2 text-sm font-light text-aether">
                {status}
              </div>
            )}

            <button
              disabled={busy || picked.length === 0 || !encounter}
              onClick={start}
              className={`chamfer-x caps-label w-full py-2.5 text-[11px] tracking-[0.3em] transition ${
                busy || picked.length === 0 || !encounter
                  ? "cursor-not-allowed bg-white/[0.03] text-dimmed"
                  : "bg-gradient-to-b from-brass-hi to-brass text-ink-0 hover:from-brass-hi hover:to-brass-hi"
              }`}
            >
              {busy ? "Working…" : encounter === GENERATE ? "Generate & Start" : "Start Game"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
