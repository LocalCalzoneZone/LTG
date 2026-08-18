import type { CharacterView } from "../lib/types";
import { hpColor, modifierColor, modifierText, powerColor } from "../lib/format";
import { CARD_WIDTH } from "../lib/layout";
import { useGame } from "../lib/store";
import { FxLayer } from "./FxLayer";
import { KeywordBadges } from "./KeywordBadges";
import { PanelAnim } from "./PanelAnim";
import { StatPop } from "./StatPop";

interface Props {
  char: CharacterView;
  focused: boolean;
  isHolder: boolean;
  waiting: boolean; // holder we don't control -> "waiting on X"
  isTarget?: boolean; // this card is a legal target of the current armed site
}

// Card height scales with the viewport (aspect-ratio drives the width). Fonts use
// clamp() against viewport height so overlays stay legible at any window size.
const BIG = "text-[clamp(15px,2.4vh,26px)]";
const SMALL = "text-[clamp(8px,1.1vh,12px)]";
const NAME = "text-[clamp(9px,1.4vh,14px)]";

// Channeling glow tint (state-effects pass): the first WUBRG letter in the
// reserved pip string picks the diamond's colour; digits are generic and
// skipped; no letter at all falls back to brass (a colourless channel).
const CHANNEL_TINT: Record<string, string> = {
  W: "rgba(233,214,160,1)",
  U: "rgba(130,180,201,1)",
  B: "rgba(158,138,188,1)",
  R: "rgba(214,122,84,1)",
  G: "rgba(132,199,147,1)",
};
const CHANNEL_TINT_DEFAULT = "rgba(201,179,126,1)"; // brass

function channelTint(reservedPips: string): string {
  for (const ch of reservedPips) {
    const tint = CHANNEL_TINT[ch];
    if (tint) return tint;
  }
  return CHANNEL_TINT_DEFAULT;
}

