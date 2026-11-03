"""Acceptance (Phase 04): the compiled ``16:9 1920x1080 photoreal`` graph runs on the pinned engine.

The graph is compiled in this process (pure) and run through ``ComfyEngine`` (Phase 05) with the
real XDG paths, so it uses the installed engine, the real models directory and the real GPU lock
(R24). ``/prompt`` validating the graph is the acceptance criterion; the run finishing with a
1920x1080 image is the stronger check. The engine's scratch copy is deleted (S6).
"""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from tests.helpers import recipe

from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.recipe.compile import compile
from p11.recipe.model import Generate
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET

DATA = Path.home() / ".local/share/p11"


@pytest.mark.gpu
async def test_compiled_wallpaper_graph_runs_on_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    for sub, name in [
        ("checkpoints", "RealVisXL_V5.0_Lightning_fp16.safetensors"),
        ("vae", "sdxl_vae.safetensors"),
        ("upscale", "4xNomosWebPhoto_RealPLKSR.safetensors"),
    ]:
        if not (DATA / "models" / sub / name).exists():
            pytest.skip(f"default-set model missing: {name}")
    for var in ("P11_CONFIG_DIR", "P11_DATA_DIR", "P11_CACHE_DIR", "P11_PICTURES_DIR"):
        monkeypatch.delenv(var, raising=False)
    r = recipe(Generate(prompt="a lighthouse on a rocky coast at dusk", aspect="16:9-1920x1080"))
    (graph,) = compile(r, {}, PROVISIONAL_DEFAULT_SET)
    engine = ComfyEngine(EngineConfig.default(lock_timeout=1800))
    await engine.start()
    try:
        result = await engine.run(graph, timeout=600)
    finally:
        await engine.aclose()
    (out,) = result.images
    with Image.open(io.BytesIO(out.data)) as img:
        assert img.size == (1920, 1080)
        stat = ImageStat.Stat(img.convert("RGB"))
        assert max(stat.mean) > 10 and max(stat.stddev) > 5, "image is black or flat"
    assert not (engine.config.output_dir / out.subfolder / out.filename).exists()
