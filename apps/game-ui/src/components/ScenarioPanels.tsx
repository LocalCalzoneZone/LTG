import { useEffect, useState } from "react";
import {
  deleteScenario,
  deleteTown,
  fetchScenario,
  fetchScenarios,
  fetchTown,
  fetchTowns,
  generateScenario,
  generateTown,
  generateTownArt,
} from "../lib/api";
import type { ScenarioDetail, ScenarioOption, TownDetail, TownOption } from "../lib/types";
import { ArtQueueButton } from "./ArtQueueButton";
import { DifficultyTag } from "./DifficultyTag";
import { IconCanvas, IconSigil, IconX } from "./Icons";

const GHOST_BTN =
  "caps-label flex items-center gap-1.5 border border-line2 px-3 py-1.5 text-[9px] tracking-[0.16em] " +
  "text-brass transition hover:border-brass hover:text-brass-hi disabled:cursor-not-allowed disabled:opacity-40";
const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch disabled:cursor-not-allowed disabled:opacity-40";
const DANGER_BTN =
  "caps-label border border-blood/60 bg-blood/15 px-2.5 py-1 text-[9px] tracking-[0.14em] text-blood transition " +
  "hover:bg-blood hover:text-parch";
const FIELD =
  "border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-aether/70 focus:outline-none";

/** Options → Towns (Update 17 §D17-5.1): the pre-generated stages. Generate /
 * inspect (locations + NPCs, per-item art) / Generate all missing / delete. */