export function CharacterCard({ char, focused, isHolder, waiting, isTarget }: Props) {
  const setFocus = useGame((s) => s.setFocus);
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);
  const setInspect = useGame((s) => s.setInspect);
  // Intents-window hover (D8-1.5): light up when a hovered intent locks onto us.
  const intentLit = useGame((s) => s.hoverIntent?.targetId === char.id);

  const onClick = () => {
    if (isTarget) {
      pickTargetId(char.id);
      return;
    }
    if (armed) return; // mid-targeting, a stray click must not pop the inspector
    if (char.is_active_focusable) setFocus(char.id);
    setInspect(char.id);
  };

  // One frame state at a time, highest-stakes first: target brackets > holder
  // breathe > focus edge > plain hairline.
  const frame = isTarget
    ? "brackets cursor-pointer border-brass-hi"
    : isHolder
      ? "anim-breathe border-brass"
      : focused
        ? "border-tide/70 shadow-[0_0_0_1px_rgba(130,180,201,0.4)]"
        : "border-line2";

  const dim = char.incapacitated ? "grayscale opacity-60" : "";
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";

  return (
    <div
      onClick={onClick}
      title={`${char.name} — click to inspect`}
      style={{
        width: CARD_WIDTH,
        ...(char.portrait
          ? { backgroundImage: `url(${char.portrait})`, backgroundSize: "cover", backgroundPosition: "top" }
          : {}),
      }}
      className={`relative aspect-[9/16] shrink-0 select-none border bg-ink-3 shadow-[0_10px_26px_rgba(0,0,0,0.55)] transition ${
        char.portrait ? "" : "bg-gradient-to-b from-ink-3 to-ink-1"
      } ${frame} ${dim} ${dimUntargeted} ${
        intentLit ? "shadow-[0_0_0_1px_rgba(194,90,80,0.6)]" : ""
      } ${isTarget || !armed ? "cursor-pointer" : "cursor-default"}`}
    >
      {/* Panel animation (Update 16): a clip over the portrait while an action
          resolves; renders nothing when the loadout has no clips. */}
      <PanelAnim charId={char.id} bundle={char.anims} incapacitated={char.incapacitated} />

      {/* scrims keep overlays legible without boxing the art */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-1/5 bg-gradient-to-b from-black/50 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[38%] bg-gradient-to-t from-black/90 via-black/50 to-transparent" />

      {/* Channeling base-glow — held magic burning at the card's base, tinted
          by the reserved colour, stronger with more held channels. */}
      {char.is_channeling && char.channels_summary.length > 0 && (
        <div
          className="fx-channel-base"
          style={{
            "--channel-color": channelTint(char.channels_summary[0].reserved_pips),
            "--channel-n": char.channels_summary.length,
          } as React.CSSProperties}
          aria-hidden
        />
      )}

      {/* Your-move / waiting chevron banner */}
      {(isHolder || waiting) && (
        <div
          className={`chamfer-x-sm caps-label absolute -top-2 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap px-2.5 py-0.5 text-[clamp(7px,1vh,9px)] tracking-[0.22em] ${
            isHolder
              ? "bg-gradient-to-b from-brass-hi to-brass text-ink-0"
              : "bg-ink-3 text-tide ring-1 ring-tide/40"
          }`}
        >
          {isHolder ? "Your Move" : "Waiting"}
        </div>
      )}

      {/* keyword sigils + counters — top-left, off the face */}
      <div className="absolute left-1.5 top-1.5">
        <KeywordBadges keywords={char.keywords} counters={char.counters}
          poison={char.poison_counters} regen={char.regen_counters} />
      </div>

      {/* ultimate gauge (D8-3.3) — a thin brass meter above the stat gems */}
      {char.ultimate != null && (
        <div
          title={`Ultimate gauge ${char.ultimate_gauge}/100${char.ultimate.used ? " — spent this encounter" : char.ultimate_gauge >= 100 ? " — READY" : ""}`}
          className="absolute inset-x-1.5 bottom-[8%] h-[3px] bg-black/60 ring-1 ring-line"
        >
          <div
            className={`h-full transition-all ${
              char.ultimate.used
                ? "bg-dimmed/50"
                : char.ultimate_gauge >= 100
                  ? "anim-ember bg-gradient-to-r from-brass to-brass-hi"
                  : "bg-brass/70"
            }`}
            style={{ width: `${Math.min(100, char.ultimate_gauge)}%` }}
          />
        </div>
      )}

      {/* Channeling chip */}
      {char.is_channeling && (
        <div className="caps-label absolute inset-x-1.5 bottom-[26%] truncate border border-aether/50 bg-ink-0/80 px-1.5 py-0.5 text-center text-[clamp(7px,1vh,9px)] tracking-[0.14em] text-aether">
          Channeling
        </div>
      )}

      {/* stat gems — power bottom-left, HP bottom-right (MTG P/T position) */}
      <div className="absolute -left-px bottom-[10%] flex items-baseline gap-1 border border-l-0 border-line bg-ink-0/80 px-1.5 py-0.5 leading-none">
        <span className={`font-display ${BIG} ${powerColor(char.power)}`}>{char.power.current}</span>
        {char.power.modifier !== 0 && (
          <span className={`${SMALL} ${modifierColor(char.power.modifier)}`}>
            {modifierText(char.power.modifier)}
          </span>
        )}
        <span className={`${SMALL} text-dimmed`}>{char.power.base}</span>
      </div>
      <div className="absolute -right-px bottom-[10%] flex items-baseline gap-1 border border-r-0 border-line bg-ink-0/80 px-1.5 py-0.5 leading-none">
        <span className={`font-display ${BIG} ${hpColor(char.hp)}`}>{char.hp.current}</span>
        {char.hp.modifier !== 0 && (
          <span className={`${SMALL} ${modifierColor(char.hp.modifier)}`}>
            {modifierText(char.hp.modifier)}
          </span>
        )}
        <span className={`${SMALL} text-dimmed`}>{char.hp.base}</span>
      </div>

      {/* nameplate */}
      <div className="absolute inset-x-0 bottom-0 px-1 pb-1.5 pt-0.5 text-center">
        <div className={`caps-label truncate ${NAME} tracking-[0.1em] text-parch`}>{char.name}</div>
      </div>

      {char.incapacitated && (
        <div className="caps-label absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-[clamp(11px,1.8vh,17px)] tracking-[0.3em] text-blood">
          Downed
        </div>
      )}

      <StatPop hp={char.hp.current} />
      <FxLayer id={char.id} />
    </div>
  );
}
