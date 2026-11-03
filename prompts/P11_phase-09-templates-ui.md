# P11 Phase 09: Templates UI & starter templates

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 08 · **Branch:** `phase-09-templates-ui` · **Worktree:** `../project1111-phase-09` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §1 (success criteria), §4 (Templates), §11.2 R6, R17, R18, R22, R23, §11.3 S5, Appendix B. Phase Log entries for 04, 07 and 08. ADR-0007.

**Phase 04 results (2026-11-02 18:27 CST):** `p11.templates.store.TemplateStore` already does save (slugged file names, same-ID overwrite, `-2` suffixes), folders (≤ 3 levels), search by name/tag/folder, `export`/`import_bytes` (validated and migrated; imports get a new ID unless `keep_id`), and `problems()` for unreadable files. Slots are `Slot(name, kind, label, required, default)`; text slots are referenced as `{{name}}` in prompts. Build the UI on it rather than a second store.

## Goal
Any successful result becomes a reusable one-click template in ≤ 3 actions, and templates run with one click (plus one action per unfilled input slot). P11 ships starter templates for Nick's repeated jobs: photoreal wallpapers, software/indie-game logos and 3D animated avatars.

## Tasks
1. **Save as Template** (from the result panel and gallery detail): a compact dialog with name (prefilled from the prompt), folder, tags, and a smart default for slots: values that came from uploads (face photo, background photo) and text marked as variable become **slots**, everything else is fixed. Seed strategy choice (fixed for "exactly this", random for "more like this"). Save = done. Action count ≤ 3 (Appendix B).
2. **Recipes that span steps:** when the result came from a chain (later: inpaint, background, face, upscale), the template captures the whole chain from the run's `RunRecord` (Phase 04/07). Until those features exist, cover generate + upscale + variations, and build the capture generically from `RunRecord.steps` so 10–14 need no template changes.
3. **Templates view:** folders, tag filter, quick search (name/tags/prompt), cards with a thumbnail of the last output, Run (one click), Edit (opens the recipe in Generate with the template loaded), Duplicate, Rename, Move, Delete (with undo toast), Export/Import (`.p11template.json`, schema-validated, Phase 04 store).
4. **Run with slots:** clicking Run on a template with unfilled required slots opens a small slot form (text field, image picker or drag-drop) and Run; filled slots can be remembered per template ("use last face photo").
5. **Quick access:** a template picker in the Generate view (Ctrl+K palette with fuzzy search) and the last 5 used templates as chips.
6. **Starter templates** (`templates/starter/*.json`, installed on first run if missing): "Wallpaper photoreal 16:9 1080p", "Wallpaper photoreal 16:9 1440p", "Software logo dark", "Software logo light", "Indie game logo", "3D animated avatar (bobblehead)" (R17 wording; face slot is optional until Phase 12 adds face-swap), each with prompts tuned on the default model on the laptop. Logo templates include a `TextOverlay` step placeholder that Phase 14 implements (R23); until then they produce the mark without text and say so in their description. None depict real people or sexual content (S5). Use generic placeholders ("Product Name", "Game Title") in slots; no personal brand or product names in the repo (spec H14).
7. **E2E:** Playwright walkthroughs counting actions: save ≤ 3, re-run 1, run-with-one-slot 3.

## Out of scope
Text overlay implementation (14), feature steps (10–13), template sharing beyond file export.

## Tests
Slot inference unit tests, store CRUD through the API, import of a malformed or future-version file (refused cleanly), Vitest for the dialog and palette, Playwright e2e on FakeEngine with action counts, one laptop run of each starter template with the real engine (outputs kept locally, not committed).

## Acceptance criteria
- From a fresh result: Save as Template in ≤ 3 actions; Run from the Templates view in 1 action produces a new image with the template's settings (verified by comparing recipes).
- Starter templates install on first run and each produces a sensible image on the laptop.
- `make check` green; action counts in the Phase Log.

## Phase-specific docs
`docs/P11_USER-GUIDE.md` (templates, slots, import/export), `docs/P11_ARCHITECTURE.md` (slot inference, starter install), CHANGELOG. Then the standard close-out checklist.
