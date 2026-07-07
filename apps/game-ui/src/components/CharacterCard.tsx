import type { CharacterView } from "../lib/types";
import { hpColor, modifierColor, modifierText, powerColor } from "../lib/format";
import { CARD_WIDTH } from "../lib/layout";
import { useGame } from "../lib/store";
import { KeywordBadges } from "./KeywordBadges";

interface Props {
  char: CharacterView;
  focused: boolean;
  isHolder: boolean;
  waiting: boolean; // holder we don't control -> "waiting on X"
  isTarget?: boolean; // this card is a legal target of the current armed site
}

// Card height scales with the viewport (aspect-ratio drives the width). Fonts use
// clamp() against viewport height so overlays stay legible at any window size.
const BIG = "text-[clamp(16px,2.6vh,30px)]";
const SMALL = "text-[clamp(8px,1.15vh,13px)]";
const NAME = "text-[clamp(10px,1.5vh,16px)]";

export function CharacterCard({ char, focused, isHolder, waiting, isTarget }: Props) {
  const setFocus = useGame((s) => s.setFocus);
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);

  const onClick = () => {
    if (isTarget) {
      pickTargetId(char.id);
      return;
    }
    if (char.is_active_focusable) setFocus(char.id);
  };

  const ring = isTarget
    ? "ring-4 ring-yellow-400 cursor-pointer"
    : focused
      ? "ring-4 ring-blue-400"
      : isHolder
        ? "ring-2 ring-emerald-400"
        : "ring-1 ring-black/40";

  const dim = char.incapacitated ? "grayscale opacity-60" : "";
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";

  return (
    <div
      onClick={onClick}
      title={char.name}
      style={{
        width: CARD_WIDTH,
        ...(char.portrait
          ? { backgroundImage: `url(${char.portrait})`, backgroundSize: "cover", backgroundPosition: "top" }
          : {}),
      }}
      className={`relative aspect-[9/16] shrink-0 select-none overflow-hidden rounded-lg shadow-lg transition ${
        char.portrait ? "bg-slate-800" : "bg-gradient-to-b from-slate-600 to-slate-800"
      } ${ring} ${dim} ${dimUntargeted} ${
        char.is_active_focusable || isTarget ? "cursor-pointer" : "cursor-default"
      }`}
    >
      {/* Power — top-left; keyword/counter badges stack beneath it */}
      <div className="absolute left-1.5 top-1.5 flex flex-col items-start gap-1">
        <div className="flex flex-col items-start rounded bg-black/55 px-1.5 py-0.5 leading-none">
          <span className={`${BIG} font-black ${powerColor(char.power)}`}>{char.power.current}</span>
          <div className={`flex gap-1.5 ${SMALL}`}>
            <span className={modifierColor(char.power.modifier)}>{modifierText(char.power.modifier)}</span>
            <span className="text-gray-400">{char.power.base}</span>
          </div>
        </div>
        <KeywordBadges keywords={char.keywords} counters={char.counters} />
      </div>

      {/* Health — top-right */}
      <div className="absolute right-1.5 top-1.5 flex flex-col items-end rounded bg-black/55 px-1.5 py-0.5 leading-none">
        <span className={`${BIG} font-black ${hpColor(char.hp)}`}>{char.hp.current}</span>
        <div className={`flex gap-1.5 ${SMALL}`}>
          <span className={modifierColor(char.hp.modifier)}>{modifierText(char.hp.modifier)}</span>
          <span className="text-gray-400">{char.hp.base}</span>
        </div>
      </div>

      {/* Channeling badge */}
      {char.is_channeling && (
        <div className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-purple-600/80 px-2 py-0.5 ${SMALL} font-bold text-white shadow ring-1 ring-purple-300`}>
          ✦ channeling
        </div>
      )}

      {/* Priority cue */}
      {(isHolder || waiting) && (
        <div className={`absolute inset-x-0 top-1/3 text-center ${SMALL} font-bold ${waiting ? "text-emerald-300" : "text-emerald-200"}`}>
          {waiting ? "waiting…" : "your move"}
        </div>
      )}

      {/* Name — bottom */}
      <div className={`absolute inset-x-0 bottom-0 truncate rounded-b-lg bg-black/65 px-1 py-1 text-center ${NAME} font-semibold`}>
        {char.name}
      </div>

      {char.incapacitated && (
        <div className={`absolute inset-x-0 top-1/2 -translate-y-1/2 text-center ${NAME} font-black text-red-500`}>
          DOWNED
        </div>
      )}
    </div>
  );
}
