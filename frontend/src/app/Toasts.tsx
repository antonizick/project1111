// Plain-English toasts with a hint (shared instructions §3). Errors are announced assertively
// and stay until closed or 15 s; information goes away after 6 s.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Problem } from "../api/types";

export type Toast = {
  id: number;
  kind: "error" | "info";
  message: string;
  hint?: string;
  action?: { label: string; run: () => void };
};

type Push = (t: Omit<Toast, "id">) => void;
type Ctx = { push: Push; problem: (p: Problem, action?: Toast["action"]) => void };

const ToastContext = createContext<Ctx | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);

  const close = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);

  const push = useCallback<Push>(
    (t) => {
      const id = next.current++;
      setToasts((ts) => {
        // The same message twice in a row (e.g. a reconnect loop) is shown once.
        const kept = ts.filter((x) => x.message !== t.message);
        return [...kept.slice(-3), { ...t, id }];
      });
      setTimeout(() => close(id), t.kind === "error" ? 15000 : 6000);
    },
    [close],
  );

  const problem = useCallback(
    (p: Problem, action?: Toast["action"]) =>
      push({ kind: "error", message: p.message, hint: p.hint || undefined, action }),
    [push],
  );

  const value = useMemo(() => ({ push, problem }), [push, problem]);
  const errors = toasts.filter((t) => t.kind === "error");
  const infos = toasts.filter((t) => t.kind === "info");
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts">
        <div role="alert" aria-live="assertive" className="toast-stack">
          {errors.map((t) => (
            <ToastView key={t.id} toast={t} onClose={close} />
          ))}
        </div>
        <div role="status" aria-live="polite" className="toast-stack">
          {infos.map((t) => (
            <ToastView key={t.id} toast={t} onClose={close} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

function ToastView({ toast, onClose }: { toast: Toast; onClose: (id: number) => void }) {
  return (
    <div className={`toast toast-${toast.kind}`}>
      <div className="toast-body">
        <p className="toast-message">{toast.message}</p>
        {toast.hint && <p className="toast-hint">{toast.hint}</p>}
      </div>
      {toast.action && (
        <button
          type="button"
          className="btn btn-small"
          onClick={() => {
            toast.action?.run();
            onClose(toast.id);
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button
        type="button"
        className="btn btn-ghost btn-small"
        aria-label="Dismiss"
        onClick={() => onClose(toast.id)}
      >
        ×
      </button>
    </div>
  );
}

export function useToasts(): Ctx {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToasts outside ToastProvider");
  return ctx;
}
