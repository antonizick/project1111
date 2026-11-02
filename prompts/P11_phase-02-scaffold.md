# P11 Phase 02: Python + React scaffold, toolchain & CI

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 01 · **Branch:** `phase-02-scaffold` · **Worktree:** `../project1111-phase-02` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md` (§2 layout, §3 conventions), spec §11.2 R1, R8, R19, R20, R21, R24 and §11.3 S1, S2, S3, S10. Phase Log entries for 00 and 01. ADR-0008, ADR-0013, ADR-0014.

## Goal
A working, empty skeleton that every later phase builds on: the `p11` Python package on uv-managed CPython 3.12, a Typer CLI, a FastAPI app with `/healthz`, a Vite + React + TypeScript frontend built into the package, XDG paths and settings, the GPU lock helper, and one `make check` that runs every quality gate locally and in CI.

## Tasks
1. **Python toolchain:** `.python-version` = 3.12; `uv python install 3.12` if needed (never the host 3.14, R1); `pyproject.toml` (`src/` layout, package `p11`, console script `p11 = p11.cli:app`, hatchling or uv_build backend), dependencies: fastapi, uvicorn[standard], pydantic, pydantic-settings, typer, httpx, websockets, pillow; dev: pytest, pytest-asyncio, pytest-cov, ruff, mypy, pip-audit. `uv lock` committed. Verify each package's current version and licence at PyPI before pinning.
2. **Package skeleton** per shared-instructions §2: empty modules with docstrings for `recipe/`, `templates/`, `outputs/`, `engine/`, `gpu/`, `models/`, `jobs/`, `media/`, `api/`. Real code now only in:
   - `paths.py`: XDG resolution of config/data/cache/pictures per R8 (`P11_*` env overrides for tests), `ensure_private_dir()` creating `0700` dirs;
   - `config.py`: `Settings` (pydantic-settings, `~/.config/p11/config.toml`): host `127.0.0.1` (not configurable to `0.0.0.0` in v1, S1), studio port, engine port, models root, outputs root, thermal thresholds (placeholders; owner question 5);
   - `gpulock.py`: `gpu_lock(timeout, holder)` context manager using `fcntl.flock` on `~/.cache/p11/gpu.lock`, writing holder info (pid, phase/session, start time) so a waiter can say who holds it (R24, ADR-0014);
   - `cli.py`: Typer app with `version`, `paths` (prints resolved paths) and stub commands `serve start stop status open doctor models update` that say "not implemented yet (Phase NN)";
   - `api/app.py`: `create_app()` with `GET /healthz` → `{"status":"ok","version":…}`; `p11 serve` runs it with uvicorn on 127.0.0.1.
3. **Frontend:** `frontend/` with Vite + React + TypeScript (strict), ESLint, Prettier, Vitest + Testing Library, Playwright installed but with one smoke test. A placeholder page that calls `/healthz`. `vite build` outputs to `src/p11/web/` (git-ignored); FastAPI serves it as static files at `/`. No external fonts, CDNs or analytics (S1). Verify current versions at npm before pinning; commit `package-lock.json`.
4. **Makefile:** `setup` (uv sync, npm ci), `fmt`, `lint` (ruff, eslint), `typecheck` (mypy --strict src/p11, tsc --noEmit), `test` (pytest -m "not gpu", vitest), `gpu-test` (pytest -m gpu, laptop only), `build` (frontend build), `audit` (pip-audit, npm audit --omit=dev), `check` = lint + typecheck + test + audit + gitleaks. Tools without a PyPI/npm package (gitleaks, shellcheck if used) are installed at user level by a `make tools` target, pinned by version and SHA-256 (spec H4; no sudo, no pacman), and documented in CONTRIBUTING. `make setup` must work on a fresh clone with nothing installed (uv sync, `npm ci`, `make tools`), because PHX verifies every phase with `scripts/phx_verify.sh` (`.phx/config.toml`: `make setup && make check` on a clean clone of `main`); keep that script working and keep GPU tests out of `make check`. pytest markers `gpu`, `slow`, `e2e` registered; `gpu` tests skipped automatically when no NVIDIA GPU is present.
5. **CI:** extend `.github/workflows/ci.yml` with Python (uv, cached) and frontend jobs running `make check` minus GPU; Dependabot for uv/pip and npm. Keep action SHAs pinned.
6. **Tests:** paths (env overrides, 0700 creation), settings defaults and rejection of a non-loopback host, GPU lock (two processes contend; second waits or times out with the holder named), `/healthz`, CLI `version`/`paths`, a Vitest render test, a Playwright smoke test against `p11 serve` (local only, marked `e2e`).
7. Update CONTRIBUTING (setup and `make` targets), README (dev quick start), `docs/P11_ARCHITECTURE.md` (package map).

## Out of scope
Any engine, model, recipe or UI feature work (03 onwards).

## Tests
As in task 6; `make check` green locally and in CI.

## Acceptance criteria
- `uv run p11 serve` serves the placeholder UI and `/healthz` on `127.0.0.1` only (`ss -ltnp` shows no `0.0.0.0` listener).
- `uv run python -c 'import sys; print(sys.version)'` prints 3.12.x; nothing was installed into the host Python.
- `make check` passes locally and CI is green on the pushed branch.

## Phase-specific docs
CONTRIBUTING, README dev section, `docs/P11_ARCHITECTURE.md`, ADR-0008 updated (P11 side Accepted, engine side still for Phase 03), CHANGELOG. Then the standard close-out checklist.
