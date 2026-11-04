"""``ComfyEngine``: the pinned headless ComfyUI behind the ``Engine`` protocol (ADR-0002).

Every ComfyUI endpoint and message shape P11 relies on lives in this module. They were read from
the pinned source (ComfyUI v0.43.0 ``426f5ee``: ``server.py``, ``execution.py``, ``main.py``,
``protocol.py``, ``comfy/model_management.py``) on 2026-11-02 18:40 CST, and ``start()`` refuses
an engine whose reported version differs from ``engine/engine.lock.toml``.

Endpoints: ``GET /object_info``; ``POST /prompt`` {prompt, client_id, prompt_id} → {prompt_id,
number, node_errors} or 400 {error, node_errors}; ``GET /ws?clientId=`` (JSON {type, data} text
frames, binary previews);
``GET /history/{id}``; ``GET /view?filename&subfolder&type``; ``POST /upload/image`` (multipart
``image``, ``type``, ``subfolder``, ``overwrite``); ``POST /interrupt`` {prompt_id};
``POST /free`` {unload_models, free_memory}; ``POST /history`` {delete}; ``GET /system_stats``.
Websocket messages: ``status``, ``execution_start``, ``execution_cached``, ``executing`` {node,
prompt_id} (node ``None`` = done), ``progress`` {value, max, node, prompt_id}, ``executed``
{node, output, prompt_id}, ``execution_success``, ``execution_error`` {node_id, node_type,
exception_type, exception_message}, ``execution_interrupted`` {node_id}.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from p11 import paths
from p11.config import Settings, load_settings
from p11.engine.base import (
    DeviceStats,
    EngineCrashed,
    EngineError,
    EngineExecutionError,
    EngineFileRef,
    EngineHealth,
    EngineInterrupted,
    EngineOOM,
    EngineTimeout,
    EngineUnavailable,
    EngineValidation,
    EventCallback,
    Executed,
    Executing,
    OutputImage,
    Preview,
    Progress,
    Queued,
    RunResult,
    SystemStats,
    UploadKind,
    VramMode,
    emit,
    graph_nodes,
    is_oom_message,
    node_titles,
    stamp_output_prefixes,
    upload_name,
)
from p11.engine.lockfile import EngineLock, load_lock
from p11.engine.process import ProcessSpec, ProcessSupervisor
from p11.recipe.compile import EngineGraph

log = logging.getLogger(__name__)

#: Extra launch flags per VRAM mode, checked in comfy/cli_args.py at the pin (ADR-0018).
VRAM_FLAGS: dict[VramMode, tuple[str, ...]] = {
    "dynamic": (),
    "lowvram": ("--disable-dynamic-vram", "--lowvram"),
}

#: Environment for the engine: no hub or telemetry calls (S1).
ENGINE_ENV = {
    "PYTHONUNBUFFERED": "1",
    "HF_HUB_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "DO_NOT_TRACK": "1",
    "COMFYUI_DISABLE_PRODUCT_TIPS": "1",
}

_BIN_PREVIEW = 1
_BIN_PREVIEW_WITH_METADATA = 4
_OOM_LOG_MARKERS = ("Got an OOM", "out of memory", "OutOfMemoryError")


@dataclass(frozen=True)
class EngineConfig:
    """Where the engine lives and how it is launched. ``default()`` derives it from P11's paths."""

    engine_dir: Path
    scratch_dir: Path
    log_path: Path
    pid_path: Path
    lock: EngineLock
    port: int = 8188
    lock_path: Path | None = None
    lock_timeout: float = 30.0
    ready_timeout: float = 180.0
    stop_timeout: float = 30.0
    #: Hard run timeout when ``run`` is not given one (5x the cold first image, ADR-0018).
    run_timeout: float = 300.0
    #: Seconds to let ``/free`` take effect (the worker handles the flag between prompts).
    free_settle: float = 1.0
    keep_outputs: bool = False
    extra_args: tuple[str, ...] = ()

    @classmethod
    def default(cls, settings: Settings | None = None, **overrides: Any) -> EngineConfig:
        settings = settings or load_settings()
        p = paths.resolve()
        cfg = cls(
            engine_dir=p.engine,
            scratch_dir=p.cache / "engine",
            log_path=p.cache / "logs" / "engine.log",
            pid_path=p.cache / "engine.pid",
            lock=load_lock(),
            port=settings.engine_port,
            lock_path=p.gpu_lock,
        )
        return replace(cfg, **overrides)

    @property
    def python(self) -> Path:
        return self.engine_dir / "venv" / "bin" / "python"

    @property
    def comfy_dir(self) -> Path:
        return self.engine_dir / "ComfyUI"

    @property
    def output_dir(self) -> Path:
        return self.scratch_dir / "out"

    def command(self, vram_mode: VramMode) -> list[str]:
        d = self.scratch_dir
        return [
            str(self.python),
            "main.py",
            "--listen",
            self.lock.listen,
            "--port",
            str(self.port),
            *self.lock.flags,
            "--extra-model-paths-config",
            str(self.engine_dir / "extra_model_paths.yaml"),
            "--output-directory",
            str(d / "out"),
            "--input-directory",
            str(d / "in"),
            "--temp-directory",
            str(d / "tmp"),
            "--user-directory",
            str(d / "user"),
            "--database-url",
            f"sqlite:///{d / 'user' / 'comfyui.db'}",
            *VRAM_FLAGS[vram_mode],
            *self.extra_args,
        ]


