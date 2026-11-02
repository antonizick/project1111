# P11 Phase 10: Inpainting & mask editor

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 08 · **Branch:** `phase-10-inpainting` · **Worktree:** `../project1111-phase-10` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §4 (Inpainting), §6, §11.2 R5, R6, R10, R18, R24, §11.3 S3, S4, S8, Appendix B. Phase Log entries for 04, 05, 06, 07 and 08. ADR-0007.

## Goal
Fixing or changing part of an image is first-class. You open any result or an uploaded photo in Inpaint, brush a mask, optionally type what should be there, pick "subtle fix" or "major change", and apply. The result chains back into the gallery, and templates can capture it. The **mask editor** built here is reused by Phase 11 (background) and Phase 12 (pose/face regions).

## Tasks
1. **Mask editor component** (`frontend/src/features/mask-editor/`): canvas over the image with brush, eraser, brush size (`[`/`]`), hardness/opacity, feather, invert, clear, undo/redo (Ctrl+Z/Ctrl+Shift+Z), zoom/pan (wheel/space-drag), show/hide mask overlay. Pointer, pen pressure if available, touchpad-friendly. Output: a single-channel PNG mask at image resolution. Performance: 60 fps on a 2560×1440 image on the laptop.
2. **Inpaint view:** open from result panel, gallery, or "Upload photo" (Phase 07 upload validation); prompt (prefilled with the original prompt), denoise presets **Subtle fix / Change / Replace** (exact strengths tuned on the default model, see task 4), "only masked area at full resolution" toggle (crop-and-paste-back with padding, so small fixes keep detail), Apply. Advanced: denoise slider, mask blur, padding, steps, seed.
3. **Compiler step** (`recipe/steps/inpaint.py`, registered with Phase 04's registry): graphs using the engine's core inpaint nodes with the base model's inpaint conditioning; if Phase 03/06 measured a dedicated inpaint checkpoint or model patch worth it on 8 GB, use that via the manifest. Read node names and inputs from the pinned ComfyUI source. Crop-and-stitch done in P11 (`media/`) or with core nodes; no custom node without an ADR (S3).
4. **Tuning on the laptop:** for the default model, test the three presets on 10 synthetic or P11-generated images (faces, hands, objects, backgrounds; no personal photos in the repo) and pick strengths, blur and padding; record results and timings in `docs/P11_BENCHMARKS.md`.
5. **Recipe integration:** an `Inpaint` step stores the mask as an input file reference with the run; "Save as Template" captures it (mask as a slot or fixed, user's choice); outputs link to their parent image in the gallery (`parent_id`).
6. **Manifest:** add any inpaint-specific model with verified URL, hash, size and licence (Phase 06 schema).
7. **E2E:** Playwright test drawing a mask programmatically, applying, and counting actions (Appendix B inpaint path ≤ 4 after the result exists).

## Out of scope
Automatic subject segmentation (11), face-specific tools (12), outpainting (follow-up if wanted).

## Tests
Mask editor unit tests (undo stack, mask export at correct resolution, invert/feather), crop/paste-back geometry tests (property tests for bounds and padding), compiler golden files for the inpaint step, FakeEngine e2e, `gpu` test inpainting a fixture with each preset and asserting unmasked pixels are unchanged outside the blend band.

## Acceptance criteria
- On the laptop: inpaint a region of a 1920×1080 result with each preset without OOM; unmasked areas stay intact; the result appears as a child in the gallery.
- A template saved from an inpaint chain re-runs end to end.
- Mask editor stays responsive on 2560×1440 (record frame timing).
- `make check` and `make gpu-test` green.

## Phase-specific docs
`docs/P11_USER-GUIDE.md` (Inpaint), `docs/P11_ARCHITECTURE.md` (mask editor component, inpaint step), `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES/manifest if a model was added, CHANGELOG. Then the standard close-out checklist.
