"""Phase 11 background-replacement tuning on the laptop (tasks 1 and 6).

Stage ``subjects`` generates the test material with the pinned engine: 10 subjects to put on new
backgrounds (portraits and products) and 10 subjects on a solid green screen (the chroma key is
their ground-truth mask for the segmentation measurements). Stage ``segment`` measures the
segmenters (IoU vs the chroma key, wall time); ``composite`` renders 10 subject x background
pairs with the colour-match strengths; ``harmonize`` runs the relight pass through the Studio API
pairs with the colour-match strengths; ``harmonize`` runs the relight pass through the Studio
API (light/strong) and records wall time and VRAM. Everything lands in
``~/.cache/p11/bench/background/`` (not in git); contact grids are for the owner's eye;
the numbers go to ``docs/P11_BENCHMARKS.md``.
    uv run python scripts/bench/background_tune.py subjects
    uv run python scripts/bench/background_tune.py segment
    uv run python scripts/bench/background_tune.py composite
    uv run python scripts/bench/background_tune.py harmonize

GPU stages run through the Studio API in-process on ``ComfyEngine`` (GPU lock R24, power profile
H8); the segmentation and composite stages are CPU only (ADR-0026).
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.media import composite as comp
from p11.media.segment import Segmenters
from p11.models.registry import ModelManager
from p11.recipe.model import (
    FileRef,
    FixedSeed,
    Generate,
    Recipe,
    ReplaceBackground,
    Slot,
)
from scripts.bench.gpumon import Monitor
from scripts.bench.power import performance

DATA = Path.home() / ".local/share/p11"
OUT = Path.home() / ".cache/p11/bench/background"
BACKGROUNDS = Path.home() / ".cache/p11/bench/inpaint/sources"  # the Phase 10 photos

SUBJECTS: list[tuple[str, str]] = [
    ("portrait1", "portrait of a smiling woman with curly hair in a beige sweater, studio photo"),
    ("portrait2", "portrait of a bald man with a beard wearing a dark jacket, studio photo"),
    ("mug", "product photo of a red ceramic coffee mug on a plain table"),
    ("sneakers", "product photo of white sneakers on a plain floor"),
    ("plant", "product photo of a potted green plant in a terracotta pot"),
    ("portrait3", "portrait of a young man in a white shirt, studio photo"),
    ("laptop", "product photo of an open laptop computer on a plain desk"),
    ("statue", "product photo of a small bronze horse statue"),
    ("portrait4", "portrait of an elderly woman with glasses wearing a blue cardigan"),
    ("chair", "product photo of a wooden chair against a plain wall"),
]
GREEN = "against a completely flat solid green chroma-key background, no shadows"


def client(tmp: Path) -> tuple[TestClient, dict[str, str]]:
    settings = load_settings(models_root=DATA / "models", outputs_root=tmp / "pictures")
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=3600))
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


def subjects() -> None:
    """10 subjects to composite and 10 on green (ground truth), 1024x1024, fixed seeds."""
    for folder in ("subjects", "greens"):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    tmp = OUT / "gen-studio"
    c, auth = client(tmp)
    with performance() as previous, c:
        print("power profile was", previous, flush=True)
        for i, (key, prompt) in enumerate(SUBJECTS):
            for folder, suffix in (("subjects", ""), ("greens", f", {GREEN}")):
                path = OUT / folder / f"{key}.png"
                if path.exists():
                    continue
                r = Recipe.new(
                    key,
                    [Generate(prompt=prompt + suffix, aspect="1:1-1024")],
                    seed=FixedSeed(value=2100 + i),
                )
                job = wait(
                    c,
                    auth,
                    c.post(
                        "/api/jobs", headers=auth, json={"recipe": r.model_dump(mode="json")}
                    ).json()["id"],
                )
                assert job["state"] == "done", job
                data = c.get(f"/api/images/{job['images'][0]}", headers=auth).content
                path.write_bytes(data)
            print(key, "ok", flush=True)


def chroma_mask(data: bytes) -> Image.Image:
    """Ground truth from a green-screen render: background where green dominates strongly."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    px = img.load()
    m = Image.new("L", img.size, 0)
    mp = m.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = px[x, y]
            mp[x, y] = 0 if (g > 100 and g > r * 1.3 and g > b * 1.3) else 255
    return m


def iou(a: Image.Image, b: Image.Image) -> float:
    import numpy as np

    aa = np.asarray(a, bool)
    bb = np.asarray(b, bool)
    union = (aa | bb).sum()
    return float((aa & bb).sum() / union) if union else 1.0


def _segments() -> Any:
    manager = ModelManager(DATA / "models")

    def resolve(mid: str) -> Path:
        entry = manager.manifest.get(mid)
        if entry is None:
            raise KeyError(mid)
        return manager.path_of(entry)

    return Segmenters(resolve)


def segment() -> None:
    """IoU vs the chroma key and wall time for the default and the high-quality model."""
    segments = _segments()
    (OUT / "masks").mkdir(exist_ok=True)
    results = []
    for key, _ in SUBJECTS:
        green = (OUT / "greens" / f"{key}.png").read_bytes()
        gt = chroma_mask(green)
        for mid in ("birefnet-lite", "birefnet"):
            t0 = time.monotonic()
            mask = Image.open(io.BytesIO(segments.segmenter(mid).mask(green))).convert("L")
            dt = time.monotonic() - t0
            mask.save(OUT / "masks" / f"{key}-{mid}.png")
            rec = {
                "key": key,
                "model": mid,
                "iou": round(iou(gt, mask), 4),
                "seconds": round(dt, 2),
            }
            results.append(rec)
            print(json.dumps(rec), flush=True)
    (OUT / "segment.json").write_text(json.dumps(results, indent=1))
    ios = [r["iou"] for r in results if r["model"] == "birefnet-lite"]
    print(f"\nbirefnet-lite IoU: mean {sum(ios) / len(ios):.3f}, min {min(ios):.3f}")


