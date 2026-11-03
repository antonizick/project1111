# Contributing

P11 is built in numbered phases (see [`P11_IMPLEMENTATION_PLAN.md`](P11_IMPLEMENTATION_PLAN.md)), each described by a prompt in `prompts/`. Agents and people follow the same rules: [`CLAUDE.md`](CLAUDE.md) and [`prompts/P11_shared-instructions.md`](prompts/P11_shared-instructions.md). Start with an issue before a large change.

## Setup
Needs [uv](https://docs.astral.sh/uv/) and Node.js (24 or newer). Nothing is installed into the host Python (3.14); uv manages CPython 3.12 (`.python-version`).

```bash
make setup      # uv sync --locked, npm ci, and `make tools`
make check      # lint + typecheck + tests (no GPU) + audit + gitleaks
```
| Target | What it does |
|---|---|
| `make setup` | `uv sync --locked`, `npm ci` in `frontend/`, then `make tools` |
| `make tools` | Installs gitleaks 8.30.1 at user level (pinned by SHA-256, no sudo, no pacman) into `.tools/bin` unless the right version is already on `PATH` |
| `make fmt` / `make lint` | ruff format + ruff check, prettier + eslint |
| `make typecheck` | `mypy --strict` on `src/p11`, `tsc --noEmit` |
| `make test` | `pytest -m "not gpu and not e2e"`, Vitest |
| `make gpu-test` | `pytest -m gpu`: real-engine tests, **laptop only**, takes the GPU lock (`~/.cache/p11/gpu.lock`) |
| `make e2e` | Builds the frontend, installs Playwright's Chromium to `~/.cache/ms-playwright`, runs the browser smoke test against `p11 serve` |
| `make build` | `vite build` into `src/p11/web/` (git-ignored; served by `p11 serve`) |
| `make audit` | `pip-audit` on the locked dependencies, `npm audit --omit=dev` |
| `make check` | lint, typecheck, test, audit, secrets (what CI and PHX run) |

Run the app: `uv run p11 serve` (`--fake` uses the FakeEngine, no GPU needed; builds first with `make build`), then open <http://127.0.0.1:8111/>. For frontend work use `cd frontend && npm run dev` (proxies `/healthz` to the service).

The git hook set uses pre-commit:
```bash
uvx pre-commit install
uvx pre-commit run --all-files
```
Dev tools are installed at user level without `sudo`; the pre-commit hook calls `gitleaks` from your `PATH`.

## Commits and pull requests
- [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`…), small and focused.
- Add an entry under `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) and update affected docs.
- Tests, lint and type checks must pass (`make check`).
- **No weights, generated outputs, uploads, face photos, videos or other personal media in a PR.** Test faces are synthetic or public-domain with recorded provenance.
- Do not add features, presets, templates or prompts that put a real person's face into sexual content or sexualize minors, and do not weaken the face-swap NSFW guard. This is not negotiable.

By contributing you agree that your contribution is licensed under the MIT licence. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
