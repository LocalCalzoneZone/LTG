import { useEffect, useId, useRef } from "react";
import type { CardView } from "../lib/types";
import type { Choices, Choice } from "../lib/choices";
import { useGame } from "../lib/store";
import { Pips } from "./Pips";

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
        return (
          <HandCard
            key={`${card.id}-${i}`}
            card={card}
            playable={playable}
            active={active}
            justDrawn={justDrawn.has(i)}
            onClick={() => choice && select(choice)}
          />
        );
      })}
    </div>
  );
}

export function HandCard({ card, playable, active, justDrawn, onClick }: {
  card: CardView;
  playable: boolean;
  active: boolean;
  justDrawn?: boolean;
  onClick: () => void;
}) {
  // h-full + aspect-ratio => every card is the same size and top-aligned; the whole
  // card scales with the (window-sized) hand area. Fonts clamp against viewport height.
  // The card is a drawn PLATE (CardFrame): its corner shape says what kind of
  // card this is at a glance, and the shadow hugs that shape.
  const state = playable ? (active ? "is-active" : "is-playable") : "is-dead";
  return (
    <div
      onClick={onClick}
      title={card.text}
      className={`card-plate ${state} relative isolate flex aspect-[2/3] h-full shrink-0 flex-col p-1.5 text-parch transition-all duration-150 ${
        playable
          ? active
            ? "-translate-y-1.5 cursor-pointer"
            : "cursor-pointer hover:-translate-y-1.5"
          : "opacity-40"
      } ${justDrawn ? "hud-card-draw" : ""}`}
    >
      <CardFrame timing={card.timing} />
      {/* Name (shrink-to-fit) + cost. The title's line height matches the 15px
          pips exactly, so a single-line name and its cost sit on one axis. */}
      <div className="flex items-start justify-between gap-1">
        <span className="line-clamp-2 font-display text-[clamp(9px,1.3vh,12px)] font-normal leading-[15px] tracking-[0.02em]">
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
      {/* Effect text (left-aligned, fills) */}
      <div className={`flex-1 overflow-hidden font-light leading-snug text-mist ${
        card.image ? "text-[clamp(8px,1.1vh,11px)]" : "text-[clamp(9px,1.25vh,12.5px)]"}`}>
        {card.text}
      </div>
      {/* Type. §D23-9's turn mark (this card spends the turn) sits on the
          plate's top edge instead — see CardFrame. */}
      <div className="caps-label mt-0.5 text-center text-[clamp(7px,1vh,9px)] tracking-[0.18em] text-dimmed">
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
   bar's brass turn mark on the plate's top edge; an instant carries none.
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

export function CardFrame({ timing }: { timing: string }) {
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
        <path d="M50 -2.4L52.4 0L50 2.4L47.6 0Z" fill="#c9b37e" fillOpacity="0.75" />
      )}
    </svg>
  );
}
