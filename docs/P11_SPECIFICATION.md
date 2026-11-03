# P11: Project_1111 Specification

> **Amendments override earlier sections.** §1–§10 are the owner's planning document (`Plan Draft.md`, v1.0, 2026-11-02), with formatting fixes only. §11 (Amendments) records the owner's decisions, the technical refinements and the security baseline from the Phase 00 planning session. Where they conflict, §11 wins. The source notes stay in the owner's vault and are not tracked in git (ADR-0004).

**Project_1111 Planning Document**
Fully Local, High-Quality, Uncensored Image Generation System for Omarchy Linux

- **Document Version:** 1.0
- **Date:** 2026-11-02
- **Status:** Implementation-ready for coding agent (Claude Code Opus)
- **Primary Target Hardware:** Laptop with mobile NVIDIA RTX 2070 (8 GB VRAM), 32 GB system RAM, ~600 GB free SSD on Omarchy (Arch + Hyprland + Quickshell)

## 1. Executive Summary

Project_1111 delivers a fully local image generation system on Omarchy Linux that recreates or surpasses a previously optimized Windows Automatic1111 setup. It prioritizes photorealistic output at HD wallpaper resolution, effortless advanced workflows (templates, inpainting, face/pose control, background replacement), and zero software-imposed content restrictions. The system ships with a curated, pre-tested uncensored model set optimized for 8 GB VRAM, a browser-based form UI with minimal tuning, and a simple one-command installation path via a public GitHub repository.

Core user profile: casual daily single-image generation (photorealistic, occasional Pixar-style bobblehead avatars), repeated logo/branding workflows for software products and indie games (must be one-button templatable), and occasional short joke video face-swaps.

**Success Criteria**
- First high-quality photorealistic image generated in under 5 minutes after install (including model download). *(Amended by R4.)*
- Daily single-image workflow (generate → optional inpaint/background/face adjust → save) completes with ≤ 5 clicks/actions after the initial prompt.
- A successful workflow can be saved as a reusable template in ≤ 3 actions and re-executed with one click.
- Inpainting, background replacement with photo upload, and face/pose control feel first-class and do not require reading documentation for basic use.
- System runs stably on the target 8 GB mobile RTX 2070 without constant VRAM tuning.
- Installation on a fresh Omarchy system is a single command (or one script) that handles drivers, dependencies, and optional model download. *(Amended by R15 and S7: drivers are detected and explained, never installed automatically.)*
- No moral, ethical, or safety filters imposed by the software. *(Amended by A5 and S5.)*

## 2. Detailed Requirements

### Functional Requirements
- High-quality uncensored text-to-image generation (primary: photorealistic; secondary: Pixar-style bobblehead).
- Reusable templates/presets that capture full workflow state (prompt, model, LoRAs, ControlNets, dimensions, steps, sampler, seed strategy, post-processing).
- Inpainting with brush/mask tools and photo-based reference.
- Face-swap and/or precise body-pose control (ControlNet-style).
- Background replacement, including upload of photographs.
- Occasional short video face-swap pipeline (extract frames → process → stitch).
- Model management: load, switch, and organize checkpoints, LoRAs, embeddings, ControlNets, IP-Adapters.
- Output organization that is consistent (date-based or template-based folders, metadata).
- Batch and variation support for logos and iterative work.
- Local-only operation; no cloud dependency after install.

### Non-Functional Requirements
- **Ease of use:** Form-based browser UI preferred. Time-to-first-image ≤ 5 min post-install. Template creation ≤ 3 actions. Daily workflow feels "push-button" after initial setup.
- **Performance on 8 GB VRAM:** Reasonable speed for HD wallpaper resolution (target 10–40 seconds per image depending on model/steps; exact numbers measured during testing). Aggressive VRAM optimizations enabled by default.
- **Stability:** No frequent crashes or out-of-memory failures under normal single-image use. Thermal awareness for longer jobs.
- **Maintainability:** Clean GitHub repo, documented, simple update path.
- **Extensibility:** Support for additional models/LoRAs without deep reconfiguration.
- **Privacy:** Fully local; no telemetry or external calls except explicit model downloads.

## 3. Recommended Architecture and Trade-offs

*(Decided by A2: P11 Studio, a form UI over headless ComfyUI, confirmed by the Phase 03 bake-off.)*

The coding agent selects the final stack. Recommendations prioritize 8 GB VRAM efficiency, form-based UI, and low ongoing tuning.

**Primary Recommendation:** Stable Diffusion WebUI Forge (or a maintained A1111 fork with strong low-VRAM support) as the core, with curated extensions for face-swap, ControlNet, and inpainting. Optional lightweight wrapper or custom form frontend if further simplification is needed.

