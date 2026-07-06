import type { CardView } from "../lib/types";
import type { Choices, Choice } from "../lib/choices";
import { useGame } from "../lib/store";
import { Pips } from "./Pips";

export function Hand({ hand, choices }: { hand: CardView[]; choices: Choices | null }) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);

  if (!hand.length) {
    return <div className="flex h-full items-center justify-center text-sm italic text-gray-600">empty hand</div>;
  }

  return (
    <div className="scroll-thin flex h-full items-stretch gap-2 overflow-x-auto px-1 py-0.5">
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
      className={`relative flex aspect-[2/3] h-full shrink-0 flex-col overflow-hidden rounded-lg bg-gradient-to-b from-slate-700 to-slate-900 p-1.5 text-white shadow transition ${
        playable
          ? active
            ? "cursor-pointer ring-2 ring-yellow-400"
            : "cursor-pointer ring-1 ring-white/20 hover:ring-blue-400"
          : "opacity-45 ring-1 ring-black/40"
      }`}
    >
      {/* Name (shrink-to-fit) + cost */}
      <div className="flex items-start justify-between gap-1">
        <span className="line-clamp-2 text-[clamp(10px,1.5vh,15px)] font-bold leading-tight">{card.name}</span>
        <div className="shrink-0">
          <Pips cost={card.cost} size={14} />
        </div>
      </div>
      {/* Art placeholder (3:2) */}
      <div className="my-1 aspect-[3/2] w-full rounded bg-slate-600/60" />
      {/* Effect text (left-aligned, fills) */}
      <div className="flex-1 overflow-hidden text-[clamp(8px,1.15vh,12px)] leading-tight text-gray-300">
        {card.text}
      </div>
      {/* Type */}
      <div className="mt-0.5 text-right text-[clamp(8px,1.1vh,11px)] italic text-gray-400">{card.timing}</div>
    </div>
  );
}
