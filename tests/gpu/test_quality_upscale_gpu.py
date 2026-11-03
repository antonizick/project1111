"""Acceptance (Phase 14): Speed and Quality upscale at both wallpaper sizes, no OOM, times recorded.

Each case compiles a ``generate`` with ``quality`` off (Speed, the ``model`` chain) or on (Quality,
the ``latent`` chain), runs it on the pinned engine under the GPU lock (R24) and appends the warm
time to ``~/.cache/p11/bench/quality/times.jsonl``. Outputs are checked for size and not being flat;
no image is kept.
"""

import io
import json
import time
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from tests.helpers import recipe

from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.models.registry import ModelManager
from p11.recipe.compile import compile
from p11.recipe.model import Generate

DATA = Path.home() / ".local/share/p11"
TIMES = Path.home() / ".cache/p11/bench/quality/times.jsonl"
SIZES = {"16:9-1920x1080": (1920, 1080), "16:9-2560x1440": (2560, 1440)}


@pytest.mark.gpu
@pytest.mark.parametrize("quality", [False, True], ids=["speed", "quality"])
async def test_wallpaper_upscale_modes_run_without_oom(
    monkeypatch: pytest.MonkeyPatch, quality: bool
) -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    for var in ("P11_CONFIG_DIR", "P11_DATA_DIR", "P11_CACHE_DIR", "P11_PICTURES_DIR"):
        monkeypatch.delenv(var, raising=False)
    registry = ModelManager(DATA / "models").registry()
    engine = ComfyEngine(EngineConfig.default(lock_timeout=3600))
    await engine.start()
    try:
        for aspect, size in SIZES.items():
            r = recipe(
                Generate(
                    prompt="a lighthouse on a rocky coast at dusk", aspect=aspect, quality=quality
                ),
            )
            (warm,) = compile(r, {}, registry, seed=1111)
            await engine.run(warm, timeout=900)  # warm the models
            # A new seed: the engine would answer an identical graph from its cache, with no image.
            (graph,) = compile(r, {}, registry, seed=2222)
            start = time.perf_counter()
            result = await engine.run(graph, timeout=900)
            seconds = round(time.perf_counter() - start, 1)
            (out,) = result.images
            with Image.open(io.BytesIO(out.data)) as img:
                assert img.size == size
                stat = ImageStat.Stat(img.convert("RGB"))
                assert max(stat.mean) > 10 and max(stat.stddev) > 5
            TIMES.parent.mkdir(parents=True, exist_ok=True)
            with TIMES.open("a") as fh:
                fh.write(
                    json.dumps({"aspect": aspect, "quality": quality, "seconds": seconds}) + "\n"
                )
    finally:
        await engine.aclose()
