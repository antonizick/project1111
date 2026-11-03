"""nvidia-smi parsing (captured output), NVML sampler shape, telemetry stream and ThermalGuard."""

from __future__ import annotations

import shutil

import pytest
from hypothesis import given
from hypothesis import strategies as st

from p11.config import load_settings
from p11.gpu.telemetry import (
    MIN_INTERVAL,
    GpuSample,
    NvidiaSmiSampler,
    TelemetryUnavailable,
    ThermalGuard,
    decode_reasons,
    default_sampler,
    parse_nvidia_smi,
    stream,
)

# Captured on the laptop (RTX 2070 Max-Q, driver 615.78.08) on 2026-11-02 18:40 CST:
# `nvidia-smi --query-gpu=<SMI_FIELDS> --format=csv,noheader,nounits`, idle desktop.
IDLE = "1117, 8192, 50, 9.50, 360, 405, 0x0000000000000001\n"
# Synthetic loaded line built from Phase 03's measurements (7.7 GB peak, 79 °C, ~68 W cap).
LOADED = "7735, 8192, 79, 68.12, 1380, 5500, 0x0000000000000004\n"
# Values nvidia-smi prints when a field is unsupported.
UNSUPPORTED = "512, 4096, 41, [N/A], [N/A], [N/A], [N/A]\n"


def test_parse_idle() -> None:
    s = parse_nvidia_smi(IDLE, at=1.0)
    assert s == GpuSample(1117, 8192, 50, 9.5, 360, 405, ("gpu_idle",), 1.0)
    assert s.vram_free_mib == 7075 and not s.thermal_throttled


def test_parse_loaded_power_capped() -> None:
    s = parse_nvidia_smi(LOADED)
    assert s.temp_c == 79 and s.power_w == pytest.approx(68.12)
    assert s.throttle_reasons == ("sw_power_cap",) and not s.thermal_throttled


def test_parse_unsupported_fields() -> None:
    s = parse_nvidia_smi(UNSUPPORTED)
    assert s.power_w is None and s.sm_clock_mhz is None and s.throttle_reasons == ()


@pytest.mark.parametrize("bad", ["", "garbage", "1, 2, 3", "[N/A], 8192, 50, 1, 1, 1, 0x0"])
def test_parse_rejects_bad_output(bad: str) -> None:
    with pytest.raises(TelemetryUnavailable):
        parse_nvidia_smi(bad)


def test_decode_thermal_reasons() -> None:
    assert decode_reasons(0x20 | 0x40) == ("sw_thermal", "hw_thermal")
    s = parse_nvidia_smi("100, 8192, 90, 50, 900, 5500, 0x0000000000000060")
    assert s.thermal_throttled


def test_smi_sampler_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("p11.gpu.telemetry.shutil.which", lambda _: None)
    with pytest.raises(TelemetryUnavailable):
        NvidiaSmiSampler()


def test_smi_sampler_failing_binary() -> None:
    sampler = NvidiaSmiSampler(binary="/bin/false")
    with pytest.raises(TelemetryUnavailable):
        sampler.sample()


@pytest.mark.skipif(not shutil.which("nvidia-smi"), reason="no NVIDIA GPU present")
def test_real_samplers_agree_roughly() -> None:
    smi = NvidiaSmiSampler().sample()
    sampler = default_sampler()
    assert sampler is not None
    try:
        s = sampler.sample()
    finally:
        sampler.close()
    assert s.vram_total_mib == smi.vram_total_mib
    assert abs(s.temp_c - smi.temp_c) <= 5


class ListSampler:
    name = "list"

    def __init__(self) -> None:
        self.n = 0

    def sample(self) -> GpuSample:
        self.n += 1
        return parse_nvidia_smi(IDLE, at=float(self.n))

    def close(self) -> None:
        pass


async def test_stream_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("p11.gpu.telemetry.asyncio.sleep", fake_sleep)
    it = stream(ListSampler(), interval=0.01).__aiter__()
    first = await it.__anext__()
    second = await it.__anext__()
    assert (first.at, second.at) == (1.0, 2.0)
    assert sleeps and all(s > MIN_INTERVAL - 0.2 for s in sleeps)


# -- ThermalGuard ------------------------------------------------------------------------------


def test_thermal_defaults_from_settings() -> None:
    s = load_settings()
    assert (s.thermal_pause_c, s.thermal_resume_c) == (87, 80)  # H9
    g = ThermalGuard(s.thermal_pause_c, s.thermal_resume_c)
    assert [g.update(t) for t in (70, 86, 87, 85, 81, 80, 86)] == [
        "ok",
        "ok",
        "paused",
        "paused",
        "paused",
        "ok",
        "ok",
    ]


def test_thermal_guard_rejects_inverted_band() -> None:
    with pytest.raises(ValueError):
        ThermalGuard(80, 80)
    with pytest.raises(ValueError):
        load_settings(thermal_pause_c=80, thermal_resume_c=85)


@given(
    pause=st.integers(60, 95),
    gap=st.integers(1, 15),
    temps=st.lists(st.floats(30, 110, allow_nan=False), max_size=200),
)
def test_no_flapping_inside_the_band(pause: int, gap: int, temps: list[float]) -> None:
    resume = pause - gap
    g = ThermalGuard(pause, resume)
    prev = g.state
    for t in temps:
        state = g.update(t)
        if state != prev:
            # Every transition is justified by crossing the matching threshold.
            assert (state == "paused" and t >= pause) or (state == "ok" and t <= resume)
        if resume < t < pause:
            assert state == prev  # inside the band nothing changes
        prev = state


@given(st.lists(st.floats(81, 86, allow_nan=False), min_size=1, max_size=100))
def test_band_never_transitions(temps: list[float]) -> None:
    g = ThermalGuard(87, 80)
    g.update(90)
    for t in temps:
        assert g.update(t) == "paused"
    assert g.transitions == 1
