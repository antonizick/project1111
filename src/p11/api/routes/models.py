"""``/api/models`` operations (Phase 14): the Models page's plan, install, verify, add and remove.

Reads (``GET /api/models``) stay in ``system.py``. Install runs in a worker thread and publishes
``models`` events (operation id, state, label, bytes done/total) on the Studio's event stream, so
the page shows real download progress without holding an HTTP request open. One model operation
runs at a time: the manager writes shared state files.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from p11.api.studio import Studio
from p11.models.download import Downloader, DownloadError, SecretsError, load_tokens
from p11.models.formats import FormatError
from p11.models.manifest import ManifestError
from p11.models.registry import LicenceNotAccepted, ModelError, ModelManager
from p11.models.state import now_stamp

from .deps import StudioDep

router = APIRouter(prefix="/api/models", tags=["models"])


class TargetRequest(BaseModel):
    target: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")


class InstallRequest(TargetRequest):
    accept_licences: bool = False


class VerifyRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)


class EnabledRequest(BaseModel):
    enabled: bool


class AddRequest(BaseModel):
    source: str = Field(min_length=1, max_length=2000)
    kind: str | None = None
    model_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    allow_pickle: bool = False
    link: bool = False


class Operation:
    def __init__(self, kind: str, target: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.target = target
        self.state: Literal["running", "done", "failed"] = "running"
        self.label = ""
        self.done = 0
        self.total = 0
        self.error: str | None = None
        self.report: dict[str, Any] | None = None
        self.started_at = now_stamp()
        self.seconds = 0.0
        self._started = time.perf_counter()

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "state": self.state,
            "label": self.label,
            "done": self.done,
            "total": self.total,
            "progress": round(self.done / self.total, 4) if self.total else 0.0,
            "error": self.error,
            "report": self.report,
            "started_at": self.started_at,
            "seconds": round(self.seconds, 1),
        }

    def finish(self) -> None:
        self.seconds = time.perf_counter() - self._started


_OPERATIONS: dict[str, Operation] = {}
_TASKS: set[asyncio.Task[None]] = set()


def _manager(studio: Studio) -> ModelManager:
    return ModelManager(studio.settings.models_root)


def _downloader() -> Downloader:
    """The e2e hook (``P11_ALLOW_LOOPBACK_MANIFEST=1``) also allows http to 127.0.0.1."""
    insecure = ("127.0.0.1",) if os.environ.get("P11_ALLOW_LOOPBACK_MANIFEST") == "1" else ()
    return Downloader(tokens=load_tokens(), insecure_hosts=insecure)


def _fail(exc: BaseException) -> HTTPException:
    if isinstance(exc, LicenceNotAccepted):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ModelError | DownloadError | ManifestError | SecretsError | FormatError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="The model operation failed inside P11.")


def _running() -> Operation | None:
    return next((op for op in _OPERATIONS.values() if op.state == "running"), None)


@router.get("/operations")
async def operations() -> list[dict[str, Any]]:
    return [op.as_json() for op in sorted(_OPERATIONS.values(), key=lambda o: o.started_at)]


@router.post("/plan")
async def plan(body: TargetRequest, studio: StudioDep) -> dict[str, Any]:
    """What an install would fetch and which licences need accepting (for the dialog)."""
    manager = _manager(studio)
    try:
        found = await asyncio.to_thread(manager.plan, body.target)
    except BaseException as exc:  # ModelError and friends, mapped to plain English
        raise _fail(exc) from None
    return {
        "target": body.target,
        "models": [e.id for e in found.entries],
        "to_fetch": [e.id for e in found.to_fetch],
        "licences_to_accept": [
            {
                "id": e.id,
                "name": e.name,
                "licence": e.licence.name,
                "url": e.licence.url,
                "commercial_use": e.licence.commercial_use,
                "flags": list(e.licence.flags),
            }
            for e in found.to_accept
        ],
        "total_bytes": sum(e.size for e in found.entries),
        "download_bytes": found.download_bytes,
    }


@router.post("/install", status_code=202)
async def install(body: InstallRequest, studio: StudioDep) -> dict[str, Any]:
    running = _running()
    if running is not None:
        raise HTTPException(
            status_code=409, detail=f"{running.target} is still {running.state}. Wait for it."
        )
    manager = _manager(studio)
    try:
        await asyncio.to_thread(manager.plan, body.target)
    except BaseException as exc:
        raise _fail(exc) from None
    op = Operation("install", body.target)
    _OPERATIONS[op.id] = op
    for old in sorted(_OPERATIONS.values(), key=lambda o: o.started_at)[:-20]:
        if old.state != "running":
            _OPERATIONS.pop(old.id, None)
    loop = asyncio.get_running_loop()

    def update(label: str, done: int, total: int) -> None:
        op.label, op.done, op.total = label, done, total
        studio.bus.publish("models", op.as_json())

    def progress(label: str, done: int, total: int) -> None:
        loop.call_soon_threadsafe(update, label, done, total)

    def work() -> Any:
        with _downloader() as downloader:
            return manager.install(
                body.target,
                downloader=downloader,
                accept_licences=body.accept_licences,
                progress=progress,
            )

    async def run() -> None:
        try:
            report = await asyncio.to_thread(work)
        except BaseException as exc:
            op.state = "failed"
            op.error = str(exc)
        else:
            op.state = "done"
            op.report = report.as_json()
            studio.bus.publish("models-changed", {"target": body.target, "installed": True})
        op.finish()
        studio.bus.publish("models", op.as_json())

    task = asyncio.create_task(run(), name=f"p11-models-{op.id}")
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return op.as_json()


@router.post("/verify")
async def verify(body: VerifyRequest, studio: StudioDep) -> dict[str, Any]:
    manager = _manager(studio)
    try:
        rows = await asyncio.to_thread(manager.verify, body.ids)
    except BaseException as exc:
        raise _fail(exc) from None
    return {
        "ok": all(s.state not in ("corrupt", "missing") for s in rows),
        "models": [s.as_json() for s in rows],
    }


@router.post("/{model_id}/enabled")
async def set_enabled(model_id: str, body: EnabledRequest, studio: StudioDep) -> dict[str, Any]:
    manager = _manager(studio)
    try:
        await asyncio.to_thread(manager.set_enabled, model_id, body.enabled)
    except BaseException as exc:
        raise _fail(exc) from None
    studio.bus.publish("models-changed", {"id": model_id, "enabled": body.enabled})
    return {"id": model_id, "enabled": body.enabled}


@router.delete("/{model_id}")
async def remove(
    model_id: str,
    studio: StudioDep,
    delete_file: bool = Query(False, description="For a user model: also delete its file."),
) -> dict[str, Any]:
    manager = _manager(studio)
    try:
        message = await asyncio.to_thread(manager.remove, model_id, delete_file=delete_file)
    except BaseException as exc:
        raise _fail(exc) from None
    studio.bus.publish("models-changed", {"id": model_id, "removed": True})
    return {"id": model_id, "message": message}


@router.post("/add", status_code=201)
async def add(body: AddRequest, studio: StudioDep) -> dict[str, Any]:
    manager = _manager(studio)

    def work() -> Any:
        with _downloader() as downloader:
            return manager.add(
                body.source,
                kind=body.kind,
                model_id=body.model_id,
                allow_pickle=body.allow_pickle,
                link=body.link,
                downloader=downloader,
            )

    try:
        status = await asyncio.to_thread(work)
    except BaseException as exc:
        raise _fail(exc) from None
    studio.bus.publish("models-changed", {"id": status.id, "added": True})
    return dict(status.as_json())


@router.get("/licences")
async def licences(studio: StudioDep) -> dict[str, Any]:
    manager = _manager(studio)
    accepted = await asyncio.to_thread(lambda: manager.licences.all())
    rows = []
    for entry in manager.manifest:
        ack = accepted.get(entry.id)
        rows.append(
            {
                "id": entry.id,
                "name": entry.name,
                "licence": entry.licence.name,
                "url": entry.licence.url,
                "commercial_use": entry.licence.commercial_use,
                "flags": list(entry.licence.flags),
                "needs_acknowledgement": entry.licence.needs_acknowledgement,
                "accepted_at": ack.accepted_at
                if ack and ack.licence == entry.licence.name
                else None,
            }
        )
    return {"licences": rows}
