"""P11 bake-off runner. Usage (from the repo root, P11 uv env):

    uv run python -m scripts.bench.run <stage> [--models a,b] [--modes dynamic,classic] [--n 50]

Stages: smoke, base, presets, vram, stability, thermal. Every stage takes the GPU lock (R24),
switches the power profile to performance and restores it (H8), starts the pinned engine and stops
it at the end. One JSON per run goes to ~/.cache/p11/bench/runs/<stage>/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from p11.gpulock import gpu_lock

from . import gpumon, power, prompts
from .configs import MODELS, PRESETS, UPSCALERS, ModelCfg, Sampler
from .engine import BENCH, Engine, EngineError
from .graphs import base_node, build
from .schema import BenchResult, MachineState

RUNS = BENCH / "runs"


def machine(profile: str) -> MachineState:
    import subprocess

    name, drv, total, used = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split(", ")
    return MachineState(power_profile=profile, on_ac=power.on_ac(), driver=drv, gpu=name,
                        vram_total_mib=int(total), vram_idle_mib=int(used))


@contextmanager
def session(vram_mode: str) -> Iterator[tuple[Engine, MachineState]]:
    with gpu_lock(timeout=3600, holder="p11-bench (phase 03)"), power.performance() as prev:
        ms = machine(power.get_profile())
        print(f"[bench] power {prev} -> {ms.power_profile}, AC={ms.on_ac}, idle VRAM {ms.vram_idle_mib} MiB",
              flush=True)
        with Engine(vram_mode=vram_mode) as eng:
            yield eng, ms


def run_one(eng: Engine, ms: MachineState, stage: str, m: ModelCfg, s: Sampler, pid: str, seed: int,
            preset: str, chain: str, cold: bool, upscaler: str = "nomos_plksr") -> BenchResult:
    out = PRESETS[preset]
    text = prompts.ALL[pid]
    neg = prompts.NEGATIVE_SD15 if m.family == "sd15" else prompts.NEGATIVE
    run_id = f"{m.key}-{preset}-{chain}-{eng.vram_mode}-{s.name}{s.steps}-{pid}-{seed}-{int(time.time() * 1000)}"
    g = build(m, s, text, neg, seed, out, chain, UPSCALERS[upscaler], f"{stage}/{run_id}")
    if cold:
        eng.free()
    rss_peak = 0
    err = None
    with gpumon.Monitor() as mon:
        try:
            r = eng.run(g)
            err = r.error
        except EngineError as e:
            r, err = None, str(e)
        rss_peak = max(rss_peak, eng.rss_mib() or 0)
    peak = mon.peak("vram_mib")
    oom = bool(err and ("out of memory" in err.lower() or "outofmemory" in err.lower()))
    res = BenchResult(
        run_id=run_id, stage=stage, model=m.key, family=m.family,  # type: ignore[arg-type]
        preset=preset, gen_size=m.bucket, out_size=out or m.bucket,
        chain="native" if out is None else chain,  # type: ignore[arg-type]
        vram_mode=eng.vram_mode, sampler=f"{s.name}/{s.scheduler}" + (f"+{upscaler}" if chain in ("model", "both") and out else ""),
        scheduler=s.scheduler, steps=s.steps, cfg=s.cfg, seed=seed, prompt_id=pid, cold=cold,
        seconds=r.seconds if r else None, it_per_s=r.it_per_s(base_node(g)) if r else None,
        peak_vram_mib=int(peak) if peak else None,
        peak_vram_engine_mib=int(peak - ms.vram_idle_mib) if peak else None,
        peak_ram_mib=rss_peak or None, gpu_temp_max_c=int(mon.peak("temp_c") or 0) or None,
        oom=oom, error=err, output_path=str(r.images[0]) if r and r.images else None,
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S %Z"), machine=ms,
    )
    d = RUNS / stage
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run_id}.json").write_text(res.model_dump_json(indent=1))
    print(f"[{stage}] {m.key:26} {preset:9} {chain:6} {eng.vram_mode:7} {s.name}{s.steps:<3} {pid} "
          f"{'cold' if cold else 'warm'} {res.seconds or 0:6.1f}s {res.it_per_s or 0:5.2f}it/s "
          f"{res.peak_vram_mib or 0:5}MiB {'OOM' if oom else (err or 'ok')[:80]}", flush=True)
    return res


def models_arg(a: str | None) -> list[ModelCfg]:
    return [MODELS[k] for k in a.split(",")] if a else list(MODELS.values())


def _sigterm(*_: object) -> None:
    raise SystemExit(143)  # run the finally blocks: stop the engine, restore the power profile


def main(argv: list[str] | None = None) -> int:
    import signal

    signal.signal(signal.SIGTERM, _sigterm)
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["smoke", "base", "presets", "vram", "stability", "thermal"])
    ap.add_argument("--models")
    ap.add_argument("--modes", default="dynamic")
    ap.add_argument("--presets", default="1920x1080,2560x1440")
    ap.add_argument("--chains", default="latent,model,both")
    ap.add_argument("--prompts")
    ap.add_argument("--upscaler", default="nomos_plksr")
    ap.add_argument("--chain", default="model", help="stability/thermal chain")
    ap.add_argument("--preset", default="2560x1440", help="stability/thermal preset")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--minutes", type=float, default=10.0)
    a = ap.parse_args(argv)

    if a.stage == "smoke":
        m = MODELS["realisticvision6"]
        m = ModelCfg(m.key, m.family, m.ckpt, m.vae, m.lora, m.samplers, (512, 512))
        with session("dynamic") as (eng, ms):
            res = run_one(eng, ms, "smoke", m, m.samplers[0], "p01", prompts.SEEDS[0], "native", "native", True)
        return 0 if res.output_path and not res.error else 1

    for mode in a.modes.split(","):
        with session(mode) as (eng, ms):
            for m in models_arg(a.models):
                s0 = m.samplers[0]
                if a.stage == "base":
                    pids = a.prompts.split(",") if a.prompts else list(prompts.ALL)
                    for i, pid in enumerate(pids):
                        run_one(eng, ms, "base", m, s0, pid, prompts.SEEDS[0], "native", "native", cold=i == 0)
                    for s in m.samplers[1:]:
                        for pid in ("p01", "a01"):
                            run_one(eng, ms, "base", m, s, pid, prompts.SEEDS[0], "native", "native", False)
                elif a.stage in ("presets", "vram"):
                    pids = a.prompts.split(",") if a.prompts else ["p01", "p03"]
                    first = True
                    if a.stage == "vram":
                        run_one(eng, ms, "vram", m, s0, pids[0], prompts.SEEDS[0], "native", "native", True)
                        run_one(eng, ms, "vram", m, s0, pids[1], prompts.SEEDS[0], "native", "native", False)
                        first = False
                    for pi, preset in enumerate(a.presets.split(",")):
                        for ci, chain in enumerate(a.chains.split(",")):
                            for pid in pids:
                                # distinct seed per combination so ComfyUI's node cache never skips the base pass
                                seed = prompts.SEEDS[1] + 10 * pi + ci
                                run_one(eng, ms, a.stage, m, s0, pid, seed, preset, chain, first, a.upscaler)
                                first = False
                elif a.stage == "stability":
                    pids = list(prompts.ALL)
                    results = []
                    for i in range(a.n):
                        results.append(run_one(eng, ms, "stability", m, s0, pids[i % len(pids)],
                                               prompts.SEEDS[i % 3] + i, a.preset, a.chain, i == 0, a.upscaler))
                    bad = [r for r in results if r.error]
                    summary = {"model": m.key, "preset": a.preset, "chain": a.chain, "mode": mode, "n": a.n,
                               "failures": len(bad), "ooms": sum(r.oom for r in results),
                               "seconds": [r.seconds for r in results], "peak_vram": [r.peak_vram_mib for r in results]}
                    (RUNS / f"stability-summary-{m.key}-{mode}-{int(time.time())}.json").write_text(
                        json.dumps(summary, indent=1))
                    print(f"[stability] {m.key} {a.n} runs, {len(bad)} failures, {summary['ooms']} OOM")
                elif a.stage == "thermal":
                    thermal(eng, ms, m, s0, a)
    return 0


def thermal(eng: Engine, ms: MachineState, m: ModelCfg, s: Sampler, a: argparse.Namespace) -> None:
    log: list[dict[str, float]] = []
    t_end = time.time() + a.minutes * 60
    pids = list(prompts.PHOTO)
    i = 0
    with gpumon.Monitor(interval_ms=1000) as mon:
        t_start = time.time()
        while time.time() < t_end:
            run_one(eng, ms, "thermal", m, s, pids[i % len(pids)], 5000 + i, a.preset, a.chain, i == 0, a.upscaler)
            i += 1
        for t, smp in mon.samples:
            log.append({"t": round(t - t_start, 1), **smp})
    out = RUNS / f"thermal-{m.key}-{int(time.time())}.json"
    out.write_text(json.dumps({"model": m.key, "preset": a.preset, "chain": a.chain, "runs": i,
                               "machine": ms.model_dump(), "samples": log}, indent=0))
    print(f"[thermal] {i} runs in {a.minutes} min; max temp {max(x['temp_c'] for x in log)} C; -> {out}")


if __name__ == "__main__":
    sys.exit(main())
