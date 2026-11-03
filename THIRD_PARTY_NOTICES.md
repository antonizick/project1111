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
| nvidia-ml-py (`pynvml` module) | 13.615.71 | BSD-3-Clause | https://pypi.org/project/nvidia-ml-py/ | NVIDIA's NVML binding; loads the driver's `libnvidia-ml` at run time (Phase 05, ADR-0020) |
| onnxruntime | 1.31.1 | MIT | https://pypi.org/project/onnxruntime/ | CPU execution provider only (Phase 11, ADR-0026) |
| numpy | 2.5.4 | BSD-3-Clause (0BSD, MIT, Zlib, CC0 components per metadata) | https://pypi.org/project/numpy/ | none |
| react, react-dom | 19.3.1 | MIT | https://www.npmjs.com/package/react | none |
| vite | 8.3.5 | MIT | https://www.npmjs.com/package/vite | none |
| ffmpeg / ffprobe (system package) | 9.0.2 (Arch `2:9.0.2-2`) | GPL-3.0-only (Arch build) | https://ffmpeg.org/ | not bundled: run as separate programs to check and remux uploaded videos (Phase 07, ADR-0022); licence read with `pacman -Qi ffmpeg` 2026-11-02 23:52 CST |

## Models
Picked by Phase 03 (ADR-0018) and pinned in `models/manifest.toml` by Phase 06 (ADR-0021). Revision, size, SHA-256 and licence tag re-read from the Hugging Face API, the hash recomputed over the downloaded file and the licence URLs fetched on 2026-11-02 19:42 CST. Weights are never committed or redistributed; P11 downloads them from these repositories at the pinned commit. Phase 16 audits.

