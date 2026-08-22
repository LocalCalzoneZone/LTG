import { useEffect, useMemo, useState } from "react";
import { roman } from "../lib/format";
import { SPLASH_HOLD_MS, useAfterHold } from "../lib/hooks";
import { useGame } from "../lib/store";
import type {
  AdventureBlock,
  BuildPrices,
  BuildView,
  Color,
  LevelUpRow,
  PriceStat,
} from "../lib/types";
import { ManaIcon } from "./Pips";
import { IconSigil } from "./Icons";

const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch";

/** The between-phases flow (§D10-6.3), driven entirely by the snapshot's
 * adventure block: phase victory splash → level-up screen (gated on every seat's
 * confirmation) → narrative splash over the next phase's scene → combat. The
 * narrative splash also opens Phase I (its narration is the adventure's opening).
 *
 * WHERE these render: the component is mounted INSIDE the bottom action-bar
 * wrapper. The phase-victory splash covers only that strip — `absolute inset-0`,
 * exactly like the game-over splash — so the board you just won on and the log
 * stay readable and inspectable underneath. The level-up screen and the
 * narrative splash both go full-screen (`fixed`, below the 42px ribbon so Copy
 * Link / seats / Options stay reachable — e.g. inviting an ally before Phase I
 * begins): the level-up as a centred modal over a dimmed board, the same
 * treatment the Spoils uses, and the narration over the next phase's scene art.
 */
export function AdventureFlow() {
  const snapshot = useGame((s) => s.snapshot);
  const sessionId = useGame((s) => s.sessionId);
  const adventure = snapshot?.adventure;

  // Which phase boundaries this client has clicked through, keyed per session.
  const [victorySeen, setVictorySeen] = useState<Record<string, boolean>>({});
  const [narrationSeen, setNarrationSeen] = useState<Record<string, boolean>>({});
  // Hold the phase-clear splash back so the final kill (and its death animation)
  // reads on the board before the screen changes.
  const boundaryReady = useAfterHold(!!adventure?.level_up, SPLASH_HOLD_MS);

  if (!snapshot || !adventure) return null;

  const key = `${sessionId}:${adventure.phase}`;

  // Defeat / final victory: the GameOverOverlay owns the bottom bar.
  if (snapshot.result != null) return null;

  if (adventure.level_up) {
    // The act-end screen (§D17-2.3) arrives AFTER the spoils — the finale's
    // victory treatment and the Rewards modal have already played, so it opens
    // straight onto the build.
    if (!victorySeen[key] && !adventure.level_up.final) {
      if (!boundaryReady) return null; // the killing blow plays out first
      return (
        <PhaseVictorySplash
          phase={adventure.phase}
          phaseName={adventure.phase_name}
          label={adventure.level_up.kind === "interlude" ? "Press On" : "Level Up"}
          onContinue={() => setVictorySeen((m) => ({ ...m, [key]: true }))}
        />
      );
    }
    if (adventure.level_up.kind === "interlude") {
      return <InterludeScreen adventure={adventure} />;
    }
    return <LevelUpScreen adventure={adventure} />;
  }

  // Nothing left to open: the adventure is won and the act is wrapping up (the
  // spoils, then the ride back to town). A client that connects or reloads here
  // must not be shown the phase's opening narration all over again.
  if (adventure.complete || snapshot.rewards) return null;

  // Combat (or the moment a phase opens): the narrative splash, once per phase.
  if (!narrationSeen[key] && adventure.narration) {
    return (
      <NarrativeSplash
        adventure={adventure}
        sceneImage={snapshot.scene_image}
        onContinue={() => setNarrationSeen((m) => ({ ...m, [key]: true }))}
      />
    );
  }
  return null;
}

