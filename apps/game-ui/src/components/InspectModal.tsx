import type {
  CharacterView,
  CreatureView,
  KeywordInfo,
  StatBlock,
  TokenView,
} from "../lib/types";
import { hpColor, modifierColor, modifierText, powerColor, roman } from "../lib/format";
import { useGame } from "../lib/store";
import { IconSkull, KEYWORD_ICONS } from "./Icons";

// §Inspect: click a portrait to open the full write-up — big art beside the
// name, stat lines, and every keyword / status effect spelled out. Read-only:
// one click anywhere (the portrait included) dismisses it.

type Subject =
  | { kind: "character"; view: CharacterView }
  | { kind: "creature"; view: CreatureView }
  | { kind: "token"; view: TokenView };

const POISON = "text-[#a9bf5e]";

interface Line {
  key: string;
  tone: string; // text colour class
  main: string;
  note?: string;
}

/** Status lines shared by every combatant kind: counters and stat modifiers,
 *  written out with the same rules phrasing as the badge tooltips. Per-effect
 *  attribution isn't in the snapshot, so modifiers say "active effects". */
function commonLines(v: {
  power: StatBlock;
  hp: StatBlock;
  counters: number;
  poison_counters: number;
  regen_counters: number;
  poisoned?: boolean;
  regenerating?: boolean;
}): Line[] {
  const out: Line[] = [];
  if (v.counters > 0) {
    out.push({
      key: "counters",
      tone: "text-vigor",
      main: `+${v.counters}/+${v.counters} — ${v.counters} +1/+1 counter${v.counters > 1 ? "s" : ""}`,
      note: "permanent; already included in the stats shown",
    });
  }
  if (v.poison_counters > 0) {
    out.push({
      key: "poison",
      tone: POISON,
      main: `−0/−${v.poison_counters} — ${v.poison_counters} poison counter${v.poison_counters > 1 ? "s" : ""}`,
      note: "already in the stats shown; any healing cures the ticking, the counters remain",
    });
  }
  if (v.poisoned) {
    out.push({
      key: "poisoned",
      tone: POISON,
      main: "Poisoned — an active poison effect is ticking",
    });
  }
  if (v.regen_counters > 0) {
    out.push({
      key: "regen",
      tone: "text-vigor",
      main: `+0/+${v.regen_counters} — ${v.regen_counters} regen counter${v.regen_counters > 1 ? "s" : ""}`,
      note: "already in the stats shown; broken by damage that connects",
    });
  }
  if (v.regenerating) {
    out.push({
      key: "regenerating",
      tone: "text-vigor",
      main: "Regenerating — an active regeneration effect",
    });
  }
  if (v.power.modifier !== 0) {
    out.push({
      key: "power-mod",
      tone: modifierColor(v.power.modifier),
      main: `${modifierText(v.power.modifier)} Power from active effects`,
      note: `base Power ${v.power.base}`,
    });
  }
  if (v.hp.modifier !== 0) {
    out.push({
      key: "hp-mod",
      tone: modifierColor(v.hp.modifier),
      main: `${modifierText(v.hp.modifier)} HP from active effects (temporary)`,
      note: `printed HP ${v.hp.base}`,
    });
  }
  return out;
}

// serialize.py's status_tags overlap what we already spell out (keywords,
// poison/regen/charge counters, the temp-HP / Power modifiers) — keep only the
// lines with no richer counterpart here (prevent, protection, turn state …).
function extraCharacterTags(char: CharacterView): string[] {
  return char.status_tags.filter(
    (t) =>
      !t.startsWith("⚜") &&
      !/^poison/.test(t) &&
      !/^regen/.test(t) &&
      !/^charge/.test(t) &&
      !/temp HP$/.test(t) &&
      !/Power$/.test(t) &&
      t !== "incapacitated",
  );
}

function characterLines(char: CharacterView): Line[] {
  const out = commonLines(char);
  if (char.incapacitated) {
    out.unshift({
      key: "downed",
      tone: "text-blood",
      main: "Downed — incapacitated; a valid heal / revive target",
    });
  }
  if (char.stance) {
    out.push({
      key: "stance",
      tone: "text-aether",
      main: `Stance: ${char.stance.card_name}`,
      note: "rewires the main abilities while it holds",
    });
  }
  for (const t of extraCharacterTags(char)) {
    // The raw acted-mode / turn-state tags read cryptically alone — phrase them.
    const main =
      t === char.acted_mode
        ? `Has acted this turn (${t})`
        : t === "turn done"
          ? "Turn ended"
          : t;
    out.push({ key: `tag-${t}`, tone: "text-mist", main });
  }
  return out;
}

