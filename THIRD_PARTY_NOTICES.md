# Third-party notices

P11 distributes none of the components below. They are installed separately, pinned by commit or SHA-256, and used under their own licences. "Flags" records restrictions such as non-commercial use. Versions, commits, licences and URLs are verified at the source before they are entered.

## Engine components
Installed by `scripts/engine_setup.sh` into `~/.local/share/p11/engine/` (never vendored), pinned in `engine/engine.lock.toml` and hash-locked in `engine/requirements.lock.txt` (full set: 103 packages). Licences read from the installed package metadata and the GitHub API on 2026-11-02 15:45 CST (Phase 03).

| Name | Version / commit | Licence | URL | Flags |
|---|---|---|---|---|
| ComfyUI | v0.43.0, `426f5eea52a7ece1dd599fff4cb6cd1f352ddd24` | GPL-3.0 | https://github.com/Comfy-Org/ComfyUI | copyleft; separate process, reached over HTTP only |
| comfyui-frontend-package | 1.57.4 | GPL-3.0 | https://github.com/Comfy-Org/ComfyUI_frontend | installed by ComfyUI's requirements; its UI is never exposed (S2) |
| comfyui-embedded-docs | 0.5.15 | GPL-3.0 | https://pypi.org/project/comfyui-embedded-docs/ | as above |
| comfyui-workflow-templates | 0.11.97 | MIT | https://pypi.org/project/comfyui-workflow-templates/ | none |
| comfy-aimdo | 0.6.0 | GPL-3.0 | https://pypi.org/project/comfy-aimdo/ | dynamic VRAM allocator |
| comfy-kitchen | 0.2.40 | Apache-2.0 | https://pypi.org/project/comfy-kitchen/ | none |
| PyTorch (`torch`) | 2.14.1+cu130 | BSD-3-Clause style (Apache-2.0, BSD-2/3 components per its metadata) | https://pytorch.org/ | from `download.pytorch.org/whl/cu130` |
| torchvision | 0.29.1+cu130 | BSD-3-Clause | https://github.com/pytorch/vision | none |
| NVIDIA CUDA 13.0 runtime wheels (cuBLAS, cuDNN 9.24, …) | as locked | NVIDIA proprietary (redistributable) | https://pypi.org/user/nvidia/ | pulled in by torch; proprietary |
| transformers, safetensors, kornia, torchsde | 5.22.1, 0.8.0, 0.9.0, 0.2.6 | Apache-2.0 | https://pypi.org/ | none |
| spandrel | 0.4.2 | MIT | https://github.com/chaiNNer-org/spandrel | loads upscaler architectures |

## Custom nodes
None as of Phase 03 (2026-11-02 15:45 CST): the bake-off used core nodes only. Adding a node needs an ADR (S3).

| Name | Version / commit | Licence | URL | Flags |
|---|---|---|---|---|

## Python and npm dependencies
Direct runtime dependencies as locked in Phase 02 (versions and licences read from the installed package metadata on 2026-11-02; the full locked set is audited in Phase 16).

| Name | Version | Licence | URL | Flags |
|---|---|---|---|---|
| fastapi | 0.162.0 | MIT | https://pypi.org/project/fastapi/ | none |
| uvicorn | 0.54.0 | BSD-3-Clause | https://pypi.org/project/uvicorn/ | none |
| pydantic | 2.14.2 | MIT | https://pypi.org/project/pydantic/ | none |
| pydantic-settings | 2.16.2 | MIT | https://pypi.org/project/pydantic-settings/ | none |
| typer | 0.27.3 | MIT | https://pypi.org/project/typer/ | none |
| httpx | 0.28.1 | BSD-3-Clause | https://pypi.org/project/httpx/ | none |
| websockets | 17.4 | BSD-3-Clause | https://pypi.org/project/websockets/ | none |
| pillow | 13.0.0 | MIT-CMU (HPND-style) | https://pypi.org/project/pillow/ | none |
| react, react-dom | 19.3.1 | MIT | https://www.npmjs.com/package/react | none |
| vite | 8.3.5 | MIT | https://www.npmjs.com/package/vite | none |

## Models
Picked by Phase 03 (ADR-0018; licences read from each Hugging Face model card and repo metadata at the pinned commit on 2026-11-02 15:30 CST); Phase 06 adds them to the manifest and Phase 16 audits. Weights are never committed or redistributed.

| Name | Version / SHA-256 | Licence | URL | Flags (e.g. non-commercial, OpenRAIL-M) |
|---|---|---|---|---|
| RealVisXL V5.0 Lightning (fp16) | `fabcadd9330dcc4f9702063428d40b9d4d07168d8acefc819b8d1d9db466b3ec` | OpenRAIL++-M | https://huggingface.co/SG161222/RealVisXL_V5.0_Lightning | default set; OpenRAIL use restrictions |
| Juggernaut XL v9 (RunDiffusionPhoto v2) | `c9e3e68f89b8e38689e1097d4be4573cf308de4e3fd044c64ca697bdb4aa8bca` | CreativeML OpenRAIL-M | https://huggingface.co/RunDiffusion/Juggernaut-XL-v9 | default set; OpenRAIL-M use restrictions |
| SDXL VAE fp16 fix | `235745af8d86bf4a4c1b5b4f529868b37019a10f7c0b2e79ad0abca3a22bc6e1` | MIT | https://huggingface.co/madebyollin/sdxl-vae-fp16-fix | default set |
| 4xNomosWebPhoto RealPLKSR | `9be0228f98156a100d6636d99b373ed2785b999723f9adc4cca504329ab157f2` | CC-BY-4.0 | https://huggingface.co/Phips/4xNomosWebPhoto_RealPLKSR | default set; attribution required |
| Realistic Vision V6.0 B1 (noVAE, fp16) | `c48bfd159cd7a6507b128685e963c398fa72399cefafaf603781df50ce836cc7` | CreativeML OpenRAIL-M | https://huggingface.co/SG161222/Realistic_Vision_V6.0_B1_noVAE | full set (SD 1.5); OpenRAIL-M use restrictions |
| sd-vae-ft-mse-original (840000 EMA pruned) | `735e4c3a447a3255760d7f86845f09f937809baa529c17370d83e4c3758f3c75` | MIT | https://huggingface.co/stabilityai/sd-vae-ft-mse-original | full set (SD 1.5) |

## Development tooling
| Name | Version | Licence | URL | Flags |
|---|---|---|---|---|
| gitleaks | 8.30.1 | MIT | https://github.com/gitleaks/gitleaks | none |
| pre-commit-hooks | v6.0.0 | MIT | https://github.com/pre-commit/pre-commit-hooks | none |
| pytest, pytest-asyncio, pytest-cov | 9.2.0 / 1.4.1.post1 / 7.1.0 | MIT / Apache-2.0 / MIT | https://pypi.org/ | dev only |
| hypothesis | 6.170.14 | MPL-2.0 | https://pypi.org/project/hypothesis/ | dev only (property tests) |
| ruff, mypy, pip-audit | 0.17.3 / 2.4.1 / 2.10.1 | MIT / MIT / Apache-2.0 | https://pypi.org/ | dev only |
| vitest, jsdom, Testing Library, eslint, typescript-eslint, prettier, typescript | 5.1.0 / 30.1.3 / 16.3.3 / 10.14.0 / 8.72.1 / 3.9.10 / 6.0.3 | MIT (typescript: Apache-2.0) | https://www.npmjs.com/ | dev only |
| @playwright/test | 1.64.1 | Apache-2.0 | https://www.npmjs.com/package/@playwright/test | dev only; downloads Chromium to `~/.cache/ms-playwright` |
