import { useCallback, useEffect, useState } from "react";
import { useGame } from "./lib/store";
import { Battlefield } from "./components/Battlefield";
import { SidePanel } from "./components/SidePanel";
import { BottomBar } from "./components/BottomBar";
import { TopRibbon } from "./components/TopRibbon";
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

// ---- resizable panes -------------------------------------------------------
const SIDE_DEFAULT = 450;
const clampSide = (w: number) => Math.min(Math.max(w, 280), Math.round(window.innerWidth * 0.5));
const clampConsole = (h: number) => Math.min(Math.max(h, 160), Math.round(window.innerHeight * 0.55));

function usePaneSize(key: string, fallback: number, clamp: (v: number) => number) {
  const [size, setSize] = useState<number>(() => {
    const saved = Number(localStorage.getItem(key));
    return saved > 0 ? clamp(saved) : fallback;
  });
  const set = useCallback(
    (v: number) => {
      const c = clamp(v);
      setSize(c);
      localStorage.setItem(key, String(c));
    },
    [key, clamp],
  );
  const reset = useCallback(() => {
    setSize(fallback);
    localStorage.removeItem(key);
  }, [key, fallback]);
  return [size, set, reset] as const;
}

/** A grabbable hairline between panes. Drag to resize; double-click to reset. */
function Splitter({ vertical, onMove, onReset }: {
  vertical: boolean; // vertical bar => horizontal drag
  onMove: (clientPos: number) => void;
  onReset: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  return (
    <div
      onPointerDown={(e) => {
        e.preventDefault();
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
          /* synthetic / already-captured pointers — dragging still works */
        }
        setDragging(true);
      }}
      onPointerMove={(e) => {
        if (!dragging) return;
        onMove(vertical ? e.clientX : e.clientY);
      }}
      onPointerUp={(e) => {
        try {
          e.currentTarget.releasePointerCapture(e.pointerId);
        } catch {
          /* ignore */
        }
        setDragging(false);
      }}
      onDoubleClick={onReset}
      title="Drag to resize · double-click to reset"
      className={`group flex-none select-none ${
        vertical ? "w-[6px] cursor-col-resize" : "h-[6px] cursor-row-resize"
      } ${dragging ? "bg-brass/40" : "bg-transparent hover:bg-brass/25"} transition-colors`}
    >
      {/* the visible hairline, centred in the grab area */}
      <div
        className={`${vertical ? "mx-auto h-full w-px" : "my-auto h-px w-full"} ${
          dragging ? "bg-brass" : "bg-line group-hover:bg-line2"
        }`}
      />
    </div>
  );
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

  // Pane sizes (persisted). consoleH 0 = "use the responsive default clamp".
  const [sideW, setSideW, resetSideW] = usePaneSize("ltg_side_w", SIDE_DEFAULT, clampSide);
  const [consoleH, setConsoleH, resetConsoleH] = usePaneSize("ltg_console_h", 0, clampConsole);

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
    <div className="flex h-full flex-col bg-ink-1">
      <TopRibbon onNewGame={() => setShowNewGame(true)} onOptions={() => setShowOptions(true)} />

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          {snapshot ? (
            <Battlefield />
          ) : (
            <div className="field-scene flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
              {sessionId ? (
                <span className="caps-label text-[11px] text-mist">
                  {connected ? "Loading game…" : "Connecting…"}
                </span>
              ) : (
                <>
                  <div className="h-2 w-2 rotate-45 border border-brass/60" aria-hidden />
                  <div className="caps-label text-[14px] text-parch">No battle in progress</div>
                  <div className="max-w-sm text-sm font-light text-mist">
                    Start a <span className="text-brass">New Game</span>, or open{" "}
                    <span className="text-parch">Options</span> to load characters and author
                    encounters.
                  </div>
                </>
              )}
            </div>
          )}
        </div>
        <Splitter
          vertical
          onMove={(x) => setSideW(window.innerWidth - x)}
          onReset={resetSideW}
        />
        <div style={{ width: sideW }} className="flex-none">
          <SidePanel />
        </div>
      </div>

      {snapshot && (
        <>
          <Splitter
            vertical={false}
            onMove={(y) => setConsoleH(window.innerHeight - y)}
            onReset={resetConsoleH}
          />
          <BottomBar height={consoleH || null} />
        </>
      )}

      {/* Overlays */}
      {showNewGame && (
        <NewGameModal onClose={() => setShowNewGame(false)} onStarted={onStarted} />
      )}
      {showOptions && <OptionsModal onClose={() => setShowOptions(false)} />}
      <ChooseModeModal />
      <ZoneModal />
      <CardPickPrompt />
      <GameOverOverlay
        onNewGame={() => setShowNewGame(true)}
        onOptions={() => setShowOptions(true)}
      />
      <PhaseBanner />
      <Toast />
    </div>
  );
}
