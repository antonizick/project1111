"""Phase 05 adapter benchmark: 20 back-to-back wallpapers through ``ComfyEngine`` (spec R5).

A/B in one session, under the GPU lock and the performance power profile (H8, restored after):
  A. 10 warm runs through the Phase 03 bench client (``scripts.bench.engine``, sync, as measured
     in docs/P11_BENCHMARKS.md);
  B. 20 back-to-back runs through ``p11.engine.ComfyEngine`` (async, events, output fetch);
  C. 3 interrupt-latency measurements (interrupt call → ``EngineInterrupted``).
Default model and preset: RealVisXL V5.0 Lightning, ``16:9-1920x1080`` photoreal, ``model`` chain.
Telemetry is sampled at 1 Hz with ``p11.gpu.telemetry``. Results:
``~/.cache/p11/bench/adapter/<timestamp>.json``.

Run: ``uv run python -m scripts.bench.adapter`` (real XDG paths; no ``P11_*`` overrides).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from p11.engine.base import EngineInterrupted, Progress
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.gpu.telemetry import default_sampler, stream
from p11.gpulock import gpu_lock
from p11.recipe.compile import compile
from p11.recipe.model import FixedSeed, Generate, Recipe
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET
from scripts.bench import power
from scripts.bench.engine import Engine as BenchEngine

OUT = Path.home() / ".cache/p11/bench/adapter"
PROMPT = "a lighthouse on a rocky coast at dusk"


def graph(seed: int):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    r = Recipe(
        id="bench-adapter",
        name="adapter bench",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        seed=FixedSeed(value=seed),
        steps=(Generate(prompt=PROMPT, aspect="16:9-1920x1080"),),
    )
    (g,) = compile(r, {}, PROVISIONAL_DEFAULT_SET, seed=seed)
    return g


def summary(xs: list[float]) -> dict[str, float]:
    return {
        "n": len(xs),
        "median": round(statistics.median(xs), 2),
        "mean": round(statistics.fmean(xs), 2),
        "min": round(min(xs), 2),
        "max": round(max(xs), 2),
    }


def run_bench_client(n: int) -> list[float]:
    times: list[float] = []
    with BenchEngine() as eng:
        eng.run(graph(100).nodes)  # warm-up (cold load)
        for i in range(n):
            res = eng.run(graph(200 + i).nodes)
            assert res.error is None, res.error
            assert res.seconds is not None
            times.append(res.seconds)
            for p in res.images:
                p.unlink(missing_ok=True)
        eng.free()
    return times


async def run_adapter(n: int) -> dict[str, Any]:
    eng = ComfyEngine(EngineConfig.default(lock_path=None))  # the bench holds the lock already
    sampler = default_sampler()
    samples: list[dict[str, Any]] = []
    stop = asyncio.Event()

    async def monitor() -> None:
        if sampler is None:
            return
        async for s in stream(sampler):
            samples.append({"t": s.at, "vram": s.vram_used_mib, "temp": s.temp_c, "w": s.power_w})
            if stop.is_set():
                return

    t_start = time.monotonic()
    await eng.start()
    started = time.monotonic() - t_start
    mon = asyncio.create_task(monitor())
    runs: list[dict[str, float]] = []
    interrupts: list[float] = []
    try:
        cold = await eng.run(graph(100))
        for i in range(n):
            res = await eng.run(graph(300 + i))
            (img,) = res.images
            runs.append({"seconds": res.seconds, "fetch": res.fetch_seconds, "bytes": len(img.data)})
            print(f"[adapter] {i + 1}/{n} {res.seconds:.2f}s (+{res.fetch_seconds:.3f}s fetch)", flush=True)
        for i in range(3):
            first = asyncio.Event()

            def on_event(ev: object, first: asyncio.Event = first) -> None:
                if isinstance(ev, Progress) and ev.step >= 2:
                    first.set()

            task = asyncio.create_task(eng.run(graph(400 + i), on_event=on_event))
            await first.wait()
            t0 = time.monotonic()
            await eng.interrupt()
            try:
                await task
            except EngineInterrupted:
                interrupts.append(time.monotonic() - t0)
        await eng.free_memory(unload_models=True)
    finally:
        stop.set()
        await asyncio.wait_for(mon, 5)
        await eng.aclose()
        if sampler is not None:
            sampler.close()
    secs = [r["seconds"] for r in runs]
    return {
        "engine_start_s": round(started, 2),
        "cold_s": round(cold.seconds, 2),
        "runs": runs,
        "seconds": summary(secs),
        "fetch": summary([r["fetch"] for r in runs]),
        "interrupt_s": [round(x, 3) for x in interrupts],
        "peak_vram_mib": max((s["vram"] for s in samples), default=None),
        "max_temp_c": max((s["temp"] for s in samples), default=None),
        "telemetry_samples": len(samples),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with gpu_lock(timeout=1800, holder="p11 bench (phase 05 adapter)"), power.performance() as prev:
        print(f"[adapter] power profile performance (was {prev})", flush=True)
        a = run_bench_client(10)
        print(f"[adapter] bench client: {summary(a)}", flush=True)
        b = asyncio.run(run_adapter(20))
    ma, mb = statistics.median(a), b["seconds"]["median"]
    result = {
        "when": time.strftime("%Y-%m-%d %H:%M %Z"),
        "preset": "16:9-1920x1080 photoreal (RealVisXL V5.0 Lightning, model chain)",
        "bench_client": summary(a),
        "adapter": b,
        "overhead_pct": round((mb - ma) / ma * 100, 2),
        "overhead_incl_fetch_pct": round((mb + b["fetch"]["median"] - ma) / ma * 100, 2),
    }
    path = OUT / f"{stamp}.json"
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "adapter"}, indent=2))
    print(json.dumps({k: v for k, v in b.items() if k != "runs"}, indent=2))
    print(f"[adapter] wrote {path}")


if __name__ == "__main__":
    main()
