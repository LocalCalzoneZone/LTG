import { useGame } from "../lib/store";
import type { Choice, Choices } from "../lib/choices";
import type { CharacterView } from "../lib/types";
import { IconMend, IconMove, IconShield, IconSkill, IconSword, IconUltimate } from "./Icons";

const CORE: { key: keyof Choices; Icon: typeof IconSword; label: string; flavor?: "offensive" | "defensive_action" | "defensive_reaction" }[] = [
  { key: "attack", Icon: IconSword, label: "Attack", flavor: "offensive" },
  { key: "defend", Icon: IconShield, label: "Defend", flavor: "defensive_action" },
  { key: "mitigate", Icon: IconMend, label: "Mitigate", flavor: "defensive_reaction" },
  { key: "move", Icon: IconMove, label: "Move" },
];

// Shared button chrome for the 3×2 action grid (core actions + the Skill).
const CELL_ON_ACTIVE = "border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0 shadow-[0_0_14px_rgba(233,204,130,0.3)]";
const CELL_ON = "border-line bg-white/[0.02] text-parch hover:border-brass hover:bg-brass/10 hover:shadow-[0_0_14px_rgba(233,204,130,0.12)]";
const CELL_OFF = "cursor-not-allowed border-line/50 text-dimmed/60 opacity-60";

export function ActionBar({ choices, reaction, char }: {
  choices: Choices | null;
  reaction: boolean;
  char?: CharacterView | null;
}) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);
  const startPassAll = useGame((s) => s.startPassAll);
  const passAllFor = useGame((s) => s.passAllFor);
  // Pass All is a per-character commitment: lit only when THIS character (the
  // one the pass action belongs to) is auto-passing. Clicking again cancels.
  const passActor = choices?.pass?.candidates[0]?.actor_id;
  const passAllActive = passActor != null && passAllFor.includes(passActor);

  const coreBtn = ({ key, Icon, label, flavor }: (typeof CORE)[number]) => {
    const choice = choices?.[key] as Choice | undefined;
    const enabled = !!choice;
    // Stance replacements (§D9-2) arrive as `stance_ability` choices carrying the
    // slot as cardId; compare it so two replaced slots don't cross-highlight.
    const active = armed?.kind === choice?.kind && armed?.cardId == (choice?.cardId ?? null);
    const isStance = choice?.kind === "stance_ability";
    // Evergreen flavour (D8-3.4): the authored display name wins; the default
    // mechanical name rides the tooltip so the mechanics stay legible. A stance
    // has REPLACED this ability, so its authored name/label wins instead.
    const entry = flavor ? char?.evergreen?.[flavor] : undefined;
    const display = isStance
      ? (choice?.label || label)
      : (entry?.name && entry.name !== label ? entry.name : label);
    const tip = isStance
      ? `${choice?.label ?? label} — ${label} (replaced by your stance)`
      : entry
        ? `${label}: ${entry.text}${entry.flavor ? `\n${entry.flavor}` : ""}`
        : label;
    return (
      <button
        key={label}
        disabled={!enabled}
        onClick={() => choice && select(choice)}
        title={tip}
        className={`caps-label flex flex-col items-center justify-center gap-1 border text-[11px] tracking-[0.14em] transition ${
          enabled ? (active ? CELL_ON_ACTIVE : CELL_ON) : CELL_OFF
        }`}
      >
        <Icon size={19} className={enabled ? (active ? "text-ink-0" : "text-brass") : "text-dimmed/60"} />
        <span className="line-clamp-2 max-w-full px-1 text-center leading-[1.1] [overflow-wrap:anywhere]">{display}</span>
      </button>
    );
  };

  // The Skill (D8-3.1): a full grid cell beside the core actions — its own
  // icon, the authored name, and a tooltip with the effect (and cost, if any).
  const skillBtn = () => {
    const skill = char?.skill ?? null;
    const choice = choices?.skill;
    const enabled = !!choice;
    const active = armed?.kind === "use_skill";
    const cost = skill?.cost && skill.cost !== "{0}" ? ` Costs ${skill.cost}.` : "";
    const tip = skill == null
      ? "Skill — none authored for this character"
      : skill.used
        ? `${skill.name ?? "Skill"} — already used this encounter`
        : `${skill.name ?? "Skill"} — Skill (an action, once per encounter; consumes your turn's action unless vigilant).${cost}`
          + `${skill.text ? `\n${skill.text}` : ""}`;
    return (
      <button
        disabled={!enabled}
        onClick={() => choice && select(choice)}
        title={tip}
        className={`caps-label flex flex-col items-center justify-center gap-1 border text-[11px] tracking-[0.14em] transition ${
          enabled ? (active ? CELL_ON_ACTIVE : CELL_ON) : CELL_OFF
        }`}
      >
        <IconSkill size={19} className={enabled ? (active ? "text-ink-0" : "text-brass") : "text-dimmed/60"} />
        {/* The authored name lives in the tooltip; the cell shows "Skill". */}
        <span className="line-clamp-2 max-w-full px-1 text-center leading-[1.1] [overflow-wrap:anywhere]">{skill?.used ? "Skill · spent" : "Skill"}</span>
      </button>
    );
  };

  const passBtnCls = (lit: boolean) =>
    `caps-label min-h-0 flex-1 border text-[11px] tracking-[0.16em] transition ${
      !choices?.pass
        ? "cursor-not-allowed border-line/50 text-dimmed/60"
        : lit
          ? "border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0"
          : "border-brass/60 bg-brass/10 text-brass hover:bg-brass hover:text-ink-0"
    }`;

  return (
    <div className="flex h-full flex-col gap-1.5">
      {reaction && (
        <div className="caps-label border border-brass/40 bg-brass/10 py-0.5 text-center text-[10px] tracking-[0.3em] text-brass-hi">
          Reaction Window
        </div>
      )}
      {/* 3×2 grid: the four core actions, the Skill, and the Pass stack. */}
      <div className="grid min-h-0 flex-1 grid-cols-2 grid-rows-3 gap-1.5">
        {CORE.map(coreBtn)}
        {skillBtn()}
        {/* Pass / Pass All share the last cell — Pass All keeps passing until
            the stack fully resolves. Passing is usually THE decision: brass. */}
        <div className="flex min-h-0 flex-col gap-1.5">
          <button
            disabled={!choices?.pass}
            onClick={() => choices?.pass && select(choices.pass)}
            className={passBtnCls(false)}
          >
            Pass
          </button>
          <button
            disabled={!choices?.pass}
            onClick={startPassAll}
            title={passAllActive
              ? "Auto-passing until the stack resolves — click to cancel"
              : "This character passes every window until the stack fully resolves"}
            className={passBtnCls(passAllActive)}
          >
            Pass All
          </button>
        </div>
      </div>
      {/* End Turn — prominent, always the bottom-most control */}
      <button
        disabled={!choices?.endTurn}
        onClick={() => choices?.endTurn && select(choices.endTurn)}
        className={`chamfer-x caps-label py-2 text-[12px] tracking-[0.3em] transition ${
          choices?.endTurn
            ? "bg-gradient-to-b from-brass/15 to-brass/5 text-brass ring-1 ring-inset ring-brass/40 hover:from-brass-hi hover:to-brass hover:text-ink-0"
            : "cursor-not-allowed bg-white/[0.02] text-dimmed/60"
        }`}
      >
        End Turn
      </button>
    </div>
  );
}

