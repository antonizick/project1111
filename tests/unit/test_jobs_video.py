"""The video face-swap job (Phase 13): pure helpers, resume, guard, thermal, cancel, API.

The pipeline runs on synthetic clips (ffmpeg ``testsrc``) with the stub face kit, so no real face,
model or GPU is involved. The S5 guard tests use the stub guard's exact marker pixels, written as
PNG frames (video compression would shift them).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from tests.studio import png_bytes, studio_client

from p11.engine.base import EngineInterrupted
from p11.gpu.telemetry import GpuSample, ThermalGuard
from p11.jobs.queue import ThermalWatch
from p11.jobs.runner import JobControl
from p11.jobs.video import (
    ScratchRecord,
    VideoError,
    VideoJobs,
    VideoSpec,
    sample_indices,
    scene_indices,
    smooth_region,
    thumb_diff,
    tracked_pick,
)
from p11.media.faces import FaceKit, StubSwapper
from p11.media.inputs import InputStore
from p11.media.nsfw import STUB_MARKER, GuardRefused

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


def make_clip(path: Path, *, seconds: float = 1.0, size: str = "160x120",
              rate: int = 10, audio: bool = True) -> Path:  # fmt: skip
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
            f"testsrc=size={size}:rate={rate}:duration={seconds}"]  # fmt: skip
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    subprocess.run([*args, str(path)], check=True, capture_output=True)
    return path


def make_jobs(tmp_path: Path, *, faces: FaceKit | None = None) -> tuple[VideoJobs, InputStore]:
    store = InputStore(tmp_path / "inputs")
    jobs = VideoJobs(
        resolve=lambda ref: store.get(ref).path.read_bytes(),
        inputs=store,
        faces=faces or FaceKit(stub=True),
        outputs_root=tmp_path / "pictures",
        scratch_root=tmp_path / "scratch",
    )
    return jobs, store


def face_photo(store: InputStore) -> str:
    return store.add_image(png_bytes((64, 64), "orange")).id


def run_job(jobs: VideoJobs, spec: VideoSpec, job_id: str = "job1",
            control: JobControl | None = None) -> object:  # fmt: skip
    events: list[tuple[str, dict[str, object]]] = []
    progress: list[float] = []
    report = asyncio.run(
        jobs.run(
            spec=spec,
            job_id=job_id,
            control=control or JobControl(),
            publish=lambda t, d: events.append((t, d)),
            on_progress=lambda p, note: progress.append(p),
        )
    )
    run_job.last_events = events  # type: ignore[attr-defined]
    return report


# -- pure helpers -----------------------------------------------------------------------------


def test_sample_indices_are_about_one_per_second():
    assert sample_indices(0, 30.0) == []
    assert sample_indices(10, 10.0) == [0, 9]
    assert sample_indices(31, 30.0) == [0, 30]
    assert sample_indices(100, 25.0) == [0, 25, 50, 75, 99]


def test_tracked_pick_auto_click_and_tracking():
    a, b = (0.0, 0.0, 10.0, 10.0), (20.0, 20.0, 30.0, 30.0)
    assert tracked_pick([a, b], None, auto=True, chosen=None) == 0
    assert tracked_pick([a, b], None, auto=False, chosen=1) == 1
    assert tracked_pick([a, b], (21.0, 21.0, 29.0, 29.0), auto=False, chosen=0) == 1
    assert tracked_pick([a], (200.0, 200.0, 210.0, 210.0), auto=False, chosen=0) is None
    assert tracked_pick([], (0.0, 0.0, 1.0, 1.0), auto=True, chosen=None) is None


def test_thumb_diff_and_scene_cuts(tmp_path):
    white = png_bytes((64, 48), "white")
    black = png_bytes((64, 48), "black")
    assert thumb_diff(white, white) == 0.0
    assert thumb_diff(white, black) > 100.0
    frames = []
    for i, colour in enumerate(["white", "white", "black", "black"]):
        p = tmp_path / f"f{i}.png"
        p.write_bytes(png_bytes((64, 48), colour))
        frames.append(p)
    assert scene_indices(frames) == [2]


def test_smooth_region_blends_only_the_face_box():
    prev = png_bytes((100, 100), "white")
    cur = png_bytes((100, 100), "black")
    box = (30.0, 30.0, 70.0, 70.0)
    out = smooth_region(prev, cur, box, box)
    with Image.open(__import__("io").BytesIO(out)) as img:
        assert img.getpixel((50, 50)) != img.getpixel((5, 5))  # blended in the box only
        assert img.getpixel((5, 5)) == (0, 0, 0)
    # boxes that do not overlap leave the frame alone
    far = smooth_region(prev, cur, (0.0, 0.0, 5.0, 5.0), (90.0, 90.0, 95.0, 95.0))
    assert far == cur


def test_spec_hash_ignores_resume_and_cleanup_flags():
    base = VideoSpec(video="vid-1", face="img-1")
    same = VideoSpec(video="vid-1", face="img-1", confirm_limits=True, keep_frames=True,
                     resume_of="job1")  # fmt: skip
    assert base.render_hash() == same.render_hash()
    assert (
        base.render_hash() != VideoSpec(video="vid-1", face="img-1", quality="fast").render_hash()
    )
    assert base.render_hash() != VideoSpec(video="vid-1", face="img-1", smooth=True).render_hash()


def test_scratch_record_round_trips():
    record = ScratchRecord(job_id="job1", spec_hash="abc", stage="swapped", frames=10,
                           swapped=4, tracked_box=(1.0, 2.0, 3.0, 4.0),
                           timings={"extract": 1.5})  # fmt: skip
    back = ScratchRecord.from_json(json.loads(json.dumps(record.as_json())))
    assert back == record


# -- the pipeline on synthetic clips ----------------------------------------------------------


@needs_ffmpeg
def test_full_run_produces_an_mp4_with_audio_and_cleans_scratch(tmp_path):
    jobs, store = make_jobs(tmp_path)
    clip = make_clip(tmp_path / "clip.mp4")
    spec = VideoSpec(video=store.add_video(clip).id, face=face_photo(store), quality="fast")
    report = run_job(jobs, spec)  # type: ignore[assignment]
    assert report.frames == 10 and report.seconds == pytest.approx(1.0, abs=0.2)
    assert report.output.is_file() and report.output.suffix == ".mp4"
    assert report.output.stat().st_mode & 0o777 == 0o600
    from p11.media.ffmpeg import probe

    out = probe(report.output)
    assert out.audio is not None and out.audio.codec == "aac" and out.seconds > 0.8
    sidecar = report.output.with_suffix(".json")
    record = json.loads(sidecar.read_text())
    assert record["frames"] == 10 and record["kind"] == "video-face-swap"
    assert record["audio_codec"] == "aac" and record["timings"]["swap"] > 0
    # scratch frames are deleted on success; the small record stays (for the result lookup)
    assert not (tmp_path / "scratch" / "job1" / "frames").exists()
    saved = jobs.record("job1")
    assert saved is not None and saved.stage == "stitched" and saved.output == str(report.output)
    events = run_job.last_events  # type: ignore[attr-defined]
    titles = [d.get("title") for t, d in events if t == "progress"]
    assert "Checking the clip" in titles and "Swapping faces" in titles


@needs_ffmpeg
def test_keep_frames_and_trim(tmp_path):
    jobs, store = make_jobs(tmp_path)
    clip = make_clip(tmp_path / "clip.mp4", seconds=2.0)
    spec = VideoSpec(video=store.add_video(clip).id, face=face_photo(store), quality="fast",
                     trim_start=0.5, trim_end=1.5, keep_frames=True)  # fmt: skip
    report = run_job(jobs, spec)  # type: ignore[assignment]
    assert report.frames == 10  # 1 s of a 10 fps clip
    assert (tmp_path / "scratch" / "job1" / "frames").is_dir()


class FlakySwapper(StubSwapper):
    """Stub swapper that stops the job after N frames, like a killed Studio."""

    def __init__(self, fail_after: int, control: JobControl | None = None) -> None:
        self.calls = 0
        self.fail_after = fail_after
        self.control = control

    def swap(self, rgb, face, embedding, amount):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls > self.fail_after:
            if self.control is not None:
                self.control.cancel(purge=True)
            raise EngineInterrupted("stopped")
        return super().swap(rgb, face, embedding, amount)


@needs_ffmpeg
def test_resume_continues_at_the_right_frame_with_no_duplicates(tmp_path):
    kit = FaceKit(stub=True)
    flaky = FlakySwapper(fail_after=5)
    kit._cache["swap"] = flaky
    jobs, store = make_jobs(tmp_path, faces=kit)
    clip = make_clip(tmp_path / "clip.mp4")
    spec = VideoSpec(video=store.add_video(clip).id, face=face_photo(store), quality="fast")
    with pytest.raises(EngineInterrupted):
        run_job(jobs, spec, "job1")
    assert flaky.calls == 6  # five frames swapped, the sixth stopped the job
    assert jobs.record("job1").swapped == 5
    done = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (tmp_path / "scratch" / "job1" / "swapped").glob("*.png")}  # fmt: skip
    assert len(done) == 5 and jobs.resumable("job1")

    class CountingSwapper(StubSwapper):
        calls = 0

        def swap(self, rgb, face, embedding, amount):  # type: ignore[no-untyped-def]
            self.calls += 1
            return super().swap(rgb, face, embedding, amount)

    counting = CountingSwapper()
    kit._cache["swap"] = counting
    resumed = VideoSpec(**{**spec.as_json(), "resume_of": "job1", "keep_frames": True})
    report = run_job(jobs, resumed, "job2")  # type: ignore[assignment]
    assert report.frames == 10
    assert counting.calls == 5  # only the unfinished frames were swapped again
    swapped_dir = tmp_path / "scratch" / "job1" / "swapped"
    files = sorted(swapped_dir.glob("*.png"))
    assert len(files) == 10  # every frame exactly once, none missing
    for name, digest in done.items():
        assert hashlib.sha256((swapped_dir / name).read_bytes()).hexdigest() == digest
    assert not jobs.resumable("job1")


@needs_ffmpeg
def test_user_cancel_deletes_scratch_unless_keep_frames(tmp_path):
    kit = FaceKit(stub=True)
    control = JobControl()
    kit._cache["swap"] = FlakySwapper(fail_after=2, control=control)
    jobs, store = make_jobs(tmp_path, faces=kit)
    clip = make_clip(tmp_path / "clip.mp4")
    spec = VideoSpec(video=store.add_video(clip).id, face=face_photo(store), quality="fast")
    with pytest.raises(EngineInterrupted):
        run_job(jobs, spec, "job1", control)
    assert control.purge
    assert not (tmp_path / "scratch" / "job1" / "frames").exists()
    assert jobs.record("job1") is not None and not jobs.resumable("job1")

    kept = VideoSpec(**{**spec.as_json(), "keep_frames": True})
    kit2 = FaceKit(stub=True)
    control2 = JobControl()
    kit2._cache["swap"] = FlakySwapper(fail_after=2, control=control2)
    jobs2, _ = make_jobs(tmp_path, faces=kit2)
    with pytest.raises(EngineInterrupted):
        run_job(jobs2, kept, "job3", control2)
    assert (tmp_path / "scratch" / "job3" / "frames").is_dir()


def _magenta_frame(tmp_path: Path, name: str) -> Path:
    img = Image.new("RGB", (64, 48), "gray")
    for x, y in ((0, 0), (63, 0), (0, 47), (63, 47)):
        img.putpixel((x, y), STUB_MARKER)
    path = tmp_path / name
    img.save(path, format="PNG")
    return path


@needs_ffmpeg
def test_guard_pre_pass_refuses_the_clip_before_any_swapping(tmp_path):
    jobs, _ = make_jobs(tmp_path)
    frames_dir = tmp_path / "scratch" / "job1" / "frames"
    frames_dir.mkdir(parents=True)
    for i in range(3):
        _magenta_frame(frames_dir, f"frame_{i + 1:06d}.png")
    record = ScratchRecord(job_id="job1", spec_hash="x", stage="extracted", frames=3, fps=10.0)
    spec = VideoSpec(video="vid-0", face="img-0")

    async def go() -> None:
        await jobs._guard_pass(spec, record, JobControl(), lambda t, d: None, lambda p, n: None)

    with pytest.raises(GuardRefused):
        asyncio.run(go())
    assert jobs.record("job1") is None or not jobs.record("job1").guarded


@needs_ffmpeg
def test_guard_refusal_during_the_run_clears_the_scratch(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    jobs, store = make_jobs(tmp_path)
    clip = make_clip(tmp_path / "clip.mp4")
    spec = VideoSpec(video=store.add_video(clip).id, face=face_photo(store), quality="fast")
    monkeypatch.setattr(
        "p11.jobs.video.check_target",
        lambda guard, image: (_ for _ in ()).throw(GuardRefused("refused")),
    )
    with pytest.raises(GuardRefused):
        run_job(jobs, spec, "job1")
    assert not (tmp_path / "scratch" / "job1" / "frames").exists()


class TempSampler:
    name = "fake"

    def __init__(self, temps: list[float]) -> None:
        self.temps = temps

    def sample(self) -> GpuSample:
        t = self.temps.pop(0) if len(self.temps) > 1 else self.temps[0]
        return GpuSample(1000, 8192, int(t), 50.0, 1500, 6000, (), 0.0)

    def close(self) -> None:
        pass


@needs_ffmpeg
def test_video_job_pauses_when_hot_and_resumes(tmp_path):
    jobs, store = make_jobs(tmp_path)
    clip = make_clip(tmp_path / "clip.mp4")
    spec = VideoSpec(video=store.add_video(clip).id, face=face_photo(store), quality="fast")
    watch = ThermalWatch(TempSampler([90, 88, 79, 70]), ThermalGuard(87, 80), poll=0.01)
    paused: list[float] = []
    resumed: list[bool] = []
    control = JobControl(lambda ctl: watch.wait(ctl, paused.append, lambda: resumed.append(True)))
    report = run_job(jobs, spec, "job1", control)  # type: ignore[assignment]
    assert report.frames == 10
    assert paused and paused[0] >= 87 and resumed == [True]


# -- API --------------------------------------------------------------------------------------


@needs_ffmpeg
def test_video_job_api_submit_progress_result_and_range(tmp_path):
    clip = make_clip(tmp_path / "clip.mp4")
    with studio_client(tmp_path) as c:
        vid = c.post("/api/uploads?kind=video", headers=c.auth,
                     content=clip.read_bytes()).json()["id"]  # fmt: skip
        face = c.post("/api/uploads?kind=image", headers=c.auth,
                      content=png_bytes((64, 64), "orange")).json()["id"]  # fmt: skip
        still = c.post("/api/video/frame", headers=c.auth, json={"ref": vid, "time": 0.0})
        assert still.status_code == 200 and still.headers["content-type"] == "image/png"
        faces = c.post("/api/video/detect", headers=c.auth, json={"ref": vid})
        assert faces.status_code == 200 and len(faces.json()["faces"]) == 1

        job = c.post("/api/video/jobs", headers=c.auth,
                     json={"video": vid, "face": face, "quality": "fast"})  # fmt: skip
        assert job.status_code == 201, job.text
        done = c.wait_job(job.json()["id"])
        assert done["state"] == "done" and done["kind"] == "video", done
        detail = c.get(f"/api/video/jobs/{job.json()['id']}", headers=c.auth).json()
        assert detail["frames"] == 10 and detail["file"] and not detail["resumable"]
        listing = c.get("/api/video/jobs", headers=c.auth).json()
        assert [j["id"] for j in listing] == [job.json()["id"]]
        full = c.get(detail["file"], headers=c.auth)
        assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
        ranged = c.get(detail["file"], headers={**c.auth, "range": "bytes=0-99"})
        assert ranged.status_code == 206 and len(ranged.content) == 100
        assert ranged.headers["content-range"].startswith("bytes 0-99/")
        saved = c.get(f"{detail['file']}?download=1", headers=c.auth)
        assert saved.headers["content-disposition"].startswith("attachment")


@needs_ffmpeg
def test_limits_need_confirmation_and_resume_refuses_finished_jobs(tmp_path):
    clip = make_clip(tmp_path / "clip.mp4")
    with studio_client(tmp_path, video_warn_seconds=0.5) as c:
        vid = c.post("/api/uploads?kind=video", headers=c.auth,
                     content=clip.read_bytes()).json()["id"]  # fmt: skip
        face = c.post("/api/uploads?kind=image", headers=c.auth,
                      content=png_bytes((64, 64), "orange")).json()["id"]  # fmt: skip
        body = {"video": vid, "face": face, "quality": "fast"}
        refused = c.post("/api/video/jobs", headers=c.auth, json=body)
        assert refused.status_code == 422
        assert refused.json()["code"] == "video.invalid"
        assert "limits" in refused.json()["message"]
        job = c.post("/api/video/jobs", headers=c.auth, json={**body, "confirm_limits": True})
        assert job.status_code == 201, job.text
        done = c.wait_job(job.json()["id"])
        assert done["state"] == "done"
        resume = c.post(f"/api/video/jobs/{job.json()['id']}/resume", headers=c.auth)
        assert resume.status_code == 422
        assert "nothing left to resume" in resume.json()["message"]


def test_video_error_maps_to_a_plain_english_problem():
    from p11.jobs.errors import problem_for

    status, err = problem_for(VideoError("The trim is empty."))
    assert status == 422 and err.code == "video.invalid" and err.hint
