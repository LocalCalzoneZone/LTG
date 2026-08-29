import { useEffect, useState } from "react";
import { useGame } from "./lib/store";
import { Splitter, usePaneSize } from "./components/Splitter";
import { Battlefield } from "./components/Battlefield";
import { SidePanel } from "./components/SidePanel";
import { BottomBar } from "./components/BottomBar";
import { TopRibbon } from "./components/TopRibbon";
import { AdventureFlow } from "./components/AdventureFlow";
import { ScreenFx } from "./components/FxLayer";
import { InspectModal } from "./components/InspectModal";
import { NewGameModal } from "./components/NewGameModal";
import { LoadGameModal } from "./components/LoadGameModal";
import { CharacterSheetModal, ConfirmOverlay, DefeatSplash, TownScreen } from "./components/TownScreen";
import { ActSpoils } from "./components/Items";
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

export default function App() {
  const connect = useGame((s) => s.connect);
  const cancelArm = useGame((s) => s.cancelArm);
  const openZone = useGame((s) => s.openZone);
  const setInspect = useGame((s) => s.setInspect);
  const snapshot = useGame((s) => s.snapshot);
  const town = useGame((s) => s.town);
  const connected = useGame((s) => s.connected);

  const [sessionId, setSessionId] = useState<string | null>(sessionFromUrl());
  // Start on an empty battlefield — the player opens New Game / Options themselves.
  const [showNewGame, setShowNewGame] = useState<boolean>(false);
  const [showOptions, setShowOptions] = useState<boolean>(false);
  const [showLoadGame, setShowLoadGame] = useState<boolean>(false);

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
        setInspect(null);
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
  }, [cancelArm, openZone, setInspect]);

  const onStarted = (sid: string) => {
    const url = new URL(location.href);
    url.searchParams.set("s", sid);
    history.pushState({}, "", url);
    setSessionId(sid);
    setShowNewGame(false);
    setShowLoadGame(false);
  };

  return (
    <div className="flex h-full flex-col bg-ink-1">
      <TopRibbon
        onNewGame={() => setShowNewGame(true)}
        onOptions={() => setShowOptions(true)}
        onLoadGame={() => setShowLoadGame(true)}
      />

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {town ? (
            <>
              <TownScreen />
              <CharacterSheetModal rows={town.party_sheet} editable inTown />
            </>
          ) : snapshot ? (
            <>
              <Battlefield />
              {snapshot.party_sheet && (
                <CharacterSheetModal rows={snapshot.party_sheet} editable={!!snapshot.gear_editable} inTown={false} />
              )}
              <ConfirmOverlay confirm={snapshot.confirm} />
            </>
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
          {/* The between- and post-combat screens cover ONLY this bottom strip
              (absolute over the bar): the battlefield and log above stay readable
              and clickable, so the board you just won on can be inspected while
              you take the level-up, the spoils, or the game-over. The adventure
              flow's full-screen narrative splash is the one exception — it opens
              the NEXT phase, and renders `fixed` from in here. */}
          <div className="relative flex-none">
            <BottomBar height={consoleH || null} />
            {snapshot.defeat_pending && (
              <DefeatSplash adventureName={snapshot.adventure_name ?? snapshot.adventure?.name ?? ""}
                            hardcore={!!snapshot.scenario?.options.hardcore} />
            )}
            {/* Adventure phase flow (Update 10): victory splash → level-up → narration */}
            <AdventureFlow />
            {snapshot.rewards && <ActSpoils rewards={snapshot.rewards} scenario={snapshot.scenario} />}
            <GameOverOverlay
              onNewGame={() => setShowNewGame(true)}
              onOptions={() => setShowOptions(true)}
              onStarted={onStarted}
            />
          </div>
        </>
      )}

      {/* Overlays */}
      {showNewGame && (
        <NewGameModal onClose={() => setShowNewGame(false)} onStarted={onStarted} />
      )}
      {showOptions && <OptionsModal onClose={() => setShowOptions(false)} />}
      {showLoadGame && (
        <LoadGameModal onClose={() => setShowLoadGame(false)} onStarted={onStarted} />
      )}
      {/* Portrait inspection — under the gameplay prompts, which must stay on top */}
      <InspectModal />
      <ChooseModeModal />
      <ZoneModal />
      <CardPickPrompt />
      {/* Full-screen combat FX (ultimates, boss enrage) — under the modals */}
      <ScreenFx />
      <PhaseBanner />
      <Toast />
    </div>
  );
}
