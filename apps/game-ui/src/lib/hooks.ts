import { useEffect, useState } from "react";

/** How long end-of-fight splashes (victory / defeat / act clear) hold back so
 * the killing blow — and the death animation it triggers — reads on the board
 * before the screen changes. Slightly longer than DEATH_MS in Battlefield. */
export const SPLASH_HOLD_MS = 1600;

/** True only once `active` has been continuously true for `ms`; resets the
 * moment it drops. Used to delay an overlay without changing what shows it. */
export function useAfterHold(active: boolean, ms: number): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!active) {
      setReady(false);
      return;
    }
    const t = window.setTimeout(() => setReady(true), ms);
    return () => window.clearTimeout(t);
  }, [active, ms]);
  return ready;
}
