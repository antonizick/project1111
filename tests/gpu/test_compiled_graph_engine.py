"""Acceptance (Phase 04): the compiled ``16:9 1920x1080 photoreal`` graph runs on the pinned engine.

The graph is compiled in this process (pure); a child process with the real XDG paths takes the GPU
lock (R24), starts ComfyUI through ``scripts.bench.engine`` (Phase 05 replaces it with
``p11.engine``), queues the graph and reports the output. ``/prompt`` validating the graph is the
acceptance criterion; the run finishing with a 1920x1080 image is the stronger check.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from tests.helpers import recipe

from p11.recipe.compile import compile
from p11.recipe.model import Generate
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET

REPO = Path(__file__).resolve().parents[2]
DATA = Path.home() / ".local/share/p11"

CHILD = r"""
import json, sys
from scripts.bench.engine import Engine
from p11.gpulock import gpu_lock
graph = json.loads(sys.stdin.read())
with gpu_lock(timeout=1800, holder="p11 gpu-test (phase 04 compiled graph)"), Engine() as eng:
    res = eng.run(graph, timeout=600)
out = {"error": res.error, "seconds": res.seconds, "images": [str(p) for p in res.images]}
print(json.dumps(out))
"""


@pytest.mark.gpu
def test_compiled_wallpaper_graph_runs_on_engine() -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    for sub, name in [
        ("checkpoints", "RealVisXL_V5.0_Lightning_fp16.safetensors"),
        ("vae", "sdxl_vae.safetensors"),
        ("upscale", "4xNomosWebPhoto_RealPLKSR.safetensors"),
    ]:
        if not (DATA / "models" / sub / name).exists():
            pytest.skip(f"default-set model missing: {name}")
    r = recipe(Generate(prompt="a lighthouse on a rocky coast at dusk", aspect="16:9-1920x1080"))
    (graph,) = compile(r, {}, PROVISIONAL_DEFAULT_SET)
    env = {k: v for k, v in os.environ.items() if not k.startswith("P11_")}
    proc = subprocess.run(
        [sys.executable, "-c", CHILD],
        cwd=REPO,
        env=env,
        input=graph.to_json().decode(),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    res = json.loads(proc.stdout.strip().splitlines()[-1])
    assert res["error"] is None, res
    (out,) = res["images"]
    try:
        with Image.open(out) as img:
            assert img.size == (1920, 1080)
            stat = ImageStat.Stat(img.convert("RGB"))
            assert max(stat.mean) > 10 and max(stat.stddev) > 5, "image is black or flat"
    finally:
        Path(out).unlink(missing_ok=True)  # engine scratch output; nothing kept (S6)
