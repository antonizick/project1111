# P11 Phase 17g: Inpaint default, gallery thumbnail sizes and a gallery picker

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 17e · **Branch:** `phase-17g-inpaint-gallery-picker` · **Worktree:** `../project1111-phase-17g` · **Gate:** review

Nick's next feedback round, after confirming the four 17e items. His dress test showed that Inpaint's default crop makes large edits fail: with **Only masked area at full resolution** on, the model sees only the box around the mask and paints a small complete person inside it. He also wants a denser gallery view, and wants to reuse pictures P11 already holds wherever a photo is asked for, instead of finding the file on disk. This work goes into v1.0.2 (17f now depends on it).

## Read first
`CLAUDE.md` (Content boundary), `prompts/P11_shared-instructions.md` (§4, including the 17e rebuild-and-restart and real-Studio rules), spec §11 Amendments (S1, S5, S6). Phase Log entries for 17b, 17e and the planning entry for this phase. ADR-0025, ADR-0037, ADR-0038, **ADR-0045**, **ADR-0046**.

## Nick's request (verbatim intent, 2026-11-04 17:34 CST)
1. "Make the \"Only masked area\" off by default"
2. "In the gallerycan we have 2 thumbnail sizes available? Small and Medium (current size)?"
3. "Anywhere there is an option to upload an image \"Choose File\" button, Can we also create a mechanism to select an existing image in the P11 gallery?"

## Decisions already made
- **ADR-0045:** the Inpaint **form** defaults to crop off. The schema default `Inpaint.crop = True` stays, so saved recipes, templates, goldens and API scripts behave as before. The checkbox stays, so small fixes can still turn it on.
- **ADR-0046:** the picker hands over `gallery/<id>` references and **never** fetches the bytes and re-uploads them. A re-upload is a new, unflagged input and would launder the S5 likeness flag (ADR-0037). This is not open to a change of approach.
- **Scope of item 3:** every control that takes an **image**. Not the Video clip input (gallery holds images), not the JSON template import, not `mask` slots in the Run dialog (a gallery picture is not a mask).
- **Defaults you may change with a reason in the Phase Log:** Small tile 120 px with the existing `?size=256` thumbnail (no backend change); the button is labelled **From gallery**; the picker is a `Dialog` opened beside the file input.

## Goal
Inpaint on a fresh form has the crop off. The gallery toolbar switches between Small and Medium and remembers the choice. Every image input in the Studio offers **From gallery** next to choosing a file, and a picked image behaves exactly like one handed over from a result, with the S5 guard unchanged.

