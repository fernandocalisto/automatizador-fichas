import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { cn } from "@/lib/cn";

export interface SplitPaneProps {
  left: ReactNode;
  right: ReactNode;
  initialRatio?: number;
  minRatio?: number;
  maxRatio?: number;
  className?: string;
  leftClassName?: string;
  rightClassName?: string;
  storageKey?: string;
}

export function SplitPane({
  left,
  right,
  initialRatio = 0.5,
  minRatio = 0.22,
  maxRatio = 0.78,
  className,
  leftClassName,
  rightClassName,
  storageKey,
}: SplitPaneProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [ratio, setRatio] = useState<number>(() => {
    if (storageKey && typeof window !== "undefined") {
      const saved = Number(window.localStorage.getItem(storageKey));
      if (!Number.isNaN(saved) && saved >= minRatio && saved <= maxRatio) {
        return saved;
      }
    }
    return initialRatio;
  });
  const [dragging, setDragging] = useState(false);

  const clamp = useCallback(
    (val: number) => Math.min(maxRatio, Math.max(minRatio, val)),
    [maxRatio, minRatio],
  );

  useEffect(() => {
    if (storageKey && typeof window !== "undefined") {
      window.localStorage.setItem(storageKey, String(ratio));
    }
  }, [ratio, storageKey]);

  useEffect(() => {
    if (!dragging) return;
    const handleMove = (e: PointerEvent) => {
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0) return;
      const next = (e.clientX - rect.left) / rect.width;
      setRatio(clamp(next));
    };
    const handleUp = () => setDragging(false);

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [dragging, clamp]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "flex h-full w-full min-h-0 overflow-hidden",
        dragging && "select-none cursor-col-resize",
        className,
      )}
    >
      <div
        style={{ width: `${(ratio * 100).toFixed(2)}%` }}
        className={cn("h-full min-w-0 min-h-0 overflow-hidden", leftClassName)}
      >
        {left}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Redimensionar painéis"
        tabIndex={0}
        onPointerDown={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDoubleClick={() => setRatio(initialRatio)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setRatio((r) => clamp(r - 0.03));
          if (e.key === "ArrowRight") setRatio((r) => clamp(r + 0.03));
          if (e.key === "Home") setRatio(initialRatio);
        }}
        className={cn(
          "group relative w-1.5 shrink-0 cursor-col-resize bg-border/80 transition-colors hover:bg-accent/70 focus:outline-none focus:bg-accent",
          dragging && "bg-accent",
        )}
      >
        <span
          aria-hidden="true"
          className="absolute inset-y-0 -left-1 -right-1"
        />
      </div>

      <div
        className={cn(
          "h-full flex-1 min-w-0 min-h-0 overflow-hidden",
          rightClassName,
        )}
      >
        {right}
      </div>
    </div>
  );
}
