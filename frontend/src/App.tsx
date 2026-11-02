import { useEffect, useState } from "react";

type Health = { status: string; version: string };
type State = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error" };

export function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch("/healthz")
      .then((r) =>
        r.ok ? (r.json() as Promise<Health>) : Promise.reject(new Error(String(r.status))),
      )
      .then((health) => !cancelled && setState({ kind: "ok", health }))
      .catch(() => !cancelled && setState({ kind: "error" }));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>P11 Studio</h1>
      {state.kind === "loading" && <p>Checking the service…</p>}
      {state.kind === "ok" && (
        <p>
          Service is {state.health.status} (version {state.health.version}).
        </p>
      )}
      {state.kind === "error" && (
        <p role="alert">Cannot reach the P11 service. Is `p11 serve` running?</p>
      )}
    </main>
  );
}