export function TownsPanel() {
  const [towns, setTowns] = useState<TownOption[] | null>(null);
  const [open, setOpen] = useState<TownDetail | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  const refresh = async (keep?: string) => {
    try {
      setTowns(await fetchTowns());
      if (keep) setOpen(await fetchTown(keep));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const gen = async () => {
    setBusy(true); setErr(null);
    try {
      const meta = await generateTown(note);
      await refresh(meta.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const paint = async (kind: "town" | "location" | "npc", targetId?: string) => {
    if (!open) return;
    setBusy(true); setErr(null);
    try {
      await generateTownArt(open.id, kind, targetId);
      setOpen(await fetchTown(open.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  if (open) {
    return (
      <div className="flex min-h-0 flex-col">
        <div className="mb-3 flex items-center gap-3">
          <button className={SMALL_BTN} onClick={() => setOpen(null)}>← Towns</button>
          <span className="caps-label text-[12px] tracking-[0.2em] text-brass">{open.name}</span>
          <span className="text-xs font-light italic text-mist">{open.region_flavor}</span>
          <span className="h-px flex-1 bg-line" />
          <ArtQueueButton target={{ townId: open.id }} subject="the town, every location and NPC"
                          onImage={() => fetchTown(open.id).then(setOpen).catch(() => {})} />
        </div>
        {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
          <div className="mb-3 flex gap-3 border border-line bg-black/25 p-3">
            <div className="h-24 w-40 shrink-0 border border-line bg-ink-0">
              {open.art_url ? <img src={open.art_url} alt="" className="h-full w-full object-cover" />
                : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={20} /></div>}
            </div>
            <div className="min-w-0 flex-1">
              <div className="caps-label text-[10px] tracking-[0.2em] text-mist">Town map</div>
              <p className="mt-1 text-xs font-light text-parch">{open.scene}</p>
              <button className={`${GHOST_BTN} mt-2`} onClick={() => paint("town")} disabled={busy}>
                <IconCanvas size={10} /> {open.art_url ? "Repaint" : "Paint"} the map
              </button>
            </div>
          </div>
          {open.locations.map((l) => (
            <div key={l.id} className="mb-2 border border-line bg-black/25 p-3">
              <div className="flex gap-3">
                <div className="h-20 w-32 shrink-0 border border-line bg-ink-0">
                  {l.art_url ? <img src={l.art_url} alt="" className="h-full w-full object-cover" />
                    : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={18} /></div>}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="caps-label text-[11px] tracking-[0.14em] text-parch">{l.name}</span>
                    <span className="caps-label text-[9px] tracking-[0.14em] text-brass">{l.function.replace(/_/g, " ")}</span>
                    <span className="h-px flex-1 bg-line" />
                    <button className={SMALL_BTN} onClick={() => paint("location", l.id)} disabled={busy}>
                      {l.art_url ? "Repaint" : "Paint"}
                    </button>
                  </div>
                  <p className="mt-1 text-xs font-light text-mist">{l.description}</p>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 pl-[140px]">
                {l.npcs.map((n) => (
                  <div key={n.id} className="flex w-[260px] gap-2 border border-line/60 p-2">
                    <div className="h-14 w-14 shrink-0 border border-line bg-ink-0">
                      {n.art_url ? <img src={n.art_url} alt="" className="h-full w-full object-cover object-top" />
                        : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={14} /></div>}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="caps-label truncate text-[10px] tracking-[0.12em] text-parch">{n.name}</div>
                      <div className="truncate text-[10px] font-light italic text-mist">{n.role}</div>
                      <button className={`${SMALL_BTN} mt-1`} onClick={() => paint("npc", n.id)} disabled={busy}>
                        {n.art_url ? "Repaint" : "Paint"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2 border border-line bg-black/25 p-3">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note, e.g. “a bell-foundry town under a glacier”"
               className={`${FIELD} min-w-[280px] flex-1`} />
        <button className={GHOST_BTN} onClick={gen} disabled={busy}>{busy ? "Generating…" : "Generate town"}</button>
      </div>
      {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
        {towns?.length === 0 && <div className="px-1 py-2 text-xs font-light text-dimmed">No towns yet — generate one above.</div>}
        {towns?.map((t) => (
          <div key={t.id} className="mb-1.5 flex items-center gap-3 border border-line bg-white/[0.02] p-2">
            <div className="h-12 w-20 shrink-0 border border-line bg-ink-0">
              {t.art_url ? <img src={t.art_url} alt="" className="h-full w-full object-cover" />
                : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={14} /></div>}
            </div>
            <div className="min-w-0 flex-1">
              <div className="caps-label text-[11px] tracking-[0.14em] text-parch">{t.name}</div>
              <div className="truncate text-xs font-light text-mist">{t.region_flavor}</div>
              <div className="text-[10px] font-light text-dimmed">{t.location_count} locations · {t.npc_count} NPCs{t.art_missing ? ` · ${t.art_missing} images missing` : ""}</div>
            </div>
            <button className={SMALL_BTN} onClick={() => fetchTown(t.id).then(setOpen)}>Open</button>
            {confirmDel === t.id ? (
              <>
                <button className={DANGER_BTN} onClick={async () => { await deleteTown(t.id); setConfirmDel(null); refresh(); }}>Delete</button>
                <button className={SMALL_BTN} onClick={() => setConfirmDel(null)}>Keep</button>
              </>
            ) : (
              <button className={SMALL_BTN} onClick={() => setConfirmDel(t.id)} title="Delete this town"><IconX size={10} /></button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Options → Scenarios (§D17-6.1): pre-generated scenarios (arc + Act I) for a
 * town — Generate / inspect the arc / open Act I's adventure / delete. */
export function ScenariosPanel({ onEditAdventure }: { onEditAdventure?: (adventureId: string) => void }) {
  const [scenarios, setScenarios] = useState<ScenarioOption[] | null>(null);
  const [towns, setTowns] = useState<TownOption[]>([]);
  const [townId, setTownId] = useState("");
  const [difficulty, setDifficulty] = useState("standard");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<ScenarioDetail | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [s, t] = await Promise.all([fetchScenarios(), fetchTowns()]);
      setScenarios(s); setTowns(t);
      if (!townId && t[0]) setTownId(t[0].id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const gen = async () => {
    if (!townId) return;
    setBusy(true); setErr(null);
    try {
      await generateScenario(townId, difficulty, note);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  if (open) {
    return (
      <div className="flex min-h-0 flex-col">
        <div className="mb-3 flex items-center gap-3">
          <button className={SMALL_BTN} onClick={() => setOpen(null)}>← Scenarios</button>
          <span className="caps-label text-[12px] tracking-[0.2em] text-brass">{open.arc.title}</span>
          <span className="text-xs font-light italic text-mist">{open.town_name}</span>
          <DifficultyTag difficulty={open.difficulty} />
          <span className="h-px flex-1 bg-line" />
          {onEditAdventure && (
            <button className={GHOST_BTN} onClick={() => onEditAdventure(open.act1.adventure_id)}>Open Act I's adventure</button>
          )}
        </div>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1 text-sm font-light">
          <div className="mb-3 border border-line bg-black/25 p-3">
            <div className="caps-label text-[10px] tracking-[0.2em] text-mist">Villain</div>
            <p className="text-parch">{open.arc.villain}</p>
            <div className="caps-label mt-2 text-[10px] tracking-[0.2em] text-mist">Stakes</div>
            <p className="text-parch">{open.arc.stakes}</p>
          </div>
          {open.arc.acts.map((a, i) => (
            <div key={i} className="mb-2 border border-line bg-black/25 p-3">
              <div className="caps-label text-[11px] tracking-[0.14em] text-parch">Act {["I", "II", "III"][i]} — {a.title}</div>
              <p className="mt-1 text-xs text-mist">{a.hook}</p>
              <p className="mt-1 text-[11px] text-dimmed">Questgiver {a.questgiver_npc}{a.handoff ? ` · handoff ${a.handoff}` : ""} · {a.adventure_theme} · {a.tone_notes}</p>
              {i === 0 && open.act1.materialization?.quest && (
                <p className="mt-2 text-xs text-parch">Quest: <span className="text-brass">{open.act1.materialization.quest.title}</span> — {open.act1.materialization.quest.text}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2 border border-line bg-black/25 p-3">
        <select value={townId} onChange={(e) => setTownId(e.target.value)} className={FIELD}>
          {towns.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className={FIELD}>
          {["easy", "standard", "hard"].map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note for the arc"
               className={`${FIELD} min-w-[220px] flex-1`} />
        <button className={GHOST_BTN} onClick={gen} disabled={busy || !townId}>
          {busy ? "Generating (arc, Act I, adventure — minutes)…" : "Generate scenario"}
        </button>
      </div>
      {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
        {scenarios?.length === 0 && (
          <div className="px-1 py-2 text-xs font-light text-dimmed">
            No pre-generated scenarios yet. Generate one for a town above (New Game can also start Town + New).
          </div>
        )}
        {scenarios?.map((s) => (
          <div key={s.id} className="mb-1.5 flex items-center gap-3 border border-line bg-white/[0.02] p-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="caps-label text-[11px] tracking-[0.14em] text-parch">{s.title}</span>
                <DifficultyTag difficulty={s.difficulty} />
                <span className="caps-label text-[9px] tracking-[0.12em] text-brass">{s.town_name}</span>
              </div>
              <div className="truncate text-xs font-light italic text-mist">{s.villain}</div>
              <div className="text-[10px] font-light text-dimmed">{s.act_titles.join(" · ")}</div>
            </div>
            <button className={SMALL_BTN} onClick={() => fetchScenario(s.id).then(setOpen)}>Open</button>
            {confirmDel === s.id ? (
              <>
                <button className={DANGER_BTN} onClick={async () => { await deleteScenario(s.id); setConfirmDel(null); refresh(); }}>Delete</button>
                <button className={SMALL_BTN} onClick={() => setConfirmDel(null)}>Keep</button>
              </>
            ) : (
              <button className={SMALL_BTN} onClick={() => setConfirmDel(s.id)} title="Delete this scenario"><IconX size={10} /></button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
