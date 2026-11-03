"""What the compiler needs to know about a model: its engine file name, family and defaults.

``ModelRegistry`` is a protocol so the compiler stays pure. The app's registry is
``p11.models.registry.ManagerRegistry`` over ``models/manifest.toml`` and the models on disk
(Phase 06). ``PROVISIONAL_DEFAULT_SET`` is a pure in-memory copy of the manifest's default and
full sets for compiler tests and golden graphs; ``tests/unit/test_models_registry.py`` asserts
that it equals the manifest, so the two cannot drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

ModelKind = Literal[
    "checkpoint",
    "vae",
    "lora",
    "upscale",
    "controlnet",
    "ipadapter",
    "facerestore",
    "faceswap",
    "facedetect",
    "classifier",
    "preprocess",
    "segmentation",
    "clipvision",
    "embedding",
]
Family = Literal["sdxl", "sd15"]


@dataclass(frozen=True)
class SamplerDefaults:
    sampler_name: str
    scheduler: str
    steps: int
    cfg: float
    clip_skip: int = 1
    #: Steps of the refinement KSampler in the ``latent``/``both`` chains (about half the base).
    hires_steps: int = 0


@dataclass(frozen=True)
class ModelInfo:
    manifest_id: str
    kind: ModelKind
    filename: str
    sha256: str | None = None
    family: Family | None = None
    defaults: SamplerDefaults | None = None
    #: Manifest ID of the VAE to load instead of the checkpoint's baked one.
    vae: str | None = None
    #: Scale factor of an upscale model (4 for a 4x model).
    scale: int | None = None


class UnknownModelError(LookupError):
    pass


class ModelRegistry(Protocol):
    def get(self, manifest_id: str) -> ModelInfo:
        """Return the model or raise ``UnknownModelError``."""
        ...


class StaticRegistry:
    """An in-memory registry (tests, and the provisional default set)."""

    def __init__(self, models: Iterable[ModelInfo]) -> None:
        self._models: Mapping[str, ModelInfo] = {m.manifest_id: m for m in models}

    def get(self, manifest_id: str) -> ModelInfo:
        try:
            return self._models[manifest_id]
        except KeyError:
            raise UnknownModelError(
                f"Model {manifest_id!r} is not installed or not in the manifest."
            ) from None

    def __contains__(self, manifest_id: object) -> bool:
        return manifest_id in self._models


# ADR-0018 (Phase 03), re-verified at the source by Phase 06 (models/manifest.toml).
PROVISIONAL_DEFAULT_SET = StaticRegistry(
    [
        ModelInfo(
            "realvisxl5-lightning",
            "checkpoint",
            "RealVisXL_V5.0_Lightning_fp16.safetensors",
            "fabcadd9330dcc4f9702063428d40b9d4d07168d8acefc819b8d1d9db466b3ec",
            "sdxl",
            SamplerDefaults("dpmpp_sde", "karras", 5, 1.5, 1, 3),
            vae="sdxl-vae-fp16-fix",
        ),
        ModelInfo(
            "juggernautxl9",
            "checkpoint",
            "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
            "c9e3e68f89b8e38689e1097d4be4573cf308de4e3fd044c64ca697bdb4aa8bca",
            "sdxl",
            SamplerDefaults("dpmpp_2m", "karras", 30, 4.5, 1, 15),
        ),
        ModelInfo(
            "sdxl-vae-fp16-fix",
            "vae",
            "sdxl_vae.safetensors",
            "235745af8d86bf4a4c1b5b4f529868b37019a10f7c0b2e79ad0abca3a22bc6e1",
            "sdxl",
        ),
        ModelInfo(
            "4x-nomos-webphoto-realplksr",
            "upscale",
            "4xNomosWebPhoto_RealPLKSR.safetensors",
            "9be0228f98156a100d6636d99b373ed2785b999723f9adc4cca504329ab157f2",
            scale=4,
        ),
        ModelInfo(
            "realisticvision6",
            "checkpoint",
            "Realistic_Vision_V6.0_NV_B1_fp16.safetensors",
            "c48bfd159cd7a6507b128685e963c398fa72399cefafaf603781df50ce836cc7",
            "sd15",
            SamplerDefaults("dpmpp_sde", "karras", 25, 5.0, 1, 12),
            vae="vae-ft-mse-840000",
        ),
        ModelInfo(
            "vae-ft-mse-840000",
            "vae",
            "vae-ft-mse-840000-ema-pruned.safetensors",
            "735e4c3a447a3255760d7f86845f09f937809baa529c17370d83e4c3758f3c75",
            "sd15",
        ),
        ModelInfo(
            "birefnet-lite",
            "segmentation",
            "birefnet-lite.onnx",
            "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333",
        ),
        ModelInfo(
            "birefnet",
            "segmentation",
            "birefnet.onnx",
            "58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c",
        ),
        # Phase 12: face, pose and reference (ADR-0028…0031), sets `face` and `control`.
        ModelInfo(
            "yunet-2023mar",
            "facedetect",
            "yunet-2023mar.onnx",
            "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        ),
        ModelInfo(
            "arcface-w600k-r50",
            "facedetect",
            "arcface-w600k-r50.onnx",
            "f1f79dc3b0b79a69f94799af1fffebff09fbd78fd96a275fd8f0cbbea23270d1",
        ),
        ModelInfo(
            "inswapper-128",
            "faceswap",
            "inswapper-128.onnx",
            "a290273ed497312095dac48cdef20feec9d5208298223dd01288ab202b54bea7",
        ),
        ModelInfo(
            "gfpgan-1.4",
            "facerestore",
            "gfpgan-1.4.onnx",
            "accc4757b26bdb89b32b4d3500d4f79c9dff97c1dd7c7104bf9dcb95e3311385",
        ),
        ModelInfo(
            "nsfw-marqo-384",
            "classifier",
            "nsfw-marqo-384.onnx",
            "5aae1806ce44e3c27fab0a7d44eed581dd25ca71a4387ff809a191c98239c1be",
        ),
        ModelInfo(
            "nsfw-freepik-eva02",
            "classifier",
            "nsfw-freepik-eva02.onnx",
            "778139fb930240ac39812a1480295bfc5dc2cec8a8e46ee6b453481d600c0fa2",
        ),
        ModelInfo(
            "dwpose-yolox-l",
            "preprocess",
            "dwpose-yolox-l.onnx",
            "7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411",
        ),
        ModelInfo(
            "dwpose-ll-ucoco-384",
            "preprocess",
            "dwpose-ll-ucoco-384.onnx",
            "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843",
        ),
        ModelInfo(
            "depth-anything-v2-small",
            "preprocess",
            "depth-anything-v2-small.onnx",
            "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c",
        ),
        ModelInfo(
            "controlnet-union-sdxl-promax",
            "controlnet",
            "controlnet-union-sdxl-promax.safetensors",
            "9fae2e50cb431bfcbe05822b59ec2228df545ef27f711dea8949e9f4ed9f7cdc",
            "sdxl",
        ),
        ModelInfo(
            "ip-adapter-plus-sdxl",
            "ipadapter",
            "ip-adapter-plus-sdxl.safetensors",
            "3f5062b8400c94b7159665b21ba5c62acdcd7682262743d7f2aefedef00e6581",
            "sdxl",
        ),
        ModelInfo(
            "ip-adapter-plus-face-sdxl",
            "ipadapter",
            "ip-adapter-plus-face-sdxl.safetensors",
            "677ad8860204f7d0bfba12d29e6c31ded9beefdf3e4bbd102518357d31a292c1",
            "sdxl",
        ),
        ModelInfo(
            "clip-vit-h-14-encoder",
            "clipvision",
            "clip-vit-h-14-encoder.safetensors",
            "6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030",
            "sdxl",
        ),
    ]
)
