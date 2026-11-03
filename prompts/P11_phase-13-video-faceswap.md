# P11 Phase 13: Video face-swap pipeline

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 12 · **Branch:** `phase-13-video-faceswap` · **Worktree:** `../project1111-phase-13` · **Gate:** auto

## Read first
`CLAUDE.md` (Content boundary), `prompts/P11_shared-instructions.md`, spec §4 (Video Face-swap), §11.2 R13, R14, R24, §11.3 S5, S6, S8. Phase Log entries for 05, 07 and 12. ADR-0005, ADR-0011. **Spec §11.6** (decided 2026-11-02 14:57 CST): H9 pause 87 °C / resume 80 °C, each adjustable by up to ±5 °C from Phase 03's measured throttle point with an ADR; H7 test material; H8 power profile during measurements.

**Phase 05 results (2026-11-02 19:28 CST):** use `p11.gpu.telemetry.ThermalGuard(settings.thermal_pause_c, settings.thermal_resume_c)` (defaults 87 / 80 °C, H9; `Settings` enforces resume < pause) fed from `stream(default_sampler())`; `GpuSample.thermal_throttled` reports the thermal clock-event bits. Per-frame runs should go through `run_with_oom_retry`; interrupt latency is ~0.5 s.

**Phase 07 results (2026-11-02 23:50 CST):** videos upload with `POST /api/uploads?kind=video` (ffprobe-checked, container/codec allowlist in `p11/media/validate.py`, metadata-free remux into `~/.local/share/p11/inputs/vid-<hex>.mp4|.mkv`; `seconds`, `width`, `height` and R13 `warnings` come back; `settings.video_warn_seconds` / `video_warn_height` are the 60 s / 1080p limits). The job model already has `paused` and the thermal hook: call `await control.checkpoint(long=True)` (a `p11.jobs.runner.JobControl`) between frame batches; it raises `EngineInterrupted` on cancel and waits in `paused` (with a note) while `ThermalWatch` says the GPU is hot. Jobs left running at a Studio restart become `failed` with `job.interrupted`; the resumable video job must keep its own frame progress to resume from.

**Phase 08 results (2026-11-03 04:18 CST):** the UI shell is in `frontend/src/` (ADR-0023, `docs/P11_ARCHITECTURE.md` → Studio UI). Views live in `features/<name>/` and are listed in `app/nav.tsx` `VIEWS` (remove the view's `phase` there and render it in `app/Shell.tsx` instead of the placeholder). Read state with `useStudio()` (jobs, progress, images, `galleryRev`), call the API through `client` in `api/client.ts` (add typed calls there), show errors with `useToasts().problem(problemOf(e))`, register keys with `useShortcuts`, and use `components/Dialog` and `components/ZoomPan`. Follow-up buttons on a result/detail image come from `features/actions.tsx`: replace your `LATER` entry with a real action (the gallery passes images by ID; a step on an earlier output uses `source_image: {ref: "gallery/<id>"}` or a slot bound to it, as `upscaleRecipe` in `features/generate/form.ts` does). Tests: `src/test/fakes.ts` (routed fake `fetch`, `FakeSource`) for Vitest; Playwright helpers in `e2e/studio.ts` (`openStudio` with the network guard, `Actions` counter); use `getByLabel("Prompt", { exact: true })` and scope Generate with `generateButton(page)`. Video is the nav placeholder; job progress (`progress` events with `run/runs`, `note` for thermal pauses) already shows in the Generate view's progress panel, reuse its `stageLabel`/ETA pattern.

## Goal
Short joke clips need no scripting. You upload a clip and a face photo, press **Swap**, and get back an MP4 with the original audio. Along the way the job shows clear progress and an ETA, pauses when the laptop runs hot, can be cancelled, and resumes after a crash. It runs on the same face-swap engine and the same NSFW guard as Phase 12.

## Tasks
1. **Media layer** (`media/ffmpeg.py`): ffprobe parsing (duration, fps incl. VFR detection, resolution, rotation, audio streams), frame extraction to PNG (or lossless WebP if faster) in `~/.cache/p11/jobs/<job>/frames/` (`0700`), re-encode with H.264 (yuv420p, CRF default for "good"), original fps and audio copied or re-encoded if incompatible, rotation honoured. Use the system ffmpeg (verified version recorded) via argument lists, never a shell string (S8).
2. **Limits (R13):** default ≤ 60 s and ≤ 1080p; longer or larger clips show a warning with an estimate (from measured per-frame time) and need confirmation; optional trim (start/end) and downscale.
3. **Pipeline job** (`jobs/video.py`): probe → extract → **guard** (the Phase 12 NSFW classifier on sampled frames: every Nth frame plus scene changes; any NSFW frame refuses the job before swapping, S5) → face-swap frames in batches through the engine (or FaceFusion CLI, per ADR-0011) with the chosen source face and target selection (auto-largest or a clicked face on the first frame with simple tracking by box overlap) → optional face restore → stitch. Progress is persisted per frame so a crash or stop resumes from the last finished frame. Cancel deletes scratch unless "keep frames" is set.
4. **Thermal guard (R14):** the Phase 05 `ThermalGuard` pauses between batches above the threshold and resumes below it; the UI shows "Cooling down (86 °C)". **Phase 03 results (2026-11-02 18:08 CST):** in a 10-minute generation loop the GPU plateaued at 78–79 °C and was power-capped (~68 W), never thermally throttled (`docs/P11_BENCHMARKS.md`, Thermals); measure the video job's own curve before tuning H9. Also respect the GPU lock (one GPU job at a time).
5. **Temporal quality:** reduce flicker with simple measures that are measurable: consistent face selection, optional temporal smoothing of the swapped face region (e.g. blending with the previous frame's result where motion is low). Keep it optional and record the effect.
6. **Video view:** upload clip (validated), choose face photo (or "my face" from Phase 12), choose target face on a thumbnail, quality preset (Fast / Good), trim, Swap; progress (frames done/total, ETA, temperature, paused state), Cancel, Resume for interrupted jobs, result player and Download. Output goes to the R7 layout as `.mp4` with a sidecar.
7. **Laptop measurement:** a 30 s 1080p 30 fps synthetic clip, plus Nick's clip from `~/Pictures/P11-test/` if present (H7, outside the repo; power per H8) at Fast and Good: total time, per-frame time, peak temperature, pauses; `docs/P11_BENCHMARKS.md`.

## Out of scope
Lip-sync, full-body replacement, live webcam, audio changes.

## Tests
ffprobe parser fixtures (VFR, rotated, no-audio, odd sizes), command-line builder tests (no shell, paths quoted as args), resume logic (kill mid-batch → resumes at the right frame, no duplicates), guard refusal on a stubbed NSFW frame, thermal pause/resume with a fake telemetry source, FakeEngine e2e of the whole pipeline on a short synthetic clip (generated with ffmpeg test sources), `gpu` test on a 3 s synthetic face clip.

## Acceptance criteria
- On the laptop: a 30 s 1080p clip produces a watchable MP4 with the original audio; killing `p11` mid-job and restarting resumes and completes; cancel cleans scratch.
- Thermal pauses occur and recover when the threshold is lowered for a test run.
- The NSFW guard runs for every video job; there is no switch to disable it.
- `make check` and `make gpu-test` green.

## Phase-specific docs
`docs/P11_USER-GUIDE.md` (Video face-swap, limits, consent notice), `docs/P11_ARCHITECTURE.md` (pipeline, resume model), `docs/P11_BENCHMARKS.md`, owner question 5 status, CHANGELOG. Then the standard close-out checklist.
