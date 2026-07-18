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
  SetupOptions,
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

// Start a game on a standalone encounter, or an adventure (exactly one of the
// two ids) — an adventure session runs the three-act flow server-side.
export async function createGame(
  character_ids: string[],
  target: { encounterId?: string; adventureId?: string },
): Promise<string> {
  const res = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      character_ids,
      encounter_id: target.encounterId ?? null,
      adventure_id: target.adventureId ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `create game failed: ${res.status}`);
  }
  const data = await res.json();
  return data.session_id as string;
}

// ---- Adventures (Update 10) ------------------------------------------------ //
export async function fetchAdventure(id: string): Promise<AdventureDetail> {
  const res = await fetch(`/api/adventures/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`adventure load failed: ${res.status}`);
  return res.json();
}

// Update the adventure-level fields (name, flavor, the three narrations) —
// acts are edited as encounters through saveEncounter with the act's id.
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

// Generate + persist a whole three-act adventure (one model call — slow).
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
function artQueueUrl(target: { encounterId?: string; adventureId?: string }): string {
  return target.adventureId
    ? `/api/adventures/${encodeURIComponent(target.adventureId)}/art/all`
    : `/api/encounters/${encodeURIComponent(target.encounterId ?? "")}/art/all`;
}

// Enqueue every still-missing image (idempotent); returns current progress.
export async function startArtQueue(
  target: { encounterId?: string; adventureId?: string },
): Promise<ArtQueueStatus> {
  const res = await fetch(artQueueUrl(target), { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `art queue failed: ${res.status}`);
  }
  return res.json();
}

export async function artQueueStatus(
  target: { encounterId?: string; adventureId?: string },
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
