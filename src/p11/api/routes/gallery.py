"""``/api/gallery`` and ``/api/images/{id}``: browse, favourite, export, re-open as a recipe.

Phase 08 adds the model filter, facets, bulk export (a ZIP), variations and the trash: deleting an
image moves its PNG and sidecar to ``<data>/trash/`` and drops the index entry; only
``POST /api/trash/empty`` removes files for good.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import random
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from p11 import paths
from p11.jobs.queue import MAX_COUNT
from p11.jobs.runner import image_json
from p11.outputs import metadata
from p11.outputs.index import ImageEntry
from p11.recipe.model import MAX_SEED, IncrementSeed
from p11.recipe.variations import prompt_mutation

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


class BulkExport(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    strip_metadata: bool = True


class Variations(BaseModel):
    #: ``seed``: the same recipe with the next seeds; ``prompt``: a small prompt change per image.
    mode: Literal["seed", "prompt"] = "seed"
    count: int = Field(default=1, ge=1, le=4)


class Facets(BaseModel):
    templates: list[str]
    models: list[str]


class TrashInfo(BaseModel):
    count: int
    bytes: int


@router.get("/gallery", response_model=GalleryPage)
async def gallery(
    studio: StudioDep,
    q: str = Query("", max_length=200),
    template: str | None = Query(None, max_length=64),
    favourites: bool = False,
    since: str | None = Query(None, max_length=40, description="ISO timestamp, inclusive"),
    until: str | None = Query(None, max_length=40, description="ISO timestamp, exclusive"),
    model: str | None = Query(None, max_length=64),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters: dict[str, Any] = dict(
        template=template, favourites=favourites, since=since, until=until, model=model
    )
    items = studio.gallery.search(q, limit=limit, offset=offset, **filters)
    return {
        "items": [image_json(e) for e in items],
        "total": studio.gallery.search_count(q, **filters),
        "limit": limit,
        "offset": offset,
    }


@router.get("/gallery/facets", response_model=Facets)
async def facets(studio: StudioDep) -> dict[str, list[str]]:
    return studio.gallery.facets()


@router.post("/gallery/export")
async def bulk_export(body: BulkExport, studio: StudioDep) -> Response:
    """Several images as one ZIP (stored, PNGs are compressed already)."""
    files = [(image_id, entry_file(studio, image_id)[1]) for image_id in dict.fromkeys(body.ids)]

    def build() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for image_id, path in files:
                data = metadata.strip_metadata(path) if body.strip_metadata else path.read_bytes()
                zf.writestr(f"p11-{image_id}.png", data)
        return buf.getvalue()

    data = await asyncio.to_thread(build)
    return Response(
        data,
        media_type="application/zip",
        headers={"content-disposition": 'attachment; filename="p11-export.zip"'},
    )


def _trash_dir(studio: StudioDep) -> Path:
    return studio.paths.data / "trash"


def _trash_info(directory: Path) -> dict[str, int]:
    if not directory.is_dir():
        return {"count": 0, "bytes": 0}
    files = [p for p in directory.iterdir() if p.is_file()]
    return {
        "count": sum(1 for p in files if p.suffix == ".png"),
        "bytes": sum(p.stat().st_size for p in files),
    }


@router.get("/trash", response_model=TrashInfo)
async def trash(studio: StudioDep) -> dict[str, int]:
    return await asyncio.to_thread(_trash_info, _trash_dir(studio))


@router.post("/trash/empty", response_model=TrashInfo)
async def empty_trash(studio: StudioDep) -> dict[str, int]:
    """Delete everything in P11's trash folder for good (only files P11 moved there)."""
    directory = _trash_dir(studio)
    if directory.is_dir():
        await asyncio.to_thread(shutil.rmtree, directory)
    return {"count": 0, "bytes": 0}


def entry_file(studio: StudioDep, image_id: int) -> tuple[ImageEntry, Path]:
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
    _, path = entry_file(studio, image_id)
    return FileResponse(path, media_type="image/png")


