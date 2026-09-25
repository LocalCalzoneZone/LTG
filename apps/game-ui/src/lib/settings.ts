// Local game settings (Options → Settings), stored in localStorage.
//
// `host address` backs the Copy Link invite URL: multiplayer over Tailscale
// needs the HOST machine's tailnet IP in the link — the server can't know
// which of its addresses the other players can reach, so the host pastes it
// here manually. Empty means the default (localhost / however you opened it).

const HOST_KEY = "ltg_host_address";

export function getHostAddress(): string {
  return localStorage.getItem(HOST_KEY) ?? "";
}

export function setHostAddress(v: string) {
  const t = v.trim();
  if (t) localStorage.setItem(HOST_KEY, t);
  else localStorage.removeItem(HOST_KEY);
}

/** The shareable URL for a session: the configured host address (e.g. a
 *  Tailscale IP) or the current location's host when unset. A pasted protocol
 *  or trailing slash is tolerated; an entry without a port inherits the port
 *  the game is being served on. */
export function inviteUrl(sessionId: string): string {
  let host = getHostAddress()
    .replace(/^[a-z]+:\/\//i, "")
    .replace(/\/+$/, "");
  if (!host) {
    host = location.host;
  } else if (!/:\d+$/.test(host) && location.port) {
    host = `${host}:${location.port}`;
  }
  return `${location.protocol}//${host}/?s=${encodeURIComponent(sessionId)}`;
}

// End Turn guard (roadmap M2.14): End Turn asks once more while a card is
// still castable or the Attack still unused. On unless the player turns it off.
const CONFIRM_END_KEY = "ltg_confirm_end_turn";

export function getConfirmEndTurn(): boolean {
  try {
    return localStorage.getItem(CONFIRM_END_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setConfirmEndTurn(on: boolean) {
  try {
    if (on) localStorage.removeItem(CONFIRM_END_KEY);
    else localStorage.setItem(CONFIRM_END_KEY, "off");
  } catch {
    /* storage blocked: the default (on) stands */
  }
}
