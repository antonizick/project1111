# Contributing

P11 is built in numbered phases (see [`P11_IMPLEMENTATION_PLAN.md`](P11_IMPLEMENTATION_PLAN.md)), each described by a prompt in `prompts/`. Agents and people follow the same rules: [`CLAUDE.md`](CLAUDE.md) and [`prompts/P11_shared-instructions.md`](prompts/P11_shared-instructions.md). Start with an issue before a large change.

## Setup
Python (uv, CPython 3.12) and frontend (npm) setup commands arrive with the scaffold in Phase 02 and will be filled in here. Until then, the only tooling is the pre-commit hook set:

```bash
uvx pre-commit install     # needs uv; installs the git hook, no host Python packages
uvx pre-commit run --all-files
```
Dev tools are installed at user level without `sudo` (`uv tool install`, or a release binary pinned by version and SHA-256 in `~/.local/bin`). `gitleaks` 8.30.1 is installed that way; the pre-commit hook calls it from your `PATH`.

## Commits and pull requests
- [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`…), small and focused.
- Add an entry under `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) and update affected docs.
- Tests, lint and type checks must pass (`make check` once Phase 02 lands).
- **No weights, generated outputs, uploads, face photos, videos or other personal media in a PR.** Test faces are synthetic or public-domain with recorded provenance.
- Do not add features, presets, templates or prompts that put a real person's face into sexual content or sexualize minors, and do not weaken the face-swap NSFW guard. This is not negotiable.

By contributing you agree that your contribution is licensed under the MIT licence. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
