# P11 Phase 17a: Editor and layout fixes

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 17 · **Branch:** `phase-17a-ui-fixes` · **Worktree:** `../project1111-phase-17a` · **Gate:** auto

Nick used v1.0.0 and found three UI defects that the jsdom-based Vitest suite could not see: the inpaint brush leaves no trail while drawing, the Background tab's mask overlay is shifted to the right, and the Face & Pose tab has no layout at all, so large uploads push the pane off screen with no scroll bars. This phase fixes all three and adds real-browser (Playwright/Chromium) checks so they cannot regress. It can run in parallel with 17b and 17c; merge this one first (all three touch `frontend/src/app/theme.css`).

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §11 Amendments (R18, S1). Phase Log entries for 10, 11, 12 and 16. ADR-0023 (UI structure), ADR-0025 (inpainting, mask editor). `docs/P11_ARCHITECTURE.md` → Studio UI, Inpainting.

## Nick's request (verbatim intent, 2026-11-04 07:25 CST)
1. "For the in-paint brush, as I brush back and forth, it does not leave a stroke where the brush was, but rather it just shows the brush moving back and forth (rather than leaving a brush stroke path as intended). I find that if I go click undo and then redo it shows up but right now the brush operation does not work as intended."
2. "On the background tab when the mask shadow is rendered, the shape looks perfect but the mask is offset off to the right by quite a bit. I can provide screenshots if helpful."
3. "On the face & pose tab when images are uploaded they show as full size and no scroll bars are ever made available on the pane the user is working on, so as the images force the operating pane off of the bottom and right edges of the screen no scroll bars manifest and the screen becomes difficult to navigate."

## Decisions already made
- Phase split and placement (17a fixes, 17b photo edit, 17c OCC, 17d release v1.0.1): Phase Log entry "Planning: phases 17a–17d inserted", 2026-11-04.
- No ADR is needed for these fixes unless you change the mask editor's architecture (ADR-0025: one image-sized mask canvas under a CSS transform, dirty-box recompositing). Keep that design.

## Goal
On the laptop in the real Studio (Chromium app window): a brush or eraser drag leaves a continuous stroke as you draw; the Background mask overlay sits exactly on the subject at any window size; the Face & Pose view shows its pictures at a sensible size and scrolls when the content is taller or wider than the pane.

## What exists (verified 2026-11-04 07:40 CST; re-check before relying on it)
- **Brush (item 1).** `frontend/src/features/mask-editor/MaskEditor.tsx:paint` draws dabs onto the offscreen stroke layer and calls `render.ts:composite(mask, snapshot, layer, stroke, rect)` with the dirty box `rect`. `composite` does `globalCompositeOperation = "copy"` then `drawImage(snapshot, x, y, w, h, x, y, w, h)`. **Likely root cause:** in browsers, `copy` replaces the *whole* canvas (outside the drawn region becomes transparent, per the canvas compositing spec), so each pointer move wipes everything except the current dab box. `replay()` (used by undo/redo) passes the full canvas rect, which is why undo→redo makes the stroke appear. jsdom has no real canvas, so `model.test.ts` and the Vitest suite never saw it. Confirm in Chromium before fixing.
  - Fix direction (default): restore the box without `copy`, for example `clearRect(rect)` then `source-over` `drawImage(snapshot, rect…)`, or `save(); beginPath(); rect(...); clip();` around the `copy` draw. Keep the dirty-box performance (the 60 fps check reads `data-draw-avg-ms` on the stage, Phase 10). Check the eraser (`destination-out`) and opacity < 100 % paths too, and `invert()`, which also uses `copy` on full canvases (fine, but verify).
