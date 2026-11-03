# P11 Phase 08: Generate view, gallery & app shell

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 07 · **Branch:** `phase-08-generate-ui` · **Worktree:** `../project1111-phase-08` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §1 (success criteria), §4 (Generation, Quality), §6, §11.2 R3, R5, R7, R14, R17, R18, R22, §11.3 S1, S2, Appendix B. Phase Log entries for 04 and 07. `docs/P11_BENCHMARKS.md` (timings for progress estimates).

**Phase 05 results (2026-11-02 19:28 CST):** progress events carry `node` and `title` (`base` / `hires` for the samplers, from the compiler's `_meta`), so the bar can show "Generating" vs "Refining"; a `Retrying` event precedes the low-VRAM OOM retry (show "Out of memory, retrying in low-memory mode"). Previews are off (`--preview-method none`). The status bar's VRAM/thermal numbers come from `GpuSample` (`vram_used_mib`, `vram_total_mib`, `temp_c`, `power_w`, `throttle_reasons`) at ≤ 1 Hz. Interrupt stops a run in ~0.5 s on the laptop.

**Phase 07 results (2026-11-02 23:50 CST):** the session bootstrap is `frontend/src/api/session.ts`: call `bootstrapSession()` once at start (it redeems the `#launch=` code from `p11 open`, keeps the token in `sessionStorage` and clears the fragment) and make every API call with `api<T>(path, init)`, which sends the token and throws `ApiError` carrying the server's `{code, message, hint}` (show `message` and `hint` as they are). `<img src="/api/images/{id}/thumb">` and `new EventSource("/api/events")` work through the `HttpOnly` cookie; never put the token in a URL. Routes and event types are listed in `docs/P11_ARCHITECTURE.md` → Studio API: `POST /api/jobs {recipe, bindings, count, template?, parent?}` (validated at submit: 4xx for slot/model/file errors), `POST /api/jobs/{id}/cancel`, SSE `job` (state, progress 0–1, `note` for OOM retry/thermal pause, `images`), `progress` (`run/runs`, `graph/graphs`, `step/total`, `title`), `image` (gallery entry JSON with `url`/`thumb`), `gpu` (≤ 1 Hz), `hello` (recent jobs); `GET /api/gallery?q&template&favourites&since&until&limit&offset` → `{items,total}`; `POST /api/images/{id}/favourite|export`; `GET /api/images/{id}/recipe` (re-open as recipe); `GET /api/presets`, `/api/models`, `/api/system`. Variations: submit with `count` (run *i* uses the recipe's seed strategy) and `parent` (gallery ID). The CSP is `default-src 'self'` (no inline scripts or styles from strings, no remote assets). `p11 serve --fake` seeds 6 demo images in `~/.cache/p11/fake/` with ~50 ms per sampler step. Playwright: `frontend/playwright.config.ts` starts `p11 serve --fake` on port 18211 in temp dirs and the tests get a launch URL from `p11 open --print-url` (see `frontend/e2e/smoke.spec.ts`).

## Goal
The daily path feels push-button. You open P11, type a prompt, pick a style and an aspect preset, press Generate, watch progress, and get a result with its follow-up actions one click away. Results land in a fast gallery with compare and export. The app shell, status bar and keyboard map that the later feature views plug into are defined here.

## Tasks
1. **App shell** (`frontend/src/app/`): left nav (Generate, Gallery, Templates, Inpaint, Background, Face & Pose, Video, Models; unbuilt views show "coming in Phase NN" placeholders, removed as phases land), a top bar with the session state, and a **status bar**: engine state, job queue, VRAM used/total, GPU temperature with a colour band, current model. Light/dark themes from CSS variables. All assets local (S1).
2. **API client** (`frontend/src/api/`): typed client generated or hand-written from the OpenAPI schema, session token handling (from the URL fragment, then memory/sessionStorage), an SSE/websocket hook for events with reconnect.
3. **Generate view (Simple mode, R18):** prompt box (multi-line, Ctrl+Enter generates), style preset chips (photoreal default, 3D animated avatar, logo flat, logo 3D), aspect/wallpaper presets (1920×1080, 2560×1440, square, portrait), batch count (1–4), Generate/Cancel. A live preview area with step progress, ETA from benchmark timings, and the latest preview image if the engine sends previews.
4. **Advanced drawer:** model selector (registry, with base family and "default" badge), LoRA list with weights, negative prompt, sampler/scheduler, steps, CFG, seed with a lock toggle, upscale chain choice; values default from the model's manifest defaults. Advanced state is part of the recipe.
5. **Result panel:** the image (zoom/pan), metadata summary, and follow-up actions: **Variations** (seed / subtle prompt mutation, Phase 04), **Upscale**, **Inpaint**, **Background**, **Face**, **Save as Template** (the button exists; Phase 09 completes the flow), **Download** (with "strip metadata" option), favourite. Actions for unbuilt features show their phase number.
6. **Gallery:** virtualized grid by day, filters (template, favourite, model), search (FTS from 04), detail view, side-by-side **compare** of two or more images with synced zoom, "open as recipe" (reload settings from the PNG/sidecar), bulk export, delete (moves to a P11 trash folder; emptied by an explicit action).
7. **Errors and empty states:** plain-English toasts with hints (OOM, engine down, missing model → link to Models), first-run empty state that explains the one thing to do.
8. **Keyboard map:** Ctrl+Enter generate, Esc cancel, V variation, T save template, G gallery, ? shortcut overlay; focus management and visible focus rings; all controls reachable by keyboard; labels for screen readers.
9. **E2E with FakeEngine:** Playwright walkthroughs of the daily path that **count actions per Appendix B** and assert generate→download ≤ 3 actions from a typed prompt.

## Out of scope
Template save/apply flow (09), mask editor (10), background (11), face/pose (12), video (13), models UI (14).

## Tests
Vitest component tests (form state → recipe JSON, preset switching, advanced defaults from manifest, error toasts), API client tests with mocked SSE, Playwright e2e on `p11 serve --fake` (generate, cancel, variations, gallery search, compare, export with stripped metadata), axe accessibility checks on Generate and Gallery. One manual run on the laptop with the real engine.

## Acceptance criteria
- On the laptop with the real engine: a 1920×1080 photoreal image generates from Simple mode with prompt + Ctrl+Enter; the status bar shows live VRAM and temperature; the result appears in the gallery.
- Playwright action counts recorded in the Phase Log; the daily path is within Appendix B.
- No network requests other than to `127.0.0.1:<port>` (checked in Playwright).
- `make check` green. Add a "for the owner's review" bullet to the Phase Log entry (Nick reviews the UI at the Phase 17 pause, spec H10); capture 2–3 screenshots under `docs/images/` from FakeEngine images only (no personal content).

## Phase-specific docs
`docs/P11_USER-GUIDE.md` (Generate, Gallery, shortcuts), `docs/P11_ARCHITECTURE.md` (frontend structure, state, events), README screenshot, CHANGELOG. Then the standard close-out checklist.
