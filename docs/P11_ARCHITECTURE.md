# P11 Architecture

Skeleton from Phase 01; each phase updates the sections it changes. Canonical requirements are in [`P11_SPECIFICATION.md`](P11_SPECIFICATION.md).

## Components
```
Browser (P11 Studio, React/TS)
   │  HTTP + SSE, 127.0.0.1 only, token + Host/Origin checks (ADR-0022)
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

| Path | What | Phase |
|---|---|---|
| `~/Pictures/P11/YYYY-MM-DD/<template\|adhoc>/` | outputs (`0600`) + sidecars, dirs `0700` | 04 |
| `~/.local/share/p11/gallery.db`, `jobs.db` | gallery index (cache of the sidecars), job table | 04, 07 |
| `~/.local/share/p11/inputs/` | validated uploads `img-<hex>.png`, `vid-<hex>.mp4/.mkv` + `.json` meta, `0700`/`0600`; `.incoming/` spool | 07 |
| `$XDG_RUNTIME_DIR/p11/studio.token`, `studio.json` | per-launch session token and the running Studio's pid/port (`0600`) | 07 |
| `~/.cache/p11/logs/studio.log`, `studio.out` | JSON Studio log (rotated, redacted), stdout of `p11 start` | 07 |
| `~/.cache/p11/thumbs/` | gallery thumbnails (WebP) | 07 |
| `~/.cache/p11/fake/` | `p11 serve --fake` sandbox (demo gallery, data, templates) | 07 |
| `~/.config/p11/templates/` | template store | 04 |

## Trust boundaries
- **Browser ↔ Studio API:** untrusted input; Host/Origin/token checks, CSP, upload validation.
- **Studio API ↔ engine:** loopback only; the engine is never exposed beyond `127.0.0.1`.
- **Network ↔ model downloads:** pinned URL (commit), size and SHA-256 checked before a file is used; HTTPS only; tokens only to their own host, never across redirects; safetensors/GGUF only unless a user opts in per file; login-free hosts by default (ADR-0021).
- **Face-swap paths:** NSFW target guard always on (spec S5, ADR-0005).

## Package map (Phase 02)
| Path | Role | Status |
|---|---|---|
| `src/p11/cli.py` | Typer app: `version`, `paths`, `serve`, `start`, `stop`, `status`, `open`, `doctor` (Phase 07), `models …` (Phase 06); stub `update` (Phase 15) | real |
| `src/p11/paths.py` | XDG config/data/cache/pictures with `P11_*_DIR` overrides; `ensure_private_dir()` makes `0700` dirs | real |
| `src/p11/config.py` | `Settings` from `~/.config/p11/config.toml` and `P11_*` env; host must be `127.0.0.1` (S1) | real |
| `src/p11/gpulock.py` | `gpu_lock(timeout, holder)`: `flock` on `~/.cache/p11/gpu.lock`, holder info (pid, name, start) readable by waiters (R24) | real |
| `src/p11/api/` | Studio API (Phase 07, below): `create_app()`, `SecurityMiddleware`, routes, the `Studio` container | real |
| `src/p11/{engine,gpu}/` | engine adapter and GPU telemetry (Phase 05, below) | real |
| `src/p11/jobs/`, `src/p11/media/` | job queue, runner, events, persisted jobs; upload validation and the input store (Phase 07, below); inpaint mask prep and paste-back (Phase 10) | real |
| `src/p11/lifecycle.py`, `doctor.py`, `logs.py` | background Studio process (`studio.json`), `p11 doctor` checks, JSON log with redaction (Phase 07) | real |
| `src/p11/{recipe,outputs,templates}/` | recipe core (Phase 04, below); `recipe/steps/` step compilers of later phases (inpaint, Phase 10) | real |
| `frontend/` | Vite + React + TS (strict); `vite build` writes to `src/p11/web/` (git-ignored), always through `make build` / `p11.webbundle build`, which bakes in the build id and writes `build-info.json` (ADR-0043); `src/api/session.ts` redeems the launch code (Phase 07) | placeholder page with a working session |

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
| `recipe/compile.py` | `compile(recipe, bindings, registry, seed=…, image_sizes=…) → list[EngineGraph]`, `resolve_seed`, `resolve_bindings`, `register_step`, `register_modifier` |
| `recipe/variations.py` | `seed_variations(recipe, n, rng?)`, `prompt_mutation(recipe, rng)` (word lists, no network) |
| `outputs/layout.py` | `output_path(root, now, template_slug, seed, step)` → `<root>/YYYY-MM-DD/<slug|adhoc>/<HHMMSS>-<seed>[-<step>].png`, `0700` dirs, file reserved `0600` with `O_EXCL`, `-2`… on collision; `slugify` |
| `outputs/metadata.py` | `RunRecord` (recipe, bindings as file refs, seed, model hashes, engine version, timings, step outputs, template, parent); sidecar `.json`; `iTXt` chunks `p11:recipe` / `p11:run`; `read_recipe_from_png`; `strip_metadata` |
| `outputs/index.py` | `GalleryIndex(db_path)`: SQLite `images` table + FTS5 `images_fts` on prompt text, migrations on `PRAGMA user_version`, search (prefix words, template, favourites), parents/children, `reindex(root)` from sidecars (keeps favourites) |
| `templates/store.py` | `TemplateStore(root)`: `<root>/<folder>/<slug>.json`, save/find/load/delete/search/folders, `export`, `import_bytes` (validated, migrated, new ID) |

**Compile flow.** Each graph-producing step becomes one ComfyUI API graph ending in `SaveImage` (`p11/step-NN`). A step that needs an image gets a `LoadImage` whose `image` is a placeholder (`p11:step:<i>` for the previous step's output, `p11:slot:<name>` for an input, `p11:source` for the recipe's source image); `EngineGraph.inputs` lists them for the job runner. `pose`/`reference` are modifiers folded into the preceding `generate` graph. Generate graph: checkpoint (+ VAE override, LoRAs, clip skip) → prompts with the style's prefix/suffix/negative → `EmptyLatentImage` at the family bucket → `KSampler` (`base`) → chain: `native` (`VAEDecode`), `model` (decode → upscale model → Lanczos to output), `latent` (bislerp latent upscale → `KSampler` `hires` at 0.45 → tiled decode), `both` (model chain → tiled encode → `hires` at 0.3 → tiled decode).

**Photo edit (Phase 17b, ADR-0038).** A `generate` step with `image_slot`, `denoise` or `denoise_preset` set starts from a photo: its slot, else the recipe's `source_image` (never the previous step). The graph replaces `EmptyLatentImage` with `LoadImage` → `ImageScale` (Lanczos, centre crop) to the family's bucket nearest the photo's aspect (`presets.BUCKETS`, `compile.nearest_bucket`) → `VAEEncode` (→ `RepeatLatentBatch` for a batch) → `KSampler` `base` at the preset's denoise (`presets.IMG2IMG_PRESETS`; steps raised to `IMG2IMG_MIN_STEPS` for few-step models). The output size is the bucket scaled toward the photo's own pixel count, capped at 2560 × 1440 (`compile.photo_output`), reached by the usual `model` chain (`latent` with Quality); the aspect preset is ignored. The compiler stays pure: the runner passes `compile(…, image_sizes={ref: (w, h)})`, read from the PIL header of each bound or source file; with no size the aspect preset's bucket is used. Pose and reference modifiers still apply.

**Engine output names (ADR-0042).** `ComfyEngine._run` stamps `SaveImage`'s `filename_prefix` with the first 8 characters of the prompt id (`base.stamp_output_prefixes`), because P11 deletes an engine output right after fetching it and ComfyUI's execution cache can otherwise report a *deleted* file name for a byte-identical repeat run. The token is a plain node input, hence part of the cache key, so `SaveImage` always writes its own file while the cached upstream nodes still save the sampling time. Nothing parses the name; the FakeEngine (no cache, no deletion) keeps the plain `p11/step-NN`.

**Upload face rule (S5, ADR-0038).** `Runner.edited_uploads(recipe, bindings)` lists the uploaded (not gallery) photos that a photo-edit `generate`, an `inpaint`, a `replace_background` or a `face_restore` (ADR-0047) edits or composites (masks excluded). At submit, `require_edit_guard` refuses the job (`GuardUnavailable`, 409 `face.guard-models`, "Editing an uploaded photo needs the face safety models…") when the detector or the guard classifiers are missing. At run time `upload_shows_face` runs YuNet (`media.faces.detect_faces`, CPU) on each; a face makes the whole run start with `likeness` on, so every output passes `check_likeness` and the sidecar records `likeness = True` (later jobs from it inherit the check, ADR-0037). Gallery images P11 made without likeness and text to image are never checked (A5).

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

## Studio API (Phase 07)
```
browser ──HTTP/SSE──► AccessLog ─► SecurityMiddleware ─► FastAPI routes ─► Studio
                         (Host, Origin/Sec-Fetch-Site, token/cookie,      │
                          CSP + headers, body caps)                       ├─ JobQueue ─► Runner ─► Engine
                                                                          ├─ GalleryIndex, JobStore (SQLite)
                                                                          ├─ InputStore, TemplateStore
                                                                          └─ EventBus ─► GET /api/events