- **Background overlay (item 2).** `frontend/src/features/background/BackgroundView.tsx` renders `.background-stage` → `<img src={source.url}>` plus, when shown, `<img className="background-overlay" src={maskUrl}>`. CSS `frontend/src/app/theme.css:920-940`: the stage is `position: relative; display: inline-block; max-width: 100%`; `.background-stage > img` (which also matches the overlay) has `max-width: 100%; max-height: 58vh; height: auto; object-fit: contain`; the overlay is `position: absolute; inset: 0; width: 100%; height: 100%`. **Likely cause:** when `max-height: 58vh` shrinks the base image, the shrink-to-fit stage stays wider than the rendered image (left-aligned), while the overlay fills the whole stage, so the mask is shifted right and scaled. Fix so the overlay box is exactly the rendered image box at every viewport size (for example size the stage from the image and give the overlay the same box, or draw both into one element). Check the same pattern anywhere else an overlay sits on an image (`grep -n 'inset: 0' frontend/src/app/theme.css`).
- **Face & Pose (item 3).** `frontend/src/features/face/FaceView.tsx` uses the classes `face-view`, `tool-tabs`, `hint`, `form-row`, `thumb`, plus a result `<img>` (around line 500); `frontend/src/features/pose-editor/PoseEditor.tsx` uses `pose-editor`, `pose-canvas`, `pose-toolbar`. **`theme.css` has no rule for any of them** (only `.face-box`), so images render at natural size. The shell is a fixed-height grid (`.shell { height: 100vh }`) and `.main { overflow: hidden }`; each view must scroll itself (the Generate and Inpaint forms do it with `overflow-y: auto; min-height: 0`, `theme.css:363, 378`). Also check `VideoView.tsx`'s classes for the same gap.
- E2E: Playwright specs in `frontend/e2e/` (`inpaint.spec.ts`, `background.spec.ts`, `face.spec.ts`, helpers in `e2e/studio.ts`), run with `make e2e` against the FakeEngine; they run in real Chromium, so they can read canvas pixels and element boxes.

## Tasks
1. **Reproduce** each defect in Chromium with Playwright (FakeEngine Studio) and write the failing checks first (Tests below).
2. **Brush fix** in `frontend/src/features/mask-editor/render.ts` (and `MaskEditor.tsx` only if needed): a live stroke stays painted along its whole path while the pointer is still down; after pointer-up the mask is pixel-identical to `replay()` of the same history (so undo/redo show no change). Keep the dirty-box recomposite and the draw-time budget.
3. **Background overlay fix** in `BackgroundView.tsx` / `theme.css`: the overlay matches the base image's rendered rect (position and size) for portrait and landscape images, at window sizes 1280×720 and 1920×1080, with and without the "Show mask overlay" toggle.
4. **Face & Pose layout** in `theme.css` (and class names in `FaceView.tsx` / `PoseEditor.tsx` where needed): the view is a scroll container (`overflow: auto; min-height: 0`); picked-picture thumbnails are bounded (default `max-height: 160px`, aspect kept, matching the look of `.background-thumb`); the pose canvas and the result image fit the pane width (`max-width: 100%`, result `max-height` about 70vh, click/zoom as the other views do if cheap); form rows and tool tabs follow the Inpaint form's spacing. Keyboard focus stays visible (R18 accessibility, Phase 16's a11y spec must stay green).
5. **Sweep** the other views for the same two classes of bug (unstyled classes in a view, overlays sized to a container rather than the image) and fix any you find in the same way; list them in the Phase Log.
6. **Screenshots:** if `docs/images/` holds screenshots of these views, regenerate them with `e2e/screenshots.spec.ts` (FakeEngine images only, S6).

## Out of scope
Photo edit on the Generate tab (17b), OCC (17c), the release (17d), new mask-editor tools, a redesign of any view.

## Tests
- Playwright (Chromium): (a) draw a horizontal drag of 20+ moves on the inpaint canvas and assert that pixels at the start, middle and end of the path have mask alpha > 0 *before* pointer-up and after it; (b) assert the mask canvas after pointer-up equals a fresh replay (compare `exportMask()` bytes or sampled pixels before/after Undo→Redo); (c) Background: bounding boxes of the base image and the overlay match within 1 px at two viewport sizes and for a portrait and a landscape upload; (d) Face & Pose: upload a 3000×2000 synthetic image, assert the thumbnail is ≤ 160 px tall and that the view scrolls (`scrollHeight > clientHeight` reaches the Run button with `scrollIntoView`), and no horizontal page overflow.
- Vitest: a unit test for any pure helper you add (for example a rect-restore helper with a canvas mock that records the composite ops).
- `make check` and `make e2e` green.

## Acceptance criteria
- In the real Studio on the laptop, brushing back and forth leaves a visible stroke path immediately, for brush and eraser at 100 % and 50 % opacity; undo/redo behave as before.
- The Background mask overlay sits exactly on the subject in a maximised and a half-width window.
- Face & Pose with large uploads keeps every control reachable by scrolling; thumbnails are small; nothing runs off the right edge.
- The new Playwright checks fail on `main` before the fix and pass after (note both runs in the Phase Log).

## Phase-specific docs
CHANGELOG `[Unreleased]` → Fixed (three entries); `docs/P11_ARCHITECTURE.md` → Inpainting (one line on the dirty-box restore); user guide only if a screenshot changed. Then the standard close-out checklist.
