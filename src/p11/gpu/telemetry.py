"""GPU telemetry at ≤ 1 Hz and the thermal guard (spec R5, R19, H9; ADR-0020).

Primary source: NVML through ``nvidia-ml-py`` (NVIDIA's official binding, BSD-3-Clause, a pure
Python ctypes wheel). Fallback: ``nvidia-smi --query-gpu`` CSV. Both produce a ``GpuSample``.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

#: Fastest sampling rate P11 uses (R19: telemetry must not load the GPU or the CPU).
MIN_INTERVAL = 1.0

#: Clock event (throttle) reason bits, from NVML's ``nvmlClocksEventReason*`` constants.
THROTTLE_REASONS: dict[int, str] = {
    0x1: "gpu_idle",
    0x2: "applications_clocks",
    0x4: "sw_power_cap",
    0x8: "hw_slowdown",
    0x10: "sync_boost",
    0x20: "sw_thermal",
    0x40: "hw_thermal",
    0x80: "hw_power_brake",
    0x100: "display_clocks",
}

SMI_FIELDS = (
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "power.draw",
    "clocks.sm",
    "clocks.mem",
    "clocks_event_reasons.active",
)


@dataclass(frozen=True)
class GpuSample:
    vram_used_mib: int
    vram_total_mib: int
    temp_c: int
    power_w: float | None
    sm_clock_mhz: int | None
    mem_clock_mhz: int | None
    throttle_reasons: tuple[str, ...]
    at: float

    @property
    def vram_free_mib(self) -> int:
        return self.vram_total_mib - self.vram_used_mib

    @property
    def thermal_throttled(self) -> bool:
        return any(r in ("sw_thermal", "hw_thermal", "hw_slowdown") for r in self.throttle_reasons)


class GpuSampler(Protocol):
    name: str

    def sample(self) -> GpuSample: ...

    def close(self) -> None: ...


class TelemetryUnavailable(RuntimeError):
    pass


def decode_reasons(mask: int) -> tuple[str, ...]:
    return tuple(name for bit, name in THROTTLE_REASONS.items() if mask & bit)


# ---------------------------------------------------------------------------------------------
# nvidia-smi


def _num(text: str) -> float | None:
    text = text.strip()
    if not text or text.startswith("[") or text.lower() in ("n/a", "[n/a]"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_nvidia_smi(output: str, at: float | None = None) -> GpuSample:
    """Parse one line of ``nvidia-smi --query-gpu=<SMI_FIELDS> --format=csv,noheader,nounits``."""
    line = next((ln for ln in output.splitlines() if ln.strip()), "")
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != len(SMI_FIELDS):
        raise TelemetryUnavailable(f"unexpected nvidia-smi output: {line!r}")
    used, total, temp, power, sm, mem, reasons = parts
    u, t, c = _num(used), _num(total), _num(temp)
    if u is None or t is None or c is None:
        raise TelemetryUnavailable(f"nvidia-smi did not report memory/temperature: {line!r}")
    try:
        mask = int(reasons, 16) if reasons.lower().startswith("0x") else 0
    except ValueError:
        mask = 0
    sm_c, mem_c = _num(sm), _num(mem)
    return GpuSample(
        vram_used_mib=int(u),
        vram_total_mib=int(t),
        temp_c=int(c),
        power_w=_num(power),
        sm_clock_mhz=int(sm_c) if sm_c is not None else None,
        mem_clock_mhz=int(mem_c) if mem_c is not None else None,
        throttle_reasons=decode_reasons(mask),
        at=time.time() if at is None else at,
    )


class NvidiaSmiSampler:
    name = "nvidia-smi"

    def __init__(self, index: int = 0, binary: str | None = None) -> None:
        self.binary = binary or shutil.which("nvidia-smi")
        if not self.binary:
            raise TelemetryUnavailable("nvidia-smi is not installed")
        self.index = index

    def sample(self) -> GpuSample:
        cmd = [
            self.binary or "nvidia-smi",
            f"--id={self.index}",
            f"--query-gpu={','.join(SMI_FIELDS)}",
            "--format=csv,noheader,nounits",
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TelemetryUnavailable(f"nvidia-smi failed: {exc}") from exc
        return parse_nvidia_smi(out.stdout)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------------------------
# NVML


class NvmlSampler:
    name = "nvml"

    def __init__(self, index: int = 0) -> None:
        try:
            import pynvml
        except ImportError as exc:  # pragma: no cover - it is a declared dependency
            raise TelemetryUnavailable("nvidia-ml-py is not installed") from exc
        self._nvml = pynvml
        try:
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        except pynvml.NVMLError as exc:
            raise TelemetryUnavailable(f"NVML is not available: {exc}") from exc

    def sample(self) -> GpuSample:
        n = self._nvml
        h = self._handle
        try:
            mem = n.nvmlDeviceGetMemoryInfo(h, version=n.nvmlMemory_v2)
            temp = n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU)
            reasons = n.nvmlDeviceGetCurrentClocksEventReasons(h)
        except n.NVMLError as exc:
            raise TelemetryUnavailable(f"NVML query failed: {exc}") from exc
        power: float | None
        try:
            power = n.nvmlDeviceGetPowerUsage(h) / 1000.0
        except n.NVMLError:
            power = None
        sm: int | None
        memclk: int | None
        try:
            sm = int(n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM))
            memclk = int(n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM))
        except n.NVMLError:
            sm = memclk = None
        mib = 1024 * 1024
        return GpuSample(
            vram_used_mib=int(mem.used) // mib,
            vram_total_mib=int(mem.total) // mib,
            temp_c=int(temp),
            power_w=power,
            sm_clock_mhz=sm,
            mem_clock_mhz=memclk,
            throttle_reasons=decode_reasons(int(reasons)),
            at=time.time(),
        )

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._nvml.nvmlShutdown()


def default_sampler() -> GpuSampler | None:
    """NVML if it initialises, else ``nvidia-smi``, else ``None`` (no NVIDIA GPU)."""
    for factory in (NvmlSampler, NvidiaSmiSampler):
        try:
            return factory()
        except TelemetryUnavailable:
            continue
    return None


async def stream(sampler: GpuSampler, interval: float = MIN_INTERVAL) -> AsyncIterator[GpuSample]:
    """Yield samples forever, at most once per ``MIN_INTERVAL`` seconds."""
    interval = max(interval, MIN_INTERVAL)
    while True:
        started = time.monotonic()
        yield await asyncio.to_thread(sampler.sample)
        await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))


# ---------------------------------------------------------------------------------------------
# Thermal guard

ThermalState = Literal["ok", "paused"]


class ThermalGuard:
    """Pause at ``pause_at`` °C, resume at ``resume_at`` °C or below (hysteresis; no flapping).

    Thresholds come from settings (``thermal_pause_c`` / ``thermal_resume_c``; H9: 87 / 80 °C).
    The video and batch jobs (Phase 13) call ``update`` with each sample between frames.
    """

    def __init__(self, pause_at: int, resume_at: int) -> None:
        if resume_at >= pause_at:
            raise ValueError("resume_at must be below pause_at")
        self.pause_at = pause_at
        self.resume_at = resume_at
        self.state: ThermalState = "ok"
        self.transitions = 0

    @property
    def paused(self) -> bool:
        return self.state == "paused"

    def update(self, temp_c: float) -> ThermalState:
        if self.state == "ok" and temp_c >= self.pause_at:
            self.state = "paused"
            self.transitions += 1
        elif self.state == "paused" and temp_c <= self.resume_at:
            self.state = "ok"
            self.transitions += 1
        return self.state
