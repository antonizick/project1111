# P11 Architecture

Skeleton from Phase 01; each phase updates the sections it changes. Canonical requirements are in [`P11_SPECIFICATION.md`](P11_SPECIFICATION.md).

## Components
```
Browser (P11 Studio, React/TS)
   │  HTTP + WebSocket/SSE, 127.0.0.1 only, token + Host/Origin checks
   ▼
Studio API (FastAPI)            src/p11/api
   ▼
Job runner (queue, GPU lock)    src/p11/jobs
   ▼
Engine adapter (p11.engine.Engine protocol; ComfyUI client, FakeEngine)
   │  127.0.0.1 only
   ▼
Headless ComfyUI (pinned commit, own uv env)   engine/
```
Recipes (`src/p11/recipe`) are pure data compiled to engine graphs; nothing outside `p11.engine` talks to ComfyUI.

## Data locations (spec R8)
User data follows XDG paths (config, data, cache, state); the exact layout is fixed in Phase 02 (`paths.py`). The advisory GPU lock is `~/.cache/p11/gpu.lock`. Weights, outputs and uploads are never inside the repository.

## Trust boundaries
- **Browser ↔ Studio API:** untrusted input; Host/Origin/token checks, CSP, upload validation.
- **Studio API ↔ engine:** loopback only; the engine is never exposed beyond `127.0.0.1`.
- **Network ↔ model downloads:** pinned URL (commit), size and SHA-256 checked before a file is used; HTTPS only; tokens only to their own host, never across redirects; safetensors/GGUF only unless a user opts in per file; login-free hosts by default (ADR-0021).
- **Face-swap paths:** NSFW target guard always on (spec S5, ADR-0005).

## Package map (Phase 02)
| Path | Role | Status |
|---|---|---|
| `src/p11/cli.py` | Typer app: `version`, `paths`, `serve`, `models …` (Phase 06); stubs `start stop status open doctor update` | real (stubs print the owning phase) |
| `src/p11/paths.py` | XDG config/data/cache/pictures with `P11_*_DIR` overrides; `ensure_private_dir()` makes `0700` dirs | real |
| `src/p11/config.py` | `Settings` from `~/.config/p11/config.toml` and `P11_*` env; host must be `127.0.0.1` (S1) | real |
| `src/p11/gpulock.py` | `gpu_lock(timeout, holder)`: `flock` on `~/.cache/p11/gpu.lock`, holder info (pid, name, start) readable by waiters (R24) | real |
| `src/p11/api/app.py` | `create_app(engine=…)`: `GET /healthz`, serves `src/p11/web/` at `/` when built, keeps the engine on `app.state.engine` | real (middleware arrives in Phase 07) |
| `src/p11/{engine,gpu}/` | engine adapter and GPU telemetry (Phase 05, below) | real |
| `src/p11/{jobs,media}/` | empty packages with docstrings naming the owning phase | skeleton |
| `src/p11/{recipe,outputs,templates}/` | recipe core (Phase 04, below) | real |
| `frontend/` | Vite + React + TS (strict); `vite build` writes to `src/p11/web/` (git-ignored) | placeholder page |

## Engine install (Phase 03)
| Path | Role |
|---|---|
| `engine/engine.lock.toml` | ComfyUI tag and commit, engine Python, torch build and index URL, launch flags (S1), custom nodes (none) |
| `engine/requirements.lock.txt` | hash-locked engine dependencies (`uv pip compile --generate-hashes`) |
| `engine/extra_model_paths.yaml.tmpl` | template for `~/.local/share/p11/engine/extra_model_paths.yaml` (models live in `~/.local/share/p11/models/<kind>/`, R8) |
| `scripts/engine_setup.sh` | idempotent install/verify: clone at the pin, uv venv (CPython 3.12), `uv pip sync --require-hashes`, model folders, sm_75 torch check; `--dry-run`, `--relock`, `--no-check` |
| `~/.local/share/p11/engine/{ComfyUI,venv}` | the installed engine (never in the repo) |
| `scripts/bench/` | bake-off harness (talks to ComfyUI directly, kept so the bake-off is reproducible; product code uses `p11.engine`); `adapter.py` is Phase 05's adapter benchmark; results in `docs/P11_BENCHMARKS.md`, raw JSON in `~/.cache/p11/bench/` |

