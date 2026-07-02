import { useEffect, useRef, useState } from "react";
import { deleteCharacter, fetchSetupOptions, importCharacter } from "../lib/api";
import type { CharacterOption } from "../lib/types";
import { ManaIcon } from "./Pips";

export function OptionsModal({ onClose }: { onClose: () => void }) {
  const [chars, setChars] = useState<CharacterOption[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<string | null>(null); // card pending delete
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () =>
    fetchSetupOptions()
      .then((o) => setChars(o.characters))
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-[min(94vw,860px)] flex-col rounded-xl bg-slate-800 p-5 shadow-2xl ring-1 ring-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold">Characters</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            ✕
          </button>
        </div>

        {/* Import from Deckbuilder JSON */}
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
          <button
            onClick={() => fileRef.current?.click()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold hover:bg-blue-500"
          >
            ⬆ Import from Deckbuilder JSON
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            multiple
            className="hidden"
            onChange={(e) => onFiles(e.target.files)}
          />
          <span className="text-xs text-gray-400">
            Loads a Deckbuilder loadout so it&apos;s available in New Game (portrait included).
          </span>
          {note && <span className="text-xs font-semibold text-emerald-400">{note}</span>}
          {err && <span className="text-xs font-semibold text-red-400">{err}</span>}
        </div>

        {/* Available characters */}
        <div className="scroll-thin -mx-1 grid min-h-0 flex-1 grid-cols-2 gap-3 overflow-y-auto px-1 sm:grid-cols-3">
          {loading && <div className="col-span-full text-gray-400">Loading…</div>}
          {!loading && chars.length === 0 && (
            <div className="col-span-full text-gray-500">No characters found. Import one above.</div>
          )}
          {chars.map((c) => (
            <div key={c.id} className="relative flex flex-col overflow-hidden rounded-lg bg-slate-700/50 ring-1 ring-white/10">
              <div className="aspect-[3/2] w-full bg-slate-900">
                {c.portrait ? (
                  <img src={c.portrait} alt={c.name} className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-3xl text-slate-600">🖼</div>
                )}
              </div>
              <div className="flex flex-col gap-1 p-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold">{c.name}</span>
                  <span className="flex gap-0.5">
                    {c.identity.map((col, i) => (
                      <ManaIcon key={i} color={col} size={14} />
                    ))}
                  </span>
                </div>
                <div className="text-xs text-gray-400">
                  {c.archetype} · {c.card_count} cards
                </div>
                {c.description && (
                  <div className="line-clamp-2 text-[11px] text-gray-500">{c.description}</div>
                )}
              </div>

              {/* Delete affordance — imported characters only */}
              {c.deletable && confirmId !== c.id && (
                <button
                  onClick={() => setConfirmId(c.id)}
                  title={`Remove ${c.name}`}
                  className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-sm text-gray-200 hover:bg-red-600 hover:text-white"
                >
                  ✕
                </button>
              )}

              {/* Confirmation overlay */}
              {confirmId === c.id && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/85 p-3 text-center">
                  <div className="text-sm">
                    Remove <span className="font-bold">{c.name}</span>?
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => doDelete(c)}
                      className="rounded bg-red-600 px-3 py-1 text-sm font-semibold hover:bg-red-500"
                    >
                      Remove
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      className="rounded bg-slate-600 px-3 py-1 text-sm font-semibold hover:bg-slate-500"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
