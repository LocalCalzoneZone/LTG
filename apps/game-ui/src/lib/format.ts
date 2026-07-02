import type { StatBlock } from "./types";

// Colour rules from brief §4.4.
export function powerColor(p: StatBlock): string {
  if (p.modifier > 0) return "text-green-400";
  if (p.modifier < 0) return "text-red-400";
  return "text-white";
}

export function hpColor(h: StatBlock): string {
  if (h.current === 0) return "text-red-500"; // downed is red regardless
  if (h.modifier > 0) return "text-green-400";
  if (h.modifier < 0) return "text-red-400";
  return "text-white";
}

export function modifierColor(mod: number): string {
  if (mod > 0) return "text-green-400";
  if (mod < 0) return "text-red-400";
  return "text-gray-300";
}

export function modifierText(mod: number): string {
  if (mod === 0) return "–";
  return mod > 0 ? `+${mod}` : `${mod}`;
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
    if (/^\d+$/.test(v)) out.push({ kind: "generic", value: v });
    else out.push({ kind: "color", value: v });
  }
  return out;
}
