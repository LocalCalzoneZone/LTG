import { useGame } from "../lib/store";
import type { Choice, Choices } from "../lib/choices";
import type { CharacterView } from "../lib/types";
import {
  IconMend, IconMove, IconPairMark, IconShield, IconSkill, IconSword,
  IconTurnMark, IconUltimate,
} from "./Icons";

type CoreSpec = {
  key: keyof Choices;
  Icon: typeof IconSword;
  label: string;
  flavor?: "offensive" | "defensive_action" | "defensive_reaction";
  // §D23-1: which turn group this verb belongs to, for the disabled reason.
  group?: "turn" | "pair";
};

const ATTACK: CoreSpec = { key: "attack", Icon: IconSword, label: "Attack", flavor: "offensive", group: "turn" };
const DEFEND: CoreSpec = { key: "defend", Icon: IconShield, label: "Defend", flavor: "defensive_action", group: "pair" };
const MOVE: CoreSpec = { key: "move", Icon: IconMove, label: "Move", group: "pair" };
const MITIGATE: CoreSpec = { key: "mitigate", Icon: IconMend, label: "Mitigate", flavor: "defensive_reaction" };

// §D23-9 — why a cell is dark. The words "action" and "half action" never
// appear: an action is a thing on the stack, and calling a Move half of one is
// exactly the framing the turn groups replaced.
function closedReason(char: CharacterView | null | undefined, spec: CoreSpec): string | null {
  if (!char) return null;
  const open = char.turn_open ?? {};
  if (spec.key === "attack" && char.reach_blocked === "front")
    return "point-blank: ranged can't fire from the Front row";
  if (spec.group && open[spec.key] === false)
    return spec.group === "turn" ? "your turn is spent" : "pair with Defend/Move only";
  return null;
}

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

  const coreBtn = (spec: CoreSpec) => {
    const { key, Icon, label, flavor } = spec;
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
    let display = isStance
      ? (choice?.label || label)
      : (entry?.name && entry.name !== label ? entry.name : label);
    // §D23-8: in a reaction window the Mitigate cell says what it would TURN, so
    // the decision needs no second look at the stack.
    if (key === "mitigate" && reaction && enabled && char)
      display = `${display} −${char.mitigate_value}`;
    const closed = enabled ? null : closedReason(char, spec);
    const base = isStance
      ? `${choice?.label ?? label} — ${label} (replaced by your stance)`
      : entry
        ? `${label}: ${entry.text}${entry.flavor ? `\n${entry.flavor}` : ""}`
        : label;
    const tip = closed ? `${base}\n${closed}` : base;
    return (
      <button
        key={label}
        disabled={!enabled}
        onClick={() => choice && select(choice)}
        title={tip}
        aria-label={closed ? `${label} — ${closed}` : label}
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
    const closed = !enabled && skill != null && !skill.used
      && char?.turn_open?.skill === false ? "your turn is spent" : null;
    const tip = skill == null
      ? "Skill — none authored for this character"
      : skill.used
        ? `${skill.name ?? "Skill"} — already used this encounter`
        : `${skill.name ?? "Skill"} — Skill (once per encounter; taking it is your turn).${cost}`
          + `${skill.text ? `\n${skill.text}` : ""}${closed ? `\n${closed}` : ""}`;
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

  const stackBtnCls = (enabled: boolean) =>
    `caps-label min-h-0 flex-1 border text-[11px] tracking-[0.16em] transition ${
      enabled
        ? "border-brass/60 bg-brass/10 text-brass hover:bg-brass hover:text-ink-0"
        : "cursor-not-allowed border-line/50 text-dimmed/60"
    }`;

  return (
    <div className="flex h-full flex-col gap-1.5">
      {reaction && (
        <div className="caps-label border border-brass/40 bg-brass/10 py-0.5 text-center text-[10px] tracking-[0.3em] text-brass-hi">
          Reaction Window
        </div>
      )}
      {/* §D23-9 — the turn GROUPS, read left-to-right in two columns.
          Left: the turn-spending verbs (Attack, Skill — the Ultimate is the same
          group, in its own gauge column). Right: the pair (Defend, Move).
          A brass hairline bracket spans each, with one diamond over the left and
          two half-diamonds over the right; the words are in the tooltips. */}
      <div className="grid grid-cols-2 gap-1.5">
        <GroupBracket Mark={IconTurnMark} label="one of these is your turn" />
        <GroupBracket Mark={IconPairMark} label="these two go together" />
      </div>
      {/* Attack | Defend · Skill | Move · Mitigate | Pass/Delay */}
      <div className="grid min-h-0 flex-1 grid-cols-2 grid-rows-3 gap-1.5">
        {coreBtn(ATTACK)}
        {coreBtn(DEFEND)}
        {skillBtn()}
        {coreBtn(MOVE)}
        {coreBtn(MITIGATE)}
        {/* Pass / Delay share a cell. Pass answers a reaction window (usually
            THE decision: brass). Delay is a main-phase move: the character drops
            to the end of the party turn order for the rest of the encounter and
            the next character goes now. */}
        <div className="flex min-h-0 flex-col gap-1.5">
          <button
            disabled={!choices?.pass}
            onClick={() => choices?.pass && select(choices.pass)}
            className={stackBtnCls(!!choices?.pass)}
          >
            Pass
          </button>
          <button
            disabled={!choices?.delay}
            onClick={() => choices?.delay && select(choices.delay)}
            title={choices?.delay
              ? "Move to the end of the party turn order for the rest of the encounter — the next character acts now; your turn comes round last"
              : "Delay — only at the start of your turn, once per turn, when another character still has a turn to take"}
            className={stackBtnCls(!!choices?.delay)}
          >
            Delay
          </button>
        </div>
      </div>
      {/* Pass-All (§D23-8) beside End Turn — the bottom row of controls. */}
      <div className="grid grid-cols-2 gap-1.5">
        <PassAllToggle char={char} />
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
    </div>
  );
}

/** §D23-9 — one group's brass hairline bracket and its mark. The tooltip says
 *  the rule in words, because a bracket alone teaches nobody. */
function GroupBracket({ Mark, label }: { Mark: typeof IconTurnMark; label: string }) {
  return (
    <div title={label} className="flex items-center justify-center gap-1.5">
      <span className="h-px flex-1 bg-gradient-to-r from-transparent to-brass/40" />
      <Mark size={10} className="text-brass/70" />
      <span className="h-px flex-1 bg-gradient-to-l from-transparent to-brass/40" />
    </div>
  );
}

/** §D23-8 — "pass for the rest of this phase". Two playtest calls shape it:
 *  PER CHARACTER, not per player (a solo player holding the whole party still
 *  wants their tank in every window while the empty-handed archer sits out), and
 *  scoped to WHICHEVER PHASE you press it in, not the enemy phase specifically.
 *  While set, the server answers that one seat's windows automatically; it
 *  clears the moment the phase turns over, so it is a standing "no" for one
 *  phase and never a setting. */
function PassAllToggle({ char }: { char?: CharacterView | null }) {
  const setPassAll = useGame((s) => s.setPassAll);
  const passAllSeats = useGame((s) => s.passAllSeats);
  const step = useGame((s) => s.snapshot?.phase_step ?? "");
  const on = !!char && passAllSeats.includes(char.id);
  const name = char?.name ?? "this character";
  // Name the span the standing "no" actually covers — "for the rest of this
  // phase" leaves the player guessing how long they have just gone quiet for.
  // `phase_step` is the server's own scope, so the words cannot over-promise.
  const here = step ? `the ${step} step` : "this step";
  return (
    <button
      disabled={!char?.controlled}
      onClick={() => char && setPassAll(!on, [char.id])}
      title={!char?.controlled
        ? "Pass All — only for characters you control"
        : on
          ? `${name} is passing every window for the rest of ${here} — click to take their windows back`
          : `Pass every remaining window in ${here} for ${name} alone (the next step asks again)`}
      className={`chamfer-x caps-label py-2 text-[11px] tracking-[0.22em] transition ${
        !char?.controlled
          ? "cursor-not-allowed bg-white/[0.02] text-dimmed/50 ring-1 ring-inset ring-line/50"
          : on
            ? "bg-gradient-to-b from-brass-hi to-brass text-ink-0"
            : "bg-white/[0.02] text-dimmed ring-1 ring-inset ring-line hover:text-brass hover:ring-brass/40"
      }`}
    >
      {on ? "Passing All" : "Pass All"}
    </button>
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
