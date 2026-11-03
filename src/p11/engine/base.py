"""The ``Engine`` protocol: the only way P11 talks to the image engine (spec A2, ADR-0002).

Two implementations: ``p11.engine.comfy.ComfyEngine`` (the pinned headless ComfyUI) and
``p11.engine.fake.FakeEngine`` (tests and ``p11 serve --fake``). Both raise the typed errors below,
emit the same ``EngineEvent`` sequence and return a ``RunResult``.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from PIL import Image

from p11.recipe.compile import EngineGraph

#: ComfyUI VRAM modes P11 uses (ADR-0018): dynamic VRAM by default, ``lowvram`` as the OOM retry.
VramMode = Literal["dynamic", "lowvram"]
EngineState = Literal["stopped", "starting", "ready", "crashed"]
UploadKind = Literal["image", "mask"]

PLACEHOLDER_PREFIX = "p11:"


# ---------------------------------------------------------------------------------------------
# Errors. Every message is plain English with a hint (shared instructions §3).


class EngineError(RuntimeError):
    """Base class for engine failures."""

    kind = "error"


class EngineUnavailable(EngineError):
    """The engine is not running, not reachable, or refused to start."""

    kind = "unavailable"


class EngineOOM(EngineError):
    """The GPU ran out of memory (after the retry, when raised by ``run_with_oom_retry``)."""

    kind = "oom"


class EngineValidation(EngineError):
    """The engine rejected the graph before running it."""

    kind = "validation"

    def __init__(self, node: str | None, detail: str) -> None:
        self.node = node
        self.detail = detail
        where = f" (node {node})" if node else ""
        super().__init__(f"The engine rejected the job{where}: {detail}")


class EngineExecutionError(EngineError):
    """A node failed while running, for a reason other than memory."""

    kind = "execution"

    def __init__(self, node: str | None, exception_type: str, detail: str) -> None:
        self.node = node
        self.exception_type = exception_type
        self.detail = detail
        where = f" in node {node}" if node else ""
        super().__init__(f"The engine failed{where}: {exception_type}: {detail}")


class EngineInterrupted(EngineError):
    """The run was cancelled with ``interrupt()``."""

    kind = "interrupted"


class EngineCrashed(EngineError):
    """The engine process died. The supervisor restarts it once; the job is not retried."""

    kind = "crashed"


class EngineTimeout(EngineError):
    """The run exceeded its hard timeout and was interrupted."""

    kind = "timeout"


# ---------------------------------------------------------------------------------------------
# Events emitted during ``run``.


@dataclass(frozen=True)
class Queued:
    prompt_id: str
    type: Literal["queued"] = "queued"


@dataclass(frozen=True)
class Executing:
    node: str
    title: str | None = None
    type: Literal["executing"] = "executing"


@dataclass(frozen=True)
class Progress:
    step: int
    total: int
    node: str
    #: ``_meta.title`` of the node (the compiler titles samplers ``base`` / ``hires``).
    title: str | None = None
    type: Literal["progress"] = "progress"


@dataclass(frozen=True)
class Preview:
    data: bytes
    mime: str = "image/jpeg"
    type: Literal["preview"] = "preview"


@dataclass(frozen=True)
class Executed:
    node: str
    outputs: Mapping[str, Any]
    type: Literal["executed"] = "executed"


@dataclass(frozen=True)
class ErrorEvent:
    kind: str
    message: str
    type: Literal["error"] = "error"


@dataclass(frozen=True)
class Retrying:
    """Emitted by ``run_with_oom_retry`` before the low-memory retry."""

    reason: str
    vram_mode: VramMode
    type: Literal["retrying"] = "retrying"


EngineEvent = Queued | Executing | Progress | Preview | Executed | ErrorEvent | Retrying
EventCallback = Callable[[EngineEvent], Awaitable[None] | None]


# ---------------------------------------------------------------------------------------------
# Values.


@dataclass(frozen=True)
class EngineFileRef:
    """An uploaded file, by the name a ``LoadImage`` node takes."""

    name: str
    subfolder: str = ""
    type: str = "input"

    @property
    def node_value(self) -> str:
        return f"{self.subfolder}/{self.name}" if self.subfolder else self.name


@dataclass(frozen=True)
class OutputImage:
    node: str
    filename: str
    data: bytes
    subfolder: str = ""
    type: str = "output"


@dataclass(frozen=True)
class RunResult:
    prompt_id: str
    images: tuple[OutputImage, ...]
    #: Wall clock from queueing to the engine reporting success (as in docs/P11_BENCHMARKS.md).
    seconds: float
    #: Time spent fetching outputs after success.
    fetch_seconds: float = 0.0
    node_seconds: Mapping[str, float] = field(default_factory=dict)
    vram_mode: VramMode = "dynamic"
    retried: bool = False


@dataclass(frozen=True)
class DeviceStats:
    name: str
    type: str
    vram_total: int
    vram_free: int
    torch_vram_total: int
    torch_vram_free: int


@dataclass(frozen=True)
class SystemStats:
    version: str
    python_version: str
    pytorch_version: str
    ram_total: int
    ram_free: int
    devices: tuple[DeviceStats, ...]
    argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineHealth:
    state: EngineState
    vram_mode: VramMode
    port: int | None = None
    pid: int | None = None
    version: str | None = None
    restarts: int = 0
    last_error: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"


# ---------------------------------------------------------------------------------------------
# Protocol.


@runtime_checkable
class Engine(Protocol):
    @property
    def vram_mode(self) -> VramMode: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def restart(self, vram_mode: VramMode | None = None) -> None: ...

    async def health(self) -> EngineHealth: ...

    async def upload(self, image: Path | bytes, kind: UploadKind = "image") -> EngineFileRef: ...

    async def run(
        self,
        graph: EngineGraph | Mapping[str, Any],
        *,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> RunResult: ...

    async def interrupt(self) -> None: ...

    async def free_memory(self, unload_models: bool = True) -> None: ...

    async def system_stats(self) -> SystemStats: ...


# ---------------------------------------------------------------------------------------------
# Helpers shared by both implementations.


def graph_nodes(graph: EngineGraph | Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """API-format nodes of ``graph``; refuses ``LoadImage`` placeholders that were not bound."""
    nodes = dict(graph.nodes) if isinstance(graph, EngineGraph) else dict(graph)
    for node_id, node in nodes.items():
        if not isinstance(node, Mapping) or "class_type" not in node:
            raise EngineValidation(node_id, "not an API-format node (missing class_type)")
        for name, value in node.get("inputs", {}).items():
            if isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIX):
                raise EngineValidation(
                    node_id,
                    f"input {name!r} is still the placeholder {value!r}; upload the image and "
                    "bind it with bind_inputs() before running",
                )
    return nodes


def bind_inputs(graph: EngineGraph, files: Mapping[str, EngineFileRef]) -> dict[str, Any]:
    """Return ``graph``'s nodes with each ``GraphInput`` placeholder replaced by its upload.

    ``files`` maps a placeholder (``p11:slot:<name>``, ``p11:step:<i>``, ``p11:source``) to the
    ``EngineFileRef`` returned by ``Engine.upload``.
    """
    nodes = {k: {**v, "inputs": dict(v.get("inputs", {}))} for k, v in graph.nodes.items()}
    for inp in graph.inputs:
        ref = files.get(inp.placeholder)
        if ref is None:
            raise EngineValidation(inp.node_id, f"no upload bound for {inp.placeholder!r}")
        nodes[inp.node_id]["inputs"]["image"] = ref.node_value
    return nodes


def node_titles(nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {
        k: str(v["_meta"]["title"])
        for k, v in nodes.items()
        if isinstance(v.get("_meta"), Mapping) and "title" in v["_meta"]
    }


async def emit(callback: EventCallback | None, event: EngineEvent) -> None:
    if callback is None:
        return
    result = callback(event)
    if result is not None:
        await result


def is_oom_message(exception_type: str, message: str) -> bool:
    """ComfyUI's ``is_oom`` (comfy/model_management.py at the pin), seen from the outside."""
    text = f"{exception_type} {message}".lower()
    return "outofmemory" in text or "out of memory" in text


def upload_name(data: bytes, kind: UploadKind) -> tuple[str, str]:
    """Content-addressed upload name (no user file names reach the engine, S6) and MIME type."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "PNG").upper()
    except OSError as exc:
        raise EngineValidation(None, "the upload is not a readable image") from exc
    ext, mime = {"JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}.get(
        fmt, ("png", "image/png")
    )
    digest = hashlib.sha256(data).hexdigest()[:20]
    return f"p11-{kind}-{digest}.{ext}", mime
