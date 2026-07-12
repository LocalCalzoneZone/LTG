import { useEffect, useRef, useState } from "react";
import {
  deleteCharacter,
  deleteEncounter,
  fetchEncounter,
  fetchSetupOptions,
  importCharacter,
} from "../lib/api";
import type { CharacterOption, EncounterDetail, EncounterOption } from "../lib/types";
import { AdventurePanel } from "./AdventurePanel";
import { EncounterEditor } from "./EncounterEditor";
import { LlmSettingsPanel } from "./LlmSettingsPanel";
import { ManaIcon } from "./Pips";
import { IconEdit, IconPlus, IconSigil, IconUpload, IconX } from "./Icons";

type Tab = "characters" | "encounters" | "adventures" | "llm";
const TAB_LABELS: Record<Tab, string> = {
  characters: "Characters",
  encounters: "Encounters",
  adventures: "Adventures",
  llm: "LLM",
};

const GHOST_BTN =
  "caps-label flex items-center gap-1.5 border border-line2 px-3 py-1.5 text-[9px] tracking-[0.16em] " +
  "text-brass transition hover:border-brass hover:text-brass-hi";
const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch";
const DANGER_BTN =
  "caps-label border border-blood/60 bg-blood/15 px-3 py-1 text-[9px] tracking-[0.14em] text-blood " +
  "transition hover:bg-blood hover:text-parch";

