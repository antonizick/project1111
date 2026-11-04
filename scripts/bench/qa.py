"""Phase 16 success-criteria runs on the laptop (spec R22, Definition of done), through the Studio API.

    uv run python scripts/bench/qa.py presets   # both wallpaper presets x Speed/Quality, cold + 3 warm
    uv run python scripts/bench/qa.py soak      # 50 runs in a row per wallpaper preset (default model)
    uv run python scripts/bench/qa.py mixed     # 30 min: generate, inpaint, background, face, upscale,
                                                # model switch; Studio + engine RSS and VRAM sampled
    uv run python scripts/bench/qa.py thermal   # 10 min of back-to-back 1920x1080 generations

Runs the Studio in-process on ``ComfyEngine`` (GPU lock R24, power profile H8: performance during the
run, restored afterwards, blocked on battery). Synthetic prompts only (no real people, S6); results
and images go to ``~/.cache/p11/bench/qa/`` (not in git), one JSON per stage.
"""

from __future__ import annotations

import io
import json
import os
import statistics
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.bench.gpumon import Monitor  # noqa: E402
from scripts.bench.power import get_profile, on_ac, performance  # noqa: E402
from scripts.bench.prompts import PHOTO  # noqa: E402

from p11.api.app import create_app  # noqa: E402
from p11.api.security import Session  # noqa: E402
from p11.api.studio import StudioPaths  # noqa: E402
from p11.config import load_settings  # noqa: E402
from p11.engine.comfy import ComfyEngine, EngineConfig  # noqa: E402
from p11.recipe.model import (  # noqa: E402
    FaceSwap,
    FileRef,
    FixedSeed,
    Generate,
    Inpaint,
    ModelRef,
    Recipe,
    ReplaceBackground,
    Slot,
    Upscale,
)

DATA = Path.home() / ".local/share/p11"
OUT = Path.home() / ".cache/p11/bench/qa"
PRESETS = ("16:9-1920x1080", "16:9-2560x1440")
PORTRAIT = "studio portrait photo of a smiling middle-aged man with short grey hair, plain background"
PORTRAIT2 = "studio portrait photo of a young man with a beard in a denim jacket, plain background"


class Run:
    """One Studio with the real engine; ``job()`` submits and waits."""

    def __init__(self, tmp: Path) -> None:
        settings = load_settings(models_root=DATA / "models", outputs_root=tmp / "pictures")
        self.engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=3600))
        session = Session()
        app = create_app(
            web_dir=tmp / "none", engine=self.engine, settings=settings, session=session,
            port=8116, studio_paths=StudioPaths.sandbox(tmp), sampler=None,
        )  # fmt: skip
        self.c = TestClient(app, base_url="http://127.0.0.1:8116")
        self.auth = {"authorization": f"Bearer {session.token}"}

    def __enter__(self) -> Run:
        self.c.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self.c.__exit__(*exc)

    def job(self, recipe: Recipe, bindings: dict[str, Any] | None = None) -> dict[str, Any]:
        t0 = time.monotonic()
        res = self.c.post("/api/jobs", headers=self.auth,
                          json={"recipe": recipe.model_dump(mode="json"), "bindings": bindings or {}})  # fmt: skip
        assert res.status_code == 201, res.text
        job_id = res.json()["id"]
        while True:
            job = dict(self.c.get(f"/api/jobs/{job_id}", headers=self.auth).json())
            if job["state"] in ("done", "failed", "cancelled"):
                job["seconds"] = round(time.monotonic() - t0, 2)
                return job
            time.sleep(0.2)

    def image(self, image_id: int) -> bytes:
        return self.c.get(f"/api/images/{image_id}", headers=self.auth).content

    def upload(self, data: bytes, kind: str = "image") -> str:
        res = self.c.post(f"/api/uploads?kind={kind}", content=data, headers=self.auth)
        assert res.status_code in (200, 201), res.text
        return str(res.json()["id"])

    def engine_pid(self) -> int | None:
        return self.engine.supervisor.pid


def gen(prompt: str, aspect: str, seed: int, *, quality: bool = False, model: str | None = None) -> Recipe:
    step = Generate(prompt=prompt, aspect=aspect, quality=quality,
                    model=ModelRef(manifest_id=model) if model else None)  # fmt: skip
    return Recipe.new("qa", [step], seed=FixedSeed(value=seed))


def summary(times: list[float]) -> dict[str, float]:
    if not times:
        return {}
    return {"n": len(times), "median": round(statistics.median(times), 2),
            "mean": round(statistics.fmean(times), 2), "min": min(times), "max": max(times)}  # fmt: skip


def note_oom(job: dict[str, Any]) -> bool:
    text = json.dumps({"note": job.get("note"), "error": job.get("error")}).lower()
    return "memory" in text


@contextmanager
def stage(name: str) -> Iterator[dict[str, Any]]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = get_profile()
    result: dict[str, Any] = {"stage": name, "started": datetime.now(UTC).astimezone().isoformat(),
                              "ac": on_ac(), "profile_before": before}  # fmt: skip
    with performance(), Monitor(interval_ms=1000) as mon:
        result["profile_during"] = get_profile()
        try:
            yield result
        finally:
            result["finished"] = datetime.now(UTC).astimezone().isoformat()
            result["peak_vram_mib"] = mon.peak("vram_mib")
            result["peak_temp_c"] = mon.peak("temp_c")
            result["gpu_samples"] = [(round(t, 1), s) for t, s in mon.samples]
            path = OUT / f"{name}-{int(time.time())}.json"
            path.write_text(json.dumps(result, indent=1))
            print(f"wrote {path}", flush=True)
    result["profile_after"] = get_profile()


