import { useEffect, useState } from "react";
import {
  deleteAdventure,
  fetchAdventure,
  fetchSetupOptions,
  generateAdventure,
  saveAdventureInfo,
} from "../lib/api";
import type {
  AdventureDetail,
  AdventureOption,
  CharacterOption,
  EncounterDetail,
} from "../lib/types";
import { roman } from "../lib/format";
import { ArtQueueButton } from "./ArtQueueButton";
import { IconEdit, IconX } from "./Icons";

const DIFFICULTIES = ["easy", "standard", "hard"];

const label = "caps-label text-[9px] tracking-[0.2em] text-mist";
const field =
  "border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-brass/60 focus:outline-none";
const GHOST_BTN =
  "caps-label flex items-center gap-1.5 border border-line2 px-3 py-1.5 text-[9px] tracking-[0.16em] " +
  "text-brass transition hover:border-brass hover:text-brass-hi";
const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch";
const DANGER_BTN =
  "caps-label border border-blood/60 bg-blood/15 px-3 py-1 text-[9px] tracking-[0.14em] text-blood " +
  "transition hover:bg-blood hover:text-parch";

/** Options → Adventures (§D10-6.1): the saved-adventures list, generation, and
 * the adventure-level editor (name / flavor / narrations + per-act art). Acts
 * themselves open in the existing encounter editor via `onEditAct`. */
