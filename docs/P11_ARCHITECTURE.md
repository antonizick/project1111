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
| `src/p11/{recipe,templates,outputs,engine,gpu,models,jobs,media}/` | empty packages with docstrings naming the owning phase | skeleton |
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

Quality gates: `make check` (see `CONTRIBUTING.md`); CI runs the same target.

_To be detailed in Phases 04–07 and the Phase 16 threat model._