def presets() -> None:
    prompts = list(PHOTO.values())
    with stage("presets") as res:
        rows = []
        for aspect in PRESETS:
            for quality in (False, True):
                with Run(OUT / "studio-presets") as r:
                    times, states = [], []
                    for i in range(4):  # run 0 is cold: the engine starts with the job
                        job = r.job(gen(prompts[i], aspect, 1600 + i, quality=quality))
                        states.append(job["state"])
                        times.append(job["seconds"])
                    row = {"aspect": aspect, "mode": "quality" if quality else "speed",
                           "cold_s": times[0], "warm": summary(times[1:]), "states": states}  # fmt: skip
                    rows.append(row)
                    print(json.dumps(row), flush=True)
        res["rows"] = rows


def soak() -> None:
    prompts = list(PHOTO.values())
    with stage("soak") as res:
        rows = []
        for aspect in PRESETS:
            with Run(OUT / "studio-soak") as r:
                times, failed, ooms = [], 0, 0
                for i in range(50):
                    job = r.job(gen(prompts[i % len(prompts)], aspect, 5000 + i))
                    ooms += note_oom(job)
                    if job["state"] == "done":
                        times.append(job["seconds"])
                    else:
                        failed += 1
                        print("FAILED", aspect, i, job.get("error"), flush=True)
                row = {"aspect": aspect, "ok": len(times), "failed": failed,
                       "oom_notes": ooms, "times": summary(times), "first_s": times[0] if times else None}  # fmt: skip
                rows.append(row)
                print(json.dumps(row), flush=True)
        res["rows"] = rows


def rss_mib(pid: int | None) -> float | None:
    if pid is None:
        return None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


def ellipse_png(size: tuple[int, int]) -> bytes:
    w, h = size
    img = Image.new("L", size, 0)
    ImageDraw.Draw(img).ellipse((int(w * 0.35), int(h * 0.3), int(w * 0.65), int(h * 0.7)), fill=255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def mixed(minutes: float = 30.0) -> None:
    prompts = list(PHOTO.values())
    with stage("mixed") as res, Run(OUT / "studio-mixed") as r:
        steps: list[dict[str, Any]] = []
        mem: list[dict[str, Any]] = []
        t_end = time.monotonic() + minutes * 60
        face = r.job(gen(PORTRAIT, "1:1-1024", 31))
        assert face["state"] == "done", face
        face_ref = r.upload(r.image(face["images"][0]))
        cycle = 0

        def log(kind: str, job: dict[str, Any]) -> dict[str, Any]:
            row = {"cycle": cycle, "kind": kind, "state": job["state"], "seconds": job["seconds"],
                   "error": job.get("error"), "oom": note_oom(job)}  # fmt: skip
            steps.append(row)
            mem.append({"t": round(time.monotonic(), 1), "studio_rss_mib": rss_mib(os.getpid()),
                        "engine_rss_mib": rss_mib(r.engine_pid())})  # fmt: skip
            print(json.dumps(row | mem[-1]), flush=True)
            return job

        while time.monotonic() < t_end:
            base = log("generate", r.job(gen(prompts[cycle % 10], "16:9-1920x1080", 7000 + cycle)))
            if base["state"] != "done":
                cycle += 1
                continue
            src = FileRef(ref=f"gallery/{base['images'][0]}")
            mask = r.upload(ellipse_png((1920, 1080)), kind="mask")
            inp = Recipe.new("qa-inpaint", [Inpaint(mask_slot="m", prompt="a small wooden cabin")],
                             slots=(Slot(name="m", kind="mask"),), source_image=src,
                             seed=FixedSeed(value=cycle))  # fmt: skip
            log("inpaint", r.job(inp, {"m": {"ref": mask}}))
            bg = Recipe.new("qa-bg", [ReplaceBackground(background_colour="#336699")],
                            source_image=src, seed=FixedSeed(value=cycle))  # fmt: skip
            log("background", r.job(bg))
            target = log("generate-portrait", r.job(gen(PORTRAIT2, "1:1-1024", 8000 + cycle)))
            if target["state"] == "done":
                fs = Recipe.new("qa-face", [FaceSwap(face_slot="face")],
                                slots=(Slot(name="face", kind="face_image"),),
                                source_image=FileRef(ref=f"gallery/{target['images'][0]}"),
                                seed=FixedSeed(value=cycle))  # fmt: skip
                log("face", r.job(fs, {"face": {"ref": face_ref}}))
            up = Recipe.new("qa-up", [Upscale(chain="model", width=2560, height=1440, scale=None)],
                            source_image=src, seed=FixedSeed(value=cycle))  # fmt: skip
            log("upscale", r.job(up))
            log("model-switch", r.job(gen(prompts[(cycle + 3) % 10], "16:9-1920x1080",
                                          9000 + cycle, model="juggernautxl9")))  # fmt: skip
            cycle += 1
        res["cycles"] = cycle
        res["steps"] = steps
        res["memory"] = mem
        res["failed"] = [s for s in steps if s["state"] != "done"]


def thermal(minutes: float = 10.0) -> None:
    prompts = list(PHOTO.values())
    with stage("thermal") as res, Run(OUT / "studio-thermal") as r:
        times = []
        t0 = time.monotonic()
        i = 0
        while time.monotonic() - t0 < minutes * 60:
            job = r.job(gen(prompts[i % 10], "16:9-1920x1080", 6000 + i))
            times.append((round(time.monotonic() - t0, 1), job["seconds"], job["state"]))
            i += 1
        res["runs"] = times


if __name__ == "__main__":
    {"presets": presets, "soak": soak, "mixed": mixed, "thermal": thermal}[sys.argv[1]]()