**Alternatives Evaluated:**
- **Automatic1111 (vanilla):** Excellent form UI and extension ecosystem. Weaknesses: higher VRAM usage than Forge on mid-range cards; more manual tuning historically. Use only if Forge gaps appear.
- **ComfyUI:** Superior flexibility, efficiency, and modern workflows (IP-Adapter, advanced ControlNets, regional prompting). Weaknesses: node-based UI has a steeper learning curve; conflicts with strong form-UI preference. Viable as a backend with a custom form frontend or via SwarmUI-style abstraction.
- **InvokeAI:** Cleaner form-based UI, good inpainting and workflow features. Often lighter; check current VRAM behavior on 8 GB NVIDIA. Strong candidate if Forge UX feels dated.
- **SwarmUI:** Multi-backend (Comfy + others) with a more approachable UI. Worth evaluating for template and ease-of-use strengths.
- **Custom hybrid:** Form frontend (React/Vue or simple HTML) over ComfyUI or Forge API. Highest long-term convenience potential but higher initial build cost.

**Model Formats:** Prefer standard checkpoints (.safetensors) for SD 1.5 / SDXL. Support quantized formats (GGUF, etc.) if they deliver better 8 GB performance. LoRAs and ControlNets in standard formats.

**UI Approach:** Browser-based form UI (localhost). Avoid pure node graphs as the primary interface. Provide a "simple mode" with strong defaults and an "advanced" toggle.

**Trade-off Summary:** Forge offers the best immediate balance of form UI + VRAM efficiency for the target hardware. ComfyUI (with frontend) offers higher ceiling for advanced features if the agent invests in UX abstraction. Decision criterion for the agent: measure real-world speed, VRAM headroom, and template/inpainting friction on the exact mobile RTX 2070.

## 4. Feature-by-Feature Design

**Generation (Core).** Default to photorealistic checkpoint optimized for 8 GB. Strong negative prompts and recommended samplers/steps pre-set. One-click variations (seed, slight prompt mutation). HD wallpaper resolution presets (1920×1080, 2560×1440). Pixar-bobblehead mode as a selectable style preset or LoRA stack. *(See R3, R17.)*

**Templates / Presets.** First-class. After any successful generation or multi-step workflow (including inpaint + background + face), user can "Save as Template" with a name and optional tags (e.g., "Software Logo Dark", "Pixar Avatar"). Template stores full state. One-click "Apply Template" loads everything and generates. Support for template folders and quick search. Logo workflows should have example templates for text-heavy or icon-style outputs. *(See R6, R23.)*

**Inpainting.** Integrated mask tool (brush, eraser, opacity). Upload photo as reference or base. One-click "inpaint selection". Denoising strength presets (subtle fix vs. major change). Works seamlessly with templates.

**Face-swap and Body-Pose Control.**
- Face-swap: Integrate a high-quality local solution (Reactor, FaceFusion, or equivalent InsightFace-based tool). Upload source face photo → select target → apply. *(See R11, S5.)*
- Pose control: ControlNet OpenPose (or equivalent) with simple upload of pose image or built-in pose editor. "Apply Pose" button.
- Both features accessible from the main generation and inpainting views. Prioritize face quality for joke videos and avatar work.

**Background Replacement.** Upload photograph as new background. Automatic or manual masking of subject (with refinement brush). Seamless blend options (color matching, lighting adjustment). One-click "Replace Background". Critical for logo and product-style work. *(See R12.)*

**Video Face-swap (Secondary).** Dedicated "Video Face-swap" mode: Upload short clip + source face photo → system extracts frames (ffmpeg), processes each, stitches output. Progress indicator. Reasonable quality/speed defaults. Limit to short clips with clear guidance. *(See R13.)*

**Quality and Effortless Techniques.**
- Curated ControlNet models (OpenPose, Depth, Canny, IP-Adapter) pre-installed or one-click.
- Regional prompting support where the backend allows.
- IP-Adapter for style/character consistency.
- Automatic upscaling option (post-generation) with a quality/speed toggle.
- Strong default prompts and negative prompts for photorealism and logo work.
- Seed locking and variation modes for consistency.

## 5. Model Management Strategy

- Ship with a recommended, pre-tested uncensored set optimized for 8 GB mobile RTX 2070 (photorealistic SD 1.5 or efficient SDXL checkpoint + key LoRAs for realism, detail, logo/text handling, and Pixar-style). *(See R9, R10.)*
- Easy one-click or scripted download from Hugging Face (or mirrored). *(Amended by A6: original hosts only, never re-hosted.)*
- Local storage under a clear directory structure (`models/checkpoints`, `models/loras`, etc.). *(See R8.)*
- Fast switching with VRAM-aware loading/unloading.
- Simple manager UI: list, download, enable/disable, delete. No deep configuration required for basic use.
- Support for user-added models from Hugging Face/Civitai without breaking defaults. *(See S4.)*

## 6. UX / Interface Recommendations

