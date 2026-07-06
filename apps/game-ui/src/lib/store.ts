import { create } from "zustand";
import { GameSocket } from "./ws";
import type { GameSnapshot, LegalAction } from "./types";
import { buildChoices, castPayment, siteCount, targetAt, type Choice, type Choices } from "./choices";

export type ZoneModal = { kind: "library" | "graveyard" | "channel"; charId: string } | null;

// A cast that needs the player to pay its cost by hand ({X}, or a generic
// portion payable more than one way): the player clicks mana symbols for the
// ENTIRE cost — coloured pips included, in any order — then hits Cast. Nothing
// is set aside automatically: what you see in the pool is what you pay from,
// exactly like tapping lands for a full MTG cost.
export interface ManaSelect {
  actorId: string;
  index: number; // the cast action's legal index (the X=0 one for an {X} cast)
  cardId: string | null;
  cardName: string;
  cost: string; // the full pip string ("{X}{U}{B}{R}") shown in the header
  colored: string[]; // the coloured pips the payment must include
  generic: number; // the fixed generic portion of the cost
  picked: string[]; // every colour clicked so far (the whole payment)
  // {X} cast: total-picks -> legal index for that X (total = coloured + generic
  // + X). Every extra pip past the base cost raises X. Null for a non-X cast.
  xByCount: Record<number, number> | null;
  maxPicks: number; // coloured + generic (+ the largest affordable X)
}

/** How the picks so far pay the cost: each pick first covers a matching coloured
 *  pip, the rest count toward the generic (+X) portion — order-free, so the
 *  player can click colours in any sequence and never dead-ends. */
export function paymentState(ms: ManaSelect) {
  const needC: Record<string, number> = {};
  for (const c of ms.colored) needC[c] = (needC[c] ?? 0) + 1;
  const paidC: Record<string, number> = {};
  let genericPaid = 0;
  for (const p of ms.picked) {
    if ((paidC[p] ?? 0) < (needC[p] ?? 0)) paidC[p] = (paidC[p] ?? 0) + 1;
    else genericPaid += 1;
  }
  const coloredPaid = Object.values(paidC).reduce((a, b) => a + b, 0);
  return {
    needC, paidC, genericPaid,
    coloredLeft: ms.colored.length - coloredPaid,
    genericCap: ms.maxPicks - ms.colored.length,
  };
}

/** Whether one more `color` pip is a legal pick: still in the pool, and it either
 *  covers an unmet coloured pip or fits the generic/X capacity. */
export function canPickMana(ms: ManaSelect, color: string, pool: Record<string, number>): boolean {
  if (ms.picked.length >= ms.maxPicks) return false;
  const spent = ms.picked.filter((x) => x === color).length;
  if ((pool[color] ?? 0) - spent <= 0) return false;
  const st = paymentState(ms);
  return (st.paidC[color] ?? 0) < (st.needC[color] ?? 0) || st.genericPaid < st.genericCap;
}

/** The legal index the current picks cast, or null while the payment is short:
 *  every coloured pip covered, and the total matches the cost (for an {X} cast,
 *  any total with a matching X action). */
export function castIndexFor(ms: ManaSelect): number | null {
  const st = paymentState(ms);
  if (st.coloredLeft > 0) return null;
  if (ms.xByCount) return ms.xByCount[ms.picked.length] ?? null;
  return ms.picked.length === ms.maxPicks ? ms.index : null;
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
  // Submit a finished action; `actions` are the matching candidates (several for
  // an {X} cast — one per affordable X — the cast detour then asks which).
  _finishAction: (kind: string, actions: LegalAction[]) => void;
  // Casts route through here so an {X} choice / ambiguous payment can prompt first.
  beginCast: (actions: LegalAction[]) => void;
  pickMana: (color: string) => void; // add one pip to the pending cast's payment
  confirmMana: () => void; // submit the cast once the picks cover the cost
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
      get()._finishAction(c.kind, c.candidates);
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
      get()._finishAction(armed.kind, filtered);
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
  _finishAction: (kind: string, actions: LegalAction[]) => {
    if (kind === "cast") get().beginCast(actions);
    else get().submitIndex(actions[0].index);
  },

  beginCast: (actions) => {
    const action = actions[0];
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
    const base = pay.colored.length + pay.generic;
    if (action.x != null) {
      // An {X} cast ALWAYS opens the picker: the player pays the WHOLE cost by
      // hand (coloured pips included); every pip past the base cost raises X,
      // and Cast locks in the action matching the total.
      const xByCount: Record<number, number> = {};
      let maxPicks = base;
      for (const a of actions) {
        if (a.x == null) continue;
        xByCount[base + a.x] = a.index;
        maxPicks = Math.max(maxPicks, base + a.x);
      }
      set({
        manaSelect: {
          actorId: char.id, index: action.index, cardId: card.id, cardName: card.name,
          cost: card.cost, colored: pay.colored, generic: pay.generic, picked: [],
          xByCount, maxPicks,
        },
        armed: null,
      });
      return;
    }
    if (!pay.ambiguous) {
      get().submitIndex(action.index); // one valid payment — no need to ask
      return;
    }
    set({
      manaSelect: {
        actorId: char.id, index: action.index, cardId: card.id, cardName: card.name,
        cost: card.cost, colored: pay.colored, generic: pay.generic, picked: [],
        xByCount: null, maxPicks: base,
      },
      armed: null,
    });
  },

  pickMana: (color) => {
    const ms = get().manaSelect;
    if (!ms) return;
    const snap = get().snapshot;
    const char = snap?.characters.find((c) => c.id === ms.actorId) ?? null;
    const pool: Record<string, number> = {};
    for (const m of char?.mana.by_color ?? []) pool[m.color] = m.pool;
    if (!canPickMana(ms, color, pool)) return;
    set({ manaSelect: { ...ms, picked: [...ms.picked, color] } });
  },

  confirmMana: () => {
    const ms = get().manaSelect;
    if (!ms) return;
    const index = castIndexFor(ms);
    if (index == null) return; // the payment is still short
    set({ manaSelect: null });
    get().submitIndex(index, [...ms.picked]);
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