Engine defaults (ADR-0009, ADR-0010, ADR-0018): fp16 UNet/text encoders, SDPA attention, fp32 VAE decode (tiled at wallpaper size), ComfyUI's dynamic VRAM by default with `--disable-dynamic-vram --lowvram` as the OOM retry; wallpapers are generated at the native bucket and upscaled with a model upscaler.

## Recipe core (Phase 04)
Everything here is pure or touches the filesystem only through roots passed in (`tests/unit/test_pure_modules.py` checks there are no network imports). ADR-0007, ADR-0019.

| Path | Role |
|---|---|
| `recipe/model.py` | Recipe schema v1 (frozen Pydantic): `Recipe`, `Step` union (`generate`, `upscale`, `inpaint`, `replace_background`, `face_swap`, `pose`, `reference`, `text_overlay`), `Slot`, `SeedStrategy`, `ModelRef`, `FileRef`; cross-checks slot references and `{{slot}}` placeholders |
| `recipe/migrate.py` | `migrate(dict)`, `loads(json)`: version check, `MIGRATIONS[n]` chain, plain-English errors; newer versions refused |
| `recipe/presets.py` | the one preset table: aspect presets (bucket per family, output size, default and Quality chain) and style presets (prompt prefix/suffix, negative, default aspect and model) |
| `recipe/registry.py` | `ModelRegistry` protocol + `ModelInfo`/`SamplerDefaults`; `PROVISIONAL_DEFAULT_SET`, a pure copy of the manifest for compiler tests (a test keeps them equal); the app uses `p11.models` (Phase 06) |
| `recipe/compile.py` | `compile(recipe, bindings, registry, seed=…) → list[EngineGraph]`, `resolve_seed`, `resolve_bindings`, `register_step`, `register_modifier` |
| `recipe/variations.py` | `seed_variations(recipe, n, rng?)`, `prompt_mutation(recipe, rng)` (word lists, no network) |
| `outputs/layout.py` | `output_path(root, now, template_slug, seed, step)` → `<root>/YYYY-MM-DD/<slug|adhoc>/<HHMMSS>-<seed>[-<step>].png`, `0700` dirs, file reserved `0600` with `O_EXCL`, `-2`… on collision; `slugify` |
| `outputs/metadata.py` | `RunRecord` (recipe, bindings as file refs, seed, model hashes, engine version, timings, step outputs, template, parent); sidecar `.json`; `iTXt` chunks `p11:recipe` / `p11:run`; `read_recipe_from_png`; `strip_metadata` |
| `outputs/index.py` | `GalleryIndex(db_path)`: SQLite `images` table + FTS5 `images_fts` on prompt text, migrations on `PRAGMA user_version`, search (prefix words, template, favourites), parents/children, `reindex(root)` from sidecars (keeps favourites) |
| `templates/store.py` | `TemplateStore(root)`: `<root>/<folder>/<slug>.json`, save/find/load/delete/search/folders, `export`, `import_bytes` (validated, migrated, new ID) |

**Compile flow.** Each graph-producing step becomes one ComfyUI API graph ending in `SaveImage` (`p11/step-NN`). A step that needs an image gets a `LoadImage` whose `image` is a placeholder (`p11:step:<i>` for the previous step's output, `p11:slot:<name>` for an input, `p11:source` for the recipe's source image); `EngineGraph.inputs` lists them for the job runner. `pose`/`reference` are modifiers folded into the preceding `generate` graph. Generate graph: checkpoint (+ VAE override, LoRAs, clip skip) → prompts with the style's prefix/suffix/negative → `EmptyLatentImage` at the family bucket → `KSampler` (`base`) → chain: `native` (`VAEDecode`), `model` (decode → upscale model → Lanczos to output), `latent` (bislerp latent upscale → `KSampler` `hires` at 0.45 → tiled decode), `both` (model chain → tiled encode → `hires` at 0.3 → tiled decode).

```
recipe + bindings + registry + seed ──compile──► [EngineGraph …] ──job runner (05/07)──► engine
                                                                        │
                    output_path ◄── RunRecord ──► sidecar .json + PNG iTXt ──► GalleryIndex
```

