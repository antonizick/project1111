"""Per-run benchmark result schema (one JSON file per run under ~/.cache/p11/bench/runs/)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class MachineState(BaseModel):
    power_profile: str
    on_ac: bool
    driver: str
    gpu: str
    vram_total_mib: int
    vram_idle_mib: int = Field(description="VRAM in use before the engine started (desktop)")


class BenchResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    stage: str
    model: str
    family: Literal["sdxl", "sd15"]
    preset: str
    gen_size: tuple[int, int]
    out_size: tuple[int, int]
    chain: Literal["native", "latent", "model", "both"]
    vram_mode: str
    sampler: str
    scheduler: str
    steps: int
    cfg: float
    seed: int
    prompt_id: str
    cold: bool
    seconds: float | None = Field(description="queue to last output, wall clock")
    it_per_s: float | None = Field(description="base sampler iterations per second")
    peak_vram_mib: int | None = Field(description="peak total VRAM used on the GPU during the run")
    peak_vram_engine_mib: int | None = Field(description="peak minus the pre-engine idle VRAM")
    peak_ram_mib: int | None = Field(description="peak RSS of the engine process")
    gpu_temp_max_c: int | None = None
    oom: bool = False
    error: str | None = None
    output_path: str | None = None
    timestamp: str
    machine: MachineState
