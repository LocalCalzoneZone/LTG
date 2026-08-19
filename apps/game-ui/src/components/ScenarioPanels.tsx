import { useEffect, useState } from "react";
import {
  deleteItem,
  deleteScenario,
  deleteTown,
  fetchItem,
  fetchItems,
  fetchScenario,
  fetchScenarios,
  fetchTown,
  fetchTowns,
  generateItemArt,
  generateScenario,
  generateTown,
  generateTownArt,
  saveItem,
  saveTown,
  type TownArtKind,
} from "../lib/api";
import type { ItemMeta, ItemView, ScenarioDetail, ScenarioOption, TownDetail, TownOption } from "../lib/types";
import { ArtQueueButton } from "./ArtQueueButton";
import { ItemCard } from "./Items";
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

  const paint = async (kind: TownArtKind, targetId?: string) => {
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
      <TownEditor
        town={open}
        busy={busy}
        err={err}
        onBack={() => setOpen(null)}
        onChange={setOpen}
        onPaint={paint}
        onSave={async () => {
          setBusy(true); setErr(null);
          try {
            const { id, ...body } = open;
            await saveTown(body as unknown as Record<string, unknown>, id);
            setOpen(await fetchTown(id));
            await refresh();
          } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
          } finally { setBusy(false); }
        }}
      />
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

// --------------------------------------------------------------------------- //
// Options → Equipment (§D17-4.3): the base catalogue + user items — list, New /
// edit (a compact item editor: statics for gear, effects JSON for consumables),
// per-item art, Generate all missing.
// --------------------------------------------------------------------------- //

const STATIC_KINDS = ["attack_mode", "power_bonus", "keyword", "stat", "ability"] as const;

type Draft = {
  id?: string; name: string; slot: "weapon" | "accessory" | "consumable"; rarity: string;
  level_min: number; points_price: number; flavor: string; art_desc: string;
  statics: { kind: string; mode?: string; amount?: number; keyword?: string; stat?: string; card?: string }[];
  effects_json: string; timing: "instant" | "sorcery";
};

function emptyDraft(): Draft {
  return { name: "", slot: "weapon", rarity: "common", level_min: 1, points_price: 0, flavor: "", art_desc: "",
           statics: [{ kind: "attack_mode", mode: "melee" }], effects_json: "[]", timing: "instant" };
}

function draftFromItem(it: ItemView): Draft {
  return {
    id: it.id, name: it.name, slot: it.slot, rarity: it.rarity, level_min: it.level_min,
    points_price: it.points_price, flavor: it.flavor, art_desc: it.art_desc,
    statics: ((it.statics ?? []) as Draft["statics"]).map((s) => ({
      ...s, card: s.card ? JSON.stringify(s.card) : undefined,
    })),
    effects_json: JSON.stringify(it.effects ?? [], null, 1),
    timing: it.consumable?.timing ?? "instant",
  };
}

