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
    "segmentation",
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
    ]
)
