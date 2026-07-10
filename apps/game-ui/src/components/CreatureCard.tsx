import type { CreatureView, TokenView } from "../lib/types";
import { hpColor, powerColor, roman } from "../lib/format";
import { BOSS_CARD_WIDTH, CARD_WIDTH, TOKEN_CARD_WIDTH } from "../lib/layout";
import { useGame } from "../lib/store";
import { ArtControls } from "./ArtControls";
import { KeywordBadges } from "./KeywordBadges";
import { IconSkull } from "./Icons";
import { StatPop } from "./StatPop";

const STAT = "text-[clamp(11px,1.7vh,18px)]";
const META = "text-[clamp(8px,1.2vh,13px)]";
const NAME = "text-[clamp(9px,1.4vh,13px)]";
// Long names on a standard-width card drop one notch instead of truncating.
const NAME_LONG = "text-[clamp(8px,1.15vh,11px)]";

export function CreatureCard({ creature, isTarget }: { creature: CreatureView; isTarget?: boolean }) {
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);
  const encounterId = useGame((s) => s.snapshot?.encounter_id ?? "");
  // This enemy has an action (attack / spell / ability) pending on the stack.
  const acting = useGame((s) => (s.snapshot?.stack ?? []).some((r) => r.source_id === creature.id));

  // Boss hooks are dormant (engine has no boss support — INTERFACE_NOTES §4.3).
  // Creatures share the player-card width (aspect-square, so shorter than a 9:16 PC).
  // One frame state at a time, highest-stakes first: target brackets > execute
  // window (blood brackets) > acting ember > plain hairline.
  const size = creature.is_boss ? BOSS_CARD_WIDTH : CARD_WIDTH;
  const frame = isTarget
    ? "brackets cursor-pointer border-brass-hi"
    : creature.in_execute_window
      ? "brackets anim-ember border-blood"
      : acting
        ? "anim-ember border-blood"
        : "border-line2";
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";

  return (
    <div
      onClick={() => isTarget && pickTargetId(creature.id)}
      title={creature.name}
      style={{
        width: size,
        ...(creature.in_execute_window && !isTarget
          ? ({ "--bracket-color": "#c25a50" } as React.CSSProperties)
          : {}),
      }}
      className={`group relative aspect-square shrink-0 select-none border bg-ink-3 shadow-[0_10px_26px_rgba(0,0,0,0.55)] transition ${frame} ${dimUntargeted} ${
        isTarget ? "cursor-pointer" : "cursor-default"
      } ${creature.is_boss ? "z-10" : ""}`}
    >
      {/* art slot — generated portrait when it exists, engraved sigil until then */}
      {creature.image ? (
        <img
          src={creature.image}
          alt=""
          className="pointer-events-none absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <>
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(80%_70%_at_50%_32%,rgba(70,110,118,0.35),transparent_75%),linear-gradient(180deg,#1d2730_0%,#141a22_55%,#10131b_100%)]" />
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[#7d99a4] opacity-40">
            <IconSkull className="h-1/2 w-1/2" />
          </div>
        </>
      )}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[38%] bg-gradient-to-t from-black/90 via-black/45 to-transparent" />

      {/* art controls — appear on hover, aimed at the pool design (clones share) */}
      {encounterId && (
        <div className="absolute right-1 top-1 z-10 opacity-0 transition group-hover:opacity-100">
          <ArtControls
            encounterId={encounterId}
            kind="enemy"
            enemyId={creature.base_id}
            hasImage={!!creature.image}
            subject={creature.name}
          />
        </div>
      )}

      {/* level — top-left gem, same chrome as the power/HP plaque */}
      <div className={`absolute -left-px top-1.5 border border-l-0 border-line bg-ink-0/80 px-1.5 py-0.5 font-display ${STAT} leading-none tracking-[0.06em] text-parch`}>
        {roman(creature.level)}
      </div>
      <div className="absolute left-1.5 top-[22%]">
        <KeywordBadges keywords={creature.keywords} counters={creature.counters} />
      </div>

      {/* channelling strip — named so the player knows what breaking does */}
      {creature.is_channeling && (
        <div
          title={`Channeling: ${(creature.channels ?? []).map((c) => c.name).join(" · ")}\nBreak it: one hit of ≥${creature.break_threshold} damage, or remove the channeler.`}
          className={`caps-label absolute inset-x-1 bottom-[26%] truncate border border-aether/50 bg-ink-0/80 px-1 py-0.5 text-center text-[clamp(7px,1vh,9px)] tracking-[0.12em] text-aether`}
        >
          {(creature.channels ?? [])[0]?.name ?? "Channeling"}
          {(creature.channels?.length ?? 0) > 1 && ` +${creature.channels.length - 1}`}
        </div>
      )}

      {/* stats — bottom-right gem */}
      <div className={`absolute -right-px bottom-[15%] border border-r-0 border-line bg-ink-0/80 px-1.5 py-0.5 font-display ${STAT} leading-none`}>
        <span className={powerColor(creature.power)}>{creature.power.current}</span>
        <span className="px-0.5 text-dimmed">/</span>
        <span className={hpColor(creature.hp)}>{creature.hp.current}</span>
      </div>

      {/* nameplate */}
      <div className="absolute inset-x-0 bottom-0 px-0.5 pb-1 pt-0.5 text-center">
        <div
          className={`caps-label truncate ${
            !creature.is_boss && creature.name.length > 15 ? NAME_LONG : NAME
          } tracking-normal ${
            creature.is_boss ? "text-[#e7cfc4]" : "text-parch"
          }`}
        >
          {creature.name}
        </div>
      </div>

      <StatPop hp={creature.hp.current} />
    </div>
  );
}

export function TokenCard({ token, isTarget }: { token: TokenView; isTarget?: boolean }) {
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);
  const encounterId = useGame((s) => s.snapshot?.encounter_id ?? "");
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";
  return (
    <div
      onClick={() => isTarget && pickTargetId(token.id)}
      title={`${token.name} (ally)`}
      style={{ width: TOKEN_CARD_WIDTH }}
      className={`group relative aspect-square shrink-0 select-none border bg-ink-3 shadow transition ${
        isTarget ? "brackets cursor-pointer border-brass-hi" : "border-tide/40"
      } ${dimUntargeted}`}
    >
      {token.image ? (
        <img
          src={token.image}
          alt=""
          className="pointer-events-none absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_60%_at_50%_35%,rgba(130,180,201,0.25),transparent_75%),linear-gradient(180deg,#16202a,#10141c)]" />
      )}

      {/* art controls — all spawns of this token definition share the image */}
      {encounterId && (
        <div className="absolute right-0.5 top-0.5 z-10 opacity-0 transition group-hover:opacity-100">
          <ArtControls
            encounterId={encounterId}
            kind="enemy"
            enemyId={token.base_id}
            hasImage={!!token.image}
            subject={token.name}
          />
        </div>
      )}
      <div className={`absolute -right-px top-1 border border-r-0 border-line bg-ink-0/80 px-1 font-display ${META} leading-tight`}>
        <span className={powerColor(token.power)}>{token.power.current}</span>
        <span className="text-dimmed">/</span>
        <span className={hpColor(token.hp)}>{token.hp.current}</span>
      </div>
      {/* Keyword/counter badges — top-left (matches the character/creature cards) */}
      <div className="absolute left-0.5 top-0.5">
        <KeywordBadges keywords={token.keywords} counters={token.counters} />
      </div>
      <div className={`caps-label absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/85 to-transparent px-0.5 pb-0.5 pt-1 text-center text-[clamp(7px,1vh,9px)] tracking-[0.06em] text-parch`}>
        {token.name}
      </div>
      <StatPop hp={token.hp.current} />
    </div>
  );
}
