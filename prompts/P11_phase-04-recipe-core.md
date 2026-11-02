# P11 Phase 04: Recipe core, compiler & output layout

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 02 · **Branch:** `phase-04-recipe-core` · **Worktree:** `../project1111-phase-04` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §4 (Generation, Templates), §6, §11.2 R3, R6, R7, R8, R17, R18, R19, R23, §11.3 S5, S6, Appendix B. Phase Log entries for 00 and 02; **Phase 03's entry if it has finished** (its presets and defaults override the provisional values here). ADR-0007, ADR-0010.

## Goal
Every part of P11 that can be pure is pure, typed and well tested: the recipe model with versions and migrations, input slots, seed strategies and presets, the **compiler** from recipes to ComfyUI API graphs (generation and upscale chains now; inpaint, background, face, pose and video steps are added later through the same extension point), and the output layout with sidecar and PNG metadata and a gallery index. Phase 03 runs in parallel and owns the real numbers. Build against provisional preset values in one table and swap in 03's when its ADR lands.

## Tasks
1. **Recipe schema** (`recipe/model.py`, Pydantic v2, frozen): `Recipe {schema_version, id, name, tags, folder, steps: list[Step], slots: list[Slot], seed: SeedStrategy, created_at, source_image?: ref}`. `Step` is a discriminated union: `Generate`, `Upscale`, `Inpaint`, `ReplaceBackground`, `FaceSwap`, `Pose`, `Reference`, `TextOverlay` (later phases fill the bodies of the last six; define their fields now, from spec §4 and R23, so templates are stable). Model references are `ModelRef {manifest_id, sha256?}`, never paths. `Slot {name, kind: text|image|face_image|background_image|video, required, default?}`. `SeedStrategy = fixed(n) | random | increment(from)`.
2. **Versioning** (`recipe/migrate.py`): `schema_version` int, `migrate(dict) → Recipe` chain with tests for each step. Unknown future versions are refused with a clear error.
3. **Presets** (`recipe/presets.py`): aspect/wallpaper presets carrying both the generation bucket and the output size and upscale chain (R3, ADR-0010): provisional `16:9 1920×1080`, `16:9 2560×1440`, `1:1 1024`, `logo 1:1`, `avatar 4:5`, plus style presets (`photoreal`, `3d-animated-avatar` (R17), `logo-flat`, `logo-3d`) with default prompt prefixes/suffixes and negatives. One table, clearly marked "provisional until ADR (Phase 03)".
4. **Compiler** (`recipe/compile.py`): `compile(recipe, bindings, registry) → list[EngineGraph]` producing ComfyUI **API-format** graph dicts from core nodes only (checkpoint loader, CLIP text encode, empty latent, KSampler, VAE decode/encode, latent upscale, model upscaler, save/preview). Read the node class names and input names from the ComfyUI source at the commit pinned in `engine/engine.lock.toml` (if 03 hasn't pinned yet, use its latest release tag and note it). A registry of step compilers (`register_step(StepType, fn)`) is the extension point later phases use. Slot bindings are validated (missing required slot → error naming the slot). Deterministic: same input → byte-identical JSON.
5. **Run metadata** (`outputs/metadata.py`): `RunRecord {recipe, bindings (file refs, not contents), seed used, model hashes, engine version, timings, step outputs}`. Write a sidecar `.json` and embed the recipe in PNG `tEXt`/`iTXt` chunks; `read_recipe_from_png(path)` round-trips; `strip_metadata(path) → bytes` for export (R7).
6. **Output layout** (`outputs/layout.py`): `output_path(root, now, template_slug|None, seed, step?)` per R7 with slugging to `[a-z0-9-]` and collision suffixes; directories created `0700` (S6).
7. **Gallery index** (`outputs/index.py`): SQLite (stdlib `sqlite3`) with migrations: images (path, created_at, recipe_id, template, seed, model, width, height, favourite, parent_id for variations/edits), FTS on prompt text for search; `reindex(root)` rebuilds from sidecars.
8. **Variations** (`recipe/variations.py`): `seed_variations(recipe, n)` and `prompt_mutation(recipe, rng)` (small, deterministic synonym/order/adjective tweaks from a word list; no network).
9. **Templates store** (`templates/store.py`): JSON files under `~/.config/p11/templates/<folder>/<slug>.json`, list/search by name and tag, import/export with schema validation; safe filenames only.

## Out of scope
HTTP API (07), engine calls (05), real model IDs (06; use placeholder manifest IDs in tests), UI (08+), the bodies of inpaint/background/face/pose/text compilers (10–14).

## Tests
Unit tests for every module: schema validation and discriminated unions, migrations, slot validation errors, seed strategies, compiler golden files (one per preset × style, reviewed by eye once and committed), byte-identical recompile, PNG metadata round-trip and strip, layout slugging/collisions/0700, index migrations, FTS search, reindex from sidecars. Hypothesis property tests for slug safety and recipe JSON round-trip. Coverage ≥ 90 % for `recipe/`, `outputs/`, `templates/`.

## Acceptance criteria
- `make check` green; coverage target met.
- A golden graph for `16:9 1920×1080 photoreal` is accepted by the real engine's `/prompt` validation when Phase 03's engine is available (run it as a `gpu` test; if 03 hasn't finished, record it as a follow-up for Phase 05).
- No module under `recipe/`, `outputs/` or `templates/` performs network I/O; `outputs/` and `templates/` touch the filesystem only through injected roots.

## Phase-specific docs
`docs/P11_ARCHITECTURE.md` (recipe model, compiler extension point, output layout, index schema), ADR-0007 notes (schema v1 fields), ADR for Pydantic/SQLite choices if they deviate from R21, CHANGELOG. Then the standard close-out checklist.
