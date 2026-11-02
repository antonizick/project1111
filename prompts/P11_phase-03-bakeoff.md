# P11 Phase 03: Hardware bake-off & engine baseline

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 02 · **Branch:** `phase-03-bakeoff` · **Worktree:** `../project1111-phase-03` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §2 (non-functional), §3, §5, §11.1 A2, A5, A6, §11.2 R1–R5, R9, R10, R14, R20, R24, §11.3 S1, S3, S4, Appendix A. Phase Log entries for 00 and 02. ADR-0002, ADR-0008, ADR-0009, ADR-0010. **Spec §11.6** (decided 2026-11-02 14:57 CST): H1 budget ≤ 100 GB for candidates, default set ≤ 30 GB; H2 login-free Hugging Face only; H3 restrictive licences allowed and flagged; H5 you pick the defaults; H6 engine switch rule; H8 power profile.

## Goal
Hard numbers from the real laptop decide the engine setup and the default model set. At the end, a pinned headless ComfyUI runs on its own uv Python with a torch build verified on sm_75. A repeatable benchmark harness exists. `docs/P11_BENCHMARKS.md` records speed, VRAM, stability and thermals for the candidate models and presets, and you have picked the defaults from the measurements and a side-by-side visual comparison, leaving the contact sheet for Nick (H5). ADR-0002, 0008, 0009 and 0010 are confirmed or superseded with evidence, and the picks are handed to Phase 06 (manifest) and Phase 04/05 (presets, VRAM mode).

## Tasks
1. **Engine install (scripted, reproducible):** `scripts/engine_setup.sh` (later reused by `install.sh`) clones ComfyUI into `~/.local/share/p11/engine/ComfyUI` at a **pinned commit** (pick the latest tagged release; read its README and `requirements.txt` at that commit), creates a separate uv venv with the Python version it supports (ADR-0008), installs a torch build and checks it: `torch.cuda.is_available()`, `torch.cuda.get_device_capability() == (7, 5)`, a real fp16 matmul and conv on the GPU, and no "no kernel image" errors (ADR-0009). Record versions in `engine/engine.lock.toml` (ComfyUI SHA, Python, torch/torchvision/CUDA build, index URL). No ComfyUI-Manager, no custom nodes yet unless the bake-off needs one, each pinned by SHA with an ADR (S3). Start ComfyUI headless on `127.0.0.1` with telemetry and update checks off (S1); check its launch flags for this at the pinned commit.
2. **Model paths:** generate `extra_model_paths.yaml` pointing ComfyUI at `~/.local/share/p11/models/...` (R8), so models live outside the engine checkout.
3. **Candidates (Appendix A), verified at the source:** shortlist 2–3 uncensored SDXL-class photoreal fine-tunes, 1–2 SD 1.5-class photoreal fine-tunes, a few-step SDXL option, an fp16-safe SDXL VAE, and an upscaler. For each, record source URL, file, size, SHA-256 (computed after download and matched against the host's value where it publishes one), licence, and whether it needs a login. Login-free Hugging Face only (H2); restrictive licences are fine for personal use but record the commercial-use flag and prefer the more permissive model when quality is comparable (H3). Safetensors only (S4). Stay inside the download budget; delete rejected candidates at the end and record that.
4. **Benchmark harness** `scripts/bench/` (Python, uses the P11 uv env; talks to ComfyUI's HTTP/websocket API directly for now; takes the GPU lock): fixed prompt set (10 photoreal, 3 3D-avatar, 3 logo, all non-sexual and without real people), fixed seeds, per-run JSON with cold/warm time, it/s, peak VRAM (NVML or `nvidia-smi` sampling), RAM, OOM yes/no, output path. Run the matrix: model × preset (`1920×1080`, `2560×1440` via native bucket + upscale chain variants: latent/hires denoise pass vs model upscaler vs both; R3, ADR-0010) × VRAM mode (default vs low-VRAM flags) × sampler/steps (2–3 sensible defaults per family).
5. **Stability and thermals** (power: `powerprofilesctl set performance` for the runs, restore the previous profile afterwards even on failure, record profile and AC state; on battery, block; H8)**:** for the leading combination, 50 consecutive generations without OOM, and a 10-minute loop logging GPU temperature, clocks and power to find where the laptop throttles (feeds owner question 5 and R14). Note whether the desktop's ~1 GB use changes (R5).
6. **Contact sheet:** build an HTML or PNG grid of outputs per model/preset (local file under `~/.cache/p11/bench/`, **not** committed) and pick yourself (best photoreal default, best avatar base, acceptable speed), with the reasoning in the default-set ADR (H5). Do not block for a rating; add a "for the owner's review" bullet with the contact-sheet path to the Phase Log entry (H10).
7. **Decide and record:** ADR-0002 (ComfyUI confirmed; a switch to the fallback only under H6: ComfyUI clearly fails a hard requirement and the fallback passes, then a superseding ADR and every affected later prompt rewritten), ADR-0008 (engine Python), ADR-0009 (torch/CUDA build, attention, VAE), ADR-0010 (default upscale chain per preset), plus a new ADR "Default model set and engine VRAM mode" naming the picks (ID, file, SHA-256, size, licence, defaults: sampler, steps, CFG, clip-skip, VAE). Total default set size ≤ the budget (R4).
8. **Hand-off:** write `docs/P11_BENCHMARKS.md` (method, machine state, results tables, picks, raw JSON path), and update Phase 04's preset table, Phase 05's VRAM-mode and timeout assumptions, and Phase 06's manifest list if your results differ from their prompts.

## Out of scope
The `Engine` adapter in `src/p11/engine/` (05), the manifest/downloader (06), face/inpaint/segmentation models (10–12), the installer (15). Bench code may be throwaway-quality but must be reproducible.

## Tests
`make check` stays green; a `gpu` test that runs the pinned engine, generates one 512×512 image with the smallest candidate and asserts a non-black PNG; a unit test for the bench result schema.

## Acceptance criteria
- `scripts/engine_setup.sh` run twice is idempotent and yields the pinned versions; the torch check passes on sm_75 with no CPU fallback.
- ComfyUI listens only on `127.0.0.1` (`ss -ltnp`); no outbound connections during a generation run (check with `ss -tnp` or a short `nethogs`/`ss` sample, S1).
- `docs/P11_BENCHMARKS.md` has numbers for both wallpaper presets for at least 3 models, the 50-run stability result and the thermal curve.
- The default-set ADR is recorded with your pick and its reasoning; the contact sheet path is in the Phase Log for Nick's review (H5, H10).

## Phase-specific docs
`docs/P11_BENCHMARKS.md` (new, prefixed), `engine/engine.lock.toml`, THIRD_PARTY_NOTICES (ComfyUI, torch, picked models), ADRs 0002/0008/0009/0010 status + new ADR, later prompts (04, 05, 06) corrected, owner questions 1 and 5 updated. No host OS changes are expected; if any are needed, stop and ask. Then the standard close-out checklist.
