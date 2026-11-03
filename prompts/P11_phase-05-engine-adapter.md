# P11 Phase 05: Engine adapter, FakeEngine & lifecycle

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 03, 04 · **Branch:** `phase-05-engine-adapter` · **Worktree:** `../project1111-phase-05` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §2 (stability), §11.1 A2, §11.2 R2, R5, R14, R19, R20, R24, §11.3 S1, S3. Phase Log entries for 03 and 04. `docs/P11_BENCHMARKS.md`, `engine/engine.lock.toml`. ADR-0002, ADR-0009, ADR-0014 and Phase 03's default-set/VRAM-mode ADR.

**Phase 04 results (2026-11-02 18:27 CST):** `p11.recipe.compile.compile(recipe, bindings, registry, seed=…)` returns `list[EngineGraph]` (`p11/recipe/compile.py`): `nodes` (API-format dict), `output_node` (a `SaveImage` with `filename_prefix` `p11/step-NN`), `inputs` (`GraphInput`: `LoadImage` nodes whose `image` is a placeholder `p11:slot:<name>`, `p11:step:<index>` or `p11:source`; upload the file and substitute the engine file name before queueing), `models`, `seed`, `size`, and `to_json()` (canonical bytes). Base/hires `KSampler` nodes carry `_meta.title` `base`/`hires` for progress mapping. `tests/gpu/test_compiled_graph_engine.py` runs a compiled wallpaper graph through `scripts/bench/engine.py`; switch it to `ComfyEngine` and the FakeEngine parity tests can reuse the golden graphs in `tests/golden/compile/`.

## Goal
All of P11 talks to the engine through one `Engine` protocol. It has two implementations: `ComfyEngine`, which supervises the pinned headless ComfyUI process and speaks its HTTP and websocket API, and `FakeEngine`, which behaves the same for tests. Progress, cancellation, OOM recovery, memory release and GPU telemetry work reliably on the laptop.

## Tasks
1. **Protocol** (`engine/base.py`): `Engine` with `async start()`, `async stop()`, `async health() → EngineHealth`, `async upload(image: Path|bytes, kind) → EngineFileRef`, `async run(graph, *, on_event) → RunResult` (events: queued, progress(step, total, node), preview(bytes)?, executed(node, outputs), error(kind, message)), `async interrupt()`, `async free_memory(unload_models: bool)`, `async system_stats()`. Typed errors: `EngineUnavailable`, `EngineOOM`, `EngineValidation(node, detail)`, `EngineCrashed`, `EngineTimeout`.
2. **ComfyEngine client** (`engine/comfy.py`, httpx + websockets): queue a prompt with a client ID, follow the websocket for that prompt only, fetch outputs from history/view, upload images, interrupt, free memory, system stats. Read the endpoints and message shapes from the pinned ComfyUI source (don't rely on memory) and keep them in one module with a version check against `engine.lock.toml`.
3. **Supervisor** (`engine/process.py`): start ComfyUI from its uv venv with the flags chosen in Phase 03 (bound to `127.0.0.1`, the configured port, `extra_model_paths.yaml`, the VRAM mode, telemetry/update checks off; **Phase 03 results (2026-11-02 18:08 CST):** the exact flags are `[launch]` in `engine/engine.lock.toml`, the default VRAM mode is ComfyUI's dynamic VRAM (no flag), and `scripts/bench/engine.py` is a working reference), wait for readiness, capture logs to `~/.cache/p11/logs/engine.log` (rotated), restart once on crash, stop cleanly (SIGTERM then SIGKILL after a timeout), refuse to start a second instance (pid file + port check). It takes the GPU lock (R24) for its lifetime and releases it on exit.
4. **OOM handling (R5):** detect OOM from engine errors/logs; `free_memory(unload_models=True)`, retry once with the low-VRAM setting or a reduced tile size (**Phase 03 results (2026-11-02 18:08 CST):** restart with `--disable-dynamic-vram --lowvram`, which caps the peak at ~6.5 GB for ~10 % more time; no OOM occurred in 200+ bake-off runs, so force one in tests; suggested hard timeouts from ADR-0018: 5× cold 60 s / warm 30 s fast, 90 s Quality model), then raise `EngineOOM` with a plain-English message and hint.
5. **GPU telemetry** (`gpu/telemetry.py`): NVML via a maintained binding if its licence and wheel suit (verify), else `nvidia-smi --query-gpu=...` parsing; `GpuSample {vram_used, vram_total, temp_c, power_w, clocks, throttle_reasons}` at ≤ 1 Hz; a `ThermalGuard(pause_at, resume_at)` state machine (thresholds from settings; owner question 5 default) with hysteresis, used later by the video and batch jobs.
6. **FakeEngine** (`engine/fake.py`): accepts the same graphs, validates node types against a list of known nodes, emits realistic event sequences with configurable timing, writes deterministic placeholder PNGs (size from the graph, seed drawn on the image), and can simulate OOM, validation error, crash and slow runs. It is the default in tests and in `p11 serve --fake`.
7. **Parity tests:** a shared contract test suite run against FakeEngine always and against ComfyEngine as `gpu` tests: generate (Phase 04's golden graphs), interrupt mid-run, upload + img2img, free memory, a forced OOM (an oversized latent) that recovers, and engine crash/restart.
8. Run 20 back-to-back generations through `ComfyEngine` with the default model and wallpaper preset, recording times and VRAM, and compare with `docs/P11_BENCHMARKS.md` (the adapter must add < 5 % overhead).

## Out of scope
HTTP API and job queue (07), model downloads (06), UI (08), feature-specific nodes (10–13).

## Tests
Contract suite (fake + gpu), supervisor tests with a dummy subprocess (readiness, crash restart, double start refused, clean stop), telemetry parser tests from captured `nvidia-smi` output, ThermalGuard property tests (no flapping inside the hysteresis band), OOM retry logic with FakeEngine.

## Acceptance criteria
- On the laptop: the default preset generates through `ComfyEngine` 20 times in a row; interrupt stops within 2 s; a forced OOM recovers or fails with the plain-English error; `p11` leaves no engine process behind after `stop`.
- Engine listens on `127.0.0.1` only; its log contains no outbound update/telemetry attempts.
- `make check` green; `make gpu-test` green on the laptop.

## Phase-specific docs
`docs/P11_ARCHITECTURE.md` (engine protocol, events, supervisor, OOM path, telemetry), `docs/P11_BENCHMARKS.md` (adapter overhead), ADRs for the NVML choice and any engine flag decisions, CHANGELOG. Then the standard close-out checklist.