- Clean, form-based browser UI focused on speed.
- Primary view: prompt box, model selector, resolution presets, generate button, and immediate image preview.
- Secondary panels or tabs for Inpaint, Face/Pose, Background, Templates.
- "Save as Template" prominent after generation.
- Minimal advanced settings visible by default; collapsible advanced section.
- Keyboard shortcuts for common actions (generate, save template, next variation).
- Clear status indicators (VRAM usage, generation progress, thermal hints if feasible). *(See R14.)*
- Output gallery with quick compare and export.

## 7. Omarchy Linux Deployment

*(Amended by R15, R16 and S7.)*

- GitHub repository containing install script(s), configuration, documentation, and example templates.
- Single command install target: `curl -sSL https://raw.githubusercontent.com/.../install.sh | bash` or `./install.sh`.
- Script responsibilities:
  - Detect Omarchy/Arch.
  - Ensure proprietary NVIDIA drivers and CUDA are present (or guide/install).
  - Install system dependencies via pacman (python, ffmpeg, git, etc.).
  - Create isolated Python environment (venv or uv).
  - Install PyTorch with CUDA support appropriate for the card.
  - Clone/setup the chosen backend (Forge or selected stack).
  - Download recommended models (optional flag).
  - Configure for low-VRAM by default.
  - Launch browser UI and provide desktop shortcut or command.
- Update path documented.
- Handle Wayland/Hyprland browser quirks if any.
- Thermal and power notes for laptop use.

## 8. Competitive Analysis and Deliberate Improvements

Compared to stock Automatic1111, ComfyUI, Forge, and InvokeAI:
- Better out-of-box experience on 8 GB hardware with curated models and defaults.
- Stronger first-class template system tailored to repeated logo/avatar workflows.
- More polished, lower-friction inpainting + background replacement + face tools than typical extension setups.
- Explicit video face-swap packaging (rare in base tools).
- Zero content restrictions and clean Omarchy-focused install. *(Amended by A5 and S5.)*
- Avoid the "constant tuning" pain of older A1111 setups through better defaults and VRAM strategies.

## 9. Prioritized Implementation Roadmap

*(Superseded in detail by the phase table in `P11_IMPLEMENTATION_PLAN.md`.)*

1. **Foundation:** Install script, environment, chosen backend (Forge preferred), basic generation on 8 GB, curated model set.
2. **Core UX:** Form UI polish, templates, output organization.
3. **Advanced Features:** Inpainting, background replacement, face-swap, pose ControlNet.
4. **Secondary:** Video face-swap pipeline, Pixar preset, upscaling.
5. **Polish & Distribution:** Documentation, GitHub release, acceptance testing on target hardware, example templates for logos and avatars.

## 10. Risks, Open Decisions, and Acceptance Criteria

**Risks**
- 8 GB VRAM headroom on mobile GPU (thermal throttling, OOM). Mitigation: aggressive defaults, model selection, testing.
- Extension conflicts or maintenance burden. Mitigation: minimal curated extensions.
- UI complexity creep. Mitigation: strict form-based, simple-mode priority.
- NVIDIA driver/CUDA setup friction on Omarchy. Mitigation: robust install script.

**Open Decisions for Coding Agent**
- Exact backend (Forge vs InvokeAI vs Comfy+frontend vs other). *(Decided by A2, confirmed in Phase 03.)*
- Precise recommended model list and quantization strategy (measure on hardware). *(Phases 03 and 06.)*
- Whether to build a thin custom frontend or rely on the backend's UI. *(Decided by A2: custom form frontend.)*
- Exact face-swap engine and ControlNet versions. *(Phase 12, ADR-0011.)*
- Degree of automation for video stitching. *(Phase 13: fully automated, R13.)*

**Testing / Acceptance Criteria**
- Install on clean Omarchy completes successfully and launches UI.
- Photorealistic HD image generates reliably without OOM.
- Template save/load works end-to-end.
- Inpaint, background replace (with photo), and face-swap complete in low-friction flows.
- Short video face-swap produces usable output.
- No content filters active. *(Amended by A5 and S5.)*
- Daily workflow meets the ≤ 5 action and one-click template targets. *(Measured per Appendix B.)*

---

## 11. Amendments (v1.1, 2026-11-02 13:14 CST; v1.2, 2026-11-02 14:57 CST; v1.3, 2026-11-03 11:46 CST)

These amendments supersede conflicting text in the earlier sections. Each amendment that records a decision has an entry in `docs/P11_DECISIONS.md`.

