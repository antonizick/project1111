# Shared Instructions for Every Phase

Read this file in full before starting any phase. Each phase prompt assumes it.

**Phase IDs.** `NN` in this file is the phase ID: two digits, optionally with a lower-case letter suffix for a phase inserted after another one with `/phase-add` (`09a`, `15a`, `15b`…). An inserted phase is a normal phase with its own claim, branch and worktree; `15a` sorts after `15` and before `16`.

## 1. Orientation and claim (every phase, before writing code)
1. Read `CLAUDE.md`, `P11_IMPLEMENTATION_PLAN.md` (including the Phase Log and Owner questions) and the spec sections named in your phase prompt. Always read the Amendments.
2. Confirm that every phase listed under "Depends on" is `✅ Complete`. If one is not, stop and tell Nick.
3. Read the Phase Log entries of the dependency phases; they may record deviations that change what you build.
4. If an owner question this phase needs is still open, ask Nick before doing the affected work. (Hands-off mode: block-with-question, §1b.)
5. **Claim the phase on `main`** by following §1a. This is the first file change of every phase session. Do not start the Tasks until the claim is verified.
6. If the prompt is ambiguous or contradicts the spec, prefer the spec's Amendments. If it is still unclear, ask Nick before guessing on anything user-visible or hard to reverse. (Hands-off mode: block-with-question, §1b.)

## 1a. Claiming a phase (mandatory; other agents may be running in parallel)
Nick and other agents read the Status column from `main`. A status change made only on a phase branch, or left uncommitted in a worktree, is invisible to them. So every phase is claimed with a commit on `main` **before** any other work.
1. In the main checkout (`/home/nick/Work/project1111`), check that `git branch --show-current` prints `main` and that `git status --short P11_IMPLEMENTATION_PLAN.md` prints nothing. If either check fails, stop and tell Nick. Never commit another agent's uncommitted changes.
2. Look for an existing claim: the phase's row on `main`, `git branch --list 'phase-NN-*'` and `git worktree list`. If the row is already `🔄 In progress`, or a branch or worktree exists, do not claim again; follow the resume rules in `/phase`.
3. Set the phase's Status cell to `🔄 In progress`, then commit **only that file** to `main`: `git commit -m "chore(plan): start phase NN" -- P11_IMPLEMENTATION_PLAN.md`.
4. In the Obsidian project note, set the phase's row to `🔄 In progress`, update its `updated:` field and add a timestamped log line: "Phase NN started (claim commit `<hash>`, branch `phase-NN-<slug>`, worktree `../project1111-phase-NN`)".
5. Create the worktree and branch from that commit: `git worktree add ../project1111-phase-NN -b phase-NN-<slug> main`, then install the project's dependencies inside it if it has any. Do all of the phase's work in the worktree, using absolute paths or `cd <worktree> && …` in every command, because the shell may reset to the main checkout between commands. Never switch the main checkout off `main`: other agents commit their claims there.
6. Verify: `git show main:P11_IMPLEMENTATION_PLAN.md | grep '^| NN '` must show `🔄 In progress`.

If the phase ends `⛔ Blocked`, commit that status to `main` the same way (`chore(plan): phase NN blocked`) so that `main` doesn't show a stale `🔄`. A `✅ Complete` status reaches `main` through the merge.

## 1b. Hands-off mode: block-with-question (PhaseHypervisor contract 1)
Applies only in hands-off mode (`/phase NN --auto` or `PHX_AUTO=1`, set only by PhaseHypervisor); manual sessions ignore this section. Wherever a manual session would ask Nick (an open owner question this phase needs, an ambiguity you must not guess, the risk rule in `CLAUDE.md`, or a failure you cannot fix within scope), do this instead, then end the session:
1. In the worktree, commit all work on the phase branch: `wip(phase-NN): blocked, <short reason>`. Do not merge; keep the branch and worktree.
2. In the main checkout, in `P11_IMPLEMENTATION_PLAN.md`:
   - add an Owner questions row `| <next #> | <question> | Open (asked <TS>, Phase NN, auto mode). Proposed default: <default> | Phase NN |` (or, for an existing open question, name this phase in its Status cell and keep it `Open`);
   - set the phase's Status to `⛔ Blocked`;
   - add a Phase Log entry `### <TS>: Phase NN: <title> (⛔ Blocked)` with bullets: `- **Timeline:** started <claim TS> (claim commit <hash>) · blocked <TS> to (open)`, then `- **Model:** …`, then `- **Question:** #<id>: <question>`, then what is done, what remains and where to resume.
3. Commit only that file to `main`: `git commit -m "chore(plan): phase NN blocked" -- P11_IMPLEMENTATION_PLAN.md`, and push `main` if a remote exists.
   Then refresh the timeline on `main` (§4a) in its own commit, `docs(plan): refresh timeline`.