## What exists (verified 2026-11-04 17:34 CST; re-check before relying on it)
- **Crop:** `frontend/src/features/inpaint/recipe.ts:initialInpaint` sets `crop: true`; `InpaintView.tsx:fromImage` carries `crop: f.crop` across images; `src/p11/recipe/model.py` `crop: bool = True` (tests in `tests/unit/test_inpaint.py` rely on it); `recipe.test.ts` asserts `crop: true` for the default form. The guide says "(on by default)" at section 5 and has a "Changing clothes" paragraph from 17e. With the crop off on a large photo, `src/p11/media/inpaint.py:work_size` scales the whole image to at most `INPAINT_MAX_PIXELS` (2560×1440): measured 2 min 10 s on 3479×5218, about 30 s on 1067×1600 (17e).
- **Gallery tiles:** `frontend/src/features/gallery/layout.ts` has fixed `TILE = 200`, `GAP`, `ROW`, `columnsFor`, `layoutRows`, `totalHeight`, `visibleRows`. `GalleryView.tsx` positions tiles with them and asks `${img.thumb}?size=256`. `THUMB_SIZES = (256, 384, 512)` in `src/p11/api/routes/gallery.py`. `GET /api/gallery` takes `q`, `limit`, `offset` and filters.
- **The ten image controls:** `GenerateView.tsx` (Start from a photo, `takePhoto`); `InpaintView.tsx` (`uploadPhoto`); `BackgroundView.tsx` (`uploadSubject`, `uploadBackground`); `FaceView.tsx` (Picture, Face photo, Pose photo, reference, all through `upload(file, into)`); `VideoView.tsx` (`pickFace`); `templates/RunDialog.tsx` (`take`, image slots only).
- **Hand-offs already exist:** `features/generate/form.ts:225` builds a photo from a gallery image with `galleryId` (which also sets the job's `parent`); `InpaintView.fromImage` and `BackgroundView` have a gallery source; `FaceView.tsx:119` builds a `Picked` with `ref: gallery/<id>`. `features/face`, `background`, `text` and `video` routes document that they accept `gallery/<id>`. Reuse these rather than adding parallel paths.
- **Guard:** `src/p11/jobs/runner.py:inputs_carry_likeness` covers `source_image`, bound `FileRef` slots and `parent`. **Check** whether each control's reference reaches it: a pose photo, a reference image or a background photo that is not a slot or source would be a gap for pictures carrying a likeness. `src/p11/api/routes/background.py`, `face.py` and `video.py` have their own `gallery/` handling.
- `components/Dialog.tsx` is the modal (focus trap, Esc). Gallery image URLs load through the session cookie, as in the gallery.

## Tasks
1. **Inpaint default.** `crop: false` in `initialInpaint`, with `recipe.test.ts` updated. Leave the schema default alone. Add one line of help under the checkbox: on suits small fixes, off suits anything large such as clothes.
2. **Thumbnail sizes.** Make the layout functions take the tile size (pure, tested). Add a Small / Medium control to `.gallery-toolbar`, keyboard reachable with visible focus, Medium the default. Remember the choice in `localStorage` wrapped in try/catch, like a per-viewer convenience. Keep virtualization correct when switching (scroll position, row heights, selection).
3. **Gallery picker component.** `frontend/src/components/GalleryPicker.tsx` (or `features/gallery/`): a **From gallery** button plus a `Dialog` with search, a paged grid of small thumbnails (image alt text, keyboard selection), an empty-gallery message, and `onPick(entry: ImageEntry)`. It returns the gallery entry, never bytes (ADR-0046). No network assets (S1).
4. **Wire the ten controls** through their existing gallery hand-offs, so `parent` and `galleryId` are set where they are today. Dropzones and file choosing keep working. In `RunDialog` only for image slots, with the value `{ref: "gallery/<id>", name}`.
5. **Guard check (S5).** For each control, test that a picture from a likeness run still triggers the guard when picked. Close any gap in the runner or route at the root, with a failing test first. Never weaken the guard. A gap you cannot close in scope blocks the phase; do not ship that control.
6. **Errors.** A picked image deleted before the job runs gets the existing plain message. Non-image gallery entries, if any, are not offered.
7. **Docs:** user guide section 3 (sizes), section 5 (the default, rewriting 17e's "Changing clothes" paragraph so it no longer says to turn the setting off, and noting that small fixes run faster and sharper with it on), and a short note that every photo input offers From gallery. `docs/P11_ARCHITECTURE.md`, `docs/P11_THREAT-MODEL.md` (the ADR-0046 rule), CHANGELOG `[Unreleased]`. Update the 17e deferred follow-up row on large masks.
8. **Walk-through (interactive; hands-off mode pauses at the Gate):** after the merge, rebuild and restart (shared instructions §4), ask Nick to try all three in his own window. Record his answer in the Phase Log with a timestamp.

## Out of scope
A negative-prompt field on Inpaint (deferred follow-up). Switching the crop automatically by mask size. A third thumbnail size. Picking videos or masks from the gallery. Resizing photos inside P11. The v1.0.2 release (17f).

## Tests
- Vitest: `initialInpaint` default; layout with both tile sizes; the size control and its storage (including storage that throws); the picker (search, paging, empty, keyboard, `onPick`); each control's hand-off produces a `gallery/<id>` reference.
- Unit: `tests/unit/test_likeness_guard.py` gains a case for each input kind from task 5.
- Playwright: Small and Medium column counts and no horizontal overflow at 1280×720 and 1918×2130; From gallery end to end on Generate, Inpaint and one Face control, with a network assertion that picking sends no `POST /api/uploads`; axe on the picker. Run once in Brave (`P11_E2E_BROWSER=/usr/bin/brave`).
- `make check`, `make e2e`; `make gpu-test` is not needed unless engine-facing code changes.

## Acceptance criteria
- A fresh Inpaint form has **Only masked area** unchecked, in the real Studio. A saved recipe or template with `crop: true` still crops.
- The gallery switches between Small and Medium, Medium looks as it does today, and the choice survives a reload.
- All ten controls offer From gallery, and a picked image runs a job successfully on at least Generate, Inpaint, Background and Face.
- Picking uploads nothing, and a picture from a likeness run stays guarded through every control.
- Nick confirms all three in his own window (Phase Log, timestamped). Without that the phase does not claim them.

## Phase-specific docs
As in task 7, plus the vault note. No host OS change is expected.

Then the standard close-out checklist.
