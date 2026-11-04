"""``/api/video``: the Video view's clip look-before-you-run calls and video face-swap jobs.

``GET /api/video/frame`` pulls one still out of a clip (the face-picker thumbnail), ``POST
/api/video/detect`` finds the faces on it, and ``/api/video/jobs`` submits, lists, resumes and
downloads video face-swap runs (the pipeline itself is ``p11.jobs.video``). The output is an MP4 in
the R7 outputs layout with a JSON sidecar; it is served here with Range support so a ``<video>``
player can seek. Job progress rides the normal job/SSE model (``kind: "video"``).

The S5 guard runs at submit time on the clip's first frame and, inside the job, on every swapped
frame (and on the sampled pre-pass); nothing here can turn it off.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from p11.api.studio import Studio
from p11.jobs.video import VideoError, VideoJobs, VideoSpec
from p11.media.faces import detect_faces
from p11.media.inputs import UnknownInput

from .deps import StudioDep, not_found

router = APIRouter(prefix="/api/video", tags=["video"])


class FrameRef(BaseModel):
    """A stored clip (``vid-…``) and the moment in it to look at."""

    ref: str = Field(min_length=5, max_length=64)
    time: float = Field(default=0.0, ge=0.0, le=600.0)


class VideoRequest(BaseModel):
    video: str = Field(min_length=5, max_length=64)
    #: Face photo: an upload ID (``img-…``) or ``gallery/<image ID>``.
    face: str = Field(min_length=1, max_length=255)
    quality: Literal["fast", "good"] = "good"
    source_face_index: int = Field(default=0, ge=0, le=15)
    #: Face clicked on the first frame; ``None`` = largest face in every frame.
    target_face: int | None = Field(default=None, ge=0, le=15)
    trim_start: float = Field(default=0.0, ge=0.0, le=600.0)
    trim_end: float | None = Field(default=None, ge=0.0, le=600.0)
    max_height: int | None = Field(default=None, ge=120, le=2160)
    smooth: bool = False
    keep_frames: bool = False
    confirm_limits: bool = False

    def to_spec(self) -> VideoSpec:
        return VideoSpec(
            video=self.video,
            face=self.face,
            quality=self.quality,
            source_face_index=self.source_face_index,
            target_face=self.target_face,
            trim_start=self.trim_start,
            trim_end=self.trim_end,
            max_height=self.max_height,
            smooth=self.smooth,
            keep_frames=self.keep_frames,
            confirm_limits=self.confirm_limits,
        )


def _video_tools(studio: Studio) -> VideoJobs:
    tools = studio.queue.video
    if tools is None:
        raise VideoError("Video face-swap is not available in this session.")
    return tools


def _still(studio: Studio, input_id: str, at: float) -> bytes:
    """One frame of a stored clip as PNG bytes (decoded and re-encoded without metadata)."""
    from p11.media import ffmpeg

    tools = _video_tools(studio)
    try:
        stored = studio.inputs.get(input_id)
    except UnknownInput:
        raise not_found("Upload") from None
    if stored.kind != "video":
        raise VideoError("That upload is not a video.")
    tmp = tools.scratch_root / f".still-{uuid.uuid4().hex}.png"
    try:
        tools.scratch_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        ffmpeg.still_frame(stored.path, tmp, at=at)
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/frame")
async def frame(body: FrameRef, studio: StudioDep) -> Response:
    """A still from the clip (the Video view's thumbnail), upright, without metadata."""
    data = await asyncio.to_thread(_still, studio, body.ref, body.time)
    return Response(content=data, media_type="image/png")


@router.post("/detect")
async def detect(body: FrameRef, studio: StudioDep) -> dict[str, Any]:
    """Faces on a clip's frame, largest first: ``{faces: [{box, score}], width, height}``."""
    data = await asyncio.to_thread(_still, studio, body.ref, body.time)

    def work() -> dict[str, Any]:
        faces, (w, h) = detect_faces(data, studio.faces)
        return {"faces": [f.to_json(w, h) for f in faces], "width": w, "height": h}

    return await asyncio.to_thread(work)


def _detail(studio: Studio, job_id: str) -> dict[str, Any] | None:
    job = studio.queue.get(job_id)
    if job is None or job.kind != "video":
        return None
    tools = studio.queue.video
    record_id = (job.spec or {}).get("resume_of") or job.id
    record = tools.record(record_id) if tools else None
    out: dict[str, Any] = {
        **job.summary(),
        "record_job": record_id,
        "stage": record.stage if record else "new",
        "frames": record.frames if record else 0,
        "swapped": record.swapped if record else 0,
        "pass_through": record.pass_through if record else 0,
        "seconds": record.seconds if record else 0.0,
        "fps": record.fps if record else 0.0,
        "width": record.width if record else 0,
        "height": record.height if record else 0,
        "timings": record.timings if record else {},
        "resumable": bool(tools and tools.resumable(record_id)),
        "file": None,
    }
    if record and record.output and Path(record.output).is_file():
        out["file"] = f"/api/video/jobs/{job.id}/file"
    return out


@router.post("/jobs", status_code=201)
async def submit(body: VideoRequest, studio: StudioDep) -> dict[str, Any]:
    """Queue a video face-swap (validated and guard-checked before it is accepted)."""
    spec = body.to_spec()
    studio.queue.check_video_face(spec)
    await asyncio.to_thread(studio.queue.check_video, spec)
    job = studio.queue.submit_video(spec)
    detail = _detail(studio, job.id)
    assert detail is not None
    return detail


@router.get("/jobs")
async def list_jobs(
    studio: StudioDep, limit: int = Query(20, ge=1, le=100)
) -> list[dict[str, Any]]:
    return [d for j in studio.queue.recent(limit * 3) if (d := _detail(studio, j.id)) is not None][
        :limit
    ]


@router.get("/jobs/{job_id}")
async def get(job_id: str, studio: StudioDep) -> dict[str, Any]:
    detail = _detail(studio, job_id)
    if detail is None:
        raise not_found("Video job")
    return detail


@router.post("/jobs/{job_id}/resume", status_code=201)
async def resume(job_id: str, studio: StudioDep) -> dict[str, Any]:
    """Continue an interrupted run from its last finished frame (same settings)."""
    spec = studio.queue.resume_video(job_id)
    studio.queue.check_video_face(spec)
    await asyncio.to_thread(studio.queue.check_video, spec)
    job = studio.queue.submit_video(spec)
    detail = _detail(studio, job.id)
    assert detail is not None
    return detail


@router.get("/jobs/{job_id}/file", response_class=FileResponse)
async def result_file(
    job_id: str, studio: StudioDep,
    download: bool = Query(False),
) -> FileResponse:  # fmt: skip
    """The finished MP4 (Range-capable, so a ``<video>`` player can seek)."""
    detail = _detail(studio, job_id)
    if detail is None or not detail["file"]:
        raise not_found("Video")
    record = studio.queue.video.record(detail["record_job"]) if studio.queue.video else None
    if record is None or not record.output:
        raise not_found("Video")
    path = Path(record.output)
    if not path.is_file():
        raise not_found("Video")
    headers = {}
    if download:
        headers["content-disposition"] = f'attachment; filename="p11-{job_id[:8]}.mp4"'
    return FileResponse(path, media_type="video/mp4", headers=headers)


__all__ = ["router"]