@dataclass
class _RunState:
    prompt_id: str
    titles: dict[str, str]
    on_event: EventCallback | None
    t0: float
    node_started: dict[str, float] = field(default_factory=dict)
    node_seconds: dict[str, float] = field(default_factory=dict)
    current: str | None = None

    def enter(self, node: str | None, now: float) -> None:
        if self.current is not None:
            self.node_seconds[self.current] = now - self.node_started[self.current]
        self.current = node
        if node is not None:
            self.node_started.setdefault(node, now)


class ComfyEngine:
    """Supervises the pinned ComfyUI process and speaks its HTTP + websocket API."""

    def __init__(self, config: EngineConfig | None = None, vram_mode: VramMode = "dynamic") -> None:
        self.config = config or EngineConfig.default()
        self._vram_mode: VramMode = vram_mode
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        self._client_id = uuid.uuid4().hex
        self._current: str | None = None
        self._version: str | None = None
        self._run_lock = asyncio.Lock()
        self.supervisor = ProcessSupervisor(self._spec(), self._ready)

    # -- properties --------------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return f"http://{self.config.lock.listen}:{self.config.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.config.lock.listen}:{self.config.port}/ws?clientId={self._client_id}"

    @property
    def vram_mode(self) -> VramMode:
        return self._vram_mode

    def _spec(self) -> ProcessSpec:
        c = self.config
        return ProcessSpec(
            command=c.command(self._vram_mode),
            cwd=c.comfy_dir,
            port=c.port,
            host=c.lock.listen,
            log_path=c.log_path,
            pid_path=c.pid_path,
            env=dict(ENGINE_ENV),
            lock_path=c.lock_path,
            lock_timeout=c.lock_timeout,
            lock_holder=f"p11 engine (ComfyUI {c.lock.tag}, {self._vram_mode})",
            ready_timeout=c.ready_timeout,
            stop_timeout=c.stop_timeout,
        )

    # -- lifecycle ---------------------------------------------------------------------------

    async def start(self) -> None:
        if not self.config.python.exists():
            raise EngineUnavailable(
                f"The engine is not installed ({self.config.python} is missing). "
                "Run scripts/engine_setup.sh (or ./install.sh)."
            )
        for sub in ("out", "in", "tmp", "user"):
            paths.ensure_private_dir(self.config.scratch_dir / sub)
        await self.supervisor.start()
        await self._check_version()

    async def stop(self) -> None:
        await self.supervisor.stop()
        self._version = None

    async def aclose(self) -> None:
        await self.stop()
        await self._http.aclose()

    async def restart(self, vram_mode: VramMode | None = None) -> None:
        if vram_mode is not None:
            self._vram_mode = vram_mode
        self.supervisor.spec = self._spec()
        await self.supervisor.restart()
        await self._check_version()

    async def _ready(self) -> bool:
        r = await self._http.get("/system_stats", timeout=2.0)
        return r.status_code == 200

    async def _check_version(self) -> None:
        stats = await self.system_stats()
        want = self.config.lock.version
        if stats.version != want:
            await self.stop()
            raise EngineUnavailable(
                f"The engine reports ComfyUI {stats.version}, but P11 is pinned to {want} "
                f"({self.config.lock.path}). Re-run scripts/engine_setup.sh."
            )
        argv = list(stats.argv)
        if "--listen" in argv and argv[argv.index("--listen") + 1] != "127.0.0.1":
            await self.stop()
            raise EngineUnavailable("The engine is not bound to 127.0.0.1 (spec S1); refusing it.")
        self._version = stats.version

    async def health(self) -> EngineHealth:
        sup = self.supervisor
        state = sup.state
        if state == "ready":
            try:
                ok = await self._ready()
            except httpx.HTTPError:
                ok = False
            if not ok:  # not answering: unusable, whatever the supervisor has noticed so far
                state = "crashed"
        return EngineHealth(
            state=state,
            vram_mode=self._vram_mode,
            port=self.config.port,
            pid=sup.pid,
            version=self._version,
            restarts=sup.restarts,
            last_error=sup.last_error,
        )

    def _require_ready(self) -> None:
        sup = self.supervisor
        if sup.state == "crashed":
            sup.raise_if_dead()
        if sup.state != "ready":
            raise EngineUnavailable(
                f"The engine is {sup.state}. Start it first (P11 starts it on demand)."
            )

    # -- requests ----------------------------------------------------------------------------

    async def system_stats(self) -> SystemStats:
        try:
            r = await self._http.get("/system_stats")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"The engine did not answer /system_stats: {exc}") from exc
        return parse_system_stats(r.json())

    async def node_types(self) -> frozenset[str]:
        """Node class names the running engine knows (``GET /object_info``)."""
        self._require_ready()
        r = await self._http.get("/object_info", timeout=60.0)
        r.raise_for_status()
        return frozenset(r.json())

    async def upload(self, image: Path | bytes, kind: UploadKind = "image") -> EngineFileRef:
        self._require_ready()
        data = image.read_bytes() if isinstance(image, Path) else image
        name, mime = upload_name(data, kind)
        try:
            r = await self._http.post(
                "/upload/image",
                files={"image": (name, data, mime)},
                data={"type": "input", "overwrite": "true"},
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"Upload to the engine failed: {exc}") from exc
        if r.status_code != 200:
            raise EngineValidation(None, f"upload refused with HTTP {r.status_code}")
        body = r.json()
        return EngineFileRef(
            name=str(body["name"]),
            subfolder=str(body.get("subfolder", "")),
            type=str(body.get("type", "input")),
        )

    async def interrupt(self) -> None:
        body = {"prompt_id": self._current} if self._current else {}
        with contextlib.suppress(httpx.HTTPError):
            await self._http.post("/interrupt", json=body, timeout=5.0)

    async def free_memory(self, unload_models: bool = True) -> None:
        self._require_ready()
        try:
            await self._http.post(
                "/free", json={"unload_models": unload_models, "free_memory": True}
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"The engine did not accept /free: {exc}") from exc
        await asyncio.sleep(self.config.free_settle)

    # -- run ---------------------------------------------------------------------------------

    async def run(
        self,
        graph: EngineGraph | Mapping[str, Any],
        *,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        nodes = graph_nodes(graph)
        async with self._run_lock:
            self._require_ready()
            return await self._run(nodes, on_event, timeout or self.config.run_timeout)

    async def _run(
        self, nodes: dict[str, dict[str, Any]], on_event: EventCallback | None, timeout: float
    ) -> RunResult:
        prompt_id = str(uuid.uuid4())
        nodes = stamp_output_prefixes(nodes, prompt_id[:8])
        log_offset = _file_size(self.config.log_path)
        try:
            ws = await connect(self.ws_url, max_size=None, open_timeout=10, ping_interval=None)
        except (OSError, InvalidHandshake, TimeoutError) as exc:
            raise await self._connection_error(exc) from exc
        try:
            t0 = time.monotonic()
            await self._queue(nodes, prompt_id)
            self._current = prompt_id
            state = _RunState(prompt_id, node_titles(nodes), on_event, t0)
            await emit(on_event, Queued(prompt_id))
            try:
                async with asyncio.timeout(timeout):
                    await self._follow(ws, state, log_offset)
            except TimeoutError:
                await self.interrupt()
                raise EngineTimeout(
                    f"The job took longer than {timeout:g} s and was stopped. "
                    "Try a faster preset or the Fast model."
                ) from None
            except ConnectionClosed as exc:
                raise await self._connection_error(exc) from exc
            seconds = time.monotonic() - t0
        finally:
            self._current = None
            await ws.close()
        t1 = time.monotonic()
        images = await self._fetch_outputs(prompt_id)
        return RunResult(
            prompt_id=prompt_id,
            images=images,
            seconds=seconds,
            fetch_seconds=time.monotonic() - t1,
            node_seconds=state.node_seconds,
            vram_mode=self._vram_mode,
        )

    async def _queue(self, nodes: dict[str, dict[str, Any]], prompt_id: str) -> None:
        payload = {"prompt": nodes, "client_id": self._client_id, "prompt_id": prompt_id}
        try:
            r = await self._http.post("/prompt", json=payload)
        except httpx.HTTPError as exc:
            raise await self._connection_error(exc) from exc
        if r.status_code != 200:
            node, detail = parse_prompt_error(r.json() if r.content else {})
            raise EngineValidation(node, detail)

    async def _follow(self, ws: ClientConnection, st: _RunState, log_offset: int) -> None:
        async for raw in ws:
            now = time.monotonic()
            if isinstance(raw, bytes):
                preview = parse_preview(raw, st.prompt_id)
                if preview is not None:
                    await emit(st.on_event, preview)
                continue
            msg = json.loads(raw)
            typ, data = msg.get("type"), msg.get("data") or {}
            if data.get("prompt_id") != st.prompt_id:
                continue
            if typ == "executing":
                node = data.get("node")
                st.enter(node, now)
                if node is None:
                    return
                await emit(st.on_event, Executing(str(node), st.titles.get(str(node))))
            elif typ == "progress":
                node = str(data.get("node"))
                await emit(
                    st.on_event,
                    Progress(int(data["value"]), int(data["max"]), node, st.titles.get(node)),
                )
            elif typ == "executed":
                await emit(st.on_event, Executed(str(data["node"]), data.get("output") or {}))
            elif typ == "execution_success":
                st.enter(None, now)
                return
            elif typ == "execution_interrupted":
                raise EngineInterrupted("The job was cancelled.")
            elif typ == "execution_error":
                raise self._execution_error(data, log_offset)

    def _execution_error(self, data: Mapping[str, Any], log_offset: int) -> EngineError:
        node = str(data.get("node_id")) if data.get("node_id") is not None else None
        etype = str(data.get("exception_type", "Exception"))
        message = str(data.get("exception_message", "")).strip()
        log_tail = _read_from(self.config.log_path, log_offset)
        if is_oom_message(etype, message) or any(m in log_tail for m in _OOM_LOG_MARKERS):
            return EngineOOM(
                f"Out of GPU memory in node {node} ({data.get('node_type')}). "
                "Try a smaller preset or the low-memory mode."
            )
        return EngineExecutionError(node, etype, message.splitlines()[0] if message else "")

    async def _connection_error(self, exc: BaseException) -> EngineError:
        """Map a lost connection to ``EngineCrashed`` if the process died, else unavailable."""
        sup = self.supervisor
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(sup.exited.wait(), 3.0)
        if sup.exited.is_set() or sup.state == "crashed" or not sup.running:
            return EngineCrashed(
                "The engine stopped while running the job. P11 restarts it once; "
                f"see {self.config.log_path}."
            )
        return EngineUnavailable(f"Lost the connection to the engine: {exc}")

    async def _fetch_outputs(self, prompt_id: str) -> tuple[OutputImage, ...]:
        r = await self._http.get(f"/history/{prompt_id}")
        r.raise_for_status()
        entry = r.json().get(prompt_id, {})
        images: list[OutputImage] = []
        for node, out in (entry.get("outputs") or {}).items():
            for img in out.get("images", []):
                if img.get("type", "output") != "output":
                    continue
                params = {
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": "output",
                }
                v = await self._http.get("/view", params=params)
                v.raise_for_status()
                images.append(
                    OutputImage(
                        node=str(node),
                        filename=str(img["filename"]),
                        subfolder=str(img.get("subfolder", "")),
                        data=v.content,
                    )
                )
                if not self.config.keep_outputs:
                    self._delete_output(params["subfolder"], params["filename"])
        with contextlib.suppress(httpx.HTTPError):
            await self._http.post("/history", json={"delete": [prompt_id]})
        return tuple(images)

    def _delete_output(self, subfolder: str, filename: str) -> None:
        """Engine outputs are scratch (S6): P11 writes its own copy under ~/Pictures/P11."""
        root = self.config.output_dir.resolve()
        target = (root / subfolder / filename).resolve()
        if target.is_relative_to(root):
            target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------------------------
# Pure parsers (unit-tested without an engine).


def parse_system_stats(body: Mapping[str, Any]) -> SystemStats:
    system = body.get("system", {})
    devices = tuple(
        DeviceStats(
            name=str(d.get("name", "")),
            type=str(d.get("type", "")),
            vram_total=int(d.get("vram_total", 0)),
            vram_free=int(d.get("vram_free", 0)),
            torch_vram_total=int(d.get("torch_vram_total", 0)),
            torch_vram_free=int(d.get("torch_vram_free", 0)),
        )
        for d in body.get("devices", [])
    )
    return SystemStats(
        version=str(system.get("comfyui_version", "")),
        python_version=str(system.get("python_version", "")),
        pytorch_version=str(system.get("pytorch_version", "")),
        ram_total=int(system.get("ram_total", 0)),
        ram_free=int(system.get("ram_free", 0)),
        devices=devices,
        argv=tuple(str(a) for a in system.get("argv", [])),
    )


def parse_prompt_error(body: Mapping[str, Any]) -> tuple[str | None, str]:
    """``(node, detail)`` from a 400 ``/prompt`` body ({error, node_errors})."""
    node_errors = body.get("node_errors") or {}
    for node, info in node_errors.items():
        errs = info.get("errors") or []
        if errs:
            e = errs[0]
            detail = f"{info.get('class_type', '')}: {e.get('message', '')}"
            extra = e.get("details")
            return str(node), f"{detail} ({extra})" if extra else detail
    err = body.get("error") or {}
    if isinstance(err, Mapping):
        msg = str(err.get("message", "invalid prompt"))
        details = err.get("details")
        return None, f"{msg} ({details})" if details and details != msg else msg
    return None, str(err) or "invalid prompt"


def parse_preview(frame: bytes, prompt_id: str) -> Preview | None:
    """Binary websocket frame → ``Preview`` (types 1 and 4 in ComfyUI's ``protocol.py``)."""
    if len(frame) < 8:
        return None
    (event,) = struct.unpack(">I", frame[:4])
    if event == _BIN_PREVIEW:
        (fmt,) = struct.unpack(">I", frame[4:8])
        return Preview(frame[8:], "image/png" if fmt == 2 else "image/jpeg")
    if event == _BIN_PREVIEW_WITH_METADATA:
        (n,) = struct.unpack(">I", frame[4:8])
        try:
            meta = json.loads(frame[8 : 8 + n])
        except ValueError:
            return None
        if meta.get("prompt_id") not in (None, prompt_id):
            return None
        return Preview(frame[8 + n :], str(meta.get("image_type", "image/jpeg")))
    return None


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_from(path: Path, offset: int, limit: int = 256 * 1024) -> str:
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read(limit).decode(errors="replace")
    except OSError:
        return ""
