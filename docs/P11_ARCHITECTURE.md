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
- **Network ↔ model downloads:** pinned URL, size and SHA-256; safetensors policy; login-free hosts by default.
- **Face-swap paths:** NSFW target guard always on (spec S5, ADR-0005).

## Package map (Phase 02)
| Path | Role | Status |
|---|---|---|
| `src/p11/cli.py` | Typer app: `version`, `paths`, `serve`; stubs `start stop status open doctor models update` | real (stubs print the owning phase) |
| `src/p11/paths.py` | XDG config/data/cache/pictures with `P11_*_DIR` overrides; `ensure_private_dir()` makes `0700` dirs | real |
| `src/p11/config.py` | `Settings` from `~/.config/p11/config.toml` and `P11_*` env; host must be `127.0.0.1` (S1) | real |
| `src/p11/gpulock.py` | `gpu_lock(timeout, holder)`: `flock` on `~/.cache/p11/gpu.lock`, holder info (pid, name, start) readable by waiters (R24) | real |
| `src/p11/api/app.py` | `create_app()`: `GET /healthz`, serves `src/p11/web/` at `/` when built | real (middleware arrives in Phase 07) |
| `src/p11/{engine,gpu,models,jobs,media}/` | empty packages with docstrings naming the owning phase | skeleton |
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
| `scripts/bench/` | bake-off harness (talks to ComfyUI directly; Phase 05 replaces this with `p11.engine`); results in `docs/P11_BENCHMARKS.md`, raw JSON in `~/.cache/p11/bench/runs/` |

Engine defaults (ADR-0009, ADR-0010, ADR-0018): fp16 UNet/text encoders, SDPA attention, fp32 VAE decode (tiled at wallpaper size), ComfyUI's dynamic VRAM by default with `--disable-dynamic-vram --lowvram` as the OOM retry; wallpapers are generated at the native bucket and upscaled with a model upscaler.

## Recipe core (Phase 04)
Everything here is pure or touches the filesystem only through roots passed in (`tests/unit/test_pure_modules.py` checks there are no network imports). ADR-0007, ADR-0019.

| Path | Role |
|---|---|
| `recipe/model.py` | Recipe schema v1 (frozen Pydantic): `Recipe`, `Step` union (`generate`, `upscale`, `inpaint`, `replace_background`, `face_swap`, `pose`, `reference`, `text_overlay`), `Slot`, `SeedStrategy`, `ModelRef`, `FileRef`; cross-checks slot references and `{{slot}}` placeholders |
| `recipe/migrate.py` | `migrate(dict)`, `loads(json)`: version check, `MIGRATIONS[n]` chain, plain-English errors; newer versions refused |
| `recipe/presets.py` | the one preset table: aspect presets (bucket per family, output size, default and Quality chain) and style presets (prompt prefix/suffix, negative, default aspect and model) |
| `recipe/registry.py` | `ModelRegistry` protocol + `ModelInfo`/`SamplerDefaults`; `PROVISIONAL_DEFAULT_SET` (ADR-0018) until Phase 06 |
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

Quality gates: `make check` (see `CONTRIBUTING.md`); CI runs the same target.

_To be detailed in Phases 05–07 and the Phase 16 threat model._