@router.get("/images/{image_id}/info", response_model=ImageOut)
async def image_info(image_id: int, studio: StudioDep) -> dict[str, Any]:
    entry, _ = entry_file(studio, image_id)
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
    _, path = entry_file(studio, image_id)
    size = min(THUMB_SIZES, key=lambda s: abs(s - size))
    out = await asyncio.to_thread(_thumbnail, path, size)
    return FileResponse(out, media_type="image/webp")


@router.post("/images/{image_id}/favourite", response_model=ImageOut)
async def favourite(image_id: int, body: Favourite, studio: StudioDep) -> dict[str, Any]:
    entry_file(studio, image_id)
    studio.gallery.set_favourite(image_id, body.favourite)
    entry = studio.gallery.get(image_id)
    assert entry is not None
    data = image_json(entry)
    studio.bus.publish("image", {"job": None, "image": data})
    return data


@router.post("/images/{image_id}/export")
async def export(image_id: int, body: Export, studio: StudioDep) -> Response:
    """The PNG as a download; ``strip_metadata`` drops the recipe, text, EXIF and time chunks."""
    _, path = entry_file(studio, image_id)
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


def run_record(path: Path) -> metadata.RunRecord:
    try:
        return metadata.read_sidecar(metadata.sidecar_path(path))
    except (OSError, ValueError):
        return metadata.read_run_from_png(path)


@router.get("/images/{image_id}/recipe")
async def recipe(image_id: int, studio: StudioDep) -> dict[str, Any]:
    """The run record (recipe, bindings, seed, models, timings): sidecar first, then PNG chunks."""
    _, path = entry_file(studio, image_id)
    out: dict[str, Any] = run_record(path).model_dump(mode="json")
    return out


@router.post("/images/{image_id}/variations", status_code=201)
async def variations(image_id: int, body: Variations, studio: StudioDep) -> dict[str, Any]:
    """Queue variations of an image (spec §4): the next seeds, or one small prompt change each.

    Seed variations are one job of ``count`` runs (seeds ``seed + 1 …``); prompt variations are
    ``count`` jobs, each with its own mutation and the original seed, so only the words change.
    """
    entry, path = entry_file(studio, image_id)
    record = run_record(path)
    bindings = {k: v if isinstance(v, str) else v.model_dump() for k, v in record.bindings.items()}
    if body.mode == "seed":
        start = (record.seed + 1) % (MAX_SEED + 1)
        recipes = [record.recipe.model_copy(update={"seed": IncrementSeed(start=start)})]
        count = min(body.count, MAX_COUNT)
    else:
        rng = random.Random()
        recipes = [
            prompt_mutation(record.recipe, rng).model_copy(
                update={"id": uuid.uuid4().hex, "seed": IncrementSeed(start=record.seed)}
            )
            for _ in range(body.count)
        ]
        count = 1
    jobs = [
        studio.queue.submit(
            r.model_dump(mode="json"),
            bindings,
            count=count,
            template=record.template,
            parent=entry.path,
        ).summary()
        for r in recipes
    ]
    return {"jobs": jobs}


@router.delete("/images/{image_id}")
async def delete(image_id: int, studio: StudioDep) -> dict[str, Any]:
    """Move the image and its sidecar to P11's trash folder and drop it from the gallery."""
    entry, path = entry_file(studio, image_id)
    directory = paths.ensure_private_dir(_trash_dir(studio))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{image_id}-{path.stem}"

    def move() -> None:
        shutil.move(path, directory / f"{base}.png")
        sidecar = metadata.sidecar_path(path)
        if sidecar.exists():
            shutil.move(sidecar, directory / f"{base}.json")

    await asyncio.to_thread(move)
    studio.gallery.delete(image_id)
    studio.bus.publish("deleted", {"image": image_id})
    info = await asyncio.to_thread(_trash_info, directory)
    return {"deleted": entry.id, "trash": info}
