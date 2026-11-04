# P11 Phase 17d: Release v1.0.1

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 17a, 17b, 17c · **Branch:** `phase-17d-release-1-0-1` · **Worktree:** `../project1111-phase-17d` · **Gate:** review

The first feedback round after v1.0.0 (17a editor and layout fixes, 17b photo edit, 17c OCC integration) ships as **v1.0.1**. Nick pre-authorized this release (ADR-0040): tag it and publish the GitHub release **without asking**, then Nick tests it right after. The Gate is `review` only so that a hands-off run pauses *after* the release for that test; it does not gate the publish.

## Read first
`CLAUDE.md` (Risk rule, git authority), `prompts/P11_shared-instructions.md`, `prompts/P11_phase-17-release.md` (the v1.0.0 procedure to repeat), spec §11.6 H13. Phase Log entries for 17, 17a, 17b, 17c. ADR-0016, **ADR-0040**. `docs/P11_FINAL-REPORT.md`, `docs/P11_PUBLICATION-READINESS.md`.

## Nick's request (verbatim intent, received by 2026-11-04 07:40 CST)
"Yes add a v1.0.1 release to auto release and publish to GitHub no approval from me (user owner) needed I will test immediately after the publication"

## Decisions already made
- **ADR-0040:** v1.0.1 is tagged and published as a GitHub release on `antonizick/project1111` with no in-session "go?" (this release only). **Repo visibility is not changed**: the repo stays as it is (private at 2026-11-04 07:40 CST, per the Phase 17 log). Making it public is still a separate, explicit owner decision (Phase 17 log), never inferred from "publish".
- Version number `1.0.1` is Nick's choice, although 17b adds a feature (SemVer would say 1.1.0); use 1.0.1 and say so in the release notes' first line only if 17b shipped.

## Goal
`v1.0.1` tagged on the merged `main`, the GitHub release page live with changelog notes, the installer able to update to it, and Nick told it is ready to test.

## What exists (verified 2026-11-04 07:40 CST; re-check before relying on it)
- Version `1.0.0` in `pyproject.toml`, `uv.lock`, `src/p11/__init__.py`, `frontend/package.json` and its lock (Phase 17 log). `CHANGELOG.md` has `## [1.0.0] - 2026-11-03 21:20 CST` and an `[Unreleased]` section that 17a–17c fill.
- Release `v1.0.0` exists: https://github.com/antonizick/project1111/releases/tag/v1.0.0 (no binaries, no weights). `p11 update` updates to the newest tag (ADR-0036).

## Tasks
1. **Pre-flight on `main`** (after 17a–17c are merged): `make check`, `make e2e`, `make gpu-test`, the container install test (`tests/install/run.sh`); gitleaks over the full history; `git ls-files` holds no weights, media (other than the synthetic fixtures), tokens or vault source notes. If any check fails and cannot be fixed within a release's scope, **block** instead of releasing (the pre-authorization covers publishing, not shipping a red build).
2. **Version and changelog:** `1.0.1` in all five places; `[Unreleased]` → `## [1.0.1] - <timestamp from date>`, compare links `v1.0.0...v1.0.1`.
3. **Final report:** add a short "v1.0.1" section to `docs/P11_FINAL-REPORT.md` (what changed, measured results from 17a/17b, the OCC card); the generated timeline block refreshes on `main`.
4. **Merge, timeline, tag:** merge to `main`, run `python3 scripts/phase_timeline.py --write --vault-note "/home/nick/Documents/02 Projects/P11 Implementation Plan.md"`, then the annotated tag `v1.0.1` on that commit; push `main` and the tag.
5. **Publish (pre-authorized, ADR-0040):** `gh release create v1.0.1 --title "P11 v1.0.1" --notes-file <changelog section>` on `antonizick/project1111`, no binaries or weights, not a draft, marked latest. Do **not** run `gh repo edit --visibility`. Check the release page shows no private data, and record `gh repo view --json visibility` before and after (must be unchanged).
6. **Post-release check:** fresh authenticated clone at `v1.0.1`, `install.sh --dry-run` exit 0; on the laptop `p11 update --check` (or the command's real flag) sees `v1.0.1`.
7. **Hand-off to Nick:** the final message gives the release URL, how to update (`p11 update`), and a 5-line test list (brush stroke, Background overlay, Face & Pose scrolling, Start from a photo, the OCC card).

## Out of scope
New fixes (record follow-ups instead), visibility change, AUR packaging.

## Tests
Task 1 suite and task 6 checks, with counts in the Phase Log.

## Acceptance criteria
- `v1.0.1` tag and GitHub release exist; notes match the changelog; visibility unchanged (before/after recorded with timestamps).
- Fresh clone at the tag passes `install.sh --dry-run`.
- Plan, vault note, final report and timeline updated.

## Phase-specific docs
CHANGELOG, `docs/P11_FINAL-REPORT.md`, README (version mentions), vault note. Then the standard close-out checklist.
