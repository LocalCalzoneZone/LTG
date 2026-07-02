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
  const [showNewGame, setShowNewGame] = useState<boolean>(!sessionFromUrl());
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
        {snapshot ? (
          <>
            <div className="min-w-0 basis-2/3">
              <Battlefield />
            </div>
            <div className="min-w-0 basis-1/3 border-l border-white/10">
              <SidePanel onNewGame={() => setShowNewGame(true)} onOptions={() => setShowOptions(true)} />
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-gray-400">
            {sessionId ? (connected ? "Loading game…" : "Connecting…") : "Start a new game."}
          </div>
        )}
      </div>

      {snapshot && <BottomBar />}

      {/* Overlays */}
      {showNewGame && (
        <NewGameModal
          onClose={sessionId ? () => setShowNewGame(false) : null}
          onStarted={onStarted}
        />
      )}
      {showOptions && <OptionsModal onClose={() => setShowOptions(false)} />}
      <ChooseModeModal />
      <ZoneModal />
      <CardPickPrompt />
      <GameOverOverlay onNewGame={() => setShowNewGame(true)} />
      <Toast />
    </div>
  );
}
