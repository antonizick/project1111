"""``/api/jobs``: submit a recipe + bindings, inspect and cancel jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from p11.jobs.queue import MAX_COUNT

from .deps import StudioDep, not_found

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobRequest(BaseModel):
    recipe: dict[str, Any]
    #: Slot name → text, or ``{"ref": "<upload ID>"}`` / ``{"ref": "gallery/<image ID>"}``.
    bindings: dict[str, Any] = Field(default_factory=dict)
    count: int = Field(default=1, ge=1, le=MAX_COUNT)
    #: Template slug the run came from (output folder and gallery filter).
    template: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    #: Gallery image this run was made from (variation, edit).
    parent: int | None = None


class JobErrorOut(BaseModel):
    code: str
    message: str
    hint: str


class JobOut(BaseModel):
    id: str
    state: str
    name: str
    count: int
    template: str | None
    created_at: str
    updated_at: str
    images: list[int]
    progress: float
    error: JobErrorOut | None
    note: str | None


@router.post("", response_model=JobOut, status_code=201)
async def submit(body: JobRequest, studio: StudioDep) -> dict[str, Any]:
    parent = None
    if body.parent is not None:
        entry = studio.gallery.get(body.parent)
        if entry is None:
            raise not_found("Parent image")
        parent = entry.path
    job = studio.queue.submit(
        body.recipe, body.bindings, count=body.count, template=body.template, parent=parent
    )
    return job.summary()


@router.get("", response_model=list[JobOut])
async def recent(studio: StudioDep, limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return [j.summary() for j in studio.queue.recent(limit)]


@router.get("/{job_id}", response_model=JobOut)
async def get(job_id: str, studio: StudioDep) -> dict[str, Any]:
    job = studio.queue.get(job_id)
    if job is None:
        raise not_found("Job")
    return job.summary()


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel(job_id: str, studio: StudioDep) -> dict[str, Any]:
    job = await studio.queue.cancel(job_id)
    if job is None:
        raise not_found("Job")
    return job.summary()
