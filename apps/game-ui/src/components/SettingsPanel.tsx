import { useState } from "react";
import { getHostAddress, inviteUrl, setHostAddress } from "../lib/settings";

const field =
  "border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-brass/60 focus:outline-none";
const label = "caps-label text-[9px] tracking-[0.2em] text-mist";

// Options → Settings: local game settings (stored in this browser). One for
// now — the host address behind the Copy Link invite URL.
export function SettingsPanel() {
  const [host, setHost] = useState(getHostAddress());

  const save = (v: string) => {
    setHost(v);
    setHostAddress(v);
  };

  return (
    <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1">
      <section className="border border-line bg-black/25 p-3">
        <div className="caps-label mb-3 text-[10px] tracking-[0.25em] text-brass">
          Multiplayer
        </div>

        <label className="flex flex-col gap-1.5">
          <span className={label}>Host address</span>
          <input
            className={`${field} w-full max-w-[360px]`}
            value={host}
            onChange={(e) => save(e.target.value)}
            placeholder="localhost"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <div className="mt-1.5 max-w-[560px] text-[11px] font-light text-dimmed">
          The address other players reach this machine at — Copy Link builds the
          invite URL from it. For sessions over Tailscale, paste this machine&apos;s
          tailnet IP (not the local-network one). Leave empty to default to
          localhost. A port is optional; without one the game&apos;s own port is used.
        </div>
        <div className="mt-2 text-[11px] font-light text-mist">
          Invite links will read:{" "}
          <span className="text-parch">{inviteUrl("SESSION")}</span>
        </div>
      </section>
    </div>
  );
}
