import { useEffect, useRef } from "react";
import type { CardView } from "../lib/types";
import type { Choices, Choice } from "../lib/choices";
import { useGame } from "../lib/store";
import { Pips } from "./Pips";
import { IconTurnMark } from "./Icons";

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
            // §D23-9: a sorcery-speed card SPENDS THE TURN, so it wears the same
            // mark as the action bar's left group. Instants carry none — they
            // cost nothing but mana.
            spendsTurn={playable && card.timing !== "instant"}
            justDrawn={justDrawn.has(i)}
            onClick={() => choice && select(choice)}
          />
        );
      })}
    </div>
  );
}

export function HandCard({ card, playable, active, spendsTurn, justDrawn, onClick }: {
  card: CardView;
  playable: boolean;
  active: boolean;
  spendsTurn?: boolean;
  justDrawn?: boolean;
  onClick: () => void;
}) {
  // h-full + aspect-ratio => every card is the same size and top-aligned; the whole
  // card scales with the (window-sized) hand area. Fonts clamp against viewport height.
  // The border STYLE says what kind of card this is at a glance: a sorcery is
  // a plain hairline, an instant is dashed (it can go at any time), a channel
  // is a double rule (it stays on the board).
  const timingBorder = card.timing === "instant"
    ? "border-dashed"
    : card.timing === "channeled" ? "border-double border-[3px]" : "border-solid";
  return (
    <div
      onClick={onClick}
      title={card.text}
      className={`relative flex aspect-[2/3] h-full shrink-0 flex-col border bg-gradient-to-b from-ink-3 to-ink-2 p-1.5 text-parch shadow-[0_6px_16px_rgba(0,0,0,0.5)] transition-all duration-150 ${timingBorder} ${
        playable
          ? active
            ? "-translate-y-1.5 cursor-pointer border-brass shadow-[0_10px_22px_rgba(0,0,0,0.65),0_0_14px_rgba(233,204,130,0.3)]"
            : "cursor-pointer border-line2 hover:-translate-y-1.5 hover:border-brass/70 hover:shadow-[0_10px_22px_rgba(0,0,0,0.65)]"
          : "border-line opacity-40"
      } ${justDrawn ? "hud-card-draw" : ""}`}
    >
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
      {/* Type — with §D23-9's turn mark when casting this card is your turn. */}
      <div className="caps-label mt-0.5 flex items-center justify-end gap-1 text-[clamp(7px,1vh,9px)] tracking-[0.18em] text-dimmed">
        {spendsTurn && (
          <IconTurnMark size={7} className="text-brass/70" />
        )}
        {card.timing}
      </div>
    </div>
  );
}
