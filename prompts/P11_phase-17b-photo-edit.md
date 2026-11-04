# P11 Phase 17b: Edit a photo from a prompt (image-to-image)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 17 · **Branch:** `phase-17b-photo-edit` · **Worktree:** `../project1111-phase-17b` · **Gate:** auto

After v1.0.0 Nick asked for a way to start from his own picture on the Generate tab: upload a photo, type what it should become, and get a re-rendered version. Today P11 can only edit an existing picture through Inpaint (masked) or Background; Generate always starts from an empty latent. This phase adds SDXL image-to-image to the Generate step with a "how much to change" control, keeping the S5 boundary for photos of people. It can run in parallel with 17a and 17c (merge after 17a; both touch `theme.css`).

## Read first
`CLAUDE.md` (Content boundary), `prompts/P11_shared-instructions.md`, spec §11 Amendments (A5, R3, R5, R6, R18, S5, S6, S8). Phase Log entries for 04, 08, 10, 12 and 16. ADR-0007, ADR-0010, ADR-0019, ADR-0025, ADR-0029, ADR-0032 (additive schema changes), ADR-0037, **ADR-0038** (this feature). `docs/P11_ARCHITECTURE.md` → Recipe compiler, Studio UI. `docs/P11_THREAT-MODEL.md` T8 (re-uploaded likeness).

## Nick's request (verbatim intent, 2026-11-04 07:25 CST)
"On the generate tab, create an option for a user to upload an image and then to a prompt give instructions on how to modify re-render following the prompt the provided image. For example, take the picture of this man and dress him as Indiana Jones, OR Take this picture of the house and paint it green and widen the driveway in front of it OR Here's a picture of an empty room. Fill it with furniture and an aesthetic way. Give it a modern feel."

## Decisions already made
- **ADR-0038:** plain SDXL image-to-image on the installed default checkpoint (no new model, no new custom node, no download). The prompt describes the wanted result; a strength control sets how much changes. An instruction-following edit model (FLUX Kontext, CosXL Edit and the like) is a recorded follow-up, not this phase.
- **ADR-0038, S5:** an edit whose source is an uploaded file and shows a detected face, or whose source is a likeness gallery image (ADR-0037), has every output checked by the S5 guard (`check_likeness`), failing closed. This is required by the content boundary and not open to the phase's judgment.
- Placement: 17b after 17, parallel with 17a/17c; release v1.0.1 in 17d (ADR-0040).

## Goal
On the Generate tab, Nick picks **Start from a photo**, uploads (or drags in, or uses a gallery image via a result/detail action) a picture, writes a prompt, chooses a strength, and presses Generate. P11 re-renders the picture at its own aspect ratio following the prompt, keeping its composition at low strength and reinventing it at high strength. The run is a normal recipe: it lands in the gallery with its sidecar, can be varied, upscaled, inpainted, and saved as a template with the photo as an image slot.

## What exists (verified 2026-11-04 07:40 CST; re-check before relying on it)
- **Schema:** `src/p11/recipe/model.py:Generate` has `prompt, negative, style, aspect, model, vae, loras, sampler, chain, quality, batch_size`; no input image and no denoise. `Upscale` already has `image_slot` + `denoise` + `prompt`, and `Recipe.source_image: FileRef | None` exists (used by `frontend/src/features/generate/form.ts:upscaleRecipe` with `{ref: "gallery/<id>"}`). Image inputs resolve through `CompileContext.resolve_input(slot)` → slot, previous step, else `source_image` (`compile.py` ~line 280), and `ctx.load_image(g, slot)` adds the `LoadImage`.
- **Compiler:** `src/p11/recipe/compile.py:compile_generate` builds checkpoint/VAE/LoRA/CLIP nodes, applies modifiers (`_MODIFIERS`: pose, reference), then `EmptyLatentImage` at the aspect preset's native bucket → `KSampler(denoise=1.0)` → upscale chain (ADR-0010). Inpaint denoise presets live in `src/p11/recipe/presets.py:INPAINT_PRESETS` (pattern to copy). Golden-file tests: `tests/unit/` compiler goldens.
- **Default model:** `realvisxl5-lightning` (SDXL Lightning, few steps; ADR-0018). Lightning img2img uses `steps × denoise` effective steps, so tune steps per strength rather than reusing the text-to-image count.
- **S5:** `src/p11/jobs/runner.py:Runner.inputs_carry_likeness(recipe, bindings, parent)` flags only *gallery* inputs from likeness runs (ADR-0037); an uploaded photo of a real person is unflagged (threat model T8). Face detection is `src/p11/media/faces.py:detect_faces(image, kit)` (YuNet, CPU); the guard is `src/p11/media/nsfw.py:check_likeness(guard, image)`. Both need the `face` model set (`yunet-2023mar`, `nsfw-*` are in sets `face`, `full`, not `default`).
- **Same gap today:** Inpaint (`recipe/steps/inpaint.py`) and Background (`recipe/steps/background.py`) on an *uploaded* photo of a person also skip the guard. Close it with the same helper (task 5).
- **UI:** `frontend/src/features/generate/GenerateView.tsx` (Simple form + `AdvancedDrawer.tsx`), `form.ts` builds the recipe; uploads go through `client.upload(blob, "image")` (`POST /api/uploads?kind=image`, validated server-side, Phase 07); result actions are in `frontend/src/features/actions.tsx`.

