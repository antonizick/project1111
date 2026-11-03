"""The Engine contract suite against FakeEngine and against ComfyEngine over a mock ComfyUI."""

from __future__ import annotations

import os
import signal
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from tests.engine_contract import CHECKS, Harness

from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.engine.fake import FakeConfig, FakeEngine
from p11.engine.lockfile import load_lock

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "tests/fixtures/mock_comfyui.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def mock_engine_dir(root: Path) -> Path:
    """An engine dir whose ``venv/bin/python main.py`` starts the mock ComfyUI."""
    bindir = root / "venv/bin"
    bindir.mkdir(parents=True)
    py = bindir / "python"
    py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    py.chmod(0o755)
    comfy = root / "ComfyUI"
    comfy.mkdir()
    (comfy / "main.py").write_text(
        f"import runpy, sys\nsys.path.insert(0, {str(REPO)!r})\n"
        f"runpy.run_path({str(MOCK)!r}, run_name='__main__')\n"
    )
    return root


def mock_config(tmp: Path, **overrides: object) -> EngineConfig:
    base = EngineConfig(
        engine_dir=mock_engine_dir(tmp / "engine"),
        scratch_dir=tmp / "scratch",
        log_path=tmp / "logs/engine.log",
        pid_path=tmp / "engine.pid",
        lock=load_lock(),
        port=free_port(),
        lock_path=tmp / "gpu.lock",
        ready_timeout=30.0,
        stop_timeout=5.0,
        free_settle=0.0,
    )
    from dataclasses import replace

    return replace(base, **overrides)  # type: ignore[arg-type]


@pytest.fixture(params=["fake", "mock-comfy"])
async def harness(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Harness]:
    if request.param == "fake":
        fake = FakeEngine(FakeConfig(step_delay=0.01))
        await fake.start()

        async def kill_fake() -> None:
            fake.crash()

        yield Harness(fake, kill_fake)
        await fake.stop()
        return
    engine = ComfyEngine(mock_config(tmp_path))
    await engine.start()

    async def kill_mock() -> None:
        pid = engine.supervisor.pid
        assert pid is not None
        os.killpg(pid, signal.SIGKILL)

    try:
        yield Harness(engine, kill_mock)
    finally:
        await engine.aclose()


@pytest.mark.parametrize("check", sorted(CHECKS))
async def test_contract(harness: Harness, check: str) -> None:
    await CHECKS[check](harness)


async def test_mock_lowvram_flag_and_free(tmp_path: Path) -> None:
    engine = ComfyEngine(mock_config(tmp_path))
    await engine.start()
    try:
        await engine.free_memory(unload_models=True)
        await engine.restart("lowvram")
        async with httpx.AsyncClient(base_url=engine.base_url) as c:
            state = (await c.get("/mock/state")).json()
        assert state["vram_mode"] == "lowvram"
        assert "--lowvram" in (await engine.system_stats()).argv
    finally:
        await engine.aclose()
