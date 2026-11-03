"""Acceptance (Phase 13): the video face-swap pipeline with the real face models and telemetry.

Everything is synthetic (S6, H7): the clip is a slow zoom over a portrait P11 generated itself, so
every frame carries a face the real detector can find, and the audio is a generated sine tone. The
S5 guard runs with the real classifiers on every swapped frame (it must pass a normal portrait);
its refusal path is covered by the stubs in ``tests/unit/test_jobs_video.py``.

Needs the ``face`` set installed (``p11 models install face --accept-licences``). Writes the
measured times to ``~/.cache/p11/video/measurements.json`` for ``docs/P11_BENCHMARKS.md``.
"""

from __future__ import annotations

import io
import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.gpu.telemetry import GpuSample, GpuSampler
from p11.media.faces import FaceKit
from p11.media.ffmpeg import probe, still_frame
from p11.models.registry import ModelManager

pytestmark = pytest.mark.gpu

DATA = Path.home() / ".local/share/p11"
OUT = Path.home() / ".cache/p11/video"
PORTRAIT = "portrait of a smiling woman with curly hair in a beige sweater, studio photo"


def measure(**values: Any) -> None:
    """Append a measurement for the benchmark note."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "measurements.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append({"at": time.strftime("%Y-%m-%d %H:%M %Z"), **values})
    path.write_text(json.dumps(rows, indent=2))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # tests/conftest.py sandboxes P11_DATA_DIR for every test; the real engine and models live in
    # the real one, which is what these acceptance runs measure.
    monkeypatch.setenv("P11_DATA_DIR", str(DATA))
    settings = load_settings(models_root=DATA / "models", outputs_root=tmp_path / "pictures")
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=3600))
    app = create_app(
        web_dir=tmp_path / "no-web",
        engine=engine,
        settings=settings,
        session=Session(),
        port=8312,
        studio_paths=StudioPaths.sandbox(tmp_path),
        sampler=None,
    )
    with TestClient(app, base_url="http://127.0.0.1:8312") as c:
        c.token_headers = {"authorization": f"Bearer {app.state.studio.session.token}"}  # type: ignore[attr-defined]
        yield c


def _model(mid: str) -> Path:
    manager = ModelManager(DATA / "models")
    entry = manager.manifest.get(mid)
    if entry is None:
        pytest.skip(f"model {mid} is not in the manifest")
    path = manager.path_of(entry)
    if not path.is_file():
        pytest.skip(f"model {mid} is not installed (p11 models install face)")
    return path


def generate(client: TestClient, prompt: str, seed: int) -> Image.Image:
    from tests.helpers import recipe

    from p11.recipe.model import FixedSeed
    from p11.recipe.model import Generate as Gen

    r = recipe(
        Gen(prompt=prompt, aspect="1:1-1024", batch_size=1),
        seed=FixedSeed(value=seed),
        id=f"g-{seed}",
    ).model_dump(mode="json")
    res = client.post("/api/jobs", json={"recipe": r}, headers=client.token_headers)  # type: ignore[attr-defined]
    assert res.status_code == 201, res.text
    job = wait(client, res.json()["id"])
    assert job["state"] == "done", job.get("error") or job
    res = client.get(f"/api/images/{job['images'][0]}", headers=client.token_headers)  # type: ignore[attr-defined]
    return Image.open(io.BytesIO(res.content))


def wait(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 1800
    while time.perf_counter() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=client.token_headers).json()  # type: ignore[attr-defined]
        if job["state"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish")


def make_face_clip(portrait: Image.Image, dest: Path, *, seconds: float = 3.0,
                   fps: int = 10, size: int = 320) -> Path:  # fmt: skip
    """A synthetic clip of the portrait with a slow zoom (a face in every frame) and a sine tone."""
    png = dest.with_suffix(".png")
    portrait.save(png)
    frames = int(seconds * fps)
    vf = (
        f"zoompan=z='min(zoom+0.004,1.25)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={size}x{size}:fps={fps}"
    )
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", str(png),
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-t", f"{seconds}", "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(dest)]  # fmt: skip
    subprocess.run(args, check=True, capture_output=True)
    png.unlink()
    return dest


def upload_video(client: TestClient, path: Path) -> str:
    res = client.post(  # type: ignore[attr-defined]
        "/api/uploads?kind=video", content=path.read_bytes(), headers=client.token_headers
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


def upload_image(client: TestClient, im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    res = client.post(  # type: ignore[attr-defined]
        "/api/uploads?kind=image", content=buf.getvalue(), headers=client.token_headers
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


def test_video_face_swap_end_to_end_with_audio(client, tmp_path) -> None:
    portrait = generate(client, PORTRAIT, 51)
    clip = make_face_clip(portrait, tmp_path / "clip.mp4")
    source = generate(client, "portrait of a bald man with a beard, studio photo", 52)

    body = {
        "video": upload_video(client, clip),
        "face": upload_image(client, source),
        "quality": "fast",
    }
    t0 = time.perf_counter()
    res = client.post("/api/video/jobs", json=body, headers=client.token_headers)  # type: ignore[attr-defined]
    assert res.status_code == 201, res.text
    job = wait(client, res.json()["id"])
    total_s = time.perf_counter() - t0
    assert job["state"] == "done", job.get("error") or job

    detail = client.get(  # type: ignore[attr-defined]
        f"/api/video/jobs/{job['id']}", headers=client.token_headers
    ).json()
    assert detail["frames"] == 30 and detail["file"], detail
    res = client.get(detail["file"], headers=client.token_headers)  # type: ignore[attr-defined]
    assert res.status_code == 200 and res.headers["content-type"] == "video/mp4"
    ranged = client.get(detail["file"], headers={**client.token_headers, "range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100

    # The finished file keeps the sound and the clip's size and length.
    out_path = tmp_path / "out.mp4"
    out_path.write_bytes(res.content)
    made = probe(out_path)
    assert made.audio is not None and made.audio.codec == "aac"
    assert made.seconds > 2.7 and (made.width, made.height) == (320, 320)

    # The swap really changed the face area: compare the first frames inside the face's box.
    in_first, out_first = tmp_path / "in-0.png", tmp_path / "out-0.png"
    still_frame(clip, in_first, at=0.0)
    still_frame(out_path, out_first, at=0.0)
    kit = FaceKit(resolve=_model)
    faces = kit.detector().detect(np.asarray(Image.open(in_first).convert("RGB")))
    assert faces, "no face in the synthetic clip"
    box = tuple(int(v) for v in faces[0].box)
    left = Image.open(in_first).convert("L").crop(box)
    right = Image.open(out_first).convert("L").crop(box)
    diff = sum(abs(a - b) for a, b in zip(left.tobytes(), right.tobytes(), strict=False)) / (
        255 * left.width * left.height
    )
    assert diff > 0.02, f"the face did not change (mean abs diff {diff:.4f})"
    measure(
        step="video_face_swap",
        quality="fast",
        frames=detail["frames"],
        seconds=round(total_s, 1),
        per_frame_s=round(total_s / max(1, detail["frames"]), 2),
        size=f"{made.width}x{made.height}",
    )
    assert detail["timings"].get("swap", 0) > 0


class ScriptedGpu:
    """The real NVML sampler with scripted temperatures, so the pause and resume are deterministic.

    The first readings sit above the (deliberately lowered) pause threshold, later ones below the
    resume threshold; VRAM, power and clocks stay real. The pure hysteresis is unit-tested with
    fake telemetry (``tests/unit/test_jobs_video.py``).
    """

    name = "scripted"

    def __init__(self, real: GpuSampler | None, hot: float, cool: float) -> None:
        self.real = real
        self.hot = hot
        self.cool = cool
        self.calls = 0
        self.temps: list[float] = []

    def sample(self) -> GpuSample:
        self.calls += 1
        base = (
            self.real.sample()
            if self.real is not None
            else GpuSample(1000, 8192, 50, 50.0, 1500, 6000, (), 0.0)
        )
        temp = self.hot if self.calls <= 3 else self.cool
        self.temps.append(temp)
        return replace(base, temp_c=int(temp))

    def close(self) -> None:
        if self.real is not None:
            self.real.close()


def test_thermal_pauses_and_resumes_the_video_job(tmp_path, monkeypatch) -> None:
    from p11.gpu.telemetry import default_sampler

    monkeypatch.setenv("P11_DATA_DIR", str(DATA))
    # Lowered thresholds (H9 defaults are 87/80): the job must pause hot and resume cool.
    pause_at, resume_at = 50, 45
    sampler = ScriptedGpu(default_sampler(), hot=pause_at + 3, cool=resume_at - 3)
    settings = load_settings(
        models_root=DATA / "models",
        outputs_root=tmp_path / "pictures",
        thermal_pause_c=pause_at,
        thermal_resume_c=resume_at,
    )
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=3600))
    app = create_app(
        web_dir=tmp_path / "no-web",
        engine=engine,
        settings=settings,
        session=Session(),
        port=8313,
        studio_paths=StudioPaths.sandbox(tmp_path),
        sampler=sampler,
    )
    with TestClient(app, base_url="http://127.0.0.1:8313") as c:
        headers = {"authorization": f"Bearer {app.state.studio.session.token}"}
        c.token_headers = headers  # type: ignore[attr-defined]
        portrait = generate(c, PORTRAIT, 61)
        clip = make_face_clip(portrait, tmp_path / "clip.mp4", seconds=1.0)
        body = {
            "video": upload_video(c, clip),
            "face": upload_image(c, portrait),
            "quality": "fast",
        }
        res = c.post("/api/video/jobs", json=body, headers=headers)
        assert res.status_code == 201, res.text
        job = wait(c, res.json()["id"])
        assert job["state"] == "done", job.get("error") or job
        events = [e.data for e in app.state.studio.bus._replay if e.type == "job"]
        seen = [e["state"] for e in events if e["id"] == job["id"]]
        assert "paused" in seen and seen[-1] == "done", seen
        paused = next(e for e in events if e.get("state") == "paused")
        assert "°C" in (paused.get("note") or "")
        measure(
            step="video_thermal",
            paused=True,
            thresholds=f"{pause_at}/{resume_at}",
            readings=str(sampler.temps[:6]),
        )