export function EquipmentPanel() {
  const [list, setList] = useState<ItemMeta[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "weapon" | "accessory" | "consumable">("all");

  const refresh = async () => {
    try { setList(await fetchItems()); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  useEffect(() => { void refresh(); }, []);

  const save = async () => {
    if (!draft) return;
    setBusy(true); setErr(null);
    try {
      const body: Record<string, unknown> = {
        name: draft.name, slot: draft.slot, rarity: draft.rarity, level_min: draft.level_min,
        points_price: draft.points_price, flavor: draft.flavor, art_desc: draft.art_desc,
      };
      if (draft.slot === "consumable") {
        body.effects = JSON.parse(draft.effects_json || "[]");
        body.consumable = { timing: draft.timing };
      } else {
        body.statics = draft.statics.map((s) => {
          const out: Record<string, unknown> = { kind: s.kind };
          if (s.kind === "attack_mode") out.mode = s.mode ?? "melee";
          if (s.kind === "power_bonus" || s.kind === "stat") out.amount = Number(s.amount ?? 1);
          if (s.kind === "stat") out.stat = s.stat ?? "hp";
          if (s.kind === "keyword") out.keyword = s.keyword ?? "reach";
          if (s.kind === "ability") out.card = JSON.parse(s.card || "{}");
          return out;
        });
      }
      await saveItem(body, draft.id);
      setDraft(null);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const paint = async (id: string) => {
    setBusy(true); setErr(null);
    try { await generateItemArt(id); await refresh(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  if (draft) {
    const d = draft;
    const set = (patch: Partial<Draft>) => setDraft({ ...d, ...patch });
    return (
      <div className="flex min-h-0 flex-col">
        <div className="mb-3 flex items-center gap-3">
          <button className={SMALL_BTN} onClick={() => setDraft(null)}>← Equipment</button>
          <span className="caps-label text-[12px] tracking-[0.2em] text-brass">{d.id ? "Edit item" : "New item"}</span>
          <span className="h-px flex-1 bg-line" />
          <button className={GHOST_BTN} onClick={save} disabled={busy || !d.name}>{busy ? "Saving…" : "Save item"}</button>
        </div>
        {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
        <div className="scroll-thin grid min-h-0 flex-1 grid-cols-2 gap-x-4 gap-y-2 overflow-y-auto pr-1 text-sm">
          <label className="flex flex-col gap-1 text-[10px] text-mist">Name<input value={d.name} onChange={(e) => set({ name: e.target.value })} className={FIELD} /></label>
          <label className="flex flex-col gap-1 text-[10px] text-mist">Slot
            <select value={d.slot} onChange={(e) => set({ slot: e.target.value as Draft["slot"] })} className={FIELD}>
              {["weapon", "accessory", "consumable"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
          <label className="flex flex-col gap-1 text-[10px] text-mist">Rarity
            <select value={d.rarity} onChange={(e) => set({ rarity: e.target.value })} className={FIELD}>
              {["common", "uncommon", "rare", "mythic"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
          <div className="flex gap-3">
            <label className="flex flex-1 flex-col gap-1 text-[10px] text-mist">Level min<input type="number" min={1} value={d.level_min} onChange={(e) => set({ level_min: Number(e.target.value) })} className={FIELD} /></label>
            <label className="flex flex-1 flex-col gap-1 text-[10px] text-mist">Points price<input type="number" min={0} value={d.points_price} onChange={(e) => set({ points_price: Number(e.target.value) })} className={FIELD} /></label>
          </div>
          <label className="col-span-2 flex flex-col gap-1 text-[10px] text-mist">Flavour (one line)<input value={d.flavor} onChange={(e) => set({ flavor: e.target.value })} className={FIELD} /></label>
          <label className="col-span-2 flex flex-col gap-1 text-[10px] text-mist">Art description<textarea rows={2} value={d.art_desc} onChange={(e) => set({ art_desc: e.target.value })} className={FIELD} /></label>
          {d.slot === "consumable" ? (
            <>
              <label className="flex flex-col gap-1 text-[10px] text-mist">Timing
                <select value={d.timing} onChange={(e) => set({ timing: e.target.value as Draft["timing"] })} className={FIELD}>
                  <option value="instant">instant</option><option value="sorcery">sorcery</option>
                </select></label>
              <label className="col-span-2 flex flex-col gap-1 text-[10px] text-mist">Effects (card vocabulary, JSON list)
                <textarea rows={6} value={d.effects_json} onChange={(e) => set({ effects_json: e.target.value })} className={`${FIELD} font-mono text-xs`} /></label>
            </>
          ) : (
            <div className="col-span-2 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="caps-label text-[10px] tracking-[0.2em] text-mist">Statics</span>
                <button className={SMALL_BTN} onClick={() => set({ statics: [...d.statics, { kind: "stat", stat: "hp", amount: 2 }] })}>+ static</button>
              </div>
              {d.statics.map((st, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 border border-line/60 p-2">
                  <select value={st.kind} onChange={(e) => { const s = [...d.statics]; s[i] = { kind: e.target.value }; set({ statics: s }); }} className={FIELD}>
                    {STATIC_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                  </select>
                  {st.kind === "attack_mode" && (
                    <select value={st.mode ?? "melee"} onChange={(e) => { const s = [...d.statics]; s[i] = { ...st, mode: e.target.value }; set({ statics: s }); }} className={FIELD}>
                      <option value="melee">melee</option><option value="ranged">ranged</option>
                    </select>
                  )}
                  {(st.kind === "power_bonus" || st.kind === "stat") && (
                    <input type="number" value={st.amount ?? 1} onChange={(e) => { const s = [...d.statics]; s[i] = { ...st, amount: Number(e.target.value) }; set({ statics: s }); }} className={`${FIELD} w-20`} />
                  )}
                  {st.kind === "stat" && (
                    <select value={st.stat ?? "hp"} onChange={(e) => { const s = [...d.statics]; s[i] = { ...st, stat: e.target.value }; set({ statics: s }); }} className={FIELD}>
                      <option value="hp">hp</option><option value="mana">mana</option><option value="cards">cards</option>
                    </select>
                  )}
                  {st.kind === "keyword" && (
                    <input value={st.keyword ?? ""} placeholder="reach / trample / hexproof …" onChange={(e) => { const s = [...d.statics]; s[i] = { ...st, keyword: e.target.value }; set({ statics: s }); }} className={FIELD} />
                  )}
                  {st.kind === "ability" && (
                    <textarea rows={3} value={st.card ?? ""} placeholder='card JSON, e.g. {"id":"sip","name":"Sip","source_name":"Sip","rarity":"common","level":1,"type":"Ability","timing":"instant","effects":[…]}'
                              onChange={(e) => { const s = [...d.statics]; s[i] = { ...st, card: e.target.value }; set({ statics: s }); }} className={`${FIELD} min-w-[320px] flex-1 font-mono text-xs`} />
                  )}
                  <button className={SMALL_BTN} onClick={() => set({ statics: d.statics.filter((_, j) => j !== i) })}><IconX size={9} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  const shown = (list ?? []).filter((m) => filter === "all" || m.slot === filter);
  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2 border border-line bg-black/25 p-3">
        {(["all", "weapon", "accessory", "consumable"] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)}
                  className={`caps-label border px-2 py-0.5 text-[9px] tracking-[0.14em] transition ${filter === f ? "border-brass text-brass" : "border-line text-mist hover:text-parch"}`}>
            {f}
          </button>
        ))}
        <span className="h-px flex-1 bg-line" />
        <ArtQueueButton target={{ items: true }} subject="every item without art" onImage={refresh} />
        <button className={GHOST_BTN} onClick={() => setDraft(emptyDraft())}>New item</button>
      </div>
      {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
      <div className="scroll-thin flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto pr-1">
        {shown.map((m) => (
          <ItemCard key={m.id} item={{ ...m, slot: m.slot as ItemView["slot"], rarity: m.rarity as ItemView["rarity"], art_desc: "" }}
                    footer={
                      <div className="mt-1 flex flex-wrap gap-1">
                        <button className={SMALL_BTN} onClick={() => fetchItem(m.id).then((it) => setDraft(draftFromItem(it)))}>Edit</button>
                        <button className={SMALL_BTN} onClick={() => paint(m.id)} disabled={busy}>{m.art_url ? "Repaint" : "Paint"}</button>
                        <button className={SMALL_BTN} onClick={async () => { await deleteItem(m.id); refresh(); }} title={m.source === "catalogue" ? "Hide this catalogue item" : "Delete"}><IconX size={9} /></button>
                      </div>
                    } />
        ))}
        {list && list.length === 0 && <div className="text-xs font-light text-dimmed">No items.</div>}
      </div>
    </div>
  );
}


const FUNCTIONS = ["inn", "weaponsmith", "artificer", "apothecary", "tavern", "shrine", "witch_hut",
                   "guard_post", "market", "docks", "library", "graveyard", "gate", "manor", "well",
                   "chapel", "stables", "flavor"];
const AREA = `${FIELD} w-full font-light`;

/** The town editor: every field editable in place — the town's name / region /
 * scene, each location's name / function / scene / description, each NPC's
 * name / role / persona / portrait description (1–2 NPCs per location) — and
 * Save re-validates server-side (§D17-5.1). Ids are kept so painted art stays
 * attached. */
function TownEditor({ town, busy, err, onBack, onChange, onPaint, onSave }: {
  town: TownDetail; busy: boolean; err: string | null;
  onBack: () => void; onChange: (t: TownDetail) => void;
  onPaint: (kind: TownArtKind, targetId?: string) => void;
  onSave: () => void;
}) {
  const set = (patch: Partial<TownDetail>) => onChange({ ...town, ...patch });
  const setLoc = (i: number, patch: Partial<TownDetail["locations"][number]>) =>
    set({ locations: town.locations.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const setNpc = (i: number, k: number, patch: Partial<TownDetail["locations"][number]["npcs"][number]>) =>
    setLoc(i, { npcs: town.locations[i].npcs.map((n, m) => (m === k ? { ...n, ...patch } : n)) });
  const addNpc = (i: number) => setLoc(i, {
    npcs: [...town.locations[i].npcs, { id: "", name: "New Resident", role: "", persona: "", portrait_desc: "", art_url: "" }],
  });
  const removeNpc = (i: number, k: number) => setLoc(i, { npcs: town.locations[i].npcs.filter((_, m) => m !== k) });
  const addLocation = () => set({
    locations: [...town.locations, { id: "", name: "New Place", function: "tavern", description: "",
                                     exterior_scene: "", exterior_art_url: "", interior_scene: "", interior_art_url: "",
                                     npcs: [{ id: "", name: "New Resident", role: "", persona: "", portrait_desc: "", art_url: "" }] }],
  });
  const removeLocation = (i: number) => set({ locations: town.locations.filter((_, j) => j !== i) });

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex items-center gap-3">
        <button className={SMALL_BTN} onClick={onBack}>← Towns</button>
        <input value={town.name} onChange={(e) => set({ name: e.target.value })}
               className={`${FIELD} caps-label w-[240px] tracking-[0.14em] text-brass`} />
        <input value={town.region_flavor} onChange={(e) => set({ region_flavor: e.target.value })}
               placeholder="Region flavour — one sentence on the land around it"
               className={`${FIELD} min-w-0 flex-1 italic`} />
        <ArtQueueButton target={{ townId: town.id }} subject="the town, every location and NPC"
                        onImage={() => fetchTown(town.id).then(onChange).catch(() => {})} />
        <button className={GHOST_BTN} onClick={onSave} disabled={busy}>{busy ? "Saving…" : "Save town"}</button>
      </div>
      {err && <div className="mb-2 border border-blood/50 bg-blood/10 px-3 py-2 text-sm font-light text-blood">{err}</div>}
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="mb-3 flex gap-3 border border-line bg-black/25 p-3">
          <div className="h-24 w-40 shrink-0 border border-line bg-ink-0">
            {town.art_url ? <img src={town.art_url} alt="" className="h-full w-full object-cover" />
              : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={20} /></div>}
          </div>
          <div className="min-w-0 flex-1">
            <div className="caps-label text-[10px] tracking-[0.2em] text-mist">Town map — scene</div>
            <textarea rows={2} value={town.scene} onChange={(e) => set({ scene: e.target.value })} className={`${AREA} mt-1 text-xs`} />
            <button className={`${GHOST_BTN} mt-2`} onClick={() => onPaint("town")} disabled={busy}>
              <IconCanvas size={10} /> {town.art_url ? "Repaint" : "Paint"} the map
            </button>
          </div>
        </div>
        {town.locations.map((l, i) => (
          <div key={l.id || `new-${i}`} className="mb-2 border border-line bg-black/25 p-3">
            <div className="flex gap-3">
              <div className="flex shrink-0 gap-2">
                <div className="flex flex-col items-center gap-1">
                  <div className="h-24 w-[72px] border border-line bg-ink-0" title="Exterior — the map card">
                    {l.exterior_art_url ? <img src={l.exterior_art_url} alt="" className="h-full w-full object-cover" />
                      : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={16} /></div>}
                  </div>
                  <button className={SMALL_BTN} onClick={() => onPaint("location_exterior", l.id)}
                          disabled={busy || !l.id || !l.exterior_scene} title={!l.id ? "Save first" : !l.exterior_scene ? "Write an exterior scene first" : "Paint the map card"}>
                    {l.exterior_art_url ? "Repaint" : "Paint"} ext.
                  </button>
                </div>
                <div className="flex flex-col items-center gap-1">
                  <div className="h-24 w-40 border border-line bg-ink-0" title="Interior — the backdrop inside">
                    {(l.interior_art_url || l.art_url) ? <img src={l.interior_art_url || l.art_url} alt="" className="h-full w-full object-cover" />
                      : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={18} /></div>}
                  </div>
                  <button className={SMALL_BTN} onClick={() => onPaint("location_interior", l.id)} disabled={busy || !l.id}
                          title={l.id ? "Paint the interior backdrop" : "Save first"}>
                    {(l.interior_art_url || l.art_url) ? "Repaint" : "Paint"} int.
                  </button>
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <input value={l.name} onChange={(e) => setLoc(i, { name: e.target.value })}
                         className={`${FIELD} caps-label w-[220px] tracking-[0.12em] text-parch`} />
                  <select value={l.function} onChange={(e) => setLoc(i, { function: e.target.value })}
                          className={`${FIELD} caps-label text-[10px] tracking-[0.12em] text-brass`}>
                    {FUNCTIONS.map((f) => <option key={f} value={f}>{f.replace(/_/g, " ")}</option>)}
                  </select>
                  <span className="h-px flex-1 bg-line" />
                  <button className={SMALL_BTN} onClick={() => removeLocation(i)} title="Remove this location"><IconX size={9} /></button>
                </div>
                <textarea rows={2} value={l.description} onChange={(e) => setLoc(i, { description: e.target.value })}
                          placeholder="Description — what the party reads when they consider visiting"
                          className={`${AREA} mt-1 text-xs`} />
                <textarea rows={2} value={l.exterior_scene} onChange={(e) => setLoc(i, { exterior_scene: e.target.value })}
                          placeholder="Exterior scene — the building's frontage from the street (paints the map card)"
                          className={`${AREA} mt-1 text-xs italic`} />
                <textarea rows={2} value={l.interior_scene || l.scene || ""} onChange={(e) => setLoc(i, { interior_scene: e.target.value })}
                          placeholder="Interior scene — only what a character standing inside sees (paints the backdrop)"
                          className={`${AREA} mt-1 text-xs italic`} />
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-2 pl-[140px]">
              {l.npcs.map((n, k) => (
                <div key={n.id || `new-${k}`} className="flex w-[420px] gap-2 border border-line/60 p-2">
                  <div className="flex w-16 shrink-0 flex-col gap-1">
                    <div className="h-16 w-16 border border-line bg-ink-0">
                      {n.art_url ? <img src={n.art_url} alt="" className="h-full w-full object-cover object-top" />
                        : <div className="flex h-full items-center justify-center text-dimmed"><IconSigil size={14} /></div>}
                    </div>
                    <button className={SMALL_BTN} onClick={() => onPaint("npc", n.id)} disabled={busy || !n.id}
                            title={n.id ? "" : "Save first"}>
                      {n.art_url ? "Repaint" : "Paint"}
                    </button>
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex items-center gap-1">
                      <input value={n.name} onChange={(e) => setNpc(i, k, { name: e.target.value })}
                             className={`${FIELD} caps-label min-w-0 flex-1 text-[10px] tracking-[0.12em] text-parch`} />
                      <input value={n.role} onChange={(e) => setNpc(i, k, { role: e.target.value })} placeholder="role"
                             className={`${FIELD} w-[120px] text-[10px] italic`} />
                      {l.npcs.length > 1 && (
                        <button className={SMALL_BTN} onClick={() => removeNpc(i, k)} title="Remove this NPC"><IconX size={9} /></button>
                      )}
                    </div>
                    <textarea rows={3} value={n.persona} onChange={(e) => setNpc(i, k, { persona: e.target.value })}
                              placeholder="Persona — prose: manner, voice, wants, a quirk (reused verbatim to write their dialogue)"
                              className={`${AREA} text-[11px]`} />
                    <textarea rows={2} value={n.portrait_desc} onChange={(e) => setNpc(i, k, { portrait_desc: e.target.value })}
                              placeholder="Portrait description — physical appearance for the painter"
                              className={`${AREA} text-[11px] italic`} />
                  </div>
                </div>
              ))}
              {l.npcs.length < 2 && (
                <button className={`${SMALL_BTN} self-start`} onClick={() => addNpc(i)}>+ NPC</button>
              )}
            </div>
          </div>
        ))}
        <button className={GHOST_BTN} onClick={addLocation}>+ Location</button>
        <div className="mt-2 text-[10px] font-light text-dimmed">
          A town needs one inn, weaponsmith, artificer, and apothecary, plus 1–3 other places; every location an interior scene and 1–2 residents with a persona and a portrait description. Save checks all of it.
        </div>
      </div>
    </div>
  );
}
