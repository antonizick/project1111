# P11 Phase 17: Release & publication

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 16 · **Branch:** `phase-17-release` · **Worktree:** `../project1111-phase-17` · **Gate:** review

## Read first
`CLAUDE.md` (Risk rule, git authority), `prompts/P11_shared-instructions.md`, spec §1, §11.1 A3, §11.4. Phase Log entry for 16 and its publication-readiness note. ADR-0003, ADR-0004, ADR-0005. The plan's Definition of done.

## Goal
P11 v1.0.0 is tagged with a complete changelog and a final report that embeds the generated timeline. Only if Nick confirms in this session does the repository become public and a GitHub release get published.

## Tasks
1. **Pre-flight:** `make check`, `make gpu-test`, and the container install test green on `main`; `git ls-files` contains no weights, media, tokens or the vault source notes (ADR-0004); gitleaks over the full history clean; THIRD_PARTY_NOTICES complete; README, user guide and screenshots (FakeEngine or non-personal generated images only) current.
2. **Version and changelog:** set the version to `1.0.0` in `pyproject.toml` and `frontend/package.json`; move `[Unreleased]` into `## [1.0.0] - <timestamp from date>` (Keep a Changelog; heading carries a timestamp per CLAUDE.md); compare links.
3. **Final report** `docs/P11_FINAL-REPORT.md`: what was built against the spec, measured results vs targets (from `docs/P11_BENCHMARKS.md`), decisions (ADR summary), deviations, known limitations and residual risks (from the threat model), deferred follow-ups, and a `## Timeline` section containing the generator's start/end marker lines (copy them from the plan). Run `python3 scripts/phase_timeline.py --write --vault-note "/home/nick/Documents/02 Projects/P11 Implementation Plan.md"` so the block is filled. Never draw a chart by hand.
4. **Tag:** annotated tag `v1.0.0` on the release commit; push the tag to the private remote (git authority).
5. **Publication decision (mandatory, in-session):** present Nick with the publication-readiness note (licence flags such as non-commercial model weights that users download themselves, the S5 boundary, the content stance in the README), then ask explicitly whether to (a) make the repo public, (b) publish a GitHub release for `v1.0.0`, both, or neither. **Do nothing public without an explicit yes in this session.** In hands-off mode, block-with-question instead.
6. **If confirmed:** `gh repo edit --visibility public --accept-visibility-change-consequences`, verify the install one-liner URL for the tag works (R15), `gh release create v1.0.0` with notes from the changelog (no binaries, no weights), add repo topics/description. Then check the public page shows no private data.
7. **Vault and wrap-up:** the vault note's status `complete` (or `released`), final log line; the plan's Definition of done all checked or annotated.

## Out of scope
New features, AUR packaging (follow-up via `/phase-add`).

## Tests
Pre-flight suite (task 1); after publication, a fresh `git clone` of the public repo at the tag in the container runs `install.sh --dry-run`.

## Acceptance criteria
- `v1.0.0` tagged and pushed; CHANGELOG and final report complete with the generated timeline.
- Repo visibility and release state match exactly what Nick confirmed in-session (recorded with a timestamp in the Phase Log).
- Definition of done fully checked or annotated.

## Phase-specific docs
CHANGELOG, `docs/P11_FINAL-REPORT.md` (new, prefixed), README (badges/links if public), vault note. Then the standard close-out checklist.
