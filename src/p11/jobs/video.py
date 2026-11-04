"""The video face-swap job (Phase 13, spec R13, R14, S5): probe → extract → guard → swap → stitch.

Per-frame swaps run through ``p11.media.faces.run_face_swap`` (ADR-0028), so the S5 guard runs on
**every** swapped frame's target and result (ADR-0029, no switch); a sampled pre-pass (about one
frame per second plus scene changes) refuses the whole clip before any swapping, so a bad clip
fails in seconds instead of after an hour of CPU work. Frames are swapped on the CPU: the job uses
no GPU and holds no GPU lock, but it still checkpoints the thermal guard between batches (R14) and
the Studio's single job queue keeps it from overlapping a GPU job (R24).

**Resume.** Progress is persisted after every frame in ``<scratch>/<job>.json`` while the frames
live in ``<scratch>/<job>/``: a killed Studio leaves both behind and a Resume run continues at the
first unfinished frame (the spec's hash is checked, so a resume can never mix two settings). A user
cancel deletes the scratch frames unless "keep frames" is set; a crash never does. On success the
frame directories are deleted and the small record stays with the output path and timings.

Target selection is either the largest face in every frame (``target_face=None``) or a face clicked
on the first frame, followed across frames by box overlap (the IoU tracker); a frame where the
tracked face is not found passes through unchanged rather than swapping the wrong face.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from p11 import __version__
from p11.engine.base import EngineInterrupted
from p11.media import ffmpeg
from p11.media.faces import FaceError, FaceKitProtocol, detect_faces, run_face_swap
from p11.media.imageio import ImageError, open_rgb
from p11.media.inputs import InputStore, UnknownInput
from p11.media.nsfw import GuardRefused, check_target
from p11.outputs.layout import output_path

from .runner import JobControl, Publish

log = logging.getLogger("p11.jobs")

#: Frames swapped between two cancel/thermal checkpoints (R14).
BATCH = 4
#: The pre-pass guard samples one frame per second (at least one frame per ``BATCH_GUARD`` chunk).
MIN_SAMPLE_FPS = 1
#: Mean thumbnail difference (0..255) that counts as a scene change for the pre-pass guard.
SCENE_DIFF = 24.0
#: Minimum box overlap for the tracker to keep following the same face.
TRACK_IOU = 0.2
#: Temporal smoothing blends a face region with the previous output when motion is this low.
SMOOTH_IOU = 0.6
SMOOTH_ALPHA = 0.35

# Stage weights for the 0..1 progress bar (swap dominates: it is seconds per frame on the CPU).
W_EXTRACT, W_GUARD, W_SWAP, W_STITCH = 0.05, 0.10, 0.80, 0.05

#: Quality presets (task 6): Fast skips face restore and caps the frames at 720p.
QUALITY: dict[str, dict[str, Any]] = {
    "fast": {"restore": False, "max_height": 720, "crf": 23},
    "good": {"restore": True, "max_height": None, "crf": 18},
}

OVER_LIMITS = (
    "This clip is over the recommended limits (60 s, 1080p): face-swapping it can take hours. "
    "Trim it or pick Fast, then confirm."
)
RESUME_MISMATCH = (
    "This job cannot be resumed: its settings do not match the interrupted run. Start a new swap."
)
RESUME_GONE = "There is nothing left to resume: the interrupted run's frames are gone."
NO_FACE_PHOTO = "The face photo is gone. Choose it again."

Quality = Literal["fast", "good"]
Stage = Literal["new", "extracted", "guarded", "swapped", "stitched"]


class VideoError(ValueError):
    """The video job cannot run as asked; the message says what to do."""


class _PassThrough(Exception):
    """Internal: this frame keeps its original pixels."""


@dataclass(frozen=True)
class VideoSpec:
    """What one video face-swap run does (persisted in the job row, hashed for resume)."""

    video: str
    face: str
    quality: Quality = "good"
    source_face_index: int = 0
    #: Face index on the first frame (from the picker); ``None`` = largest face in every frame.
    target_face: int | None = None
    trim_start: float = 0.0
    trim_end: float | None = None
    max_height: int | None = None
    smooth: bool = False
    keep_frames: bool = False
    confirm_limits: bool = False
    #: Job whose interrupted run this one continues.
    resume_of: str | None = None

    def as_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> VideoSpec:
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def render_hash(self) -> str:
        """Identity of everything that shapes the output (a resume refuses a mismatch)."""
        keys = ("video", "face", "quality", "source_face_index", "target_face", "trim_start",
                "trim_end", "max_height", "smooth")  # fmt: skip
        blob = json.dumps({k: getattr(self, k) for k in keys}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def restore(self) -> bool:
        return bool(QUALITY[self.quality]["restore"])

    @property
    def crf(self) -> int:
        return int(QUALITY[self.quality]["crf"])

    @property
    def frame_height(self) -> int | None:
        """Frame height cap: the user's choice, else the quality preset's."""
        return (
            self.max_height if self.max_height is not None else QUALITY[self.quality]["max_height"]
        )


@dataclass
class ScratchRecord:
    """``<scratch>/<job>.json``: per-frame progress and the result (kept after cleanup)."""

    job_id: str
    spec_hash: str
    stage: Stage = "new"
    frames: int = 0
    fps: float = 0.0
    seconds: float = 0.0
    width: int = 0
    height: int = 0
    swapped: int = 0
    pass_through: int = 0
    guarded: bool = False
    tracked_box: tuple[float, float, float, float] | None = None
    #: Whether the last written frame was swapped (smoothing must not blend a pass-through).
    prev_swapped: bool = False
    output: str | None = None
    timings: dict[str, float] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["tracked_box"] = list(self.tracked_box) if self.tracked_box else None
        return data

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> ScratchRecord:
        box = raw.get("tracked_box")
        return cls(
            job_id=str(raw["job_id"]),
            spec_hash=str(raw["spec_hash"]),
            stage=raw.get("stage", "new"),
            frames=int(raw.get("frames", 0)),
            fps=float(raw.get("fps", 0.0)),
            seconds=float(raw.get("seconds", 0.0)),
            width=int(raw.get("width", 0)),
            height=int(raw.get("height", 0)),
            swapped=int(raw.get("swapped", 0)),
            pass_through=int(raw.get("pass_through", 0)),
            guarded=bool(raw.get("guarded", False)),
            tracked_box=(float(box[0]), float(box[1]), float(box[2]), float(box[3]))
            if box
            else None,
            prev_swapped=bool(raw.get("prev_swapped", False)),
            output=raw.get("output"),
            timings={str(k): float(v) for k, v in (raw.get("timings") or {}).items()},
        )


@dataclass(frozen=True)
class VideoReport:
    output: Path
    frames: int
    pass_through: int
    seconds: float
    timings: dict[str, float]


# ---------------------------------------------------------------------------------------------
# Pure helpers


def sample_indices(frames: int, fps: float) -> list[int]:
    """Frame indices the pre-pass guard always checks: about one per second, evenly spread."""
    if frames <= 0:
        return []
    step = max(MIN_SAMPLE_FPS, round(fps))
    return sorted({min(i, frames - 1) for i in range(0, frames, step)} | {frames - 1})


def thumb_diff(a: bytes, b: bytes) -> float:
    """Mean absolute difference of two frame images' 32x32 greyscale thumbnails (0..255)."""
    from PIL import Image

    def thumb(data: bytes) -> bytes:
        img = open_rgb(data).resize((32, 32), Image.Resampling.BILINEAR)
        return img.convert("L").tobytes()

    ta, tb = thumb(a), thumb(b)
    return sum(abs(x - y) for x, y in zip(ta, tb, strict=True)) / len(ta)