### 11.1 Decisions confirmed by the project owner
| ID | Topic | Decision |
|---|---|---|
| A1 | Project prefix | `P11`. Project documents are named `P11_…`; the vault note is `P11 Implementation Plan.md`. (ADR-0001) |
| A2 | Architecture | **P11 Studio**: the project's own browser form UI and Python service, driving a **headless ComfyUI** engine over its local API. The node graph is never the user-facing interface. Chosen because one-click templates that span generate → inpaint → background → face → upscale need a layer that owns the whole workflow, and ComfyUI's API-first, memory-managed engine fits 8 GB best. The Phase 03 bake-off must confirm it on the laptop; if ComfyUI fails the measured criteria there, Phase 03 stops and asks before switching (fallback: Forge-family engine behind the same engine interface). (ADR-0002) |
| A3 | Publication and licence | Private GitHub repo from Phase 01; made public only in the release phase (17) with the owner's explicit in-session confirmation. The project's own code is MIT. Third-party weights are never committed or re-hosted. (ADR-0003) |
| A4 | Source notes | `Plan Draft.md` and `Brainstorming Project 1111.md` stay in the vault and are git-ignored; this spec carries the plan text. (ADR-0004) |
| A5 | Content scope of generation | No software content filter on generation: no safety checker, no prompt blocklist, uncensored checkpoints in the curated set. This is the owner's requirement from §1, kept within the boundary in S5. (ADR-0005) |
| A6 | Curated model set | The system ships a pre-tested, hash-pinned **model manifest** (no weights) for the 8 GB laptop, downloaded from the models' original hosts on request. (ADR-0006) |
| A7 | UI style | Browser form UI with Simple mode by default and an Advanced toggle (§3 "UI Approach" confirmed). |

