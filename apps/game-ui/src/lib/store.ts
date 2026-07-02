import { create } from "zustand";
import { GameSocket } from "./ws";
import type { GameSnapshot, LegalAction } from "./types";
import { buildChoices, siteCount, targetAt, type Choice, type Choices } from "./choices";

export type ZoneModal = { kind: "library" | "graveyard" | "channel"; charId: string } | null;

// A target-selection in progress. Walks the candidate actions site-by-site:
// single-target (one site), independent multi-target (e.g. Agony Warp), or a
// stack-targeting counter (target ids look like "#<uid>").
export interface Armed {
  label: string;
  kind: string;
  cardId: string | null;
  candidates: LegalAction[]; // remaining actions matching the picks so far
  site: number; // which target site we're choosing now
  numSites: number;
  picks: string[]; // chosen target ids so far (for the hint)
}

/** The set of legal target ids for the current armed site (entity ids, rows, or
 *  "#<uid>" stack refs). Empty when nothing is armed. */
export function armedTargetIdSet(armed: Armed | null): Set<string> {
  if (!armed) return new Set();
  const ids = armed.candidates
    .map((a) => targetAt(a, armed.site))
    .filter((x): x is string => x != null);
  return new Set(ids);
}

interface StoreState {
  socket: GameSocket | null;
  sessionId: string | null;
  clientId: string | null;
  connected: boolean;

  snapshot: GameSnapshot | null;
  seats: Record<string, string | null>;
  you: string[];

  focusedId: string | null;
  armed: Armed | null; // a target selection in progress
  chooseModeFor: Choice | null; // a modal card awaiting a mode pick
  zoneModal: ZoneModal;
  error: string | null;
  gameOver: string | null;

  // lifecycle
  connect: (sessionId: string) => void;
  disconnect: () => void;
  handle: (msg: any) => void;

  // seats
  claim: (ids: string[]) => void;
  release: (ids: string[]) => void;

  // interaction (§4.6)
  setFocus: (id: string) => void;
  selectChoice: (c: Choice) => void; // arm a target, submit immediately, or open a mode modal
  pickMode: (sub: Choice) => void;
  pickTargetId: (id: string) => void; // pick a target for the current armed site
  cancelArm: () => void;
  submitIndex: (index: number) => void;
  _arm: (c: Choice) => void;

  openZone: (z: ZoneModal) => void;
  setError: (m: string | null) => void;

  // internal
  _recomputeFocus: () => void;
}

let errorTimer: number | undefined;

export const useGame = create<StoreState>((set, get) => ({
  socket: null,
  sessionId: null,
  clientId: null,
  connected: false,
  snapshot: null,
  seats: {},
  you: [],
  focusedId: null,
  armed: null,
  chooseModeFor: null,
  zoneModal: null,
  error: null,
  gameOver: null,

  connect: (sessionId) => {
    get().socket?.close();
    const socket = new GameSocket(sessionId, (msg) => get().handle(msg));
    set({ socket, sessionId, snapshot: null, gameOver: null });
  },

  disconnect: () => {
    get().socket?.close();
    set({ socket: null, sessionId: null, connected: false, snapshot: null });
  },

  handle: (msg) => {
    switch (msg.type) {
      case "_open":
        set({ connected: true });
        break;
      case "_close":
        set({ connected: false });
        break;
      case "hello":
        set({ clientId: msg.client_id });
        break;
      case "seats":
        set({ seats: msg.seats, you: msg.you });
        get()._recomputeFocus();
        break;
      case "state": {
        const snap = msg as GameSnapshot;
        // A fresh authoritative state ends any optimistic arming (§4.6).
        set({ snapshot: snap, armed: null, chooseModeFor: null });
        get()._recomputeFocus();
        break;
      }
      case "prompt":
        // priority is already carried inside `state`; nothing extra to store.
        break;
      case "game_over":
        set({ gameOver: msg.result });
        break;
      case "error":
        get().setError(msg.message);
        set({ armed: null, chooseModeFor: null });
        break;
    }
  },

  // internal — not part of the public interface but kept on the object for reuse
  _recomputeFocus: () => {
    const { snapshot, you, focusedId } = get() as any;
    if (!snapshot) return;
    const controlled = new Set(you);
    const holder = snapshot.priority?.holder_character_id ?? null;
    let focus = focusedId;
    if (holder && controlled.has(holder)) {
      focus = holder; // surface whoever must act (great for single-player)
    } else if (!focus || !controlled.has(focus)) {
      focus = you.length ? you[0] : (snapshot.characters[0]?.id ?? null);
    }
    if (focus !== focusedId) set({ focusedId: focus });
  },

  claim: (ids) => get().socket?.send({ type: "claim_seat", character_ids: ids }),
  release: (ids) => get().socket?.send({ type: "release_seat", character_ids: ids }),

  setFocus: (id) => set({ focusedId: id, armed: null, chooseModeFor: null }),

  selectChoice: (c) => {
    if (c.modes && c.modes.length) {
      set({ chooseModeFor: c, armed: null });
      return;
    }
    get()._arm(c);
  },

  pickMode: (sub) => {
    set({ chooseModeFor: null });
    get()._arm(sub);
  },

  // Begin (or immediately resolve) a target selection for a choice.
  _arm: (c) => {
    const n = siteCount(c.candidates);
    if (n === 0) {
      // Untargeted (Defend / Pass / a self-only cast): submit the sole action.
      get().submitIndex(c.candidates[0].index);
      set({ armed: null, chooseModeFor: null });
      return;
    }
    set({
      armed: { label: c.label, kind: c.kind, cardId: c.cardId ?? null,
               candidates: c.candidates, site: 0, numSites: n, picks: [] },
      chooseModeFor: null,
    });
  },

  pickTargetId: (id) => {
    const armed = get().armed;
    if (!armed) return;
    const filtered = armed.candidates.filter((a) => targetAt(a, armed.site) === id);
    if (!filtered.length) return;
    const nextSite = armed.site + 1;
    // Done when we've filled every site, or only one action can still match.
    if (nextSite >= armed.numSites || filtered.length === 1) {
      get().submitIndex(filtered[0].index);
      set({ armed: null });
      return;
    }
    set({ armed: { ...armed, candidates: filtered, site: nextSite, picks: [...armed.picks, id] } });
  },

  cancelArm: () => set({ armed: null, chooseModeFor: null }),

  submitIndex: (index) => {
    get().socket?.send({ type: "submit_action", action: { index } });
  },

  openZone: (z) => set({ zoneModal: z }),

  setError: (m) => {
    window.clearTimeout(errorTimer);
    set({ error: m });
    if (m) errorTimer = window.setTimeout(() => set({ error: null }), 3500);
  },
}));

// ---- selectors / derived helpers ------------------------------------------ //
/** The structured choices for the focused character — only non-empty when that
 *  character is the priority holder AND controlled (legal actions ship for the
 *  holder only). Otherwise the action bar / hand render disabled. */
export function focusedChoices(state: StoreState): Choices | null {
  const { snapshot, focusedId } = state;
  if (!snapshot || !focusedId) return null;
  const holder = snapshot.priority.holder_character_id;
  if (holder !== focusedId) return null;
  if (!snapshot.legal_actions.length) return null;
  return buildChoices(snapshot.legal_actions);
}