/** "Phase I — clear": the phase-labelled victory treatment (§D10-6.3 step 1). */
function PhaseVictorySplash({ phase, phaseName, onContinue, label = "Level Up" }: {
  phase: number;
  phaseName: string;
  onContinue: () => void;
  label?: string;
}) {
  return (
    <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-2 overflow-y-auto bg-ink-0/95 px-6 py-3 text-center">
      <div className="flex items-center justify-center gap-5">
        <span className="h-px w-16 bg-gradient-to-r from-transparent to-vigor/70" />
        <div
          className="caps-label pl-[0.3em] text-2xl tracking-[0.3em] text-vigor"
          style={{ textShadow: "0 0 30px rgba(132,199,147,.4)" }}
        >
          Phase {roman(phase)} — Clear
        </div>
        <span className="h-px w-16 bg-gradient-to-l from-transparent to-vigor/70" />
      </div>
      <div className="text-sm font-light text-mist">{phaseName}</div>
      <button
        onClick={onContinue}
        className="chamfer-x caps-label mt-2 bg-gradient-to-b from-brass-hi to-brass px-8 py-2.5 text-[11px] tracking-[0.3em] text-ink-0 transition hover:from-brass-hi hover:to-brass-hi"
      >
        {label}
      </button>
    </div>
  );
}

