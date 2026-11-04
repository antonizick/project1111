"""Phase 17b photo-edit tuning on the laptop: strengths x 6 P11-generated photos (ADR-0038).

Stage ``generate`` makes the six source photos with the default model and synthetic prompts (a
person, a house, an empty room, two products, a landscape; no real people, S6) at two sizes: the
16:9 wallpaper (1920x1080, bucket 1344x768) and the square (1024x1024). Stage ``edit`` uploads each
one and runs every candidate strength with an edit prompt, then writes ``results.json`` and one
contact grid per photo. Stage ``detect`` times the face detector on a 1920x1080 photo.

    uv run python scripts/bench/photo_edit_tune.py generate
    uv run python scripts/bench/photo_edit_tune.py edit
    uv run python scripts/bench/photo_edit_tune.py edit2   # Change at 0.70 / 0.75 on four photos
    uv run python scripts/bench/photo_edit_tune.py detect

Runs through the Studio API in-process on ``ComfyEngine`` (GPU lock R24, power profile H8);
everything lands in ``~/.cache/p11/bench/photo-edit/`` (not in git).
"""

from __future__ import annotations

import json
import statistics
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
from p11.media.faces import FaceKit, detect_faces  # noqa: E402
from p11.recipe.model import FileRef, FixedSeed, Generate, Recipe  # noqa: E402

DATA = Path.home() / ".local/share/p11"
OUT = Path.home() / ".cache/p11/bench/photo-edit"
SOURCES: list[tuple[str, str, str, str]] = [
    # (key, aspect, source prompt, edit prompt)
    (
        "person",
        "16:9-1920x1080",
        "full body photo of a man in a plain grey t-shirt and jeans standing in a park",
        "a man in a leather jacket and fedora, adventurer outfit",
    ),
    (
        "house",
        "16:9-1920x1080",
        "a white two-storey suburban house with a narrow driveway, sunny day",
        "the same house painted green, wider driveway",
    ),
    (
        "room",
        "16:9-1920x1080",
        "an empty living room with white walls, wooden floor and a large window",
        "a modern furnished living room, sofa, rug, plants, warm light",
    ),
    (
        "sneaker",
        "1:1-1024",
        "product photo of a white canvas sneaker on a plain grey background",
        "the same sneaker in bright red leather",
    ),
    (
        "mug",
        "1:1-1024",
        "product photo of a plain white ceramic mug on a wooden table",
        "the same mug made of polished copper",
    ),
    (
        "landscape",
        "1:1-1024",
        "a green alpine valley with a river and mountains in summer",
        "the same valley in winter, covered in snow",
    ),
]
CANDIDATES: tuple[tuple[str, float | None], ...] = (
    ("light", 0.25), ("light", None), ("light", 0.45),
    ("change", None), ("change", 0.65),
    ("reimagine", None), ("reimagine", 0.85),
)  # fmt: skip


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
    c, auth = client(OUT / "gen-studio")
    with performance(), c:
        for i, (key, aspect, prompt, _) in enumerate(SOURCES):
            r = Recipe.new(key, [Generate(prompt=prompt, aspect=aspect)],
                           seed=FixedSeed(value=1700 + i))  # fmt: skip
            body = {"recipe": r.model_dump(mode="json")}
            job = wait(c, auth, c.post("/api/jobs", headers=auth, json=body).json()["id"])
            assert job["state"] == "done", job
            data = c.get(f"/api/images/{job['images'][0]}", headers=auth).content
            (OUT / "sources" / f"{key}.png").write_bytes(data)
            print(key, "ok", flush=True)


#: Second round: Change between 0.65 (outfit, colour) and 0.75 (the room is furnished).
CANDIDATES_2: tuple[tuple[str, float | None], ...] = (("change", 0.7), ("change", 0.75))
KEYS_2 = ("person", "house", "room", "sneaker")