**Gallery schema (v1).** `images(id, path UNIQUE relative to the outputs root, created_at, recipe_id, template, seed, model, width, height, favourite, parent_id → images.id ON DELETE SET NULL, prompt)`; `images_fts(prompt)` external-content FTS5 kept in sync by triggers. The index is a cache; `reindex` rebuilds it.

## Engine adapter and telemetry (Phase 05)
Everything that talks to the engine takes a `p11.engine.Engine`; only `p11.engine` imports the ComfyUI client. ADR-0020.

| Path | Role |
|---|---|
| `engine/base.py` | `Engine` protocol (`start`, `stop`, `restart(vram_mode)`, `health`, `upload(image, kind)`, `run(graph, on_event, timeout)`, `interrupt`, `free_memory(unload_models)`, `system_stats`, `vram_mode`); events `Queued`, `Executing`, `Progress(step, total, node, title)`, `Preview`, `Executed(node, outputs)`, `ErrorEvent`, `Retrying`; values `EngineFileRef`, `OutputImage`, `RunResult`, `SystemStats`, `EngineHealth`; errors `EngineUnavailable`, `EngineOOM`, `EngineValidation(node, detail)`, `EngineExecutionError`, `EngineInterrupted`, `EngineCrashed`, `EngineTimeout`; `bind_inputs(graph, {placeholder: ref})` |
| `engine/comfy.py` | `ComfyEngine(EngineConfig)`: every ComfyUI endpoint and message shape (read from v0.43.0 `426f5ee`), version + loopback check at start, per-run websocket with a client-chosen `prompt_id`, outputs fetched via `/history` + `/view` and deleted from the engine scratch dir; `EngineConfig.default(settings)` builds the command from `engine.lock.toml` |
| `engine/process.py` | `ProcessSupervisor(ProcessSpec, ready)`: GPU lock for the process lifetime, pid file + port check, own session + `PR_SET_PDEATHSIG`, log rotation, readiness poll, one restart after a crash, SIGTERM → SIGKILL stop |
| `engine/recovery.py` | `run_with_oom_retry(engine, graph)`: free memory → restart in `lowvram` → retry once → plain-English `EngineOOM` |
| `engine/fake.py` | `FakeEngine(FakeConfig)`: validates like `/prompt` (known nodes, links, uploads, optional model list), emits the same events, deterministic placeholder PNGs at the graph's output size, simulated OOM (by latent area per VRAM mode), validation error, crash (+ one auto-restart), failure, slow runs; `p11 serve --fake` |
| `engine/lockfile.py` | `load_lock()`: `$P11_ENGINE_LOCK`, else the repo's `engine/engine.lock.toml`, else `~/.local/share/p11/engine/engine.lock.toml` |
| `engine/__init__.py` | `create_engine(settings, fake=False)` |
| `gpu/telemetry.py` | `GpuSample` (VRAM, temperature, power, clocks, throttle reasons); `NvmlSampler` (`nvidia-ml-py`), `NvidiaSmiSampler` fallback, `default_sampler()`, `stream(sampler)` at ≤ 1 Hz; `ThermalGuard(pause_at, resume_at)` with hysteresis (settings 87 / 80 °C, H9) |

