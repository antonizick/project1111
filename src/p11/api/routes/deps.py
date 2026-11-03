"""Shared route helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from p11.api.studio import Studio


def _studio(request: Request) -> Studio:
    studio: Studio = request.app.state.studio
    return studio


StudioDep = Annotated[Studio, Depends(_studio)]


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found.")
