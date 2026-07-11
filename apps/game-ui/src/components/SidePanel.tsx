import { useState } from "react";
import { actionModeColor } from "../lib/format";
import { armedTargetIdSet, useGame } from "../lib/store";
import type { CardView, LogEntry } from "../lib/types";
import { HandCard } from "./Hand";

/** `text` with the card name dotted-underlined (the hover-a-card affordance). */
function withCardName(text: string, name: string | undefined) {
  const i = name ? text.indexOf(name) : -1;
  if (i < 0 || !name) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <span className="text-spell underline decoration-dotted underline-offset-2">{name}</span>
      {text.slice(i + name.length)}
    </>
  );
}

// Chronicle line tinting by engine event type (engine.py _log vocabulary).
const DMG_TYPES = new Set([
  "damage", "wound", "fight", "lose_life", "destroyed", "enemy_died",
  "incapacitated", "token_died", "deathtouch", "trample", "loss",
]);
const HEAL_TYPES = new Set([
  "heal", "wound_mend", "revive", "prevent", "prevented", "absorbed",
  "mitigate", "protected", "counters", "pump", "ramp", "win",
]);
const ENEMY_TYPES = new Set([
  "intent_declared", "enemy_react", "enemy_move", "enrage", "taunt",
  "intent_execute", "attack_declared", "boss_immune",
]);
const SYS_TYPES = new Set([
  "capacity_locked", "mana_refresh", "mana_released", "end_step", "end_turn",
  "pass", "shuffle", "scry_done", "add_mana",
]);

function logTint(type: string): string {
  if (DMG_TYPES.has(type)) return "text-[#d99e95]";
  if (HEAL_TYPES.has(type)) return "text-vigor/90";
  if (ENEMY_TYPES.has(type)) return "text-blood/90";
  if (SYS_TYPES.has(type)) return "text-dimmed";
  return "text-mist";
}

