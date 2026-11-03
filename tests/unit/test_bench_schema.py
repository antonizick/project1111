"""The bench result schema round-trips and rejects bad values (Phase 03)."""

import pytest
from pydantic import ValidationError
from scripts.bench import gpumon
from scripts.bench.schema import SCHEMA_VERSION, BenchResult, MachineState


def _result(**over: object) -> BenchResult:
    base: dict[str, object] = dict(
        run_id="r1",
        stage="presets",
        model="realvisxl5",
        family="sdxl",
        preset="1920x1080",
        gen_size=(1344, 768),
        out_size=(1920, 1080),
        chain="model",
        vram_mode="dynamic",
        sampler="dpmpp_sde/karras",
        scheduler="karras",
        steps=30,
        cfg=5.0,
        seed=1111,
        prompt_id="p01",
        cold=False,
        seconds=21.5,
        it_per_s=1.9,
        peak_vram_mib=6900,
        peak_vram_engine_mib=5400,
        peak_ram_mib=9000,
        timestamp="2026-11-02 15:40:00 CST",
        machine=MachineState(
            power_profile="performance",
            on_ac=True,
            driver="615.78.08",
            gpu="RTX 2070",
            vram_total_mib=8192,
            vram_idle_mib=1500,
        ),
    )
    base.update(over)
    return BenchResult.model_validate(base)


def test_round_trip() -> None:
    r = _result()
    again = BenchResult.model_validate_json(r.model_dump_json())
    assert again == r
    assert again.schema_version == SCHEMA_VERSION
    assert again.oom is False and again.error is None


def test_rejects_unknown_chain_and_family() -> None:
    with pytest.raises(ValidationError):
        _result(chain="tiled")
    with pytest.raises(ValidationError):
        _result(family="flux")


def test_failed_run_has_no_timing() -> None:
    r = _result(
        seconds=None, it_per_s=None, oom=True, error="torch.OutOfMemoryError: CUDA out of memory"
    )
    assert r.oom and r.seconds is None


def test_gpumon_parse() -> None:
    s = gpumon.parse(["5123", "71", "1290", "65.20", "0x0000000000000004", "98"])
    assert s["vram_mib"] == 5123 and s["temp_c"] == 71 and s["throttle"] == 4
    assert (
        gpumon.parse(["[N/A]", "1", "2", "3", "0x0", "4"])["vram_mib"]
        != gpumon.parse(["1"])["vram_mib"]
    )
