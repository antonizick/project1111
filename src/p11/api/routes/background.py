"""``/api/background``: the Background view's look-before-you-run calls (Phase 11).

``/mask`` segments the subject of an image (the auto-mask the view shows and the refiner starts
from); ``/preview`` runs the same local pipeline a ``replace_background`` job runs (minus the
engine's harmonize pass) so the view shows what Apply will produce. Both run the CPU work in a
worker thread and never touch the engine (ADR-0026).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from p11.media.composite import CompositeParams, run_replace_background
from p11.media.imageio import open_rgb
from p11.media.nsfw import check_likeness
from p11.recipe.model import FileRef

from .deps import StudioDep

router = APIRouter(prefix="/api/background", tags=["background"])


class Ref(BaseModel):
    """A file P11 already holds: an upload ID (``img-…``) or ``gallery/<image ID>``."""

    ref: str = Field(min_length=1, max_length=255)


class MaskRequest(BaseModel):
    image: Ref
    segmentation_model: str | None = None


class PreviewRequest(BaseModel):
    image: Ref
    background: Ref | None = None
    background_colour: str | None = None
    #: A refined mask (upload); ``None`` segments the subject.
    mask: Ref | None = None
    segmentation_model: str | None = None
    colour_match: bool = True
    colour_match_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    feather_px: int = Field(default=8, ge=0, le=128)
    fit: Literal["cover", "contain"] = "cover"
    background_x: float = Field(default=0.5, ge=0.0, le=1.0)
    background_y: float = Field(default=0.5, ge=0.0, le=1.0)
    subject_scale: float = Field(default=1.0, ge=0.1, le=4.0)
    subject_x: float = Field(default=0.5, ge=0.0, le=1.0)
    subject_y: float = Field(default=0.5, ge=0.0, le=1.0)
    shadow: bool = False


def _png(data: bytes) -> Response:
    return Response(content=data, media_type="image/png")


@router.post("/mask")
async def mask(body: MaskRequest, studio: StudioDep) -> Response:
    """The subject mask of an image, greyscale PNG (white = subject)."""
    runner = studio.queue.runner
    subject = runner.resolve_file(FileRef(ref=body.image.ref))

    def work() -> bytes:
        return studio.segmenters.segmenter(body.segmentation_model).mask(subject)

    return _png(await asyncio.to_thread(work))


@router.post("/preview")
async def preview(body: PreviewRequest, studio: StudioDep) -> Response:
    """The composited image (what Apply will save, without the harmonize pass).

    S5 (ADR-0047): a gallery picture from a likeness run passes the guard here as it does on Apply.
    """
    runner = studio.queue.runner
    subject = runner.resolve_file(FileRef(ref=body.image.ref))
    background = runner.resolve_file(FileRef(ref=body.background.ref)) if body.background else None
    pictures = [FileRef(ref=r.ref) for r in (body.image, body.background) if r is not None]
    likeness = runner.refs_carry_likeness(pictures)  # gallery: this thread
    mask_bytes = runner.resolve_file(FileRef(ref=body.mask.ref)) if body.mask else None
    params = CompositeParams(
        colour_match=body.colour_match,
        colour_match_strength=body.colour_match_strength,
        feather_px=body.feather_px,
        fit=body.fit,
        background_x=body.background_x,
        background_y=body.background_y,
        subject_scale=body.subject_scale,
        subject_x=body.subject_x,
        subject_y=body.subject_y,
        shadow=body.shadow,
        background_colour=body.background_colour,
    )

    def work() -> bytes:
        inputs: dict[str, bytes] = {"image": subject}
        if background is not None:
            inputs["background"] = background
        if mask_bytes is not None:
            inputs["mask"] = mask_bytes
        out = run_replace_background(asdict(params), inputs, studio.segmenters)
        if likeness:
            check_likeness(runner.faces.guard(), open_rgb(out["image"]))
        return out["image"]

    return _png(await asyncio.to_thread(work))
