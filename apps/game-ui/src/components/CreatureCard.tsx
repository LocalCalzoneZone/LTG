import type { CreatureView, TokenView } from "../lib/types";
import { hpColor, powerColor } from "../lib/format";
import { BOSS_CARD_WIDTH, CARD_WIDTH, TOKEN_CARD_WIDTH } from "../lib/layout";
import { useGame } from "../lib/store";

const KEYWORD_ABBR: Record<string, string> = {
  flying: "Fly",
  lifelink: "Life",
  deathtouch: "Death",
  reach: "Reach",
};

const STAT = "text-[clamp(11px,1.8vh,20px)]";
const META = "text-[clamp(9px,1.3vh,14px)]";
const NAME = "text-[clamp(9px,1.4vh,15px)]";

export function CreatureCard({ creature, isTarget }: { creature: CreatureView; isTarget?: boolean }) {
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);

  // Boss hooks are dormant (engine has no boss support — INTERFACE_NOTES §4.3).
  // Creatures share the player-card width (aspect-square, so shorter than a 9:16 PC).
  const size = creature.is_boss ? BOSS_CARD_WIDTH : CARD_WIDTH;
  const border = creature.is_boss
    ? "ring-2 ring-amber-500"
    : isTarget
      ? "ring-4 ring-yellow-400"
      : "ring-1 ring-black/40";
  const execute = creature.in_execute_window ? "ring-4 ring-red-500 ring-active" : "";
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";

  return (
    <div
      onClick={() => isTarget && pickTargetId(creature.id)}
      title={creature.name}
      style={{ width: size }}
      className={`relative aspect-square shrink-0 select-none rounded-lg bg-gradient-to-b from-rose-900 to-slate-900 shadow-lg transition ${border} ${execute} ${dimUntargeted} ${
        isTarget ? "cursor-pointer" : "cursor-default"
      } ${creature.is_boss ? "z-10" : ""}`}
    >
      {/* Level — top-left */}
      <div className={`absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 ${META} font-bold text-gray-200`}>
        L{creature.level}
      </div>
      {/* Power / HP — top-right */}
      <div className={`absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 ${STAT} font-bold leading-none`}>
        <span className={powerColor(creature.power)}>{creature.power.current}</span>
        <span className="text-gray-400"> / </span>
        <span className={hpColor(creature.hp)}>{creature.hp.current}</span>
      </div>
      {creature.is_channeling && (
        <div className={`absolute left-1.5 bottom-7 rounded-full bg-purple-600/80 px-1 ${META} text-white`}>✦</div>
      )}
      {/* Keywords (flying, lifelink, …) — stacked top-left under the level chip */}
      {creature.keywords.length > 0 && (
        <div className="absolute left-1.5 top-7 flex flex-col gap-0.5">
          {creature.keywords.map((kw) => (
            <span key={kw} title={kw} className={`rounded bg-indigo-600/80 px-1 ${META} font-semibold leading-tight text-white`}>
              {KEYWORD_ABBR[kw] ?? kw.slice(0, 4)}
            </span>
          ))}
        </div>
      )}
      {/* Name — bottom-center */}
      <div className={`absolute inset-x-0 bottom-0 truncate rounded-b-lg bg-black/65 px-1 py-1 text-center ${NAME} font-semibold`}>
        {creature.name}
      </div>
    </div>
  );
}

export function TokenCard({ token, isTarget }: { token: TokenView; isTarget?: boolean }) {
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";
  return (
    <div
      onClick={() => isTarget && pickTargetId(token.id)}
      title={`${token.name} (ally)`}
      style={{ width: TOKEN_CARD_WIDTH }}
      className={`relative aspect-square shrink-0 select-none rounded-md bg-gradient-to-b from-emerald-800 to-slate-900 shadow ${
        isTarget ? "ring-4 ring-yellow-400 cursor-pointer" : "ring-1 ring-emerald-500/50"
      } ${dimUntargeted}`}
    >
      <div className={`absolute right-0.5 top-0.5 rounded bg-black/60 px-1 ${META} font-bold leading-none`}>
        <span className={powerColor(token.power)}>{token.power.current}</span>
        <span className="text-gray-400">/</span>
        <span className={hpColor(token.hp)}>{token.hp.current}</span>
      </div>
      <div className={`absolute inset-x-0 bottom-0 truncate rounded-b-md bg-black/65 px-0.5 text-center ${META}`}>
        {token.name}
      </div>
    </div>
  );
}
