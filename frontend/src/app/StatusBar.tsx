// Status bar (R14): engine state, job queue, VRAM used/total, GPU temperature band, model.

import { FINISHED } from "../api/types";
import { useStudio } from "./studio";

/** Colour band for a GPU temperature; the pause threshold is 87 °C (H9). */
export function tempBand(c: number): "cool" | "warm" | "hot" | "pause" {
  if (c >= 87) return "pause";
  if (c >= 80) return "hot";
  if (c >= 70) return "warm";
  return "cool";
}

const ENGINE_LABEL: Record<string, string> = {
  stopped: "Engine idle (starts with the next job)",
  starting: "Engine starting…",
  ready: "Engine ready",
  stopping: "Engine stopping…",
  failed: "Engine failed",
};

/** The build this window loaded; the server's `web` id is the build on disk (ADR-0043). */
export const BUILD = __P11_BUILD__;

export function StatusBar() {
  const { state } = useStudio();
  const { system, gpu } = state;
  const jobs = Object.values(state.jobs).filter((j) => !FINISHED.has(j.state));
  const running = jobs.filter((j) => j.state === "running" || j.state === "paused").length;
  const waiting = jobs.length - running;
  const engine = system?.engine.state;
  return (
    <footer className="statusbar" aria-label="Status">
      <span className={`status-item engine-${engine ?? "unknown"}`}>
        {system?.fake ? "Fake engine · " : ""}
        {engine ? (ENGINE_LABEL[engine] ?? `Engine ${engine}`) : "Engine …"}
      </span>
      <span className="status-item">
        Queue: {running ? `${running} running` : "idle"}
        {waiting ? `, ${waiting} waiting` : ""}
      </span>
      {gpu ? (
        <>
          <span className="status-item" title="GPU memory in use (the desktop holds ~1 GB)">
            VRAM {(gpu.vram_used_mib / 1024).toFixed(1)} / {(gpu.vram_total_mib / 1024).toFixed(1)}{" "}
            GB
          </span>
          <span className={`status-item temp temp-${tempBand(gpu.temp_c)}`} title="GPU temperature">
            {Math.round(gpu.temp_c)} °C
            {tempBand(gpu.temp_c) === "pause" ? " · long jobs pause" : ""}
          </span>
        </>
      ) : (
        <span className="status-item muted">GPU: no readings</span>
      )}
      <span className="status-item">Model: {state.currentModel ?? "style default"}</span>
      <span className="status-item muted" title="Studio build; `p11 status` shows the same id">
        Build {BUILD}
      </span>
      {system?.web && BUILD !== "dev" && system.web !== BUILD && (
        <button type="button" className="btn-link" onClick={() => location.reload()}>
          New build ready: reload
        </button>
      )}
    </footer>
  );
}
