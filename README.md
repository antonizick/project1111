# Project_1111 (P11)

P11 is a fully local image-generation system for Omarchy Linux, tuned for a laptop with an 8 GB NVIDIA GPU. **P11 Studio** is its own browser form UI (Vite, React, TypeScript) with a Python service (FastAPI, Typer CLI, SQLite) that drives a pinned, headless ComfyUI engine reachable only on `127.0.0.1`. Planned features: photoreal text-to-image at wallpaper resolutions, one-click templates, inpainting, background replacement with your own photos, face-swap, pose and reference control, short-video face-swap, and a curated, hash-pinned model set.

> **Status: pre-release, under construction.** The repository holds the specification, the implementation plan, the project governance files and the Python/React scaffold (CLI, `/healthz`, placeholder page), the pinned engine with its benchmarks, and the recipe core (recipe schema, presets, recipe → engine graph compiler, output layout and metadata, gallery index, template store), the engine adapter, the model manager, the Studio API with its job queue and `p11 start/stop/status/open/doctor`, and the Studio UI's Generate view, gallery and status bar. Templates, inpainting, background, face/pose, video and the models view are still to come, and there is no installer yet. Progress is tracked in [`P11_IMPLEMENTATION_PLAN.md`](P11_IMPLEMENTATION_PLAN.md).

![P11 Studio: Generate view](docs/images/p11-generate.png)

## Development quick start
```bash
make setup        # uv sync, npm ci, pinned tools (see CONTRIBUTING.md)
make build        # builds the frontend into src/p11/web/
uv run p11 start && uv run p11 open   # Studio in the background, app window with a one-time session link
uv run p11 status / stop / doctor     # state, stop, health checks with fix hints
uv run p11 serve --fake  # foreground, with the FakeEngine and a demo gallery (no GPU or ComfyUI needed)
uv run p11 models list   # curated models and their state; `p11 models install default` (14.4 GB)
make check        # all quality gates (no GPU)
make e2e          # Playwright walkthroughs on the fake engine (action counts, axe, network guard)
```

## Target hardware
- Reference machine: HP Omen laptop, Omarchy (Arch + Hyprland), NVIDIA GeForce RTX 2070 Mobile / Max-Q (8 GB, Turing), driver via `nvidia-open-dkms`, 31 GB RAM.
- Budget: about 7 GB of VRAM for generation; the desktop uses the rest.

## Planned install
```bash
git clone https://github.com/antonizick/project1111.git
cd project1111
./install.sh        # not available yet (Phase 15)
```
The installer will not install GPU drivers, will ask before any `pacman` step, and will not pipe unpinned scripts to a shell.

## Privacy
Everything runs on your machine. The service listens on `127.0.0.1` only, has no telemetry, loads no network assets in the UI, and downloads only the pinned models you approve (spec S1). Your prompts, uploads and outputs are never committed to this repository.

## Content stance
Image generation is unfiltered: P11 makes fictional imagery without a content filter. Face-swap and video face-swap require that you have the consent of the person pictured, and they refuse sexual target material. That guard cannot be turned off (spec S5).

## Documentation
- [Specification](docs/P11_SPECIFICATION.md) (the Amendments section overrides earlier sections)
- [Decisions (ADR log)](docs/P11_DECISIONS.md)
- [Architecture](docs/P11_ARCHITECTURE.md)
- [User guide](docs/P11_USER-GUIDE.md) (outline)
- [Implementation plan](P11_IMPLEMENTATION_PLAN.md)
- [Security policy](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Repository
The repository is **private**: <https://github.com/antonizick/project1111>. It stays private until the owner decides otherwise.

## Licence
MIT, see [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party engine components, custom nodes and models are installed separately under their own licences; some restrict commercial use (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
