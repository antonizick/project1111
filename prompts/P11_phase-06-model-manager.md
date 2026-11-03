# P11 Phase 06: Model manager & curated model set

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 03, 04 · **Branch:** `phase-06-model-manager` · **Worktree:** `../project1111-phase-06` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/P11_shared-instructions.md`, spec §5, §11.1 A6, §11.2 R4, R8, R9, R10, R11, R12, §11.3 S4, S9. Phase Log entries for 03 and 04. `docs/P11_BENCHMARKS.md` and Phase 03's default-set ADR. ADR-0006. **Spec §11.6** (decided 2026-11-02 14:57 CST): H1 default set ≤ 30 GB; H2 login-free Hugging Face only, login/Civitai models documented as optional extras; H3 licence handling.

**Phase 04 results (2026-11-02 18:27 CST):** the compiler needs a `p11.recipe.registry.ModelRegistry` (protocol: `get(manifest_id) → ModelInfo` raising `UnknownModelError`). `ModelInfo` carries `manifest_id, kind, filename` (the name ComfyUI lists in its model folder), `sha256, family (sdxl|sd15), defaults (SamplerDefaults: sampler_name, scheduler, steps, cfg, clip_skip, hires_steps), vae` (manifest ID of the VAE to load) and `scale` (upscalers). Implement it from the manifest in `models/registry.py` and replace `PROVISIONAL_DEFAULT_SET` (ADR-0018 values) as the app's registry; keep the same manifest IDs (`realvisxl5-lightning`, `juggernautxl9`, `sdxl-vae-fp16-fix`, `4x-nomos-webphoto-realplksr`, `realisticvision6`; the SD 1.5 VAE's provisional ID is `vae-ft-mse-840000`, rename it there if you pick another and update the presets/golden files). `hires_steps` is 3 for RealVisXL Lightning, 15 for Juggernaut, 12 for Realistic Vision (Phase 03).

## Goal
P11 knows exactly which models it ships with and can fetch them safely. A hash-pinned `models/manifest.toml` holds Phase 03's picks. The downloader resumes, verifies hashes and records licences. A registry covers manifest and user-added models, and the `p11 models` CLI drives it. After this phase, `p11 models install default` turns an empty models directory into the tested default set.

## Tasks
1. **Manifest schema** (`models/manifest.py` + `models/manifest.toml`): per entry `id, kind (checkpoint|lora|vae|controlnet|ipadapter|upscale|facerestore|faceswap|facedetect|segmentation|embedding), base (sd15|sdxl|…), files[{url, filename, sha256, size}], licence {name, url, flags: [non-commercial, attribution, …]}, requires_login, sets [default|full|optional], defaults {sampler, scheduler, steps, cfg, clip_skip, vae}, notes`. Validate on load; unknown keys are an error.
2. **Fill the manifest** from Phase 03's ADR (**Phase 03 results (2026-11-02 18:08 CST):** ADR-0018 lists the `default` set: `realvisxl5-lightning`, `juggernautxl9`, `sdxl-vae-fp16-fix`, `4x-nomos-webphoto-realplksr`, 14.4 GB; and the `full` entries `realisticvision6` + `vae-ft-mse-840000`. The weights are already in `~/.local/share/p11/models/`, so the slow test and Phase 15 can verify instead of re-downloading): re-verify each URL, size and SHA-256 at the source (fetch the file's page; compute the hash after download, never copy a hash from memory). The `default` set fits the budget (owner question 1). Add `full` entries Phase 03 measured but did not make the default. Leave face, pose, segmentation and inpaint entries to Phases 10–12 (they add their own).
3. **Downloader** (`models/download.py`): HTTPS only, ranged resume into `*.part`, streaming SHA-256, atomic rename, mismatch → delete and fail with a clear message, retry with backoff, progress callback, total-size preview before starting, disk-space check, a per-host concurrency limit. Tokens from `~/.config/p11/secrets.toml` (`0600`) are sent only to their own host, never logged, never on redirects to other hosts (S9).
4. **Licence acknowledgement** (on Nick's machine you may pass `--accept-licences`, H3; each licence carries a commercial-use flag)**:** first install of a model with licence flags prints the licence name and URL and requires `--accept-licences` or an interactive yes; record acknowledgements in `~/.config/p11/licences.toml` with a timestamp.
5. **Safety policy (S4):** only `.safetensors` (and GGUF if any entry uses it) load by default; `p11 models add <path|url>` for user models: copy/link into the right folder, compute the hash, sniff the format by content (not the extension), refuse pickle formats unless `--allow-pickle` with a warning that names the risk. Read safetensors headers to detect base architecture where possible.
6. **Registry** (`models/registry.py`): scan the models root, join with the manifest by hash, report `installed | missing | corrupt (hash mismatch) | user-added`, enable/disable flag (kept in config), delete (P11-managed files only; user-added files are only unlinked from the registry unless `--delete-file`). Provides `ModelRef` resolution for the compiler (Phase 04) and writes `extra_model_paths.yaml` for the engine (shared with 03's script).
7. **CLI** (`p11 models list|install <set|id>|verify|add|remove|enable|disable|licences`), with `--json` output for the installer and the UI (Phase 14).
8. **Doctor hook:** `models.check() → list[Problem]` for `p11 doctor` (missing default model, corrupt file, disk low), used by Phase 07.

## Out of scope
Model manager **UI** (14), feature-specific models (10–12 add their manifest entries using this schema), the installer wrapper (15).

## Tests
Manifest validation (good/bad files), downloader against a local test HTTP server (resume after an interrupted transfer, hash mismatch, redirect to another host drops the token, disk-full simulation), licence acknowledgement flow, format sniffing (a crafted pickle file is refused), registry states, CLI `--json` snapshots. One `slow` test downloads the smallest real default entry and verifies it.

## Acceptance criteria
- On the laptop, from an empty temporary models root, `p11 models install default --accept-licences` downloads, verifies and registers the set, and a second run downloads nothing.
- `p11 models verify` detects a deliberately corrupted file.
- Every manifest entry has a verified URL, size, SHA-256 and licence with the check timestamp in a comment.

## Phase-specific docs
`models/manifest.toml`, THIRD_PARTY_NOTICES (model table with licence flags), `docs/P11_ARCHITECTURE.md` (model layout, registry), `docs/P11_USER-GUIDE.md` (adding your own models), SECURITY (model file risks), ADR for the manifest format if it deviates, owner question 3 status, CHANGELOG. Then the standard close-out checklist.
