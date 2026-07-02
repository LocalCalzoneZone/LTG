// REST lobby client. Same-origin (the server serves the built client), so
// relative URLs work in prod; in dev Vite proxies /api to the server.
import type { CharacterOption, SetupOptions } from "./types";

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

export async function createGame(character_ids: string[], encounter_id: string): Promise<string> {
  const res = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character_ids, encounter_id }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `create game failed: ${res.status}`);
  }
  const data = await res.json();
  return data.session_id as string;
}

export async function gameStatus(session_id: string): Promise<boolean> {
  const res = await fetch(`/api/games/${session_id}`);
  return res.ok;
}
