# P11 Phase 16: Hardening, security review & QA

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 09, 11, 13, 14, 15 · **Branch:** `phase-16-hardening` · **Worktree:** `../project1111-phase-16` · **Gate:** review

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, the whole spec (especially §1 success criteria, §10 acceptance criteria, §11 all amendments, Appendix B). Every Phase Log entry and its follow-ups. `docs/P11_DECISIONS.md` (all `Proposed` ADRs must end Accepted or Superseded), `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES.

## Goal
Prove that P11 is safe, stable and as effortless as the spec promises, using measurements on the laptop, and fix what falls short. Every security control S1–S10 is verified, every success criterion is measured, licences are audited for publication, and every open follow-up is closed or explicitly deferred with Nick's agreement.

## Tasks
1. **Threat model** `docs/P11_THREAT-MODEL.md`: assets (face photos, videos, outputs, tokens, the machine), trust boundaries (browser ↔ Studio, Studio ↔ engine, P11 ↔ model hosts, installer ↔ system), threats (DNS rebinding, CSRF from a malicious page, local processes hitting the engine port, malicious model files, compromised custom node or dependency, path traversal via uploads, ffmpeg/Pillow parser bugs, token leakage in logs), mitigations and residual risks (e.g. the engine has no auth; any local process can reach it).
2. **Verify S1–S10** with evidence: listeners (`ss -ltnp`), an egress capture during a full session (no traffic except explicit downloads), Host/Origin/token tests against the running service, CSP check, pinned SHAs for engine and nodes match `engine.lock.toml`, `uv lock`/npm lock integrity, pickle refusal, upload fuzzing (malformed PNG/JPEG/MP4 with a small fuzz corpus; Pillow and ffprobe errors handled), secrets scan of full history (gitleaks), private-dir permissions, log redaction.
3. **S5 guard bypass review:** try to reach a face-swap without the guard via every path (UI, API, template import with edited steps, recipe migration, video job, direct job submission, engine port directly). The engine port bypass is a residual risk to document; every P11 path must be guarded. Fix any gap.
4. **Scanners:** ruff security rules/bandit, pip-audit, npm audit, Semgrep (or CodeQL in CI) on `src/` and `frontend/`; ShellCheck on scripts; triage every finding (fix or justify).
5. **Measured success criteria (R22, Appendix B), on the laptop:** time-to-first-image (from Phase 15's method), per-preset generation times (both wallpaper presets, cold/warm, Speed/Quality), 50-run OOM soak per preset, a 30-minute mixed-workload soak (generate, inpaint, background, face, upscale, model switch) with no crash or leak (RSS and VRAM sampled), 10-minute thermal loop, video 30 s clip time. Playwright action counts for daily path, save template, re-run template, inpaint and background paths. Record all in `docs/P11_BENCHMARKS.md` against the targets; fix regressions that miss them or record why with Nick.
6. **Accessibility:** axe on every view, keyboard-only walkthrough of the daily path, focus order, contrast in both themes, reduced-motion.
7. **Licence audit:** every Python/npm dependency (licence report), engine and custom nodes (GPL-3.0 components are installed separately, not vendored, so P11 stays MIT: confirm no copied code), fonts, models (non-commercial and other restrictions surfaced in THIRD_PARTY_NOTICES, the installer and the Models page). Produce a short "publication readiness" note for Phase 17 listing any blockers.
8. **Follow-ups:** close every Phase Log follow-up, or list it as deferred with a reason in the plan; mark all `Proposed` ADRs; refresh docs (README, user guide, architecture) to match reality.

## Out of scope
New features. A change request goes through `/phase-add`.

## Tests
New regression tests for every bug found; fuzz corpus committed (synthetic files only); `make check` and `make gpu-test` green; Playwright suite green on FakeEngine and once on the real engine.

## Acceptance criteria
- Threat model written; S1–S10 each have a verification note with evidence.
- Every success criterion in spec §1 and §10 has a measured result in `docs/P11_BENCHMARKS.md` marked met, or not met with Nick's agreement recorded.
- No high/critical scanner findings open; licence audit done with no publication blocker, or blockers listed for Nick.
- The plan's Definition of done items through "All docs current" are checked.

## Phase-specific docs
`docs/P11_THREAT-MODEL.md` (new, prefixed), SECURITY, `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES, README, `docs/P11_USER-GUIDE.md`, `docs/P11_ARCHITECTURE.md`, ADR statuses, CHANGELOG. Then the standard close-out checklist.
