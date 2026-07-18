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
} from "../lib/types";
import { ManaIcon } from "./Pips";
import { IconSigil } from "./Icons";

const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch";

/** The between-acts flow (§D10-6.3), driven entirely by the snapshot's
 * adventure block: act victory splash → level-up screen (gated on every seat's
 * confirmation) → narrative splash over the next act's scene → combat. The
 * narrative splash also opens Act I (its narration is the adventure's opening).
 */
export function AdventureFlow() {
  const snapshot = useGame((s) => s.snapshot);
  const sessionId = useGame((s) => s.sessionId);
  const adventure = snapshot?.adventure;

  // Which act boundaries this client has clicked through, keyed per session.
  const [victorySeen, setVictorySeen] = useState<Record<string, boolean>>({});
  const [narrationSeen, setNarrationSeen] = useState<Record<string, boolean>>({});
  // Hold the act-clear splash back so the final kill (and its death animation)
  // reads on the board before the screen changes.
  const boundaryReady = useAfterHold(!!adventure?.level_up, SPLASH_HOLD_MS);

  if (!snapshot || !adventure) return null;

  const key = `${sessionId}:${adventure.act}`;

  // Defeat / final victory: the GameOverOverlay owns the screen.
  if (snapshot.result != null) return null;

  if (adventure.level_up) {
    if (!victorySeen[key]) {
      if (!boundaryReady) return null; // the killing blow plays out first
      return (
        <ActVictorySplash
          act={adventure.act}
          actName={adventure.act_name}
          onContinue={() => setVictorySeen((m) => ({ ...m, [key]: true }))}
        />
      );
    }
    return <LevelUpScreen adventure={adventure} />;
  }

  // Combat (or the moment an act opens): the narrative splash, once per act.
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

/** "Act I — clear": the act-labelled victory treatment (§D10-6.3 step 1). */
function ActVictorySplash({ act, actName, onContinue }: {
  act: number;
  actName: string;
  onContinue: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-[2px]">
      <div className="panel-ticks border border-line2 bg-ink-2/95 px-12 py-9 text-center shadow-2xl">
        <div className="flex items-center justify-center gap-5">
          <span className="h-px w-16 bg-gradient-to-r from-transparent to-vigor/70" />
          <div
            className="caps-label pl-[0.3em] text-4xl tracking-[0.3em] text-vigor"
            style={{ textShadow: "0 0 30px rgba(132,199,147,.4)" }}
          >
            Act {roman(act)} — Clear
          </div>
          <span className="h-px w-16 bg-gradient-to-l from-transparent to-vigor/70" />
        </div>
        <div className="mt-3 text-sm font-light text-mist">{actName}</div>
        <button
          onClick={onContinue}
          className="chamfer-x caps-label mt-6 bg-gradient-to-b from-brass-hi to-brass px-8 py-2.5 text-[11px] tracking-[0.3em] text-ink-0 transition hover:from-brass-hi hover:to-brass-hi"
        >
          Level Up
        </button>
      </div>
    </div>
  );
}

/** The next act's narration over its scene art (§D10-6.3 step 3). */
function NarrativeSplash({ adventure, sceneImage, onContinue }: {
  adventure: AdventureBlock;
  sceneImage: string;
  onContinue: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink-0">
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
            Act {roman(adventure.act)} · {adventure.act_name}
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

function draftCost(d: Draft, base: BuildView, prices: BuildPrices): number {
  return (
    ((d.hp - base.hp) / 2) * prices.hp_step +
    (d.starting_mana.length - base.starting_mana.length) * prices.mana +
    (d.starting_cards - base.starting_cards) * prices.card +
    (d.power_bought - base.power_bought) * prices.power
  );
}

function LevelUpScreen({ adventure }: { adventure: AdventureBlock }) {
  const you = useGame((s) => s.you);
  const confirmLevelUp = useGame((s) => s.confirmLevelUp);
  const lu = adventure.level_up!;

  // The first of MY characters still to confirm (each client confirms its own).
  const mine = lu.characters.filter((r) => you.includes(r.id) && r.build);
  const active = mine.find((r) => !r.confirmed) ?? null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/80 backdrop-blur-[2px]">
      <div className="panel-ticks flex max-h-[90vh] w-[min(94vw,880px)] flex-col border border-line2 bg-ink-2 shadow-2xl">
        <div className="flex items-center gap-3 border-b border-line px-5 py-3">
          <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">
            Level Up — Level {lu.next_level}
          </h2>
          <span className="h-px flex-1 bg-line" />
          <span className="caps-label text-[10px] tracking-[0.2em] text-mist">
            +{lu.points_per_level} points · bankable · irreversible
          </span>
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
          <div className="flex flex-col items-center gap-3 px-8 py-12 text-center">
            <div className="h-2 w-2 rotate-45 border border-brass/60" aria-hidden />
            <div className="caps-label text-[12px] tracking-[0.2em] text-parch">
              {mine.length ? "Your characters are ready" : "Claim a seat to level up"}
            </div>
            <div className="max-w-md text-sm font-light text-mist">
              {mine.length
                ? "Waiting for the other players to confirm — the next act begins when every character is confirmed."
                : "You control no characters. Claim a seat in the top ribbon to confirm its level-up."}
            </div>
          </div>
        )}

        {/* Everyone's confirmed / waiting status */}
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          {lu.characters.map((r) => (
            <span
              key={r.id}
              className={`caps-label border px-2.5 py-1 text-[9px] tracking-[0.14em] ${
                r.confirmed
                  ? "border-vigor/60 text-vigor"
                  : "border-line text-mist"
              }`}
            >
              {r.name} · {r.confirmed ? "confirmed" : "choosing…"}
            </span>
          ))}
        </div>
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
      <div className="relative w-[280px] shrink-0 overflow-hidden border-r border-line bg-ink-0">
        {base.portrait ? (
          <img src={base.portrait} alt={row.name} className="h-full w-full object-cover object-top" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-dimmed">
            <IconSigil size={48} />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-0/95 to-transparent p-3 pt-8">
          <div className="caps-label text-[13px] tracking-[0.2em] text-parch">{row.name}</div>
          <div className="caps-label mt-0.5 text-[9px] tracking-[0.18em] text-brass">
            Level {base.level} → {nextLevel}
          </div>
        </div>
      </div>

      {/* The points-buy panel, locked-baseline mode */}
      <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-5">
        {/* Locked · new · banked — always visible (§D10-3.3) */}
        <div className="mb-3 flex items-center gap-4 border border-line bg-black/25 px-3 py-2">
          <Figure label="Locked" value={row.locked ?? 0} title="The entering build's spend — nothing can be sold back" />
          <Figure label="New" value={pointsPerLevel} accent title="This level-up's grant" />
          <Figure label="Banked" value={row.banked ?? 0} title="Unspent points carried from earlier" />
          <span className="mx-1 h-6 w-px bg-line" />
          <Figure
            label="Remaining"
            value={remaining}
            accent={remaining > 0}
            danger={remaining < 0}
            title="Available minus this screen's purchases — anything left banks for the next level"
          />
        </div>

        <StatRow
          name="Hit Points"
          value={String(draft.hp)}
          cost={`+2 HP · ${prices.hp_step} pts (heals +2)`}
          canUp={remaining >= prices.hp_step}
          canDown={draft.hp - 2 >= base.hp}
          onUp={() => patch({ hp: draft.hp + 2 })}
          onDown={() => patch({ hp: draft.hp - 2 })}
          hint="HP bought here is also healed: +2 max is +2 current."
        />
        <StatRow
          name="Starting Cards"
          value={String(draft.starting_cards)}
          cost={`+1 card · ${prices.card} pts`}
          canUp={remaining >= prices.card}
          canDown={draft.starting_cards - 1 >= base.starting_cards}
          onUp={() => patch({ starting_cards: draft.starting_cards + 1 })}
          onDown={() => patch({ starting_cards: draft.starting_cards - 1 })}
          hint="Each act opens on a full reshuffle and a fresh hand of this many cards."
        />
        <StatRow
          name="Power"
          value={`${basePower + draft.power_bought}`}
          cost={`+1 Power · ${prices.power} pts (cap +${powerCap} at level ${nextLevel})`}
          canUp={remaining >= prices.power && draft.power_bought < powerCap}
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
              disabled={remaining < prices.mana}
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
            +1 slot · {prices.mana} pts · colour locks now
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

        <div className="mt-auto flex items-center gap-3 pt-4">
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