export function AdventurePanel({ onEditAct }: {
  onEditAct: (act: EncounterDetail) => void;
}) {
  const [adventures, setAdventures] = useState<AdventureOption[]>([]);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  // Generation controls.
  const [genOpen, setGenOpen] = useState(false);
  const [party, setParty] = useState<string[]>([]);
  const [difficulty, setDifficulty] = useState("standard");
  const [theme, setTheme] = useState("");
  const [genBusy, setGenBusy] = useState(false);

  // The adventure open for wrapper-level editing.
  const [editing, setEditing] = useState<AdventureDetail | null>(null);
  const [infoBusy, setInfoBusy] = useState(false);

  const refresh = () =>
    fetchSetupOptions()
      .then((o) => {
        setAdventures(o.adventures);
        setCharacters(o.characters);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
  }, []);

  const toggleParty = (id: string) =>
    setParty((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const doGenerate = async () => {
    setGenBusy(true);
    setErr(null);
    setNote("Generating adventure — three acts in one arc… (this can take a few minutes)");
    try {
      const meta = await generateAdventure(party, difficulty, theme);
      setNote(`Generated ${meta.name}`);
      setGenOpen(false);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setNote(null);
    } finally {
      setGenBusy(false);
    }
  };

  const doDelete = async (a: AdventureOption) => {
    setErr(null);
    try {
      await deleteAdventure(a.id);
      setNote(`Removed ${a.name}`);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirmId(null);
    }
  };

  const openEditor = async (a: AdventureOption) => {
    setErr(null);
    try {
      setEditing(await fetchAdventure(a.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const saveInfo = async () => {
    if (!editing) return;
    setInfoBusy(true);
    setErr(null);
    try {
      await saveAdventureInfo(editing.id, {
        name: editing.name,
        flavor: editing.flavor,
        narrations: editing.acts.map((a) => a.narration),
      });
      setNote("Adventure saved");
      setEditing(null);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setInfoBusy(false);
    }
  };

  // ---- wrapper editor view -------------------------------------------------- //
  if (editing) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-[200px] flex-1 flex-col gap-1">
            <span className={label}>Adventure name</span>
            <input className={field} value={editing.name}
                   onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
          </label>
          <label className="flex min-w-[260px] flex-[2] flex-col gap-1">
            <span className={label}>Flavor (one-line pitch, shown in New Game)</span>
            <input className={field} value={editing.flavor}
                   onChange={(e) => setEditing({ ...editing, flavor: e.target.value })} />
          </label>
          <ArtQueueButton
            target={{ adventureId: editing.id }}
            subject="all three acts (Act I first)"
          />
        </div>

        <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          {editing.acts.map((act, i) => (
            <div key={act.encounter_id} className="border border-line bg-black/25 p-3">
              <div className="mb-2 flex items-center gap-3">
                <span className="caps-label text-[11px] tracking-[0.2em] text-brass">
                  Act {roman(i + 1)}
                </span>
                <span className="truncate font-normal text-parch">{act.name}</span>
                <span className="truncate text-xs font-light text-mist">
                  {act.enemies.map((e) => e.name).join(", ")}
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <button className={SMALL_BTN} onClick={() => onEditAct(act)}>
                    <span className="flex items-center gap-1.5">
                      <IconEdit size={10} /> Edit act
                    </span>
                  </button>
                </span>
              </div>
              <label className="flex flex-col gap-1">
                <span className={label}>
                  Narration (second person, present tense — the act&apos;s opening splash)
                </span>
                <textarea
                  className={`${field} min-h-[52px]`}
                  rows={2}
                  value={act.narration}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      acts: editing.acts.map((a, j) =>
                        j === i ? { ...a, narration: e.target.value } : a),
                    })
                  }
                  placeholder="You push through the splintered gate. Beyond, the courtyard…"
                />
              </label>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button onClick={saveInfo} disabled={infoBusy} className={GHOST_BTN}>
            {infoBusy ? "Saving…" : "Save Adventure"}
          </button>
          <button onClick={() => setEditing(null)} className={SMALL_BTN}>
            Cancel
          </button>
          {err && <span className="text-xs text-blood">{err}</span>}
        </div>
      </div>
    );
  }

  // ---- list view ------------------------------------------------------------ //
  return (
    <>
      <div className="mb-4 flex flex-col gap-3 border border-line bg-black/25 p-3">
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={() => setGenOpen((v) => !v)} className={GHOST_BTN}>
            Generate Adventure
          </button>
          <span className="text-xs font-light text-mist">
            A three-act run against one theme: guards at the gate, knights in the
            courtyard, the tyrant in his throne room.
          </span>
          {note && <span className="text-xs text-vigor">{note}</span>}
          {err && <span className="text-xs text-blood">{err}</span>}
        </div>
        {genOpen && (
          <div className="flex flex-col gap-2 border-t border-line pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className={label}>Party</span>
              {characters.map((c) => (
                <button
                  key={c.id}
                  onClick={() => toggleParty(c.id)}
                  className={`caps-label border px-2.5 py-1 text-[9px] tracking-[0.14em] transition ${
                    party.includes(c.id)
                      ? "border-brass bg-brass/20 text-brass"
                      : "border-line text-mist hover:text-parch"
                  }`}
                >
                  {c.name}
                </button>
              ))}
              <span className="mx-2 h-4 w-px bg-line" />
              <span className={label}>Difficulty</span>
              {DIFFICULTIES.map((d) => (
                <button
                  key={d}
                  onClick={() => setDifficulty(d)}
                  className={`caps-label border px-2.5 py-1 text-[9px] tracking-[0.14em] transition ${
                    difficulty === d
                      ? "border-aether bg-aether/20 text-aether"
                      : "border-line text-mist hover:text-parch"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                maxLength={140}
                placeholder="Optional theme, e.g. “a drowned monastery and its bell-wraiths”"
                className={`${field} flex-1`}
              />
              <button
                onClick={doGenerate}
                disabled={genBusy || party.length === 0}
                className={`${GHOST_BTN} disabled:cursor-not-allowed disabled:opacity-40`}
              >
                {genBusy ? "Generating…" : "Generate"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-1">
        {loading && <div className="font-light text-mist">Loading…</div>}
        {!loading && adventures.length === 0 && (
          <div className="font-light text-dimmed">
            No adventures yet. Generate one above — or start from the New Game modal.
          </div>
        )}
        {adventures.map((a) => (
          <div key={a.id} className="relative flex items-center gap-3 border border-line bg-white/[0.02] p-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="caps-label truncate text-[11px] tracking-[0.1em] text-parch">
                  {a.name}
                </span>
                {a.flavor && (
                  <span className="truncate text-xs font-light italic text-mist">{a.flavor}</span>
                )}
              </div>
              <div className="truncate text-xs font-light text-mist">
                {a.act_names.map((n, i) => `${roman(i + 1)}. ${n}`).join(" · ")}
              </div>
            </div>
            <ArtQueueButton target={{ adventureId: a.id }} subject="all three acts" />
            {confirmId === a.id ? (
              <div className="flex items-center gap-2">
                <span className="text-xs font-light">Remove?</span>
                <button onClick={() => doDelete(a)} className={DANGER_BTN}>
                  Remove
                </button>
                <button onClick={() => setConfirmId(null)} className={SMALL_BTN}>
                  Cancel
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <button onClick={() => openEditor(a)} className={SMALL_BTN}>
                  Edit
                </button>
                <button
                  onClick={() => setConfirmId(a.id)}
                  title={`Remove ${a.name}`}
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
  );
}
