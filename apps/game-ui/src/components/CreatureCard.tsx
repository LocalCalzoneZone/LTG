import type { CorpseView, CreatureView, TokenView } from "../lib/types";
import { hpColor, powerColor, roman } from "../lib/format";
import { BOSS_CARD_WIDTH, CARD_WIDTH, TOKEN_CARD_WIDTH } from "../lib/layout";
import { useGame } from "../lib/store";
import { ArtControls } from "./ArtControls";
import { FxLayer } from "./FxLayer";
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
  const setInspect = useGame((s) => s.setInspect);
  const encounterId = useGame((s) => s.snapshot?.encounter_id ?? "");
  // This enemy has an action (attack / spell / ability) pending on the stack.
  const acting = useGame((s) => (s.snapshot?.stack ?? []).some((r) => r.source_id === creature.id));
  // Intents-window hover wiring (D8-1.5): the line and the card highlight together.
  const hoverIntent = useGame((s) => s.hoverIntent);
  const setHoverIntent = useGame((s) => s.setHoverIntent);
  const intentLit = hoverIntent != null
    && (hoverIntent.enemyId === creature.id || hoverIntent.targetId === creature.id);

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
      onClick={() =>
        isTarget ? pickTargetId(creature.id) : !armed && setInspect(creature.id)}
      onMouseEnter={() => creature.intent && setHoverIntent({
        enemyId: creature.id, targetId: creature.intent.target_id })}
      onMouseLeave={() => setHoverIntent(null)}
      title={`${creature.intent ? `${creature.name} — ${creature.intent.line}` : creature.name}\nClick to inspect.`}
      style={{
        width: size,
        ...(creature.in_execute_window && !isTarget
          ? ({ "--bracket-color": "#c25a50" } as React.CSSProperties)
          : {}),
      }}
      className={`group relative aspect-square shrink-0 select-none border bg-ink-3 shadow-[0_10px_26px_rgba(0,0,0,0.55)] transition ${frame} ${dimUntargeted} ${
        intentLit ? "shadow-[0_0_0_1px_rgba(233,204,130,0.5)]" : ""
      } ${isTarget || !armed ? "cursor-pointer" : "cursor-default"} ${creature.is_boss ? "z-10" : ""}`}
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
        <KeywordBadges keywords={creature.keywords} counters={creature.counters}
          poison={creature.poison_counters} regen={creature.regen_counters} />
      </div>

      {/* charge gauge (D8-2.4) — the public windup pips: what they feed is veiled */}
      {(creature.charge > 0 || creature.charge_threshold != null) && (
        <div
          title={`Charge ${creature.charge}${creature.charge_threshold ? ` / ${creature.charge_threshold}` : ""} — it is gathering power; what detonates is hidden until it fires.`}
          className="absolute inset-x-1 bottom-[36%] flex items-center justify-center gap-1 border border-brass/40 bg-ink-0/80 px-1 py-0.5"
        >
          {Array.from({ length: Math.max(creature.charge_threshold ?? 0, creature.charge) }).map((_, i) => (
            <span
              key={i}
              className={`h-[6px] w-[6px] rotate-45 ${
                i < creature.charge ? "anim-ember bg-brass" : "border border-brass/40 bg-transparent"
              }`}
            />
          ))}
        </div>
      )}

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
      <FxLayer id={creature.id} />
    </div>
  );
}

// A corpse marker (§D9-1.7): small and dim on its row — information, not
// spectacle. A stirring corpse carries a subtle pulse; corpse-legal picks
// (control / exile) make it a clickable target like any card.
export function CorpseMarker({ corpse, isTarget }: { corpse: CorpseView; isTarget?: boolean }) {
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);
  const dimUntargeted = armed && !isTarget ? "opacity-30" : "";
  const stirring = corpse.stirring > 0;
  const title = stirring
    ? `${corpse.name}'s corpse stirs — it rises in ${corpse.stirring} Upkeep(s) unless exiled or raised.`
    : `${corpse.name}'s corpse — defeated; a necromancer can raise it, exile burns it.`;
  return (
    <div
      onClick={() => isTarget && pickTargetId(corpse.id)}
      title={title}
      style={{ width: "clamp(50px, 5.5vh, 80px)" }}
      className={`relative aspect-square shrink-0 select-none border transition ${
        isTarget
          ? "brackets cursor-pointer border-brass-hi opacity-90"
          : stirring
            ? "anim-ember border-blood/50 opacity-70"
            : "border-line2 opacity-40"
      } ${dimUntargeted} bg-ink-0/70`}
    >
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-dimmed">
        <IconSkull className="h-3/5 w-3/5" />
      </div>
      {stirring && (
        <div className="caps-label absolute inset-x-0 top-0 text-center text-[8px] tracking-[0.14em] text-blood">
          {corpse.stirring}
        </div>
      )}
      <div className="caps-label absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/85 to-transparent px-0.5 text-center text-[clamp(6px,0.9vh,8px)] tracking-[0.06em] text-dimmed">
        {corpse.name}
      </div>
    </div>
  );
}

export function TokenCard({ token, isTarget }: { token: TokenView; isTarget?: boolean }) {
  const pickTargetId = useGame((s) => s.pickTargetId);
  const armed = useGame((s) => s.armed);
  const setInspect = useGame((s) => s.setInspect);
  const encounterId = useGame((s) => s.snapshot?.encounter_id ?? "");
  const dimUntargeted = armed && !isTarget ? "opacity-40" : "";
  const controlTitle = token.control_kind == null ? "" :
    token.control_kind === "dominated"
      ? `\nDominated enemy — fights for the party${token.control_left != null ? ` (${token.control_left} round(s) left)` : " for the encounter"}; it snaps back when control ends.`
      : `\nRaised undead — crumbles when the necromancy ends${token.control_left != null ? ` (${token.control_left} round(s) left)` : ""}.`;
  return (
    <div
      onClick={() => (isTarget ? pickTargetId(token.id) : !armed && setInspect(token.id))}
      title={`${token.name} (ally)${controlTitle}\nClick to inspect.`}
      style={{ width: TOKEN_CARD_WIDTH }}
      className={`group relative aspect-square shrink-0 select-none border bg-ink-3 shadow transition ${
        isTarget ? "brackets cursor-pointer border-brass-hi" : "border-tide/40"
      } ${!armed ? "cursor-pointer" : ""} ${dimUntargeted}`}
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
        <KeywordBadges keywords={token.keywords} counters={token.counters}
          poison={token.poison_counters} regen={token.regen_counters} />
      </div>
      {/* Control chip (§D9-1.4): a dominated enemy / raised undead with duration */}
      {token.control_kind != null && (
        <div className="caps-label absolute inset-x-0 top-0 truncate border-b border-aether/50 bg-ink-0/85 px-0.5 text-center text-[clamp(6px,0.9vh,8px)] tracking-[0.1em] text-aether">
          {token.control_kind === "dominated" ? "controlled" : "undead"}
          {token.control_left != null ? ` · ${token.control_left}` : ""}
        </div>
      )}
      <div className={`caps-label absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/85 to-transparent px-0.5 pb-0.5 pt-1 text-center text-[clamp(7px,1vh,9px)] tracking-[0.06em] text-parch`}>
        {token.name}
      </div>
      <StatPop hp={token.hp.current} />
      <FxLayer id={token.id} />
    </div>
  );
}
