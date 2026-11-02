# P11: Architecture Decision Log

Lightweight ADRs. Append new decisions at the bottom, and never rewrite history: to reverse a decision, add a new entry that supersedes the old one. Every phase that makes a non-trivial technical choice adds an entry here. Timestamps are `YYYY-MM-DD HH:MM TZ` from `date '+%Y-%m-%d %H:%M %Z'`; a status change (for example `Proposed` → `Accepted`, or `Superseded by ADR-00NN`) is noted in the entry with its own timestamp.

| ID | Timestamp | Decision | Status | Phase |
|---|---|---|---|---|
| ADR-0001 | 2026-11-02 13:16 CST | Project prefix `P11` | Accepted | 00 |
| ADR-0002 | 2026-11-02 13:16 CST | P11 Studio form UI over headless ComfyUI | Accepted (confirm in 03) | 00 |
| ADR-0003 | 2026-11-02 13:16 CST | Private repo until release; MIT for own code; no weights in git | Accepted | 00 |
| ADR-0004 | 2026-11-02 13:16 CST | Source notes stay in the vault, git-ignored | Accepted | 00 |
| ADR-0005 | 2026-11-02 13:16 CST | Unfiltered generation; NSFW guard kept on face-swap | Accepted | 00 |
| ADR-0006 | 2026-11-02 13:16 CST | Curated model set as a hash-pinned manifest | Accepted | 00 |
| ADR-0007 | 2026-11-02 13:16 CST | Templates are versioned P11 recipes compiled to engine graphs | Accepted | 00 |
| ADR-0008 | 2026-11-02 13:16 CST | uv-managed CPython, separate from host Python 3.14 | Proposed (verify 02/03) | 00 |
| ADR-0009 | 2026-11-02 13:16 CST | Turing defaults: fp16, SDPA, fp16-safe SDXL VAE, sm_75-capable torch | Proposed (verify 03) | 00 |
| ADR-0010 | 2026-11-02 13:16 CST | Wallpaper presets = native bucket + upscale | Proposed (verify 03/14) | 00 |
| ADR-0011 | 2026-11-02 13:16 CST | Face-swap engine: ReActor node vs FaceFusion | Proposed (decide 12) | 00 |
| ADR-0012 | 2026-11-02 13:16 CST | Installer: clone + `./install.sh`, no driver installs | Accepted | 00 |
| ADR-0013 | 2026-11-02 13:16 CST | Local-only security posture | Accepted | 00 |
| ADR-0014 | 2026-11-02 13:16 CST | Advisory GPU lock across sessions and parallel phases | Accepted | 00 |

---