**Run flow.** `run` opens `ws://127.0.0.1:<port>/ws?clientId=<id>`, `POST /prompt` with its own `prompt_id`, and maps messages for that prompt only: `executing` → `Executing` (node `None` = done), `progress` → `Progress` (titled `base`/`hires` from the compiler's `_meta`), `executed` → `Executed`, `execution_success` → done, `execution_interrupted` → `EngineInterrupted`, `execution_error` → `EngineOOM` (exception type/message or `Got an OOM` in the log since the run started) or `EngineExecutionError`; HTTP 400 → `EngineValidation` with the first node error; a lost websocket → `EngineCrashed` if the process died, else `EngineUnavailable`; the hard timeout interrupts the run and raises `EngineTimeout`.

```
job (07) ─► run_with_oom_retry ─► Engine.run ──ws + HTTP──► ComfyUI (127.0.0.1:8188)
               │ EngineOOM                                     ▲
               └─► free_memory ─► restart("lowvram") ─► retry ─┘   ProcessSupervisor: lock, pid,
                                                                   log, 1 crash restart, stop
```

**Files.** Engine log `~/.cache/p11/logs/engine.log` (rotated, 3 kept); pid file `~/.cache/p11/engine.pid`; scratch `~/.cache/p11/engine/{in,out,tmp,user}` (`0700`; outputs deleted after fetch; uploads are content-addressed `p11-<kind>-<sha256[:20]>.<ext>`, never user file names).

**Tests.** `tests/engine_contract.py` is one contract suite run against `FakeEngine`, against `ComfyEngine` over a mock ComfyUI server (`tests/fixtures/mock_comfyui.py`, same endpoints and messages, backed by a `FakeEngine`) in `make test`, and against the real engine in `make gpu-test` (`tests/gpu/test_engine_contract_gpu.py`, which forces a real OOM with `tests/gpu/vram_hog.py`). Supervisor tests use `tests/fixtures/dummy_engine.py`.

Quality gates: `make check` (see `CONTRIBUTING.md`); CI runs the same target.

## Model manager (Phase 06)
`src/p11/models/` turns the hash-pinned manifest (ADR-0006, ADR-0018, ADR-0021) into installed files.

| Module | Role |
|---|---|
| `models/manifest.toml` (repo root) | the curated set: per entry `id, name, kind, base, files[{url (HF `/resolve/<commit>/`), filename, sha256, size}], licence {name, url, commercial_use, flags}, requires_login, sets, defaults, scale, source, notes`, each with a `# Checked <TS>` comment |
| `models/manifest.py` | strict schema (unknown keys are errors) and cross-checks; `find_manifest()`: `$P11_MODEL_MANIFEST`, else the repo copy, else `~/.local/share/p11/manifest.toml`; `KIND_FOLDERS` |
| `models/download.py` | `Downloader`: HTTPS only, manual redirects (token only to its own host), `.part` + `Range` resume, streaming SHA-256, atomic rename, size/hash mismatch deletes the part, backoff retries, disk-space pre-check, ≤ 2 per host; `load_tokens()` from `secrets.toml` (`0600` enforced) |
| `models/formats.py` | content sniffing (`safetensors`, `gguf`, `pickle`, `torch-zip`, `unknown`), safetensors header reader, kind/base detection from tensor names |
| `models/state.py` | `LicenceStore` (`~/.config/p11/licences.toml`), `StateStore` (`~/.config/p11/models.toml`: disabled IDs, user models), `HashCache` (`~/.cache/p11/model-hashes.json`, keyed by path + size + mtime) |
| `models/registry.py` | `ModelManager`: `statuses()` (`installed | missing | corrupt | user-added | unregistered`, join by hash), `plan`/`install` (licence acknowledgement, `--from` reuse, repair), `verify`, `add` (S4 policy), `remove`, `set_enabled`, `write_extra_model_paths`; `registry()` → `ManagerRegistry` for the compiler |
| `models/doctor.py` | `check()` → `list[p11.problems.Problem]` for `p11 doctor` |
| `models/cli.py` | `p11 models list|install|verify|add|remove|enable|disable|licences`, all with `--json` |

**Layout.** `~/.local/share/p11/models/` (or `models_root` in `config.toml`) holds `checkpoints/ loras/ vae/ controlnet/ ipadapter/ upscale/ facerestore/ faceswap/ facedetect/ segmentation/ embeddings/`; ComfyUI reads them through `extra_model_paths.yaml`, written by `scripts/engine_setup.sh` and by `p11 models install` from the same template. Partial downloads are `<file>.part` next to the target; URL adds are staged in `.incoming/`.

**Tests.** `tests/fixtures/model_server.py` is a loopback HTTP server with Range, cut-off connections, redirects and request recording; `Downloader(insecure_hosts=…)` and `parse_manifest(…, loopback_http=True)` are the only ways to use plain http (tests). `tests/net/` holds the one real download (the smallest default entry), run with `P11_NET_TESTS=1`.

_To be detailed in Phase 07 and the Phase 16 threat model._
