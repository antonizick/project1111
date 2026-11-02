"""Candidate models and their sampler settings (from each model card, checked 2026-11-02 15:30 CST)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sampler:
    name: str
    scheduler: str
    steps: int
    cfg: float
    hires_steps: int


@dataclass(frozen=True)
class ModelCfg:
    key: str
    family: str  # sdxl | sd15
    ckpt: str
    vae: str | None
    lora: str | None
    samplers: tuple[Sampler, ...]  # first one is the default
    bucket: tuple[int, int]  # native 16:9 bucket


SDXL_16x9 = (1344, 768)
SD15_16x9 = (1024, 576)

MODELS: dict[str, ModelCfg] = {
    m.key: m
    for m in [
        ModelCfg("realvisxl5", "sdxl", "RealVisXL_V5.0_fp16.safetensors", "sdxl_vae.safetensors", None,
                 (Sampler("dpmpp_sde", "karras", 30, 5.0, 15), Sampler("dpmpp_2m", "karras", 40, 5.0, 15)),
                 SDXL_16x9),
        ModelCfg("juggernautxl9", "sdxl", "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors", None, None,
                 (Sampler("dpmpp_2m", "karras", 30, 4.5, 15), Sampler("dpmpp_2m", "karras", 40, 4.5, 15)),
                 SDXL_16x9),
        ModelCfg("realvisxl5_lightning", "sdxl", "RealVisXL_V5.0_Lightning_fp16.safetensors", "sdxl_vae.safetensors",
                 None, (Sampler("dpmpp_sde", "karras", 5, 1.5, 3), Sampler("dpmpp_sde", "karras", 8, 2.0, 4)),
                 SDXL_16x9),
        ModelCfg("dreamshaperxl_turbo", "sdxl", "DreamShaperXL_Turbo_v2_1.safetensors", "sdxl_vae.safetensors", None,
                 (Sampler("dpmpp_sde", "karras", 6, 2.0, 3), Sampler("dpmpp_sde", "karras", 8, 2.0, 4)),
                 SDXL_16x9),
        ModelCfg("juggernautxl9_lightning4", "sdxl", "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors", None,
                 "sdxl_lightning_4step_lora.safetensors",
                 (Sampler("euler", "sgm_uniform", 4, 1.0, 2),), SDXL_16x9),
        ModelCfg("realisticvision6", "sd15", "Realistic_Vision_V6.0_NV_B1_fp16.safetensors",
                 "vae-ft-mse-840000-ema-pruned.safetensors", None,
                 (Sampler("dpmpp_sde", "karras", 25, 5.0, 12), Sampler("dpmpp_2m_sde", "karras", 40, 5.0, 20)),
                 SD15_16x9),
    ]
}

PRESETS = {"native": None, "1920x1080": (1920, 1080), "2560x1440": (2560, 1440)}
UPSCALERS = {"nomos_plksr": "4xNomosWebPhoto_RealPLKSR.safetensors", "ultrasharp": "4x-UltraSharp.safetensors"}
