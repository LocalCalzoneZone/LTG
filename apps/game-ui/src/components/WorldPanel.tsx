import { useEffect, useState } from "react";
import { fetchWorld, saveWorldEntry, saveWorldRegion } from "../lib/api";
import type { WorldEntry, WorldOverview } from "../lib/types";
import { IconX } from "./Icons";

const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch disabled:cursor-not-allowed disabled:opacity-40";
const GHOST_BTN =
  "caps-label flex items-center gap-1.5 border border-line2 px-3 py-1.5 text-[9px] tracking-[0.16em] " +
  "text-brass transition hover:border-brass hover:text-brass-hi disabled:cursor-not-allowed disabled:opacity-40";
const FIELD =
  "border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-aether/70 focus:outline-none";

/** Options → World (Update 24 §D24-8.3): the worldbook — regions with their
 * towns, each entry editable (gist, notable, neighbours, region), a warning
 * row for towns without a page. Brief on purpose: what a traveller knows,
 * never what happened (that is the campaign's). */
export function WorldPanel() {
  const [world, setWorld] = useState<WorldOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [editing, setEditing] = useState<WorldEntry | null>(null);
  const [regionEdit, setRegionEdit] = useState<{ id: string; name: string; gist: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setWorld(await fetchWorld());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => { void refresh(); }, []);

  const saveEntry = async () => {
    if (!editing) return;
    setBusy(true); setErr(null); setNote(null);
    try {
      await saveWorldEntry(editing.town_id, {
        name: editing.name, region_id: editing.region_id, gist: editing.gist,
        notable: editing.notable, neighbours: editing.neighbours,
      });
      setNote(`Saved ${editing.name}`);
      setEditing(null);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const saveRegion = async () => {
    if (!regionEdit) return;
    setBusy(true); setErr(null); setNote(null);
    try {
      await saveWorldRegion(regionEdit.id, regionEdit.name, regionEdit.gist);
      setNote(`Saved ${regionEdit.name}`);
      setRegionEdit(null);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const allTowns = world?.towns ?? [];
  const regions = world?.regions ?? [];

  if (editing) {
    const e = editing;
    return (
      <div className="flex min-h-0 flex-col">
        <div className="mb-3 flex items-center gap-3">
          <button className={SMALL_BTN} onClick={() => setEditing(null)}>Back</button>
          <span className="caps-label text-[11px] tracking-[0.2em] text-brass">{e.name}</span>
          <span className="text-[10px] font-light text-dimmed">[{e.town_id}]</span>
          <span className="h-px flex-1 bg-line" />
          <button className={GHOST_BTN} onClick={saveEntry} disabled={busy}>Save page</button>
        </div>
        {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
        <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          <label className="flex flex-col gap-1">
            <span className="caps-label text-[9px] tracking-[0.16em] text-mist">Region</span>
            <select value={e.region_id} onChange={(ev) => setEditing({ ...e, region_id: ev.target.value })} className={FIELD}>
              {regions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              {!regions.some((r) => r.id === e.region_id) && <option value={e.region_id}>{e.region_id}</option>}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="caps-label text-[9px] tracking-[0.16em] text-mist">Gist — one paragraph, what a traveller knows</span>
            <textarea value={e.gist} onChange={(ev) => setEditing({ ...e, gist: ev.target.value })} rows={4} className={FIELD} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="caps-label text-[9px] tracking-[0.16em] text-mist">Notable — one per line</span>
            <textarea value={e.notable.join("\n")} rows={4} className={FIELD}
                      onChange={(ev) => setEditing({ ...e, notable: ev.target.value.split("\n") })} />
          </label>
          <div className="flex flex-col gap-1">
            <span className="caps-label text-[9px] tracking-[0.16em] text-mist">Neighbours — the road between (edges are mirrored on save)</span>
            {e.neighbours.map((n, i) => (
              <div key={i} className="flex items-center gap-2">
                <select value={n.town_id} className={`${FIELD} w-48`}
                        onChange={(ev) => setEditing({ ...e, neighbours: e.neighbours.map((x, j) => (j === i ? { ...x, town_id: ev.target.value } : x)) })}>
                  {allTowns.filter((t) => t.town_id !== e.town_id).map((t) => <option key={t.town_id} value={t.town_id}>{t.name}</option>)}
                </select>
                <input value={n.how} placeholder="three days north by the Greatway" className={`${FIELD} flex-1`}
                       onChange={(ev) => setEditing({ ...e, neighbours: e.neighbours.map((x, j) => (j === i ? { ...x, how: ev.target.value } : x)) })} />
                <button className={SMALL_BTN} onClick={() => setEditing({ ...e, neighbours: e.neighbours.filter((_, j) => j !== i) })}><IconX size={10} /></button>
              </div>
            ))}
            <button className={`${SMALL_BTN} self-start`}
                    disabled={!allTowns.some((t) => t.town_id !== e.town_id)}
                    onClick={() => {
                      const first = allTowns.find((t) => t.town_id !== e.town_id && !e.neighbours.some((n) => n.town_id === t.town_id));
                      if (first) setEditing({ ...e, neighbours: [...e.neighbours, { town_id: first.town_id, how: "" }] });
                    }}>
              Add neighbour
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-3 border border-line bg-black/25 p-3">
        <span className="text-xs font-light text-mist">
          The worldbook: one page per town, what a traveller knows — read by every campaign, appended by every town generated. What happened somewhere lives on the campaign, not here.
        </span>
        {note && <span className="text-xs text-vigor">{note}</span>}
        {err && <span className="text-xs text-blood">{err}</span>}
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
        {world === null && <div className="text-xs font-light text-dimmed">Loading…</div>}
        {world && regions.length === 0 && world.missing.length === 0 && (
          <div className="px-1 py-2 text-xs font-light text-dimmed">The book is empty — generate a town in Options → Towns and it writes its own page.</div>
        )}
        {regions.map((r) => (
          <div key={r.id} className="mb-3 border border-line bg-white/[0.02]">
            <div className="flex items-start gap-3 border-b border-line p-3">
              <div className="min-w-0 flex-1">
                <div className="caps-label text-[11px] tracking-[0.2em] text-brass">{r.name}</div>
                {regionEdit?.id === r.id ? (
                  <div className="mt-1 flex flex-col gap-1">
                    <input value={regionEdit.name} onChange={(e) => setRegionEdit({ ...regionEdit, name: e.target.value })} className={FIELD} />
                    <textarea value={regionEdit.gist} onChange={(e) => setRegionEdit({ ...regionEdit, gist: e.target.value })} rows={3} className={FIELD} />
                    <div className="flex gap-2">
                      <button className={GHOST_BTN} onClick={saveRegion} disabled={busy}>Save region</button>
                      <button className={SMALL_BTN} onClick={() => setRegionEdit(null)}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-0.5 text-xs font-light text-mist">{r.gist || <span className="italic text-dimmed">(unwritten)</span>}</div>
                )}
              </div>
              {regionEdit?.id !== r.id && (
                <button className={SMALL_BTN} onClick={() => setRegionEdit({ id: r.id, name: r.name, gist: r.gist })}>Edit</button>
              )}
            </div>
            {r.towns.map((t) => (
              <div key={t.town_id} className="flex items-start gap-3 border-b border-line/50 px-3 py-2 last:border-b-0">
                <div className="min-w-0 flex-1">
                  <div className="caps-label text-[11px] tracking-[0.14em] text-parch">{t.name}</div>
                  <div className="text-xs font-light text-mist">{t.gist}</div>
                  <div className="mt-0.5 text-[10px] font-light text-dimmed">
                    {t.notable.length ? `Known for: ${t.notable.join("; ")}` : ""}
                    {t.neighbours.length ? ` · Neighbours: ${t.neighbours.map((n) => `${allTowns.find((x) => x.town_id === n.town_id)?.name ?? n.town_id}${n.how ? ` (${n.how})` : ""}`).join(", ")}` : " · no neighbours yet"}
                  </div>
                </div>
                <button className={SMALL_BTN} onClick={() => setEditing({ ...t, notable: [...t.notable], neighbours: t.neighbours.map((n) => ({ ...n })) })}>Edit</button>
              </div>
            ))}
            {r.towns.length === 0 && <div className="px-3 py-2 text-[11px] font-light italic text-dimmed">No towns in this region yet.</div>}
          </div>
        ))}
        {world && world.missing.length > 0 && (
          <div className="border border-brass/40 bg-brass/5 p-3">
            <div className="caps-label text-[10px] tracking-[0.2em] text-brass">Towns without a page</div>
            <div className="mt-1 text-[11px] font-light text-mist">
              The writers get no neighbours for these. Write a page by hand, or run <span className="text-parch">scripts/backfill_worldbook.py</span> once.
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {world.missing.map((m) => (
                <button key={m.id} className={SMALL_BTN}
                        onClick={() => setEditing({ town_id: m.id, name: m.name, region_id: regions[0]?.id ?? "", gist: "", notable: [], neighbours: [] })}>
                  {m.name} — write its page
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
