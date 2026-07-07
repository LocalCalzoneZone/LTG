import type { StatBlock } from "./types";

// Colour rules from brief §4.4, mapped onto the Brasswork & Ink palette:
// vigor = buffed, blood = weakened/downed, parchment = neutral.
export function powerColor(p: StatBlock): string {
  if (p.modifier > 0) return "text-vigor";
  if (p.modifier < 0) return "text-blood";
  return "text-parch";
}

export function hpColor(h: StatBlock): string {
  if (h.current === 0) return "text-blood"; // downed is red regardless
  if (h.modifier > 0) return "text-vigor";
  if (h.modifier < 0) return "text-blood";
  return "text-parch";
}

export function modifierColor(mod: number): string {
  if (mod > 0) return "text-vigor";
  if (mod < 0) return "text-blood";
  return "text-mist";
}

export function modifierText(mod: number): string {
  if (mod === 0) return "";
  return mod > 0 ? `+${mod}` : `${mod}`;
}

// Colour for an action's classification tag (the engine's vocabulary — see
// serialize.py action_mode): attacks brass (combat damage: Mitigate and
// combat-damage prevention answer them), abilities aether (NOT combat damage),
// spells spell-blue. One glance tells you which damage lane a stack item is in.
export function actionModeColor(mode: string | null): string {
  if (mode === "spell") return "text-spell";
  if (mode === "ability") return "text-aether";
  return "text-brass"; // "melee attack" / "ranged attack"
}

/** Creature level as a roman numeral (fantasy sigil, replaces "L2"). */
export function roman(n: number): string {
  const table: [number, string][] = [
    [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"],
  ];
  let out = "";
  let v = Math.max(0, Math.floor(n));
  for (const [k, s] of table) {
    while (v >= k) {
      out += s;
      v -= k;
    }
  }
  return out || "0";
}

export interface Pip {
  kind: "generic" | "color";
  value: string;
}

// Parse a pip string like "{2}{U}{U}" into ordered pips.
export function parsePips(cost: string): Pip[] {
  const out: Pip[] = [];
  const re = /\{([^}]+)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(cost)) !== null) {
    const v = m[1];
    if (/^\d+$/.test(v) || /^[Xx]$/.test(v)) out.push({ kind: "generic", value: v.toUpperCase() });
    else out.push({ kind: "color", value: v });
  }
  return out;
}
