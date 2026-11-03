# P11 Phase 14: Upscaling, style presets & logo text

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 09 · **Branch:** `phase-14-quality-presets` · **Worktree:** `../project1111-phase-14` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §4 (Generation, Templates, Quality), §5, §11.2 R3, R9, R17, R18, R23, §11.3 S4, S5. Phase Log entries for 03, 06, 08 and 09. `docs/P11_BENCHMARKS.md`. ADR-0010.

**Phase 04 results (2026-11-02 18:27 CST):** `TextOverlay` (schema v1: `text, font, size_pct, colour, position, margin_pct, stroke_px, stroke_colour, shadow, also_prompt_model`) has no compiler yet and `compile()` raises `UnsupportedStepError` for it. Text overlay runs in Pillow, not in the engine, so extend the compile driver with a local (non-engine) step output and record it in an ADR. Upscale chains: `Generate.quality` switches to the preset's `quality_chain` (provisionally `latent`), `Generate.chain` forces one; the `Upscale` step supports `model | latent | both` with `scale` or `width`/`height`. Presets live in `recipe/presets.py` (one table).

**Phase 06 results (2026-11-02 23:09 CST):** the Models page mirrors `p11 models … --json` (ADR-0021): `ModelStatus.as_json()` has `id, name, kind, base, state (installed|missing|corrupt|user-added|unregistered), origin (manifest|user|disk), filename, path, size, sha256, verified, enabled, sets, format, licence {name, url, commercial_use, flags, accepted}, detail`. Install through `ModelManager.install(target, downloader=…, accept_licences=…, confirm=…, progress=(label, done, total))` after `plan(target)` (gives `to_fetch`, `to_accept` and `download_bytes` for the size and licence dialog); add with `ModelManager.add(path, kind=…, allow_pickle=…)`; `set_enabled`, `remove(id, delete_file=…)`, `verify(ids)`. A new LoRA goes into `models/manifest.toml` with the same schema (verified facts, a `# Checked <TS>` comment, `commercial_use`).

## Goal
Output quality is good by default and fast when you want it. Upscaling has a clear Quality/Speed toggle. The 3D animated avatar preset is dialled in. Logos get exact, crisp text through a deterministic overlay step. Logo work gets variations and batch help. The model manager UI turns `p11 models` into a page.

## Tasks
1. **Upscale toggle (ADR-0010):** expose **Speed** (model upscaler only) and **Quality** (model upscaler + low-denoise refinement pass, tiled if needed for 2560×1440 in ~7 GB) in Simple mode, per preset; standalone **Upscale** action on any image (×1.5/×2/to-wallpaper). Values from Phase 03 measurements; re-measure and record times. **Phase 03 results (2026-11-02 18:08 CST):** Speed = `model` chain (~18 s per wallpaper with the default model); refinement measured as `latent` (45 / 66 s at 1920×1080 / 2560×1440) and `both` (55 / 88 s), both without OOM. ADR-0010 is already Accepted with `latent` as the provisional Quality chain; confirm `latent` vs `both` by eye and update ADR-0010. Mark ADR-0010 Accepted.
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
