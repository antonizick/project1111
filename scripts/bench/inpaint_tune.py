"""Phase 10 inpaint tuning on the laptop: presets x candidate strengths on 10 P11-generated images.

Stage ``generate`` makes the 10 source images (1920x1080, default model, synthetic prompts only);
stage ``inpaint`` paints each one's mask (``masks.json``: relative ellipses picked after looking at the
sources) with every candidate denoise, plus one full-image run (crop off), and writes
``results.json`` and per-image contact grids (original, every variant, and a zoom on the mask).

    uv run python scripts/bench/inpaint_tune.py generate
    uv run python scripts/bench/inpaint_tune.py inpaint

Runs through the Studio API in-process on ``ComfyEngine`` (GPU lock R24, power profile H8);
everything lands in ``~/.cache/p11/bench/inpaint/`` (not in git).
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.bench.gpumon import Monitor  # noqa: E402
from scripts.bench.power import performance  # noqa: E402

from p11.api.app import create_app  # noqa: E402
from p11.api.security import Session  # noqa: E402
from p11.api.studio import StudioPaths  # noqa: E402
from p11.config import load_settings  # noqa: E402
from p11.engine.comfy import ComfyEngine, EngineConfig  # noqa: E402
from p11.recipe.model import FileRef, FixedSeed, Generate, Inpaint, Recipe, Slot  # noqa: E402

DATA = Path.home() / ".local/share/p11"
OUT = Path.home() / ".cache/p11/bench/inpaint"
SOURCES: list[tuple[str, str, str]] = [
    # (key, prompt, what the mask should become)
    ("fisherman", "portrait of an elderly fisherman in a yellow raincoat on a harbour pier",
     "weathered smiling face, natural skin, detailed eyes"),
    ("hands", "close-up of hands holding a white ceramic coffee mug on a wooden table",
     "two natural hands with five fingers holding a mug"),
    ("car", "a red vintage car parked on a cobblestone street in an old town",
     "a blue vintage car"),
    ("apples", "a wooden kitchen table with a bowl of green apples, morning sunlight",
     "a bowl of oranges"),
    ("lake", "a calm mountain lake at sunrise with pine trees, clear sky",
     "dramatic stormy clouds"),
    ("dog", "a golden retriever sitting on a green lawn in a garden",
     "a golden retriever wearing a red collar, detailed fur"),
    ("sofa", "a modern living room with a grey sofa and a large window",
     "a dark green velvet sofa"),
    ("street", "a rainy city street at night with neon signs and a pedestrian",
     "empty wet street with reflections"),
    ("office", "full body photo of a man in a navy business suit standing in a bright office",
     "a man's face, natural skin, short hair"),
    ("beach", "a tropical beach with palm trees and turquoise sea",
     "a white sailboat on the sea"),
]
CANDIDATES: dict[str, tuple[float, ...]] = {
    "subtle": (0.3, 0.4),
    "balanced": (0.55, 0.65),
    "major": (0.85, 1.0),
}


def client(tmp: Path) -> tuple[TestClient, dict[str, str]]:
    settings = load_settings(models_root=DATA / "models", outputs_root=tmp / "pictures")
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=1800))
    session = Session()
    app = create_app(
        web_dir=tmp / "none", engine=engine, settings=settings, session=session, port=8111,
        studio_paths=StudioPaths.sandbox(tmp), sampler=None,
    )  # fmt: skip
    return TestClient(app, base_url="http://127.0.0.1:8111"), {
        "authorization": f"Bearer {session.token}"
    }


def wait(c: TestClient, auth: dict[str, str], job_id: str) -> dict[str, Any]:
    while True:
        job = c.get(f"/api/jobs/{job_id}", headers=auth).json()
        if job["state"] in ("done", "failed", "cancelled"):
            return dict(job)
        time.sleep(0.25)


def generate() -> None:
    (OUT / "sources").mkdir(parents=True, exist_ok=True)
    tmp = OUT / "gen-studio"
    c, auth = client(tmp)
    with performance(), c:
        for i, (key, prompt, _) in enumerate(SOURCES):
            r = Recipe.new(key, [Generate(prompt=prompt, aspect="16:9-1920x1080")],
                           seed=FixedSeed(value=1100 + i))  # fmt: skip
            job = wait(c, auth, c.post("/api/jobs", headers=auth,
                                       json={"recipe": r.model_dump(mode="json")}).json()["id"])  # fmt: skip
            assert job["state"] == "done", job
            data = c.get(f"/api/images/{job['images'][0]}", headers=auth).content
            (OUT / "sources" / f"{key}.png").write_bytes(data)
            print(key, "ok", flush=True)


def ellipse_mask(size: tuple[int, int], spec: tuple[float, float, float, float]) -> bytes:
    w, h = size
    cx, cy, rx, ry = spec
    img = Image.new("L", size, 0)
    ImageDraw.Draw(img).ellipse(
        (int((cx - rx) * w), int((cy - ry) * h), int((cx + rx) * w), int((cy + ry) * h)), fill=255
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def inpaint() -> None:
    masks = json.loads((OUT / "masks.json").read_text())
    tmp = OUT / "inpaint-studio"
    c, auth = client(tmp)
    results: list[dict[str, Any]] = []
    runs = [(p, d, True) for p, ds in CANDIDATES.items() for d in ds] + [("balanced", None, False)]
    with performance() as previous, c:
        print("power profile was", previous, flush=True)
        for key, _prompt, fix in SOURCES:
            src = (OUT / "sources" / f"{key}.png").read_bytes()
            up = c.post("/api/uploads?kind=image", headers=auth, content=src).json()
            size = (up["width"], up["height"])
            mask = c.post("/api/uploads?kind=mask", headers=auth,
                          content=ellipse_mask(size, tuple(masks[key]))).json()  # fmt: skip
            for preset, denoise, crop in runs:
                step = Inpaint(
                    mask_slot="mask", prompt=fix, crop=crop,
                    denoise_preset=None if denoise is not None else preset,
                    denoise=denoise if denoise is not None else 0.6,
                )  # fmt: skip
                r = Recipe.new(f"{key}-{preset}", [step], slots=(Slot(name="mask", kind="mask"),),
                               source_image=FileRef(ref=up["id"]), seed=FixedSeed(value=77))  # fmt: skip
                body = {"recipe": r.model_dump(mode="json"), "bindings": {"mask": {"ref": mask["id"]}}}
                t0 = time.monotonic()
                with Monitor() as mon:
                    job = wait(c, auth, c.post("/api/jobs", headers=auth, json=body).json()["id"])
                wall = time.monotonic() - t0
                ok = job["state"] == "done"
                name = f"{key}__{preset}-{denoise if denoise is not None else 'preset'}-{'crop' if crop else 'full'}.png"
                if ok:
                    (OUT / "results").mkdir(exist_ok=True)
                    data = c.get(f"/api/images/{job['images'][0]}", headers=auth).content
                    (OUT / "results" / name).write_bytes(data)
                rec = c.get(f"/api/images/{job['images'][0]}/recipe", headers=auth).json() if ok else {}
                results.append({
                    "key": key, "preset": preset, "denoise": denoise, "crop": crop, "ok": ok,
                    "error": job.get("error"), "wall_s": round(wall, 2),
                    "engine_s": rec.get("timings", {}).get("total"),
                    "vram_peak_mib": mon.peak("vram_mib"), "temp_peak_c": mon.peak("temp_c"),
                    "file": name,
                })  # fmt: skip
                print(json.dumps(results[-1]), flush=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    grids(results, masks)


def grids(results: list[dict[str, Any]], masks: dict[str, list[float]]) -> None:
    (OUT / "grids").mkdir(exist_ok=True)
    for key, *_ in SOURCES:
        files = [("source", OUT / "sources" / f"{key}.png")] + [
            (r["file"].split("__")[1][:-4], OUT / "results" / r["file"])
            for r in results if r["key"] == key and r["ok"]
        ]
        cx, cy, rx, ry = masks[key]
        tw, th = 480, 270
        grid = Image.new("RGB", (tw * len(files), th * 2 + 20), "white")
        d = ImageDraw.Draw(grid)
        for i, (label, path) in enumerate(files):
            img = Image.open(path).convert("RGB")
            w, h = img.size
            grid.paste(img.resize((tw, th)), (i * tw, 20))
            pad = 1.4
            box = (max(0, int((cx - rx * pad) * w)), max(0, int((cy - ry * pad) * h)),
                   min(w, int((cx + rx * pad) * w)), min(h, int((cy + ry * pad) * h)))  # fmt: skip
            zoom = img.crop(box)
            zoom.thumbnail((tw, th))
            grid.paste(zoom, (i * tw, 20 + th))
            d.text((i * tw + 4, 4), label, fill="black")
        grid.save(OUT / "grids" / f"{key}.jpg", quality=85)


if __name__ == "__main__":
    {"generate": generate, "inpaint": inpaint,
     "grids": lambda: grids(json.loads((OUT / "results.json").read_text()),
                            json.loads((OUT / "masks.json").read_text()))}[sys.argv[1]]()  # fmt: skip
