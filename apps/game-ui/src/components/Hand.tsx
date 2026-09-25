import { useEffect, useId, useRef, useState } from "react";
import type { CardView } from "../lib/types";
import type { Choices, Choice } from "../lib/choices";
import { useGame } from "../lib/store";
import { Pips } from "./Pips";

// How long a hand card must be hovered (or focused) before it enlarges (M2.6).
const PEEK_DELAY_MS = 150;
const PEEK_WIDTH = 224; // px — the enlarged card (the Stack/Chronicle popup's size class)

type Peek = { card: CardView; left: number; bottom: number; castable: boolean };

export function Hand({ hand, choices }: { hand: CardView[]; choices: Choices | null }) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);
  const focusedId = useGame((s) => s.focusedId);

  // Diff card ids across renders (a multiset diff — the same card id can sit
  // in hand more than once) so only genuinely NEW entries play the draw-in
  // treatment. Baselines are PER CHARACTER: switching whose hand is shown is
  // not a draw (their known hand renders quietly), but cards a character drew
  // while the view was elsewhere still glimmer once when you switch back.
  // A character's first-ever showing baselines silently.
  const baselinesRef = useRef<Map<string, Map<string, number>>>(new Map());
  const holder = focusedId ?? "";
  const baseline = baselinesRef.current.get(holder);
  const justDrawn = new Set<number>();
  if (baseline) {
    const seenSoFar = new Map<string, number>();
    hand.forEach((card, i) => {
      const seen = (seenSoFar.get(card.id) ?? 0) + 1;
      seenSoFar.set(card.id, seen);
      if (seen > (baseline.get(card.id) ?? 0)) justDrawn.add(i);
    });
  }
  useEffect(() => {
    const counts = new Map<string, number>();
    for (const card of hand) counts.set(card.id, (counts.get(card.id) ?? 0) + 1);
    baselinesRef.current.set(holder, counts);
  });

  // Hover-enlarge (M2.6): after a short dwell the card floats full-size above
  // the console, flavour line and all; keyboard focus does the same.
  const [peek, setPeek] = useState<Peek | null>(null);
  const peekTimer = useRef<number | null>(null);
  const clearPeek = () => {
    if (peekTimer.current != null) window.clearTimeout(peekTimer.current);
    peekTimer.current = null;
    setPeek(null);
  };
  const startPeek = (card: CardView, castable: boolean, el: HTMLElement) => {
    if (peekTimer.current != null) window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => {
      const r = el.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.left + r.width / 2 - PEEK_WIDTH / 2,
                                        window.innerWidth - PEEK_WIDTH - 8));
      setPeek({ card, left, bottom: window.innerHeight - r.top + 10, castable });
    }, PEEK_DELAY_MS);
  };
  useEffect(() => clearPeek, []);
  useEffect(() => clearPeek(), [holder]);

  if (!hand.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm font-light italic text-dimmed">
        empty hand
      </div>
    );
  }

  return (
    <div className="scroll-thin flex h-full items-stretch gap-2.5 overflow-x-auto px-1 pb-0.5 pt-2">
      {hand.map((card, i) => {
        const choice: Choice | undefined = choices?.casts[card.id];
        const playable = !!choice;
        const active = armed?.cardId === card.id;
        // The why-not chip (M2.7): the server names the reason; the client
        // only shows it.
        const why = playable ? null : card.unplayable_reason ?? null;
        return (
          <div
            key={`${card.id}-${i}`}
            className="relative h-full shrink-0"
            onMouseEnter={(e) => startPeek(card, playable, e.currentTarget)}
            onMouseLeave={clearPeek}
            onFocus={(e) => startPeek(card, playable, e.currentTarget)}
            onBlur={clearPeek}
          >
            <HandCard
              card={card}
              playable={playable}
              active={active}
              justDrawn={justDrawn.has(i)}
              onClick={() => choice && select(choice)}
              focusable
            />
            {why && (
              <span className="caps-label pointer-events-none absolute inset-x-1 bottom-[22%] z-10 truncate border border-line2 bg-ink-0/90 px-1 py-0.5 text-center text-[clamp(8px,1.1vh,10px)] tracking-[0.12em] text-mist">
                {why}
              </span>
            )}
          </div>
        );
      })}
      {peek && (
        <div
          className="pointer-events-none fixed z-50"
          style={{ left: peek.left, bottom: peek.bottom, width: PEEK_WIDTH }}
          aria-hidden
        >
          <HandCard card={peek.card} playable active={false} onClick={() => {}} large
                    castable={peek.castable} />
        </div>
      )}
    </div>
  );
}

