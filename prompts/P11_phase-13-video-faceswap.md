# P11 Phase 13: Video face-swap pipeline

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 12 · **Branch:** `phase-13-video-faceswap` · **Worktree:** `../project1111-phase-13` · **Gate:** auto

## Read first
`CLAUDE.md` (Content boundary), `prompts/P11_shared-instructions.md`, spec §4 (Video Face-swap), §11.2 R13, R14, R24, §11.3 S5, S6, S8. Phase Log entries for 05, 07 and 12. ADR-0005, ADR-0011. **Owner question 5** (thermal thresholds; proposed default pause 87 °C / resume 80 °C, adjusted to Phase 03's measured throttle point). If it is still open, ask before fixing the defaults.

## Goal
Short joke clips need no scripting. You upload a clip and a face photo, press **Swap**, and get back an MP4 with the original audio. Along the way the job shows clear progress and an ETA, pauses when the laptop runs hot, can be cancelled, and resumes after a crash. It runs on the same face-swap engine and the same NSFW guard as Phase 12.

## Tasks
1. **Media layer** (`media/ffmpeg.py`): ffprobe parsing (duration, fps incl. VFR detection, resolution, rotation, audio streams), frame extraction to PNG (or lossless WebP if faster) in `~/.cache/p11/jobs/<job>/frames/` (`0700`), re-encode with H.264 (yuv420p, CRF default for "good"), original fps and audio copied or re-encoded if incompatible, rotation honoured. Use the system ffmpeg (verified version recorded) via argument lists, never a shell string (S8).
2. **Limits (R13):** default ≤ 60 s and ≤ 1080p; longer or larger clips show a warning with an estimate (from measured per-frame time) and need confirmation; optional trim (start/end) and downscale.
3. **Pipeline job** (`jobs/video.py`): probe → extract → **guard** (the Phase 12 NSFW classifier on sampled frames: every Nth frame plus scene changes; any NSFW frame refuses the job before swapping, S5) → face-swap frames in batches through the engine (or FaceFusion CLI, per ADR-0011) with the chosen source face and target selection (auto-largest or a clicked face on the first frame with simple tracking by box overlap) → optional face restore → stitch. Progress is persisted per frame so a crash or stop resumes from the last finished frame. Cancel deletes scratch unless "keep frames" is set.
4. **Thermal guard (R14):** the Phase 05 `ThermalGuard` pauses between batches above the threshold and resumes below it; the UI shows "Cooling down (86 °C)". Also respect the GPU lock (one GPU job at a time).
5. **Temporal quality:** reduce flicker with simple measures that are measurable: consistent face selection, optional temporal smoothing of the swapped face region (e.g. blending with the previous frame's result where motion is low). Keep it optional and record the effect.
6. **Video view:** upload clip (validated), choose face photo (or "my face" from Phase 12), choose target face on a thumbnail, quality preset (Fast / Good), trim, Swap; progress (frames done/total, ETA, temperature, paused state), Cancel, Resume for interrupted jobs, result player and Download. Output goes to the R7 layout as `.mp4` with a sidecar.
7. **Laptop measurement:** a 30 s 1080p 30 fps clip (owner-supplied, outside the repo, owner question 4) at Fast and Good: total time, per-frame time, peak temperature, pauses; `docs/P11_BENCHMARKS.md`.

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
