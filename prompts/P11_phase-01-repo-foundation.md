# P11 Phase 01: Repository foundation & governance

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 00 · **Branch:** `phase-01-repo-foundation` · **Worktree:** `../project1111-phase-01` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §1, §7 and §11 (all of the Amendments, especially A3, A4, S1–S10, §11.4). Phase Log entry for 00. ADR-0003, ADR-0004, ADR-0005, ADR-0012, ADR-0013. Owner question 2 (repo name; proposed default `antonizick/project1111`, private: use it unless Nick has answered otherwise).

## Goal
The repository is ready to be published later without rework: governance files, ignore rules that make it hard to commit weights, outputs, personal media or the vault source notes, a secret scan, GitHub templates and CI stubs, a docs skeleton, and a **private** GitHub remote with `main` pushed. No product code yet.

## Tasks
1. **LICENSE** (MIT, copyright 2026, holder = `git config user.name`; ask Nick if it is unset) and **NOTICE** (project name, MIT, that third-party engine components, custom nodes and models are installed separately under their own licences and are not distributed in this repo).
2. **README.md**: what P11 is (one paragraph, from spec §1 and CLAUDE.md), status "pre-release, under construction", target hardware, the planned install (`git clone … && ./install.sh`, R15), privacy stance (S1), the content stance in neutral wording (unfiltered generation of fictional imagery; face-swap requires consent and refuses sexual targets, S5), links to the docs, licence. No screenshots yet. Don't use trademarked names for presets (R17).
3. **SECURITY.md** (private reporting via GitHub security advisories; the scope: localhost service, installer, model downloads, supply chain), **CONTRIBUTING.md** (uv/npm setup placeholders filled in Phase 02, Conventional Commits, phase method pointer, "no weights, outputs or personal media in PRs"), **CODE_OF_CONDUCT.md** (Contributor Covenant 2.1: fetch the official text, don't write it from memory), **CHANGELOG.md** (Keep a Changelog, `[Unreleased]` with this phase's entries).
4. **THIRD_PARTY_NOTICES.md** skeleton: tables for engine components, custom nodes, Python/npm dependencies and models (name, version/commit, licence, URL, flags such as non-commercial), each "to be filled by Phase 03/06/12/16".
5. **.gitignore**: Python, node, `src/p11/web/`, `.env*`, `*.safetensors *.ckpt *.pt *.pth *.bin *.gguf *.onnx`, `models/*` except `models/manifest.toml`, `outputs/ inputs/ scratch/ *.mp4 *.mov *.webm`, `engine/ComfyUI/` and any engine checkout, `.cache/`, and the two vault notes `Plan Draft.md` and `Brainstorming Project 1111.md` (ADR-0004; keep the line Phase 00 added). **.dockerignore** to match. **.editorconfig** (utf-8, LF, 4 spaces Python, 2 spaces TS/JSON/YAML/TOML, final newline).
6. **Secret scanning:** `.pre-commit-config.yaml` with gitleaks (pinned rev, verified at its repo) plus basic hooks (trailing whitespace, end-of-file, check-added-large-files with a 5 MB cap, check-merge-conflict). Install the hook locally (`uv tool run pre-commit install` or equivalent, no host Python packages).
7. **.github/**: `workflows/ci.yml` (gitleaks job now; Python and frontend jobs added in Phase 02; minimal permissions, pinned action SHAs verified at their repos), `ISSUE_TEMPLATE/` (bug report asking for GPU/driver/VRAM, `p11 doctor` output and **no personal images**; feature request), `PULL_REQUEST_TEMPLATE.md` (checklist: tests, docs, changelog, no weights/media), `dependabot.yml` (github-actions now; pip/uv and npm noted for Phase 02).
8. **Docs skeleton:** `docs/P11_ARCHITECTURE.md` (component diagram in text: browser → Studio API → job runner → Engine adapter → ComfyUI on 127.0.0.1; data locations R8; trust boundaries), `docs/P11_USER-GUIDE.md` (outline only), `docs/images/.gitkeep`.
9. **GitHub remote:** check that the name from owner question 2 isn't already taken (`gh repo view`), then `gh repo create antonizick/project1111 --private --source . --remote origin` (or the answered name) and push `main`. Never `--public` (A3). Record the URL in README and the vault note.

## Out of scope
Python/frontend code, CI test jobs (02), engine and models (03, 06), installer (15).

## Tests
`pre-commit run --all-files` passes; `git check-ignore -v "Plan Draft.md" "Brainstorming Project 1111.md" x.safetensors outputs/a.png` reports each as ignored; a test commit of a fake 6 MB file is refused by the hook (then removed); CI workflow passes on GitHub (check with `gh run list`).

## Acceptance criteria
- Every file listed in spec §11.4 exists and is accurate for the current state.
- `git ls-files` contains neither source note nor any weight/media extension.
- The GitHub repo exists, is **private** (`gh repo view --json visibility`), and `main` is pushed; CI is green.

## Phase-specific docs
README, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, CHANGELOG, NOTICE, THIRD_PARTY_NOTICES, `docs/P11_ARCHITECTURE.md`, `docs/P11_USER-GUIDE.md`, owner question 2 marked Decided with a timestamp. Then the standard close-out checklist.
