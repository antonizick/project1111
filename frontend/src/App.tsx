import { useEffect, useState } from "react";
import { ApiError, api, bootstrapSession } from "./api/session";
import type { EventSourceLike } from "./api/events";
import { NavProvider } from "./app/nav";
import { Shell } from "./app/Shell";
import { ShortcutProvider } from "./app/shortcuts";
import { StudioProvider } from "./app/studio";
import { ToastProvider } from "./app/Toasts";
import "./app/theme.css";

type SessionInfo = { ok: boolean; version: string; fake: boolean };
type State =
  | { kind: "loading" }
  | { kind: "ok"; info: SessionInfo }
  | { kind: "no-session"; message?: string }
  | { kind: "error" };

export function App({ createSource }: { createSource?: (url: string) => EventSourceLike }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const set = (s: State) => !cancelled && setState(s);
    bootstrapSession()
      .then((token) =>
        token
          ? api<SessionInfo>("/api/session").then((info) => set({ kind: "ok", info }))
          : set({ kind: "no-session" }),
      )
      .catch((e: unknown) =>
        e instanceof ApiError && e.status === 401
          ? set({ kind: "no-session", message: e.problem.message })
          : set({ kind: "error" }),
      );
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "ok")
    return (
      <ToastProvider>
        <ShortcutProvider>
          <NavProvider>
            <StudioProvider createSource={createSource}>
              <Shell version={state.info.version} fake={state.info.fake} />
            </StudioProvider>
          </NavProvider>
        </ShortcutProvider>
      </ToastProvider>
    );

  return (
    <main className="splash">
      <h1>P11 Studio</h1>
      {state.kind === "loading" && <p>Connecting…</p>}
      {state.kind === "no-session" && (
        <p role="alert">
          {state.message ?? "No session."} Open P11 Studio with <code>p11 open</code>.
        </p>
      )}
      {state.kind === "error" && (
        <p role="alert">Cannot reach the P11 service. Is it running? Try `p11 status`.</p>
      )}
    </main>
  );
}
