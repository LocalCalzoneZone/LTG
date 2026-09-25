// Combat keyboard (roadmap M2.15). Presentation only: every key maps onto a
// choice the snapshot already offers, through the same store calls a click
// makes — nothing here decides what is legal.
//
//   Space / Enter  Pass in a reaction window, else End Turn (with its guard);
//                  Enter also casts once the mana picker's payment is complete
//   1–9            the hand's cards, left to right
//   A D M V S U    Attack · Defend · Mitigate · moVe · Skill · Ultimate
//   Esc            cancel (handled in App with the other cancel gestures)

import { castIndexFor, focusedChoices, useGame } from "./store";

const VERB_KEYS: Record<string, "attack" | "defend" | "mitigate" | "move" | "skill" | "ultimate"> = {
  a: "attack", d: "defend", m: "mitigate", v: "move", s: "skill", u: "ultimate",
};

/** True when the key belongs to a text field or a focused control, which
 *  handles its own Space/Enter. */
function ownedByTarget(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if ((e.key === "Enter" || e.key === " ")
      && (tag === "BUTTON" || tag === "A" || el.getAttribute("role") === "button")) return true;
  return false;
}

/** Handle one keydown for the battle console; returns true if it acted. */
export function handleCombatKey(e: KeyboardEvent): boolean {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return false;
  if (ownedByTarget(e)) return false;
  const st = useGame.getState();
  // Only on the battlefield, and only with nothing modal open over it (App's
  // own menus are checked by the caller).
  if (!st.snapshot || st.town || st.inspectId || st.zoneModal || st.chooseModeFor
      || st.sheetFor || st.gameOver || st.showQuestLog || st.snapshot.pending_choice) return false;
  // The resolution hold gates the keyboard exactly as it gates the mouse.
  if (st._snapQueue.length > 0 || Date.now() < st.holdUntil) return false;

  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (key === "Enter" && st.manaSelect) {
    if (castIndexFor(st.manaSelect) == null) return false;
    st.confirmMana();
    return true;
  }
  const choices = focusedChoices(st);
  if (!choices) return false;

  if (key === "Enter" || key === " ") {
    if (st.armed || st.manaSelect) return false;
    if (choices.pass) {
      st.selectChoice(choices.pass);
      return true;
    }
    // End Turn goes through the button, so its guard (M2.14) applies.
    const btn = document.querySelector<HTMLButtonElement>("[data-end-turn]");
    if (btn && !btn.disabled) {
      btn.click();
      return true;
    }
    return false;
  }
  if (/^[1-9]$/.test(key)) {
    const hand = st.snapshot.characters.find((c) => c.id === st.focusedId)?.hand ?? [];
    const card = hand[Number(key) - 1];
    const choice = card ? choices.casts[card.id] : undefined;
    if (!choice) return false;
    st.selectChoice(choice);
    return true;
  }
  const verb = VERB_KEYS[key];
  if (verb) {
    const choice = choices[verb];
    if (!choice) return false;
    st.selectChoice(choice);
    return true;
  }
  return false;
}