def pair_inputs(c: TestClient, auth: dict[str, str], i: int) -> tuple[str, str]:
    """The subject and the background photo of pair ``i`` as upload IDs."""
    key = SUBJECTS[i][0]
    bg_name = sorted(p.name for p in BACKGROUNDS.glob("*.png"))[i]
    subject = c.post(
        "/api/uploads?kind=image",
        headers=auth,
        content=(OUT / "subjects" / f"{key}.png").read_bytes(),
    ).json()
    background = c.post(
        "/api/uploads?kind=image", headers=auth, content=(BACKGROUNDS / bg_name).read_bytes()
    ).json()
    return subject["id"], background["id"]


def composite() -> None:
    """Colour-match strengths on 10 pairs, locally (no engine): grids + timing."""
    segments = _segments()
    (OUT / "results").mkdir(exist_ok=True)
    (OUT / "grids").mkdir(exist_ok=True)
    results = []
    for i, (key, _) in enumerate(SUBJECTS):
        bg_name = sorted(p.name for p in BACKGROUNDS.glob("*.png"))[i]
        subject = (OUT / "subjects" / f"{key}.png").read_bytes()
        background = (BACKGROUNDS / bg_name).read_bytes()
        t0 = time.monotonic()
        mask = segments.segmenter("birefnet-lite").mask(subject)
        seg_s = time.monotonic() - t0
        for strength in (0.0, 0.5, 1.0):
            params = comp.CompositeParams(colour_match_strength=strength, feather_px=8)
            t0 = time.monotonic()
            out, _ = comp.compose(subject, background, mask, params)
            dt = time.monotonic() - t0
            name = f"{key}__cm-{strength}.png"
            out.save(OUT / "results" / name)
            rec = {
                "key": key,
                "colour_match_strength": strength,
                "segment_s": round(seg_s, 2),
                "compose_s": round(dt, 2),
                "file": name,
            }
            results.append(rec)
            print(json.dumps(rec), flush=True)
        grid([(key, OUT / "results" / f"{key}__cm-{s}.png") for s in (0.0, 0.5, 1.0)],
             OUT / "grids" / f"{key}-colour.jpg", subject)  # fmt: skip
    (OUT / "composite.json").write_text(json.dumps(results, indent=1))


def harmonize() -> None:
    """The relight pass (light/strong) through the Studio API on 10 pairs: timings and VRAM."""
    tmp = OUT / "harm-studio"
    c, auth = client(tmp)
    results = []
    slots = (Slot(name="bg", kind="background_image"),)
    with performance() as previous, c:
        print("power profile was", previous, flush=True)
        for i, (key, _) in enumerate(SUBJECTS):
            subject, background = pair_inputs(c, auth, i)
            for label, denoise in (("light", 0.25), ("strong", 0.45)):
                step = ReplaceBackground(
                    background_slot="bg", relight=True, relight_denoise=denoise,
                    colour_match=True, feather_px=8,
                )  # fmt: skip
                r = Recipe.new(
                    f"{key}-{label}",
                    [step],
                    slots=slots,
                    source_image=FileRef(ref=subject),
                    seed=FixedSeed(value=77),
                )
                body = {
                    "recipe": r.model_dump(mode="json"),
                    "bindings": {"bg": {"ref": background}},
                }
                t0 = time.monotonic()
                with Monitor() as mon:
                    job = wait(c, auth, c.post("/api/jobs", headers=auth, json=body).json()["id"])
                wall = time.monotonic() - t0
                ok = job["state"] == "done"
                name = f"{key}__harm-{label}.png"
                if ok:
                    data = c.get(f"/api/images/{job['images'][0]}", headers=auth).content
                    (OUT / "results" / name).write_bytes(data)
                rec_api = (
                    c.get(f"/api/images/{job['images'][0]}/recipe", headers=auth).json()
                    if ok
                    else {}
                )
                rec = {
                    "key": key,
                    "harmonize": label,
                    "denoise": denoise,
                    "ok": ok,
                    "error": job.get("error"),
                    "wall_s": round(wall, 2),
                    "timings": rec_api.get("timings"),
                    "vram_peak_mib": mon.peak("vram_mib"),
                    "temp_peak_c": mon.peak("temp_c"),
                    "file": name,
                }
                results.append(rec)
                print(json.dumps(rec), flush=True)
    (OUT / "harmonize.json").write_text(json.dumps(results, indent=1))


def grid(files: list[tuple[str, Path]], out: Path, subject: bytes | None = None) -> None:
    tw, th = 384, 384
    imgs = [("original", subject)] if subject else []
    imgs += [(label, path.read_bytes()) for label, path in files]
    sheet = Image.new("RGB", (tw * len(imgs), th + 20), "white")
    from PIL import ImageDraw

    d = ImageDraw.Draw(sheet)
    for i, (label, data) in enumerate(imgs):
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((tw, th))
        sheet.paste(img, (i * tw + (tw - img.width) // 2, 20 + (th - img.height) // 2))
        d.text((i * tw + 4, 4), label, fill="black")
    sheet.save(out, quality=88)


if __name__ == "__main__":
    {
        "subjects": subjects,
        "segment": segment,
        "composite": composite,
        "harmonize": harmonize,
    }[sys.argv[1]]()
