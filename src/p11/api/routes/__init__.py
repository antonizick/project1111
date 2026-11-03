"""Studio API routes (Phase 07). Every route here is behind ``SecurityMiddleware``."""

from __future__ import annotations

from fastapi import APIRouter

from . import background, events, face, gallery, jobs, session, system, templates, uploads, video

ROUTERS: tuple[APIRouter, ...] = (
    session.router,
    jobs.router,
    events.router,
    gallery.router,
    uploads.router,
    templates.router,
    background.router,
    face.router,
    video.router,
    system.router,
)
