// REST lobby client. Same-origin (the server serves the built client), so
// relative URLs work in prod; in dev Vite proxies /api to the server.
import type {
  AdventureDetail,
  AdventureOption,
  ArtQueueStatus,
  CharacterOption,
  EncounterDetail,
  EncounterOption,
  LlmSettings,
  LlmSettingsPatch,
  ItemMeta,
  ItemView,
  ScenarioDetail,
  ScenarioOption,
  SetupOptions,
  TownDetail,
  TownOption,
} from "./types";

export async function fetchSetupOptions(): Promise<SetupOptions> {
  const res = await fetch("/api/setup-options");
  if (!res.ok) throw new Error(`setup-options failed: ${res.status}`);
  return res.json();
}

export async function importCharacter(loadout: unknown): Promise<CharacterOption> {
  const res = await fetch("/api/characters", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(loadout),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `import failed: ${res.status}`);
  }
  const data = await res.json();
  return data.character as CharacterOption;
}

export async function deleteCharacter(id: string): Promise<void> {
  const res = await fetch(`/api/characters/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `delete failed: ${res.status}`);
  }
}

export async function fetchEncounter(id: string): Promise<EncounterDetail> {
  const res = await fetch(`/api/encounters/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`encounter load failed: ${res.status}`);
  return res.json();
}

// Create (id omitted) or edit (id given) an encounter; returns the saved meta.
export async function saveEncounter(
  encounter: Omit<EncounterDetail, "id">,
  id?: string,
): Promise<EncounterOption> {
  const res = await fetch("/api/encounters", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id ?? null, encounter }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `save failed: ${res.status}`);
  }
  const data = await res.json();
  return data.encounter as EncounterOption;
}

export async function deleteEncounter(id: string): Promise<void> {
  const res = await fetch(`/api/encounters/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `delete failed: ${res.status}`);
  }
}

// Run options (Update 17 §D17-1): present on an adventure start == play it
// inside a NEW run — saved at every phase boundary, resumable and forkable
// from Load Game. Absent == today's throwaway session.
export interface RunOptions {
  difficulty: "easy" | "standard" | "hard";
  hardcore: boolean;
  everquest: boolean;
  name?: string;
}

// Start a game on a standalone encounter, or an adventure (exactly one of the
// two ids) — an adventure session runs the three-phase flow server-side.
export async function createGame(
  character_ids: string[],
  target: { encounterId?: string; adventureId?: string; scenarioId?: string; townId?: string;
            run?: RunOptions; note?: string },
): Promise<string> {
  const res = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      character_ids,
      encounter_id: target.encounterId ?? null,
      adventure_id: target.adventureId ?? null,
      scenario_id: target.scenarioId ?? null,
      town_id: target.townId ?? null,
      run: target.run ?? null,
      note: target.note ?? "",
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `create game failed: ${res.status}`);
  }
  const data = await res.json();
  return data.session_id as string;
}

// ---- Runs & saves (Update 17 §D17-3) — Load Game ---------------------------- //
export interface RunSummary {
  run_id: string;
  name: string;
  party: { id: string; name: string; portrait: string }[];
  options: { difficulty: string; hardcore: boolean; everquest: boolean };
  created_at: string;
  updated_at: string;
  dead: boolean;
  save_count?: number;
  latest_label?: string;
}
export interface SaveRow {
  save_id: string;
  saved_at: string;
  label: string;
  kind: string;
  auto: boolean;
}
export interface RunDetail extends RunSummary {
  saves: SaveRow[]; // oldest → newest
}

export async function fetchRuns(): Promise<RunSummary[]> {
  const res = await fetch("/api/runs");
  if (!res.ok) throw new Error(`runs load failed: ${res.status}`);
  return (await res.json()).runs as RunSummary[];
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) throw new Error(`run load failed: ${res.status}`);
  return res.json();
}

// Rebuild the save's session (the exact adventure + party it points at) and
// return its id; continuing appends new saves — a fork when the save was not
// the newest.
export async function loadSave(runId: string, saveId: string): Promise<string> {
  const res = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/saves/${encodeURIComponent(saveId)}/load`,
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `load failed: ${res.status}`);
  }
  return (await res.json()).session_id as string;
}

