import { useEffect, useState } from "react";
import { fetchLlmSettings, saveLlmSettings } from "../lib/api";
import type { LlmSettings } from "../lib/types";

const field =
  "border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-brass/60 focus:outline-none";
const label = "caps-label text-[9px] tracking-[0.2em] text-mist";

// Options → LLM. Sets the OpenRouter API key and, under "Encounter Generation",
// the model + the editable instruction prompt used to generate encounters.
export function LlmSettingsPanel() {
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [model, setModel] = useState("");
  const [instructions, setInstructions] = useState("");
  const [artStyle, setArtStyle] = useState("");
  const [artBackend, setArtBackend] = useState("openrouter");
  const [comfyUrl, setComfyUrl] = useState("");
  const [comfyWorkflow, setComfyWorkflow] = useState("");
  const [apiKey, setApiKey] = useState(""); // "" == leave stored key untouched
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = (s: LlmSettings) => {
    setSettings(s);
    setModel(s.model);
    setInstructions(s.instructions);
    setArtStyle(s.art_style);
    setArtBackend(s.art_backend);
    setComfyUrl(s.comfyui_url);
    setComfyWorkflow(s.comfyui_workflow);
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
      const patch: {
        model: string; instructions: string; art_style: string;
        art_backend: string; comfyui_url: string; comfyui_workflow: string;
        api_key?: string;
      } = {
        model,
        instructions,
        art_style: artStyle,
        art_backend: artBackend,
        comfyui_url: comfyUrl,
        comfyui_workflow: comfyWorkflow,
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

  // Reset a prompt to the server's built-in default (also picks up upgrades to
  // the default that a previously saved copy would otherwise shadow).
  const reset = async (patch: { instructions: null } | { art_style: null }, what: string) => {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      const s = await saveLlmSettings(patch);
      load(s);
      setNote(`${what} reset to default`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!settings && !err) return <div className="font-light text-mist">Loading…</div>;

  return (
    <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1">
      {/* API key */}
      <section className="border border-line bg-black/25 p-3">
        <div className={`${label} mb-1.5`}>OpenRouter API key</div>
        <input
          type="password"
          className={`${field} w-full`}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={settings?.has_key ? "•••••••• (a key is set — type to replace)" : "sk-or-…"}
          autoComplete="off"
        />
        <div className="mt-1.5 text-[11px] font-light text-dimmed">
          Stored locally on the server (gitignored), never sent to the browser. Get one at
          openrouter.ai/keys. {settings?.has_key ? "A key is currently set." : "No key set yet."}
        </div>
      </section>

      {/* Encounter generation */}
      <section className="border border-line bg-black/25 p-3">
        <div className="caps-label mb-3 text-[10px] tracking-[0.25em] text-brass">
          Encounter Generation
        </div>

        <label className="mb-3 flex flex-col gap-1.5">
          <span className={label}>Model</span>
          <select className={field} value={model} onChange={(e) => setModel(e.target.value)}>
            {settings?.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="flex items-center justify-between">
            <span className={label}>Instructions (system prompt)</span>
            <button
              type="button"
              onClick={() => reset({ instructions: null }, "Instructions")}
              disabled={busy}
              className="caps-label border border-line px-2 py-0.5 text-[9px] tracking-[0.14em] text-mist transition hover:border-line2 hover:text-parch disabled:opacity-50"
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
        <div className="mt-1.5 text-[11px] font-light text-dimmed">
          How the model builds enemies and scopes difficulty. The party, difficulty, and target
          budget are appended automatically at generation time.
        </div>
      </section>

      {/* Art generation */}
      <section className="border border-line bg-black/25 p-3">
        <div className="caps-label mb-3 text-[10px] tracking-[0.25em] text-brass">
          Art Generation
        </div>

        <label className="mb-3 flex flex-col gap-1.5">
          <span className={label}>Backend</span>
          <select className={field} value={artBackend} onChange={(e) => setArtBackend(e.target.value)}>
            {settings?.art_backends.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}
              </option>
            ))}
          </select>
          <span className="text-[11px] font-light text-dimmed">
            {artBackend === "comfyui"
              ? "Images render on your own ComfyUI server using the workflow below."
              : `Images render in the cloud via OpenRouter (${settings?.art_model}) using the API key above.`}
          </span>
        </label>

        {artBackend === "comfyui" && (
          <>
            <label className="mb-3 flex flex-col gap-1.5">
              <span className={label}>ComfyUI server address</span>
              <input
                className={`${field} w-full`}
                value={comfyUrl}
                onChange={(e) => setComfyUrl(e.target.value)}
                placeholder="http://192.168.1.50:8188"
                autoComplete="off"
                spellCheck={false}
              />
              <span className="text-[11px] font-light text-dimmed">
                The machine running ComfyUI (default port 8188). Start it with{" "}
                <code className="text-mist">--listen</code> so other machines on your network can
                reach it; use http://127.0.0.1:8188 if it runs on this machine.
              </span>
            </label>
            <label className="mb-3 flex flex-col gap-1.5">
              <span className={label}>Workflow (API format JSON)</span>
              <textarea
                className={`${field} min-h-[160px] w-full font-mono text-[11px] leading-relaxed`}
                value={comfyWorkflow}
                onChange={(e) => setComfyWorkflow(e.target.value)}
                placeholder='Paste the export from Workflow → Export (API)…'
                spellCheck={false}
              />
              <span className="text-[11px] font-light text-dimmed">
                Export your workflow with Workflow → Export (API) (enable dev mode in older
                versions), then put <code className="text-mist">%prompt%</code> inside the
                positive-prompt text — it is replaced with the art-style + description prompt.
                Optionally set width/height inputs to the strings{" "}
                <code className="text-mist">"%width%"</code> /{" "}
                <code className="text-mist">"%height%"</code> (no extra quotes inside the value)
                to get 1344×768 backdrops and 1024×1024 portraits, and a seed input to{" "}
                <code className="text-mist">"%seed%"</code> so every repaint rolls a fresh seed.
                The workflow must end in a SaveImage node.
              </span>
            </label>
          </>
        )}

        <label className="flex flex-col gap-1.5">
          <span className="flex items-center justify-between">
            <span className={label}>Art style (aesthetic prompt)</span>
            <button
              type="button"
              onClick={() => reset({ art_style: null }, "Art style")}
              disabled={busy}
              className="caps-label border border-line px-2 py-0.5 text-[9px] tracking-[0.14em] text-mist transition hover:border-line2 hover:text-parch disabled:opacity-50"
              title="Discard edits and restore the built-in default style"
            >
              Reset to default
            </button>
          </span>
          <textarea
            className={`${field} min-h-[120px] w-full font-mono text-[12px] leading-relaxed`}
            value={artStyle}
            onChange={(e) => setArtStyle(e.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="mt-1.5 text-[11px] font-light text-dimmed">
          The look every generated image is prompted into. The encounter&apos;s scene text (for
          backdrops) or the enemy&apos;s physical description (for portraits) is appended
          automatically.
        </div>
      </section>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={busy}
          className="caps-label border border-brass/60 bg-brass/10 px-4 py-2 text-[10px] tracking-[0.2em] text-brass transition hover:bg-brass hover:text-ink-0 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save LLM Settings"}
        </button>
        {note && <span className="text-xs text-vigor">{note}</span>}
        {err && <span className="text-xs text-blood">{err}</span>}
      </div>
    </div>
  );
}
