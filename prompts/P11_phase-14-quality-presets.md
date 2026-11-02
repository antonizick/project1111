# P11 Phase 14: Upscaling, style presets & logo text

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 09 · **Branch:** `phase-14-quality-presets` · **Worktree:** `../project1111-phase-14` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §4 (Generation, Templates, Quality), §5, §11.2 R3, R9, R17, R18, R23, §11.3 S4, S5. Phase Log entries for 03, 06, 08 and 09. `docs/P11_BENCHMARKS.md`. ADR-0010.

## Goal
Output quality is good by default and fast when you want it. Upscaling has a clear Quality/Speed toggle. The 3D animated avatar preset is dialled in. Logos get exact, crisp text through a deterministic overlay step. Logo work gets variations and batch help. The model manager UI turns `p11 models` into a page.

## Tasks
1. **Upscale toggle (ADR-0010):** expose **Speed** (model upscaler only) and **Quality** (model upscaler + low-denoise refinement pass, tiled if needed for 2560×1440 in ~7 GB) in Simple mode, per preset; standalone **Upscale** action on any image (×1.5/×2/to-wallpaper). Values from Phase 03 measurements; re-measure and record times. Mark ADR-0010 Accepted.
2. **3D animated avatar preset (R17):** tune prompt prefix/suffix, negatives, LoRA(s) if Phase 03/06 found a suitable licensed one (add to the manifest with verified facts), and default aspect 4:5; make the starter template use it with an optional face slot (Phase 12's swap if available).
3. **Text overlay step** (`recipe/steps/text_overlay.py`, `media/text.py`, R23): Pillow rendering with bundled open-licence fonts (3–5 families from Google Fonts/OFL, verified licences, files in `assets/fonts/` with their licence texts), options: text, font, weight, size (auto-fit to box), colour/gradient, outline, shadow, alignment, position (draggable box in the UI), letter-spacing; output at full resolution. Optional "let the model try text" toggle keeps the diffusion text instead.
4. **Logo helpers:** batch of 4–8 variations in a grid with "pick → refine" (inpaint/upscale/text), a transparent-background export (using Phase 11's segmentation when present, else a flat-colour key), square and favicon size exports (512, 256, 128, 64, 32 PNG + ICO).
5. **Starter template update:** logo starters gain the text overlay with a `logo text` slot; re-tune all starter prompts on the default model.
6. **Prompt defaults:** review default positive/negative prompts for photoreal, avatar and logo against 10 prompts each on the laptop; record before/after notes (no images committed except FakeEngine-safe docs images).
7. **Models page** (`frontend/src/features/models/`): list by kind with installed/missing/corrupt/user-added state, size, licence flags, sets; install a set (with licence acknowledgement dialog and total size), verify, enable/disable, remove, add from file (Phase 06 API, safetensors policy S4). Downloads show progress via the event stream.

## Out of scope
New engine features, training, cloud fonts.

## Tests
Text layout unit tests (auto-fit, multi-line, alignment, no clipping), font licence files present, compiler golden files for upscale modes and text overlay, Vitest for the models page and text box editor, Playwright e2e (logo template with text slot → image with exact text; models page install flow on a local test server), `gpu` test for Quality upscale at 2560×1440 without OOM.

## Acceptance criteria
- On the laptop: both upscale modes work for both wallpaper presets without OOM, with times recorded; a logo template produces crisp, correctly spelled text; the avatar template gives consistent results across seeds.
- Models page can install, verify and remove a small test model.
- `make check` and `make gpu-test` green.

## Phase-specific docs
`docs/P11_USER-GUIDE.md` (upscaling, logos, avatar, models page), `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES (fonts, any LoRA), ADR-0010 status, CHANGELOG. Then the standard close-out checklist.
