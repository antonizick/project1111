"""``/api/session``: trade a one-time launch code for the session token (ADR-0022)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from p11 import __version__
from p11.api.security import LAUNCH_TTL, session_cookie

from .deps import StudioDep

router = APIRouter(prefix="/api/session", tags=["session"])


class Redeem(BaseModel):
    code: str = Field(min_length=8, max_length=128)


class SessionOut(BaseModel):
    token: str


class LaunchOut(BaseModel):
    code: str
    expires_in: float


class SessionInfo(BaseModel):
    ok: bool
    version: str
    fake: bool


@router.post("", response_model=SessionOut)
async def redeem(body: Redeem, response: Response, studio: StudioDep) -> SessionOut:
    """No token needed: the code from ``p11 open``'s URL fragment, valid once for 2 minutes."""
    if not studio.session.redeem(body.code):
        raise HTTPException(
            status_code=401, detail="This launch link was already used or has expired."
        )
    response.headers["set-cookie"] = session_cookie(studio.session.token)
    return SessionOut(token=studio.session.token)


@router.get("", response_model=SessionInfo)
async def info(studio: StudioDep) -> SessionInfo:
    return SessionInfo(ok=True, version=__version__, fake=studio.fake)


@router.post("/launch", response_model=LaunchOut)
async def launch(studio: StudioDep) -> LaunchOut:
    """A new launch code (``p11 open`` calls this with the token from the runtime dir)."""
    return LaunchOut(code=studio.session.mint_launch_code(), expires_in=LAUNCH_TTL)
