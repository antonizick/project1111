"""ProcessSupervisor with a dummy subprocess: readiness, crash restart, double start, clean stop."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from p11.engine.base import EngineCrashed, EngineUnavailable
from p11.engine.process import ProcessSpec, ProcessSupervisor, pid_alive, rotate_log
from p11.gpulock import GpuLockTimeout, gpu_lock

DUMMY = Path(__file__).resolve().parents[1] / "fixtures/dummy_engine.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def make_spec(tmp: Path, port: int | None = None, **env: str) -> ProcessSpec:
    return ProcessSpec(
        command=[sys.executable, str(DUMMY), "--port", str(port or free_port())],
        cwd=tmp,
        port=port or 0,
        log_path=tmp / "logs/engine.log",
        pid_path=tmp / "engine.pid",
        env=env,
        lock_path=tmp / "gpu.lock",
        lock_timeout=0.5,
        ready_timeout=10.0,
        stop_timeout=1.0,
    )


def spec_for(tmp: Path, **env: str) -> ProcessSpec:
    port = free_port()
    spec = make_spec(tmp, port, **env)
    spec.port = port
    return spec


def ready_check(spec: ProcessSpec):  # type: ignore[no-untyped-def]
    async def ready() -> bool:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"http://127.0.0.1:{spec.port}/system_stats", timeout=1)
            return r.status_code == 200

    return ready


@pytest.fixture
async def sup(tmp_path: Path) -> AsyncIterator[ProcessSupervisor]:
    spec = spec_for(tmp_path, DUMMY_MARK=str(tmp_path / "starts"))
    s = ProcessSupervisor(spec, ready_check(spec))
    yield s
    await s.stop()


async def wait_for(cond, timeout: float = 10.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


def starts(tmp: Path) -> int:
    f = tmp / "starts"
    return len(f.read_text().splitlines()) if f.exists() else 0


async def test_start_waits_for_ready_and_holds_gpu_lock(
    sup: ProcessSupervisor, tmp_path: Path
) -> None:
    sup.spec.env["DUMMY_READY_DELAY"] = "0.5"
    await sup.start()
    assert sup.state == "ready" and sup.running and sup.holds_gpu_lock
    assert sup.spec.pid_path.exists()
    assert "dummy engine listening" in sup.spec.log_path.read_text()
    assert sup.spec.log_path.stat().st_mode & 0o777 == 0o600  # private like the Studio log (S6)
    with pytest.raises(GpuLockTimeout), gpu_lock(0, path=tmp_path / "gpu.lock"):
        pass
    await sup.start()  # idempotent
    assert starts(tmp_path) == 1


async def test_clean_stop_leaves_nothing(sup: ProcessSupervisor, tmp_path: Path) -> None:
    await sup.start()
    pid = sup.pid
    assert pid is not None
    await sup.stop()
    assert not pid_alive(pid)
    assert not sup.spec.pid_path.exists()
    assert sup.state == "stopped" and not sup.holds_gpu_lock
    with gpu_lock(0, path=tmp_path / "gpu.lock"):
        pass


async def test_stop_escalates_to_sigkill(sup: ProcessSupervisor) -> None:
    sup.spec.env["DUMMY_IGNORE_TERM"] = "1"
    await sup.start()
    pid = sup.pid
    assert pid is not None
    t0 = time.monotonic()
    await sup.stop()
    assert not pid_alive(pid)
    assert 0.9 < time.monotonic() - t0 < 5


async def test_crash_restarts_once_then_gives_up(sup: ProcessSupervisor, tmp_path: Path) -> None:
    sup.spec.env["DUMMY_EXIT_AFTER"] = "0.5"
    crashes: list[int | None] = []
    sup.on_crash = crashes.append
    await sup.start()
    await wait_for(lambda: starts(tmp_path) == 2 and sup.state == "ready")
    assert sup.restarts == 1
    await wait_for(lambda: sup.state == "crashed" and len(crashes) == 2)
    assert crashes == [3, 3]
    assert starts(tmp_path) == 2  # no second restart
    assert not sup.holds_gpu_lock and not sup.spec.pid_path.exists()
    with pytest.raises(EngineCrashed, match="restarts it once"):
        sup.raise_if_dead()
    # An explicit restart brings it back (and takes the lock again).
    sup.spec.env.pop("DUMMY_EXIT_AFTER")
    await sup.restart()
    assert sup.state == "ready" and sup.holds_gpu_lock


async def test_exit_during_startup_is_unavailable(sup: ProcessSupervisor) -> None:
    sup.spec.env["DUMMY_EXIT_NOW"] = "1"
    with pytest.raises(EngineUnavailable, match="exited during start-up"):
        await sup.start()
    assert sup.state == "stopped" and not sup.holds_gpu_lock


async def test_ready_timeout(sup: ProcessSupervisor) -> None:
    sup.spec.env["DUMMY_READY_DELAY"] = "30"
    sup.spec.ready_timeout = 0.5
    with pytest.raises(EngineUnavailable, match="did not become ready"):
        await sup.start()
    assert not sup.running


async def test_double_start_refused_by_pid_file(sup: ProcessSupervisor, tmp_path: Path) -> None:
    await sup.start()
    other_spec = spec_for(tmp_path)
    other_spec.pid_path = sup.spec.pid_path
    other_spec.lock_path = None
    other = ProcessSupervisor(other_spec, ready_check(other_spec))
    with pytest.raises(EngineUnavailable, match="already running"):
        await other.start()


async def test_double_start_refused_by_port(sup: ProcessSupervisor, tmp_path: Path) -> None:
    await sup.start()
    other_spec = spec_for(tmp_path / "x")
    other_spec.port = sup.spec.port
    other_spec.lock_path = None
    other = ProcessSupervisor(other_spec, ready_check(other_spec))
    with pytest.raises(EngineUnavailable, match="already in use"):
        await other.start()


async def test_stale_pid_file_is_ignored(sup: ProcessSupervisor) -> None:
    sup.spec.pid_path.write_text('{"pid": 999999999, "port": 1}')
    await sup.start()
    assert sup.state == "ready"


async def test_gpu_lock_busy_is_unavailable(sup: ProcessSupervisor, tmp_path: Path) -> None:
    busy = pytest.raises(EngineUnavailable, match="GPU is busy")
    with gpu_lock(0, holder="other job", path=tmp_path / "gpu.lock"), busy:
        await sup.start()
    assert not sup.running


async def test_restart_keeps_lock(sup: ProcessSupervisor, tmp_path: Path) -> None:
    await sup.start()
    first = sup.pid
    await sup.restart()
    assert sup.pid != first and sup.state == "ready" and sup.holds_gpu_lock
    assert first is not None and not pid_alive(first)
    assert sup.restarts == 0


def test_rotate_log(tmp_path: Path) -> None:
    log = tmp_path / "engine.log"
    rotate_log(log)  # missing: no-op
    for i in range(5):
        log.write_bytes(b"x" * (20 + i))
        rotate_log(log, keep=3, max_bytes=10)
    assert not log.exists()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["engine.log.1", "engine.log.2", "engine.log.3"]
    assert (tmp_path / "engine.log.1").stat().st_size == 24
    log.write_bytes(b"small")
    rotate_log(log, keep=3, max_bytes=10)
    assert log.exists()


def test_pid_alive() -> None:
    assert pid_alive(os.getpid())
    assert not pid_alive(999999999)
