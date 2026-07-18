import { useEffect, useState } from "react";
import { applyUpdate, checkUpdate, UpdateStatus } from "../lib/api";
import { getHostAddress, inviteUrl, setHostAddress } from "../lib/settings";

const field =
  "border border-line bg-ink-0 px-2 py-1.5 text-sm font-light focus:border-brass/60 focus:outline-none";
const label = "caps-label text-[9px] tracking-[0.2em] text-mist";
const GHOST_BTN =
  "caps-label flex items-center gap-1.5 border border-line2 px-3 py-1.5 text-[9px] tracking-[0.16em] " +
  "text-brass transition hover:border-brass hover:text-brass-hi";
const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch";
// Options → Settings: local game settings and self-update (Quit lives in the
// top ribbon, beside New Game).
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

      <UpdateSection />
    </div>
  );
}

// Self-update over git (appctl.py): one update covers the whole install —
// game, deckbuilder, and shared encounters/adventures alike. Saved characters
// live outside git and are never touched.
function UpdateSection() {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [phase, setPhase] = useState<"idle" | "checking" | "updating" | "updated">("idle");

  const check = async (manual: boolean) => {
    if (manual) setPhase("checking");
    try {
      setStatus(await checkUpdate());
    } catch {
      if (manual) setStatus({ supported: true, error: "Couldn't check for updates." });
    }
    if (manual) setPhase("idle");
  };

  useEffect(() => {
    void check(false); // quiet check when the panel opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = async () => {
    setPhase("updating");
    try {
      const res = await applyUpdate();
      setStatus(res);
      setPhase(res.updated ? "updated" : "idle");
    } catch {
      setStatus({ supported: true, error: "The update failed unexpectedly — try again." });
      setPhase("idle");
    }
  };

  if (status && !status.supported) return null; // not a git checkout — nothing to offer

  const behind = status?.behind ?? 0;
  return (
    <section className="border border-line bg-black/25 p-3">
      <div className="caps-label mb-3 text-[10px] tracking-[0.25em] text-brass">
        Updates
      </div>

      {phase === "updated" ? (
        <div className="max-w-[560px] text-[12px] font-light text-parch">
          Updated. Quit (top right, beside New Game) and relaunch LTG-Start
          to finish.
        </div>
      ) : (
        <>
          <div className="max-w-[560px] text-[11px] font-light text-dimmed">
            Updates the whole install — game, deckbuilder, and any new
            encounters or adventures. Your saved characters are never touched.
          </div>
          <div className="mt-2 text-[12px] font-light text-mist">
            {status?.error
              ? status.error
              : behind > 0
                ? `${behind} update${behind === 1 ? "" : "s"} available.`
                : status
                  ? "You're up to date."
                  : "…"}
          </div>
          {behind > 0 && !status?.error && (
            <ul className="mt-1 max-h-[30vh] max-w-[560px] list-disc overflow-y-auto pl-5 text-[11px] font-light text-dimmed">
              {(status?.log ?? []).map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex gap-2">
            {behind > 0 && !status?.error ? (
              <button className={GHOST_BTN} onClick={update} disabled={phase !== "idle"}>
                {phase === "updating" ? "Updating…" : "Update now"}
              </button>
            ) : (
              <button className={SMALL_BTN} onClick={() => void check(true)} disabled={phase !== "idle"}>
                {phase === "checking" ? "Checking…" : "Check for updates"}
              </button>
            )}
          </div>
          {phase === "updating" && (
            <div className="mt-2 text-[11px] font-light text-dimmed">
              This can take a minute — don&apos;t close the window.
            </div>
          )}
        </>
      )}
    </section>
  );
}
