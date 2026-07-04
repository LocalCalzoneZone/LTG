import { useState } from "react";
import { saveEncounter } from "../lib/api";
import type { EnemySpec, EncounterDetail, Row } from "../lib/types";

// Vocabulary the engine understands (see scenario.py / engine.py heuristics).
const ROWS: Row[] = ["front", "mid", "rear"];
const MODES: Array<"melee" | "ranged"> = ["melee", "ranged"];
const KEYWORDS = ["flying", "lifelink", "deathtouch", "reach"];
const TARGETING: Array<{ value: string; label: string }> = [
  { value: "lowest_hp_party", label: "Lowest HP (reachable)" },
  { value: "front_lowest_hp", label: "Front row, lowest HP" },
  { value: "lowest_hp", label: "Lowest HP (anywhere)" },
];

const blankEnemy = (): EnemySpec => ({
  name: "",
  hp: 5,
  level: 1,
  power: undefined,
  row: "front",
  keywords: [],
  intent: { name: "Attack", amount: 2, mode: "melee", targeting: "lowest_hp_party", action_type: "ability" },
  ranged_intent: null,
});

const field = "rounded bg-slate-900 px-2 py-1 text-sm ring-1 ring-white/10 focus:ring-blue-400 focus:outline-none";
const label = "text-[11px] uppercase tracking-wide text-gray-400";

export function EncounterEditor({
  initial,
  onSaved,
  onCancel,
}: {
  initial: EncounterDetail | null; // null == create a new encounter
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [enemies, setEnemies] = useState<EnemySpec[]>(
    initial ? initial.enemies.map((e) => ({ ...e, keywords: e.keywords ?? [] })) : [blankEnemy()],
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const patch = (i: number, next: Partial<EnemySpec>) =>
    setEnemies((es) => es.map((e, j) => (j === i ? { ...e, ...next } : e)));
  const patchIntent = (i: number, next: Partial<EnemySpec["intent"]>) =>
    setEnemies((es) => es.map((e, j) => (j === i ? { ...e, intent: { ...e.intent, ...next } } : e)));

  const toggleKw = (i: number, kw: string) =>
    setEnemies((es) =>
      es.map((e, j) => {
        if (j !== i) return e;
        const has = (e.keywords ?? []).includes(kw);
        return { ...e, keywords: has ? (e.keywords ?? []).filter((k) => k !== kw) : [...(e.keywords ?? []), kw] };
      }),
    );

  const toggleRanged = (i: number) =>
    setEnemies((es) =>
      es.map((e, j) =>
        j !== i
          ? e
          : {
              ...e,
              ranged_intent: e.ranged_intent
                ? null
                : { name: "Ranged Attack", amount: 1, mode: "ranged", action_type: "ability" },
            },
      ),
    );

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      // Drop empty ranged intents; the server validates the rest.
      const payload = {
        name: name.trim() || "Encounter",
        enemies: enemies.map((e) => ({ ...e, ranged_intent: e.ranged_intent || undefined })),
        tokens: initial?.tokens ?? {},
      };
      await saveEncounter(payload, initial?.id);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-1 flex-col gap-1">
          <span className={label}>Encounter name</span>
          <input className={field} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bandit Ambush" />
        </label>
        <button onClick={() => setEnemies((es) => [...es, blankEnemy()])} className="rounded-lg bg-slate-600 px-3 py-2 text-sm font-semibold hover:bg-slate-500">
          + Add enemy
        </button>
      </div>

      <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1">
        {enemies.map((e, i) => (
          <div key={i} className="rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
            <div className="mb-2 flex items-center gap-2">
              <input
                className={`${field} flex-1 font-semibold`}
                value={e.name}
                onChange={(ev) => patch(i, { name: ev.target.value })}
                placeholder="Enemy name"
              />
              {enemies.length > 1 && (
                <button
                  onClick={() => setEnemies((es) => es.filter((_, j) => j !== i))}
                  title="Remove enemy"
                  className="flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-gray-300 hover:bg-red-600 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <label className="flex flex-col gap-1">
                <span className={label}>HP</span>
                <input type="number" min={1} className={field} value={e.hp} onChange={(ev) => patch(i, { hp: Number(ev.target.value) })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Level</span>
                <input type="number" min={1} className={field} value={e.level} onChange={(ev) => patch(i, { level: Number(ev.target.value) })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Row</span>
                <select className={field} value={e.row ?? "front"} onChange={(ev) => patch(i, { row: ev.target.value as Row })}>
                  {ROWS.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Power (opt)</span>
                <input
                  type="number"
                  className={field}
                  value={e.power ?? ""}
                  placeholder="= dmg"
                  onChange={(ev) => patch(i, { power: ev.target.value === "" ? undefined : Number(ev.target.value) })}
                />
              </label>
            </div>

            <div className="mt-2 rounded bg-slate-900/60 p-2">
              <div className={`${label} mb-1`}>Attack (intent)</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <input className={field} value={e.intent.name} onChange={(ev) => patchIntent(i, { name: ev.target.value })} placeholder="Attack name" />
                <label className="flex items-center gap-1">
                  <span className={label}>Dmg</span>
                  <input type="number" min={0} className={`${field} w-full`} value={e.intent.amount} onChange={(ev) => patchIntent(i, { amount: Number(ev.target.value) })} />
                </label>
                <select className={field} value={e.intent.mode ?? "melee"} onChange={(ev) => patchIntent(i, { mode: ev.target.value as "melee" | "ranged" })}>
                  {MODES.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <select className={field} value={e.intent.targeting ?? "lowest_hp_party"} onChange={(ev) => patchIntent(i, { targeting: ev.target.value })}>
                  {TARGETING.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-3">
              <span className={label}>Keywords</span>
              {KEYWORDS.map((kw) => (
                <label key={kw} className="flex cursor-pointer items-center gap-1 text-sm">
                  <input type="checkbox" checked={(e.keywords ?? []).includes(kw)} onChange={() => toggleKw(i, kw)} />
                  {kw}
                </label>
              ))}
            </div>

            <div className="mt-2">
              <label className="flex cursor-pointer items-center gap-1 text-sm text-gray-300">
                <input type="checkbox" checked={!!e.ranged_intent} onChange={() => toggleRanged(i)} />
                Ranged fallback (used when its melee attack can&apos;t reach)
              </label>
              {e.ranged_intent && (
                <div className="mt-1 grid grid-cols-2 gap-2 pl-5">
                  <input
                    className={field}
                    value={e.ranged_intent.name}
                    onChange={(ev) => patch(i, { ranged_intent: { ...e.ranged_intent!, name: ev.target.value } })}
                    placeholder="Ranged attack name"
                  />
                  <label className="flex items-center gap-1">
                    <span className={label}>Dmg</span>
                    <input
                      type="number"
                      min={0}
                      className={`${field} w-full`}
                      value={e.ranged_intent.amount}
                      onChange={(ev) => patch(i, { ranged_intent: { ...e.ranged_intent!, amount: Number(ev.target.value), mode: "ranged" } })}
                    />
                  </label>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {err && <div className="mt-2 rounded bg-red-900/50 px-3 py-2 text-sm text-red-200">{err}</div>}

      <div className="mt-3 flex justify-end gap-2">
        <button onClick={onCancel} className="rounded-lg bg-slate-600 px-4 py-2 text-sm font-semibold hover:bg-slate-500">
          Cancel
        </button>
        <button onClick={save} disabled={busy} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold hover:bg-blue-500 disabled:bg-slate-600">
          {busy ? "Saving…" : initial ? "Save changes" : "Create encounter"}
        </button>
      </div>
    </div>
  );
}
