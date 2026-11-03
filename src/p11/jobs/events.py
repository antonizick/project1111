"""In-process event bus for the Studio's ``GET /api/events`` stream (ADR-0022).

Every event gets a strictly increasing ``id``; the SSE stream sends it as the event ID, so a
reconnecting browser (``Last-Event-ID``) gets what it missed from a short replay buffer and the
order is the publish order. Slow subscribers lose their oldest *transient* events (previews,
GPU samples) first; job state changes are kept. Nothing here carries prompt text.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

#: Event types a slow subscriber may lose; the rest (job state, images) are never dropped.
TRANSIENT = frozenset({"preview", "gpu", "progress"})
REPLAY = 256
QUEUE = 512


@dataclass(frozen=True)
class Event:
    id: int
    type: str
    data: dict[str, Any]


class _Subscriber:
    def __init__(self) -> None:
        self.items: deque[Event] = deque()
        self.ready = asyncio.Event()

    def push(self, event: Event) -> None:
        if len(self.items) >= QUEUE:
            victim = next((e for e in self.items if e.type in TRANSIENT), None)
            if victim is not None:
                self.items.remove(victim)
            elif event.type in TRANSIENT:
                return
            else:
                self.items.popleft()
        self.items.append(event)
        self.ready.set()


class EventBus:
    def __init__(self) -> None:
        self._next = 1
        self._replay: deque[Event] = deque(maxlen=REPLAY)
        self._subs: set[_Subscriber] = set()

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    @property
    def last_id(self) -> int:
        return self._next - 1

    def publish(self, type: str, data: dict[str, Any]) -> Event:
        event = Event(self._next, type, data)
        self._next += 1
        if type != "preview":  # previews are large and stale by the time anyone reconnects
            self._replay.append(event)
        for sub in self._subs:
            sub.push(event)
        return event

    @contextlib.asynccontextmanager
    async def subscribe(self, last_id: int | None = None) -> AsyncIterator[AsyncIterator[Event]]:
        sub = _Subscriber()
        if last_id is not None:
            for event in self._replay:
                if event.id > last_id:
                    sub.push(event)
        self._subs.add(sub)

        async def events() -> AsyncIterator[Event]:
            while True:
                if not sub.items:
                    sub.ready.clear()
                    await sub.ready.wait()
                while sub.items:
                    yield sub.items.popleft()

        try:
            yield events()
        finally:
            self._subs.discard(sub)