## Tasks
1. **Schema (additive, ADR-0032 style; no version bump unless a migration is needed):** add to `Generate` an optional `image_slot: str | None` (image kinds) and `denoise: Unit | None` plus `denoise_preset: Literal["light", "change", "reimagine"] | None`; with no input image the step behaves exactly as today. Text-to-image recipes and templates round-trip unchanged (golden tests).
2. **Compiler:** when the step has an input image (slot, else `source_image`; never the previous step unless the recipe asks for it), `compile_generate` loads it, scales it to the model family's native bucket nearest its own aspect ratio (default: keep the photo's aspect, ignore the aspect preset; the output size is the bucket, then the usual upscale chain toward the photo's original size, capped by the wallpaper presets), `VAEEncode`s it and samples with the chosen denoise. Add `IMG2IMG_PRESETS` to `presets.py` (starting points 0.35 / 0.55 / 0.75, steps tuned for Lightning), tuned on the laptop in task 6. Batch > 1 repeats the latent. Pose/reference modifiers still apply.
3. **Generate UI (Simple mode first, R18):** a **Start from a photo** control (upload button + drop zone; a thumbnail with Remove), visible strength chips **Light touch / Change / Reimagine** (Advanced: a 0.10–0.95 slider), help text under the prompt: "Describe the picture you want, for example *a man in a leather jacket and fedora, adventurer outfit*. Higher strength changes more but keeps less of the original." The aspect chips are disabled with a note while a photo is set. Generate with a photo shows in progress and results like any run. Add a **Use as starting photo** action to result/detail images (`features/actions.tsx`). Keyboard reachable, visible focus, no layout overflow (17a's lessons: `docs/P11_ARCHITECTURE.md` → Studio UI → "Layout rule"; bound the photo thumbnail like `.thumb`, max 160 px tall, and check it in Chromium as `frontend/e2e/ui-fixes.spec.ts` does).
4. **Templates:** `capture_template` turns the photo into an image slot (`Start photo`) so "Save as Template" (≤ 3 actions) and one-click re-run with a new photo work; starter templates are not changed.
5. **S5 for edits of uploaded photos (ADR-0038):** extend the runner's likeness rule with a helper (for example `Runner.upload_shows_face(ref)`) that runs `detect_faces` on any *uploaded* input image of a Generate-with-photo, Inpaint or Background job; a face → the job's outputs go through `check_likeness` and the sidecar gets `likeness = True`, so later edits inherit it. If the `face` set is missing, an edit of an **uploaded** photo is refused before queueing with a plain-English hint ("Editing an uploaded photo needs the face safety models: run `p11 models install face`"); gallery images P11 made without likeness are not affected, and text-to-image is never checked (A5). Record the measured cost (detector on a 1920×1080 photo) in the ADR's consequences.
6. **Laptop tuning (GPU lock, R24):** on 6 synthetic/P11-generated photos (a person, a house, an empty room, two products, a landscape; no real people, S6) run each preset; pick defaults; record time per image and peak VRAM at 1024² and 1344×768 in `docs/P11_BENCHMARKS.md`. Keep every run within the ~7 GB budget (R5).
7. **API/CLI parity:** the existing jobs API accepts the new fields with no route change; document a `curl` example in the user guide.
8. **Follow-up note:** add an "Instruction-edit model" row to the plan's deferred follow-ups (candidates, licences and VRAM checked at the source with the date) so a later `/phase-add` can pick it up.

## Out of scope
An instruction-following edit model or new custom node (ADR-0038 follow-up); masked img2img on the Generate tab (Inpaint already does masked edits; link to it in the help text); video; the 17a fixes; any change to text-to-image defaults.

## Tests
- Unit: schema round-trip and defaults (no image → identical graph to today's goldens); compiler goldens for img2img with slot and with `source_image`, each preset, batch 2, with a pose modifier; aspect/bucket choice for portrait, landscape and square photos; template capture makes a `Start photo` slot.
- Runner: an uploaded photo with a synthetic face → outputs go through a stub guard and are blocked when it says sexual; without the `face` set → refused before queueing; a non-face upload → no guard call; a non-likeness gallery source → no guard call; Inpaint and Background on an uploaded face photo → guarded.
- Vitest: Generate form with a photo builds the expected recipe; aspect chips disabled; strength chips.
- Playwright (FakeEngine): upload → prompt → Light touch → Generate → result in gallery, ≤ 5 actions; Use as starting photo from a result.
- `gpu` test: one img2img run per preset on a fixture photo, no OOM, output size as computed.
- `make check`, `make e2e`, `make gpu-test`.

## Acceptance criteria
- In the real Studio on the laptop: an uploaded empty-room photo with "a modern furnished living room, sofa, rug, plants, warm light" at **Change** returns a furnished room in the same perspective; a house photo with "the same house painted green, wider driveway" at **Change** keeps the house recognisable; a synthetic person photo with an outfit prompt changes the clothes at **Change**, and the S5 guard ran on its output (visible in the log/sidecar).
- Text-to-image is unchanged (goldens and the daily-workflow e2e pass).
- Times and VRAM per preset recorded in benchmarks; ADR-0038 updated with the measured consequences.

## Phase-specific docs
CHANGELOG `[Unreleased]` → Added (photo edit) and Security (guard on edits of uploaded photos of people); user guide (new section "Start from a photo" with the three examples and what strength does); `docs/P11_ARCHITECTURE.md` (Generate img2img path, the upload face rule); `docs/P11_THREAT-MODEL.md` T8 (narrowed); ADR-0038 consequences; README feature list. Then the standard close-out checklist.
