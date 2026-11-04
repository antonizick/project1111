# P11: Final Report (v1.0.0)

Project_1111 (P11) is a fully local image-generation system for Omarchy Linux on an 8 GB RTX 2070 Mobile laptop. **P11 Studio** (Vite + React + TypeScript, FastAPI, Typer, SQLite, Python 3.12 via uv) drives a pinned headless ComfyUI on 127.0.0.1. This report covers phases 00–16 as shipped in v1.0.0. The repository is private (spec H13, ADR-0016).

## What was built against the spec
| Spec goal (§1, §10) | Result | Phase |
|---|---|---|
| Photoreal text-to-image at wallpaper resolution (1920×1080, 2560×1440) on 8 GB | Native bucket + upscale chain, Speed and Quality modes, `--lowvram` OOM retry | 03, 04, 05, 14 |
| One-click templates (recipes compiled to engine graphs) | Save as Template in 2 actions, re-run in 1, six starters, import/export | 04, 09 |
| Inpainting | Mask editor, crop-and-stitch, unmasked pixels byte-identical | 10 |
| Background replacement with photos | BiRefNet-lite mask on the CPU, LAB colour match, harmonize pass | 11 |
| Face-swap, pose and reference control | CPU face pipeline, ControlNet Union, IP-Adapter through P11's own node pack | 12 |
| Short video face-swap | Per-frame pipeline, audio kept, resumable after a kill | 13 |
| Upscale, logo text, Models page | Exact text overlay with five OFL fonts, logo pack ZIP, hash-pinned model manager UI | 14 |
| Installer and Omarchy integration | `install.sh`, `uninstall.sh`, `p11 update`, desktop entry, container install test | 15 |
| Security baseline S1–S10, threat model, QA | `docs/P11_THREAT-MODEL.md`, scanners, fuzz corpus, axe on every view | 16 |
| Unfiltered generation (A5); face-swap NSFW guard (S5) | Plain generation has no filter; the guard cannot be configured off (ADR-0005, ADR-0029, ADR-0034, ADR-0037) | 12, 13, 16 |

## Measured results against targets
Full tables: `docs/P11_BENCHMARKS.md` → "Success criteria (Phase 16 …)".

| Criterion | Target | Measured |
|---|---|---|
| Time to first image after the default-set download | ≤ 5 min | 37.7 s |
| Wallpaper presets in a row without OOM | 50 each | 50/50 at 1920×1080 and 50/50 at 2560×1440 |
| Stability on 8 GB | no crash, no leak | 30-minute mixed soak, 105 jobs, 0 OOM, 0 crashes, RSS flat |
| Daily workflow | ≤ 5 actions | 5 (generate → download is 2) |
| Save as Template / re-run | ≤ 3 / 1 | 2 / 1 |
| Warm wallpaper time, Speed | recorded | 16.2 s (1080p), 17.8 s (1440p) |
| Warm wallpaper time, Quality | recorded | 35.6 s (1080p), 59.4 s (1440p) |
| Thermal plateau | below the 87 °C pause | 80–81 °C |
| Video face-swap, 30 s 1080p Fast | usable file with audio, resume works | 2.75 s/frame, killed and resumed to completion |

## Decisions
37 ADRs are indexed in `docs/P11_DECISIONS.md`. The ones that shape the product:
- **ADR-0002, 0013:** a form UI over headless ComfyUI, with a local-only security posture.
- **ADR-0003, 0016:** MIT for P11's own code, no weights in git, a private v1.0.0 release.
- **ADR-0005, 0029, 0034, 0037:** unfiltered generation; the S5 guard on face-swap targets and results, video frames and every picture that carries a person's likeness.
- **ADR-0006, 0021:** a hash-pinned model manifest with a verified downloader.
- **ADR-0007, 0019:** templates are versioned recipes compiled to engine graphs.
- **ADR-0018:** the default model set (RealVisXL V5.0 Lightning, Juggernaut XL v9, fp16-fix VAE, NomosWebPhoto RealPLKSR; about 14.6 GB).
- **ADR-0028, 0031:** the face pipeline runs on the CPU in P11; the IP-Adapter node pack is P11's own code.
- **ADR-0036:** the installer is an editable `uv tool` install from the checkout, with tag-based updates.

## Deviations
Recorded per phase in the Phase Log of `P11_IMPLEMENTATION_PLAN.md`. The notable ones: no Forge-family engine was measured because ComfyUI passed every hard requirement (Phase 03); face detection, swap and restore run in P11 instead of a ReActor node (ADR-0028); the gitleaks hook is a local system hook (ADR-0017); logo starters were mark-only until Phase 14 (ADR-0024).

## Known limitations and residual risks
From `docs/P11_THREAT-MODEL.md` §3 and `docs/P11_PUBLICATION-READINESS.md`:
- **T6:** ComfyUI has no authentication. Another local process that can reach the engine port can run graphs, and can use the face adapter without the S5 guard.
- **T7, T8:** the S5 classifiers can miss. There are two models and either one refusing is enough. A re-uploaded picture of someone's likeness is only caught when its sidecar carries the `likeness` flag.
- **Licences:** the InsightFace models (`arcface-w600k-r50`, `inswapper-128`) are non-commercial research only, so face-swap output is not cleared for commercial use. The CreativeML OpenRAIL-M checkpoints carry use-based restrictions. Both are flagged in `THIRD_PARTY_NOTICES.md`, the installer and the Models page.
- **Hardware:** built and measured on one machine (RTX 2070 Max-Q, 31 GB RAM). Other GPUs are untested. Good-quality video runs at about 7 s/frame on the CPU.
- **Not tested against a real tag:** the pinned-tag one-liner and `p11 update` need the public tag and a public repo.

## Deferred follow-ups
The full list is the plan's "Deferred follow-ups (Phase 16, H12)" table. None is a security item. The ones that need the owner's eye: avatar/LoRA tuning, the 10-prompt defaults review, and the by-eye `latent` vs `both` comparison. AUR packaging and an Omarchy shell status indicator are candidates for `/phase-add`.

## Timeline
<!-- phase-timeline:start (generated by scripts/phase_timeline.py; do not edit) -->
<!-- phase-timeline:end -->
