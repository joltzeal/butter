import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { Toast } from "../lib/types";

interface ToastValue {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id">) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastValue | null>(null);

let seq = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      seq += 1;
      const id = seq;
      setToasts((prev) => [...prev.slice(-3), { ...toast, id }]);
      if (!toast.sticky) {
        window.setTimeout(() => dismiss(id), toast.kind === "error" ? 7000 : 4200);
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toasts, push, dismiss }), [toasts, push, dismiss]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToasts(): ToastValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToasts must be used inside ToastProvider");
  return ctx;
}
