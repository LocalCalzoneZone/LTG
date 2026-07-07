import type { CardView } from "../lib/types";
import type { Choices, Choice } from "../lib/choices";
import { useGame } from "../lib/store";
import { Pips } from "./Pips";
import { IconSigil } from "./Icons";

export function Hand({ hand, choices }: { hand: CardView[]; choices: Choices | null }) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);

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
            onClick={() => choice && select(choice)}
          />
        );
      })}
    </div>
  );
}

export function HandCard({ card, playable, active, onClick }: {
  card: CardView;
  playable: boolean;
  active: boolean;
  onClick: () => void;
}) {
  // h-full + aspect-ratio => every card is the same size and top-aligned; the whole
  // card scales with the (window-sized) hand area. Fonts clamp against viewport height.
  return (
    <div
      onClick={onClick}
      title={card.text}
      className={`relative flex aspect-[2/3] h-full shrink-0 flex-col border bg-gradient-to-b from-ink-3 to-ink-2 p-1.5 text-parch shadow-[0_6px_16px_rgba(0,0,0,0.5)] transition-all duration-150 ${
        playable
          ? active
            ? "-translate-y-1.5 cursor-pointer border-brass shadow-[0_10px_22px_rgba(0,0,0,0.65),0_0_14px_rgba(233,204,130,0.3)]"
            : "cursor-pointer border-line2 hover:-translate-y-1.5 hover:border-brass/70 hover:shadow-[0_10px_22px_rgba(0,0,0,0.65)]"
          : "border-line opacity-40"
      }`}
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
      {/* Reserved art slot (3:2) — sigil placeholder until card art exists */}
      <div className="relative my-1 flex aspect-[3/2] w-full items-center justify-center border border-line bg-[radial-gradient(70%_60%_at_50%_40%,rgba(90,110,120,0.22),transparent_75%),linear-gradient(180deg,#1c222c,#141821)] text-[#6f7f8f]">
        <IconSigil className="h-2/5 w-2/5 opacity-50" />
      </div>
      {/* Effect text (left-aligned, fills) */}
      <div className="flex-1 overflow-hidden text-[clamp(8px,1.1vh,11px)] font-light leading-snug text-mist">
        {card.text}
      </div>
      {/* Type */}
      <div className="caps-label mt-0.5 text-right text-[clamp(7px,1vh,9px)] tracking-[0.18em] text-dimmed">
        {card.timing}
      </div>
    </div>
  );
}
