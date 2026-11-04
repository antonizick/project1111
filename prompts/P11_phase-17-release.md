# P11 Phase 17: Release & publication

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 16 · **Branch:** `phase-17-release` · **Worktree:** `../project1111-phase-17` · **Gate:** review

## Read first
`CLAUDE.md` (Risk rule, git authority), `prompts/P11_shared-instructions.md`, spec §1, §11.1 A3, §11.4. Phase Log entry for 16 and its publication-readiness note. ADR-0003, ADR-0004, ADR-0005, ADR-0015, ADR-0016; spec §11.6 H10, H12, H13. The plan's Definition of done.

**Phase 16 results (2026-11-03 20:30 CST):** the publication-readiness note is `docs/P11_PUBLICATION-READINESS.md` (no blocker for the private release; keep the InsightFace non-commercial flag visible); residual risks are in `docs/P11_THREAT-MODEL.md` §3 (T6 engine port, T8 re-uploaded likeness, classifier misses); measured results vs targets are in `docs/P11_BENCHMARKS.md` → "Success criteria (Phase 16 …)"; the deferred misses for task 5 (a) are the plan's "Deferred follow-ups (Phase 16, H12)" table. ADR-0037 (Phase 16) extends the S5 guard to face references and edits of likeness pictures. The Playwright suite now runs with one worker and has a CI job (`e2e`); the e2e and Vitest suites are green when the machine is idle. Phase 16 used bandit and Semgrep from `uv tool` (user level); `make check` does not run them.

## Goal
P11 v1.0.0 is tagged with a complete changelog and a final report that embeds the generated timeline. Only if Nick confirms in this session ("go?") is a GitHub release published, **on the private repo**; the repo stays private (spec H13, ADR-0016).

## Tasks
1. **Pre-flight:** `make check`, `make gpu-test`, and the container install test green on `main`; `git ls-files` contains no weights, media, tokens or the vault source notes (ADR-0004); gitleaks over the full history clean; THIRD_PARTY_NOTICES complete; README, user guide and screenshots (FakeEngine or non-personal generated images only) current.
2. **Version and changelog:** set the version to `1.0.0` in `pyproject.toml` and `frontend/package.json`; move `[Unreleased]` into `## [1.0.0] - <timestamp from date>` (Keep a Changelog; heading carries a timestamp per CLAUDE.md); compare links.
3. **Final report** `docs/P11_FINAL-REPORT.md`: what was built against the spec, measured results vs targets (from `docs/P11_BENCHMARKS.md`), decisions (ADR summary), deviations, known limitations and residual risks (from the threat model), deferred follow-ups, and a `## Timeline` section containing the generator's start/end marker lines (copy them from the plan). Run `python3 scripts/phase_timeline.py --write --vault-note "/home/nick/Documents/02 Projects/P11 Implementation Plan.md"` so the block is filled. Never draw a chart by hand.
4. **Tag:** annotated tag `v1.0.0` on the release commit; push the tag to the private remote (git authority).
5. **Review and release decision (mandatory, in-session):** present Nick with (a) the review items deferred to this pause (H10): Phase 03's model pick and contact-sheet path, Phase 08's UI screenshots, Phase 15's installer and host changes, Phase 16's deferred misses (H12); (b) the release plan decided in the preflight: a GitHub release for `v1.0.0` on the **private** repo, repo stays private (H13). Ask "go?" for the release. **Publish nothing without an explicit yes in this session; never change the repo's visibility in this phase.** In hands-off mode, block-with-question instead (the planned stop of the run).
6. **If confirmed:** `gh release create v1.0.0` on the private repo with notes from the changelog (no binaries, no weights); add repo topics/description. Check the release page shows no private data. The pinned-tag one-liner (R15) stays documented as "works once the repo is public".
7. **Vault and wrap-up:** the vault note's status `complete` (or `released`), final log line; the plan's Definition of done all checked or annotated.

## Out of scope
New features, AUR packaging (follow-up via `/phase-add`).

## Tests
Pre-flight suite (task 1); after the release, a fresh `git clone` of the private repo at the tag (authenticated with `gh`) in the container runs `install.sh --dry-run`.

## Acceptance criteria
- `v1.0.0` tagged and pushed; CHANGELOG and final report complete with the generated timeline.
- Repo visibility and release state match exactly what Nick confirmed in-session (recorded with a timestamp in the Phase Log).
- Definition of done fully checked or annotated.

## Phase-specific docs
CHANGELOG, `docs/P11_FINAL-REPORT.md` (new, prefixed), README (badges/links if public), vault note. Then the standard close-out checklist.