export function OptionsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("characters");
  const [chars, setChars] = useState<CharacterOption[]>([]);
  const [encounters, setEncounters] = useState<EncounterOption[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<string | null>(null); // card pending delete
  const [encConfirmId, setEncConfirmId] = useState<string | null>(null);
  // Encounter being authored: an EncounterDetail (edit), "new" (create), or null.
  const [editing, setEditing] = useState<EncounterDetail | "new" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () =>
    fetchSetupOptions()
      .then((o) => {
        setChars(o.characters);
        setEncounters(o.encounters);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
  }, []);

  const onFiles = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setErr(null);
    setNote(null);
    let imported = 0;
    for (const f of Array.from(files)) {
      try {
        const raw = JSON.parse(await f.text());
        const meta = await importCharacter(raw);
        imported++;
        setNote(`Imported ${meta.name}`);
      } catch (e) {
        setErr(`${f.name}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
    if (imported) await refresh();
    if (fileRef.current) fileRef.current.value = "";
  };

  const doDelete = async (c: CharacterOption) => {
    setErr(null);
    setNote(null);
    try {
      await deleteCharacter(c.id);
      setNote(`Removed ${c.name}`);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirmId(null);
    }
  };

  const doDeleteEncounter = async (e: EncounterOption) => {
    setErr(null);
    setNote(null);
    try {
      await deleteEncounter(e.id);
      setNote(`Removed ${e.name}`);
      await refresh();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setEncConfirmId(null);
    }
  };

  const openEditor = async (e: EncounterOption) => {
    setErr(null);
    try {
      setEditing(await fetchEncounter(e.id));
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    }
  };

  // Open the Deckbuilder app with this character loaded for editing. There its
  // export button becomes "Update Game Character", writing back to the repo so
  // the next New Game picks the changes up. The Deckbuilder serves on port 8000
  // by default (`ltg-deckbuilder`); override via localStorage if you run it
  // elsewhere: localStorage.setItem("ltg_deckbuilder_port", "8012").
  const editInDeckbuilder = (c: CharacterOption) => {
    const port = localStorage.getItem("ltg_deckbuilder_port") || "8000";
    window.open(
      `http://${location.hostname}:${port}/?edit=${encodeURIComponent(c.id)}`,
      "_blank",
    );
  };

  if (editing) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-[2px]" onClick={onClose}>
        <div
          className="panel-ticks flex max-h-[88vh] w-[min(94vw,900px)] flex-col border border-line2 bg-ink-2 p-5 shadow-2xl"
          onClick={(ev) => ev.stopPropagation()}
        >
          <div className="mb-4 flex items-center gap-3">
            <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">
              {editing === "new" ? "New Encounter" : "Edit Encounter"}
            </h2>
            <span className="h-px flex-1 bg-line" />
            <button onClick={() => setEditing(null)} className="text-mist hover:text-parch" title="Close">
              <IconX size={14} />
            </button>
          </div>
          <EncounterEditor
            initial={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onSaved={async () => {
              setEditing(null);
              setNote("Encounter saved");
              await refresh();
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-[2px]" onClick={onClose}>
      <div
        className="panel-ticks flex max-h-[85vh] w-[min(94vw,860px)] flex-col border border-line2 bg-ink-2 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center gap-3">
          <div className="flex gap-4">
            {(["characters", "encounters", "adventures", "llm"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`caps-label pb-1 text-[11px] tracking-[0.2em] transition ${
                  tab === t
                    ? "border-b border-brass text-brass-hi"
                    : "border-b border-transparent text-mist hover:text-parch"
                }`}
              >
                {TAB_LABELS[t]}
              </button>
            ))}
          </div>
          <span className="h-px flex-1 bg-line" />
          <button onClick={onClose} className="text-mist hover:text-parch" title="Close">
            <IconX size={14} />
          </button>
        </div>

        {tab === "characters" && (
        <>
        {/* Import from Deckbuilder JSON */}
        <div className="mb-4 flex flex-wrap items-center gap-3 border border-line bg-black/25 p-3">
          <button onClick={() => fileRef.current?.click()} className={GHOST_BTN}>
            <IconUpload size={11} />
            Import from Deckbuilder JSON
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            multiple
            className="hidden"
            onChange={(e) => onFiles(e.target.files)}
          />
          <span className="text-xs font-light text-mist">
            Loads a Deckbuilder loadout so it&apos;s available in New Game (portrait included).
          </span>
          {note && <span className="text-xs text-vigor">{note}</span>}
          {err && <span className="text-xs text-blood">{err}</span>}
        </div>

        {/* Available characters */}
        <div className="scroll-thin -mx-1 grid min-h-0 flex-1 grid-cols-2 gap-3 overflow-y-auto px-1 sm:grid-cols-3">
          {loading && <div className="col-span-full font-light text-mist">Loading…</div>}
          {!loading && chars.length === 0 && (
            <div className="col-span-full font-light text-dimmed">No characters found. Import one above.</div>
          )}
          {chars.map((c) => (
            <div key={c.id} className="relative flex flex-col overflow-hidden border border-line bg-white/[0.02]">
              <div className="aspect-[3/2] w-full bg-ink-0">
                {c.portrait ? (
                  <img src={c.portrait} alt={c.name} className="h-full w-full object-cover object-top" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-dimmed">
                    <IconSigil size={32} />
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1 p-2">
                <div className="flex items-center justify-between">
                  <span className="caps-label text-[11px] tracking-[0.1em] text-parch">{c.name}</span>
                  <span className="flex gap-0.5">
                    {c.identity.map((col, i) => (
                      <ManaIcon key={i} color={col} size={13} />
                    ))}
                  </span>
                </div>
                <div className="text-xs font-light text-mist">
                  {c.card_count} cards
                </div>
                {c.description && (
                  <div className="line-clamp-2 text-[11px] font-light text-dimmed">{c.description}</div>
                )}
                <button
                  onClick={() => editInDeckbuilder(c)}
                  title="Open this character in the Deckbuilder (it must be running). Its Update Game Character button saves back here."
                  className={`${SMALL_BTN} mt-1 flex items-center gap-1.5 self-start`}
                >
                  <IconEdit size={10} />
                  Edit in Deckbuilder
                </button>
              </div>

              {/* Delete affordance — imported characters only */}
              {c.deletable && confirmId !== c.id && (
                <button
                  onClick={() => setConfirmId(c.id)}
                  title={`Remove ${c.name}`}
                  className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center border border-line bg-ink-0/70 text-mist transition hover:border-blood hover:text-blood"
                >
                  <IconX size={11} />
                </button>
              )}

              {/* Confirmation overlay */}
              {confirmId === c.id && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-0/90 p-3 text-center">
                  <div className="text-sm font-light">
                    Remove <span className="font-normal text-parch">{c.name}</span>?
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => doDelete(c)} className={DANGER_BTN}>
                      Remove
                    </button>
                    <button onClick={() => setConfirmId(null)} className={SMALL_BTN}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        </>
        )}

        {tab === "encounters" && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3 border border-line bg-black/25 p-3">
            <button onClick={() => setEditing("new")} className={GHOST_BTN}>
              <IconPlus size={11} />
              New Encounter
            </button>
            <span className="text-xs font-light text-mist">
              Author an enemy group for playtesting. Edit or remove any encounter below.
            </span>
            {note && <span className="text-xs text-vigor">{note}</span>}
            {err && <span className="text-xs text-blood">{err}</span>}
          </div>

          <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-1">
            {loading && <div className="font-light text-mist">Loading…</div>}
            {!loading && encounters.length === 0 && (
              <div className="font-light text-dimmed">No encounters yet. Create one above.</div>
            )}
            {encounters.map((e) => (
              <div key={e.id} className="relative flex items-center gap-3 border border-line bg-white/[0.02] p-3">
                <div className="min-w-0 flex-1">
                  <div className="caps-label truncate text-[11px] tracking-[0.1em] text-parch">{e.name}</div>
                  <div className="truncate text-xs font-light text-mist">
                    {e.enemy_count} {e.enemy_count === 1 ? "enemy" : "enemies"}
                    {e.scales && e.scales.length > 0 &&
                      ` · scales ${Math.min(...e.scales)}–${Math.max(...e.scales)} heroes`}
                    {" · "}{e.enemy_names.join(", ")}
                  </div>
                </div>
                {encConfirmId === e.id ? (
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-light">Remove?</span>
                    <button onClick={() => doDeleteEncounter(e)} className={DANGER_BTN}>
                      Remove
                    </button>
                    <button onClick={() => setEncConfirmId(null)} className={SMALL_BTN}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <button onClick={() => openEditor(e)} className={SMALL_BTN}>
                      Edit
                    </button>
                    <button
                      onClick={() => setEncConfirmId(e.id)}
                      title={`Remove ${e.name}`}
                      className="flex h-7 w-7 items-center justify-center border border-line text-mist transition hover:border-blood hover:text-blood"
                    >
                      <IconX size={11} />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
        )}

        {tab === "adventures" && (
          <AdventurePanel onEditAct={(act) => setEditing(act)} />
        )}

        {tab === "llm" && <LlmSettingsPanel />}
      </div>
    </div>
  );
}
