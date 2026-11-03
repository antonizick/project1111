"""``/api/templates``: the JSON template store (Phase 04) over HTTP."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from p11.recipe.migrate import migrate
from p11.recipe.model import Recipe
from p11.templates.store import MAX_IMPORT_BYTES, TemplateError, TemplateInfo

from .deps import StudioDep, not_found

router = APIRouter(prefix="/api/templates", tags=["templates"])


def template_json(t: TemplateInfo) -> dict[str, Any]:
    r = t.recipe
    return {
        "id": r.id,
        "name": r.name,
        "folder": t.folder,
        "slug": t.slug,
        "tags": list(r.tags),
        "slots": [s.model_dump(mode="json") for s in r.slots],
        "recipe": r.model_dump(mode="json"),
    }


def _find(studio: StudioDep, recipe_id: str) -> TemplateInfo:
    found = studio.templates.find(recipe_id)
    if found is None:
        raise not_found("Template")
    return found


@router.get("")
async def list_templates(
    studio: StudioDep,
    q: str = Query("", max_length=200),
    tag: str | None = Query(None, max_length=40),
) -> list[dict[str, Any]]:
    return [template_json(t) for t in studio.templates.search(q, tag)]


@router.get("/folders")
async def folders(studio: StudioDep) -> list[str]:
    return studio.templates.folders()


@router.post("", status_code=201)
async def create(recipe: dict[str, Any], studio: StudioDep) -> dict[str, Any]:
    parsed = migrate(recipe)
    if studio.templates.find(parsed.id) is not None:
        raise HTTPException(409, "A template with this ID exists; use PUT to change it.")
    return template_json(studio.templates.save(parsed))


@router.post("/import", status_code=201)
async def import_template(request: Request, studio: StudioDep) -> dict[str, Any]:
    data = await request.body()
    if len(data) > MAX_IMPORT_BYTES:
        raise TemplateError("The template file is too large.")
    return template_json(studio.templates.import_bytes(data))


@router.get("/{recipe_id}")
async def get(recipe_id: str, studio: StudioDep) -> dict[str, Any]:
    return template_json(_find(studio, recipe_id))


@router.put("/{recipe_id}")
async def update(recipe_id: str, recipe: dict[str, Any], studio: StudioDep) -> dict[str, Any]:
    parsed: Recipe = migrate(recipe)
    if parsed.id != recipe_id:
        raise HTTPException(422, "The recipe's id does not match the URL.")
    _find(studio, recipe_id)
    return template_json(studio.templates.save(parsed))


@router.delete("/{recipe_id}", status_code=204)
async def delete(recipe_id: str, studio: StudioDep) -> Response:
    if not studio.templates.delete(recipe_id):
        raise not_found("Template")
    return Response(status_code=204)


@router.get("/{recipe_id}/export")
async def export(recipe_id: str, studio: StudioDep) -> Response:
    found = _find(studio, recipe_id)
    return Response(
        studio.templates.export(recipe_id),
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="{found.slug}.p11.json"'},
    )
