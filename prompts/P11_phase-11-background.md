# P11 Phase 11: Background replacement

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 10 · **Branch:** `phase-11-background` · **Worktree:** `../project1111-phase-11` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §4 (Background Replacement), §11.2 R6, R10, R12, R24, §11.3 S3, S4, S6, S8, Appendix B. Phase Log entries for 06, 07 and 10. ADR-0007.

**Phase 04 results (2026-11-02 18:27 CST):** `ReplaceBackground` (schema v1) has `image_slot, background_slot, mask_mode (auto|manual), mask_slot, segmentation_model, colour_match, feather_px, relight, relight_denoise`; register its compiler with `register_step("replace_background", fn)` (see Phase 10's note for the context API). Compositing done outside the engine is not yet a compiler output: `compile()` only returns engine graphs, so either express it with engine nodes or extend the driver with a local-step kind (as Phase 14 must for text overlay) and record the choice in an ADR.

**Phase 05 results (2026-11-02 19:28 CST):** the FakeEngine only accepts node types in `p11.engine.fake.KNOWN_NODES`; add segmentation/compositing nodes you introduce there (the gpu test `test_known_nodes_exist_in_pinned_engine` checks them against `/object_info`).

**Phase 06 results (2026-11-02 23:09 CST):** add models to `models/manifest.toml` with the schema in `src/p11/models/manifest.py` (ADR-0021): `id, name, kind, base (sdxl|sd15|any), files = [{url (HF `/resolve/<commit>/`), filename, sha256, size}], licence {name, url, commercial_use, flags}, requires_login, sets, scale, source, notes`, plus a `# Checked <TS>: …` comment saying what was verified. Kinds and folders: `KIND_FOLDERS` (`facerestore/`, `faceswap/`, `facedetect/`, `segmentation/`, `controlnet/`, `ipadapter/`; `facedetect` is new, and ComfyUI only sees a folder listed in `engine/extra_model_paths.yaml.tmpl`, so add the key a custom node expects there). Non-`.safetensors` formats (ONNX, pickle-only face models) are not loaded through `p11 models add`; curated entries are hash-pinned, which S4 allows. Put new entries in `full` or an `optional` set, never silently into `default` (≤ 30 GB). Tests can serve fake weights with `tests/fixtures/model_server.py` and `parse_manifest(text, loopback_http=True)`.

## Goal
Replacing a background with a photograph takes one click. You open an image, P11 finds the subject automatically, you refine the edge with the Phase 10 mask editor if needed, drop in a background photo (or describe one), and press **Replace Background**. The subject is blended in with matched colour and light, and the step can be captured in templates. This matters most for logo and product shots.

## Tasks
1. **Segmentation model choice:** shortlist subject/background segmentation models that run in ~7 GB alongside nothing else (the engine model can be unloaded first). Verify licences at the source: prefer a permissive default; a stronger non-commercial model may be an opt-in manifest entry flagged `non-commercial` (R12). Decide whether it runs inside the engine (core node or a pinned custom node, with an ADR per S3) or in P11 via onnxruntime-gpu/torch in the P11 env. Record an ADR with measured quality (on synthetic/P11-generated images) and speed.
2. **Manifest entries** for the chosen model(s): URL, hash, size, licence, flags (Phase 06 schema).
3. **Background view:** open from result/gallery/upload; auto-mask on open (with a spinner), mask overlay toggle, **Refine** (opens the mask editor seeded with the auto-mask), background source: **Photo** (upload, Phase 07 validation), **Describe** (generate a background from a prompt at the image's size), **Colour/transparent** (export PNG with alpha). Options: fit (cover/contain/position drag), subject scale/position, edge feather, **Colour match** (on by default), **Harmonize** (a low-denoise inpaint pass over the edge band and/or whole image to unify light; strength presets Off/Light/Strong), shadow (simple drop/contact shadow toggle).
4. **Compositing and blending** (`media/composite.py`, pure where possible): alpha compositing with feathered mask, colour transfer (e.g. LAB mean/std or histogram matching) from background to subject at a chosen strength, edge decontamination (spill removal), then the optional harmonize pass compiled through the inpaint step (Phase 10).
5. **Compiler step** `ReplaceBackground` (`recipe/steps/background.py`): segmentation (or a stored mask) → composite → optional harmonize → optional upscale; stores the background as a slot (default) so templates like "Product on my studio background" re-run on new subjects with one slot fill.
6. **Laptop tuning:** pick defaults for colour match and harmonize strength on 10 synthetic/generated test pairs; record timings and VRAM (segmentation + engine must not be resident together if that would exceed ~7 GB: unload in between) in `docs/P11_BENCHMARKS.md`.
7. **E2E:** Playwright path: open result → Background → choose photo → Apply → Save; ≤ 5 actions (Appendix B).

## Out of scope
Video backgrounds, relighting with 3D/depth models (follow-up if wanted), face tools (12).

## Tests
Composite and colour-transfer unit tests (alpha correctness, no clipping, idempotence at strength 0), segmentation adapter tests with a stub model, compiler golden files, FakeEngine e2e, `gpu` test on fixtures (mask IoU against a synthetic ground-truth mask ≥ a threshold you record).

## Acceptance criteria
- On the laptop: a P11-generated portrait/product image gets a new photo background in one Apply, with no visible halo at 100 % zoom in the default settings (screenshots kept local), within the time recorded in benchmarks.
- A template with a background slot re-runs on a new subject image.
- Licence of every added model recorded with flags; `make check` and `make gpu-test` green.

## Phase-specific docs
`docs/P11_USER-GUIDE.md` (Background), `docs/P11_ARCHITECTURE.md`, `docs/P11_BENCHMARKS.md`, THIRD_PARTY_NOTICES, ADRs (segmentation model, where it runs), CHANGELOG. Then the standard close-out checklist.
