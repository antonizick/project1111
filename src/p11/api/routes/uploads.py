"""``/api/uploads``: validated image, mask and video inputs (spec S8).

The body is the raw file (``fetch(url, {method: "POST", body: file})``), not multipart, so no
multipart parser is needed. Names are generated; the response is an opaque ID for bindings.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from p11.media.inputs import UnknownInput
from p11.media.validate import MAX_IMAGE_BYTES, MAX_VIDEO_BYTES, UploadRejected

from .deps import StudioDep, not_found

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadOut(BaseModel):
    id: str
    kind: str
    width: int
    height: int
    sha256: str
    created_at: str
    seconds: float | None
    warnings: list[str]


def _too_big(limit: int) -> UploadRejected:
    return UploadRejected(
        f"The file is larger than {limit // (1024 * 1024)} MB.", "Use a smaller file."
    )


@router.post("", response_model=UploadOut, status_code=201)
async def upload(
    request: Request,
    studio: StudioDep,
    kind: Literal["image", "mask", "video"] = Query("image"),
) -> dict[str, Any]:
    if kind != "video":
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_IMAGE_BYTES:
                raise _too_big(MAX_IMAGE_BYTES)
        if not data:
            raise UploadRejected("The upload is empty.")
        item = await asyncio.to_thread(studio.inputs.add_image, bytes(data), kind)
        return item.as_json()
    fd, spool = studio.inputs.spool()
    try:
        size = 0
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise _too_big(MAX_VIDEO_BYTES)
                fh.write(chunk)
        if size == 0:
            raise UploadRejected("The upload is empty.")
        s = studio.settings
        item = await asyncio.to_thread(
            studio.inputs.add_video,
            spool,
            warn_seconds=s.video_warn_seconds,
            warn_height=s.video_warn_height,
        )
    finally:
        spool.unlink(missing_ok=True)
    return item.as_json()


@router.get("/{input_id}/info", response_model=UploadOut)
async def info(input_id: str, studio: StudioDep) -> dict[str, Any]:
    try:
        return studio.inputs.get(input_id).as_json()
    except UnknownInput:
        raise not_found("Upload") from None


@router.get("/{input_id}", response_class=FileResponse)
async def file(input_id: str, studio: StudioDep) -> FileResponse:
    try:
        item = studio.inputs.get(input_id)
    except UnknownInput:
        raise not_found("Upload") from None
    media = "image/png" if item.kind != "video" else "video/mp4"
    if item.path.suffix == ".mkv":
        media = "video/x-matroska"
    return FileResponse(item.path, media_type=media)
