import { create } from "zustand";
import { GameSocket } from "./ws";
import type { GameSnapshot, LegalAction } from "./types";
import { buildChoices, castPayment, siteCount, targetAt, type Choice, type Choices } from "./choices";

export type ZoneModal = { kind: "library" | "graveyard" | "channel"; charId: string } | null;

// A cast whose generic mana can be paid more than one way: the player clicks mana
// symbols to choose which colours to spend before the cast is submitted.
export interface ManaSelect {
  actorId: string;
  index: number; // the cast action's legal index
  cardId: string | null;
  cardName: string;
  colored: string[]; // mandatory coloured pips, spent automatically
  generic: number; // how many generic pips the player still picks
  picked: string[]; // generic colours chosen so far
}

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
  // Per-site effect labels (from the action's `target_labels`) so the arming hint
  // can name what each pick is for — shared across a choice's candidates.
  targetLabels: (string | null)[];
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
  manaSelect: ManaSelect | null; // an ambiguous cast awaiting a mana pick
  zoneModal: ZoneModal;
  // The character id auto-passing every reaction window it holds priority in until
  // the stack fully resolves (null = off). Scoped to one character — other party
  // members still decide for themselves.
  passAllFor: string | null;
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
  submitIndex: (index: number, mana?: string[]) => void;
  startPassAll: () => void; // pass now and keep passing until the stack resolves
  _arm: (c: Choice) => void;
  _finishAction: (kind: string, action: LegalAction) => void; // submit, or detour a cast
  // Casts route through here so an ambiguous mana payment can prompt a pick first.
  beginCast: (action: LegalAction) => void;
  pickMana: (color: string) => void; // choose one generic mana in the pending cast
  resetMana: () => void; // clear the picks and start the selection over

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
  manaSelect: null,
  zoneModal: null,
  passAllFor: null,
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
        set({ snapshot: snap, armed: null, chooseModeFor: null, manaSelect: null });
        get()._recomputeFocus();
        // Pass All: auto-pass for the initiating character only, each time it holds
        // priority, until the stack fully resolves — then reset. Other characters'
        // priority windows are left for the player to decide.
        const forId = get().passAllFor;
        if (forId != null) {
          if (snap.stack.length === 0) {
            set({ passAllFor: null }); // stack resolved — done
          } else {
            const pass = snap.legal_actions.find(
              (a) => a.kind === "pass" && a.actor_id === forId,
            );
            if (pass) get().submitIndex(pass.index);
            // else: another character holds priority (or a forced choice) — wait.
          }
        }
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
        set({ armed: null, chooseModeFor: null, manaSelect: null, passAllFor: null });
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
      // Untargeted (Defend / Pass / a self-only cast): finish the sole action.
      set({ armed: null, chooseModeFor: null });
      get()._finishAction(c.kind, c.candidates[0]);
      return;
    }
    set({
      armed: { label: c.label, kind: c.kind, cardId: c.cardId ?? null,
               candidates: c.candidates, site: 0, numSites: n, picks: [],
               targetLabels: c.candidates[0]?.target_labels ?? [] },
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
      set({ armed: null });
      get()._finishAction(armed.kind, filtered[0]);
      return;
    }
    set({ armed: { ...armed, candidates: filtered, site: nextSite, picks: [...armed.picks, id] } });
  },

  cancelArm: () => set({ armed: null, chooseModeFor: null, manaSelect: null }),

  submitIndex: (index, mana) => {
    const action: Record<string, unknown> = { index };
    if (mana) action.mana = mana;
    get().socket?.send({ type: "submit_action", action });
  },

  // Submit a finished action — but casts detour through beginCast so an ambiguous
  // mana payment can prompt a pick before the action is sent.
  _finishAction: (kind: string, action: LegalAction) => {
    if (kind === "cast") get().beginCast(action);
    else get().submitIndex(action.index);
  },

  beginCast: (action) => {
    const snap = get().snapshot;
    const char = snap?.characters.find((c) => c.id === action.actor_id) ?? null;
    const card = char?.hand?.find((c) => c.id === action.card_id) ?? null;
    if (!char || !card) {
      get().submitIndex(action.index); // no hand info — let the engine pay deterministically
      return;
    }
    const pool: Record<string, number> = {};
    for (const m of char.mana.by_color) pool[m.color] = m.pool;
    const pay = castPayment(card.cost, pool);
    if (!pay.ambiguous) {
      get().submitIndex(action.index); // one valid payment — no need to ask
      return;
    }
    set({
      manaSelect: {
        actorId: char.id, index: action.index, cardId: card.id, cardName: card.name,
        colored: pay.colored, generic: pay.generic, picked: [],
      },
      armed: null,
    });
  },

  pickMana: (color) => {
    const ms = get().manaSelect;
    if (!ms || ms.picked.length >= ms.generic) return;
    const picked = [...ms.picked, color];
    if (picked.length >= ms.generic) {
      // Full payment settled — spend the coloured pips plus the chosen generic.
      set({ manaSelect: null });
      get().submitIndex(ms.index, [...ms.colored, ...picked]);
      return;
    }
    set({ manaSelect: { ...ms, picked } });
  },

  resetMana: () => {
    const ms = get().manaSelect;
    if (ms) set({ manaSelect: { ...ms, picked: [] } });
  },

  startPassAll: () => {
    const snap = get().snapshot;
    const pass = snap?.legal_actions.find((a) => a.kind === "pass");
    if (!pass) return;
    set({ passAllFor: pass.actor_id, armed: null, chooseModeFor: null });
    get().submitIndex(pass.index);
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