```
`create_app(web_dir, engine, *, settings, session, port, fake, studio_paths, sampler, seed_demo)` builds a `Studio` (`api/studio.py`); its lifespan opens the SQLite stores on the event-loop thread, starts the job worker and (with a GPU) the ≤ 1 Hz GPU publisher, and on shutdown cancels jobs and stops the engine. ADR-0022.

**Security middleware** (`api/security.py`): Host must be `127.0.0.1:<port>` or `localhost:<port>` (421); a foreign `Origin` or cross-site `Sec-Fetch-Site` is refused on state-changing requests and on every `/api` read (403); `/api` needs the session token in `Authorization: Bearer` / `X-P11-Token`, or the `p11_session` cookie for `GET`/`HEAD` only (401); `POST /api/session` (launch code → token) is the one public `/api` route; websockets are refused. Every response gets the CSP (`default-src 'self'; img-src 'self' blob: data:; …; object-src 'none'; frame-ancestors 'none'`), `nosniff`, `no-referrer`, `X-Frame-Options: DENY`, COOP/CORP; `/api` responses are `no-store`; everything else is `no-cache` (so `index.html` is revalidated on every load) except the content-hashed `/assets/*`, which stay cacheable (ADR-0043). Body caps: 1 MiB, uploads 1 GiB (413). `/healthz` and the static UI need no token. `/healthz` returns `status`, `version`, `busy` (`idle`/`busy`) and `queue` (`{"running": 0|1, "waiting": n}`) — counts only, no job id, prompt or file name — so the Omarchy Control Center can show a busy badge without the session token (Phase 17c, ADR-0039), and `web`, the bundle's short build id (Phase 17e).

**Frontend bundle** (`src/p11/webbundle.py`, ADR-0043): `src/p11/web/` is git-ignored, so a merge or checkout changes the sources under a bundle that stays as it was. `build-info.json` records a SHA-256 over `frontend/src/**`, `frontend/public/**`, `index.html`, `package-lock.json` and `vite.config.ts`, plus `built_at`, `version` and `commit`. `status()` is `current`, `stale` (including a bundle with no stamp), `missing` or `no-sources` (a tree without `frontend/`). `install.sh` rebuilds on `stale` or `missing`, and `p11 update` inherits that by re-running it; `p11 doctor`, `p11 status` and a startup WARNING from `p11 serve` report it; `p11 serve` never builds. The module is standard library only because `install.sh` runs it on uv's Python 3.12 before P11's environment exists. The window's id is baked into the JavaScript (`__P11_BUILD__`, from `P11_BUILD_ID`), not fetched, so it names what the window actually loaded; the status bar compares it with `/api/system`'s `web` and offers a reload when they differ.

**Routes** (`api/routes/`; errors are always `{"code", "message", "hint"}`):

| Route | Purpose |
|---|---|
| `POST /api/session` · `GET /api/session` · `POST /api/session/launch` | redeem a launch code (sets the cookie, returns the token) · check the session · mint a launch code (`p11 open`) |
| `POST /api/jobs` · `GET /api/jobs` · `GET /api/jobs/{id}` · `POST /api/jobs/{id}/cancel` | `{recipe, bindings, count 1–16, template?, parent?}` → 201 job (validated by compiling first) · recent jobs · one job · cancel (queued: at once; running: engine interrupt) |
| `GET /api/events` | SSE: `hello`, `job`, `progress`, `preview`, `image`, `gpu`, `deleted` (Phase 08); IDs increase; `Last-Event-ID` replays |
| `GET /api/gallery` · `/gallery/facets` · `POST /api/gallery/export` | `q` (prefix word search), `template`, `model`, `favourites`, `since`/`until` (ISO), `limit`/`offset` → `{items, total, limit, offset}` · distinct templates and models · `{ids, strip_metadata}` → ZIP (Phase 08) |
| `GET /api/images/{id}` · `/info` · `/thumb?size=` · `/recipe` | PNG · entry · WebP thumbnail (256/384/512, cached) · run record (sidecar, else PNG chunks) |
| `POST /api/images/{id}/favourite` · `/export` · `/variations` · `DELETE /api/images/{id}` | `{favourite}` · `{strip_metadata: true}` → PNG download · `{mode: seed\|prompt, count 1–4}` → `{jobs}` · move PNG + sidecar to `<data>/trash/` (Phase 08) |
| `GET /api/trash` · `POST /api/trash/empty` | `{count, bytes}` of the trash · delete the trash folder (Phase 08) |
| `POST /api/uploads?kind=image\|mask\|video` · `GET /api/uploads/{id}` · `/info` | raw-body upload → `{id, kind, width, height, sha256, seconds, warnings}` · the stored file · its metadata |
| `GET/POST /api/templates` · `GET/PUT/DELETE /api/templates/{id}` · `/export` · `POST /api/templates/import` · `GET /api/templates/folders` | template store (Phase 04) |
| `GET /api/presets` · `GET /api/models` · `GET /api/system` | aspect and style presets · `p11 models list --json` objects plus `usable`, `family`, `defaults`, `vae` from the registry (Phase 08) · engine health, GPU sample, queue, disk |
| `GET /api/openapi.json` | the schema (behind the token; no docs UI) |

**Job model** (`jobs/`): `JobStore` (SQLite `jobs.db`) holds `id, state, recipe, bindings, count, template, parent, images, progress, error, note`; states `queued → running ⇄ paused → done | failed | cancelled`. `JobQueue` has one worker: lazy engine start, `Runner.run` per job, idle stop after `engine_idle_stop` s, `lowvram → dynamic` reset after 60 s idle; `mark_interrupted()` at startup. `Runner` resolves seeds, compiles, uploads slot/source/step inputs (`img-…` uploads or `gallery/<id>` images), runs each graph through `run_with_oom_retry`, saves every output (`output_path`, sidecar, `embed_record`, `GalleryIndex.add`, parent chain) and publishes events. `JobControl.checkpoint(long=…)` is the cancel point and the `ThermalWatch` hook (87/80 °C). `jobs/errors.py` maps every typed error to `(HTTP status, JobError)`.

**Uploads** (`media/`): `validate_image` (Pillow decode, PNG/JPEG/WebP, ≤ 40 MP, EXIF transpose, PNG re-encode without EXIF/text; masks → `L`), `check_video`/`probe_video` (ffprobe; mp4/mov or mkv/webm; h264/hevc/vp8/vp9/av1/mpeg4; ≤ 600 s, ≤ 2160p; warnings beyond R13's 60 s/1080p settings), `strip_video_metadata` (stream-copy remux, `-map_metadata -1`). `InputStore` names files `img-<uuid hex>`/`vid-<uuid hex>`.

**CLI lifecycle** (`lifecycle.py`): `p11 serve` writes the token and `studio.json` and removes them on exit; `p11 start` = detached `python -m p11 serve` + `/healthz` wait; `p11 stop` = SIGTERM (graceful: the lifespan stops the engine) then SIGKILL after 30 s, only to a pid whose cmdline is `p11 serve`; `p11 status` reads `/api/system` (exit 3 when not running); `p11 open` mints a launch code and runs `omarchy-launch-webapp <url>` / `<chromium-family> --app=<url>` / `xdg-open` (`$P11_BROWSER` overrides; `--print-url` prints it). `p11 doctor` (`doctor.py`) checks the GPU (`nvidia-smi`), the engine install and pinned version (`comfyui_version.py` vs `engine.lock.toml`), the engine's torch/CUDA/sm arch (skipped by `--quick`), models (`p11.models.check()`), ports, disk and permissions; exit 1 on any error.

**Logging** (`logs.py`): JSON lines, rotated 5 MB × 3, `0600`; uvicorn's access log off; `AccessLog` writes method, path, status, ms; `debug_private` for prompt text (DEBUG only); `register_secret` redacts the token and launch codes everywhere.

_The Phase 16 threat model builds on this section._

## Studio UI (Phase 08)
```
main.tsx ─► App (session bootstrap) ─► ToastProvider ─► ShortcutProvider ─► NavProvider ─► StudioProvider ─► Shell
                                                                                              │
             api/events.ts (EventSource + reconnect) ─► reducer (app/studio.tsx) ◄── 5 s /api/system poll
```
`frontend/src/`:

| Path | Role |
|---|---|
| `api/session.ts` · `api/client.ts` · `api/types.ts` | launch code → token; typed calls (`client.*`), `apiBlob` + `saveDownload` for exports, `problemOf` for toasts; hand-written API types |
| `api/events.ts` | `EventStream`: `EventSource('/api/events')` (cookie auth), all event types, rebuild with 1/2/5/10 s backoff once the browser gives up |
| `app/studio.tsx` | pure `reduce()` over events and actions → jobs, step progress, previews, images, `galleryRev` (bumped on new/changed/deleted images), GPU, system, presets, models, current model |
| `app/Shell.tsx` · `app/nav.tsx` · `app/StatusBar.tsx` | left nav (`VIEWS`, placeholders for 09–14), top bar (connection, version, theme, `?`), status bar (engine, queue, VRAM, temperature band 70/80/87 °C, model); "open as recipe" hand-off |
| `app/shortcuts.tsx` · `app/Toasts.tsx` · `app/theme.css` | keyboard map (`commandFor`) with a newest-wins handler stack; plain-English toasts with hints and an optional action; light/dark CSS variables, system fonts only |
| `features/generate/` | `form.ts` (pure form ⇄ recipe v1, upscale follow-up recipe; Phase 17b: `StartPhoto`, `PHOTO_PRESETS`, `photoFromImage`, the photo becomes `source_image` + `denoise_preset`/`denoise`), `eta.ts`, `GenerateView` (Simple mode, **Start from a photo** drop zone with a bounded `.thumb` and Remove, Strength chips, Size chips disabled while a photo is set, progress, result; receives "Use as starting photo" through `nav.edit("generate", image)`), `AdvancedDrawer` (photo strength slider 0.10–0.95), `ResultPanel` |
| `features/gallery/` | `layout.ts` (pure day-grouped virtual rows at either tile size), `tileSize.ts` (the remembered Small/Medium choice), `GalleryView` (search, filters, sizes, selection, bulk export, delete, trash), `DetailView`, `CompareView` (shared zoom) |
| `components/GalleryPicker.tsx` | **From gallery** on all ten image inputs (Phase 17g): button plus a `Dialog` portalled to `document.body` (Enter in its search box must not submit the view's form), search and paging over `GET /api/gallery`. `onPick` returns the `ImageEntry`; each control turns it into a `gallery/<id>` reference through its existing hand-off, never into bytes (ADR-0046) |
| `features/actions.tsx` · `components/` | follow-up actions shared by result and detail (`LATER` = actions of later phases); `Dialog` (focus trap, Esc), `ZoomPan` (wheel/keys/drag, controllable) |

Generate builds a one-step `generate` recipe; Advanced fields stay `null` (manifest defaults) until changed, a locked seed becomes `increment`. Styles only use the CSSOM (`element.style`), which `style-src 'self'` allows. Tests: Vitest + Testing Library with a routed fake `fetch` and a fake `EventSource` (`src/test/fakes.ts`); Playwright walkthroughs on `p11 serve --fake` (`e2e/daily.spec.ts`: action counts, network guard, axe), `e2e/screenshots.spec.ts` (`P11_SCREENSHOTS=1`) and `e2e/real-engine.spec.ts` (`P11_REAL_LAUNCH_URL=…`, laptop only). ADR-0023.

**Layout rule (Phase 17a).** The shell is fixed-height and `.main` clips, so every view is its own scroll container (`overflow: auto; min-height: 0`): the Generate/Inpaint/Background grid columns, and the single-column Face & Pose, Video and Models views. An overlay on a picture (the Background mask, the Video face boxes, the Text & logo crosshair) sits in a wrapper that shrink-wraps the picture (`width: fit-content`, `align-self: flex-start` inside a flex column), never in a box that stretches to the pane. `e2e/ui-fixes.spec.ts` checks both rules in Chromium.

**Reset (Phase 17h, ADR-0048).** The top bar's Reset is client-only and sends no writing request. `Shell` keys the views on `NavProvider.resetKey`, so they remount with their initial state; `nav.reset()` clears `editing` in the same update, because each view compares `editing.at` during render and a remounted view would load the old hand-off again. The `reset` reducer action drops finished jobs and `currentModel`. `ResetDialog` disables the action while `unfinishedJobs` is not empty or the stream is not connected, because a job's Cancel lives in the view that started it. After every reconnect `StudioProvider` re-reads each unfinished job with `GET /api/jobs/<id>`: a missed finish is not replayed after a service restart or a full event buffer. A `refreshed` answer applies only while the job is still unfinished here, so a late response cannot undo the stream, and a 404 forgets the job.

## Templates (Phase 09, ADR-0024)
```
result / gallery image ─► Save as Template dialog ─► POST /api/templates/from-image
                                                        └► capture_template(RunRecord, choices) ─► TemplateStore.save
Templates view / Ctrl+K palette / recent chips ─► TemplateUi.run ─► (RunDialog if a required slot is open) ─► POST /api/jobs {recipe, bindings, template: slug}
p11 serve start ─► install_starters(templates/starter/*.json) ─► <config>/templates/ + .starter-installed.json
```
- **Slot inference** (`src/p11/templates/capture.py`, pure): keeps the run's slots, turns bound text into defaults, turns `source_image` into a `source` image slot on the first step with an unset image field (a photo-edit `generate` gets `start_photo`, "Start photo"; a text-to-image `generate` is skipped, Phase 17b), makes the prompt a `prompt` slot only on request, never copies bound files. It is step-type agnostic, so later steps need no change.
- **Starters** (`src/p11/templates/starter.py`): the six recipes live in `templates/starter/` (repo root, like `models/manifest.toml`; `$P11_STARTER_TEMPLATES` overrides). A marker file in the template store remembers installed IDs, so deleted starters stay deleted and edited ones are not overwritten. `GET /api/templates` includes `last_image` (newest gallery image whose template slug matches) for the card thumbnail.
- **Frontend** `features/templates/`: `slots.ts` (pure: missing slots, bindings, remembered inputs in `localStorage`, recents, fuzzy score, placeholder defaults), `ui.tsx` (`TemplateUiProvider`: one place that mounts the Save, Run and Palette dialogs and submits runs; Generate follows template-run jobs through `useTemplateRuns`), `TemplatesView`, `SaveTemplateDialog`, `RunDialog` (picker and drag-and-drop upload through `POST /api/uploads`), `Palette` (Ctrl+K), `TemplateBar` (Generate view chips). `api()` returns `null` for 204 responses.
- **Action counts** (Playwright on the FakeEngine, Appendix B): Save as Template 2, re-run 1, run with one image slot 3.

## Inpainting and the mask editor (Phase 10, ADR-0025)
```
Inpaint view ─► MaskEditor.exportMask() (greyscale PNG at image size) ─► POST /api/uploads?kind=mask
             └► POST /api/jobs {recipe: [inpaint], bindings: {mask}, source_image: gallery/<id> | img-…, parent}
Runner ─► compile ─► EngineGraph(prep=MaskPrep) ─► media.inpaint.prepare(image, mask) ─► engine (working image + soft mask)
       └► media.inpaint.stitch(result) ─► full-size PNG, unmasked pixels = original ─► gallery child (parent_id)
```
- **Step compiler** `src/p11/recipe/steps/inpaint.py` (registered on import of `p11.recipe.compile`): checkpoint (the step's, else the previous generate's, else the default) + its VAE, prompts (empty prompt falls back to the previous generate's), `LoadImage` (slot, previous step or `source_image`), `LoadImageMask` (red channel; from the `mask` slot or the step's inline `mask_png`), `InpaintModelConditioning` (noise mask on), `KSampler` titled `inpaint` with the preset's denoise (`presets.INPAINT_PRESETS`), `VAEDecode`, `ImageCompositeMasked` over the input with the same mask. Core nodes only (S3); all were already in `FakeEngine.KNOWN_NODES`.
- **`MaskPrep`** (`p11.recipe.compile`): pure data on `EngineGraph.prep` naming the image and mask placeholders and the grow/blur/crop/padding/work-size settings. The runner (`p11.jobs.runner._bind`) calls `p11.media.inpaint.prepare` before upload and `stitch` on each output. `prepare` resizes the painted mask to the image, grows it (box blur + threshold) and blurs it (Gaussian) at full resolution, then with `crop` cuts the soft mask's box padded by `padding_px` and scales it so small crops reach `INPAINT_WORK_PIXELS` (1 MP, at most 4×) and big ones fit `INPAINT_MAX_PIXELS` (2560×1440); without `crop` the whole image is used at a multiple of 8. `stitch` scales the result back and blends it over the **original** with the soft mask, so pixels where the soft mask is 0 are byte-identical. An empty mask is refused at submit (`input.mask`, 422).
- **Inline inputs:** `GraphInput.source == "inline"` carries bytes (a template's fixed mask); `GraphInput.kind` tells the runner to upload as `image` or `mask`.
- **Templates:** `POST /api/templates/from-image {…, mask: slot|fixed}`; `fixed` compacts the run's mask (`compact_mask`, greyscale, ≤ 1024 px long side) into the step's `mask_png` and drops the slot; `slot` keeps a `mask` slot (the RunDialog uploads it as `kind=mask`).
- **Frontend:** `features/mask-editor/` (`model.ts` pure history, brush, view, keys; `render.ts` canvas dabs, dirty-box compositing, replay, invert, export; `MaskEditor.tsx`), `features/inpaint/` (`recipe.ts` pure form → recipe, `InpaintView.tsx`). The editor keeps an image-sized mask canvas under a CSS transform (zoom/pan never redraw it); each pointer move draws dabs on a stroke layer and recomposites only their box (snapshot + layer at the stroke's opacity), so opacity does not build up inside a stroke. The box is restored with `clearRect` + `source-over`, never a `copy` draw, because `copy` clears the whole canvas outside the drawn image (the Phase 17a live-stroke fix; `e2e/ui-fixes.spec.ts` reads the canvas pixels in Chromium). Undo replays the history after the last clear. `NavProvider.edit(view, image)` hands an image to an editing view (Phases 11 and 12 reuse it and the editor).
- **Measured:** Playwright on a 2560×1440 photo: 241 pointer moves, draw 0.24 ms average / 4.9 ms max, frames median and p95 16.7 ms (60 fps). Engine timings and preset tuning: `docs/P11_BENCHMARKS.md` → Inpainting.

## Background replacement (Phase 11, ADR-0026, ADR-0027)
```
Background view ─► POST /api/background/mask {image}  ─► auto-mask (greyscale PNG) ─► Refine (MaskEditor.initialMask)
                └► POST /api/background/preview {..., mask} ─► the composite (same pipeline Apply runs)
                └► POST /api/jobs {recipe: [replace_background], bindings: {mask, background}, parent}
Runner ─► compile ─► [LocalStep("replace_background")  + optional EngineGraph tail]
       └► media.composite.run_replace_background: segment (CPU ONNX) → fit/place → colour match →
          edge unmix → feather/shadow → blend → seam band; with `relight` the band is the tail
          inpaint pass's MaskPrep mask (crop-and-stitch keeps everything outside it exact)
```
- **Segmentation (ADR-0026)** `src/p11/media/segment.py`: BiRefNet-lite as ONNX (`onnx-community/BiRefNet_lite-ONNX`, MIT, hash-pinned in the manifest as `birefnet-lite`, opt-in `birefnet` for the full model), run **on the CPU** with ONNX Runtime inside P11. It never touches the GPU, so segmentation and the engine are never resident together (R5) and the Background view can find a subject with the engine stopped. Pre/post-processing follow the repo's `preprocessor_config.json` (1024², ImageNet mean/std; verified at the source, R10). `Segmenters` resolves manifest IDs to files and caches sessions; `StubSegmenter` (a centred ellipse) serves `p11 serve --fake` and tests. The engine-side alternative (ComfyUI's core `LoadBackgroundRemovalModel`/`RemoveBackground` nodes) is recorded in ADR-0026 as the fallback if CPU masks ever feel too slow.
- **Compositing** `src/p11/media/composite.py`: pure geometry (`fit_box`, `place_box`) and colour (sRGB⇄LAB, weighted LAB mean/std transfer at `colour_match_strength`, edge decontamination by unmixing the background from pixels in the feather band) plus the pipeline `run_replace_background(params, inputs, segments)` → `{image, mask}`. The output keeps the subject's size; a flat colour/transparent background writes an RGBA PNG. The `mask` output is the **seam band** (a blurred ring around the subject edge) for the harmonize pass.
- **The local-step driver (ADR-0027):** `compile()` returns `list[PlanItem]`, `PlanItem = EngineGraph | LocalStep`. A `LocalStep` is pure data (op name, params, `GraphInput`s, model IDs) that the runner executes in `p11.media` between engine runs; a step may compile to a local step plus an **engine tail** (`LocalStep.engine`), whose inputs are `GraphInput.source == "local"` (`p11:local:<name>`) fed from the local step's outputs. Only a step's last plan item is saved (the composite is intermediate when the tail runs); `images[step_index]` chaining, sidecars and the gallery are unchanged. Phase 14's `text_overlay` registers a tail-less local step the same way.
- **The harmonize tail:** the Phase 10 inpaint graph (`InpaintModelConditioning` + `KSampler` at `relight_denoise` + `VAEDecode` + `ImageCompositeMasked`) over the seam band with `MaskPrep(image="p11:local:image", mask="p11:local:mask", grow=8, blur=8, crop=True, padding=64)`: the crop-and-stitch keeps every pixel outside the band exact. Core nodes only (S3); the prompts fall back to the recipe's generate step.
- **API:** `POST /api/background/mask` (the auto-mask) and `POST /api/background/preview` (the composite without the harmonize pass, so the stage shows what Apply saves). Both run the CPU work in a worker thread and resolve uploads/gallery refs like the runner does.
- **Templates:** `from-image {mask: auto|slot|fixed}`; `auto` (the default for background runs) sets `mask_mode = "auto"` so each run segments its own subject, `fixed` compacts the mask into `mask_png`, `slot` keeps a `mask` input. The background photo stays a `background_image` slot; a colour background is stored in the step.
- **Frontend:** `features/background/` (`recipe.ts` pure form → recipe + describe recipe + nearest-aspect; `BackgroundView.tsx`), `MaskEditor` gained `initialMask` (the auto-mask is the history's first entry, so Clear/Undo behave). The preview is fetched from `/api/background/preview` debounced per change (the mask is uploaded once per mask change), so geometry, feather, colour match and shadow are always the server's real output.
- **Measured:** segmentation and composite timings, mask IoU and the tuning runs: `docs/P11_BENCHMARKS.md` → Background replacement.

## Face, pose and reference (Phase 12, ADR-0028…0031)

**Faces are P11's own CPU code, not engine work.** `face_swap` and `face_restore` compile to
`LocalStep`s (ADR-0027) and run in `src/p11/media/faces.py`: YuNet (OpenCV's `FaceDetectorYN`)
finds the faces and their five landmarks at two working sizes, ArcFace w600k-r50 turns the source
face into a 512-d embedding, `inswapper_128` swaps it onto the target's aligned face, and GFPGAN
v1.4 optionally restores the result; each is pasted back through the inverse similarity with a
feathered box mask, so pixels away from the face are untouched. Everything is ONNX Runtime on the
CPU: no VRAM taken from the engine (R5), no ComfyUI custom node (S3), and the face path works with
the engine stopped. `FaceKit` caches one session per model file and `p11 serve --fake` uses the
stubs (a coloured ellipse for a swap, a rectangle for a restore).

**The S5 guard is a straight line through every path** (`src/p11/media/nsfw.py`): two classifiers
(both installed, either refusing is enough) run on the target before anything else and again on the
swapped result, and `Runner.validate` refuses at submit time whenever the target is already a file.
The model IDs and thresholds are module constants; `FaceSwap` has no guard field (asserted by
`tests/unit/test_recipe_model.py`) and a test greps the tree for a switch
(`tests/unit/test_media_faces.py`). A missing classifier refuses the swap (`GuardUnavailable`) —
fail closed.

**Gallery references and threads (Phase 17g).** `GalleryIndex` is bound to the event-loop thread, so anything that resolves a `gallery/<id>` runs there. `check_video` runs in a worker thread, so the routes call `queue.check_video_face` first. `POST /api/background/preview` checks `Runner.refs_carry_likeness` on the same thread and, for a likeness picture, passes the composite through `check_likeness` in the worker (ADR-0047).

**Likeness beyond the swap (Phase 16, ADR-0037).** `p11.recipe.likeness.carries_likeness` (pure)
marks a `face_swap` and any `reference` that is not the stock style adapter in `style` mode; the
compiler sets `EngineGraph.likeness`. In `Runner.run` a `likeness` flag starts true when an input
(source image, bound slot or parent) is a gallery image whose sidecar says `likeness` (or whose
recipe carries one), and turns true at the first likeness step; from then on every output passes
`check_likeness` before it is saved, and the run's `RunRecord.likeness` is written to the sidecar so
later edits inherit it. `Runner.validate` calls `faces.guard()` for such jobs, so missing guard
models refuse at submit time. Generation without a likeness never reaches the guard (A5).

**Controls are made in P11 and consumed by the engine.** A `pose` step's slot picture becomes the
control map through `GraphInput.transform` (applied by the runner before upload): `pose` extracts a
body skeleton with DWPose (`media/pose.py`) or takes the pose editor's drawing unchanged,
`depth` runs Depth Anything V2 Small, `canny` is OpenCV Canny(100, 200) (`media/control.py`).
The graph then uses the **core** `ControlNetLoader` → `SetUnionControlNetType` →
`ControlNetApplyAdvanced` with Xinsir's ControlNet-Union SDXL ProMax (`recipe/steps/pose.py`).

**Reference images go through P11's own node pack.** ComfyUI v0.43.0 has no IP-Adapter node, so
`engine/custom_nodes/p11_ipadapter/` provides `P11IPAdapterLoader` and `P11IPAdapterApply`: the
reference picture is encoded by the core `CLIPVisionLoader` + `CLIPVisionEncode` (CLIP ViT-H/14),
projected to 16 cross-attention tokens by the checkpoint's Perceiver resampler, and every
cross-attention layer of the UNet is patched to attend to them as well as to the text. The pack is
P11's own source (MIT), copied into the engine by `scripts/engine_setup.sh` with its SHA-256 checked
against `engine/engine.lock.toml`, and it is the only pack the engine is allowed to load
(`--disable-all-custom-nodes --whitelist-custom-nodes p11_ipadapter`). The layer mapping
(`ip_adapter.N` follows the UNet's **input → output → middle** module order) is verified against
the checkpoint's own per-layer widths at apply time.

**What the UI calls.** `POST /api/face/detect` (faces, largest first, for click-to-pick),
`POST /api/pose/extract` (keypoints from a photo), `POST /api/pose/render` (the OpenPose picture for
a pose); all CPU-only and none of them runs a swap. The Face & Pose view submits ordinary jobs, so
swaps and restores chain, save, index and template like every other step.

## Video face-swap pipeline (Phase 13, ADR-0033, ADR-0034)

**One face path, two media.** The video pipeline (`src/p11/jobs/video.py`) swaps each frame through
the same `p11.media.faces.run_face_swap` as the image step, so the S5 guard runs on every swapped
frame's target and result (ADR-0029) and there is no video-specific swap code that could forget it
(ADR-0034). A sampled pre-pass — about one frame per second plus scene changes (a 32x32 thumbnail
difference) — refuses the whole clip before any swapping; a refusal stops the job and deletes its
scratch frames.

**Media layer** (`src/p11/media/ffmpeg.py`): ffprobe parsing is pure (`parse_probe` on the JSON:
duration, fps with VFR detection, display rotation, audio streams) and every command is an argument
list built by a pure builder and run with `subprocess` (never a shell string, S8). Frames are
extracted as numbered PNGs at a constant rate, upright (auto-rotate on decode); the stitcher
re-encodes H.264 yuv420p (pad-to-even) at the source rate with the clip's own audio — copied for
MP4-compatible codecs, re-encoded to AAC otherwise — and the trim's start offset applied to the
audio input.

**Resume model.** Scratch lives in `~/.cache/p11/jobs/<job>/` (`0700`): `frames/frame_%06d.png`
and `swapped/frame_%06d.png`; the per-frame progress record `<job>.json` sits *next to* that
directory so it survives cleanup. The record stores the stage (`extracted`/`guarded`/`swapped`/
`stitched`), the frame count, the tracked face box and the output path, and is saved after **every**
frame — a crash resumes at the first unfinished frame with no duplicates. A **user** cancel purges
the scratch (`JobControl.cancel(purge=True)`) unless "keep frames" is set; a shutdown or crash never
purges. A resume (`POST /api/video/jobs/{id}/resume`) checks the spec's `render_hash` (which ignores
`resume_of`, `keep_frames` and `confirm_limits`) and continues into the same scratch.

**Jobs.** `jobs.db` grew `kind` and `spec` columns (migration v2): a video job carries a
`VideoSpec` (clip upload, face photo ref, quality, target face, trim, size cap, smoothing,
keep-frames, confirm) instead of a recipe. `JobQueue.submit_video` validates and queues it; the
single worker runs it with the same `JobControl` (cancel + thermal checkpoint between frame batches,
R14) but skips the engine start — the pipeline is CPU work and holds no GPU lock (R24). Progress
goes out as ordinary `progress` events (`step`/`total` = frames done, `title` = stage).

**Limits and output.** R13's 60 s / 1080p defaults warn at upload and at submit with a rough
time estimate and require `confirm_limits`; the hard caps of `p11.media.validate` still apply. The
finished MP4 is written to the R7 layout with a JSON sidecar (`VideoRecord`: source, settings,
frames, timings) and served by `/api/video/jobs/{id}/file` with Range support so a `<video>` player
can seek; it does not enter the image gallery index.

## Text overlay, logo exports and the Models page (Phase 14, ADR-0035)
- **Text overlay.** `recipe/steps/text_overlay.py` registers a plan step that returns one `LocalStep(op="text_overlay")` taking the previous step's image (nothing when the text is empty or `also_prompt_model` is set). `jobs/runner.py::_run_local` calls `p11.media.text.run_text_overlay`; `media/text.py` loads a bundled font (`assets/fonts/fonts.json`, override with `P11_FONTS_DIR`), fits the block to the printable box by binary search, places it by anchor or `x`/`y` and draws shadow, outline and gradient with Pillow. `POST /api/text/preview` runs the same `render_overlay`, so the editor shows what the job saves. Errors (`TextError`) map to `text.invalid`.
- **Logo pack.** `media/logo.py`: cut-out (segmentation from Phase 11, else a border-colour key), square LANCZOS resizes on a transparent canvas, `favicon.ico`; `POST /api/images/{id}/logo-export` returns a ZIP.
- **Models page.** `api/routes/models.py` wraps `ModelManager` (plan, install, verify, add, enable, remove, licences). Installs run in a worker thread, one at a time, and publish `models` events; `models-changed` tells the page to re-read `/api/models`. The UI is `frontend/src/features/models/ModelsView.tsx`; the store keeps `modelOps` and `modelsRev`.
- **Optional steps.** `_Step.skippable_if_unbound` (face swap): `compile()` drops a step whose optional image slot is empty; `previous` only moves when a step produced a plan item.
- **Upscale.** `upscaleRecipe(…, options)` builds `scale` or `width`+`height` and `chain` `model` (Speed) or `latent` (Quality); Generate's Speed/Quality toggle sets `Generate.quality`, which picks the preset's `quality_chain`.

## Installer, update and desktop integration (Phase 15, ADR-0036)
```
install.sh ──► checks (os-release, nvidia-smi ≥ 580) ─► pacman list + ask ─► uv (pinned) ─► 0700 dirs
          ├─► frontend build (npm) ─► uv tool install --editable <checkout>   (python 3.12)
          ├─► scripts/engine_setup.sh (pinned ComfyUI, torch check) ─► p11 models install <set>
          └─► p11 doctor ─► ~/.local/share/applications/p11.desktop + icon (Exec = p11 open)
state: ~/.local/share/p11/install-state   (digests of pyproject/uv.lock and of the engine pin)
p11 update    ─► p11.updater: clean-tree check, fetch tags, CHANGELOG diff, checkout vX.Y.Z, install.sh --yes --models none
p11 uninstall ─► exec uninstall.sh (app, engine, desktop entry, caches; asks about models / config / images)
```
The checkout is the application (editable install), so the lock file, manifest, node pack and built UI need no copies. `install.sh` and `uninstall.sh` are plain bash with `--dry-run`; tests fake `os-release`, `nvidia-smi`, `pacman` and `sudo` through `P11_OS_RELEASE` and `PATH` (`tests/unit/test_install_scripts.py`), and `tests/install/run.sh` runs the whole thing in a stock Arch container with the host GPU. Hyprland integration is opt-in (`--keybinding`) and appends one marked line to the user's `bindings.lua`.
