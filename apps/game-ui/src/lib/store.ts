import { create } from "zustand";
import { GameSocket } from "./ws";
import type { CardView, GameSnapshot, LegalAction, TownSnapshot } from "./types";
import { buildChoices, castPayment, siteCount, targetAt, type Choice, type Choices } from "./choices";
import {
  FX_TTL,
  fxFromLog,
  stackModes,
  syncSeq,
  type DepartKind,
  type FxEvent,
} from "./fx";

export type ZoneModal = { kind: "library" | "graveyard" | "channel"; charId: string } | null;

// The about-to-resolve hold: how long an armed Pass All waits before firing
// its automated pass into an open window. The client-side half of the
// server's resolution pacing (session.py PACE_*) — in hotseat play nearly
// every window is answered by THIS client, so without the hold the whole
// stack collapses at click speed and the server pacer never gets a turn.
const AUTO_PASS_HOLD_MS = 900;

// The resolution hold (the beat after "what just happened"): fx kinds whose
// arrival gates the action UI until the choreography lands, and how long
// past the timeline tail the gate stays (the effect itself needs a moment
// to play out once mounted).
const HOLD_KINDS = new Set([
  "hit", "arcane", "strike", "bolt", "heal", "wound", "downed", "revive",
  "enemyact", "detonate", "ultimate", "enrage",
]);
const HOLD_SETTLE_MS = 680;

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
  // Scenario Mode (Update 17): the town-mode state (the session has no engine
  // state); null while a fight is on. Set directly — no choreography queue.
  town: TownSnapshot | null;
  showQuestLog: boolean;
  sheetFor: string | null; // character sheet modal: a character id, or null
  seats: Record<string, string | null>;
  you: string[];

  focusedId: string | null;
  // Intents-window hover wiring (D8-1.5): hovering a line highlights the enemy
  // and its target on the battlefield, and hovering the enemy highlights its line.
  hoverIntent: { enemyId: string; targetId: string | null } | null;
  armed: Armed | null; // a target selection in progress
  chooseModeFor: Choice | null; // a modal card awaiting a mode pick
  manaSelect: ManaSelect | null; // an ambiguous cast awaiting a mana pick
  zoneModal: ZoneModal;
  // Portrait inspection: the combatant id whose full write-up is open (the
  // modal derives the live view from the snapshot each render), or null.
  inspectId: string | null;
  // Characters auto-passing until the current stack episode resolves. Pass All
  // is a PER-CHARACTER commitment — "this character has nothing more to add for
  // the rest of THIS stack" — so it only ever passes for the character that
  // armed it; the player's OTHER characters keep their reaction windows and may
  // still respond (or arm their own Pass All). The commitment is scoped to the
  // stack episode it was armed against, identified by the root (bottom) item's
  // uid: it clears when the stack empties OR when a fresh episode opens (a new
  // root). This matters during the enemy step, where the server chains each
  // enemy's swing without ever emitting an empty-stack snapshot — without the
  // root check, one Pass All would silently decline a First Strike swing the
  // holder is owed against every LATER enemy in the same step.
  passAllFor: string[];
  // The root stack uid the current Pass All commitment is bound to (null when
  // no commitment is live). A different root in a new snapshot ends it.
  passAllRootUid: number | null;
  // Idempotency guard for the Pass All auto-submit: the signature of the last
  // game state we already auto-passed. The server re-broadcasts state for
  // reasons that DON'T advance the game (art refresh, a reconnect, a seat
  // change), and each such duplicate would otherwise fire a second pass for a
  // window already passed — the stale index racing the real one into an
  // "action index out of range" rejection (which also cancels the commitment).
  // Keyed off the snapshot's log high-water seq, which only moves on a real
  // state change, so a genuine next window still auto-passes.
  _lastAutoPassKey: string | null;
  error: string | null;
  gameOver: string | null;

  // Combat FX (one-shot visuals keyed off NEW log entries). `departures` maps
  // a just-vanished combatant to HOW it left (death / exile / bounce) so the
  // battlefield ghost can play the right send-off.
  fx: FxEvent[];
  departures: Record<string, DepartKind>;
  lastLogSeq: number | null;
  _stackModes: Record<string, string>;

  // The resolution hold: while a snapshot's choreography is still landing
  // (fx timeline tail), the action UI stays gated — the board finishes
  // RESOLVING before the player is PROMPTED. Epoch ms; 0 = not holding.
  // `_holdTick` bumps at expiry so gated components re-render open.
  holdUntil: number;
  _holdTick: number;
  // The presentation queue: arrived-but-not-yet-shown states. Each applies
  // only after the previous one's choreography has landed, so the WORLD
  // advances beat by beat instead of batches overlapping.
  _snapQueue: GameSnapshot[];
  // Pre-roll (Update 16): the queued state whose opening panel clip is
  // already playing on the OLD board, and how far into its timeline the
  // world state applies (the clip's impact moment). Null when not pre-rolling.
  _preroll: { snap: GameSnapshot; ms: number } | null;
  _applySnapshot: (snap: GameSnapshot, prerollMs?: number) => number;
  _drainPresent: () => void;

  // lifecycle
  connect: (sessionId: string) => void;
  disconnect: () => void;
  sendTown: (verb: string, payload?: Record<string, unknown>) => void;
  answerConfirm: (id: number, yes: boolean) => void;
  cancelConfirm: (id: number) => void;
  retryJob: () => void;
  setQuestLog: (open: boolean) => void;
  setSheetFor: (id: string | null) => void;
  handle: (msg: any) => void;

  // seats
  claim: (ids: string[]) => void;
  release: (ids: string[]) => void;

  // adventures (Update 10): confirm one controlled character's level-up.
  confirmLevelUp: (characterId: string, build: Record<string, unknown>) => void;

  // interaction (§4.6)
  setHoverIntent: (h: { enemyId: string; targetId: string | null } | null) => void;
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
  setInspect: (id: string | null) => void;
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
  hoverIntent: null,
  armed: null,
  chooseModeFor: null,
  manaSelect: null,
  zoneModal: null,
  inspectId: null,
  passAllFor: [],
  passAllRootUid: null,
  _lastAutoPassKey: null,
  error: null,
  gameOver: null,
  town: null,
  showQuestLog: false,
  sheetFor: null,
  fx: [],
  departures: {},
  lastLogSeq: null,
  _stackModes: {},
  holdUntil: 0,
  _holdTick: 0,
  _snapQueue: [],
  _preroll: null,

  connect: (sessionId) => {
    get().socket?.close();
    const socket = new GameSocket(sessionId, (msg) => get().handle(msg));
    set({ socket, sessionId, snapshot: null, gameOver: null, inspectId: null,
          town: null, showQuestLog: false, sheetFor: null,
          passAllFor: [], passAllRootUid: null, _lastAutoPassKey: null,
          fx: [], departures: {}, lastLogSeq: null, _stackModes: {},
          holdUntil: 0, _snapQueue: [], _preroll: null });
  },

  disconnect: () => {
    get().socket?.close();
    set({ socket: null, sessionId: null, connected: false, snapshot: null, town: null });
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
        if (msg.mode === "town" || msg.mode === "complete") {
          // Town mode (Update 17): no engine state, no choreography — the
          // town screen renders straight from the message. Leaving a fight
          // for town clears the battlefield and any queued beats.
          set({ town: msg as TownSnapshot, snapshot: null, gameOver: null,
                _snapQueue: [], holdUntil: 0, fx: [], armed: null });
          break;
        }
        if (get().town) set({ town: null }); // riding out: the fight takes over
        // THE PRESENTATION QUEUE: states are not applied on arrival — they
        // are applied in order, each held until the PREVIOUS state's
        // choreography has fully landed. Without this, every batch's effect
        // timeline starts at its own arrival moment, and with broadcasts
        // ~1s apart but choreography up to ~1.7s long, the next attack's
        // animations begin while the last one's are still ending — and the
        // board (HP, chronicle, stack, departures) jumps ahead of both.
        // Sequential application makes the WORLD move beat by beat, not
        // just the overlays.
        set((s) => ({ _snapQueue: [...s._snapQueue, msg as GameSnapshot] }));
        get()._drainPresent();
        break;
      }
      case "prompt":
        // priority is already carried inside `state`; nothing extra to store.
        break;
      case "prompt":
        // priority is already carried inside `state`; nothing extra to store.
        break;
      case "game_over": {
        // The end-of-battle modal must not jump the queue: let the final
        // batch's choreography land (the grand death, the victory/defeat
        // screen treatment) before the menu covers it.
        const wait = Math.max(0, get().holdUntil - Date.now())
          + get()._snapQueue.length * 1000 + 1200;
        window.setTimeout(() => set({ gameOver: msg.result }), wait);
        break;
      }
      case "error":
        if (msg.fatal) {
          // The session can never be reached (e.g. the server restarted and
          // in-memory sessions were wiped): stop the 1s reconnect loop for
          // good rather than hammering the dead id forever.
          get().socket?.close();
          set({ connected: false });
          get().setError(`${msg.message} — start a new game`);
          break;
        }
        get().setError(msg.message);
        set({ armed: null, chooseModeFor: null, manaSelect: null, passAllFor: [], passAllRootUid: null, _lastAutoPassKey: null });
        break;
    }
  },

  // internal — not part of the public interface but kept on the object for reuse
  _applySnapshot: (snap, prerollMs = 0) => {
    const lastSeq = get().lastLogSeq;
    const synced = syncSeq(lastSeq, snap.log);
    let fxState: Partial<StoreState> = { lastLogSeq: synced };
    let fired: FxEvent[] = [];
    if (lastSeq != null && synced === lastSeq) {
      const r = fxFromLog(snap, lastSeq, get()._stackModes);
      fired = r.events;
      if (prerollMs > 0) {
        // The opening clip already fired on the old board (see
        // _drainPresent); everything else lands relative to the impact.
        fired = fired
          .filter((e) => !(e.kind === "panel" && !(e.delayMs && e.delayMs > 0)))
          .map((e) => ({ ...e, delayMs: Math.max(0, (e.delayMs ?? 0) - prerollMs) }));
      }
      // The timeline scheduler: an event with a beat delay mounts LATER —
      // impact follows delivery, response follows impact. Only beat-zero
      // events ride in with the snapshot itself.
      const now = fired.filter((e) => !(e.delayMs && e.delayMs > 0));
      fxState = {
        lastLogSeq: r.maxSeq,
        fx: now.length ? [...get().fx, ...now] : get().fx,
        departures: Object.keys(r.departures).length
          ? { ...get().departures, ...r.departures }
          : get().departures,
      };
    } else if (synced !== lastSeq) {
      fxState = { lastLogSeq: synced, fx: [], departures: {} };
    }
    // A fresh authoritative state ends any optimistic arming (§4.6).
    set({ snapshot: snap, armed: null, chooseModeFor: null, manaSelect: null,
          _stackModes: stackModes(snap), ...fxState });
    for (const e of fired) {
      const mountAt = e.delayMs ?? 0;
      if (mountAt > 0) {
        window.setTimeout(
          () => set((s) => ({ fx: [...s.fx, e] })), mountAt);
      }
      window.setTimeout(
        () => set((s) => ({ fx: s.fx.filter((x) => x.key !== e.key) })),
        mountAt + FX_TTL[e.kind],
      );
    }
    // The resolution hold: when this batch carries real combat
    // choreography, gate the action UI until its timeline tail has
    // landed — the player watches the board RESOLVE, then gets the
    // prompt. This is what paces the fully-interactive flow (manual
    // passes, resource-rich windows) that never touches the server
    // pacer or Pass All. Holds only extend, never shrink.
    const dur = fired.some((e) => HOLD_KINDS.has(e.kind))
      ? fired.reduce((m, e) => Math.max(m, e.delayMs ?? 0), 0) + HOLD_SETTLE_MS
      : 0;
    get()._recomputeFocus();
    // Pass All: whenever a window opens for a character that armed it, pass
    // automatically — until the stack fully resolves, then reset. Windows
    // for characters that did NOT arm it stay interactive.
    const autoPassers = get().passAllFor;
    if (autoPassers.length) {
      // The commitment is bound to ONE stack episode, keyed by the root
      // (bottom) item's uid. It ends when the stack empties or when a fresh
      // episode opens under a different root — e.g. the next enemy's swing
      // in the same enemy step, which the holder may still First Strike.
      const rootUid = snap.stack.length ? snap.stack[0].uid : null;
      if (rootUid === null || rootUid !== get().passAllRootUid) {
        set({ passAllFor: [], passAllRootUid: null, _lastAutoPassKey: null }); // episode ended
      } else {
        const pass = snap.legal_actions.find(
          (a) => a.kind === "pass" && autoPassers.includes(a.actor_id),
        );
        // Only auto-pass ONCE per real state. A re-broadcast of an
        // already-passed window (art refresh / reconnect / seat change)
        // carries the same log high-water seq; firing again would submit a
        // now-stale index (→ "action index out of range"). A genuine next
        // window advances the log, so its key differs and the pass fires.
        const stateSeq = snap.log.reduce((m, e) => Math.max(m, e.seq ?? -1), -1);
        if (pass) {
          const key = `${rootUid}@${stateSeq}#${pass.index}`;
          if (get()._lastAutoPassKey !== key) {
            set({ _lastAutoPassKey: key });
            // The about-to-resolve hold: an AUTOMATED pass waits a beat
            // before firing, so the window it answers is actually SEEN
            // (the stack row glows, the acting card embers) before the
            // resolution lands — the client-side half of the server's
            // resolution pacing. A manual click never waits. At fire
            // time the world may have moved on (a fresh snapshot, the
            // episode ended, someone acted): every check below bails
            // out; a genuine next window re-schedules its own hold.
            window.setTimeout(() => {
              if (get()._lastAutoPassKey !== key) return;
              const s = get().snapshot;
              if (!s) return;
              const seqNow = s.log.reduce((m, e) => Math.max(m, e.seq ?? -1), -1);
              const still = s.legal_actions.find(
                (a) => a.kind === "pass" && a.index === pass.index
                  && a.actor_id === pass.actor_id);
              if (seqNow !== stateSeq || !still) return;
              get().submitIndex(pass.index);
            }, AUTO_PASS_HOLD_MS);
          }
        }
        // else: a non-committed character (or another client) holds
        // priority, or a forced choice is open — wait for the player.
      }
    }
    return dur;
  },

  _drainPresent: () => {
    // Applies queued states in order, one per choreography window. When the
    // current window is still open the pending expiry timeout re-drains;
    // batches with no choreography apply straight through.
    if (Date.now() < get().holdUntil) return;
    const q = get()._snapQueue;
    if (!q.length) return;
    const snap = q[0];
    set({ _snapQueue: q.slice(1) });
    // Pre-roll (Update 16): if this batch OPENS with a hero's panel clip, the
    // clip must lead the world — play it now over the OLD board, hold the
    // state (HP, deaths, hit flashes) until the clip's impact moment, then
    // apply. Without this the enemy visibly dies before the swing.
    const pre = get()._preroll;
    let prerollMs = 0;
    if (pre && pre.snap === snap) {
      prerollMs = pre.ms;
      set({ _preroll: null });
    } else {
      const lastSeq = get().lastLogSeq;
      const synced = syncSeq(lastSeq, snap.log);
      if (lastSeq != null && synced === lastSeq) {
        const peek = fxFromLog(snap, lastSeq, get()._stackModes);
        if (peek.preroll > 0) {
          const leadEvents = peek.events.filter(
            (e) => e.kind === "panel" && !(e.delayMs && e.delayMs > 0));
          set((s) => ({ fx: [...s.fx, ...leadEvents], _preroll: { snap, ms: peek.preroll },
                        _snapQueue: [snap, ...s._snapQueue], holdUntil: Date.now() + peek.preroll }));
          for (const e of leadEvents) {
            window.setTimeout(
              () => set((s) => ({ fx: s.fx.filter((x) => x.key !== e.key) })), FX_TTL[e.kind]);
          }
          window.setTimeout(() => {
            set({ _holdTick: Date.now() });
            get()._drainPresent();
          }, peek.preroll + 20);
          return;
        }
      }
    }
    let dur = get()._applySnapshot(snap, prerollMs);
    // Backlog collapse: if the queue is deep (a long Pass-All chain, a
    // reconnect), shorten each beat so presentation lag stays bounded.
    if (get()._snapQueue.length > 3) dur = Math.min(dur, 600);
    if (dur > 0) {
      set({ holdUntil: Date.now() + dur });
      window.setTimeout(() => {
        set({ _holdTick: Date.now() });
        get()._drainPresent();
      }, dur + 20);
    } else if (get()._snapQueue.length) {
      get()._drainPresent();
    }
  },

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
  // Scenario Mode (Update 17): town verbs, the all-players confirmation, jobs.
  sendTown: (verb, payload) => get().socket?.send({ type: "town", verb, payload: payload ?? {} }),
  answerConfirm: (id, yes) => get().socket?.send({ type: "confirm", id, yes }),
  cancelConfirm: (id) => get().socket?.send({ type: "confirm", id, cancel: true }),
  retryJob: () => get().socket?.send({ type: "retry_job" }),
  setQuestLog: (open) => set({ showQuestLog: open }),
  setSheetFor: (id) => set({ sheetFor: id }),
  release: (ids) => get().socket?.send({ type: "release_seat", character_ids: ids }),

  confirmLevelUp: (characterId, build) =>
    get().socket?.send({ type: "confirm_level_up", character_id: characterId, build }),

  setHoverIntent: (h) => set({ hoverIntent: h }),

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
  // mana payment can prompt a pick before the action is sent. The Skill pays
  // mana exactly like a cast (engine: _do_use_skill → _pay), so it detours too;
  // the Ultimate never costs mana (the gauge is the cost) and submits directly.
  _finishAction: (kind: string, actions: LegalAction[]) => {
    if (kind === "cast" || kind === "use_skill") get().beginCast(actions);
    else get().submitIndex(actions[0].index);
  },

  beginCast: (actions) => {
    const action = actions[0];
    const snap = get().snapshot;
    const char = snap?.characters.find((c) => c.id === action.actor_id) ?? null;
    // The card being paid for: a hand card for a cast, the Skill face for
    // use_skill (full card fields ship for controlled characters).
    const card =
      char?.hand?.find((c) => c.id === action.card_id)
      ?? (char?.skill?.id === action.card_id && char.skill.cost != null
        ? (char.skill as CardView)
        : null);
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
    const armed = get().passAllFor;
    if (armed.includes(pass.actor_id)) {
      // Already committed — clicking again cancels this character's auto-pass.
      const remaining = armed.filter((id) => id !== pass.actor_id);
      set({ passAllFor: remaining, passAllRootUid: remaining.length ? get().passAllRootUid : null });
      return;
    }
    // Bind the commitment to the episode it was armed against (the root item).
    const rootUid = snap!.stack.length ? snap!.stack[0].uid : null;
    // Record this window as already-passed so a re-broadcast of the SAME state
    // (before the server processes this submit) can't fire a duplicate pass.
    const stateSeq = snap!.log.reduce((m, e) => Math.max(m, e.seq ?? -1), -1);
    set({ passAllFor: [...armed, pass.actor_id], passAllRootUid: rootUid,
          _lastAutoPassKey: `${rootUid}@${stateSeq}#${pass.index}`,
          armed: null, chooseModeFor: null });
    get().submitIndex(pass.index);
  },

  openZone: (z) => set({ zoneModal: z }),

  setInspect: (id) => set({ inspectId: id }),

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