| Name (manifest ID) | Source @ commit | SHA-256 | Licence | Commercial use | Flags / set |
|---|---|---|---|---|---|
| RealVisXL V5.0 Lightning fp16 (`realvisxl5-lightning`) | [SG161222/RealVisXL_V5.0_Lightning](https://huggingface.co/SG161222/RealVisXL_V5.0_Lightning) @ `f4454158` | `fabcadd9330dcc4f9702063428d40b9d4d07168d8acefc819b8d1d9db466b3ec` | [CreativeML Open RAIL++-M](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md) | yes | use restrictions; default |
| Juggernaut XL v9 RunDiffusionPhoto v2 (`juggernautxl9`) | [RunDiffusion/Juggernaut-XL-v9](https://huggingface.co/RunDiffusion/Juggernaut-XL-v9) @ `cf419233` | `c9e3e68f89b8e38689e1097d4be4573cf308de4e3fd044c64ca697bdb4aa8bca` | [CreativeML OpenRAIL-M](https://huggingface.co/spaces/CompVis/stable-diffusion-license) | yes | use restrictions; default |
| SDXL VAE fp16 fix (`sdxl-vae-fp16-fix`) | [madebyollin/sdxl-vae-fp16-fix](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix) @ `207b116d` | `235745af8d86bf4a4c1b5b4f529868b37019a10f7c0b2e79ad0abca3a22bc6e1` | [MIT](https://opensource.org/license/mit) | yes | none; default |
| 4xNomosWebPhoto RealPLKSR (`4x-nomos-webphoto-realplksr`) | [Phips/4xNomosWebPhoto_RealPLKSR](https://huggingface.co/Phips/4xNomosWebPhoto_RealPLKSR) @ `49d5da19` | `9be0228f98156a100d6636d99b373ed2785b999723f9adc4cca504329ab157f2` | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) | yes | attribution required; default |
| Realistic Vision V6.0 B1 noVAE fp16 (`realisticvision6`) | [SG161222/Realistic_Vision_V6.0_B1_noVAE](https://huggingface.co/SG161222/Realistic_Vision_V6.0_B1_noVAE) @ `9a857a69` | `c48bfd159cd7a6507b128685e963c398fa72399cefafaf603781df50ce836cc7` | [CreativeML OpenRAIL-M](https://huggingface.co/spaces/CompVis/stable-diffusion-license) | yes | use restrictions; full (SD 1.5) |
| sd-vae-ft-mse-original 840000 EMA pruned (`vae-ft-mse-840000`) | [stabilityai/sd-vae-ft-mse-original](https://huggingface.co/stabilityai/sd-vae-ft-mse-original) @ `629b3ad3` | `735e4c3a447a3255760d7f86845f09f937809baa529c17370d83e4c3758f3c75` | [MIT](https://opensource.org/license/mit) | yes | none; full (SD 1.5) |

Phase 11 (ADR-0026) added the segmentation models on 2026-11-03 07:30 CST: revision, size, SHA-256
and licence tag read from the Hugging Face API, the hash recomputed over the downloaded file
(`sha256sum`), and the pre/post-processing config read from the repos' `preprocessor_config.json`.
They are ONNX exports of ZhengPeng7's MIT-licensed BiRefNet (the original is linked from each
repo's card).

| Name (manifest ID) | Source @ commit | SHA-256 | Licence | Commercial use | Flags / set |
|---|---|---|---|---|---|
| BiRefNet Lite subject segmentation (`birefnet-lite`) | [onnx-community/BiRefNet_lite-ONNX](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX) @ `de15b22b` | `5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333` | [MIT](https://opensource.org/license/mit) | yes | none; default |
| BiRefNet subject segmentation (`birefnet`) | [onnx-community/BiRefNet-ONNX](https://huggingface.co/onnx-community/BiRefNet-ONNX) @ `534d3c82` | `58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c` | [MIT](https://opensource.org/license/mit) | yes | none; full |

## Development tooling
| Name | Version | Licence | URL | Flags |
|---|---|---|---|---|
| gitleaks | 8.30.1 | MIT | https://github.com/gitleaks/gitleaks | none |
| pre-commit-hooks | v6.0.0 | MIT | https://github.com/pre-commit/pre-commit-hooks | none |
| pytest, pytest-asyncio, pytest-cov | 9.2.0 / 1.4.1.post1 / 7.1.0 | MIT / Apache-2.0 / MIT | https://pypi.org/ | dev only |
| hypothesis | 6.170.14 | MPL-2.0 | https://pypi.org/project/hypothesis/ | dev only (property tests) |
| httpx2, httpcore2, truststore | 2.16.0 / 2.16.0 / 0.10.5 | BSD-3-Clause / BSD-3-Clause / MIT | https://pypi.org/project/httpx2/ | dev only: Starlette's `TestClient` transport (licences read from PyPI 2026-11-02 23:39 CST; Phase 07) |
| ruff, mypy, pip-audit | 0.17.3 / 2.4.1 / 2.10.1 | MIT / MIT / Apache-2.0 | https://pypi.org/ | dev only |
| vitest, jsdom, Testing Library, eslint, typescript-eslint, prettier, typescript | 5.1.0 / 30.1.3 / 16.3.3 / 10.14.0 / 8.72.1 / 3.9.10 / 6.0.3 | MIT (typescript: Apache-2.0) | https://www.npmjs.com/ | dev only |
| @playwright/test | 1.64.1 | Apache-2.0 | https://www.npmjs.com/package/@playwright/test | dev only; downloads Chromium to `~/.cache/ms-playwright` |
| @axe-core/playwright, axe-core | 4.14.0 / 4.14.0 | MPL-2.0 | https://www.npmjs.com/package/@axe-core/playwright | dev only: accessibility checks in the e2e walkthroughs, not shipped (licence read with `npm view` 2026-11-03 04:17 CST; Phase 08, ADR-0023) |

Phase 12 (ADR-0028…0031) added the face, pose and reference models on 2026-11-03 10:12 CST:
revision, size, SHA-256 and licence tag read from the Hugging Face API, the hash recomputed over
each downloaded file (`sha256sum`), and the licence terms read at each project's own page. The
face files are FaceFusion's hash-pinned ONNX re-hosts of InsightFace and Tencent ARC's originals;
the insightface.ai licence policy (read 2026-11-03 10:36 CST) says the models trained with their
data are **for non-commercial research purposes only** and that the inswapper and face-recognition
models need a licence from them for anything else. Those two entries are flagged
`non-commercial, research-only` and require an explicit acknowledgement before install (H3).

| Name (manifest ID) | Source @ commit | SHA-256 | Licence | Commercial use | Flags / set |
|---|---|---|---|---|---|
| YuNet face detector (`yunet-2023mar`) | [opencv/face_detection_yunet](https://huggingface.co/opencv/face_detection_yunet) @ `3cc26e7f` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | [MIT](https://opensource.org/license/mit) | yes | none; face |
| ArcFace w600k_r50 (`arcface-w600k-r50`) | [facefusion/models-3.0.0](https://huggingface.co/facefusion/models-3.0.0) @ `728b9659` (ONNX export of deepinsight/insightface `buffalo_l`) | `f1f79dc3b0b79a69f94799af1fffebff09fbd78fd96a275fd8f0cbbea23270d1` | [InsightFace model zoo: non-commercial research only](https://github.com/deepinsight/insightface#license) | **no** | non-commercial, research-only; face |
| INSwapper 128 (`inswapper-128`) | [facefusion/models-3.0.0](https://huggingface.co/facefusion/models-3.0.0) @ `728b9659` (ONNX export of deepinsight/insightface `inswapper_128`) | `a290273ed497312095dac48cdef20feec9d5208298223dd01288ab202b54bea7` | [InsightFace model zoo: non-commercial research only](https://github.com/deepinsight/insightface#license) | **no** | non-commercial, research-only; face |
| GFPGAN v1.4 (`gfpgan-1.4`) | [facefusion/models-3.0.0](https://huggingface.co/facefusion/models-3.0.0) @ `728b9659` (ONNX export of TencentARC/GFPGAN v1.4) | `accc4757b26bdb89b32b4d3500d4f79c9dff97c1dd7c7104bf9dcb95e3311385` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; face |
| NSFW classifier Marqo (`nsfw-marqo-384`) | [facefusion/models-3.3.0](https://huggingface.co/facefusion/models-3.3.0) @ `6271ab1c` (ONNX export of Marqo/nsfw-image-detection-384) | `5aae1806ce44e3c27fab0a7d44eed581dd25ca71a4387ff809a191c98239c1be` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; face (S5 guard) |
| NSFW classifier Freepik (`nsfw-freepik-eva02`) | [facefusion/models-3.3.0](https://huggingface.co/facefusion/models-3.3.0) @ `6271ab1c` (ONNX export of Freepik/nsfw_image_detector) | `778139fb930240ac39812a1480295bfc5dc2cec8a8e46ee6b453481d600c0fa2` | [MIT](https://opensource.org/license/mit) | yes | none; face (S5 guard) |
| YOLOX-L person detector (`dwpose-yolox-l`) | [yzd-v/DWPose](https://huggingface.co/yzd-v/DWPose) @ `1a714410` | `7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; control |
| DWPose whole-body estimator (`dwpose-ll-ucoco-384`) | [yzd-v/DWPose](https://huggingface.co/yzd-v/DWPose) @ `1a714410` | `724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; control |
| Depth Anything V2 Small (`depth-anything-v2-small`) | [onnx-community/depth-anything-v2-small](https://huggingface.co/onnx-community/depth-anything-v2-small) @ `4472b736` | `afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; control |
| ControlNet Union SDXL ProMax (`controlnet-union-sdxl-promax`) | [xinsir/controlnet-union-sdxl-1.0](https://huggingface.co/xinsir/controlnet-union-sdxl-1.0) @ `801a4a3f` | `9fae2e50cb431bfcbe05822b59ec2228df545ef27f711dea8949e9f4ed9f7cdc` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; control |
| IP-Adapter Plus SDXL (`ip-adapter-plus-sdxl`) | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter) @ `018e4027` | `3f5062b8400c94b7159665b21ba5c62acdcd7682262743d7f2aefedef00e6581` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; control |
| IP-Adapter Plus Face SDXL (`ip-adapter-plus-face-sdxl`) | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter) @ `018e4027` | `677ad8860204f7d0bfba12d29e6c31ded9beefdf3e4bbd102518357d31a292c1` | [Apache-2.0](https://opensource.org/license/apache-2-0) | yes | none; control |
| CLIP ViT-H/14 image encoder (`clip-vit-h-14-encoder`) | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter) @ `018e4027` | `6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030` | [Apache-2.0](https://opensource.org/license/apache-2-0) (the CLIP ViT-H/14 weights it carries are OpenAI's CLIP, MIT) | yes | none; control |

Code read at the source to implement these paths (not bundled): InsightFace's
`model_zoo/inswapper.py` (the reference swapper), FaceFusion's `face_helper.py`,
`face_recognizer.py`, `face_enhancer/core.py`, `content_analyser.py` and `face_masker.py`
(OpenRAIL-AS), DWPose's `ControlNet-v1-1-nightly/annotator/dwpose/` (Apache-2.0) and
huggingface/controlnet_aux `dwpose/util.py` (Apache-2.0) for the OpenPose drawing convention,
and the model cards for the NSFW classifiers. P11's own `engine/custom_nodes/p11_ipadapter/` is
part of this project (MIT, see `LICENSE`).

## Bundled fonts (Phase 14, text overlay)
Fonts in `assets/fonts/` are redistributed under the SIL Open Font License 1.1 (licence texts beside them as `OFL-*.txt`; commercial use and bundling allowed, the fonts may not be sold on their own). Source: the Google Fonts repository (`github.com/google/fonts`, `ofl/<family>/`), fetched and checked 2026-11-03 17:00 CST; SHA-256 values are in `assets/fonts/fonts.json` and checked by a test.

| Font | File | Source | Licence |
|---|---|---|---|
| Inter | `inter-var.ttf` | [google/fonts ofl/inter](https://github.com/google/fonts/tree/main/ofl/inter) | OFL-1.1 (`OFL-inter.txt`) |
| Space Grotesk | `space-grotesk-var.ttf` | [google/fonts ofl/spacegrotesk](https://github.com/google/fonts/tree/main/ofl/spacegrotesk) | OFL-1.1 (`OFL-spacegrotesk.txt`) |
| Playfair Display | `playfair-display-var.ttf` | [google/fonts ofl/playfairdisplay](https://github.com/google/fonts/tree/main/ofl/playfairdisplay) | OFL-1.1 (`OFL-playfairdisplay.txt`) |
| Bebas Neue | `bebas-neue.ttf` | [google/fonts ofl/bebasneue](https://github.com/google/fonts/tree/main/ofl/bebasneue) | OFL-1.1 (`OFL-bebasneue.txt`) |
| JetBrains Mono | `jetbrains-mono-var.ttf` | [google/fonts ofl/jetbrainsmono](https://github.com/google/fonts/tree/main/ofl/jetbrainsmono) | OFL-1.1 (`OFL-jetbrainsmono.txt`) |

No LoRA was added in Phase 14.
