import { useCallback, useState } from "react";

export function usePaneSize(key: string, fallback: number, clamp: (v: number) => number) {
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
export function Splitter({ vertical, onMove, onReset }: {
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
