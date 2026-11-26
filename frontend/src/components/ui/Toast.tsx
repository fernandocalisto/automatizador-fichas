import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/cn";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface ToastContextValue {
  pushToast: (input: Omit<ToastMessage, "id">) => void;
  dismissToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const pushToast = useCallback(
    (input: Omit<ToastMessage, "id">) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setToasts((prev) => [...prev.slice(-4), { ...input, id }]);
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((item) => item.id !== id));
      }, 4500);
    },
    [],
  );

  const value = useMemo(
    () => ({ pushToast, dismissToast }),
    [pushToast, dismissToast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={cn(
              "pointer-events-auto flex items-start gap-2.5 rounded-md border bg-surface-elevated p-3 shadow-lg text-xs",
              toast.tone === "success" && "border-success/40",
              toast.tone === "error" && "border-danger/40",
              toast.tone === "warning" && "border-warning/40",
              toast.tone === "info" && "border-border-strong",
            )}
          >
            {toast.tone === "success" && (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            )}
            {toast.tone === "error" && (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            )}
            {toast.tone === "warning" && (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            )}
            {toast.tone === "info" && (
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-blueprint" />
            )}
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-ink">{toast.title}</p>
              {toast.description && (
                <p className="mt-0.5 text-ink-muted break-words">
                  {toast.description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => dismissToast(toast.id)}
              aria-label="Dispensar notificação"
              className="rounded p-0.5 text-ink-muted hover:text-ink cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return {
      pushToast: () => {},
      dismissToast: () => {},
    };
  }
  return ctx;
}
