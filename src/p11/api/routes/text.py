"""``/api/text``: the bundled fonts and a live text-overlay preview (Phase 14, ADR-0035).

The preview runs the same ``p11.media.text.render`` call the job runner uses, so what the editor
shows is what the saved image gets. Without an image the preview draws on a dark canvas at the
requested size, which is enough to place the text before a generation exists.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from p11.media import text
from p11.media.imageio import png
from p11.recipe.model import FileRef, TextOverlay

from .deps import StudioDep

router = APIRouter(prefix="/api/text", tags=["text"])


class Ref(BaseModel):
    ref: str = Field(min_length=1, max_length=255)


class PreviewRequest(BaseModel):
    #: An upload ID or ``gallery/<image ID>``; omitted, a plain canvas is used.
    image: Ref | None = None
    overlay: TextOverlay
    width: int = Field(default=1024, ge=64, le=8192)
    height: int = Field(default=1024, ge=64, le=8192)


@router.get("/fonts")
async def fonts() -> dict[str, object]:
    return {"fonts": text.font_info()}


@router.post("/preview")
async def preview(body: PreviewRequest, studio: StudioDep) -> Response:
    if body.image is not None:
        source = studio.queue.runner.resolve_file(FileRef(ref=body.image.ref))
    else:
        source = png(Image.new("RGB", (body.width, body.height), "#1b1b26"))

    def work() -> bytes:
        return text.render_overlay(source, body.overlay.model_dump())

    try:
        data = await asyncio.to_thread(work)
    except text.TextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(content=data, media_type="image/png")