def scene_indices(frames: list[Path], threshold: float = SCENE_DIFF) -> list[int]:
    """Indices of hard cuts (the frame after the jump) in an extracted sequence."""
    out: list[int] = []
    prev: bytes | None = None
    for i, path in enumerate(frames):
        data = path.read_bytes()
        if prev is not None and thumb_diff(prev, data) >= threshold:
            out.append(i)
        prev = data
    return out


def tracked_pick(
    boxes: list[tuple[float, float, float, float]],
    previous: tuple[float, float, float, float] | None,
    *,
    auto: bool,
    chosen: int | None,
) -> int | None:
    """Which face to swap this frame: the largest (auto), the clicked index (first frame or a
    lost track), or the best box overlap with the previous target. ``None`` = pass through."""
    if not boxes:
        return None
    if auto:
        return 0
    if previous is None:
        return min(max(int(chosen or 0), 0), len(boxes) - 1)
    scores = [_iou(previous, b) for b in boxes]
    best = max(range(len(boxes)), key=lambda i: scores[i])
    return best if scores[best] >= TRACK_IOU else None


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def smooth_region(prev: bytes, cur: bytes, prev_box: tuple[float, float, float, float],
                  cur_box: tuple[float, float, float, float]) -> bytes:  # fmt: skip
    """Blend the current frame's face region with the previous output where motion is low.

    The region is the two boxes' intersection grown by 20 %; everything outside it is untouched.
    """
    from PIL import Image

    prev_img, cur_img = open_rgb(prev), open_rgb(cur)
    x1 = max(prev_box[0], cur_box[0])
    y1 = max(prev_box[1], cur_box[1])
    x2 = min(prev_box[2], cur_box[2])
    y2 = min(prev_box[3], cur_box[3])
    if x2 <= x1 or y2 <= y1:
        return cur
    px, py = (x2 - x1) * 0.2, (y2 - y1) * 0.2
    box = (
        int(max(0, x1 - px)),
        int(max(0, y1 - py)),
        int(min(cur_img.width, x2 + px)),
        int(min(cur_img.height, y2 + py)),
    )
    mixed = Image.blend(cur_img.crop(box), prev_img.crop(box), SMOOTH_ALPHA)
    out = cur_img.copy()
    out.paste(mixed, box[:2])
    return png_bytes(out)


