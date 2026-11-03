// Time estimates for the progress panel. Before a run reports progress the estimate comes from
// the laptop measurements in docs/P11_BENCHMARKS.md (warm, dynamic VRAM, RTX 2070 Mobile); once
// it does, the observed rate takes over.

/** Warm seconds per image by model and aspect preset (Phase 03 bake-off). */
export const BENCHMARK_SECONDS: Record<string, Record<string, number>> = {
  "realvisxl5-lightning": {
    "16:9-1920x1080": 18.3,
    "16:9-2560x1440": 17.7,
    "1:1-1024": 13.7,
    "logo-1:1": 13.7,
    "avatar-4:5": 12.3,
  },
  juggernautxl9: {
    "16:9-1920x1080": 40.8,
    "16:9-2560x1440": 40.8,
    "1:1-1024": 38.6,
    "logo-1:1": 38.6,
    "avatar-4:5": 34.2,
  },
};
/** Engine start + first model load on top of a warm run (cold minus warm, Phase 03). */
export const COLD_START_SECONDS = 15;
export const FALLBACK_SECONDS = 30;

export function baselineSeconds(
  model: string | null,
  aspect: string | null,
  count: number,
): number {
  const per = (model && aspect && BENCHMARK_SECONDS[model]?.[aspect]) || FALLBACK_SECONDS;
  return per * Math.max(1, count);
}

/**
 * Seconds left. `progress` is 0–1, `elapsed` seconds since the job started running.
 * Below 5 % the benchmark baseline is used; from there the observed rate is blended in.
 */
export function remainingSeconds(
  progress: number,
  elapsed: number,
  baseline: number,
  cold = false,
): number {
  const base = Math.max(0, baseline + (cold ? COLD_START_SECONDS : 0) - elapsed);
  if (progress < 0.05 || elapsed <= 0) return Math.max(1, base);
  const observed = (elapsed * (1 - progress)) / progress;
  const w = Math.min(1, progress * 2); // trust the observed rate fully from 50 %
  return Math.max(0, w * observed + (1 - w) * base);
}

export function formatSeconds(s: number): string {
  if (s < 1) return "almost done";
  if (s < 60) return `about ${Math.ceil(s)} s left`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s % 60);
  return `about ${m} min ${rest} s left`;
}
