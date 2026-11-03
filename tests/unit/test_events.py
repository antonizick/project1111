"""Event bus ordering and replay, and the SSE stream over a real uvicorn server."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from tests.studio import generate_recipe

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.fake import FakeConfig, FakeEngine
from p11.jobs import events as events_mod
from p11.jobs.events import EventBus


async def _take(it, n):  # type: ignore[no-untyped-def]
    return [await anext(it) for _ in range(n)]


async def test_bus_orders_and_replays():
    bus = EventBus()
    async with bus.subscribe() as stream:
        for i in range(5):
            bus.publish("job", {"i": i})
        got = await asyncio.wait_for(_take(stream, 5), 1)
    assert [e.id for e in got] == [1, 2, 3, 4, 5]
    assert [e.data["i"] for e in got] == [0, 1, 2, 3, 4]
    bus.publish("preview", {"data": "x"})
    bus.publish("job", {"i": 5})
    async with bus.subscribe(last_id=3) as stream:
        replay = await asyncio.wait_for(_take(stream, 3), 1)
    assert [e.id for e in replay] == [4, 5, 7]  # previews are not replayed
    assert bus.subscribers == 0 and bus.last_id == 7


async def test_slow_subscriber_drops_transient_events_first(monkeypatch):
    monkeypatch.setattr(events_mod, "QUEUE", 4)
    bus = EventBus()
    async with bus.subscribe() as stream:
        bus.publish("job", {"n": 1})
        for _ in range(5):
            bus.publish("gpu", {})
        bus.publish("job", {"n": 2})
        got = await asyncio.wait_for(_take(stream, 4), 1)
    assert [e.type for e in got].count("job") == 2
    assert [e.id for e in got] == sorted(e.id for e in got)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live(tmp_path) -> Iterator[tuple[str, Session]]:  # type: ignore[no-untyped-def]
    port = _free_port()
    session = Session()
    app = create_app(
        web_dir=tmp_path / "none",
        engine=FakeEngine(FakeConfig(step_delay=0.01)),
        settings=load_settings(outputs_root=tmp_path / "pictures"),
        session=session,
        port=port,
        studio_paths=StudioPaths.sandbox(tmp_path),
        sampler=None,
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}", session
    finally:
        server.should_exit = True
        thread.join(10)


def _events(response: httpx.Response, until: str, limit: int = 400) -> list[tuple[str, int, dict]]:
    out: list[tuple[str, int, dict]] = []
    event, eid, data = "message", -1, ""
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("id:"):
            eid = int(line[3:].strip())
        elif line.startswith("data:"):
            data += line[5:].strip()
        elif line == "" and data:
            out.append((event, eid, json.loads(data)))
            if until in json.dumps(out[-1][2]) or len(out) >= limit:
                break
            event, data = "message", ""
    return out


def test_sse_stream_orders_job_events(live):
    base, session = live
    auth = {"authorization": f"Bearer {session.token}"}
    with httpx.Client(base_url=base, headers=auth, timeout=20) as client:
        with client.stream("GET", "/api/events") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert "content-security-policy" in r.headers
            job = client.post("/api/jobs", json={"recipe": generate_recipe()}).json()
            got = _events(r, until='"done"')
        kinds = [k for k, _, _ in got]
        assert kinds[0] == "hello"
        ids = [i for _, i, _ in got[1:]]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        states = [d["state"] for k, _, d in got if k == "job" and d["id"] == job["id"]]
        assert states[0] == "queued" and states[-1] == "done" and "running" in states
        steps = [d["step"] for k, _, d in got if k == "progress" and "step" in d]
        assert steps == sorted(steps) and steps
        image = next(d for k, _, d in got if k == "image")
        assert image["job"] == job["id"] and image["image"]["url"].startswith("/api/images/")
        assert kinds.index("image") < len(kinds) - 1  # the image comes before the final state
        # resume after the image event: only later events come back
        image_id = next(i for k, i, _ in got if k == "image")
        with client.stream("GET", "/api/events", headers={"last-event-id": str(image_id)}) as r2:
            again = _events(r2, until='"done"')
        assert again[0][0] == "job" and all(i > image_id for _, i, _ in again)


def test_sse_needs_the_token_or_cookie(live):
    base, session = live
    with httpx.Client(base_url=base, timeout=5) as client:
        assert client.get("/api/events").status_code == 401
        with client.stream("GET", "/api/events",
                           headers={"cookie": f"p11_session={session.token}"}) as r:  # fmt: skip
            assert r.status_code == 200
