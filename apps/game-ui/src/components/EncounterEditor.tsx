import { useMemo, useState } from "react";
import { saveEncounter } from "../lib/api";
import type { ComponentSpec, EncounterDetail, EnemySpec, Row } from "../lib/types";

// Vocabulary the engine understands (scenario.py / engine.py / Design Update 04).
const ROWS: Row[] = ["front", "mid", "rear"];
const MODES: Array<"melee" | "ranged"> = ["melee", "ranged"];
const KEYWORDS = ["reach", "trample", "flying", "lifelink", "deathtouch",
                  "protection", "hexproof", "indestructible"];
const ARCHETYPES = ["Burst", "Drain", "Fortify", "Debilitate", "Punish",
                    "Evasive", "Escalate", "Swarm", "Enrage"];
const TARGET_RULES = ["valuation", "self", "trigger_source", "lowest_hp_ally",
                      "channeling_player"];
const TRIGGERS = ["on_hit", "on_ally_hit", "on_ally_death", "on_targeted",
                  "on_spell_cast", "on_incoming_lethal", "on_ally_below_50",
                  "on_enrage"];
const TARGETING: Array<{ value: string; label: string }> = [
  { value: "lowest_hp_party", label: "Lowest HP (reachable)" },
  { value: "front_lowest_hp", label: "Front row, lowest HP" },
  { value: "lowest_hp", label: "Lowest HP (anywhere)" },
  { value: "valuation", label: "Valuation (smart)" },
];

// Components carry their verbs/condition as staged JSON text while editing; the
// engine gate re-validates everything server-side on save.
type EditComp = ComponentSpec & { _verbsText: string; _condText: string };
type EditEnemy = Omit<EnemySpec, "components"> & { components: EditComp[] };

const field = "rounded bg-slate-900 px-2 py-1 text-sm ring-1 ring-white/10 focus:ring-blue-400 focus:outline-none";
const label = "text-[11px] uppercase tracking-wide text-gray-400";

const stage = (e: EnemySpec): EditEnemy => ({
  ...e,
  keywords: e.keywords ?? [],
  components: (e.components ?? []).map((c) => ({
    ...c,
    _verbsText: JSON.stringify(c.verbs ?? [], null, 1),
    _condText: c.condition ? JSON.stringify(c.condition) : "",
  })),
});

const blankEnemy = (): EditEnemy => ({
  name: "New Enemy", hp: 10, power: 2, level: 1, row: "front",
  attack_mode: "melee", keywords: [], components: [],
  flavor: "", description: "",
});

const blankComp = (): EditComp => ({
  archetype: "Burst", timing: "proactive", cooldown: 2, priority: 30,
  target_rule: "valuation", telegraph: "",
  _verbsText: JSON.stringify(
    [{ kind: "deal_damage", amount: 3,
       target: { mode: "chosen", side: "ally", targeted: true } }], null, 1),
  _condText: "",
});

/** Unstage one component back to engine JSON. Throws with a human message on bad JSON. */
function unstageComp(c: EditComp, enemyName: string, i: number): ComponentSpec {
  const { _verbsText, _condText, ...rest } = c;
  let verbs: unknown[];
  try {
    verbs = _verbsText.trim() ? JSON.parse(_verbsText) : [];
  } catch {
    throw new Error(`${enemyName} · ability ${i + 1}: verbs is not valid JSON`);
  }
  let condition: unknown;
  try {
    condition = _condText.trim() ? JSON.parse(_condText) : undefined;
  } catch {
    throw new Error(`${enemyName} · ability ${i + 1}: condition is not valid JSON`);
  }
  const out: ComponentSpec = { ...rest, verbs, condition };
  if (!out.id) out.id = `${(out.archetype || "comp").toLowerCase()}_${i + 1}`;
  if (out.timing !== "reactive" && out.archetype !== "Enrage") delete out.trigger;
  if (!out.phase) delete out.phase;
  if (!out.action_type || out.action_type === "ability") delete out.action_type;
  if (!out.channel) delete out.channel;
  if (!out.once_per_encounter) delete out.once_per_encounter;
  if (!out.move_home) delete out.move_home;
  if (condition === undefined) delete out.condition;
  return out;
}