/** The next phase's narration over its scene art (§D10-6.3 step 3). */
function NarrativeSplash({ adventure, sceneImage, onContinue }: {
  adventure: AdventureBlock;
  sceneImage: string;
  onContinue: () => void;
}) {
  return (
    <div className="fixed inset-x-0 bottom-0 top-[42px] z-20 flex items-center justify-center bg-ink-0">
      {sceneImage && (
        <img
          src={sceneImage}
          alt=""
          className="absolute inset-0 h-full w-full object-cover opacity-60"
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-ink-0 via-ink-0/40 to-ink-0/70" />
      <div className="relative z-10 flex max-w-2xl flex-col items-center gap-5 px-8 text-center">
        <div className="caps-label text-[11px] tracking-[0.3em] text-mist">
          {adventure.name}
        </div>
        <div className="flex items-center gap-4">
          <span className="h-px w-14 bg-gradient-to-r from-transparent to-brass" />
          <div className="caps-label whitespace-nowrap text-[15px] tracking-[0.25em] text-brass-hi">
            Phase {roman(adventure.phase)} · {adventure.phase_name}
          </div>
          <span className="h-px w-14 bg-gradient-to-l from-transparent to-brass" />
        </div>
        <p className="font-display text-lg font-light leading-relaxed text-parch">
          {adventure.narration}
        </p>
        <button
          onClick={onContinue}
          className="chamfer-x caps-label mt-2 bg-gradient-to-b from-brass-hi to-brass px-10 py-2.5 text-[11px] tracking-[0.3em] text-ink-0 transition hover:from-brass-hi hover:to-brass-hi"
        >
          Continue
        </button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The level-up screen (§D10-3.3): portrait left, the points-buy panel right in
// locked-baseline mode. Per-seat: you edit only characters you control; other
// seats are confirmed/waiting lights. A client with several characters
// confirms them one after another.
// --------------------------------------------------------------------------- //
type Draft = {
  hp: number;
  starting_mana: Color[];
  starting_cards: number;
  power_bought: number;
};

function draftFrom(b: BuildView): Draft {
  return {
    hp: b.hp,
    starting_mana: [...b.starting_mana],
    starting_cards: b.starting_cards,
    power_bought: b.power_bought,
  };
}

/** Price of the nth purchase (1-based) of a stat on the T-79 curve. Past the
 * shipped list, extend by the last step (the server's list is long enough
 * that this is a formality). */
function nthPrice(prices: BuildPrices, stat: PriceStat, n: number): number {
  const list = prices.curve[stat];
  if (n <= list.length) return list[n - 1];
  const step = list.length >= 2 ? list[list.length - 1] - list[list.length - 2] : 0;
  return list[list.length - 1] + step * (n - list.length);
}

/** Total price of purchases (from+1 … to) of a stat, counted from baseline. */
function rangeCost(prices: BuildPrices, stat: PriceStat, from: number, to: number): number {
  let sum = 0;
  for (let n = from + 1; n <= to; n++) sum += nthPrice(prices, stat, n);
  return sum;
}

/** Bought-count of each stat in a build (purchases since the free baseline). */
function boughtCounts(b: { hp: number; starting_mana: unknown[]; starting_cards: number; power_bought: number },
                      prices: BuildPrices): Record<PriceStat, number> {
  return {
    hp_step: (b.hp - prices.baseline.hp) / 2,
    mana: b.starting_mana.length - prices.baseline.mana,
    card: b.starting_cards - prices.baseline.cards,
    power: b.power_bought,
  };
}

function draftCost(d: Draft, base: BuildView, prices: BuildPrices): number {
  const from = boughtCounts(base, prices);
  const to = boughtCounts(d, prices);
  return (
    rangeCost(prices, "hp_step", from.hp_step, to.hp_step) +
    rangeCost(prices, "mana", from.mana, to.mana) +
    rangeCost(prices, "card", from.card, to.card) +
    rangeCost(prices, "power", from.power, to.power)
  );
}

/** The Phase Clear INTERLUDE (§D17-2.3): the phase paid its points into the
 * pool, but this boundary buys nothing — the party checks its gear and presses
 * on. Points are spent at the act's end, behind the spoils. */
function InterludeScreen({ adventure }: { adventure: AdventureBlock }) {
  const you = useGame((s) => s.you);
  const confirmLevelUp = useGame((s) => s.confirmLevelUp);
  const setSheetFor = useGame((s) => s.setSheetFor);
  const lu = adventure.level_up!;

  const mine = lu.characters.filter((r) => you.includes(r.id) && r.build);
  const waiting = mine.filter((r) => !r.confirmed);
  const banked = mine.find((r) => r.available != null)?.available ?? null;

  return (
    <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 overflow-y-auto bg-ink-0/95 px-6 py-4 text-center">
      <div className="caps-label text-[12px] tracking-[0.3em] text-brass">
        +{lu.phase_grant} Points Banked
      </div>
      <div className="max-w-md text-sm font-light text-mist">
        {banked != null ? `${banked} points are waiting` : "Your points are waiting"} —
        they are spent at the level-up screen when the act is done. Gear and belt
        can be changed here.
      </div>
      <div className="flex flex-wrap items-center justify-center gap-2">
        {lu.characters.map((r) => (
          <span
            key={r.id}
            className={`caps-label border px-2 py-0.5 text-[9px] tracking-[0.14em] ${
              r.confirmed ? "border-vigor/60 text-vigor" : "border-line text-mist"
            }`}
          >
            {r.name} · {r.confirmed ? "ready" : "waiting"}
          </span>
        ))}
      </div>
      {waiting.length ? (
        <div className="mt-1 flex items-center gap-3">
          <button
            onClick={() => setSheetFor(waiting[0].id)}
            className="chamfer-x caps-label border border-line bg-ink-2 px-5 py-2.5 text-[11px] tracking-[0.25em] text-parch transition hover:border-brass/60"
          >
            Character Sheet
          </button>
          <button
            onClick={() => waiting.forEach((r) => confirmLevelUp(r.id, {}))}
            className="chamfer-x caps-label bg-gradient-to-b from-brass-hi to-brass px-8 py-2.5 text-[11px] tracking-[0.3em] text-ink-0 transition hover:from-brass-hi hover:to-brass-hi"
          >
            Press On
          </button>
        </div>
      ) : (
        <div className="max-w-md text-sm font-light text-mist">
          {mine.length
            ? "Waiting for the other players — the next phase begins when every character is ready."
            : "You control no characters. Claim a seat in the top ribbon."}
        </div>
      )}
    </div>
  );
}

function LevelUpScreen({ adventure }: { adventure: AdventureBlock }) {
  const you = useGame((s) => s.you);
  const confirmLevelUp = useGame((s) => s.confirmLevelUp);
  const lu = adventure.level_up!;

  // The first of MY characters still to confirm (each client confirms its own).
  const mine = lu.characters.filter((r) => you.includes(r.id) && r.build);
  const active = mine.find((r) => !r.confirmed) ?? null;

  // A full modal over the board (playtest: squeezed into the bottom strip, a
  // points-buy screen never had the room). Same treatment as the Spoils —
  // dimmed backdrop below the 42px ribbon, a fixed-size panel centred in it —
  // so the two post-combat decisions read as one pair. Seat lights ride the
  // header row; only the stat rows scroll.
  return (
    <div className="fixed inset-x-0 bottom-0 top-[42px] z-30 flex items-center justify-center bg-black/80 backdrop-blur-[2px]">
    <div className="panel-ticks flex h-[min(84vh,620px)] w-[min(94vw,980px)] flex-col border border-line2 bg-ink-2 shadow-2xl">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-1.5">
        <h2 className="caps-label text-[12px] tracking-[0.25em] text-brass">
          {lu.final ? "The Act Is Done" : "Level Up"} — Level {lu.next_level}
        </h2>
        <span className="caps-label text-[9px] tracking-[0.2em] text-mist">
          {active?.available ?? 0} points to spend · bankable · irreversible
          {active?.points_to_next_level != null && active.earned_points != null && (
            <> · {active.earned_points} earned · {active.points_to_next_level} to level {(active.next_level ?? lu.next_level) + 1}</>
          )}
        </span>
        <span className="h-px min-w-[1rem] flex-1 bg-line" />
        {lu.characters.map((r) => (
          <span
            key={r.id}
            className={`caps-label border px-2 py-0.5 text-[9px] tracking-[0.14em] ${
              r.confirmed ? "border-vigor/60 text-vigor" : "border-line text-mist"
            }`}
          >
            {r.name} · {r.confirmed ? "confirmed" : "choosing…"}
          </span>
        ))}
      </div>

      {active ? (
        <BuildPanel
          key={active.id}
          row={active}
          prices={lu.prices}
          nextLevel={lu.next_level}
          pointsPerLevel={lu.points_per_level}
          onConfirm={(build) => confirmLevelUp(active.id, build)}
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 overflow-y-auto px-8 py-4 text-center">
          <div className="h-2 w-2 rotate-45 border border-brass/60" aria-hidden />
          <div className="caps-label text-[12px] tracking-[0.2em] text-parch">
            {mine.length ? "Your characters are ready" : "Claim a seat to level up"}
          </div>
          <div className="max-w-md text-sm font-light text-mist">
            {mine.length
              ? "Waiting for the other players to confirm — the next phase begins when every character is confirmed."
              : "You control no characters. Claim a seat in the top ribbon to confirm its level-up."}
          </div>
        </div>
      )}
    </div>
    </div>
  );
}

function StatRow({ name, value, cost, canUp, canDown, onUp, onDown, hint }: {
  name: string;
  value: string;
  cost: string;
  canUp: boolean;
  canDown: boolean;
  onUp: () => void;
  onDown: () => void;
  hint?: string;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-line/60 py-2" title={hint}>
      <span className="caps-label w-32 shrink-0 text-[10px] tracking-[0.18em] text-mist">
        {name}
      </span>
      <span className="w-16 text-right font-display text-lg text-parch">{value}</span>
      <span className="flex items-center gap-1">
        <button
          onClick={onDown}
          disabled={!canDown}
          className={`${SMALL_BTN} w-7 disabled:cursor-not-allowed disabled:opacity-30`}
          title="Sell back (this screen's purchases only — the entering build is locked)"
        >
          −
        </button>
        <button
          onClick={onUp}
          disabled={!canUp}
          className={`${SMALL_BTN} w-7 disabled:cursor-not-allowed disabled:opacity-30`}
        >
          +
        </button>
      </span>
      <span className="ml-auto text-xs font-light text-dimmed">{cost}</span>
    </div>
  );
}

function BuildPanel({ row, prices, nextLevel, pointsPerLevel, onConfirm }: {
  row: LevelUpRow;
  prices: BuildPrices;
  nextLevel: number;
  pointsPerLevel: number;
  onConfirm: (build: Record<string, unknown>) => void;
}) {
  const base = row.build!;
  const [draft, setDraft] = useState<Draft>(() => draftFrom(base));
  useEffect(() => setDraft(draftFrom(base)), [row.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const available = row.available ?? pointsPerLevel;
  const spent = useMemo(() => draftCost(draft, base, prices), [draft, base, prices]);
  const remaining = available - spent;
  const powerCap = prices.power_cap_per_level * nextLevel;
  // The NEXT purchase's price per stat — escalating (T-79), so it moves as you buy.
  const bought = boughtCounts(draft, prices);
  const nextHp = nthPrice(prices, "hp_step", bought.hp_step + 1);
  const nextCard = nthPrice(prices, "card", bought.card + 1);
  const nextPower = nthPrice(prices, "power", bought.power + 1);
  const nextMana = nthPrice(prices, "mana", bought.mana + 1);
  const basePower = base.attack_mode === "melee" ? 2 : 1;

  const patch = (next: Partial<Draft>) => setDraft((d) => ({ ...d, ...next }));

  const cycleColor = (i: number) => {
    // Only slots added on THIS screen pick their colour (within the identity).
    if (i < base.starting_mana.length) return;
    const identity = base.colors;
    const cur = identity.indexOf(draft.starting_mana[i]);
    const next = identity[(cur + 1) % identity.length];
    patch({
      starting_mana: draft.starting_mana.map((c, j) => (j === i ? next : c)),
    });
  };

  return (
    <div className="flex min-h-0 flex-1">
      {/* Portrait, full height on the left */}
      <div className="relative hidden w-[180px] shrink-0 overflow-hidden border-r border-line bg-ink-0 sm:block">
        {base.portrait ? (
          <img src={base.portrait} alt={row.name} className="h-full w-full object-cover object-top" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-dimmed">
            <IconSigil size={48} />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-0/95 to-transparent p-2 pt-8">
          <div className="caps-label text-[12px] tracking-[0.2em] text-parch">{row.name}</div>
          <div className="caps-label mt-0.5 text-[9px] tracking-[0.18em] text-brass">
            Level {base.level} → {nextLevel}
          </div>
        </div>
      </div>

      {/* The points-buy panel, locked-baseline mode. The ledger and the Confirm
          are pinned; only the stat rows scroll, so the screen still works at the
          bottom strip's shortest height. */}
      <div className="flex min-h-0 flex-1 flex-col gap-1 p-3">
        {/* Locked · new · banked — always visible (§D10-3.3) */}
        <div className="mb-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 border border-line bg-black/25 px-3 py-1.5">
          <Figure label="Locked" value={row.locked ?? 0} title="The entering build's spend — nothing can be sold back" />
          <Figure label="To spend" value={available} accent title="Every point won so far and not yet spent (+10 / +20 / +30 a phase)" />
          <span className="mx-1 h-6 w-px bg-line" />
          <Figure
            label="Remaining"
            value={remaining}
            accent={remaining > 0}
            danger={remaining < 0}
            title="Available minus this screen's purchases — anything left banks for the next level"
          />
        </div>

        <div className="scroll-thin flex min-h-0 flex-1 flex-col overflow-y-auto pr-1">
        <StatRow
          name="Hit Points"
          value={String(draft.hp)}
          cost={`+2 HP · ${nextHp} pts (heals +2)`}
          canUp={remaining >= nextHp}
          canDown={draft.hp - 2 >= base.hp}
          onUp={() => patch({ hp: draft.hp + 2 })}
          onDown={() => patch({ hp: draft.hp - 2 })}
          hint="HP bought here is also healed: +2 max is +2 current."
        />
        <StatRow
          name="Starting Cards"
          value={String(draft.starting_cards)}
          cost={`+1 card · ${nextCard} pts`}
          canUp={remaining >= nextCard}
          canDown={draft.starting_cards - 1 >= base.starting_cards}
          onUp={() => patch({ starting_cards: draft.starting_cards + 1 })}
          onDown={() => patch({ starting_cards: draft.starting_cards - 1 })}
          hint="Each phase opens on a full reshuffle and a fresh hand of this many cards."
        />
        <StatRow
          name="Power"
          value={`${basePower + draft.power_bought}`}
          cost={`+1 Power · ${nextPower} pts (cap +${powerCap} at level ${nextLevel})`}
          canUp={remaining >= nextPower && draft.power_bought < powerCap}
          canDown={draft.power_bought - 1 >= base.power_bought}
          onUp={() => patch({ power_bought: draft.power_bought + 1 })}
          onDown={() => patch({ power_bought: draft.power_bought - 1 })}
        />

        {/* Mana capacity: existing slots read-only; new slots pick a colour */}
        <div className="flex items-center gap-3 border-b border-line/60 py-2">
          <span className="caps-label w-32 shrink-0 text-[10px] tracking-[0.18em] text-mist">
            Mana Capacity
          </span>
          <span className="flex flex-wrap items-center gap-1">
            {draft.starting_mana.map((c, i) => {
              const added = i >= base.starting_mana.length;
              return (
                <button
                  key={i}
                  onClick={() => cycleColor(i)}
                  disabled={!added}
                  title={added ? "Click to cycle this new slot's colour (identity only)" : "Locked slot"}
                  className={`flex h-6 w-6 items-center justify-center border transition ${
                    added
                      ? "cursor-pointer border-brass/70 bg-brass/10"
                      : "cursor-default border-line/60 opacity-80"
                  }`}
                >
                  <ManaIcon color={c} size={14} />
                </button>
              );
            })}
            <button
              onClick={() =>
                patch({ starting_mana: [...draft.starting_mana, base.colors[0]] })}
              disabled={remaining < nextMana}
              className={`${SMALL_BTN} disabled:cursor-not-allowed disabled:opacity-30`}
            >
              +
            </button>
            {draft.starting_mana.length > base.starting_mana.length && (
              <button
                onClick={() =>
                  patch({ starting_mana: draft.starting_mana.slice(0, -1) })}
                className={SMALL_BTN}
              >
                −
              </button>
            )}
          </span>
          <span className="ml-auto text-xs font-light text-dimmed">
            +1 slot · {nextMana} pts · colour locks now
          </span>
        </div>

        {/* Keyword: character creation only — shown, never bought here */}
        <div className="flex items-start gap-3 py-2">
          <span className="caps-label w-32 shrink-0 pt-1 text-[10px] tracking-[0.18em] text-mist">
            Keyword
          </span>
          {base.keyword ? (
            <span className="caps-label border border-line px-2.5 py-1 text-[10px] tracking-[0.14em] text-parch">
              {base.keyword.replace("_", " ")}
            </span>
          ) : (
            <span className="caps-label border border-line/60 px-2.5 py-1 text-[10px] tracking-[0.14em] text-dimmed">
              None
            </span>
          )}
          <span className="ml-auto shrink-0 pt-1 text-xs font-light text-dimmed">
            set at character creation
          </span>
        </div>
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={() =>
              onConfirm({
                hp: draft.hp,
                starting_mana: draft.starting_mana,
                starting_cards: draft.starting_cards,
                power_bought: draft.power_bought,
              })}
            disabled={remaining < 0}
            className={`chamfer-x caps-label flex-1 py-2.5 text-[11px] tracking-[0.3em] transition ${
              remaining < 0
                ? "cursor-not-allowed bg-white/[0.03] text-dimmed"
                : "bg-gradient-to-b from-brass-hi to-brass text-ink-0 hover:from-brass-hi hover:to-brass-hi"
            }`}
          >
            Confirm{remaining > 0 ? ` · bank ${remaining}` : ""}
          </button>
        </div>
      </div>
    </div>
  );
}

function Figure({ label, value, accent, danger, title }: {
  label: string;
  value: number;
  accent?: boolean;
  danger?: boolean;
  title?: string;
}) {
  return (
    <span className="flex items-baseline gap-2" title={title}>
      <span className="caps-label text-[9px] tracking-[0.18em] text-mist">{label}</span>
      <span
        className={`font-display text-lg ${
          danger ? "text-blood" : accent ? "text-brass-hi" : "text-parch"
        }`}
      >
        {value}
      </span>
    </span>
  );
}
