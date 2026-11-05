# P11 Phase 17h: Reset button in the top bar

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 17g · **Branch:** `phase-17h-reset-button` · **Worktree:** `../project1111-phase-17h` · **Gate:** review

The Studio keeps every view mounted, so forms, picked photos, masks and results stay in all tabs until the window is reloaded. Nick wants one control that gives him a clean slate across the tabs without touching anything on disk. This goes into v1.0.2 (17f now depends on it).

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md` (§4, including the rebuild-and-restart and real-Studio rules), spec §11 Amendments (S1). Phase Log entries for 17g and the planning entry for this phase. ADR-0043, **ADR-0048**.

## Nick's request (verbatim intent, 2026-11-04 18:34 CST)
"Add a Reset button at the right of the top bar that clears the on-screen state in all tabs after a short confirmation, and leave disk files alone at first. Disk cleanup could be a separate, clearly labelled option if you want it."

## Decisions already made
- **ADR-0048:** Reset is on-screen only. It deletes nothing on disk and calls no delete route.
- **ADR-0048, running work:** while any job is queued, running or paused, the dialog says so and the Reset button in it is disabled. Reset never cancels a job and never orphans one.
- **ADR-0048, what stays:** theme, gallery thumbnail size, the Run dialog's remembered inputs (`p11.slot-memory`), recent templates (`p11.recent-templates`) and the session token. The dialog says remembered template inputs stay.
- **Disk cleanup is not in this phase.** It is a deferred follow-up; do not add a button for it, disabled or otherwise.
- **Defaults you may change with a reason in the Phase Log:** the current tab stays open after a reset; a modifier-free keyboard shortcut is not added; Cancel takes the dialog's first focus.

## Goal
Pressing **Reset** and confirming returns all eight tabs to their fresh form, with no file touched and no job affected.

## What exists (verified 2026-11-04 18:34 CST; re-check before relying on it)
- `frontend/src/app/Shell.tsx`: `.topbar` ends with the theme button and `?`; the eight views are mounted together in `<main>` and hidden by `active`. Their state is local `useState`, so remounting clears it. `Shell` already opens a `Dialog` for shortcuts.
- `frontend/src/app/nav.tsx`: `NavProvider` holds `editing`. Each editing view compares `editing.at` with its own `seen` state **during render**, so a remounted view reloads the old hand-off unless `editing` is cleared in the same update.
- `frontend/src/app/studio.tsx`: pure `reduce` with `jobs`, `progress`, `previews`, `images`, `currentModel`; `FINISHED` in `api/types`. `StatusBar.tsx` shows running work from `state.jobs` and the model from `currentModel`.
- **Cancel lives in the view:** `client.cancelJob` is called from each view's own followed job (`GenerateView.tsx`, `InpaintView.tsx`, `BackgroundView.tsx`, `VideoView.tsx`); only Video's history list has a Cancel that survives a remount. This is why ADR-0048 holds Reset.
- `frontend/src/app/Toasts.tsx`: `push` and `problem`, no way to clear. `Toast` timers call `close` by id, which is safe after a clear.
- `frontend/src/features/templates/ui.tsx`: `TemplateUiProvider` sits above `Shell`, so it is not remounted. `useRecipeReceiver` and `useTemplateRuns` clean up their listeners on unmount.
- `frontend/src/components/Dialog.tsx`: modal, focus trap, Esc, `data-autofocus`. `.btn-danger` is in `theme.css`.
- Views create `blob:` URLs and revoke them only on replacement, so a remount leaves them to the window's lifetime.

## Tasks
1. **Reducer.** Add `{ type: "reset" }` to `app/studio.tsx`: drop finished jobs with their progress and previews, keep unfinished ones, set `currentModel` to null. Keep `connected`, `images`, `gpu`, `system`, `presets`, `models`, `modelOps` and both revision counters.
2. **Nav.** Add `resetKey` and `reset()` to `NavProvider`: bump the key and clear `editing` in one update. Do not change `view`.
3. **Remount.** In `Shell`, wrap the views in a keyed `Fragment` using `resetKey`. Check that no view starts a job, an upload or a toast on mount, and that the Models view shows an install in progress after a reset (it reads `modelOps`).
4. **Toasts.** Add `clear()` so old messages go, then push one info toast: "Studio reset. Nothing on disk changed."
5. **Button and dialog.** Add `Reset` as the last control in `.topbar`, `btn btn-ghost`, with an `aria-label` that names what it does. The dialog title is **Reset Studio?**. Its body says in two short lines that it clears forms, picked photos, masks and results in every tab, and that images, uploads, models, templates and remembered template inputs stay. Gallery contents come from disk, so say the gallery keeps its images and only its filters and selection reset. Buttons: **Cancel** (`data-autofocus`) and **Reset** (`btn-danger`).
6. **Hold while busy.** In the dialog, count unfinished jobs from `state.jobs`. With any, disable **Reset** and show "N job(s) still running. Reset is available when they finish or you cancel them." The state is live, so the button enables itself when the last job ends. While `state.connected === false`, job states are stale: keep Reset disabled too, with a line saying the Studio is reconnecting, so a dropped stream cannot orphan a job.
7. **Stale job check.** `hello` carries only `queue.recent(20)`. Confirm that a job which ended while the stream was down cannot stay "running" in `state.jobs` and hold Reset forever. If it can, fix it at the root and add a test.
8. **Docs:** user guide (the top bar paragraph and section on tabs), `docs/P11_ARCHITECTURE.md` (the reset path), CHANGELOG `[Unreleased]`, the screenshots if the top bar in them changes.
9. **Walk-through (interactive; hands-off mode pauses at the Gate):** after the merge, rebuild and restart (shared instructions §4), ask Nick to try it in his own window. Record his answer in the Phase Log with a timestamp.

## Out of scope
Any disk cleanup, delete route or disk-usage display. Cancelling jobs from Reset. Clearing remembered template inputs or recent templates. Backend changes (unless task 7 finds a defect). Preset or model defaults. The v1.0.2 release (17f).

## Tests
- Vitest: the `reset` reducer case (pure, including unfinished jobs kept); `resetKey` and cleared `editing`; a hand-off already consumed is not reloaded after a reset; the dialog's Cancel, Esc and first focus; Reset disabled with a running job and while disconnected, enabled once idle; `localStorage` keys for theme, tile size, slot memory and recent templates unchanged.
- Playwright: fill Generate, load a picture on Inpaint and set a gallery filter, reset, and see all three fresh, on the same tab; a network assertion that a reset sends **no** `POST`, `PUT` or `DELETE`; the hold with a running fake job; axe on the dialog; no overflow in the top bar at 1280×720 and 1918×2130. Run once in Brave (`P11_E2E_BROWSER=/usr/bin/brave`).
- `make check`, `make e2e`; `make gpu-test` is not needed unless engine-facing code changes.

## Acceptance criteria
- Reset is the rightmost top-bar control and nothing happens without the confirmation.
- After confirming, all eight tabs are fresh, the current tab stays open, and old results and hand-offs do not come back.
- A reset sends no writing request, and files on disk are unchanged.
- With a job unfinished, or the stream down, Reset cannot be confirmed. It becomes available without reopening the dialog.
- Theme, thumbnail size, remembered inputs and recent templates survive a reset.
- Nick confirms it in his own window (Phase Log, timestamped). Without that the phase does not claim it.

## Phase-specific docs
As in task 8, plus the vault note. No host OS change is expected.

Then the standard close-out checklist.
