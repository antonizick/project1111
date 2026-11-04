# P11 Phase 17f: Release v1.0.2

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 17e · **Branch:** `phase-17f-release-1-0-2` · **Worktree:** `../project1111-phase-17f` · **Gate:** review

v1.0.1 carried 17a's interface fixes and 17b's photo edit, but `./install.sh` and `p11 update` kept the first frontend build, so anyone updating from v1.0.0 never saw them (17e). This release ships 17e's fix so that `p11 update` delivers the current interface. Nick pre-authorized it **on one condition**: he has confirmed the four items in his own Studio window (ADR-0044, owner question 23).

## Read first
`CLAUDE.md` (Risk rule, git authority), `prompts/P11_shared-instructions.md`, `prompts/P11_phase-17d-release-1-0-1.md` (the procedure to repeat). Phase Log entries for 17d and 17e. ADR-0040, ADR-0043, **ADR-0044**. `docs/P11_FINAL-REPORT.md`.

## Nick's request (verbatim intent, 2026-11-04 15:07 CST)
Answer to "Should this phase cut v1.0.2 … once you have confirmed the fixes?": "Yes, v1.0.2 after your check".

## Decisions already made
- **ADR-0044:** tag `v1.0.2` and publish the GitHub release on `antonizick/project1111` without an in-session go, **only if owner question 23 is `Answered`** with Nick's confirmation that the four items work in his window. If it is still `Open`, stop and ask (hands-off: block-with-question). Visibility is not changed (the repo is PUBLIC by Nick's own change, owner question 21).

## Goal
`v1.0.2` tagged on the merged `main`, the release page live, and `p11 update` from `v1.0.0` or `v1.0.1` rebuilding the frontend, verified.

## What exists (verified 2026-11-04 15:10 CST; re-check before relying on it)
- Version `1.0.1` in `pyproject.toml`, `uv.lock`, `src/p11/__init__.py`, `frontend/package.json` and its lock. Release `v1.0.1`: https://github.com/antonizick/project1111/releases/tag/v1.0.1.
- 17e fills `CHANGELOG.md` `[Unreleased]`.

## Tasks
1. **Check owner question 23** (must be `Answered`, with Nick confirming). Otherwise stop.
2. **Pre-flight on the branch:** `make check`, `make e2e`, `make gpu-test`, `tests/install/run.sh`. gitleaks over the full history. `git ls-files` holds no weights, tokens or vault notes. A red build blocks.
3. **Version and changelog:** `1.0.2` in all five places. `[Unreleased]` → `## [1.0.2] - <timestamp>`. Compare links `v1.0.1...v1.0.2`. The release notes' first line says that updating from v1.0.0/v1.0.1 now rebuilds the interface.
4. **Final report:** a short "v1.0.2" section (the stale-bundle root cause, the fix, Nick's confirmation).
5. **Merge, timeline, tag, publish** as in 17d (annotated tag, `gh release create v1.0.2 --title "P11 v1.0.2"`, notes from the changelog, latest, no binaries). Record `gh repo view --json visibility` before and after (unchanged).
6. **Post-release check:** a fresh clone at `v1.0.1`, built and installed in a scratch HOME or the container, then `p11 update` to `v1.0.2`. Assert the served bundle's `build-info.json` `source_hash` equals the `v1.0.2` sources and `p11 doctor` says current. On the laptop: `p11 update --dry-run` sees `v1.0.2`.
7. **Hand-off:** the release URL, `p11 update`, and the reminder to reload the app window.

## Out of scope
New fixes (record follow-ups), visibility changes, an instruction-edit model.

## Tests
Task 2 and task 6, with counts in the Phase Log.

## Acceptance criteria
- `v1.0.2` tag and release exist; notes match the changelog; visibility unchanged (timestamps recorded).
- An update from `v1.0.1` ends with a current frontend bundle (task 6 evidence).
- Plan, vault note, final report and timeline updated.

## Phase-specific docs
CHANGELOG, `docs/P11_FINAL-REPORT.md`, README version mentions, vault note. Then the standard close-out checklist.
