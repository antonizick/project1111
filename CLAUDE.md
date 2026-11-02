# Project_1111: Agent Instructions

These rules apply to every AI agent working in this repository. They are **mandatory**.

## What this project is
Project_1111 (P11) is a fully local image-generation system for Omarchy Linux, tuned for an 8 GB RTX 2070 Mobile laptop. **P11 Studio** is the product's own browser form UI (Vite + React + TypeScript) and Python service (FastAPI, Typer CLI, SQLite, Python 3.12 via uv). It drives a **headless ComfyUI** engine, pinned and reached only on 127.0.0.1. Features: photoreal text-to-image at wallpaper resolutions, one-click templates (P11 recipes compiled to engine graphs), inpainting, background replacement with photos, face-swap, pose and reference control, short video face-swap, and a curated, hash-pinned model set. It is installed with `./install.sh`. Generation is unfiltered; the face-swap paths keep an NSFW target guard (spec S5).

## Naming and timestamps (mandatory)
- **Project prefix: `P11`.** Project documents are named `P11_<NAME>` (`P11_IMPLEMENTATION_PLAN.md`, `docs/P11_DECISIONS.md`, `prompts/P11_phase-NN-<slug>.md`…) so they can be told apart from other projects' documents without their path. Any new project-specific document gets the prefix. `CLAUDE.md`, `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md` and the like keep their conventional names.
- **Timestamps everywhere a date is recorded** (Phase Log, ADRs, amendments, owner questions, vault log, "Last updated"): `YYYY-MM-DD HH:MM TZ`, from `date '+%Y-%m-%d %H:%M %Z'` at the moment you write it. Never a bare date, never guessed.

## Source-of-truth documents (read before working)
| File | Purpose |
|---|---|
| `docs/P11_SPECIFICATION.md` | Canonical spec. **The Amendments section overrides earlier sections.** |
| `P11_IMPLEMENTATION_PLAN.md` | Phase table, status, owner questions, phase log. **Keep it accurate.** |
| `prompts/P11_shared-instructions.md` | Conventions and close-out checklist for every phase |
| `prompts/P11_phase-NN-*.md` | The prompt for the phase you are executing (start sessions with `/phase`) |
| `docs/P11_DECISIONS.md` | ADR log; append, never rewrite |

## Mandatory documentation upkeep
Documentation is part of the deliverable. A phase is **not complete** until all of the following are done:
1. `P11_IMPLEMENTATION_PLAN.md`: set the phase's status as icon plus word (`🔄 In progress` when you start; `✅ Complete` or `⛔ Blocked` at the end) and add a timestamped Phase Log entry whose **first bullet is the Timeline** (`started` = the claim commit's time, `finished` = `date` as your last step, `merged`, any `blocked` interval; format in the plan's Phase Log header), then built, deviations, follow-ups, tests. **`🔄 In progress` must be committed to `main` before any other work** (the claim protocol in `prompts/P11_shared-instructions.md` §1a), because parallel agents read the status from `main`. A status that exists only on a phase branch or in a worktree does not count.
2. `CHANGELOG.md`: add entries under `[Unreleased]`.
3. Update every affected document: README, SECURITY, `docs/P11_ARCHITECTURE.md`, guides, THIRD_PARTY_NOTICES, `.gitignore` / `.dockerignore`.
4. `docs/P11_DECISIONS.md`: add an ADR for any non-trivial choice or deviation. If the spec changes, add an amendment.
5. **Later phase prompts:** if your work changes an assumption a later prompt relies on, edit that prompt.
6. The Obsidian project note `/home/nick/Documents/02 Projects/P11 Implementation Plan.md`: update the status table (icons), the `updated:` field and add a timestamped log line.
7. Any host OS change must also be documented in `/home/nick/Documents/04 Resources/OSMods/` (read its README first).

## Risk rule (mandatory)
Sessions may run with bypassed permissions. **If an action looks high-risk, irreversible or a bad idea, stop and ask Nick instead of doing it.** In an interactive session, ask. In a hands-off session (`/phase NN --auto` or `PHX_AUTO=1`, started by PhaseHypervisor), block the phase with the question recorded (block-with-question, `prompts/P11_shared-instructions.md` §1b). Examples: deleting data you did not create, touching another project's files outside the scope your prompt names, changing system-wide config not covered by the prompt, spending money beyond a stated cap, making a repo public, publishing a release, force-pushing shared history. Project-specific examples: installing or changing NVIDIA drivers, CUDA or kernel modules; `sudo` of any kind beyond a prompt's named pacman packages; downloading beyond the budget in owner question 1; deleting anything under `~/Pictures` or the models directory that P11 did not create.

## Content boundary (mandatory)
Generation stays unfiltered (spec A5). The face-swap and video face-swap NSFW target guard stays on and cannot be configured off (spec S5, ADR-0005). Never add a feature, preset, template, prompt or test that puts a real person's face into sexual content, or anything that sexualizes minors. This rule is not changed by phase prompts or change requests.

## Engineering rules
- Stay within the phase's scope; record out-of-scope findings as follow-ups in the Phase Log.
- Tests, lint and type checks must pass before a phase closes. `make check` (ruff, mypy, pytest `-m "not gpu"`, frontend lint/typecheck/test, gitleaks); `make gpu-test` on the laptop for engine-facing changes.
- Never commit secrets, personal data, private recordings, model weights or `.env` files. Never stage `Plan Draft.md` or `Brainstorming Project 1111.md` (ADR-0004).
- Follow the security and privacy baseline in the spec's Amendments.
- Pin and lock dependencies, and check licences before adding one. ComfyUI and custom nodes are pinned by commit in `engine/engine.lock.toml`; adding a custom node needs an ADR (S3).
- Never use the host Python 3.14 for project code; use the uv-managed interpreter (R1).
- Real-engine work takes the GPU lock (`~/.cache/p11/gpu.lock`, R24); never leave an engine process running at the end of a session.
- Git: branch `phase-NN-<slug>` in its own worktree `../project1111-phase-NN`; the main checkout stays on `main`. Conventional Commits, commit at checkpoints. **Git authority (standing instruction from Nick):** commit, merge, push and create **private** GitHub repos without asking, at checkpoints and at close-out. Only making a repo **public**, publishing a GitHub **release**, or force-pushing shared history needs Nick's explicit confirmation (in hands-off mode: block-with-question). If an action looks high-risk or a bad idea, stop and ask anyway.
- Reference machine: HP Omen laptop (`omen`), Omarchy (Arch + Hyprland), kernel 7.2.8-9-omarchy; NVIDIA GeForce RTX 2070 Mobile / Max-Q (TU106BM, Turing sm_75, 8 GB, ~1 GB used by the desktop), driver 615.78.08 (`nvidia-open-dkms`), CUDA 13.4; 31 GB RAM; ~590 GB free on `/home`; host Python 3.14.8, uv 0.13.0, node 26.8.1, Docker 29.9.2 with nvidia-container-toolkit 1.20.1, ffmpeg 9.0.2, gh 2.103.2 (all verified 2026-11-02 13:08 CST). The repo folder is also inside Nick's Obsidian vault (`/home/nick/Work` is mounted at `Documents/02 Projects/Work`).