export function EncounterEditor({ initial, onSaved, onCancel }: {
  initial: EncounterDetail | null; // null == create a new encounter
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [scene, setScene] = useState(initial?.scene ?? "");
  const [enemies, setEnemies] = useState<EditEnemy[]>(
    initial ? initial.enemies.map(stage) : [blankEnemy()],
  );
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const patch = (i: number, next: Partial<EditEnemy>) =>
    setEnemies((es) => es.map((e, j) => (j === i ? { ...e, ...next } : e)));
  const patchComp = (i: number, ci: number, next: Partial<EditComp>) =>
    setEnemies((es) => es.map((e, j) => j !== i ? e : {
      ...e, components: e.components.map((c, k) => (k === ci ? { ...c, ...next } : c)),
    }));

  const cur = enemies[sel];
  const byRow = useMemo(() => {
    const m: Record<Row, number[]> = { front: [], mid: [], rear: [] };
    enemies.forEach((e, i) => m[(e.row ?? "front") as Row].push(i));
    return m;
  }, [enemies]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const payload = {
        name: name.trim() || "Encounter",
        scene,
        enemies: enemies.map((e) => {
          const { components, ...rest } = e;
          const out: EnemySpec = { ...rest, ranged_intent: e.ranged_intent || undefined };
          if (components.length) {
            out.components = components.map((c, ci) => unstageComp(c, e.name, ci));
          }
          if (!out.is_boss) delete out.is_boss;
          return out;
        }),
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
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Name + scene */}
      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-[220px] flex-1 flex-col gap-1">
          <span className={label}>Encounter name</span>
          <input className={field} value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="e.g. Bandit Ambush" />
        </label>
        <label className="flex min-w-[280px] flex-[2] flex-col gap-1">
          <span className={label}>Scene (battle backdrop — feeds art & narration)</span>
          <textarea className={`${field} min-h-[42px]`} rows={2} value={scene}
                    onChange={(e) => setScene(e.target.value)}
                    placeholder="2–3 sentences: location, light, one striking detail…" />
        </label>
      </div>

      {/* Battlefield preview — enemies as they'd appear in game, by row */}
      <div className="rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
        <div className="mb-2 flex items-center justify-between">
          <span className={label}>Battlefield — click a creature to edit it</span>
          <button
            onClick={() => { setEnemies((es) => [...es, blankEnemy()]); setSel(enemies.length); }}
            className="rounded bg-slate-600 px-2.5 py-1 text-xs font-semibold hover:bg-slate-500"
          >
            + Add enemy
          </button>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {ROWS.map((row) => (
            <div key={row} className="min-h-[104px] rounded bg-slate-900/60 p-2">
              <div className={`${label} mb-1 text-center`}>{row}</div>
              <div className="flex flex-wrap justify-center gap-2">
                {byRow[row].map((i) => {
                  const e = enemies[i];
                  const selected = i === sel;
                  return (
                    <div
                      key={i}
                      onClick={() => setSel(i)}
                      title={e.description || e.flavor || e.name}
                      style={{ width: e.is_boss ? 92 : 72 }}
                      className={`relative aspect-square shrink-0 cursor-pointer select-none rounded-lg bg-gradient-to-b from-rose-900 to-slate-900 shadow transition ${
                        selected ? "ring-4 ring-yellow-400"
                        : e.is_boss ? "ring-2 ring-amber-500" : "ring-1 ring-black/40"
                      }`}
                    >
                      <div className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[9px] font-bold text-gray-200">
                        L{e.level}
                      </div>
                      <div className="absolute right-1 top-1 rounded bg-black/60 px-1 text-[10px] font-bold">
                        {e.power ?? 0}<span className="text-gray-400">/</span>{e.hp}
                      </div>
                      {e.is_boss && (
                        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-[9px] font-black tracking-widest text-amber-400">
                          BOSS
                        </div>
                      )}
                      {(e.components?.length ?? 0) > 0 && (
                        <div className="absolute left-1 bottom-5 rounded bg-indigo-600/80 px-1 text-[8px] font-semibold text-white">
                          {e.components.length} abl
                        </div>
                      )}
                      <div className="absolute inset-x-0 bottom-0 truncate rounded-b-lg bg-black/65 px-0.5 py-0.5 text-center text-[9px] font-semibold">
                        {e.name || "?"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Selected creature editor */}
      {cur && (
        <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1">
          <div className="rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-bold">{cur.name || "New Enemy"}</span>
              {enemies.length > 1 && (
                <button
                  onClick={() => { setEnemies((es) => es.filter((_, j) => j !== sel)); setSel(0); }}
                  className="rounded bg-red-700/70 px-2.5 py-1 text-xs font-semibold hover:bg-red-600"
                >
                  Remove enemy
                </button>
              )}
            </div>

            {/* Stats & level */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
              <label className="col-span-2 flex flex-col gap-1">
                <span className={label}>Name</span>
                <input className={field} value={cur.name}
                       onChange={(e) => patch(sel, { name: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>HP</span>
                <input type="number" min={1} className={field} value={cur.hp}
                       onChange={(e) => patch(sel, { hp: Number(e.target.value) })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Power</span>
                <input type="number" min={0} className={field} value={cur.power ?? 0}
                       onChange={(e) => patch(sel, { power: Number(e.target.value) })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Level</span>
                <input type="number" min={1} className={field} value={cur.level}
                       onChange={(e) => patch(sel, { level: Number(e.target.value) })} />
              </label>
              <label className="flex items-end gap-1 pb-1 text-sm">
                <input type="checkbox" checked={!!cur.is_boss}
                       onChange={(e) => patch(sel, { is_boss: e.target.checked })} />
                Boss
              </label>
            </div>

            {/* Position + attack mode */}
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <label className="flex flex-col gap-1">
                <span className={label}>Row</span>
                <select className={field} value={cur.row ?? "front"}
                        onChange={(e) => patch(sel, { row: e.target.value as Row })}>
                  {ROWS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Home row (retreats to)</span>
                <select className={field} value={cur.home_row ?? cur.row ?? "front"}
                        onChange={(e) => patch(sel, { home_row: e.target.value as Row })}>
                  {ROWS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Attack mode</span>
                <select className={field} value={cur.attack_mode ?? "melee"}
                        onChange={(e) => patch(sel, { attack_mode: e.target.value as "melee" | "ranged" })}>
                  {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </label>
              {cur.intent && (
                <label className="flex flex-col gap-1">
                  <span className={label}>Attack targeting</span>
                  <select className={field} value={cur.intent.targeting ?? "lowest_hp_party"}
                          onChange={(e) => patch(sel, { intent: { ...cur.intent!, targeting: e.target.value } })}>
                    {TARGETING.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select>
                </label>
              )}
            </div>

            {/* Keywords */}
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <span className={label}>Keywords</span>
              {KEYWORDS.map((kw) => (
                <label key={kw} className="flex cursor-pointer items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={(cur.keywords ?? []).includes(kw)}
                    onChange={() => {
                      const has = (cur.keywords ?? []).includes(kw);
                      patch(sel, { keywords: has ? (cur.keywords ?? []).filter((k) => k !== kw)
                                                 : [...(cur.keywords ?? []), kw] });
                    }}
                  />
                  {kw}
                </label>
              ))}
            </div>

            {/* Description (art/narration) + flavor */}
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className={label}>Physical description (art/narration)</span>
                <textarea className={`${field} min-h-[54px]`} rows={2} value={cur.description ?? ""}
                          onChange={(e) => patch(sel, { description: e.target.value })}
                          placeholder="1–2 sentences: size, anatomy, colors, gear…" />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Flavor (mechanical hint)</span>
                <textarea className={`${field} min-h-[54px]`} rows={2} value={cur.flavor ?? ""}
                          onChange={(e) => patch(sel, { flavor: e.target.value })}
                          placeholder="one line: how it plays" />
              </label>
            </div>
          </div>

          {/* Abilities (components): behaviour + heuristics */}
          <div className="rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
            <div className="mb-2 flex items-center justify-between">
              <span className={label}>Abilities & heuristics ({cur.components.length})</span>
              <button
                onClick={() => patch(sel, { components: [...cur.components, blankComp()] })}
                className="rounded bg-slate-600 px-2.5 py-1 text-xs font-semibold hover:bg-slate-500"
              >
                + Add ability
              </button>
            </div>
            {cur.components.length === 0 && (
              <div className="text-xs text-gray-500">
                No abilities — this creature just attacks (its basic attack is derived from Power).
              </div>
            )}
            {cur.components.map((c, ci) => (
              <div key={ci} className="mb-2 rounded bg-slate-900/60 p-2 ring-1 ring-white/5">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <label className="flex flex-col gap-1">
                    <span className={label}>Archetype</span>
                    <select className={field} value={c.archetype ?? "Burst"}
                            onChange={(e) => patchComp(sel, ci, { archetype: e.target.value })}>
                      {ARCHETYPES.map((a) => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={label}>Timing</span>
                    <select className={field} value={c.timing ?? "proactive"}
                            onChange={(e) => patchComp(sel, ci, { timing: e.target.value as "proactive" | "reactive" })}>
                      <option value="proactive">proactive</option>
                      <option value="reactive">reactive</option>
                    </select>
                  </label>
                  {(c.timing === "reactive" || c.archetype === "Enrage") && (
                    <label className="flex flex-col gap-1">
                      <span className={label}>Trigger</span>
                      <select className={field} value={c.trigger ?? "on_hit"}
                              onChange={(e) => patchComp(sel, ci, { trigger: e.target.value })}>
                        {TRIGGERS.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </label>
                  )}
                  <label className="flex flex-col gap-1">
                    <span className={label}>Target rule</span>
                    <select className={field} value={c.target_rule ?? "valuation"}
                            onChange={(e) => patchComp(sel, ci, { target_rule: e.target.value })}>
                      {TARGET_RULES.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={label}>Cooldown</span>
                    <input type="number" min={0} className={field} value={c.cooldown ?? 2}
                           onChange={(e) => patchComp(sel, ci, { cooldown: Number(e.target.value) })} />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={label}>Priority (low = first)</span>
                    <input type="number" className={field} value={c.priority ?? 30}
                           onChange={(e) => patchComp(sel, ci, { priority: Number(e.target.value) })} />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={label}>Class</span>
                    <select className={field} value={c.action_type ?? "ability"}
                            onChange={(e) => patchComp(sel, ci, { action_type: e.target.value })}>
                      <option value="ability">ability</option>
                      <option value="spell">spell</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={label}>Boss phase</span>
                    <select className={field} value={c.phase ?? ""}
                            onChange={(e) => patchComp(sel, ci, { phase: e.target.value })}>
                      <option value="">always</option>
                      <option value="pre_enrage">pre-enrage</option>
                      <option value="post_enrage">post-enrage</option>
                    </select>
                  </label>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-4 text-sm">
                  <label className="flex items-center gap-1">
                    <input type="checkbox" checked={!!c.channel}
                           onChange={(e) => patchComp(sel, ci, { channel: e.target.checked })} />
                    channel (ongoing until broken)
                  </label>
                  <label className="flex items-center gap-1">
                    <input type="checkbox" checked={!!c.once_per_encounter}
                           onChange={(e) => patchComp(sel, ci, { once_per_encounter: e.target.checked })} />
                    once per encounter
                  </label>
                  <label className="flex items-center gap-1">
                    <input type="checkbox" checked={!!c.move_home}
                           onChange={(e) => patchComp(sel, ci, { move_home: e.target.checked })} />
                    reposition home (Evasive)
                  </label>
                  <button
                    onClick={() => patch(sel, { components: cur.components.filter((_, k) => k !== ci) })}
                    className="ml-auto rounded bg-red-700/60 px-2 py-0.5 text-xs font-semibold hover:bg-red-600"
                  >
                    remove
                  </button>
                </div>
                <label className="mt-1 flex flex-col gap-1">
                  <span className={label}>Telegraph (what players see)</span>
                  <input className={field} value={c.telegraph ?? ""}
                         onChange={(e) => patchComp(sel, ci, { telegraph: e.target.value })}
                         placeholder="e.g. Life Drain — deal 3, heal 3" />
                </label>
                <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <label className="flex flex-col gap-1">
                    <span className={label}>Verbs (effect JSON)</span>
                    <textarea className={`${field} min-h-[72px] font-mono text-[11px]`} rows={4}
                              spellCheck={false} value={c._verbsText}
                              onChange={(e) => patchComp(sel, ci, { _verbsText: e.target.value })} />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={label}>Condition (optional JSON gate)</span>
                    <textarea className={`${field} min-h-[72px] font-mono text-[11px]`} rows={4}
                              spellCheck={false} value={c._condText}
                              onChange={(e) => patchComp(sel, ci, { _condText: e.target.value })}
                              placeholder='{"kind": "self_hp_pct", "op": "<", "value": 50}' />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {err && <div className="rounded bg-red-900/50 px-3 py-2 text-sm text-red-200">{err}</div>}

      <div className="flex justify-end gap-2">
        <button onClick={onCancel}
                className="rounded-lg bg-slate-600 px-4 py-2 text-sm font-semibold hover:bg-slate-500">
          Cancel
        </button>
        <button onClick={save} disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold hover:bg-blue-500 disabled:bg-slate-600">
          {busy ? "Saving…" : initial ? "Update Encounter" : "Create Encounter"}
        </button>
      </div>
    </div>
  );
}