def edit(
    candidates: tuple[tuple[str, float | None], ...] = CANDIDATES,
    keys: tuple[str, ...] | None = None,
    out_name: str = "results.json",
) -> None:
    c, auth = client(OUT / "edit-studio")
    results: list[dict[str, Any]] = []
    with performance() as previous, c:
        print("power profile was", previous, flush=True)
        for key, _aspect, _prompt, change in SOURCES:
            if keys is not None and key not in keys:
                continue
            src = (OUT / "sources" / f"{key}.png").read_bytes()
            up = c.post("/api/uploads?kind=image", headers=auth, content=src).json()
            for preset, denoise in candidates:
                step = Generate(prompt=change, denoise_preset=None if denoise else preset,  # type: ignore[arg-type]
                                denoise=denoise)  # fmt: skip
                r = Recipe.new(f"{key}-{preset}", [step], source_image=FileRef(ref=up["id"]),
                               seed=FixedSeed(value=77))  # fmt: skip
                t0 = time.monotonic()
                with Monitor() as mon:
                    body = {"recipe": r.model_dump(mode="json")}
                    job = wait(c, auth, c.post("/api/jobs", headers=auth, json=body).json()["id"])
                wall = time.monotonic() - t0
                ok = job["state"] == "done"
                name = f"{key}__{preset}-{denoise if denoise else 'preset'}.png"
                rec: dict[str, Any] = {}
                size = None
                if ok:
                    (OUT / "results").mkdir(exist_ok=True)
                    data = c.get(f"/api/images/{job['images'][0]}", headers=auth).content
                    (OUT / "results" / name).write_bytes(data)
                    rec = c.get(f"/api/images/{job['images'][0]}/recipe", headers=auth).json()
                    size = [o["width"], o["height"]] if (o := rec["step_outputs"][-1]) else None
                results.append({
                    "key": key, "preset": preset, "denoise": denoise, "ok": ok,
                    "error": job.get("error"), "wall_s": round(wall, 2),
                    "engine_s": rec.get("timings", {}).get("total"), "size": size,
                    "likeness": rec.get("likeness"),
                    "vram_peak_mib": mon.peak("vram_mib"), "temp_peak_c": mon.peak("temp_c"),
                    "file": name,
                })  # fmt: skip
                print(json.dumps(results[-1]), flush=True)
    (OUT / out_name).write_text(json.dumps(results, indent=1))
    if out_name != "results.json":
        results = json.loads((OUT / "results.json").read_text()) + results
    grids(results)


def grids(results: list[dict[str, Any]]) -> None:
    (OUT / "grids").mkdir(exist_ok=True)
    for key, *_ in SOURCES:
        files = [("source", OUT / "sources" / f"{key}.png")] + [
            (r["file"].split("__")[1][:-4], OUT / "results" / r["file"])
            for r in results if r["key"] == key and r["ok"]
        ]  # fmt: skip
        tw = 400
        first = Image.open(files[0][1])
        th = round(tw * first.height / first.width)
        cols = 5
        rows = -(-len(files) // cols)
        grid = Image.new("RGB", (tw * cols, (th + 20) * rows), "white")
        d = ImageDraw.Draw(grid)
        for i, (label, path) in enumerate(files):
            x, y = (i % cols) * tw, (i // cols) * (th + 20)
            grid.paste(Image.open(path).convert("RGB").resize((tw, th)), (x, y + 20))
            d.text((x + 4, y + 4), label, fill="black")
        grid.save(OUT / "grids" / f"{key}.jpg", quality=85)


def detect() -> None:
    """Face detector cost on the person photo (1920x1080), CPU, warm, 20 runs."""
    kit = FaceKit(resolve=lambda mid: next((DATA / "models").rglob(f"{mid}.onnx")))
    data = (OUT / "sources" / "person.png").read_bytes()
    faces, size = detect_faces(data, kit)  # warm-up: loads the model
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        detect_faces(data, kit)
        times.append(time.perf_counter() - t0)
    print(json.dumps({"size": size, "faces": len(faces), "median_ms":
                      round(statistics.median(times) * 1000, 1), "max_ms": round(max(times) * 1000, 1)}))  # fmt: skip


if __name__ == "__main__":
    {"generate": generate, "edit": edit, "detect": detect,
     "edit2": lambda: edit(CANDIDATES_2, KEYS_2, "results-2.json"),
     "grids": lambda: grids(json.loads((OUT / "results.json").read_text()))}[sys.argv[1]]()  # fmt: skip
