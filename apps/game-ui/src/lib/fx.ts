// The combat-FX layer: turns NEW engine log entries into one-shot visual
// effects. Pure mapping — the client still computes no rules; it only reacts
// to what the engine says happened. Entries are identified by `seq` (their
// absolute position in the engine log), so effects fire exactly once each.

import type { GameSnapshot, LogEntry } from "./types";

export type FxKind =
  | "hit" // attack damage connecting — a slash across the target
  | "arcane" // spell / ability damage — an aether burst on the target
  | "heal" // healing / regen — a vigor glow rising
  | "pump" // +X/+X (temporary or counters) — chevrons rising
  | "wound" // −X/−X — crimson chevrons sinking
  | "keyword" // a keyword granted — brass shimmer + the keyword chip
  | "stun" // stunned — crimson concentric rings + chip
  | "poison" // poisoned — a sickly pulse + chip
  | "skill" // a hero Skill goes off — brass sigil flare on the caster
  | "ultimate" // an Ultimate — golden shockwave on the caster + screen flash
  | "enrage" // a boss enrages — crimson flare on it + screen pulse
  | "detonate" // a charge windup erupts — brass shockwave on the enemy
  | "revive" // a hero stands back up — golden rise
  | "downed" // a hero is incapacitated — heavy crimson flash
  | "countered" // an action is cancelled — grey fizzle on its source
  | "defend" // Defend declared — a tide shield raised on the defender
  | "mitigate" // Mitigate declared — a parry sigil snapping in on the mitigator
  | "absorb" // damage soaked (mitigate / prevent / temp HP) — on the target
  | "strike" // melee blow landing — the ATTACKER's card lunges at its target
  | "bolt" // a projectile crossing the field (ranged shot / spell bolt)
  | "engrave" // permanent +1/+1 counters — stamped, not faded (vs `pump`)
  | "ward" // prevent / protection granted — a lingering ward ring
  | "draw" // a card drawn — the hand plays its glimmer (and audio, one day)
  | "vignette" // a hero takes a heavy hit — red edge-glow on the screen
  | "victory" // the fight is won — full-screen laurel treatment
  | "defeat" // the party falls — full-screen treatment
  | "passed" // an AUTO-pass fired — a visible beat, so resolutions never
  // feel like they jumped the queue (also stretches the scheduler's timeline)
  | "enemyact"; // an enemy's declared intent hits the stack — the card steps
  // forward with a crimson flare; the moment you are being asked to answer

export interface FxEvent {
  key: string; // unique per firing (seq + slot)
  kind: FxKind;
  entityId: string; // the card the effect plays over
  amount?: number; // scales the effect (damage / healing size)
  label?: string; // chip text (keyword name, etc.)
  screen?: boolean; // additionally fires the full-screen treatment
  targetId?: string; // strike: whom the lunge aims at
  sourceId?: string; // bolt: where the projectile launches from
  variant?: "arrow" | "arcane"; // bolt flavour (ranged shot vs spellfire)
  // Choreography (the timeline scheduler): ms after the snapshot lands before
  // this effect MOUNTS — the store defers insertion, so renderers never see
  // an event before its beat. Impact follows delivery; response follows impact.
  delayMs?: number;
  // The caster's first identity colour (W/U/B/R/G) when the log names a party
  // source — spell effects tint per school. Undefined = neutral palette.
  tint?: string;
}

// How long each effect stays mounted (ms) — matches its CSS animation.
export const FX_TTL: Record<FxKind, number> = {
  hit: 700,
  arcane: 900,
  heal: 1100,
  pump: 1000,
  wound: 1000,
  keyword: 1400,
  stun: 1300,
  poison: 1200,
  skill: 1200,
  ultimate: 1800,
  enrage: 1800,
  detonate: 1200,
  revive: 1400,
  downed: 1300,
  countered: 1100,
  defend: 1200,
  mitigate: 1100,
  absorb: 1000,
  strike: 500,
  bolt: 600,
  engrave: 1300,
  ward: 2600,
  draw: 900,
  vignette: 900,
  victory: 3400,
  defeat: 3400,
  passed: 900,
  enemyact: 1100,
};

// Departing-card treatments (the Battlefield ghost system): how a combatant
// LEAVES tells the player what happened to it.
export type DepartKind = "death" | "exile" | "bounce";
export const DEPART_MS: Record<DepartKind, number> = {
  death: 1400, // hold, flash, drain to black-and-white, crumble
  exile: 1000, // banished — a white flare and an implosion
  bounce: 900, // returned / suspended — slips away upward
};

