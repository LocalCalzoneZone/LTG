import { useEffect, useState } from "react";
import {
  createGame,
  fetchSetupOptions,
  generateAdventure,
  generateEncounter,
} from "../lib/api";
import type { SetupOptions } from "../lib/types";
import { DifficultyTag } from "./DifficultyTag";
import { ManaIcon } from "./Pips";
import { IconSigil, IconX } from "./Icons";

// Sentinel ids for the "generate a new one" choices.
const GENERATE_ENC = "__generate_encounter__";
const GENERATE_ADV = "__generate_adventure__";
const DIFFICULTIES = ["easy", "standard", "hard"];

const SECTION = "caps-label mb-2 text-[10px] tracking-[0.25em] text-brass";

/** The selection is the mode (§D10-6.2): one encounter OR one adventure. */
type Pick =
  | { kind: "encounter"; id: string }
  | { kind: "adventure"; id: string }
  | null;

function DifficultyNote({ difficulty, setDifficulty, note, setNote, accent }: {
  difficulty: string;
  setDifficulty: (d: string) => void;
  note: string;
  setNote: (n: string) => void;
  accent: string; // tailwind color name: "aether" | "brass"
}) {
  return (
    <div className="flex flex-col gap-2 pl-6" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-2">
        <span className="caps-label text-[9px] tracking-[0.2em] text-mist">Difficulty</span>
        <div className="flex gap-1">
          {DIFFICULTIES.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDifficulty(d)}
              className={`caps-label border px-2.5 py-1 text-[9px] tracking-[0.14em] transition ${
                difficulty === d
                  ? accent === "aether"
                    ? "border-aether bg-aether/20 text-aether"
                    : "border-brass bg-brass/20 text-brass"
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
  );
}

export function NewGameModal({ onClose, onStarted }: {
  onClose: (() => void) | null; // null == not dismissable (first launch)
  onStarted: (sessionId: string) => void;
}) {
  const [opts, setOpts] = useState<SetupOptions | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [pick, setPick] = useState<Pick>(null);
  const [tab, setTab] = useState<"encounters" | "adventures">("encounters");
  const [difficulty, setDifficulty] = useState("standard");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null); // busy sub-status
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchSetupOptions()
      .then((o) => {
        setOpts(o);
        if (o.encounters[0]) setPick({ kind: "encounter", id: o.encounters[0].id });
      })
      .catch((e) => setErr(String(e)));
  }, []);

  // Switching tabs re-anchors the selection to that tab's first card (or its
  // generate row) so the Start button always reflects what's on screen.
  const switchTab = (t: "encounters" | "adventures") => {
    setTab(t);
    if (t === "encounters") {
      setPick({ kind: "encounter", id: opts?.encounters[0]?.id ?? GENERATE_ENC });
    } else {
      setPick({ kind: "adventure", id: opts?.adventures[0]?.id ?? GENERATE_ADV });
    }
  };

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const start = async () => {
    if (!pick) return;
    setBusy(true);
    setErr(null);
    try {
      if (pick.kind === "adventure") {
        let adventureId = pick.id;
        if (adventureId === GENERATE_ADV) {
          setStatus("Generating adventure — three acts in one arc… (this can take a few minutes)");
          const meta = await generateAdventure(picked, difficulty, note);
          adventureId = meta.id;
        }
        setStatus("Starting adventure…");
        onStarted(await createGame(picked, { adventureId }));
        return;
      }
      let encounterId = pick.id;
      if (encounterId === GENERATE_ENC) {
        setStatus("Generating encounter… (this can take up to a minute)");
        const meta = await generateEncounter(picked, difficulty, note);
        encounterId = meta.id;
      }
      setStatus("Starting game…");
      onStarted(await createGame(picked, { encounterId }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
      setStatus(null);
    }
  };

  const encPicked = pick?.kind === "encounter" ? pick.id : "";
  const advPicked = pick?.kind === "adventure" ? pick.id : "";
  const generating = encPicked === GENERATE_ENC || advPicked === GENERATE_ADV;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-[2px]">
      <div className="panel-ticks flex max-h-[88vh] w-[min(94vw,1180px)] flex-col border border-line2 bg-ink-2 p-5 shadow-2xl">
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
            <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              {/* Left — characters: full-height portraits, scrollable */}
              <section className="flex min-h-0 flex-col">
                <h3 className={SECTION}>Characters · {picked.length} selected</h3>
                {/* auto-rows-max: rows size to the tile's content — without it
                    the browser stretch-distributes the container height and
                    squashes the portraits into clipped slivers. */}
                <div className="scroll-thin grid min-h-0 flex-1 auto-rows-max grid-cols-3 content-start gap-2 overflow-y-auto pr-1">
                  {opts.characters.map((c) => {
                    const on = picked.includes(c.id);
                    return (
                      <button
                        key={c.id}
                        onClick={() => toggle(c.id)}
                        className={`relative flex flex-col overflow-hidden border text-left transition ${
                          on
                            ? "border-brass bg-brass/10 shadow-[0_0_14px_rgba(233,204,130,0.15)]"
                            : "border-line bg-white/[0.02] hover:border-line2"
                        }`}
                      >
                        {/* Uniform tiles: every portrait fills the same 3:4
                            frame (object-cover crops the overflow). */}
                        <div className="aspect-[3/4] w-full bg-ink-0">
                          {c.portrait ? (
                            <img src={c.portrait} alt={c.name} className="h-full w-full object-cover object-top" />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center text-dimmed">
                              <IconSigil size={30} />
                            </div>
                          )}
                        </div>
                        <div className="flex items-center justify-between gap-1 bg-gradient-to-t from-ink-0/95 to-ink-0/60 p-2">
                          <span className="caps-label truncate text-[11px] tracking-[0.1em] text-parch">
                            {c.name}
                          </span>
                          <span className="flex shrink-0 gap-0.5">
                            {c.identity.map((col, i) => (
                              <ManaIcon key={i} color={col} size={12} />
                            ))}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </section>

              {/* Right — the opposition: Encounters | Adventures, tabbed for
                  full-width title cards (Options-list typography, no truncation) */}
              <section className="flex min-h-0 flex-col">
                <div className="mb-2 flex items-center gap-4">
                  {(["encounters", "adventures"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => switchTab(t)}
                      className={`caps-label pb-1 text-[11px] tracking-[0.2em] transition ${
                        tab === t
                          ? "border-b border-brass text-brass-hi"
                          : "border-b border-transparent text-mist hover:text-parch"
                      }`}
                    >
                      {t === "encounters" ? "Encounters · one fight" : "Adventures · three acts"}
                    </button>
                  ))}
                </div>

                <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
                  <label
                    className={`flex cursor-pointer flex-col gap-2 border p-3 transition ${
                      (tab === "encounters" ? encPicked === GENERATE_ENC : advPicked === GENERATE_ADV)
                        ? "border-aether/70 bg-aether/10"
                        : "border-line bg-white/[0.02] hover:border-line2"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="target"
                        className="accent-[#b39ddb]"
                        checked={tab === "encounters" ? encPicked === GENERATE_ENC : advPicked === GENERATE_ADV}
                        onChange={() => setPick(tab === "encounters"
                          ? { kind: "encounter", id: GENERATE_ENC }
                          : { kind: "adventure", id: GENERATE_ADV })}
                      />
                      <span className="font-normal text-parch">
                        {tab === "encounters" ? "Generate new encounter" : "Generate new adventure"}
                      </span>
                    </div>
                    {(tab === "encounters" ? encPicked === GENERATE_ENC : advPicked === GENERATE_ADV) && (
                      <DifficultyNote difficulty={difficulty} setDifficulty={setDifficulty}
                                      note={note} setNote={setNote} accent="aether" />
                    )}
                  </label>

                  {tab === "encounters" && opts.encounters.map((e) => (
                    <label
                      key={e.id}
                      className={`flex cursor-pointer flex-col gap-1 border p-3 transition ${
                        encPicked === e.id
                          ? "border-brass bg-brass/10"
                          : "border-line bg-white/[0.02] hover:border-line2"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="target"
                          className="accent-[#c9b37e]"
                          checked={encPicked === e.id}
                          onChange={() => setPick({ kind: "encounter", id: e.id })}
                        />
                        <span className="caps-label text-[11px] tracking-[0.1em] text-parch">{e.name}</span>
                        <DifficultyTag difficulty={e.difficulty} />
                        {e.scales && e.scales.length > 0 && (
                          <span className="caps-label ml-auto shrink-0 text-[9px] tracking-[0.1em] text-brass">
                            scales {Math.min(...e.scales)}–{Math.max(...e.scales)}
                          </span>
                        )}
                      </div>
                      <div className="pl-6 text-xs font-light text-mist">
                        {e.enemy_count} {e.enemy_count === 1 ? "enemy" : "enemies"}
                        {" · "}{e.enemy_names.join(", ")}
                      </div>
                    </label>
                  ))}

                  {tab === "adventures" && opts.adventures.map((a) => (
                    <label
                      key={a.id}
                      className={`flex cursor-pointer flex-col gap-1 border p-3 transition ${
                        advPicked === a.id
                          ? "border-brass bg-brass/10"
                          : "border-line bg-white/[0.02] hover:border-line2"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="target"
                          className="accent-[#c9b37e]"
                          checked={advPicked === a.id}
                          onChange={() => setPick({ kind: "adventure", id: a.id })}
                        />
                        <span className="caps-label text-[11px] tracking-[0.1em] text-parch">{a.name}</span>
                        <DifficultyTag difficulty={a.difficulty} />
                      </div>
                      {a.flavor && (
                        <div className="pl-6 text-xs font-light italic text-mist">{a.flavor}</div>
                      )}
                      <div className="flex flex-col gap-0.5 pl-6">
                        {a.act_names.map((n, i) => (
                          <span key={i} className="text-[11px] font-light text-dimmed">
                            {["I", "II", "III"][i] ?? i + 1}. {n}
                          </span>
                        ))}
                      </div>
                    </label>
                  ))}
                  {tab === "adventures" && opts.adventures.length === 0 && (
                    <div className="px-1 py-2 text-xs font-light text-dimmed">
                      No adventures yet — generate one above, or author one in Options.
                    </div>
                  )}
                </div>
              </section>
            </div>

            {busy && status && (
              <div className="mb-3 mt-3 border border-aether/50 bg-aether/10 px-3 py-2 text-sm font-light text-aether">
                {status}
              </div>
            )}

            <button
              disabled={busy || picked.length === 0 || !pick}
              onClick={start}
              className={`chamfer-x caps-label mt-3 w-full py-2.5 text-[11px] tracking-[0.3em] transition ${
                busy || picked.length === 0 || !pick
                  ? "cursor-not-allowed bg-white/[0.03] text-dimmed"
                  : "bg-gradient-to-b from-brass-hi to-brass text-ink-0 hover:from-brass-hi hover:to-brass-hi"
              }`}
            >
              {busy ? "Working…" : generating ? "Generate & Start" : "Start Game"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
