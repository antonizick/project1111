"""Engine process supervisor: start, readiness, logs, one crash restart, clean stop (spec R14, R24).

Generic over the command so the tests drive it with a dummy subprocess; ``ComfyEngine`` gives it
the pinned ComfyUI command line. The supervisor holds the GPU lock (``p11.gpulock``) for as long
as the process may run and refuses a second instance (pid file + port check).
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import logging
import os
import signal
import socket
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from p11 import paths
from p11.engine.base import EngineCrashed, EngineState, EngineUnavailable
from p11.gpulock import GpuLockTimeout, gpu_lock

log = logging.getLogger(__name__)

ReadyCheck = Callable[[], Awaitable[bool]]

_PR_SET_PDEATHSIG = 1
LOG_ROTATE_BYTES = 10 * 1024 * 1024
LOG_KEEP = 3


@dataclass
class ProcessSpec:
    command: Sequence[str]
    cwd: Path
    port: int
    log_path: Path
    pid_path: Path
    env: dict[str, str] = field(default_factory=dict)
    host: str = "127.0.0.1"
    #: Path of the GPU lock; ``None`` skips the lock (dummy-process tests only).
    lock_path: Path | None = None
    lock_timeout: float = 30.0
    lock_holder: str = "p11 engine"
    ready_timeout: float = 180.0
    stop_timeout: float = 30.0
    #: Unexpected exits the supervisor restarts after (spec R14: once).
    max_restarts: int = 1


def _set_pdeathsig() -> None:  # pragma: no cover - runs in the child between fork and exec
    """Ask Linux to SIGTERM the engine if P11 dies without stopping it (no orphaned engine)."""
    with contextlib.suppress(OSError, AttributeError):
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)


def rotate_log(path: Path, keep: int = LOG_KEEP, max_bytes: int = LOG_ROTATE_BYTES) -> None:
    """Rotate ``path`` → ``path.1`` … ``path.<keep>`` when it is larger than ``max_bytes``."""
    try:
        if path.stat().st_size <= max_bytes:
            return
    except FileNotFoundError:
        return
    for i in range(keep - 1, 0, -1):
        src = path.with_name(f"{path.name}.{i}")
        if src.exists():
            src.replace(path.with_name(f"{path.name}.{i + 1}"))
    path.replace(path.with_name(f"{path.name}.1"))


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid_file(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class ProcessSupervisor:
    def __init__(self, spec: ProcessSpec, ready: ReadyCheck) -> None:
        self.spec = spec
        self._ready = ready
        self._proc: asyncio.subprocess.Process | None = None
        self._monitor: asyncio.Task[None] | None = None
        self._lock: ExitStack | None = None
        self._stopping = False
        self._restart_lock = asyncio.Lock()
        self.state: EngineState = "stopped"
        self.restarts = 0
        self.last_error: str | None = None
        #: Set whenever the process exits, expected or not.
        self.exited = asyncio.Event()
        self.on_crash: Callable[[int | None], None] | None = None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    # -- lifecycle ---------------------------------------------------------------------------

    async def start(self) -> None:
        if self.running:
            return
        self._check_single_instance()
        await self._acquire_lock()
        try:
            await self._spawn()
        except BaseException:
            self._release_lock()
            raise
        self.restarts = 0

    async def stop(self) -> None:
        self._stopping = True
        try:
            if self._monitor:
                self._monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._monitor
                self._monitor = None
            await self._terminate()
        finally:
            self._remove_pid_file()
            self._release_lock()
            self.state = "stopped"
            self._stopping = False

    async def restart(self) -> None:
        """Stop the process (keeping the GPU lock) and start it again."""
        async with self._restart_lock:
            self._stopping = True
            try:
                if self._monitor:
                    self._monitor.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._monitor
                    self._monitor = None
                await self._terminate()
            finally:
                self._stopping = False
            await self._acquire_lock()
            await self._spawn()

    # -- internals ---------------------------------------------------------------------------

    def _check_single_instance(self) -> None:
        info = read_pid_file(self.spec.pid_path)
        if info is not None:
            pid = info.get("pid")
            if isinstance(pid, int) and pid_alive(pid) and _is_same_command(pid, self.spec):
                raise EngineUnavailable(
                    f"The engine is already running (pid {pid}, port {info.get('port')}). "
                    "Stop it first with `p11 stop`."
                )
            self._remove_pid_file()  # stale
        if port_in_use(self.spec.host, self.spec.port):
            raise EngineUnavailable(
                f"Port {self.spec.port} on {self.spec.host} is already in use, so the engine "
                "cannot start. Stop whatever is using it, or set engine_port in "
                "~/.config/p11/config.toml."
            )

    async def _acquire_lock(self) -> None:
        if self.spec.lock_path is None or self._lock is not None:
            return
        stack = ExitStack()
        cm = gpu_lock(self.spec.lock_timeout, self.spec.lock_holder, self.spec.lock_path)
        try:
            await asyncio.to_thread(stack.enter_context, cm)
        except GpuLockTimeout as exc:
            raise EngineUnavailable(f"{exc} Try again when that job has finished.") from exc
        self._lock = stack

    def _release_lock(self) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    @property
    def holds_gpu_lock(self) -> bool:
        return self._lock is not None

    async def _spawn(self) -> None:
        spec = self.spec
        paths.ensure_private_dir(spec.log_path.parent)
        paths.ensure_private_dir(spec.pid_path.parent)
        rotate_log(spec.log_path)
        self.state = "starting"
        self.exited = asyncio.Event()
        # 0600 like the Studio log (S6): engine errors can quote file names and node inputs.
        fd = os.open(spec.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "ab") as logf:
            logf.write(f"\n=== p11: starting engine at {time.strftime('%F %T %Z')} ===\n".encode())
            logf.flush()
            self._proc = await asyncio.create_subprocess_exec(
                *spec.command,
                cwd=spec.cwd,
                env={**os.environ, **spec.env},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=logf,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                preexec_fn=_set_pdeathsig,
            )
        self._write_pid_file()
        try:
            await self._wait_ready()
        except BaseException:
            await self._terminate()
            self._remove_pid_file()
            self.state = "stopped"
            raise
        self.state = "ready"
        self._monitor = asyncio.create_task(self._watch(), name="p11-engine-monitor")

    async def _wait_ready(self) -> None:
        assert self._proc is not None
        deadline = time.monotonic() + self.spec.ready_timeout
        while time.monotonic() < deadline:
            if self._proc.returncode is not None:
                raise EngineUnavailable(
                    f"The engine exited during start-up (code {self._proc.returncode}). "
                    f"See {self.spec.log_path}."
                )
            with contextlib.suppress(Exception):
                if await self._ready():
                    return
            await asyncio.sleep(0.25)
        raise EngineUnavailable(
            f"The engine did not become ready within {self.spec.ready_timeout:g} s. "
            f"See {self.spec.log_path}."
        )

    async def _watch(self) -> None:
        assert self._proc is not None
        code = await self._proc.wait()
        self.exited.set()
        if self._stopping:
            return
        self.last_error = f"engine exited unexpectedly with code {code}"
        log.warning("%s", self.last_error)
        self.state = "crashed"
        if self.on_crash:
            self.on_crash(code)
        if self.restarts >= self.spec.max_restarts:
            self._remove_pid_file()
            self._proc = None
            self._release_lock()  # nothing runs on the GPU any more; let other jobs have it
            return
        self.restarts += 1
        self._monitor = None
        try:
            async with self._restart_lock:
                await self._spawn()
        except EngineUnavailable as exc:
            self.last_error = str(exc)
            self.state = "crashed"

    async def _terminate(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), self.spec.stop_timeout)
            except TimeoutError:
                log.warning(
                    "engine ignored SIGTERM for %ss; sending SIGKILL", self.spec.stop_timeout
                )
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        # Anything left in the session (workers) goes too.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        self.exited.set()
        self._proc = None

    def _write_pid_file(self) -> None:
        assert self._proc is not None
        info = {
            "pid": self._proc.pid,
            "port": self.spec.port,
            "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "command": list(self.spec.command)[:4],
        }
        self.spec.pid_path.write_text(json.dumps(info))
        self.spec.pid_path.chmod(0o600)

    def _remove_pid_file(self) -> None:
        self.spec.pid_path.unlink(missing_ok=True)

    def raise_if_dead(self) -> None:
        if self.state == "crashed" or not self.running:
            raise EngineCrashed(
                "The engine stopped unexpectedly"
                + (f" ({self.last_error})" if self.last_error else "")
                + f". P11 restarts it once; see {self.spec.log_path}."
            )


def _is_same_command(pid: int, spec: ProcessSpec) -> bool:
    """True if ``pid`` runs our engine command (guards against a recycled pid)."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    args = [a.decode(errors="replace") for a in cmdline if a]
    return bool(args) and any(str(part) in args for part in list(spec.command)[1:2])