## ADR-0001: Project prefix `P11`
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** Project documents must be identifiable out of context; existing prefixes are CL, MM3, OCC, PHX, YTPL2.
**Options considered.** `P11`, `1111`, `PJ11`.
**Decision.** `P11` (owner's choice).
**Consequences.** Files are `P11_…`; the vault note is `P11 Implementation Plan.md`; the Python package and CLI are `p11`.

## ADR-0002: P11 Studio form UI over headless ComfyUI
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The source plan leaves the engine open, leaning to Forge. Its success criteria (one-click templates covering generate → inpaint → background → face, ≤ 5 actions daily) need a layer that owns the multi-step workflow; Forge's UI does not capture that as one template, and the Forge family's upstream maintenance has been uneven. The hardware (8 GB Turing laptop, ~1 GB taken by the desktop) rewards the most memory-efficient engine.
**Options considered.** (a) own form UI over headless ComfyUI; (b) Forge/reForge plus curated extensions and a small templates extension; (c) InvokeAI as-is plus presets and side tools.
**Decision.** (a), owner's choice. P11 owns the UI, recipes, jobs and outputs; ComfyUI is an engine behind an `Engine` interface, reached only on 127.0.0.1. Phase 03 must confirm on the laptop that ComfyUI meets the speed/VRAM/stability criteria; if it fails, Phase 03 stops and asks the owner before switching to the fallback (a Forge-family engine behind the same interface).
**Consequences.** More build work (custom UI, compiler, adapter), but templates, Simple mode and the action targets are fully under P11's control and the engine can be swapped. Engine graph churn is contained in the compiler (ADR-0007).

## ADR-0003: Private repo until release; MIT for own code; no weights in git
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The source wants a public repo with a one-command install; the content scope and third-party licences deserve review before anything is public.
**Options considered.** Private now and public at release; private only; public from Phase 01.
**Decision.** Private GitHub repo from Phase 01 (owner question 2 gives the name). Public only in Phase 17 with the owner's explicit in-session confirmation. P11's own code is MIT. Model weights are never committed or re-hosted; the manifest points at original hosts.
**Consequences.** Phase 16 audits licences (engine GPL-3.0 components are installed separately, not vendored; non-commercial model flags are surfaced) before the publication decision.

## ADR-0004: Source notes stay in the vault, git-ignored
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The repo folder is also a vault folder (`/home/nick/Work` is mounted at `Documents/02 Projects/Work`), so the source notes sit in the repo root.
**Options considered.** Ignore them; commit them under `docs/source/`.
**Decision.** Ignore them (`.gitignore`), owner's choice. The spec reproduces the plan text.
**Consequences.** The Grok transcript never becomes public. Agents may read the notes in place but never stage them.

## ADR-0005: Unfiltered generation; NSFW guard kept on face-swap
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The owner requires no software-imposed content restrictions on generation. Face-swap combined with unfiltered generation can produce sexual imagery of real, identifiable people, which is harmful and illegal to distribute in many jurisdictions.
**Options considered.** No guard anywhere; guard on generation and face-swap; guard on face-swap only.
**Decision.** No safety checker or prompt filter on generation (owner requirement). The face-swap and video face-swap paths keep an NSFW check on the target and refuse sexual or nude targets; no feature, preset or template places a real person's face into sexual content; nothing sexualizes minors. Fixed by the planning session (spec S5), not a user setting.
**Consequences.** Phases 12 and 13 implement and test the guard; Phase 16 verifies it cannot be bypassed through templates or the API. Jokes, avatars and logos are unaffected.

## ADR-0006: Curated model set as a hash-pinned manifest
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The owner expects a pre-tested model set; weights are large, separately licensed and must not live in git.
**Options considered.** Bundle weights; download unpinned "latest"; pinned manifest.
**Decision.** `models/manifest.toml` with URL, SHA-256, size, licence and defaults per model; resumable verified downloads from original hosts; per-model licence acknowledgement. Contents chosen by Phase 03 measurements and verified at the source in Phase 06 (spec R9, R10).
**Consequences.** Reproducible installs; a host removing a file breaks that entry, which `p11 doctor` reports.

## ADR-0007: Templates are versioned P11 recipes compiled to engine graphs
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** Templates must capture full multi-step state and survive engine updates.
**Options considered.** Store ComfyUI workflow JSON; store P11 recipes and compile.
**Decision.** Recipes (spec R6) with a schema version and migrations; a pure compiler emits ComfyUI API graphs.
**Consequences.** Engine node changes touch only the compiler; recipes stay readable and diffable; the compiler needs strong tests (Phase 04).

## ADR-0008: uv-managed CPython, separate from host Python 3.14
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** Host Python is 3.14.8; PyTorch/ComfyUI and many custom nodes lag new Python releases.
**Options considered.** System Python; pyenv; uv-managed interpreters; conda.
**Decision (Proposed).** uv-managed CPython 3.12 for P11 (Phase 02) and a separate uv environment for the engine with the version its pins support (Phase 03).
**Consequences.** No system Python changes. Phase 03 marks this Accepted or supersedes it.

## ADR-0009: Turing defaults: fp16, SDPA, fp16-safe SDXL VAE, sm_75-capable torch
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** RTX 2070 Mobile is compute capability 7.5; host driver 615.78.08 (nvidia-open), CUDA 13.4. Newer CUDA toolkits have dropped older architectures, so the torch build must be checked for sm_75.
**Options considered.** Recorded by Phase 03 (which CUDA build of torch; SDPA vs xformers; fp16 vs fp32 VAE).
**Decision (Proposed).** fp16 UNet/text encoders, SDPA attention, fp16-safe SDXL VAE, a torch build verified to run kernels on sm_75 with this driver.
**Consequences.** Phase 03 pins the exact versions in `engine/engine.lock.toml` and marks this Accepted.

## ADR-0010: Wallpaper presets = native bucket + upscale
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** Models degrade (duplicated subjects, composition errors) far from their training resolution; 1920×1080 and 2560×1440 exceed SDXL's ~1 MP sweet spot and VRAM budget.
**Options considered.** Direct generation; native bucket + latent/hires pass; native bucket + model upscaler; tiled upscale.
**Decision (Proposed).** Native-bucket generation then an upscale chain chosen by Phase 03 measurements (quality/speed toggle in Phase 14).
**Consequences.** Presets carry both the generation size and the output size; the compiler emits the chain.

## ADR-0011: Face-swap engine: ReActor node vs FaceFusion
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** Face-swap quality matters for avatars and joke videos; licences of swapper weights vary (some non-commercial).
**Options considered.** ReActor ComfyUI node; FaceFusion headless CLI; another InsightFace-based tool.
**Decision (Proposed).** Phase 12 measures both on synthetic/owner-supplied test material, checks licences and NSFW-guard support (ADR-0005), and records the choice.
**Consequences.** The video pipeline (Phase 13) uses the same engine.

## ADR-0012: Installer: clone + `./install.sh`, no driver installs
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The source suggests `curl … | bash` and having the script install drivers. Piping an unpinned script is a supply-chain risk; installing GPU drivers can break a working desktop.
**Options considered.** curl|bash from `main`; clone + script; pinned-tag one-liner; distro package (AUR).
**Decision.** Primary: clone a tagged release and run `./install.sh` (spec R15, S7). A one-liner may fetch a pinned tag. Drivers are detected and explained, never installed. An AUR package is a possible follow-up.
**Consequences.** One extra step for users; no root changes beyond confirmed pacman packages.

## ADR-0013: Local-only security posture
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** The engine has no authentication; uploads include photos of real people.
**Options considered.** LAN access with auth; localhost only.
**Decision.** Localhost only, browser hardening, pinned supply chain, safetensors-first, private data dirs (spec S1–S10).
**Consequences.** Remote/LAN use is out of scope for v1.

## ADR-0014: Advisory GPU lock across sessions and parallel phases
**Recorded.** 2026-11-02 13:16 CST (Phase 00)
**Context.** Several phases may run in parallel worktrees on one 8 GB GPU; two engines loading SDXL at once will OOM.
**Options considered.** No coordination; serialize phases; advisory lock.
**Decision.** `flock` on `~/.cache/p11/gpu.lock` around GPU tests, benchmarks and the Studio's engine jobs (spec R24); a waiting session reports who holds it.
**Consequences.** GPU tests may wait; CPU-only tests and FakeEngine tests never take the lock.
