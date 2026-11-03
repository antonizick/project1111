# Changelog

All notable changes are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [Semantic Versioning](https://semver.org/). Release headings carry a timestamp (`YYYY-MM-DD HH:MM TZ`).

## [Unreleased]

### Added
- Phase 03: pinned headless ComfyUI v0.43.0 engine (`engine/engine.lock.toml`, hash-locked `engine/requirements.lock.txt`, `extra_model_paths.yaml` template) installed by the idempotent `scripts/engine_setup.sh` into its own uv CPython 3.12 venv with torch 2.14.1+cu130 verified on sm_75; bake-off harness `scripts/bench/`; `docs/P11_BENCHMARKS.md` (native, avatar, wallpaper presets, VRAM modes, 50-run stability, 10-minute thermals, network check); ADR-0018 default model set (RealVisXL V5.0 Lightning, Juggernaut XL v9, fp16-fix SDXL VAE, 4×NomosWebPhoto RealPLKSR; 14.4 GB); ADR-0002/0008/0009/0010 confirmed; `gpu` engine smoke test and bench schema unit test.
- Phase 00: specification with amendments, ADR log, implementation plan, phase prompts, agent rules.
- Phase 01: MIT `LICENSE` and `NOTICE`; `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `THIRD_PARTY_NOTICES.md` skeleton; `.gitignore`, `.dockerignore`, `.editorconfig`; pre-commit with gitleaks and basic hooks; `.github/` (CI with a gitleaks job, issue and PR templates, Dependabot); docs skeleton (`P11_ARCHITECTURE.md`, `P11_USER-GUIDE.md`); private GitHub repository `antonizick/project1111`.
- Phase 02: `p11` package on uv-managed CPython 3.12 (`pyproject.toml`, `uv.lock`); Typer CLI (`version`, `paths`, `serve`, stubs); FastAPI app factory with `/healthz` and static serving; XDG `paths.py`, `config.py` (loopback-only host), advisory `gpulock.py`; Vite + React + TypeScript frontend with Vitest and a Playwright smoke test, built into `src/p11/web/`; `Makefile` (`setup`, `tools`, `lint`, `typecheck`, `test`, `gpu-test`, `e2e`, `build`, `audit`, `check`); CI job running `make check`; Dependabot for uv and npm.
