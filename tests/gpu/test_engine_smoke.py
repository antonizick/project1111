"""Real-engine smoke test (laptop only): the pinned ComfyUI renders one 512x512 image (Phase 03).

Runs ``scripts.bench.run smoke`` in a subprocess with the real XDG paths, so it uses the installed
engine, the real models directory and the real GPU lock (R24). It leaves the power profile alone.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageStat

REPO = Path(__file__).resolve().parents[2]
DATA = Path.home() / ".local/share/p11"
CKPT = DATA / "models/checkpoints/Realistic_Vision_V6.0_NV_B1_fp16.safetensors"


@pytest.mark.gpu
def test_engine_renders_non_black_png() -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    if not CKPT.exists():
        pytest.skip(f"smoke model missing: {CKPT.name}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("P11_")}
    env["P11_BENCH_KEEP_POWER"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.bench.run", "smoke"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    runs = sorted(
        (Path.home() / ".cache/p11/bench/runs/smoke").glob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    res = json.loads(runs[-1].read_text())
    assert res["error"] is None and not res["oom"]
    img = Image.open(res["output_path"]).convert("RGB")
    assert img.size == (512, 512)
    stat = ImageStat.Stat(img)
    assert max(stat.mean) > 10 and max(stat.stddev) > 5, "image is black or flat"