function creatureLines(c: CreatureView): Line[] {
  const out = commonLines(c);
  if (c.charge > 0 || c.charge_threshold != null) {
    out.push({
      key: "charge",
      tone: "text-brass",
      main: `Charge ${c.charge}${c.charge_threshold ? ` of ${c.charge_threshold}` : ""} — gathering power`,
      note: "what detonates is hidden until it fires",
    });
  }
  if (c.intent && c.intent.line && c.intent.status === "declared") {
    out.push({ key: "intent", tone: "text-blood", main: `Intent — ${c.intent.line}` });
  }
  if (c.rises != null) {
    out.push({
      key: "rises",
      tone: "text-blood",
      main: `Rises — when killed, its corpse stirs and it revives in ${c.rises} Upkeep(s)`,
      note: "unless the corpse is exiled or raised first",
    });
  }
  if (c.in_execute_window) {
    out.push({
      key: "execute",
      tone: "text-blood",
      main: "Execute window — at ≤25% HP its removal immunity has lifted",
    });
  }
  return out;
}

function tokenLines(t: TokenView): Line[] {
  const out = commonLines(t);
  if (t.control_kind != null) {
    out.push({
      key: "control",
      tone: "text-aether",
      main:
        t.control_kind === "dominated"
          ? `Dominated enemy — fights for the party${
              t.control_left != null ? ` (${t.control_left} round(s) left)` : " for the encounter"
            }; snaps back when control ends`
          : `Raised undead — crumbles when the necromancy ends${
              t.control_left != null ? ` (${t.control_left} round(s) left)` : ""
            }`,
    });
  }
  return out;
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="caps-label mb-1.5 flex items-center gap-2 text-[9px] tracking-[0.22em] text-brass">
        {label}
        <span className="h-px flex-1 bg-line" />
      </div>
      {children}
    </div>
  );
}

