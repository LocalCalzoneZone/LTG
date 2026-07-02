// Groups the engine's flat legal actions into UI affordances, mirroring the
// cockpit's `build_menu` (presentation only). Each Choice carries the raw
// candidate actions it covers; the store's arming logic walks their per-site
// `targets` to drive selection (single-target, independent multi-target, or a
// stack-targeting counter) and submits the chosen action's index verbatim.

import type { LegalAction } from "./types";

export interface Choice {
  key: string;
  kind: string; // engine action kind
  cardId?: string | null;
  mode?: number | null;
  label: string;
  // For a modal card: one sub-choice per mode (drives the choose-one modal §4.8).
  modes?: Choice[];
  // Every legal action this choice covers (one per target / target-combination).
  candidates: LegalAction[];
}

/** The target id an action picks at a given site: the per-site `targets` tuple for
 *  multi-target casts, else the single `target_id` (site 0 only). */
export function targetAt(a: LegalAction, site: number): string | null {
  if (a.targets && a.targets.length > 0) return a.targets[site] ?? null;
  return site === 0 ? a.target_id : null;
}

/** How many target sites a choice's candidates require (0 == untargeted). */
export function siteCount(candidates: LegalAction[]): number {
  const a = candidates[0];
  if (!a) return 0;
  if (a.targets && a.targets.length > 0) return a.targets.length;
  return candidates.some((c) => c.target_id != null) ? 1 : 0;
}

function nameFromLabel(label: string): string {
  return label.split(" on ")[0].trim(); // strip the per-target suffix
}

export interface Choices {
  attack?: Choice;
  defend?: Choice;
  move?: Choice;
  mitigate?: Choice;
  pass?: Choice;
  endTurn?: Choice;
  dropChannels?: Choice;
  casts: Record<string, Choice>; // cardId -> Choice (may carry modes[])
  mana: { color: string; index: number; label: string }[];
  // A mandatory mid-resolution pick (move_card / scry): rendered as a prompt modal.
  cardPicks: { index: number; label: string; kind: string }[];
}

export function buildChoices(legal: LegalAction[]): Choices {
  const out: Choices = { casts: {}, mana: [], cardPicks: [] };
  const pick = (kind: string) => legal.filter((a) => a.kind === kind);

  const mk = (key: string, kind: string, candidates: LegalAction[], label: string): Choice => ({
    key, kind, candidates, label,
  });

  const attacks = pick("attack");
  if (attacks.length) out.attack = mk("attack", "attack", attacks, "Attack");
  const defend = pick("defend");
  if (defend.length) out.defend = mk("defend", "defend", defend, "Defend");
  const moves = pick("move");
  if (moves.length) out.move = mk("move", "move", moves, "Move");
  const mitigates = pick("mitigate");
  if (mitigates.length) out.mitigate = mk("mitigate", "mitigate", mitigates, "Mitigate");
  const pass = pick("pass");
  if (pass.length) out.pass = mk("pass", "pass", pass, "Pass");
  const end = pick("end_turn");
  if (end.length) out.endTurn = mk("end_turn", "end_turn", end, "End Turn");
  const drop = pick("drop_channels");
  if (drop.length) out.dropChannels = mk("drop", "drop_channels", drop, drop[0].label);

  // Casts, grouped by card. A card with >1 distinct mode becomes a modal choice.
  const casts = pick("cast");
  const byCard: Record<string, LegalAction[]> = {};
  for (const a of casts) (byCard[a.card_id ?? "?"] ||= []).push(a);
  for (const [cid, group] of Object.entries(byCard)) {
    const modes = [...new Set(group.map((a) => a.mode))].filter((m) => m != null) as number[];
    if (modes.length > 1) {
      const modeChoices = modes.map((m) => {
        const g = group.filter((a) => a.mode === m);
        return { key: `cast:${cid}:${m}`, kind: "cast", cardId: cid, mode: m,
                 label: nameFromLabel(g[0].label), candidates: g } as Choice;
      });
      out.casts[cid] = { key: `cast:${cid}`, kind: "cast", cardId: cid,
                         label: "Choose a mode", candidates: group, modes: modeChoices };
    } else {
      out.casts[cid] = { key: `cast:${cid}`, kind: "cast", cardId: cid, mode: group[0].mode,
                         label: nameFromLabel(group[0].label), candidates: group };
    }
  }

  for (const a of pick("choose_mana")) {
    if (a.color) out.mana.push({ color: a.color, index: a.index, label: a.label });
  }
  for (const a of legal.filter((x) => x.kind === "choose_card" || x.kind === "choose_scry")) {
    out.cardPicks.push({ index: a.index, label: a.label, kind: a.kind });
  }

  return out;
}