export async function deleteSave(runId: string, saveId: string): Promise<void> {
  const res = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/saves/${encodeURIComponent(saveId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

export async function deleteRun(runId: string): Promise<void> {
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

// ---- Adventures (Update 10) ------------------------------------------------ //
export async function fetchAdventure(id: string): Promise<AdventureDetail> {
  const res = await fetch(`/api/adventures/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`adventure load failed: ${res.status}`);
  return res.json();
}

// Update the adventure-level fields (name, flavor, the three narrations) —
// phases are edited as encounters through saveEncounter with the phase's id.
export async function saveAdventureInfo(
  id: string,
  patch: { name?: string; flavor?: string; narrations?: string[] },
): Promise<AdventureOption> {
  const res = await fetch(`/api/adventures/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `save failed: ${res.status}`);
  }
  const data = await res.json();
  return data.adventure as AdventureOption;
}

export async function deleteAdventure(id: string): Promise<void> {
  const res = await fetch(`/api/adventures/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `delete failed: ${res.status}`);
  }
}

// Generate + persist a whole three-phase adventure (one model call — slow).
export async function generateAdventure(
  character_ids: string[],
  difficulty: string,
  note: string,
): Promise<AdventureOption> {
  const res = await fetch("/api/adventures/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character_ids, difficulty, note }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `generate failed: ${res.status}`);
  }
  const data = await res.json();
  return data.adventure as AdventureOption;
}

// ---- The art queue ("Generate all art", §D10-6.4) --------------------------- //
export type ArtTarget = { encounterId?: string; adventureId?: string; townId?: string; items?: boolean };
function artQueueUrl(target: ArtTarget): string {
  if (target.items) return "/api/items/art/all";
  if (target.townId) return `/api/towns/${encodeURIComponent(target.townId)}/art/all`;
  return target.adventureId
    ? `/api/adventures/${encodeURIComponent(target.adventureId)}/art/all`
    : `/api/encounters/${encodeURIComponent(target.encounterId ?? "")}/art/all`;
}

// Enqueue every still-missing image (idempotent); returns current progress.
export async function startArtQueue(
  target: ArtTarget,
): Promise<ArtQueueStatus> {
  const res = await fetch(artQueueUrl(target), { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `art queue failed: ${res.status}`);
  }
  return res.json();
}

export async function artQueueStatus(
  target: ArtTarget,
): Promise<ArtQueueStatus> {
  const res = await fetch(artQueueUrl(target));
  if (!res.ok) throw new Error(`art queue status failed: ${res.status}`);
  return res.json();
}

export async function fetchLlmSettings(): Promise<LlmSettings> {
  const res = await fetch("/api/llm/settings");
  if (!res.ok) throw new Error(`llm settings failed: ${res.status}`);
  return res.json();
}

export async function saveLlmSettings(patch: LlmSettingsPatch): Promise<LlmSettings> {
  const res = await fetch("/api/llm/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `save failed: ${res.status}`);
  }
  return res.json();
}

// Generate + persist a new encounter scoped to the picked party; returns its meta.
export async function generateEncounter(
  character_ids: string[],
  difficulty: string,
  note: string,
): Promise<EncounterOption> {
  const res = await fetch("/api/encounters/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character_ids, difficulty, note }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `generate failed: ${res.status}`);
  }
  const data = await res.json();
  return data.encounter as EncounterOption;
}

// Generate (or regenerate) art for an encounter's scene backdrop or one enemy.
// `enemyId` is the POOL enemy id (a clone's `base_id`). `text` optionally
// overrides the saved description as the prompt subject (the editor passes its
// live textarea so what you see is what gets painted). Slow — the image model
// takes several seconds.
export async function generateArt(
  encounterId: string,
  kind: "scene" | "enemy",
  enemyId?: string,
  text?: string,
): Promise<{ url: string }> {
  const res = await fetch(`/api/encounters/${encodeURIComponent(encounterId)}/art`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, enemy_id: enemyId ?? null, text: text || null }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `art generation failed: ${res.status}`);
  }
  return res.json();
}

// Remove generated art (the file and the encounter's reference to it).
export async function removeArt(
  encounterId: string,
  kind: "scene" | "enemy",
  enemyId?: string,
): Promise<void> {
  const params = new URLSearchParams({ kind });
  if (enemyId) params.set("enemy_id", enemyId);
  const res = await fetch(
    `/api/encounters/${encodeURIComponent(encounterId)}/art?${params}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `art removal failed: ${res.status}`);
  }
}

export async function gameStatus(session_id: string): Promise<boolean> {
  const res = await fetch(`/api/games/${session_id}`);
  return res.ok;
}

// ---- Self-update + quit (appctl.py; shared updater in ltg_core.selfupdate) ----

export type UpdateStatus = {
  supported: boolean;
  behind?: number;
  target?: string;
  log?: string[];
  updated?: boolean;
  error?: string;
  detail?: string;
};

export async function checkUpdate(): Promise<UpdateStatus> {
  const res = await fetch("/api/update/check");
  if (!res.ok) throw new Error(`update check failed: ${res.status}`);
  return res.json();
}

export async function applyUpdate(): Promise<UpdateStatus> {
  const res = await fetch("/api/update/apply", { method: "POST" });
  if (!res.ok) throw new Error(`update failed: ${res.status}`);
  return res.json();
}

export async function quitApp(): Promise<void> {
  await fetch("/api/quit", { method: "POST" });
}


// ---- Towns & scenarios (Update 17 — Options → Towns / Scenarios) ------------ //
export async function fetchTowns(): Promise<TownOption[]> {
  const res = await fetch("/api/towns");
  if (!res.ok) throw new Error(`towns load failed: ${res.status}`);
  return (await res.json()).towns;
}
export async function fetchTown(id: string): Promise<TownDetail> {
  const res = await fetch(`/api/towns/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`town load failed: ${res.status}`);
  return res.json();
}
export async function generateTown(note: string): Promise<TownOption> {
  const res = await fetch("/api/towns/generate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `town generation failed: ${res.status}`);
  }
  return (await res.json()).town;
}
export async function deleteTown(id: string): Promise<void> {
  const res = await fetch(`/api/towns/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}
export async function generateTownArt(townId: string, kind: "town" | "location" | "npc", targetId?: string): Promise<{ url: string }> {
  const res = await fetch(`/api/towns/${encodeURIComponent(townId)}/art`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, target_id: targetId ?? null }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `art failed: ${res.status}`);
  }
  return res.json();
}
export async function fetchScenarios(): Promise<ScenarioOption[]> {
  const res = await fetch("/api/scenarios");
  if (!res.ok) throw new Error(`scenarios load failed: ${res.status}`);
  return (await res.json()).scenarios;
}
export async function fetchScenario(id: string): Promise<ScenarioDetail> {
  const res = await fetch(`/api/scenarios/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`scenario load failed: ${res.status}`);
  return res.json();
}
export async function generateScenario(townId: string, difficulty: string, note: string): Promise<ScenarioOption> {
  const res = await fetch("/api/scenarios/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ town_id: townId, difficulty, note }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `scenario generation failed: ${res.status}`);
  }
  return (await res.json()).scenario;
}
export async function deleteScenario(id: string): Promise<void> {
  const res = await fetch(`/api/scenarios/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}


// ---- Equipment (Update 17 §D17-4.3 — Options → Equipment) ------------------- //
export async function fetchItems(): Promise<ItemMeta[]> {
  const res = await fetch("/api/items");
  if (!res.ok) throw new Error(`items load failed: ${res.status}`);
  return (await res.json()).items;
}
export async function fetchItem(id: string): Promise<ItemView & { source: string }> {
  const res = await fetch(`/api/items/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`item load failed: ${res.status}`);
  return res.json();
}
export async function saveItem(item: Record<string, unknown>, id?: string): Promise<ItemMeta> {
  const res = await fetch("/api/items", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id ?? null, item }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `save failed: ${res.status}`);
  }
  return (await res.json()).item;
}
export async function deleteItem(id: string): Promise<void> {
  const res = await fetch(`/api/items/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}
export async function generateItemArt(id: string): Promise<{ url: string }> {
  const res = await fetch(`/api/items/${encodeURIComponent(id)}/art`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `art failed: ${res.status}`);
  }
  return res.json();
}