4. In the Obsidian note: row `⛔ Blocked`, `updated:` field, and a timestamped log line naming the question.
5. Final message: what was done, the question and its proposed default, then the `PHX-RESULT` line with `"status":"blocked"` and the question IDs (see `/phase`).

A question is **open** while its Status cell starts with `Open`; `Answered …`, `Decided …` and `Deferred …` are not open.

**Resuming** a `⛔ Blocked` phase in hands-off mode: if a question needed by it is still open, refuse without changing anything. Otherwise set the row to `🔄 In progress`, change `blocked <TS> to (open)` to `blocked <TS> to <TS now>` in its Timeline, commit only the plan file to `main` (`chore(plan): resume phase NN`), refresh the timeline on `main` (§4a) as `docs(plan): refresh timeline`, update the Obsidian note, then run `git merge main` in the worktree, read the answer and continue as a normal resume.

## 2. Target repository layout (evolves; keep `docs/P11_ARCHITECTURE.md` in sync)
```
project1111/
├── CLAUDE.md  README.md  LICENSE  NOTICE  SECURITY.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md
├── CHANGELOG.md  THIRD_PARTY_NOTICES.md  .gitignore  .dockerignore  .editorconfig
├── P11_IMPLEMENTATION_PLAN.md            (prefixed)
├── install.sh  uninstall.sh              (Phase 15)
├── pyproject.toml  uv.lock  Makefile  .python-version  .pre-commit-config.yaml
├── src/p11/
│   ├── cli.py              Typer: serve/start/stop/status/open/doctor/models/update
│   ├── config.py  paths.py XDG paths (spec R8), settings
│   ├── gpulock.py          advisory GPU lock (R24)
│   ├── recipe/             pure: schema, versions, migrations, presets, compiler → ComfyUI graphs
│   ├── templates/          template store (JSON), import/export
│   ├── outputs/            output layout, sidecar + PNG metadata, SQLite gallery index
│   ├── engine/             Engine protocol, ComfyUI client, FakeEngine, process supervisor
│   ├── gpu/                NVML / nvidia-smi telemetry, thermal guard
│   ├── models/             manifest loader, downloader, verification, registry
│   ├── jobs/               job queue, step runner, video pipeline
│   ├── media/              image/video validation, ffmpeg wrappers, text overlay
│   ├── api/                FastAPI app, middleware, routes/
│   └── web/                built frontend (generated, git-ignored)
├── frontend/               Vite + React + TypeScript; src/features/{generate,gallery,templates,inpaint,background,face,video,models}
├── engine/
│   ├── engine.lock.toml    pinned ComfyUI + custom node SHAs, torch build (Phase 03)
│   └── extra_model_paths.yaml.tmpl
├── models/manifest.toml    curated set, no weights (Phase 06)
├── templates/              starter templates (Phase 09/14)
├── assets/fonts/           open-licence fonts for text overlay (Phase 14)
├── scripts/phase_timeline.py   scripts/bench/
├── tests/                  unit/  integration/  gpu/  e2e/  fixtures/ (synthetic only)
├── docs/
│   ├── P11_SPECIFICATION.md  P11_DECISIONS.md  P11_ARCHITECTURE.md  P11_BENCHMARKS.md   (prefixed)
│   ├── P11_USER-GUIDE.md  P11_THREAT-MODEL.md  P11_FINAL-REPORT.md  P11_TIMELINE.svg      (prefixed)
│   └── images/
└── prompts/                P11_shared-instructions.md, P11_phase-NN-*.md, P11_change-request-template.md (prefixed)
```
Not in git: `Plan Draft.md`, `Brainstorming Project 1111.md` (vault notes, ADR-0004), weights, outputs, uploads, scratch, `.env`, `src/p11/web/`.

## 3. Conventions
- **Prefix.** Project documents carry the project prefix `P11_` (see `CLAUDE.md`). New project-specific documents follow the same rule; convention-bound files (`README.md`, `LICENSE`, `CHANGELOG.md`, `CLAUDE.md`…) keep their names.
- **Timestamps, not dates.** Every place that records when (Phase Log, ADRs, amendments, owner questions, vault log, "Last updated", changelog release headings) uses `YYYY-MM-DD HH:MM TZ`. Run `date '+%Y-%m-%d %H:%M %Z'` when you write each one; do not guess or copy an earlier timestamp.
- **Python:** 3.12 via uv (never the host 3.14), `src/` layout, full type hints (`mypy --strict` on `src/p11`), ruff format + lint, pytest. Pure logic has no I/O; I/O sits behind protocols with fakes.
- **Frontend:** React + TypeScript strict, ESLint, Vitest + Testing Library, Playwright for e2e; no network assets (S1); keyboard-reachable controls with visible focus.
- **Engine access** only through `p11.engine.Engine`; nothing else imports the ComfyUI client. Real-engine tests carry `@pytest.mark.gpu` and take the GPU lock (`p11.gpulock`, R24).
- **No facts from memory.** Model names, URLs, hashes, versions, licences and node names are verified at the source (fetch the page, read the repo, check the file) before they go into code, the manifest or docs; record where and when you checked.
- **Private data.** Never put uploads, outputs, face photos, videos or weights in the repo, fixtures, logs or commit messages (S6). Test faces are synthetic or public-domain with recorded provenance.
- **Content boundary (S5).** Never weaken or bypass the face-swap NSFW guard, and never add presets, templates or prompts that place real people into sexual content or sexualize minors. This is not open to a phase's judgment or to a change request.
- **Errors** shown to the user are plain English with a hint (e.g. "Out of GPU memory: P11 retried with low-memory mode. Try a smaller preset.").
- **Commits:** Conventional Commits, small checkpoints, explicit paths when staging (`git add <paths>`, never `git add -A` in the main checkout).

