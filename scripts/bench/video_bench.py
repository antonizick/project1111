"""Phase 13 video face-swap measurement and acceptance on the laptop (tasks 4 and 7).

Stage ``material`` makes the synthetic material with the pinned engine: one portrait (the clip's
subject) and one face photo (the swap source), then a **30 s 1920x1080 30 fps** clip with a slow
zoom over the portrait and a sine audio track, plus a short 640x480 clip for the resume/cancel
acceptance. Stage ``fast`` and ``good`` run the 30 s clip through the Studio's video API at both
quality presets with ``Monitor`` sampling the GPU (wall time, per-frame time, peak temperature,
thermal pauses). Stage ``resume`` is the acceptance on the real service: it starts ``p11 serve``,
kills it mid-job with SIGKILL, restarts it, resumes from the last finished frame, and checks that
a user cancel deletes the scratch frames. Everything lands in ``~/.cache/p11/bench/video/`` (not
in git); the numbers go to ``docs/P11_BENCHMARKS.md``.

    uv run python scripts/bench/video_bench.py material
    uv run python scripts/bench/video_bench.py fast
    uv run python scripts/bench/video_bench.py good
    uv run python scripts/bench/video_bench.py resume
    uv run python scripts/bench/video_bench.py smooth

The quality runs go through the Studio API in-process (real face models, GPU lock R24, power
profile H8: the video job is CPU work, but the thermal curve is part of the measurement). The
``resume`` stage spawns the real service and speaks HTTP to it (the token comes from the runtime
dir, ``0600``).
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
from p11.models.registry import ModelManager
from scripts.bench.gpumon import Monitor
from scripts.bench.power import performance

DATA = Path.home() / ".local/share/p11"
OUT = Path.home() / ".cache/p11/bench/video"
PORTRAIT_PROMPT = "portrait of a smiling woman with curly hair in a beige sweater, studio photo"
FACE_PROMPT = "portrait of a bald man with a beard wearing a dark jacket, studio photo"


def _model(mid: str) -> Path:
    manager = ModelManager(DATA / "models")
    entry = manager.manifest.get(mid)
    if entry is None:
        raise SystemExit(f"model {mid} is not in the manifest")
    path = manager.path_of(entry)
    if not path.is_file():
        raise SystemExit(f"model {mid} is not installed (p11 models install face)")
    return path


def studio_client(tmp: Path) -> TestClient:
    settings = load_settings(models_root=DATA / "models", outputs_root=tmp / "pictures")
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=3600))
    app = create_app(
        web_dir=tmp / "no-web",
        engine=engine,
        settings=settings,
        session=Session(),
        port=8314,
        studio_paths=StudioPaths.sandbox(tmp),
        sampler=None,
    )
    c = TestClient(app, base_url="http://127.0.0.1:8314")
    c.token_headers = {"authorization": f"Bearer {app.state.studio.session.token}"}  # type: ignore[attr-defined]
    return c


def generate(c: TestClient, prompt: str, seed: int) -> Image.Image:
    from tests.helpers import recipe

    from p11.recipe.model import FixedSeed
    from p11.recipe.model import Generate as Gen

    r = recipe(
        Gen(prompt=prompt, aspect="1:1-1024", batch_size=1),
        seed=FixedSeed(value=seed),
        id=f"g-{seed}",
    ).model_dump(mode="json")
    res = c.post("/api/jobs", json={"recipe": r}, headers=c.token_headers)  # type: ignore[attr-defined]
    assert res.status_code == 201, res.text
    job = wait_job(c, res.json()["id"])
    assert job["state"] == "done", job.get("error") or job
    img = c.get(f"/api/images/{job['images'][0]}", headers=c.token_headers)  # type: ignore[attr-defined]
    return Image.open(io.BytesIO(img.content))


def wait_job(c: TestClient, job_id: str, timeout: float = 3600) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = c.get(f"/api/jobs/{job_id}", headers=c.token_headers).json()  # type: ignore[attr-defined]
        if job["state"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(1.0)
    raise AssertionError(f"job {job_id} did not finish")


def make_clip(
    portrait: Path, dest: Path, *, seconds: float, fps: int, size: tuple[int, int]
) -> Path:
    frames = int(seconds * fps)
    w, h = size
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"zoompan=z='min(zoom+0.0006,1.15)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={w}x{h}:fps={fps}"
    )
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", str(portrait),
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-t", f"{seconds}", "-vf", vf, "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dest)]  # fmt: skip
    subprocess.run(args, check=True, capture_output=True)
    return dest


def record(name: str, **values: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "measurements.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append({"at": time.strftime("%Y-%m-%d %H:%M %Z"), "run": name, **values})
    path.write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows[-1], indent=2))


# -- stages ------------------------------------------------------------------------------------


def stage_material() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    c = studio_client(OUT / "studio")
    with c, performance():
        portrait = generate(c, PORTRAIT_PROMPT, 71)
        face = generate(c, FACE_PROMPT, 72)
        portrait.save(OUT / "portrait.png")
        face.save(OUT / "face.png")
    make_clip(OUT / "portrait.png", OUT / "clip-1080p-30s.mp4", seconds=30, fps=30,
              size=(1920, 1080))  # fmt: skip
    make_clip(OUT / "portrait.png", OUT / "clip-short.mp4", seconds=4, fps=10, size=(640, 480))
    for name in ("portrait.png", "face.png", "clip-1080p-30s.mp4", "clip-short.mp4"):
        p = OUT / name
        print(f"{name}: {p.stat().st_size / 1e6:.1f} MB")


def stage_quality(quality: str) -> None:
    clip = OUT / "clip-1080p-30s.mp4"
    face = OUT / "face.png"
    if not clip.is_file() or not face.is_file():
        raise SystemExit("run the material stage first")
    c = studio_client(OUT / "studio")
    with c, performance() as profile:
        vid = c.post("/api/uploads?kind=video", content=clip.read_bytes(),
                     headers=c.token_headers).json()["id"]  # type: ignore[attr-defined]
        face_id = c.post("/api/uploads?kind=image", content=face.read_bytes(),
                         headers=c.token_headers).json()["id"]  # type: ignore[attr-defined]
        with Monitor() as mon:
            t0 = time.perf_counter()
            res = c.post("/api/video/jobs", headers=c.token_headers,  # type: ignore[attr-defined]
                         json={"video": vid, "face": face_id, "quality": quality,
                               "confirm_limits": True})  # fmt: skip
            assert res.status_code == 201, res.text
            # Good at 1080p is ~7 s a frame (900 frames ≈ 1 h 45 min); 3600 s cut the first run.
            job = wait_job(c, res.json()["id"], timeout=4 * 3600)
            total_s = time.perf_counter() - t0
        assert job["state"] == "done", job.get("error") or job
        detail = c.get(f"/api/video/jobs/{job['id']}", headers=c.token_headers).json()  # type: ignore[attr-defined]
    temps = [s["temp_c"] for _, s in mon.samples if s["temp_c"] == s["temp_c"]]
    frames = detail["frames"]
    out_file = OUT / f"result-1080p-30s-{quality}.mp4"
    out_file.write_bytes(_http_get_detail(c, detail["file"]))
    record(
        f"1080p-30s-{quality}",
        quality=quality,
        frames=frames,
        pass_through=detail["pass_through"],
        total_s=round(total_s, 1),
        per_frame_s=round(total_s / max(1, frames), 2),
        peak_temp_c=max(temps) if temps else None,
        min_temp_c=min(temps) if temps else None,
        timings=detail["timings"],
        power_profile=profile,
    )


def _frame_jitter(frames: Path) -> float:
    """Mean absolute difference between consecutive frames (0-255), the flicker proxy."""
    import numpy as np

    paths = sorted(frames.glob("frame_*.png"))
    prev: Any = None
    diffs: list[float] = []
    for p in paths:
        cur = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
        if prev is not None:
            diffs.append(float(np.abs(cur - prev).mean()))
        prev = cur
    return sum(diffs) / max(1, len(diffs))


def stage_smooth() -> None:
    """Task 5: the short clip at Fast with and without temporal smoothing, flicker compared.

    The clip is a slow zoom over a still portrait, so the source frames barely change; whatever
    the swapped frames add on top of the source's own frame-to-frame difference is swap flicker.
    """
    clip = OUT / "clip-short.mp4"
    face = OUT / "face.png"
    if not clip.is_file() or not face.is_file():
        raise SystemExit("run the material stage first")
    tmp = OUT / "smooth"
    c = studio_client(tmp)
    results: dict[str, Any] = {}
    with c:
        vid = c.post("/api/uploads?kind=video", content=clip.read_bytes(),
                     headers=c.token_headers).json()["id"]  # type: ignore[attr-defined]
        face_id = c.post("/api/uploads?kind=image", content=face.read_bytes(),
                         headers=c.token_headers).json()["id"]  # type: ignore[attr-defined]
        for smooth in (False, True):
            t0 = time.perf_counter()
            res = c.post("/api/video/jobs", headers=c.token_headers,  # type: ignore[attr-defined]
                         json={"video": vid, "face": face_id, "quality": "fast",
                               "smooth": smooth, "keep_frames": True})  # fmt: skip
            assert res.status_code == 201, res.text
            job = wait_job(c, res.json()["id"])
            assert job["state"] == "done", job.get("error") or job
            scratch = tmp / "jobs" / job["id"]
            results["source"] = round(_frame_jitter(scratch / "frames"), 3)
            results["smooth" if smooth else "plain"] = round(_frame_jitter(scratch / "swapped"), 3)
            results[f"{'smooth' if smooth else 'plain'}_s"] = round(time.perf_counter() - t0, 1)
    record("temporal-smoothing", clip="640x480 4 s 10 fps", metric="mean |frame - prev|", **results)


def _http_get_detail(c: TestClient, file_url: str) -> bytes:
    res = c.get(file_url, headers=c.token_headers)  # type: ignore[attr-defined]
    assert res.status_code == 200
    return res.content


# -- the acceptance on the real service (kill, resume, cancel) ----------------------------------


def _serve(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["uv", "run", "p11", "serve"],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Its own process group: `uv run` forks `p11 serve`, and a kill must reach both.
        start_new_session=True,
    )


def _kill(proc: subprocess.Popen[str], sig: signal.Signals) -> None:
    """Signal the whole service process group (uv and the `p11 serve` it started)."""
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        return


def _http(env: dict[str, str], method: str, path: str, body: Any = None,
          raw: bytes | None = None) -> Any:  # fmt: skip
    token = (Path(env["P11_RUNTIME_DIR"]) / "studio.token").read_text().strip()
    url = f"http://127.0.0.1:{env['P11_STUDIO_PORT']}{path}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("authorization", f"Bearer {token}")
    if raw is None and body is not None:
        req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def _wait_service(env: dict[str, str], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _http(env, "GET", "/api/session")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise AssertionError("the service did not start")


def _wait_video(env: dict[str, str], job_id: str, timeout: float = 1800) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = _http(env, "GET", f"/api/video/jobs/{job_id}")
        if d["state"] in ("done", "failed", "cancelled"):
            return d
        time.sleep(1.0)
    raise AssertionError(f"video job {job_id} did not finish")


def stage_resume() -> None:
    clip = OUT / "clip-short.mp4"
    face = OUT / "face.png"
    if not clip.is_file():
        raise SystemExit("run the material stage first")
    root = OUT / "serve"
    env = {
        **os.environ,
        "P11_CONFIG_DIR": str(root / "config"),
        "P11_DATA_DIR": str(root / "data"),
        "P11_CACHE_DIR": str(root / "cache"),
        "P11_RUNTIME_DIR": str(root / "run"),
        "P11_PICTURES_DIR": str(root / "pictures"),
        "P11_MODELS_ROOT": str(DATA / "models"),
        "P11_STUDIO_PORT": "18314",
    }
    for sub in ("config", "data", "cache", "run", "pictures"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    proc = _serve(env)
    try:
        _wait_service(env)
        vid = _http(env, "POST", "/api/uploads?kind=video", raw=clip.read_bytes())["id"]
        face_id = _http(env, "POST", "/api/uploads?kind=image", raw=face.read_bytes())["id"]
        t0 = time.perf_counter()
        body = {"video": vid, "face": face_id, "quality": "fast", "keep_frames": True}
        job = _http(env, "POST", "/api/video/jobs", body)
        # Wait until a few frames are swapped, then kill the service outright (a crash).
        detail: dict[str, Any] = {}
        while not detail.get("swapped") or detail["swapped"] < 3:
            time.sleep(1)
            detail = _http(env, "GET", f"/api/video/jobs/{job['id']}")
        killed_at = detail["swapped"]
        _kill(proc, signal.SIGKILL)
        proc.wait(timeout=30)
        time.sleep(1)  # let the kernel release the port

        # Restart: the job is marked interrupted, and a Resume continues at the right frame.
        proc = _serve(env)
        _wait_service(env)
        old = _http(env, "GET", f"/api/video/jobs/{job['id']}")
        assert old["state"] == "failed", old
        resumed = _http(env, "POST", f"/api/video/jobs/{job['id']}/resume")
        assert resumed["id"] != job["id"]
        done = _wait_video(env, resumed["id"])
        total_s = time.perf_counter() - t0
        assert done["state"] == "done", done
        assert done["swapped"] == done["frames"], done
        record(
            "kill-resume",
            killed_at_frames=killed_at,
            frames=done["frames"],
            total_s=round(total_s, 1),
            resumed_from=done["record_job"],
        )

        # A user cancel deletes the scratch frames unless "keep frames" is set.
        job2 = _http(env, "POST", "/api/video/jobs",
                     {"video": vid, "face": face_id, "quality": "fast"})  # fmt: skip
        while True:
            time.sleep(1)
            d2 = _http(env, "GET", f"/api/video/jobs/{job2['id']}")
            if d2["swapped"] >= 2 or d2["state"] in ("done", "failed", "cancelled"):
                break
        _http(env, "POST", f"/api/jobs/{job2['id']}/cancel")
        cancelled = _wait_video(env, job2["id"])
        scratch = Path(env["P11_CACHE_DIR"]) / "jobs" / job2["id"] / "frames"
        assert cancelled["state"] == "cancelled", cancelled
        assert not scratch.exists(), f"cancel left the scratch frames at {scratch}"
        record("cancel-cleans-scratch", job=job2["id"], scratch=str(scratch), deleted=True)
    finally:
        _kill(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _kill(proc, signal.SIGKILL)


def stage_resume_quality(quality: str) -> None:
    """Resume an interrupted 30 s 1080p run (the Studio was killed mid-job) to the end.

    Opening the Studio marks the killed job ``failed`` (``job.interrupted``); the resume continues
    in the same scratch at the first unfinished frame. Records the frames done before the kill,
    the resumed part's per-frame time and the finished file's audio.
    """
    from p11.media.ffmpeg import probe

    c = studio_client(OUT / "studio")
    with c, performance() as profile:
        jobs = c.get("/api/video/jobs?limit=50", headers=c.token_headers).json()  # type: ignore[attr-defined]
        todo = [j for j in jobs if j["resumable"]]
        if not todo:
            raise SystemExit("no interrupted video run to resume")
        old = todo[0]
        before = old["swapped"]
        with Monitor() as mon:
            t0 = time.perf_counter()
            res = c.post(f"/api/video/jobs/{old['id']}/resume", headers=c.token_headers)  # type: ignore[attr-defined]
            assert res.status_code == 201, res.text
            job = wait_job(c, res.json()["id"], timeout=4 * 3600)
            total_s = time.perf_counter() - t0
        assert job["state"] == "done", job.get("error") or job
        detail = c.get(f"/api/video/jobs/{job['id']}", headers=c.token_headers).json()  # type: ignore[attr-defined]
        out_file = OUT / f"result-1080p-30s-{quality}.mp4"
        out_file.write_bytes(_http_get_detail(c, detail["file"]))
    made = probe(out_file)
    temps = [s["temp_c"] for _, s in mon.samples if s["temp_c"] == s["temp_c"]]
    resumed = detail["frames"] - before
    record(
        f"1080p-30s-{quality}-resumed",
        quality=quality,
        frames=detail["frames"],
        swapped_before_kill=before,
        resumed_frames=resumed,
        resumed_s=round(total_s, 1),
        per_frame_s=round(total_s / max(1, resumed), 2),
        pass_through=detail["pass_through"],
        peak_temp_c=max(temps) if temps else None,
        out_size=f"{made.width}x{made.height}",
        out_seconds=round(made.seconds, 2),
        out_audio=made.audio.codec if made.audio else None,
        timings=detail["timings"],
        power_profile=profile,
    )


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "material":
        stage_material()
    elif stage in ("fast", "good"):
        stage_quality(stage)
    elif stage == "resume":
        stage_resume()
    elif stage in ("resume-fast", "resume-good"):
        stage_resume_quality(stage.removeprefix("resume-"))
    elif stage == "smooth":
        stage_smooth()
    else:
        raise SystemExit(
            "usage: video_bench.py material|fast|good|resume|resume-fast|resume-good|smooth"
        )


if __name__ == "__main__":
    main()