/** label -> mode ("melee attack" | "ranged attack" | "spell" | "ability") for
 * everything currently on the stack — the FX layer uses the PREVIOUS
 * snapshot's map to classify a `damage` event's source action. */
export function stackModes(snapshot: GameSnapshot): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of snapshot.stack) {
    if (row.mode) out[row.label] = row.mode;
  }
  return out;
}

const str = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown): number | undefined =>
  typeof v === "number" ? v : undefined;

// The choreography beats (ms within a resolution): delivery leads, the impact
// answers it, the defence answers the impact. One resolution's scene ends
// before the next one starts; a long Pass-All chain is clamped so the tail
// never lags the authoritative board by more than ~1.5s.
const BEAT_IMPACT = 180;
const BEAT_RESPONSE = 340;
const BEAT_SCENE = 480; // how much board-time one damaging resolution occupies
const BEAT_CAP = 1500;

/** Map the log entries with seq > lastSeq onto FX events + departure kinds.
 * `modes` is the previous snapshot's stackModes (what was resolving). */
export function fxFromLog(
  snapshot: GameSnapshot,
  lastSeq: number,
  modes: Record<string, string>,
): { events: FxEvent[]; departures: Record<string, DepartKind>; maxSeq: number } {
  const entries = [...snapshot.log]
    .filter((e) => e.seq != null)
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)); // oldest → newest
  const maxSeq = entries.length ? (entries[entries.length - 1].seq ?? lastSeq) : lastSeq;
  const events: FxEvent[] = [];
  const departures: Record<string, DepartKind> = {};

  // Party casters by id — the school-tint lookup (enemies have no identity).
  const partyIds = new Map(snapshot.characters.map((c) => [c.id, c]));
  const tintOf = (id: string): string | undefined =>
    partyIds.get(id)?.mana?.identity_colors?.[0];

  // What is resolving right now, updated as we walk the batch in order: a
  // `resolve` names the action whose effects the following entries describe.
  let resolvingMode = "";
  // The scheduler cursors: `beat` anchors the current resolution's scene;
  // `cursor` is the running end of everything scheduled so far.
  let beat = 0;
  let cursor = 0;

  for (const e of entries) {
    const seq = e.seq ?? -1;
    if (seq <= lastSeq) continue;
    const d = (e.data ?? {}) as Record<string, unknown>;
    const push = (kind: FxKind, entityId: string, extra: Partial<FxEvent> = {}) => {
      if (!entityId) return;
      const offsets: Partial<Record<FxKind, number>> = {
        strike: 0,
        bolt: 0,
        hit: BEAT_IMPACT,
        arcane: BEAT_IMPACT,
        wound: BEAT_IMPACT,
        downed: BEAT_IMPACT,
        absorb: BEAT_RESPONSE,
      };
      const delayMs = Math.min(beat + (offsets[kind] ?? BEAT_IMPACT / 2), BEAT_CAP);
      events.push({ key: `${seq}:${events.length}`, kind, entityId, delayMs,
                    ...extra });
      if (offsets[kind] === BEAT_IMPACT) {
        cursor = Math.max(cursor, Math.min(beat + BEAT_SCENE, BEAT_CAP));
      }
    };

    switch (e.type) {
      case "resolve":
        resolvingMode = modes[str(d.label)] ?? "";
        beat = cursor; // a new scene opens where the last one ended
        break;
      case "damage": {
        const attack = resolvingMode.includes("attack");
        const ranged = resolvingMode.includes("ranged");
        const target = str(d.target);
        const source = str(d.source_id);
        push(attack ? "hit" : "arcane", target, {
          amount: num(d.amount),
          tint: attack ? undefined : tintOf(source),
        });
        // A heavy blow on a hero bleeds onto the screen's edges.
        if ((num(d.amount) ?? 0) >= 5 && partyIds.has(target)) {
          push("vignette", target, { screen: true });
        }
        // The blow's delivery, from the source's side of the field: a melee
        // hit lunges the attacker's card; ranged shots and spellfire cross
        // the board as a bolt. Same log entry, read twice.
        if (source && source !== target) {
          if (attack && !ranged) {
            push("strike", source, { targetId: target });
          } else {
            push("bolt", target, {
              sourceId: source,
              variant: ranged ? "arrow" : "arcane",
              tint: ranged ? undefined : tintOf(source),
              amount: num(d.amount), // a 9-point bolt should LOOK like one
            });
          }
        }
        break;
      }
      case "lose_life":
        push("arcane", str(d.target), { amount: num(d.amount) });
        break;
      case "heal":
        push("heal", str(d.target), {
          amount: num(d.amount),
          tint: tintOf(str(d.source_id)),
        });
        break;
      case "regen":
        push("heal", str(d.target), { amount: 1 });
        break;
      case "pump":
        push("pump", str(d.target));
        break;
      case "counters":
        // Permanent counters ENGRAVE; a temporary pump fades. The distinction
        // is real information — the treatments must not be the same.
        push("engrave", str(d.target));
        break;
      case "prevent":
      case "protection":
        push("ward", str(d.target));
        break;
      case "draw": {
        push("draw", str(d.character), { label: str(d.card) });
        cursor = Math.min(cursor + 120, BEAT_CAP); // draws riffle, not clump
        beat = cursor;
        break;
      }
      case "pass":
        // Only AUTO passes get a visible beat — the player saw their own
        // click. The chip makes the teammate's silent pass part of the
        // choreography, and the cursor bump gives the following resolution
        // room to breathe instead of firing "out of nowhere".
        if (d.auto) {
          push("passed", str(d.character), { label: "passes" });
          cursor = Math.min(cursor + 300, BEAT_CAP);
          beat = cursor;
        }
        break;
      case "intent_execute":
        // The moment an enemy's declared intent actually hits the stack —
        // the single most jarring "suddenly you are being asked" instant.
        // The card flares and steps forward, and the timeline holds a beat.
        push("enemyact", str(d.enemy), { label: str(d.label) });
        cursor = Math.min(cursor + 260, BEAT_CAP);
        beat = cursor;
        break;
      case "win":
        push("victory", "screen", { screen: true });
        break;
      case "loss":
        push("defeat", "screen", { screen: true });
        break;
      case "wound":
        push("wound", str(d.target));
        break;
      case "grant_keyword":
        push("keyword", str(d.target), {
          label: Array.isArray(d.keywords)
            ? (d.keywords as unknown[]).map(String).join(" · ").replace(/_/g, " ")
            : "",
        });
        break;
      case "stun":
        push("stun", str(d.target));
        break;
      case "poison":
        push("poison", str(d.target));
        break;
      case "skill":
        push("skill", str(d.character));
        break;
      case "ultimate":
        push("ultimate", str(d.character), { screen: true });
        break;
      case "enrage":
        push("enrage", str(d.enemy), { screen: true });
        break;
      case "charge_detonate":
        push("detonate", str(d.enemy));
        break;
      case "revive":
        push("revive", str(d.character));
        break;
      case "incapacitated":
        push("downed", str(d.character));
        break;
      case "countered":
        push("countered", str(d.source));
        break;
      case "defend":
        push("defend", str(d.character));
        break;
      case "mitigate":
        push("mitigate", str(d.character), {
          label: d.value != null ? `mitigates ${num(d.value)}` : "mitigates",
        });
        break;
      // Damage soaked before it lands: a Mitigate / prevent shield ("reduced")
      // or Defend's temp HP buffer ("absorbed") — the defence paying off.
      case "reduced":
      case "absorbed":
        push("absorb", str(d.target), {
          amount: num(d.amount),
          label: d.amount != null ? `${num(d.amount)} absorbed` : "absorbed",
        });
        break;

      // ---- departures (consumed by the Battlefield ghost system) ---------- //
      case "enemy_died":
        departures[str(d.enemy)] = "death";
        break;
      case "token_died":
      case "crumbled":
        departures[str(d.token)] = "death";
        break;
      case "deathtouch":
        departures[str(d.target)] = "death";
        break;
      case "exiled":
        // A spell's exile removes for good (data carries the level); a
        // channel's exile merely suspends — it slips away instead.
        departures[str(d.target)] = d.level != null ? "exile" : "bounce";
        break;
      case "bounced":
        departures[str(d.enemy)] = "bounce";
        break;
    }
  }
  return { events, departures, maxSeq };
}

/** New-entry bookkeeping across snapshots. Returns lastSeq to use: the log
 * resets on a new session or an adventure act transition — history must not
 * replay as effects. */
export function syncSeq(lastSeq: number | null, log: LogEntry[]): number {
  const seqs = log.map((e) => e.seq ?? -1);
  const max = seqs.length ? Math.max(...seqs) : -1;
  if (lastSeq == null || max < lastSeq) return max; // fresh log — swallow history
  return lastSeq;
}
