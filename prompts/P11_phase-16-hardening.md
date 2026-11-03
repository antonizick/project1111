# P11 Phase 16: Hardening, security review & QA

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 09, 11, 13, 14, 15 · **Branch:** `phase-16-hardening` · **Worktree:** `../project1111-phase-16` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, the whole spec (especially §1 success criteria, §10 acceptance criteria, §11 all amendments, Appendix B). Every Phase Log entry and its follow-ups. `docs/P11_DECISIONS.md` (all `Proposed` ADRs must end Accepted or Superseded), `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES.

**Phase 05 results (2026-11-02 19:28 CST):** the OOM soak can force a real OOM with `tests/gpu/vram_hog.py` (oversized latents do not OOM at v0.43.0, ADR-0020). `tests/gpu/test_engine_contract_gpu.py::test_engine_listens_on_loopback_only_and_stays_offline` checks the listening socket and scans the engine log for non-loopback URLs; the engine environment sets `HF_HUB_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, `TRANSFORMERS_OFFLINE`, `DO_NOT_TRACK`.

**Phase 07 results (2026-11-02 23:50 CST):** the threat model starts from `src/p11/api/security.py` (Host allowlist, Origin/Sec-Fetch-Site, token header vs read-only cookie, launch codes, CSP, body caps), `p11/media/validate.py` (S8) and ADR-0022; existing tests: `tests/unit/test_api_security.py`, `test_media.py`. Known limits to review: the token file is readable by the same user (out of scope by SECURITY.md); `StaticFiles` serves `src/p11/web/` without a token by design; the upload route buffers images in memory (≤ 64 MiB) and spools videos to disk. The access log never logs query strings; `debug_private` is the only path for prompt text.

**Phase 08 results (2026-11-03 04:18 CST):** the UI shell is in `frontend/src/` (ADR-0023, `docs/P11_ARCHITECTURE.md` → Studio UI). Views live in `features/<name>/` and are listed in `app/nav.tsx` `VIEWS` (remove the view's `phase` there and render it in `app/Shell.tsx` instead of the placeholder). Read state with `useStudio()` (jobs, progress, images, `galleryRev`), call the API through `client` in `api/client.ts` (add typed calls there), show errors with `useToasts().problem(problemOf(e))`, register keys with `useShortcuts`, and use `components/Dialog` and `components/ZoomPan`. Follow-up buttons on a result/detail image come from `features/actions.tsx`: replace your `LATER` entry with a real action (the gallery passes images by ID; a step on an earlier output uses `source_image: {ref: "gallery/<id>"}` or a slot bound to it, as `upscaleRecipe` in `features/generate/form.ts` does). Tests: `src/test/fakes.ts` (routed fake `fetch`, `FakeSource`) for Vitest; Playwright helpers in `e2e/studio.ts` (`openStudio` with the network guard, `Actions` counter); use `getByLabel("Prompt", { exact: true })` and scope Generate with `generateButton(page)`. Measured in Phase 08 (FakeEngine): typed prompt → Generate → Download = 2 actions (`[action-count]` in the e2e output). `e2e/daily.spec.ts` already runs axe and the network guard; `e2e/real-engine.spec.ts` drives a real Studio (`P11_REAL_LAUNCH_URL`). The trash (`<data>/trash/`) has no restore button yet (follow-up).

## Goal
Prove that P11 is safe, stable and as effortless as the spec promises, using measurements on the laptop, and fix what falls short. Every security control S1–S10 is verified, every success criterion is measured, licences are audited for publication, and every open follow-up is closed or deferred under spec H12 (non-security items recorded with measurements and listed for Nick's review at Phase 17; high/critical security findings fixed or the phase blocks).

## Tasks
1. **Threat model** `docs/P11_THREAT-MODEL.md`: assets (face photos, videos, outputs, tokens, the machine), trust boundaries (browser ↔ Studio, Studio ↔ engine, P11 ↔ model hosts, installer ↔ system), threats (DNS rebinding, CSRF from a malicious page, local processes hitting the engine port, malicious model files, compromised custom node or dependency, path traversal via uploads, ffmpeg/Pillow parser bugs, token leakage in logs), mitigations and residual risks (e.g. the engine has no auth; any local process can reach it).
2. **Verify S1–S10** with evidence: listeners (`ss -ltnp`), an egress capture during a full session (no traffic except explicit downloads), Host/Origin/token tests against the running service, CSP check, pinned SHAs for engine and nodes match `engine.lock.toml`, `uv lock`/npm lock integrity, pickle refusal, upload fuzzing (malformed PNG/JPEG/MP4 with a small fuzz corpus; Pillow and ffprobe errors handled), secrets scan of full history (gitleaks), private-dir permissions, log redaction.
3. **S5 guard bypass review:** try to reach a face-swap without the guard via every path (UI, API, template import with edited steps, recipe migration, video job, direct job submission, engine port directly). The engine port bypass is a residual risk to document; every P11 path must be guarded. Fix any gap.
4. **Scanners** (installed at user level, H4)**:** ruff security rules/bandit, pip-audit, npm audit, Semgrep (or CodeQL in CI) on `src/` and `frontend/`; ShellCheck on scripts; triage every finding (fix or justify).
5. **Measured success criteria (R22, Appendix B), on the laptop:** time-to-first-image (from Phase 15's method), per-preset generation times (both wallpaper presets, cold/warm, Speed/Quality), 50-run OOM soak per preset, a 30-minute mixed-workload soak (generate, inpaint, background, face, upscale, model switch) with no crash or leak (RSS and VRAM sampled), 10-minute thermal loop, video 30 s clip time. Playwright action counts for daily path, save template, re-run template, inpaint and background paths. Record all in `docs/P11_BENCHMARKS.md` against the targets; fix regressions that miss them, or record the miss with its measurement and reason and defer it (H12). Benchmarks use the power profile rule H8.
6. **Accessibility:** axe on every view, keyboard-only walkthrough of the daily path, focus order, contrast in both themes, reduced-motion.
7. **Licence audit:** every Python/npm dependency (licence report), engine and custom nodes (GPL-3.0 components are installed separately, not vendored, so P11 stays MIT: confirm no copied code), fonts, models (non-commercial and other restrictions surfaced in THIRD_PARTY_NOTICES, the installer and the Models page). Produce a short "publication readiness" note for Phase 17 listing any blockers.
8. **Follow-ups:** close every Phase Log follow-up, or list it as deferred with a reason in the plan; mark all `Proposed` ADRs; refresh docs (README, user guide, architecture) to match reality.

## Out of scope
New features. A change request goes through `/phase-add`.

## Tests
New regression tests for every bug found; fuzz corpus committed (synthetic files only); `make check` and `make gpu-test` green; Playwright suite green on FakeEngine and once on the real engine.

## Acceptance criteria
- Threat model written; S1–S10 each have a verification note with evidence.
- Every success criterion in spec §1 and §10 has a measured result in `docs/P11_BENCHMARKS.md` marked met, or not met and deferred under H12 with the reason recorded and listed for the Phase 17 review.
- No high/critical scanner findings open; licence audit done with no publication blocker, or blockers listed for Nick.
- The plan's Definition of done items through "All docs current" are checked.

## Phase-specific docs
`docs/P11_THREAT-MODEL.md` (new, prefixed), SECURITY, `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES, README, `docs/P11_USER-GUIDE.md`, `docs/P11_ARCHITECTURE.md`, ADR statuses, CHANGELOG. Then the standard close-out checklist.
