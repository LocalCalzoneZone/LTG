import { useEffect, useState } from "react";
import {
  deleteRun,
  deleteSave,
  fetchRun,
  fetchRuns,
  loadSave,
  type RunDetail,
  type RunSummary,
} from "../lib/api";
import { IconSigil, IconX } from "./Icons";

const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch disabled:cursor-not-allowed disabled:opacity-40";
const DANGER_BTN =
  "caps-label border border-blood/60 bg-blood/15 px-2.5 py-1 text-[9px] tracking-[0.14em] text-blood transition " +
  "hover:bg-blood hover:text-parch";

function when(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function optionsLabel(o: RunSummary["options"]): string {
  const parts = [o.difficulty, o.hardcore ? "Hardcore" : "Normal", o.everquest ? "Everquest" : "Standard"];
  return parts.join(" · ");
}

/** Load Game (Update 17 §D17-3 / §D17-7): runs → the run's saves (oldest →
 * newest, each loadable / deletable) → load. Loading an older save and
 * continuing appends new rows — a fork; nothing is ever pruned. A whole run
 * can be deleted (double-confirm). */
export function LoadGameModal({ onClose, onStarted }: {
  onClose: () => void;
  onStarted: (sessionId: string) => void;
}) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selected, setSelected] = useState<RunDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmSave, setConfirmSave] = useState<string | null>(null);
  const [confirmRun, setConfirmRun] = useState<0 | 1 | 2>(0);

  const refresh = async (keepRun?: string) => {
    try {
      const list = await fetchRuns();
      setRuns(list);
      if (keepRun && list.some((r) => r.run_id === keepRun)) {
        setSelected(await fetchRun(keepRun));
      } else if (keepRun) {
        setSelected(null);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const open = async (r: RunSummary) => {
    setErr(null);
    setConfirmRun(0);
    setConfirmSave(null);
    try {
      setSelected(await fetchRun(r.run_id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const doLoad = async (saveId: string) => {
    if (!selected) return;
    setBusy(true);
    setErr(null);
    try {
      onStarted(await loadSave(selected.run_id, saveId));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const doDeleteSave = async (saveId: string) => {
    if (!selected) return;
    setBusy(true);
    try {
      await deleteSave(selected.run_id, saveId);
      setConfirmSave(null);
      await refresh(selected.run_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const doDeleteRun = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await deleteRun(selected.run_id);
      setSelected(null);
      setConfirmRun(0);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-[2px]" onClick={onClose}>
      <div
        className="panel-ticks flex max-h-[85vh] w-[min(94vw,980px)] flex-col border border-line2 bg-ink-2 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center gap-3">
          <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">Load Game</h2>
          <span className="h-px flex-1 bg-line" />
          <button onClick={onClose} className="text-mist hover:text-parch" title="Close">
            <IconX size={14} />
          </button>
        </div>

        {err && (
          <div className="mb-3 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>
        )}

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-5">
          {/* Runs */}
          <section className="flex min-h-0 flex-col">
            <div className="caps-label mb-2 text-[10px] tracking-[0.25em] text-brass">Runs</div>
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              {runs === null && <div className="text-xs font-light text-dimmed">Loading…</div>}
              {runs !== null && runs.length === 0 && (
                <div className="px-1 py-2 text-xs font-light text-dimmed">
                  No runs yet. Start an adventure from New Game with “Save as a run” to begin one.
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                {runs?.map((r) => {
                  const on = selected?.run_id === r.run_id;
                  return (
                    <button
                      key={r.run_id}
                      onClick={() => open(r)}
                      className={`flex flex-col gap-1 border p-2 text-left transition ${
                        on ? "border-brass bg-brass/10" : "border-line bg-white/[0.02] hover:border-line2"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex -space-x-1">
                          {r.party.slice(0, 4).map((p) =>
                            p.portrait ? (
                              <img key={p.id} src={p.portrait} alt={p.name} title={p.name}
                                   className="h-7 w-7 border border-line object-cover object-top" />
                            ) : (
                              <span key={p.id} title={p.name}
                                    className="flex h-7 w-7 items-center justify-center border border-line bg-ink-0 text-dimmed">
                                <IconSigil size={14} />
                              </span>
                            ),
                          )}
                        </span>
                        <span className={`caps-label truncate text-[11px] tracking-[0.1em] ${
                          r.dead ? "text-dimmed line-through" : "text-parch"}`}>
                          {r.name}
                        </span>
                        {r.dead && (
                          <span className="caps-label ml-auto shrink-0 text-[9px] tracking-[0.14em] text-blood">Fallen</span>
                        )}
                      </div>
                      <div className="text-[11px] font-light text-mist">
                        {r.party.map((p) => p.name).join(", ")}
                      </div>
                      <div className="flex justify-between gap-2 text-[10px] font-light text-dimmed">
                        <span className="truncate">{r.latest_label || optionsLabel(r.options)}</span>
                        <span className="shrink-0">{when(r.updated_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>

          {/* Saves */}
          <section className="flex min-h-0 flex-col">
            <div className="mb-2 flex items-center gap-3">
              <span className="caps-label text-[10px] tracking-[0.25em] text-brass">Saves</span>
              {selected && (
                <span className="text-[10px] font-light text-dimmed">{optionsLabel(selected.options)}</span>
              )}
              <span className="h-px flex-1 bg-line" />
              {selected && confirmRun === 0 && (
                <button className={SMALL_BTN} onClick={() => setConfirmRun(1)} disabled={busy}>Delete run</button>
              )}
              {selected && confirmRun === 1 && (
                <>
                  <span className="text-[10px] font-light text-mist">Delete the whole run and every save?</span>
                  <button className={DANGER_BTN} onClick={() => setConfirmRun(2)}>Yes</button>
                  <button className={SMALL_BTN} onClick={() => setConfirmRun(0)}>No</button>
                </>
              )}
              {selected && confirmRun === 2 && (
                <>
                  <span className="text-[10px] font-light text-blood">This cannot be undone.</span>
                  <button className={DANGER_BTN} onClick={doDeleteRun} disabled={busy}>Delete for good</button>
                  <button className={SMALL_BTN} onClick={() => setConfirmRun(0)}>Keep</button>
                </>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              {!selected && (
                <div className="px-1 py-2 text-xs font-light text-dimmed">Select a run to see its saves.</div>
              )}
              {selected && selected.saves.length === 0 && (
                <div className="px-1 py-2 text-xs font-light text-dimmed">This run has no saves left.</div>
              )}
              <div className="flex flex-col gap-1">
                {selected?.saves.map((s, i) => (
                  <div key={s.save_id}
                       className="flex items-center gap-3 border border-line bg-white/[0.02] px-2 py-1.5">
                    <span className="w-6 shrink-0 text-right text-[10px] font-light text-dimmed">{i + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] font-light text-parch">{s.label}</span>
                      <span className="block text-[10px] font-light text-dimmed">
                        {when(s.saved_at)}{s.auto ? " · auto" : " · manual"}
                      </span>
                    </span>
                    {confirmSave === s.save_id ? (
                      <>
                        <span className="text-[10px] font-light text-mist">Delete this save?</span>
                        <button className={DANGER_BTN} onClick={() => doDeleteSave(s.save_id)} disabled={busy}>Delete</button>
                        <button className={SMALL_BTN} onClick={() => setConfirmSave(null)}>Keep</button>
                      </>
                    ) : (
                      <>
                        <button className={SMALL_BTN} onClick={() => setConfirmSave(s.save_id)} disabled={busy}>Delete</button>
                        <button
                          className="caps-label border border-brass/70 bg-brass/10 px-3 py-1 text-[9px] tracking-[0.16em] text-brass transition hover:bg-brass hover:text-ink-0 disabled:cursor-not-allowed disabled:opacity-40"
                          onClick={() => doLoad(s.save_id)}
                          disabled={busy || selected.dead}
                          title={selected.dead ? "A fallen Hardcore run can be viewed, not continued" : "Load this save (continuing forks from here)"}
                        >
                          {busy ? "…" : "Load"}
                        </button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
            {selected && selected.saves.length > 0 && (
              <div className="mt-2 text-[10px] font-light text-dimmed">
                Loading an older save and playing on branches from it — new saves append; nothing here is ever overwritten.
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
