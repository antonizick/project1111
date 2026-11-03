"""``/api/gallery`` and ``/api/images/{id}``: browse, favourite, export, re-open as a recipe."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel

from p11 import paths
from p11.jobs.runner import image_json
from p11.outputs import metadata
from p11.outputs.index import ImageEntry

from .deps import StudioDep, not_found

router = APIRouter(prefix="/api", tags=["gallery"])
THUMB_SIZES = (256, 384, 512)


class ImageOut(BaseModel):
    id: int
    path: str
    created_at: str
    recipe_id: str
    template: str | None
    seed: int
    model: str | None
    width: int | None
    height: int | None
    favourite: bool
    parent_id: int | None
    prompt: str
    url: str
    thumb: str


class GalleryPage(BaseModel):
    items: list[ImageOut]
    total: int
    limit: int
    offset: int


class Favourite(BaseModel):
    favourite: bool = True


class Export(BaseModel):
    strip_metadata: bool = True


@router.get("/gallery", response_model=GalleryPage)
async def gallery(
    studio: StudioDep,
    q: str = Query("", max_length=200),
    template: str | None = Query(None, max_length=64),
    favourites: bool = False,
    since: str | None = Query(None, max_length=40, description="ISO timestamp, inclusive"),
    until: str | None = Query(None, max_length=40, description="ISO timestamp, exclusive"),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters: dict[str, Any] = dict(
        template=template, favourites=favourites, since=since, until=until
    )
    items = studio.gallery.search(q, limit=limit, offset=offset, **filters)
    return {
        "items": [image_json(e) for e in items],
        "total": studio.gallery.search_count(q, **filters),
        "limit": limit,
        "offset": offset,
    }


def _entry_file(studio: StudioDep, image_id: int) -> tuple[ImageEntry, Path]:
    entry = studio.gallery.get(image_id)
    if entry is None:
        raise not_found("Image")
    root = studio.paths.outputs.resolve()
    path = (root / entry.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise not_found("Image file")
    return entry, path


@router.get("/images/{image_id}", response_class=FileResponse)
async def image(image_id: int, studio: StudioDep) -> FileResponse:
    _, path = _entry_file(studio, image_id)
    return FileResponse(path, media_type="image/png")


@router.get("/images/{image_id}/info", response_model=ImageOut)
async def image_info(image_id: int, studio: StudioDep) -> dict[str, Any]:
    entry, _ = _entry_file(studio, image_id)
    return image_json(entry)


def _thumbnail(src: Path, size: int) -> Path:
    st = src.stat()
    key = hashlib.sha256(f"{src}:{st.st_mtime_ns}:{st.st_size}:{size}".encode()).hexdigest()[:32]
    directory = paths.ensure_private_dir(paths.cache_dir() / "thumbs")
    out = directory / f"{key}.webp"
    if out.exists():
        return out
    with Image.open(src) as img:
        img.thumbnail((size, size))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="WEBP", quality=82)
    tmp = directory / f".{key}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(buf.getvalue())
    tmp.replace(out)
    return out


@router.get("/images/{image_id}/thumb", response_class=FileResponse)
async def thumb(
    image_id: int, studio: StudioDep, size: int = Query(384, ge=64, le=512)
) -> FileResponse:
    _, path = _entry_file(studio, image_id)
    size = min(THUMB_SIZES, key=lambda s: abs(s - size))
    out = await asyncio.to_thread(_thumbnail, path, size)
    return FileResponse(out, media_type="image/webp")


@router.post("/images/{image_id}/favourite", response_model=ImageOut)
async def favourite(image_id: int, body: Favourite, studio: StudioDep) -> dict[str, Any]:
    _entry_file(studio, image_id)
    studio.gallery.set_favourite(image_id, body.favourite)
    entry = studio.gallery.get(image_id)
    assert entry is not None
    data = image_json(entry)
    studio.bus.publish("image", {"job": None, "image": data})
    return data


@router.post("/images/{image_id}/export")
async def export(image_id: int, body: Export, studio: StudioDep) -> Response:
    """The PNG as a download; ``strip_metadata`` drops the recipe, text, EXIF and time chunks."""
    _, path = _entry_file(studio, image_id)
    data = (
        await asyncio.to_thread(metadata.strip_metadata, path)
        if body.strip_metadata
        else await asyncio.to_thread(path.read_bytes)
    )
    return Response(
        data,
        media_type="image/png",
        headers={"content-disposition": f'attachment; filename="p11-{image_id}.png"'},
    )


@router.get("/images/{image_id}/recipe")
async def recipe(image_id: int, studio: StudioDep) -> dict[str, Any]:
    """The run record (recipe, bindings, seed, models, timings): sidecar first, then PNG chunks."""
    _, path = _entry_file(studio, image_id)
    sidecar = metadata.sidecar_path(path)
    try:
        record = metadata.read_sidecar(sidecar)
    except (OSError, ValueError):
        record = metadata.read_run_from_png(path)
    out: dict[str, Any] = record.model_dump(mode="json")
    return out