def png_bytes(img: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    tmp.replace(path)


# ---------------------------------------------------------------------------------------------
# The job


@dataclass
class VideoJobs:
    """Runs video face-swap jobs for the Studio's queue (built in ``api.studio.Studio.open``)."""

    #: Resolves an upload or gallery ref to its bytes (the runner's ``resolve_file``).
    resolve: Callable[[str], bytes]
    #: Stored uploads: the pipeline needs the video's path on disk, not its bytes.
    inputs: InputStore
    faces: FaceKitProtocol
    outputs_root: Path
    scratch_root: Path
    #: R13 warn limits (``Settings.video_warn_seconds`` / ``video_warn_height``).
    warn_seconds: float = 60.0
    warn_height: int = 1080
    clock: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())

    # -- paths and record ---------------------------------------------------------------------

    def _dir(self, record_id: str) -> Path:
        return self.scratch_root / record_id

    def _frames_dir(self, record_id: str) -> Path:
        return self._dir(record_id) / "frames"

    def _swapped_dir(self, record_id: str) -> Path:
        return self._dir(record_id) / "swapped"

    def _record_path(self, record_id: str) -> Path:
        return self.scratch_root / f"{record_id}.json"

    def record(self, record_id: str) -> ScratchRecord | None:
        path = self._record_path(record_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        try:
            return ScratchRecord.from_json(raw) if isinstance(raw, dict) else None
        except (KeyError, TypeError, ValueError):
            return None

    def _save_record(self, record: ScratchRecord) -> None:
        path = self._record_path(record.job_id)
        self.scratch_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.scratch_root.chmod(0o700)
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record.as_json(), fh)
        tmp.replace(path)

    def resumable(self, record_id: str) -> bool:
        """An interrupted run whose frames are still on disk can continue."""
        record = self.record(record_id)
        return bool(
            record
            and record.stage != "stitched"
            and record.frames > 0
            and record.swapped < record.frames
            and self._frames_dir(record_id).is_dir()
        )

    def clear(self, record_id: str) -> None:
        """Delete a run's scratch frames (a user cancel or a refused clip); the record stays."""
        shutil.rmtree(self._dir(record_id), ignore_errors=True)

    # -- submit-time checks -------------------------------------------------------------------

    def _video_path(self, spec: VideoSpec) -> Path:
        try:
            stored = self.inputs.get(spec.video)
        except UnknownInput:
            raise VideoError("The video upload is gone. Upload the clip again.") from None
        if stored.kind != "video":
            raise VideoError("That upload is not a video.")
        return stored.path

    def check_limits(self, spec: VideoSpec, clip: ffmpeg.ClipInfo) -> None:
        """R13: over the default limits the caller must confirm (the UI shows the estimate)."""
        over = clip.seconds > self.warn_seconds or min(clip.width, clip.height) > self.warn_height
        if over and not spec.confirm_limits:
            raise VideoError(OVER_LIMITS)

    def resolve_face(self, spec: VideoSpec) -> bytes:
        """The source face photo (an upload or a gallery image)."""
        try:
            return self.resolve(spec.face)
        except (UnknownInput, LookupError, ValueError) as exc:
            raise VideoError(NO_FACE_PHOTO) from exc

    def guard_frame(self, spec: VideoSpec, *, at: float) -> None:
        """S5: one frame of the clip through the guard (fails closed when a model is missing)."""
        tmp = self.scratch_root / f".guard-{os.getpid()}-{uuid.uuid4().hex[:8]}.png"
        try:
            self.scratch_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            ffmpeg.still_frame(self._video_path(spec), tmp, at=at)
            check_target(self.faces.guard(), open_rgb(tmp.read_bytes()))
        except (ImageError, OSError) as exc:
            raise VideoError(f"A frame of the clip could not be read: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)

    def submit_check(self, spec: VideoSpec) -> ffmpeg.ClipInfo:
        """At submit time: the clip is readable and within limits, and its first frame passes the
        S5 guard (the full sampled pre-pass runs in the job). The face photo is checked first, on
        the event-loop thread, because a gallery reference reads the SQLite index (Phase 17g)."""
        clip = ffmpeg.probe(self._video_path(spec))
        self.check_limits(spec, clip)
        if spec.trim_start < 0 or (spec.trim_end is not None and spec.trim_end <= spec.trim_start):
            raise VideoError("The trim is empty. Pick a start before the end.")
        if spec.trim_start >= clip.seconds:
            raise VideoError("The start of the trim is past the end of the clip.")
        self.guard_frame(spec, at=max(0.0, min(spec.trim_start + 0.5, clip.seconds - 0.1)))
        return clip

    # -- the pipeline -------------------------------------------------------------------------

    async def run(
        self,
        *,
        spec: VideoSpec,
        job_id: str,
        control: JobControl,
        publish: Publish,
        on_progress: Callable[[float, str | None], None],
    ) -> VideoReport:
        record_id = spec.resume_of or job_id
        record = ScratchRecord(job_id=record_id, spec_hash=spec.render_hash())
        if spec.resume_of:
            existing = self.record(record_id)
            if existing is None or not self.resumable(record_id):
                raise VideoError(RESUME_GONE)
            if existing.spec_hash != spec.render_hash():
                raise VideoError(RESUME_MISMATCH)
            record = existing
        else:
            self._save_record(record)
        try:
            return await self._run(spec, record, control, publish, on_progress)
        except (EngineInterrupted, asyncio.CancelledError):
            # A user cancel drops the scratch frames (unless "keep frames"); a crash or a
            # shutdown keeps them, which is what makes the run resumable.
            if control.purge and not spec.keep_frames:
                self.clear(record.job_id)
            raise
        except GuardRefused:
            # A refused clip has nothing worth resuming: drop its frames (S6).
            if not spec.keep_frames:
                self.clear(record.job_id)
            raise

    async def _run(
        self,
        spec: VideoSpec,
        record: ScratchRecord,
        control: JobControl,
        publish: Publish,
        on_progress: Callable[[float, str | None], None],
    ) -> VideoReport:
        src = self._video_path(spec)
        started = time.perf_counter()
        record = await asyncio.to_thread(self._prepare, spec, record, src)
        await control.checkpoint(long=True)
        record = await self._guard_pass(spec, record, control, publish, on_progress)
        swap_started = time.perf_counter()
        record = await self._swap_all(spec, record, control, publish, on_progress)
        swap_time = time.perf_counter() - swap_started
        await control.checkpoint(long=True)
        stitch_started = time.perf_counter()
        output, audio = await asyncio.to_thread(self._stitch, spec, record, src)
        timings = dict(record.timings)
        timings["swap"] = round(timings.get("swap", 0.0) + swap_time, 3)
        timings["stitch"] = round(time.perf_counter() - stitch_started, 3)
        timings["total"] = round(time.perf_counter() - started, 3)
        record = replace(record, stage="stitched", output=str(output), timings=timings)
        write_video_record(output, record, spec, audio)
        self._save_record(record)
        if not spec.keep_frames:
            self.clear(record.job_id)
        on_progress(1.0, None)
        return VideoReport(
            output=output,
            frames=record.frames,
            pass_through=record.pass_through,
            seconds=record.seconds,
            timings=timings,
        )

    def _prepare(self, spec: VideoSpec, record: ScratchRecord, src: Path) -> ScratchRecord:
        """Probe and extract (skipped on resume when the frames are complete)."""
        clip = ffmpeg.probe(src)
        self.check_limits(spec, clip)
        start = spec.trim_start
        end = min(spec.trim_end, clip.seconds) if spec.trim_end is not None else clip.seconds
        seconds = max(0.0, end - start)
        if seconds <= 0:
            raise VideoError("The trim is empty. Pick a start before the end.")
        height = spec.frame_height
        scaled_h = min(clip.height, height) if height else clip.height
        scaled_w = round(clip.width * scaled_h / clip.height)
        frames_dir = self._frames_dir(record.job_id)
        if (
            record.stage != "new"
            and record.frames > 0
            and len(list(frames_dir.glob("frame_*.png"))) == record.frames
        ):
            return record
        t0 = time.perf_counter()
        made = ffmpeg.extract_frames(
            src,
            frames_dir,
            fps=clip.fps,
            start=start,
            end=end,
            max_height=height,
            source_height=clip.height,
        )
        if not made:
            raise VideoError("P11 could not read any frames from this clip.")
        record = replace(
            record,
            stage="extracted",
            frames=len(made),
            fps=clip.fps,
            seconds=seconds,
            width=scaled_w,
            height=scaled_h,
            timings={**record.timings, "extract": round(time.perf_counter() - t0, 3)},
        )
        self._save_record(record)
        return record

    async def _guard_pass(
        self,
        spec: VideoSpec,
        record: ScratchRecord,
        control: JobControl,
        publish: Publish,
        on_progress: Callable[[float, str | None], None],
    ) -> ScratchRecord:
        """S5 pre-pass: sampled frames (about 1/s) plus scene changes, before any swapping."""
        if record.guarded:
            return record
        frames = sorted(self._frames_dir(record.job_id).glob("frame_*.png"))

        def work(indices: list[int]) -> None:
            guard = self.faces.guard()  # GuardUnavailable fails closed
            for i in indices:
                check_target(guard, open_rgb(frames[i].read_bytes()))

        checked = sorted(
            set(sample_indices(len(frames), record.fps)) | set(await self._cuts(frames))
        )
        for start in range(0, max(1, len(checked)), 16):
            await control.checkpoint(long=True)
            chunk = checked[start : start + 16]
            await asyncio.to_thread(work, chunk)
            done = min(start + 16, len(checked))
            frac = W_EXTRACT + W_GUARD * (done / max(1, len(checked)))
            on_progress(frac, None)
            publish("progress", {"job": record.job_id, "run": 0, "runs": 1, "progress": frac,
                                 "step": done, "total": max(1, len(checked)),
                                 "title": "Checking the clip"})  # fmt: skip
        record = replace(record, guarded=True)
        self._save_record(record)
        return record

    async def _cuts(self, frames: list[Path]) -> list[int]:
        try:
            return await asyncio.to_thread(scene_indices, frames)
        except OSError:
            return []

    async def _swap_all(
        self,
        spec: VideoSpec,
        record: ScratchRecord,
        control: JobControl,
        publish: Publish,
        on_progress: Callable[[float, str | None], None],
    ) -> ScratchRecord:
        frames = sorted(self._frames_dir(record.job_id).glob("frame_*.png"))
        face = self.resolve_face(spec)
        total = max(1, record.frames)
        while record.swapped < record.frames:
            await control.checkpoint(long=True)
            batch = min(BATCH, record.frames - record.swapped)
            record = await asyncio.to_thread(self._swap_batch, spec, record, frames, face, batch)
            frac = W_EXTRACT + W_GUARD + W_SWAP * (record.swapped / total)
            on_progress(frac, None)
            publish("progress", {"job": record.job_id, "run": 0, "runs": 1, "progress": frac,
                                 "step": record.swapped, "total": record.frames,
                                 "title": "Swapping faces"})  # fmt: skip
        return replace(record, stage="swapped")

    def _swap_batch(
        self,
        spec: VideoSpec,
        record: ScratchRecord,
        frames: list[Path],
        face: bytes,
        count: int,
    ) -> ScratchRecord:
        """Swap (or pass through) frames one at a time from ``record.swapped`` on, saving the
        record after each frame, so a crash resumes at the right frame with no duplicates."""
        swapped_dir = self._swapped_dir(record.job_id)
        swapped_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        swapped_dir.chmod(0o700)
        params: dict[str, Any] = {
            "source_face_index": spec.source_face_index,
            "blend": 1.0,
            "restore": spec.restore,
        }
        tracked = record.tracked_box
        prev_swapped = record.prev_swapped
        pass_through = record.pass_through
        prev_path: Path | None = None
        if spec.smooth and record.swapped > 0:
            candidate = swapped_dir / frames[record.swapped - 1].name
            prev_path = candidate if candidate.is_file() else None

        for i in range(record.swapped, record.swapped + count):
            data = frames[i].read_bytes()
            out_path = swapped_dir / frames[i].name
            made, swapped_now = data, False
            try:
                boxes = [f.box for f in detect_faces(data, self.faces)[0]]
                index = tracked_pick(
                    boxes,
                    tracked,
                    auto=spec.target_face is None,
                    chosen=spec.target_face,
                )
                if index is None:
                    raise _PassThrough()
                tracked = boxes[index]
                params["target_face_index"] = index
                made = run_face_swap(params, {"image": data, "face": face}, self.faces)["image"]
                swapped_now = True
                prev_box = record.tracked_box
                if (
                    spec.smooth
                    and prev_path is not None
                    and prev_swapped
                    and prev_box is not None
                    and _iou(prev_box, tracked) >= SMOOTH_IOU
                ):
                    made = smooth_region(prev_path.read_bytes(), made, prev_box, tracked)
            except _PassThrough:
                pass
            except FaceError:
                # The face is gone or unswappable in this frame: pass it through rather than
                # swapping the wrong face. The per-frame guard has already run where it applied.
                pass
            _atomic_write(out_path, made)
            prev_path = out_path
            prev_swapped = swapped_now
            pass_through += 0 if swapped_now else 1
            record = replace(
                record,
                swapped=i + 1,
                pass_through=pass_through,
                tracked_box=tracked,
                prev_swapped=swapped_now,
            )
            self._save_record(record)
        return record

    def _stitch(
        self, spec: VideoSpec, record: ScratchRecord, src: Path
    ) -> tuple[Path, ffmpeg.AudioInfo | None]:
        clip = ffmpeg.probe(src)
        dest = output_path(self.outputs_root, self.clock(), None, 0, suffix=".mp4")
        ffmpeg.stitch(
            self._swapped_dir(record.job_id),
            src,
            dest,
            fps=record.fps,
            seconds=record.seconds,
            audio=clip.audio,
            crf=spec.crf,
            start=spec.trim_start,
        )
        return dest, clip.audio


# ---------------------------------------------------------------------------------------------
# Sidecar of a finished video (R7)


@dataclass(frozen=True)
class VideoRecord:
    """What made a finished video, from what, with what settings (its sidecar ``.json``, R7)."""

    record_version: int = 1
    kind: str = "video-face-swap"
    p11_version: str = __version__
    created_at: str = ""
    job_id: str = ""
    video: str = ""
    face: str = ""
    quality: str = "good"
    source_face_index: int = 0
    target_face: int | None = None
    trim_start: float = 0.0
    trim_end: float | None = None
    max_height: int | None = None
    smooth: bool = False
    frames: int = 0
    pass_through: int = 0
    seconds: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    audio_codec: str | None = None
    timings: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def write_video_record(dest: Path, record: ScratchRecord, spec: VideoSpec,
                       audio: ffmpeg.AudioInfo | None) -> Path:  # fmt: skip
    """Write ``<video>.json`` next to the output (``0600``), like an image's sidecar."""
    sidecar = dest.with_suffix(".json")
    payload = VideoRecord(
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        job_id=record.job_id,
        video=spec.video,
        face=spec.face,
        quality=spec.quality,
        source_face_index=spec.source_face_index,
        target_face=spec.target_face,
        trim_start=spec.trim_start,
        trim_end=spec.trim_end,
        max_height=spec.max_height,
        smooth=spec.smooth,
        frames=record.frames,
        pass_through=record.pass_through,
        seconds=record.seconds,
        fps=record.fps,
        width=record.width,
        height=record.height,
        audio_codec=audio.codec if audio else None,
        timings=dict(record.timings),
    )
    _atomic_write(sidecar, (payload.to_json() + "\n").encode())
    return sidecar


__all__ = [
    "ScratchRecord",
    "VideoError",
    "VideoJobs",
    "VideoRecord",
    "VideoReport",
    "VideoSpec",
    "sample_indices",
    "scene_indices",
    "smooth_region",
    "thumb_diff",
    "tracked_pick",
]