function KeywordRows({ keywords }: { keywords: KeywordInfo[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      {keywords.map((kw) => {
        const Icon = KEYWORD_ICONS[kw.id];
        return (
          <div key={kw.id} className="flex items-start gap-2">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center border border-line2 bg-ink-0/75 text-brass">
              {Icon ? (
                <Icon className="h-[70%] w-[70%]" />
              ) : (
                <span className="caps-label text-[9px] tracking-normal">
                  {kw.name.charAt(0).toUpperCase()}
                </span>
              )}
            </span>
            <div className="min-w-0 text-sm leading-snug">
              <span className="text-parch">{kw.name}</span>
              {kw.gloss && <span className="font-light text-mist"> — {kw.gloss}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatusRows({ lines }: { lines: Line[] }) {
  if (!lines.length) {
    return <div className="text-sm font-light italic text-dimmed">no active effects</div>;
  }
  return (
    <div className="flex flex-col gap-1">
      {lines.map((l) => (
        <div key={l.key} className="text-sm leading-snug">
          <span className={l.tone}>{l.main}</span>
          {l.note && <span className="font-light text-dimmed"> · {l.note}</span>}
        </div>
      ))}
    </div>
  );
}

/** The channels a combatant holds, written out. Characters carry the full
 *  summary (card, target, text, break clause); enemies just the names plus the
 *  public break rule. */
function ChannelsSection({ subject }: { subject: Subject }) {
  if (subject.kind === "character") {
    const chans = subject.view.channels_summary;
    if (!chans.length) return null;
    return (
      <Section label="Channeling">
        <div className="flex flex-col gap-1.5">
          {chans.map((ch) => (
            <div key={ch.card_id} className="border border-aether/30 bg-aether/5 p-2 text-sm">
              <div className="text-parch">
                {ch.card_name}
                {ch.target_name && <span className="text-mist"> — on {ch.target_name}</span>}
              </div>
              {ch.text && <div className="text-xs font-light text-mist">{ch.text}</div>}
              {ch.break_text && (
                <div className="mt-0.5 text-xs font-light text-brass">
                  When this channel ends: {ch.break_text}.
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>
    );
  }
  if (subject.kind === "creature") {
    const c = subject.view;
    if (!c.is_channeling) return null;
    return (
      <Section label="Channeling">
        <div className="flex flex-col gap-1.5">
          {(c.channels ?? []).map((ch, i) => (
            <div key={`${ch.name}-${i}`} className="border border-aether/30 bg-aether/5 p-2 text-sm">
              <div className="text-aether">{ch.name}</div>
            </div>
          ))}
          <div className="text-xs font-light text-mist">
            Break it: one hit of ≥{c.break_threshold} damage, or remove the channeler.
          </div>
        </div>
      </Section>
    );
  }
  return null;
}

function findSubject(id: string, snap: {
  characters: CharacterView[];
  creatures: CreatureView[];
  tokens: TokenView[];
}): Subject | null {
  const char = snap.characters.find((c) => c.id === id);
  if (char) return { kind: "character", view: char };
  const creature = snap.creatures.find((c) => c.id === id);
  if (creature) return { kind: "creature", view: creature };
  const token = snap.tokens.find((t) => t.id === id);
  if (token) return { kind: "token", view: token };
  return null;
}

export function InspectModal() {
  const inspectId = useGame((s) => s.inspectId);
  const snapshot = useGame((s) => s.snapshot);
  const setInspect = useGame((s) => s.setInspect);
  if (!inspectId || !snapshot) return null;
  const subject = findSubject(inspectId, snapshot);
  if (!subject) return null; // it left the field — nothing to show
  const close = () => setInspect(null);

  const v = subject.view;
  const image = subject.kind === "character" ? subject.view.portrait : subject.view.image;
  const lines =
    subject.kind === "character"
      ? characterLines(subject.view)
      : subject.kind === "creature"
        ? creatureLines(subject.view)
        : tokenLines(subject.view);
  // Characters show their loadout blurb in place of the archetype label;
  // enemies/tokens keep the level line and add their art-direction prose below.
  const subtitle =
    subject.kind === "character"
      ? subject.view.description
        ? ""
        : subject.view.archetype
      : subject.kind === "creature"
        ? `${subject.view.is_boss ? "Boss · " : ""}Level ${roman(subject.view.level)} enemy${
            subject.view.attack_mode ? ` · ${subject.view.attack_mode}` : ""
          }`
        : "ally";

  return (
    <div
      className="fixed inset-0 z-40 flex cursor-pointer items-center justify-center bg-black/70 backdrop-blur-[2px]"
      onClick={close}
      onContextMenu={(e) => {
        e.preventDefault();
        close();
      }}
    >
      <div className="panel-ticks flex max-h-[90vh] w-[min(96vw,1180px)] gap-6 overflow-y-auto border border-line2 bg-ink-2 p-5 shadow-2xl">
        {/* the portrait, writ large — same fallback sigil as the card. The vh
            term keeps the tall 9:16 character art inside the panel. */}
        <div
          className={`relative shrink-0 self-start overflow-hidden border border-line2 bg-ink-3 ${
            subject.kind === "character"
              ? "aspect-[9/16] w-[min(42vw,44vh,420px)]"
              : "aspect-square w-[min(50vw,76vh,510px)]"
          }`}
        >
          {image ? (
            <img src={image} alt={v.name} className="absolute inset-0 h-full w-full object-cover object-top" />
          ) : (
            <>
              <div className="absolute inset-0 bg-[radial-gradient(80%_70%_at_50%_32%,rgba(70,110,118,0.35),transparent_75%),linear-gradient(180deg,#1d2730_0%,#141a22_55%,#10131b_100%)]" />
              {subject.kind !== "character" && (
                <div className="absolute inset-0 flex items-center justify-center text-[#7d99a4] opacity-40">
                  <IconSkull className="h-1/2 w-1/2" />
                </div>
              )}
            </>
          )}
        </div>

        {/* the write-up */}
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div>
            <div className="font-display text-2xl leading-tight text-parch" style={{ letterSpacing: "0.04em" }}>
              {v.name}
            </div>
            {subtitle && (
              <div className="caps-label mt-0.5 text-[10px] tracking-[0.2em] text-mist">{subtitle}</div>
            )}
            {v.description && (
              <p className="mt-1.5 text-sm font-light leading-relaxed text-mist">{v.description}</p>
            )}
          </div>

          <Section label="Stats">
            <div className="flex items-baseline gap-6 font-display">
              <div className="flex items-baseline gap-1.5">
                <span className="caps-label text-[9px] tracking-[0.18em] text-dimmed">Power</span>
                <span className={`text-xl ${powerColor(v.power)}`}>{v.power.current}</span>
                {v.power.modifier !== 0 && (
                  <span className={`text-xs ${modifierColor(v.power.modifier)}`}>
                    {modifierText(v.power.modifier)}
                  </span>
                )}
                <span className="text-xs text-dimmed">base {v.power.base}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="caps-label text-[9px] tracking-[0.18em] text-dimmed">HP</span>
                <span className={`text-xl ${hpColor(v.hp)}`}>{v.hp.current}</span>
                {v.hp.modifier !== 0 && (
                  <span className={`text-xs ${modifierColor(v.hp.modifier)}`}>
                    {modifierText(v.hp.modifier)}
                  </span>
                )}
                <span className="text-xs text-dimmed">of {v.hp.base}</span>
              </div>
            </div>
          </Section>

          {v.keywords.length > 0 && (
            <Section label="Keywords">
              <KeywordRows keywords={v.keywords} />
            </Section>
          )}

          <Section label="Status effects">
            <StatusRows lines={lines} />
          </Section>

          <ChannelsSection subject={subject} />
        </div>
      </div>
    </div>
  );
}