/** The Ultimate column (D8-3.2/3.3): an icon button over a vertical gauge,
 * sitting between the mana widget and the action grid. The gauge fills from
 * the bottom; full means the button can light. Rendered only when the
 * character has an ultimate authored. */
export function UltimateColumn({ choices, char }: {
  choices: Choices | null;
  char?: CharacterView | null;
}) {
  const select = useGame((s) => s.selectChoice);
  const armed = useGame((s) => s.armed);
  const ultimate = char?.ultimate ?? null;
  if (!char || ultimate == null) return null;

  const choice = choices?.ultimate;
  const enabled = !!choice;
  const active = armed?.kind === "use_ultimate";
  const gauge = ultimate.used ? 0 : Math.min(100, char.ultimate_gauge);
  const ready = !ultimate.used && gauge >= 100;
  const tip = ultimate.used
    ? `${ultimate.name ?? "Ultimate"} — already unleashed this encounter`
    : `${ultimate.name ?? "Ultimate"} — Ultimate (an action, once per encounter). `
      + `Castable only on a full gauge — ${char.ultimate_gauge}/100; the gauge is the cost.`
      + `${ultimate.text ? `\n${ultimate.text}` : ""}`;

  return (
    <div className="flex w-[52px] shrink-0 flex-col items-stretch gap-1.5" title={tip}>
      <button
        disabled={!enabled}
        onClick={() => choice && select(choice)}
        className={`flex aspect-square items-center justify-center border transition ${
          enabled
            ? active
              ? "border-brass bg-gradient-to-b from-brass-hi to-brass text-ink-0"
              : "anim-ember border-brass bg-brass/15 text-brass hover:bg-brass hover:text-ink-0"
            : ultimate.used
              ? "cursor-not-allowed border-line/50 text-dimmed/50 opacity-60"
              : "cursor-not-allowed border-line text-dimmed"
        }`}
      >
        <IconUltimate size={22} />
      </button>
      <div className={`caps-label text-center text-[9px] tracking-[0.1em] ${
        ultimate.used ? "text-dimmed/60" : ready ? "text-brass-hi" : "text-dimmed"
      }`}>
        {ultimate.used ? "spent" : `${gauge}/100`}
      </div>
      {/* the vertical gauge — fills bottom-up */}
      <div className="relative min-h-0 flex-1 border border-line bg-black/40">
        <div
          className={`absolute inset-x-0 bottom-0 transition-all ${
            ultimate.used
              ? "bg-dimmed/30"
              : ready
                ? "anim-ember bg-gradient-to-t from-brass to-brass-hi"
                : "bg-brass/60"
          }`}
          style={{ height: `${gauge}%` }}
        />
      </div>
    </div>
  );
}
