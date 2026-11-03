import { useEffect, useState } from "react";
import { ApiError, api, bootstrapSession } from "./api/session";

type SessionInfo = { ok: boolean; version: string; fake: boolean };
type State =
  | { kind: "loading" }
  | { kind: "ok"; info: SessionInfo }
  | { kind: "no-session"; message?: string }
  | { kind: "error" };

export function App() {
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

  return (
    <main>
      <h1>P11 Studio</h1>
      {state.kind === "loading" && <p>Connecting…</p>}
      {state.kind === "ok" && (
        <p>
          Session active (version {state.info.version}
          {state.info.fake ? ", fake engine" : ""}).
        </p>
      )}
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
