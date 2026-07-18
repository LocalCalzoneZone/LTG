import { useState } from "react";
import { quitApp } from "../lib/api";

/** The top-ribbon Quit button: confirm modal → /api/quit (scope "all" — the
 * server also stops the deckbuilder) → a full-screen shut-down notice. Ends
 * the session for every connected player: it is the host's control. */
export function QuitControl() {
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState(false);

  const quit = async () => {
    try {
      await quitApp();
    } catch {
      /* server is dying — expected */
    }
    setConfirming(false);
    setDone(true);
    window.close(); // usually blocked for user-opened tabs; the screen covers it
  };

  if (done) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-2 bg-ink-0">
        <div className="caps-label text-[13px] tracking-[0.25em] text-brass">LTG</div>
        <div className="text-[13px] font-light text-mist">
          The game and deckbuilder have shut down. You can close this tab.
        </div>
      </div>
    );
  }

  return (
    <>
      <button
        onClick={() => setConfirming(true)}
        title="Quit — stops the game AND the deckbuilder"
        className="caps-label ml-1 flex items-center gap-1.5 border border-line px-3 py-[5px] text-[10px] tracking-[0.16em] text-mist transition hover:border-blood/60 hover:text-blood"
      >
        Quit
      </button>
      {confirming && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-[2px]"
          onClick={() => setConfirming(false)}
        >
          <div
            className="panel-ticks w-[min(90vw,420px)] border border-line2 bg-ink-2 p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="caps-label mb-2 text-[11px] tracking-[0.25em] text-brass">
              Quit LTG
            </div>
            <div className="text-[12px] font-light text-mist">
              This quits the Game AND the Deckbuilder — both servers stop, and
              every connected player is disconnected. Anything not saved is
              lost.
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirming(false)}
                className="caps-label border border-line px-3 py-1.5 text-[9px] tracking-[0.14em] text-mist transition hover:border-line2 hover:text-parch"
              >
                Cancel
              </button>
              <button
                onClick={() => void quit()}
                className="caps-label border border-blood/60 bg-blood/15 px-3 py-1.5 text-[9px] tracking-[0.14em] text-blood transition hover:bg-blood hover:text-parch"
              >
                Quit
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