## 4. Phase close-out checklist (all items required)
- [ ] All acceptance criteria in the phase prompt are met, with a short verification note for each.
- [ ] Tests, lint and type checks pass: `make check` (ruff, mypy, pytest `-m "not gpu"`, frontend lint/typecheck/test, gitleaks); on the laptop also `make gpu-test` when the phase touched engine-facing code. (Before Phase 02 exists: the checks the prompt names.)
- [ ] `P11_IMPLEMENTATION_PLAN.md`: Status set (`✅ Complete` or `⛔ Blocked`, icon plus word; a `⛔ Blocked` status is also committed to `main` per §1a), Phase Log entry added (timestamp, summary, deviations, follow-ups, test counts).
- [ ] **Timeline bullet written** as the first bullet of the Phase Log entry: *started* = the claim commit's time (`git log -1 --format=%cd --date=format-local:'%Y-%m-%d %H:%M %Z' <claim hash>`), *finished* = `date '+%Y-%m-%d %H:%M %Z'` taken as the last step before the final commit, *merged* = the merge time or `not merged yet`, plus `blocked <TS> to <TS>` for any `⛔` interval. Never reuse an earlier timestamp.
- [ ] `CHANGELOG.md` `[Unreleased]` updated (a release heading carries a timestamp, not just a date).
- [ ] README, SECURITY, `P11_ARCHITECTURE`, guides, THIRD_PARTY_NOTICES, ignore files updated where affected.
- [ ] ADR added for any notable choice (timestamped in both the entry and its row in the index table at the top of `docs/P11_DECISIONS.md`); spec amendment added if the spec changed.
- [ ] Later phase prompts corrected if your work changed their assumptions.
- [ ] Obsidian project note updated (status icons, `updated:` field and a timestamped log line).
- [ ] OS-modification log (`/home/nick/Documents/04 Resources/OSMods/`) updated if the host system was modified.
- [ ] Work committed on the phase branch. Once the phase is `✅ Complete` and every check passes, merge it into `main` without asking (fast-forward where possible), from the main checkout. Conflicts in `P11_IMPLEMENTATION_PLAN.md` and the changelog are expected when phases ran in parallel: keep every row and entry from both sides, and use the branch's final status for this phase's row. Then push `main` if a remote exists (create a **private** GitHub repo if the plan calls for one), `git worktree remove ../project1111-phase-NN` and `git branch -d phase-NN-<slug>`. Do not merge a `⛔ Blocked` phase or one with failing checks. Making a repo public or publishing a release needs Nick's explicit confirmation (hands-off mode: block-with-question, §1b).
- [ ] **Timeline refreshed on `main`** after the merge (§4a), committed as `docs(plan): refresh timeline` and pushed.
- [ ] Final message to Nick: what was built, how to try it, what's next, and any open questions. In hands-off mode, its last line is the `PHX-RESULT` line (see `/phase`).

## 4a. Visual timeline (`scripts/phase_timeline.py`)
The plan's `## Timeline` block, `docs/P11_TIMELINE.svg`, the vault note's timeline and the final report's timeline (once it exists) are generated. Refresh them **only on `main`, never on a phase branch**, so parallel branches never conflict over them:
`python3 scripts/phase_timeline.py --write --vault-note "/home/nick/Documents/02 Projects/P11 Implementation Plan.md"`, then commit the plan, the SVG and the final report (if present) together: `docs(plan): refresh timeline`.
- When: after the merge at close-out, after the `⛔` commit (§1b) and after the resume commit. The claim commit stays status-only; the new bar appears at the next block, resume or close-out.
- If the block or the SVG ever conflicts, take either side and re-run `--write`; never merge it by hand.
- `python3 scripts/phase_timeline.py --check` exits 1 when the outputs are stale (right after a claim this is expected).
