import { useEffect, useState } from "react";
import { fetchLlmSettings, saveLlmSettings } from "../lib/api";
import type { LlmSettings } from "../lib/types";

const field =
  "rounded bg-slate-900 px-2 py-1.5 text-sm ring-1 ring-white/10 focus:ring-blue-400 focus:outline-none";
const label = "text-[11px] uppercase tracking-wide text-gray-400";

// Options → LLM. Sets the OpenRouter API key and, under "Encounter Generation",
// the model + the editable instruction prompt used to generate encounters.
export function LlmSettingsPanel() {
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [model, setModel] = useState("");
  const [instructions, setInstructions] = useState("");
  const [apiKey, setApiKey] = useState(""); // "" == leave stored key untouched
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = (s: LlmSettings) => {
    setSettings(s);
    setModel(s.model);
    setInstructions(s.instructions);
  };

  useEffect(() => {
    fetchLlmSettings()
      .then(load)
      .catch((e) => setErr(String(e)));
  }, []);

  const save = async () => {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      const patch: { model: string; instructions: string; api_key?: string } = {
        model,
        instructions,
      };
      if (apiKey.trim()) patch.api_key = apiKey.trim();
      const s = await saveLlmSettings(patch);
      load(s);
      setApiKey("");
      setNote("Saved");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Reset the prompt to the server's built-in default (also picks up upgrades to
  // the default that a previously saved copy would otherwise shadow).
  const resetInstructions = async () => {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      const s = await saveLlmSettings({ instructions: null });
      load(s);
      setNote("Instructions reset to default");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!settings && !err) return <div className="text-gray-400">Loading…</div>;

  return (
    <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1">
      {/* API key */}
      <section className="rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
        <div className={`${label} mb-1`}>OpenRouter API key</div>
        <input
          type="password"
          className={`${field} w-full`}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={settings?.has_key ? "•••••••• (a key is set — type to replace)" : "sk-or-…"}
          autoComplete="off"
        />
        <div className="mt-1 text-[11px] text-gray-500">
          Stored locally on the server (gitignored), never sent to the browser. Get one at
          openrouter.ai/keys. {settings?.has_key ? "A key is currently set." : "No key set yet."}
        </div>
      </section>

      {/* Encounter generation */}
      <section className="rounded-lg bg-black/30 p-3 ring-1 ring-white/5">
        <div className="mb-2 text-sm font-bold">Encounter Generation</div>

        <label className="mb-3 flex flex-col gap-1">
          <span className={label}>Model</span>
          <select className={field} value={model} onChange={(e) => setModel(e.target.value)}>
            {settings?.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="flex items-center justify-between">
            <span className={label}>Instructions (system prompt)</span>
            <button
              type="button"
              onClick={resetInstructions}
              disabled={busy}
              className="rounded bg-slate-600 px-2 py-0.5 text-[11px] font-semibold hover:bg-slate-500 disabled:bg-slate-700"
              title="Discard edits and restore the built-in default prompt"
            >
              Reset to default
            </button>
          </span>
          <textarea
            className={`${field} min-h-[320px] w-full font-mono text-[12px] leading-relaxed`}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="mt-1 text-[11px] text-gray-500">
          How the model builds enemies and scopes difficulty. The party, difficulty, and target
          budget are appended automatically at generation time.
        </div>
      </section>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={busy}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold hover:bg-blue-500 disabled:bg-slate-600"
        >
          {busy ? "Saving…" : "Save LLM settings"}
        </button>
        {note && <span className="text-xs font-semibold text-emerald-400">{note}</span>}
        {err && <span className="text-xs font-semibold text-red-400">{err}</span>}
      </div>
    </div>
  );
}
