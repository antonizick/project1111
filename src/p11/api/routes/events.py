"""``GET /api/events``: server-sent events (ADR-0022).

Event types: ``hello`` (snapshot on connect), ``job`` (a job changed state, progress note or
images), ``progress`` (sampler steps), ``preview`` (base64 JPEG, ≤ 2 per second), ``image`` (a
new gallery entry) and ``gpu`` (≤ 1 Hz while anyone listens). The SSE ``id`` is the bus's
increasing event ID; send ``Last-Event-ID`` to resume after a reconnect.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.sse import EventSourceResponse, ServerSentEvent

from .deps import StudioDep

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", response_class=EventSourceResponse)
async def events(
    studio: StudioDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    last = int(last_event_id) if last_event_id and last_event_id.isdigit() else None
    async with studio.bus.subscribe(last) as stream:
        if last is None:
            jobs = [j.summary() for j in studio.queue.recent(20)]
            yield ServerSentEvent(
                event="hello", id=str(studio.bus.last_id), data={"jobs": jobs}, retry=2000
            )
        async for ev in stream:
            yield ServerSentEvent(event=ev.type, id=str(ev.id), data=ev.data)
