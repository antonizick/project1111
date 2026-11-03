"""Aspect/wallpaper presets and style presets: the one table of generation defaults (R3, R17).

Values come from Phase 03 (ADR-0010, ADR-0018, ``docs/P11_BENCHMARKS.md``): models generate at their
native bucket and the preset's chain upscales to the output size. ``model`` is the default chain for
the wallpaper presets; ``latent`` is the provisional Quality chain (Phase 14 confirms it).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Chain
from .registry import Family

DEFAULT_MODEL = "realvisxl5-lightning"
QUALITY_MODEL = "juggernautxl9"
DEFAULT_UPSCALER = "4x-nomos-webphoto-realplksr"
#: Subject segmentation model for background replacement (Phase 11, ADR-0026).
DEFAULT_SEGMENTER = "birefnet-lite"
#: Harmonize (``relight``) denoise per UI preset (Off / Light / Strong), tuned in Phase 11
#: (``docs/P11_BENCHMARKS.md`` → Background replacement, ADR-0027).
HARMONIZE_PRESETS: dict[str, float] = {"light": 0.25, "strong": 0.45}

#: Hires-pass denoise per refinement chain (ADR-0010).
HIRES_DENOISE: dict[str, float] = {"latent": 0.45, "both": 0.3}
#: Inpaint denoise per preset (UI: Subtle fix / Change / Replace), tuned on the default model in
#: Phase 10 (``docs/P11_BENCHMARKS.md`` → Inpainting, ADR-0025).
INPAINT_PRESETS: dict[str, float] = {"subtle": 0.4, "balanced": 0.65, "major": 0.85}
#: Crop-and-stitch working size: a crop smaller than this many pixels is scaled up to it (at most
#: ``INPAINT_MAX_UPSCALE`` times); one larger than ``INPAINT_MAX_PIXELS`` shrinks to fit 8 GB.
INPAINT_WORK_PIXELS = 1024 * 1024
INPAINT_MAX_UPSCALE = 4.0
INPAINT_MAX_PIXELS = 2560 * 1440
#: Tiled VAE settings for decodes/encodes above the native bucket (ADR-0009).
VAE_TILE = 512
VAE_OVERLAP = 64


@dataclass(frozen=True)
class AspectPreset:
    id: str
    label: str
    #: Native generation size per model family.
    bucket: dict[Family, tuple[int, int]]
    #: Final size; ``None`` means the bucket is the output (no upscale chain).
    output: tuple[int, int] | None
    chain: Chain = "native"
    quality_chain: Chain = "native"

    def size_for(self, family: Family) -> tuple[int, int]:
        return self.bucket[family]


@dataclass(frozen=True)
class StylePreset:
    id: str
    label: str
    prefix: str
    suffix: str
    negative: str
    aspect: str
    model: str = DEFAULT_MODEL
    tags: tuple[str, ...] = field(default=())

    def positive(self, prompt: str) -> str:
        return ", ".join(p for p in (self.prefix, prompt.strip(), self.suffix) if p)

    def negative_for(self, extra: str) -> str:
        return ", ".join(p for p in (self.negative, extra.strip()) if p)


ASPECTS: dict[str, AspectPreset] = {
    a.id: a
    for a in [
        AspectPreset(
            "16:9-1920x1080",
            "Wallpaper 1920 x 1080 (16:9)",
            {"sdxl": (1344, 768), "sd15": (1024, 576)},
            (1920, 1080),
            "model",
            "latent",
        ),
        AspectPreset(
            "16:9-2560x1440",
            "Wallpaper 2560 x 1440 (16:9)",
            {"sdxl": (1344, 768), "sd15": (1024, 576)},
            (2560, 1440),
            "model",
            "latent",
        ),
        AspectPreset(
            "1:1-1024",
            "Square 1024",
            {"sdxl": (1024, 1024), "sd15": (512, 512)},
            (1024, 1024),
            "model",
            "latent",
        ),
        AspectPreset(
            "logo-1:1",
            "Logo (square)",
            {"sdxl": (1024, 1024), "sd15": (512, 512)},
            (1024, 1024),
            "model",
            "model",
        ),
        AspectPreset(
            "avatar-4:5",
            "Avatar (portrait)",
            {"sdxl": (896, 1152), "sd15": (512, 640)},
            None,
        ),
    ]
}

_PHOTO_NEGATIVE = (
    "worst quality, low quality, blurry, deformed, disfigured, bad anatomy, extra fingers, "
    "watermark, signature, jpeg artifacts"
)
_LOGO_NEGATIVE = (
    "photo, photorealistic, gradient noise, clutter, busy background, blurry, low quality, "
    "jpeg artifacts, watermark, signature, misspelled text"
)

STYLES: dict[str, StylePreset] = {
    s.id: s
    for s in [
        StylePreset(
            "photoreal",
            "Photoreal",
            "photo",
            "highly detailed, natural light, sharp focus",
            _PHOTO_NEGATIVE,
            "16:9-1920x1080",
        ),
        StylePreset(
            "3d-animated-avatar",
            "3D animated avatar (bobblehead)",
            "3d animated character, bobblehead caricature",
            "big head small body, glossy 3d render, soft studio lighting, cute, vibrant colors",
            "photo, realistic skin, " + _PHOTO_NEGATIVE,
            "avatar-4:5",
        ),
        StylePreset(
            "logo-flat",
            "Logo (flat)",
            "minimalist flat vector logo",
            "clean lines, simple shapes, two to three colors, centered, plain background",
            _LOGO_NEGATIVE,
            "logo-1:1",
        ),
        StylePreset(
            "logo-3d",
            "Logo (3D)",
            "3d logo emblem",
            "glossy bevelled render, studio lighting, centered, plain dark background",
            _LOGO_NEGATIVE,
            "logo-1:1",
        ),
    ]
}


# --- Phase 12 defaults (face, pose and reference) ---------------------------------------------
#: The face tools P11 runs itself (``p11.media.faces``); the manifest IDs it resolves models by.
DEFAULT_SWAPPER = "inswapper-128"
DEFAULT_DETECTOR = "yunet-2023mar"
DEFAULT_RECOGNIZER = "arcface-w600k-r50"
DEFAULT_RESTORER = "gfpgan-1.4"
#: The S5 NSFW target guard's classifiers (ADR-0029): both must be installed.
DEFAULT_GUARD_CLASSIFIERS = ("nsfw-marqo-384", "nsfw-freepik-eva02")
#: Pose and reference controls (ADR-0030, ADR-0031).
DEFAULT_CONTROLNET = "controlnet-union-sdxl-promax"
DEFAULT_IPADAPTER = "ip-adapter-plus-sdxl"
DEFAULT_IPADAPTER_FACE = "ip-adapter-plus-face-sdxl"
DEFAULT_CLIPVISION = "clip-vit-h-14-encoder"
#: Pose extraction and the depth map (``p11.media.pose`` / ``p11.media.control``).
DEFAULT_POSE_DETECTOR = "dwpose-yolox-l"
DEFAULT_POSE_ESTIMATOR = "dwpose-ll-ucoco-384"
DEFAULT_DEPTH_MODEL = "depth-anything-v2-small"
