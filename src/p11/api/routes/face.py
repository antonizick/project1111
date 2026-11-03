"""``/api/face`` and ``/api/pose``: the Face & Pose view's look-before-you-run calls (Phase 12).

``/api/face/detect`` finds the faces in a photo (so the user can click the one to use),
``/api/pose/extract`` reads a body pose out of a photo, ``/api/pose/render`` draws the skeleton
picture the pose editor shows and the ControlNet reads. All of it is CPU work in P11
(``p11.media.faces`` / ``p11.media.pose``), never engine work, so none of it needs the GPU.

None of these run a face swap, so the S5 guard does not apply here; it runs on every swap
(``p11.jobs.runner``, and inside the swap itself). These routes never store what they are given.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from p11.media.faces import detect_faces
from p11.media.pose import MAX_PEOPLE, extract_people, parse_people, people_json, render_png
from p11.recipe.model import FileRef

from .deps import StudioDep

router = APIRouter(prefix="/api", tags=["face"])


class Ref(BaseModel):
    """A file P11 already holds: an upload ID (``img-…``) or ``gallery/<image ID>``."""

    ref: str = Field(min_length=1, max_length=255)


class PoseRequest(BaseModel):
    people: list[Any]
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)


@router.post("/face/detect")
async def face_detect(body: Ref, studio: StudioDep) -> dict[str, Any]:
    """Faces in an image, largest first: ``{faces: [{box, score}], width, height}``."""
    image = studio.queue.runner.resolve_file(FileRef(ref=body.ref))

    def work() -> dict[str, Any]:
        faces, (w, h) = detect_faces(image, studio.faces)
        return {"faces": [f.to_json(w, h) for f in faces], "width": w, "height": h}

    return await asyncio.to_thread(work)


@router.post("/pose/extract")
async def pose_extract(body: Ref, studio: StudioDep) -> dict[str, Any]:
    """Body poses in an image (normalized keypoints, OpenPose-18 order)."""
    image = studio.queue.runner.resolve_file(FileRef(ref=body.ref))

    def work() -> dict[str, Any]:
        people, (w, h) = extract_people(image, studio.controls.pose())
        return {"people": people_json(people), "width": w, "height": h}

    return await asyncio.to_thread(work)


@router.post("/pose/render")
async def pose_render(body: PoseRequest) -> Response:
    """The OpenPose control picture for a pose (black background, coloured limbs)."""
    people = parse_people(body.people)

    def work() -> bytes:
        return render_png(people, body.width, body.height)

    return Response(content=await asyncio.to_thread(work), media_type="image/png")


__all__ = ["MAX_PEOPLE", "router"]