export function HandCard({ card, playable, active, justDrawn, onClick, large, focusable, castable }: {
  card: CardView;
  playable: boolean;
  active: boolean;
  justDrawn?: boolean;
  onClick: () => void;
  // The enlarged card (hover, Stack, Chronicle): full width of its box, the
  // whole rules text unclipped at a fixed readable size, and the flavour line.
  large?: boolean;
  // A card in the hand is a keyboard stop (M2.15): Enter or Space plays it.
  focusable?: boolean;
  // Lights the turn mark brass (M2.21): the card can be cast right now.
  // Defaults to `playable` in the hand; a Stack/Chronicle copy is never lit.
  castable?: boolean;
}) {
  // h-full + aspect-ratio => every card is the same size and top-aligned; the whole
  // card scales with the (window-sized) hand area. Fonts clamp against viewport height.
  // The card is a drawn PLATE (CardFrame): its corner shape says what kind of
  // card this is at a glance, and the shadow hugs that shape.
  const state = playable ? (active ? "is-active" : "is-playable") : "is-dead";
  return (
    <div
      onClick={onClick}
      role={focusable ? "button" : undefined}
      tabIndex={focusable ? 0 : undefined}
      aria-disabled={focusable ? !playable : undefined}
      aria-label={focusable ? `${card.name}: ${card.text}` : undefined}
      onKeyDown={focusable ? (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      } : undefined}
      className={`card-plate ${state} relative isolate flex aspect-[2/3] shrink-0 flex-col p-1.5 text-parch transition-all duration-150 ${
        large ? "w-full p-2.5" : "h-full"
      } ${
        large
          ? ""
          : playable
            ? active
              ? "-translate-y-1.5 cursor-pointer"
              : "cursor-pointer hover:-translate-y-1.5"
            : "opacity-40"
      } ${justDrawn ? "hud-card-draw" : ""} focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-brass`}
    >
      <CardFrame timing={card.timing} lit={castable ?? (playable && !large)} />
      {/* Name (shrink-to-fit) + cost. The title's line height matches the 15px
          pips exactly, so a single-line name and its cost sit on one axis. */}
      <div className="flex items-start justify-between gap-1">
        <span className={`line-clamp-2 font-display font-normal leading-[15px] tracking-[0.02em] ${
          large ? "text-[14px]" : "text-[clamp(9px,1.3vh,12px)]"}`}>
          {card.name}
        </span>
        <div className="flex h-[15px] shrink-0 items-center">
          <Pips cost={card.cost} size={15} />
        </div>
      </div>
      {/* Art (3:2) only when the card HAS any — a consumable carries its
          item's, painted for exactly this frame. Cards without art give the
          whole face to the text instead of a placeholder. */}
      {card.image && (
        <div className="relative my-1 flex aspect-[3/2] w-full items-center justify-center overflow-hidden border border-line bg-ink-0">
          <img src={card.image} alt="" className="h-full w-full object-cover" />
        </div>
      )}
      <div className="my-1 h-px w-full bg-line" aria-hidden />
      {/* Effect text (left-aligned, fills). The enlarged card never clips:
          the plate grows past 2:3 before a word is lost. */}
      <div className={`flex-1 font-light leading-snug text-mist ${
        large
          ? "text-[12.5px]"
          : `overflow-hidden ${card.image ? "text-[clamp(8px,1.1vh,11px)]" : "text-[clamp(9px,1.25vh,12.5px)]"}`}`}>
        {card.text}
        {large && card.flavor && (
          <p className="mt-2 border-t border-line pt-1.5 text-[11.5px] font-light italic leading-snug text-dimmed">
            “{card.flavor}”
          </p>
        )}
      </div>
      {/* Type. §D23-9's turn mark (this card spends the turn) sits on the
          plate's top edge instead — see CardFrame. */}
      <div className={`caps-label mt-0.5 text-center tracking-[0.18em] text-dimmed ${
        large ? "text-[9.5px]" : "text-[clamp(7px,1vh,9px)]"}`}>
        {card.timing}
      </div>
    </div>
  );
}

/* The card's face and frame, drawn rather than bordered. One plate per
   timing, told apart by the shape of its corners — the same brass-hairline
   vocabulary as the panels (panel-ticks), scaled with the card:
     sorcery   a square plate with engraved corner brackets — set down;
     instant   the corners are CUT, a second stroke glinting off each cut
               edge — struck, quick, playable any time;
     channeled a cartouche with scalloped corners — bound to the board.
   A sorcery and a channel SPEND THE TURN (§D23-9), so they wear the action
   bar's turn mark on the plate's top edge; an instant carries none. Ruled
   2026-09-25 (M2.21): the mark is always there, but brass only while the card
   can be cast — gold means "you can act on this" — and a dim hairline grey
   otherwise.
   The stroke colour follows the card's state through --frame (.card-plate in
   index.css); the plate itself is the old ink gradient. */
const FRAME_PATH: Record<string, string> = {
  sorcery: "M0 0H100V150H0Z",
  instant: "M3 0H97L100 3V147L97 150H3L0 147V3Z",
  channeled: "M3 0H97A3 3 0 0 0 100 3V147A3 3 0 0 0 97 150H3A3 3 0 0 0 0 147V3A3 3 0 0 0 3 0Z",
};
const CORNER_MARKS: Record<string, string> = {
  // Inset L-brackets, all four corners.
  sorcery: "M1.8 9V1.8H9M91 1.8H98.2V9M98.2 141V148.2H91M9 148.2H1.8V141",
  // A short stroke paralleling each cut, just outside it.
  instant: "M-1.4 2L2 -1.4M98 -1.4L101.4 2M101.4 148L98 151.4M2 151.4L-1.4 148",
  channeled: "",
};

export function CardFrame({ timing, lit = true }: { timing: string; lit?: boolean }) {
  const kind = timing in FRAME_PATH ? timing : "sorcery";
  const gradId = useId();
  return (
    <svg
      viewBox="0 0 100 150"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-0 -z-10 h-full w-full overflow-visible"
      aria-hidden
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#161a24" />
          <stop offset="1" stopColor="#10131b" />
        </linearGradient>
      </defs>
      <path d={FRAME_PATH[kind]} fill={`url(#${gradId})`} stroke="var(--frame)"
            strokeWidth="1" vectorEffect="non-scaling-stroke" className="card-frame-ink" />
      {CORNER_MARKS[kind] && (
        <path d={CORNER_MARKS[kind]} fill="none" stroke="var(--frame)" strokeWidth="1"
              vectorEffect="non-scaling-stroke" className="card-frame-ink" />
      )}
      {kind !== "instant" && (
        <path d="M50 -2.4L52.4 0L50 2.4L47.6 0Z"
              fill={lit ? "#c9b37e" : "#59616e"} fillOpacity={lit ? 0.75 : 0.9} />
      )}
    </svg>
  );
}