### 11.2 Technical refinements
- **R1 Python runtime.** The host Python is 3.14 (verified 2026-11-02 13:08 CST), which is newer than the ML stack supports. P11 and the engine each run on a **uv-managed CPython** (default 3.12, or whatever the pinned ComfyUI and PyTorch versions support), never the system Python. Phase 02 sets it for P11; Phase 03 verifies it for the engine. (ADR-0008, Proposed)
- **R2 Turing GPU.** The RTX 2070 Mobile is Turing (compute capability 7.5): fp16 works, bf16 does not run natively, FlashAttention 2 is unavailable. Defaults: fp16 weights, PyTorch SDPA attention, an fp16-safe SDXL VAE (the stock SDXL VAE can produce NaNs/black images in fp16). The host has driver 615.78.08 (open kernel modules) and CUDA 13.4 (verified 2026-11-02 13:08 CST); Phase 03 verifies which PyTorch CUDA build supports sm_75 on this driver and pins it. (ADR-0009, Proposed)
- **R3 Resolution strategy.** SDXL-class models generate best near 1 megapixel and SD 1.5 near 0.25–0.4 MP; neither should be asked for 1920×1080 directly. Wallpaper presets are produced as **native-bucket generation + upscale pass** (for 16:9 SDXL, e.g. 1344×768 → 1920×1080 or 2560×1440, with a light second denoise or a model upscaler). Phase 03 measures the candidates; Phase 04 encodes the presets; Phase 14 adds the quality/speed toggle. (ADR-0010, Proposed)
- **R4 Time-to-first-image.** Measured from the end of the default-set download to the first saved image (target ≤ 5 min including engine cold start and first model load). Download time depends on bandwidth and is reported separately; the installer shows total download size before starting. The default set is kept small (owner question 1).
- **R5 VRAM budget.** The Hyprland desktop already holds ~1 GB of the 8 GB (961 MiB in use at idle, verified 2026-11-02 13:08 CST), so the working budget is ~7 GB. One checkpoint resident at a time; unload on switch; engine VRAM mode chosen by measurement in Phase 03 (`--normalvram` vs `--lowvram` etc.) and set by P11, not by the user. OOM is caught, reported in plain English and retried once with a lower-memory setting.
- **R6 Templates are P11 recipes.** A template is a versioned JSON **recipe**: ordered steps (`generate`, `inpaint`, `replace_background`, `face_swap`, `pose`, `reference`, `upscale`, `text_overlay`) with parameters, model references by manifest ID (+ hash), seed strategy (`fixed | random | increment`), and named **input slots** (e.g. "face photo", "background photo", "logo text"). Applying a template asks only for unfilled slots, then runs. A pure **compiler** turns a recipe into ComfyUI API graphs. Templates never store raw ComfyUI graph JSON as their source of truth (the graph schema and node set change; recipes are migrated by version). (ADR-0007)
- **R7 Output organization.** `~/Pictures/P11/YYYY-MM-DD/<template-slug|adhoc>/<HHMMSS>-<seed>[-<step>].png`, a sidecar `.json` with the full recipe and run metadata, and a SQLite index for the gallery. PNG text chunks embed the recipe so an image can be re-opened as a recipe. Export offers "strip metadata". Root configurable.
- **R8 Data locations (XDG).** Config `~/.config/p11/`; engine `~/.local/share/p11/engine/`; models `~/.local/share/p11/models/{checkpoints,loras,vae,controlnet,ipadapter,upscale,facerestore,faceswap,segmentation,embeddings}` (relocatable to another disk); cache and job scratch `~/.cache/p11/`; outputs per R7. Directories holding uploads, outputs and scratch are created `0700`.
- **R9 Model manifest.** `models/manifest.toml` in the repo lists, per model: id, kind, base architecture, source URL, SHA-256, size, licence name and URL, licence flags (e.g. non-commercial), default parameters (sampler, steps, CFG, clip-skip, VAE), and which presets use it. The downloader resumes, verifies the hash, refuses on mismatch, and records a per-model licence acknowledgement.
- **R10 No model facts from memory.** Model names, URLs, hashes, sizes and licences are written into the manifest only after Phase 03/06 verify them at the source. This spec names categories (Appendix A), not files.
- **R11 Face-swap engine.** Candidates: the ReActor ComfyUI node (InsightFace swapper) and FaceFusion (standalone, headless CLI). Some InsightFace swapper weights are licensed for non-commercial research only; the manifest flags this and the installer requires an explicit acknowledgement. Phase 12 measures quality/speed and decides. (ADR-0011, Proposed)
- **R12 Background segmentation licences differ.** Several strong background-removal models are non-commercial. Prefer a permissively licensed default; a stronger non-commercial model may be an opt-in with a flag. Phase 11 verifies.
- **R13 Video pipeline.** Fully automated: probe (ffprobe) → extract frames at source fps (cap configurable) → face-swap in batches with resumable progress → optional face restore → re-encode with the original audio track. Default limits: ≤ 60 s and ≤ 1080p (configurable, warned beyond). Cancel and resume after crash; scratch frames deleted on success.
- **R14 GPU telemetry and thermal guard.** P11 reads VRAM, temperature, power and clocks (NVML or `nvidia-smi --query-gpu`), shows them in the status bar, and pauses long jobs (video, batches) above a configurable temperature threshold until it drops (owner question 5).
- **R15 Installer.** Documented primary path: `git clone <repo> && cd <repo> && ./install.sh` (a tagged release). A one-line form may fetch a **pinned tag**, never `main`. The script detects Omarchy/Arch, checks the NVIDIA driver and GPU (explains and links if missing; never installs drivers), lists pacman packages and asks before `sudo pacman -S` (`--yes` for unattended), installs uv if missing, sets up P11 and the pinned engine, optionally downloads the default model set (`--models default|none|all`), and runs `p11 doctor`. Idempotent; `uninstall.sh` and `p11 update` exist.
- **R16 Omarchy/Hyprland integration.** A desktop entry and `p11 open`, which opens the UI in an app-mode browser window like Omarchy web apps. Any host change made on the owner's machine is documented in the OSMods log.
- **R17 Trademarks.** User-facing names in the public repo avoid trademarks: the "Pixar-style bobblehead" preset ships as **"3D animated avatar (bobblehead)"**. Prompts may still describe the style.
- **R18 Simple vs Advanced.** Simple mode shows prompt, style/template, aspect preset, Generate, and the result with its follow-up actions (Variations, Inpaint, Background, Face, Upscale, Save as Template). Advanced reveals model, LoRA weights, sampler, steps, CFG, seed, denoise, ControlNet strengths.
- **R19 FakeEngine.** An `Engine` protocol has a **FakeEngine** that returns deterministic placeholder images with realistic progress events and errors, so the recipe compiler, API, jobs and UI are built and tested without a GPU.
- **R20 GPU tests.** CI has no GPU: tests that need the real engine are marked `gpu` and run only on the laptop (`make gpu-test`). Parallel phases serialize GPU use with the lock in R24.
- **R21 Stack defaults.** Python 3.12 via uv, FastAPI + uvicorn, Pydantic, SQLite, Typer CLI; frontend Vite + React + TypeScript built into the Python package; Playwright for end-to-end tests. Phase 02 may change a default with an ADR.
- **R22 Measured success criteria.** Action counts follow Appendix B and are measured with scripted Playwright walkthroughs in Phase 16, alongside timed measurements of time-to-first-image and per-preset generation times on the laptop.
- **R23 Logo text.** Diffusion models render text unreliably. Logo templates generate the mark/background with the model and add exact text with a deterministic **text overlay** step (bundled open-licence fonts), with an optional "let the model try text" toggle.
- **R24 GPU lock.** Anything that loads the real engine (GPU tests, benchmarks, the running Studio's jobs) takes an advisory `flock` on `~/.cache/p11/gpu.lock`, so two phase agents or a test and a live session never fight over 8 GB.

### 11.3 Security and privacy baseline (applies to every phase)
- **S1 Local-only network.** P11 Studio binds `127.0.0.1` only. The engine binds `127.0.0.1` on a configured port and is reached only by P11. No telemetry anywhere; engine update checks and any package-manager node (e.g. ComfyUI-Manager) are not installed. The frontend bundles all assets (no CDN, no web fonts from the network). Outbound traffic happens only for explicit model downloads, `p11 update` and the installer.
- **S2 Browser-facing hardening.** Host-header allowlist and Origin checks (DNS-rebinding and CSRF protection), a per-launch session token, a strict Content-Security-Policy, and no remote resources. The engine's own UI and API are never exposed to the browser directly.
- **S3 Supply chain.** ComfyUI and every custom node are pinned to a commit SHA in `engine/engine.lock.toml`, kept to a minimal reviewed set, and bumped only with a reviewed diff. Python dependencies are locked with hashes (`uv lock`); npm with `package-lock.json`. Custom nodes are a known malware vector, so none is added without an ADR.
- **S4 Model file safety.** Only `.safetensors` (and verified non-executable formats such as GGUF) are loaded by default. Pickle-based formats (`.ckpt`, `.pt`, `.bin`, `.pth`) are refused unless the user opts in per file with a warning; files in the manifest are SHA-256 verified. Face-analysis models that exist only in pickle/ONNX form are pinned by hash in the manifest.
- **S5 Content boundary.** Generation is unfiltered (A5). The **face-swap and video face-swap features keep an NSFW check on the target** (the engine's built-in detector, or one P11 adds if the chosen engine lacks it) and refuse sexual or nude targets. P11 ships no feature, preset or template for placing a real person's face into sexual content, and nothing that sexualizes minors. The docs carry a short notice on using real people's likenesses with consent. This control is not a setting and is not removed by later phases.
- **S6 Personal data.** Uploaded face photos, videos, backgrounds and all outputs are private: stored under the R7/R8 locations (`0700`), never in the repo, never in test fixtures (fixtures are synthetic or public-domain). Logs at INFO do not contain prompt text or file contents. `.gitignore` covers outputs, inputs, models, weights and scratch.
- **S7 Installer safety.** No piping an unpinned script to bash; `sudo` only for the printed pacman list after confirmation; no driver installs, no edits to system files, no changes outside the user's home except pacman packages. ShellCheck-clean; `--dry-run` prints every action.
- **S8 Upload validation.** Images and videos are validated by content (Pillow decode, ffprobe), with size, pixel-count and duration caps; filenames are generated, never taken from the upload; no path traversal; EXIF location is stripped from stored inputs.
- **S9 Secrets.** Optional Hugging Face or Civitai tokens live in `~/.config/p11/secrets.toml` (`0600`), are never logged, and are sent only to their own host.
- **S10 Repo hygiene.** A gitleaks pre-commit hook and CI job; no weights, outputs, tokens or personal media in git history.

### 11.4 Repository and publication requirement (mandatory)
The project lives in a single Git repository that is ready to publish on GitHub. It must contain and keep accurate: README, LICENSE, NOTICE, THIRD_PARTY_NOTICES, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, CHANGELOG, .gitignore, .dockerignore, .editorconfig, .github/ (CI, templates, Dependabot), and docs/. Private data never gets committed; `.gitignore` and a pre-commit secret scan enforce this. THIRD_PARTY_NOTICES lists every engine component, custom node and model in the manifest with its licence, including non-commercial flags. The repo stays private until the owner confirms publication in Phase 17.

### 11.5 Owner questions (status as of 2026-11-02 14:57 CST)
All decided in the hands-off preflight on 2026-11-02 14:57 CST; details and pre-authorizations in §11.6.
1. **Decided (2026-11-02 14:57 CST).** Download budget: up to **100 GB** for the Phase 03 bake-off candidates; the default install set **≤ 30 GB** (H1). *Phase 03, 06, 15.*
2. **Decided (2026-11-02 14:57 CST).** GitHub repo `antonizick/project1111`, private (name checked free at 2026-11-02 14:57 CST); LICENSE holder "Nick Antonizick" (`git config user.name`) (H15). *Phase 01.*
3. **Decided (2026-11-02 14:57 CST).** Model hosts: only Hugging Face files that need no login, for the bake-off and the default set; no tokens are used in the build. Login-gated or Civitai models are optional extras the owner adds later with a token (S9) (H2). *Phase 03, 06.*
4. **Decided (2026-11-02 14:57 CST).** Face-swap test material: synthetic faces generated by P11 and a synthetic clip; owner material in `~/Pictures/P11-test/` is used too if present. Never blocks (H7). *Phase 12, 13.*
5. **Decided (2026-11-02 14:57 CST).** Thermal pause at 87 °C, resume at 80 °C; Phase 13 may adjust either by up to ±5 °C from the measured throttle point and records why (H9). *Phase 13.*
6. **Decided (2026-11-02 13:14 CST).** Prefix P11 (A1), architecture (A2), publication and licence (A3, amended by H13), source notes (A4).

### 11.6 Hands-off pre-authorizations (v1.2, 2026-11-02 14:57 CST)
Answers given by the owner in the preflight for an unattended PHX run (`phx run`). They **replace** any "ask Nick", "confirm" or "block-with-question" in phase prompts for the cases they cover; anything not covered here still follows the risk rule in `CLAUDE.md`. Recorded in ADR-0015 and ADR-0016.

| # | Topic | Decision | Phases |
|---|---|---|---|
| H1 | Download budget | Bake-off candidates ≤ 100 GB in total (rejected ones deleted at the end); default install set ≤ 30 GB. Phase 15's throw-away-HOME install reuses the already-downloaded files (hard link, copy from the local models dir, or a local cache) so it does not download them again. Exceeding a cap blocks. | 03, 06, 15 |
| H2 | Model hosts | Hugging Face, login-free files only. No tokens in the build. Civitai or gated models are documented as optional extras. | 03, 06 |
| H3 | Model licences | Non-commercial, CreativeML OpenRAIL-M and similar licences may be downloaded and used on the owner's machine for personal use without asking. Every licence is recorded in THIRD_PARTY_NOTICES, the manifest, the Models page and the installer, with a clear "commercial use allowed?" flag (the owner also makes logos and game assets). Where quality is comparable, prefer the more permissive model. Weights are never committed or redistributed. Agents may pass `--accept-licences` for these models on the owner's machine. | 03, 06, 12, 14, 15 |
| H4 | Dev tools | No `sudo`. shellcheck, gitleaks, bats, semgrep and similar tools are installed at user level: `uv tool install` or the project's dev dependencies where a PyPI package exists, else a release binary pinned by version and SHA-256 into `~/.local/bin` (or a repo-local `.tools/`, git-ignored). The Makefile finds them; CONTRIBUTING documents it. Nothing is installed with pacman. | 01, 02, 15, 16 |
| H5 | Default model pick | Phase 03 picks the default photoreal and avatar models itself from measurements (speed, VRAM, stability) and its own side-by-side visual comparison, records the reasoning in the default-set ADR, and leaves the contact sheet at `~/.cache/p11/bench/` for the owner. No block. The owner may override later through `/phase-add`. | 03 |
| H6 | Engine fallback | If headless ComfyUI fails a hard requirement on the laptop (fits the ~7 GB budget at the native bucket size, 50-run stability, a working torch build on sm_75) and the fallback engine clearly passes where ComfyUI fails, the agent may switch. It must write an ADR superseding ADR-0002 with the evidence, rewrite every affected later prompt (04–17), and record it in the Phase Log. A close call does not count as "clearly". | 03 |
| H7 | Face test material | Synthetic faces generated by P11 (no real person) and a synthetic clip for laptop checks. If `~/Pictures/P11-test/` exists, its photo and clip are also used, read-only, never copied into the repo, logs, fixtures or screenshots. Never block for missing material. The S5 guard and the content boundary apply. | 12, 13 |
| H8 | Power profile | For GPU benchmarks, soaks and thermal runs only: `powerprofilesctl set performance` (no sudo), restored to the previous profile afterwards (also on failure, via a `trap`/`finally`). The profile and AC state are recorded with every benchmark. On battery, GPU benchmarks block; other work continues. Not an OS modification (runtime only, restored). | 03, 13, 15, 16 |
| H9 | Thermal limits | Pause at 87 °C, resume at 80 °C; Phase 13 may adjust each by up to ±5 °C based on Phase 03's measured throttle point, with the reason in an ADR. | 13 |
| H10 | Review pauses | Gate `auto` for every phase except 17 (`review`). The owner reviews Phase 03's model pick, Phase 08's UI, Phase 15's installer and Phase 16's QA results at the Phase 17 pause; each of those phases leaves a short "for the owner's review" note in its Phase Log entry. | 03, 08, 15, 16, 17 |
| H11 | Host changes (Phase 15) | Pre-approved, each written up in OSMods with undo steps: (a) desktop entry and icon; (b) a Hyprland launch keybinding in the owner's user config (pick a combination that is unused: check the existing bindings first); (c) a P11 status indicator, only through a supported user-level extension of the Omarchy shell, never by editing or shadowing files under `/usr/share/omarchy/`; if there is none, skip it and log a follow-up; (d) a real install under the owner's HOME (`~/.local/share/p11`, `~/.config/p11`) after the throw-away-HOME test, reusing the downloaded models. Load the `omarchy` skill before (b) and (c). | 15 |
| H12 | QA misses (Phase 16) | Fix what can be fixed. A missed non-security target, or a follow-up that cannot be closed, is recorded with its measurement and reason, deferred, and listed for the owner in the Phase 17 review. A high or critical security finding must be fixed, or the phase blocks. | 16 |
| H13 | Publication | v1.0.0 is an annotated tag plus a GitHub release **on the private repo**; the repo stays private (amends A3 and §11.4). Phase 17 still asks the owner "go?" for the release at that moment (hands-off: block-with-question, the one planned stop). Making the repo public is out of scope for v1.0.0. | 17 |
| H14 | Starter templates | Generic placeholders ("Product Name", "Game Title") with slots; no personal brand or product names in the repo. | 09, 14 |
| H15 | Repo and licence holder | `antonizick/project1111`, private; MIT copyright holder "Nick Antonizick". | 01 |

---

### 11.7 Face, pose and reference decisions (v1.3, 2026-11-03 11:46 CST)

Recorded by Phase 12; the ADRs named here override the wording of §4 and R11 where they differ.

- **R11 (face-swap engine) is decided: neither candidate is an engine dependency.** §4's "high-quality local solution (Reactor, FaceFusion, or equivalent InsightFace-based tool)" is satisfied by **P11's own InsightFace-based pipeline** run on the CPU in P11 (YuNet + ArcFace w600k_r50 + `inswapper_128` + GFPGAN v1.4, all ONNX). Measured on the laptop: 2.4 s per swap, 3.9 s restored, no VRAM. The ReActor node would be third-party custom-node code with an unpinned run-time model download (S3), and FaceFusion would be a second application to install, pin and supervise. **ADR-0028** (resolves ADR-0011). Phase 13's video path uses the same module per frame.
- **S5's guard is implemented exactly as specified, with two classifiers**: Marqo's ViT-tiny and Freepik's EVA02, both hash-pinned ONNX models, both required, either one refusing is enough, thresholds fixed in `src/p11/media/nsfw.py`. The guard runs on the target before a swap, on the result before it is saved, and at submit time when the target is already a file; it fails closed when a classifier is missing. No setting, env var, route parameter or recipe field can disable it. **ADR-0029**.
- **R10/R11's licence rule is applied to the face models**: InsightFace's `buffalo_l` recognition and `inswapper_128` weights are **non-commercial research only** and need a licence from insightface.ai (their README, read 2026-11-03 10:36 CST). They are flagged in the manifest, in THIRD_PARTY_NOTICES and on the Models page, and the installer requires an explicit acknowledgement (H3). They are in the `face` set, never in `default`.
- **Controls and reference use one union ControlNet and P11's own IP-Adapter node.** ComfyUI v0.43.0 ships no IP-Adapter node, so the reference path is served by `engine/custom_nodes/p11_ipadapter` (P11's own MIT code, the only custom node the engine may load, its SHA-256 pinned in `engine/engine.lock.toml`) — **ADR-0030, ADR-0031**.
- **Additive schema changes** (no version bump, every older v1 document still loads): `FaceSwap.blend`, `Pose.control`, a `face_restore` step, and the manifest's `classifier`/`preprocess`/`clipvision` kinds with the `face` and `control` sets. **ADR-0032**.

## Appendix A: Bake-off candidate categories (Phase 03)
Names, versions, URLs and licences are verified at the source during Phase 03; nothing here is a fact to copy.
- **Engines:** ComfyUI (headless, pinned commit) as the decided engine; for comparison, one Forge-family WebUI build, measured with the same prompts.
- **Base families:** SDXL 1.0-class photoreal fine-tunes (uncensored); SD 1.5-class photoreal fine-tunes (uncensored); few-step distillation LoRAs or checkpoints for SDXL (Lightning/Hyper/DMD-style) for speed; a quantized larger-model variant only if it fits ~7 GB at usable speed.
- **Support models:** fp16-safe SDXL VAE; ControlNet (OpenPose, Depth, Canny) or equivalent for the chosen base; IP-Adapter (style/character, and a face-ID variant); an upscaler (model-based and latent/denoise pass); face restoration (GFPGAN/CodeFormer class); a background segmentation model; a face detector/swapper.
- **Measurements per combination:** seconds per image at each wallpaper preset (cold and warm), peak VRAM, system RAM, OOM behaviour, quality on a fixed 10-prompt photoreal set + 3 avatar prompts + 3 logo prompts (owner rates a contact sheet), GPU temperature over a 10-minute loop.

## Appendix B: Action counting (success criteria)
- An **action** is one click, one key chord, or one drag gesture (a brush stroke counts as one). Typing the prompt or a template name is not counted; selecting a file in the file picker counts as one action.
- **Daily workflow (≤ 5):** from a typed prompt with the default preset: Generate (1) → Background (1) → choose photo (1) → Apply (1) → Save/Download (1). Inpaint path: Inpaint (1) → one mask stroke (1) → Apply (1) → Save (1).
- **Save as template (≤ 3):** Save as Template (1) → type name (not counted) → Save (1).
- **Re-run template (1):** clicking the template runs it when it has no unfilled slots; a template with input slots needs one action per slot plus Run.
