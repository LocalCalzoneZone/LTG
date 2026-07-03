import { useEffect, useState } from "react";
import { useGame } from "./lib/store";
import { Battlefield } from "./components/Battlefield";
import { SidePanel } from "./components/SidePanel";
import { BottomBar } from "./components/BottomBar";
import { SeatBar } from "./components/SeatBar";
import { NewGameModal } from "./components/NewGameModal";
import { OptionsModal } from "./components/OptionsModal";
import {
  CardPickPrompt,
  ChooseModeModal,
  GameOverOverlay,
  PhaseBanner,
  Toast,
  ZoneModal,
} from "./components/Modals";

function sessionFromUrl(): string | null {
  return new URLSearchParams(location.search).get("s");
}

export default function App() {
  const connect = useGame((s) => s.connect);
  const cancelArm = useGame((s) => s.cancelArm);
  const openZone = useGame((s) => s.openZone);
  const snapshot = useGame((s) => s.snapshot);
  const connected = useGame((s) => s.connected);

  const [sessionId, setSessionId] = useState<string | null>(sessionFromUrl());
  // Start on an empty battlefield — the player opens New Game / Options themselves.
  const [showNewGame, setShowNewGame] = useState<boolean>(false);
  const [showOptions, setShowOptions] = useState<boolean>(false);

  // Connect when a session id is set (from URL or after New Game).
  useEffect(() => {
    if (sessionId) connect(sessionId);
  }, [sessionId, connect]);

  // Global cancel gestures (§4.6): Esc / right-click clear arming and close modals.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        cancelArm();
        openZone(null);
      }
    };
    const onCtx = (e: MouseEvent) => {
      e.preventDefault();
      cancelArm();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("contextmenu", onCtx);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("contextmenu", onCtx);
    };
  }, [cancelArm, openZone]);

  const onStarted = (sid: string) => {
    const url = new URL(location.href);
    url.searchParams.set("s", sid);
    history.pushState({}, "", url);
    setSessionId(sid);
    setShowNewGame(false);
  };

  return (
    <div className="flex h-full flex-col">
      {sessionId && <SeatBar />}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 basis-2/3">
          {snapshot ? (
            <Battlefield />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              {sessionId ? (
                <span className="text-gray-400">{connected ? "Loading game…" : "Connecting…"}</span>
              ) : (
                <>
                  <div className="text-lg font-semibold text-gray-300">No game in progress</div>
                  <div className="max-w-sm text-sm text-gray-500">
                    Start a <span className="font-semibold text-blue-400">New Game</span>, or open{" "}
                    <span className="font-semibold text-gray-300">Options</span> to load characters and
                    author encounters.
                  </div>
                </>
              )}
            </div>
          )}
        </div>
        <div className="min-w-0 basis-1/3 border-l border-white/10">
          <SidePanel onNewGame={() => setShowNewGame(true)} onOptions={() => setShowOptions(true)} />
        </div>
      </div>

      {snapshot && <BottomBar />}

      {/* Overlays */}
      {showNewGame && (
        <NewGameModal onClose={() => setShowNewGame(false)} onStarted={onStarted} />
      )}
      {showOptions && <OptionsModal onClose={() => setShowOptions(false)} />}
      <ChooseModeModal />
      <ZoneModal />
      <CardPickPrompt />
      <GameOverOverlay onNewGame={() => setShowNewGame(true)} />
      <PhaseBanner />
      <Toast />
    </div>
  );
}