export function SidePanel() {
  const snapshot = useGame((s) => s.snapshot);
  const armed = useGame((s) => s.armed);
  const pickTargetId = useGame((s) => s.pickTargetId);
  // The card a hovered log line references, floated at a FIXED position (the
  // log scrolls, so an absolutely-positioned child would be clipped).
  const [hoverCard, setHoverCard] = useState<{ card: CardView; top: number; right: number } | null>(null);
  const showCard = (card: CardView | null | undefined) => (e: React.MouseEvent) => {
    if (!card) return;
    const r = e.currentTarget.getBoundingClientRect();
    setHoverCard({
      card,
      top: Math.max(8, Math.min(r.top - 120, window.innerHeight - 300)),
      right: window.innerWidth - r.left + 8,
    });
  };

  // A counter arms with stack-ref targets ("#<uid>"): those rows become clickable.
  const targetIds = armedTargetIdSet(armed);

  if (!snapshot) {
    return (
      <div className="flex h-full flex-col bg-ink-2 p-2.5">
        <div className="flex flex-1 items-center justify-center px-2 text-center text-xs font-light italic text-dimmed">
          No game loaded.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2.5 bg-ink-2 p-2.5">
      {/* Stack */}
      <Panel title="The Stack">
        {snapshot.stack.length === 0 ? (
          <Empty>empty</Empty>
        ) : (
          snapshot.stack.map((s, i) => {
            const isTarget = targetIds.has(`#${s.uid}`);
            return (
              <div
                key={i}
                onClick={() => isTarget && pickTargetId(`#${s.uid}`)}
                className={`group relative py-1 pl-4 pr-1.5 text-[12px] leading-snug ${
                  isTarget
                    ? "brackets cursor-pointer bg-brass/10"
                    : s.top
                      ? "anim-stackglow"
                      : ""
                }`}
              >
                {/* resolution thread + node */}
                <span className="absolute bottom-0 left-[5px] top-0 w-px bg-line" aria-hidden />
                <span
                  className={`absolute left-[2.5px] top-[11px] h-[6px] w-[6px] rotate-45 ${
                    s.top ? "bg-brass" : "border border-dimmed bg-ink-2"
                  }`}
                  aria-hidden
                />
                <span className={s.source_side === "enemy" ? "text-blood" : "text-tide"}>
                  {s.source_name}
                </span>
                <span className="text-mist"> · {withCardName(s.label, s.card?.name)}</span>
                {s.mode && (
                  <span
                    className={`caps-label ml-1.5 border border-current px-1 text-[9px] tracking-[0.12em] opacity-90 ${actionModeColor(s.mode)}`}
                  >
                    {s.mode}
                  </span>
                )}
                {s.target_name && <span className="text-mist"> → {s.target_name}</span>}
                {/* Hovering a card-backed action pops the FULL card, so the whole
                    effect (e.g. what a break trigger will do) is readable. */}
                {s.card && (
                  <div className="pointer-events-none absolute right-full top-0 z-50 mr-2 hidden h-72 w-48 group-hover:block">
                    <HandCard card={s.card} playable active={false} onClick={() => {}} />
                  </div>
                )}
              </div>
            );
          })
        )}
        <div className="mt-1 pl-4 text-[10px] font-light text-dimmed">top resolves first</div>
      </Panel>

      {/* Intents (D8-1.5) — one veiled line per living enemy for this round
          (two for an enraged boss, §D9-4) */}
      <Panel title="Intents">
        {snapshot.intents.length === 0 ? (
          <Empty>no declared intents</Empty>
        ) : (
          snapshot.intents.map((it) => (
            <IntentLine key={`${it.enemy_id}:${it.slot ?? 1}`} intent={it} />
          ))
        )}
      </Panel>

      {/* Chronicle (fills the rest) */}
      <Panel title="Chronicle" className="min-h-0 flex-1">
        <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto pr-1">
          {snapshot.log.length === 0 ? (
            <Empty>no events yet</Empty>
          ) : (
            snapshot.log.map((e, i) => <ChronicleLine key={i} entry={e} showCard={showCard} onLeave={() => setHoverCard(null)} />)
          )}
        </div>
      </Panel>

      {hoverCard && (
        <div
          className="pointer-events-none fixed z-50 h-72 w-48"
          style={{ top: hoverCard.top, right: hoverCard.right }}
        >
          <HandCard card={hoverCard.card} playable active={false} onClick={() => {}} />
        </div>
      )}
    </div>
  );
}

// The veiled category → a small tag colour: hostile reads blood, magic reads
// spell-blue, gathering reads brass (the fuse), the rest stay mist.
function categoryTint(category: string): string {
  if (category === "threat" || category === "party assault" || category === "row assault")
    return "text-blood/90 border-blood/50";
  if (category === "spellcraft") return "text-spell border-spell/50";
  if (category === "gathering") return "text-brass border-brass/50";
  if (category === "summon" || category === "support") return "text-aether border-aether/50";
  return "text-mist border-line2";
}

function IntentLine({ intent }: { intent: import("../lib/types").IntentView }) {
  const hoverIntent = useGame((s) => s.hoverIntent);
  const setHoverIntent = useGame((s) => s.setHoverIntent);
  const struck = intent.status === "executed" || intent.status === "stripped"
    || intent.status === "fizzled";
  const hovered = hoverIntent?.enemyId === intent.enemy_id;
  return (
    <div
      onMouseEnter={() => setHoverIntent({ enemyId: intent.enemy_id, targetId: intent.target_id })}
      onMouseLeave={() => setHoverIntent(null)}
      className={`px-1 py-0.5 text-[12px] font-light leading-snug transition ${
        hovered ? "bg-brass/10" : ""
      }`}
    >
      <span className={`${struck ? "line-through opacity-50" : ""} ${
        intent.status === "stunned" ? "italic text-dimmed" : "text-mist"
      }`}>
        {intent.line}
      </span>
      {intent.status !== "stunned" && intent.category !== "none" && (
        <span
          className={`caps-label ml-1.5 border px-1 text-[9px] tracking-[0.12em] opacity-90 ${categoryTint(intent.category)}`}
        >
          {intent.category}
        </span>
      )}
      {intent.status === "stripped" && intent.reveal && (
        <div className="pl-3 text-[11px] italic text-brass/90">
          unravelled — it would have been {intent.reveal}
        </div>
      )}
    </div>
  );
}

function ChronicleLine({ entry, showCard, onLeave }: {
  entry: LogEntry;
  showCard: (card: CardView | null | undefined) => (e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  // Turn markers become hairline separators.
  if (entry.type === "turn_start") {
    const label = entry.msg.replace(/—/g, "").trim();
    return (
      <div className="caps-label my-1 flex items-center gap-2 text-[9px] tracking-[0.3em] text-dimmed">
        <span className="h-px flex-1 bg-line" />
        {label}
        <span className="h-px flex-1 bg-line" />
      </div>
    );
  }
  return (
    <div
      onMouseEnter={showCard(entry.card)}
      onMouseLeave={onLeave}
      className={`text-[12px] font-light leading-snug ${logTint(entry.type)}`}
    >
      {entry.card ? withCardName(entry.msg, entry.card.name) : entry.msg}
    </div>
  );
}

function Panel({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`panel-ticks flex flex-col border border-line bg-black/25 px-2.5 py-2 ${className}`}>
      <div className="caps-label mb-1.5 text-[10px] tracking-[0.3em] text-brass">{title}</div>
      <div className="flex min-h-0 flex-1 flex-col gap-0.5">{children}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-[12px] font-light italic text-dimmed">{children}</div>;
}
