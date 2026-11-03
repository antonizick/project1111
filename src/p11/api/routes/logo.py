"""Logo export (Phase 14): square PNGs (512 → 32) and a favicon, transparent by default."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from p11.media.logo import DEFAULT_SIZES, LogoError, pack
from p11.recipe.model import FileRef

from .deps import StudioDep, not_found

router = APIRouter(prefix="/api", tags=["logo"])


class LogoExportRequest(BaseModel):
    #: Cut the background out (segmentation, else a flat-colour key). Off = the image as it is.
    transparent: bool = True
    sizes: list[int] = Field(default_factory=lambda: list(DEFAULT_SIZES), max_length=8)


@router.post("/images/{image_id}/logo-export")
async def logo_export(image_id: int, body: LogoExportRequest, studio: StudioDep) -> Response:
    entry = studio.gallery.get(image_id)
    if entry is None:
        raise not_found("Image")
    source = studio.queue.runner.resolve_file(FileRef(ref=f"gallery/{image_id}"))
    try:
        data = await asyncio.to_thread(
            pack,
            source,
            transparent=body.transparent,
            sizes=body.sizes,
            segmenters=studio.segmenters,
            name=entry.prompt or f"p11-{image_id}",
        )
    except LogoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    filename = f"p11-logo-{image_id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )
