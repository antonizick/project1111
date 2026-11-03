"""The Engine contract suite against the real pinned ComfyUI on the laptop (Phase 05).

Uses the real XDG paths (installed engine, models, GPU lock, ``~/.cache/p11/logs/engine.log``).
Each test starts and stops its own engine; nothing is left running.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from tests.engine_contract import CHECKS, Harness

from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.engine.fake import KNOWN_NODES

DATA = Path.home() / ".local/share/p11"
HOG = Path(__file__).with_name("vram_hog.py")
#: Free VRAM the hog leaves: enough to start a run, too little for the SDXL VAE decode (probed
#: 2026-11-02 19:05 CST: 1500 MiB still fits, 600 MiB runs out in VAEDecode).
HOG_LEAVE_MIB = 600

pytestmark = pytest.mark.gpu


def _require_install() -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    if not (DATA / "models/checkpoints/RealVisXL_V5.0_Lightning_fp16.safetensors").exists():
        pytest.skip("default-set model missing")


class Hog:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None

    async def start(self) -> None:
        self.proc = subprocess.Popen(
            [str(DATA / "engine/venv/bin/python"), str(HOG), str(HOG_LEAVE_MIB)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self.proc.stdout is not None
        assert self.proc.stdout.readline().startswith("hog ")

    def release(self) -> None:
        if self.proc and self.proc.poll() is None:
            assert self.proc.stdin is not None
            self.proc.stdin.close()
            self.proc.wait(30)


@pytest.fixture
async def engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ComfyEngine]:
    _require_install()
    for var in ("P11_CONFIG_DIR", "P11_DATA_DIR", "P11_CACHE_DIR", "P11_PICTURES_DIR"):
        monkeypatch.delenv(var, raising=False)
    eng = ComfyEngine(EngineConfig.default(lock_timeout=1800))
    await eng.start()
    try:
        yield eng
    finally:
        pid = eng.supervisor.pid
        await eng.aclose()
        assert pid is None or not Path(f"/proc/{pid}").exists(), "engine left running"


def harness(engine: ComfyEngine, **kw: object) -> Harness:
    async def kill() -> None:
        pid = engine.supervisor.pid
        assert pid is not None
        os.killpg(pid, signal.SIGKILL)

    return Harness(engine, kill, ready_timeout=180.0, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "check",
    [
        "generate",
        "interrupt",
        "upload_img2img",
        "bind_inputs",
        "validation",
        "free_memory",
        "crash_restart",
    ],
)
async def test_contract(engine: ComfyEngine, check: str) -> None:
    await CHECKS[check](harness(engine))


async def test_oom_recovers_after_pressure_is_relieved(engine: ComfyEngine) -> None:
    hog = Hog()
    try:
        await CHECKS["oom_recovery"](
            harness(engine, pressure=hog.start, relieve=hog.release, oom_recovers=True)
        )
    finally:
        hog.release()


async def test_oom_under_lasting_pressure_fails_in_plain_english(engine: ComfyEngine) -> None:
    hog = Hog()
    h = harness(
        engine, pressure=hog.start, relieve=hog.release, relieve_on_retry=False, oom_recovers=False
    )
    try:
        await CHECKS["oom_recovery"](h)
    finally:
        hog.release()


async def test_known_nodes_exist_in_pinned_engine(engine: ComfyEngine) -> None:
    missing = KNOWN_NODES - await engine.node_types()
    assert not missing


async def test_engine_listens_on_loopback_only_and_stays_offline(engine: ComfyEngine) -> None:
    pid = engine.supervisor.pid
    assert pid is not None
    out = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, check=True).stdout
    mine = [ln for ln in out.splitlines() if f"pid={pid}," in ln]
    assert mine, out
    for line in mine:
        local = line.split()[3]
        assert local == f"127.0.0.1:{engine.config.port}", line
    log = engine.config.log_path.read_text(errors="replace")
    urls = set(re.findall(r"https?://[^\s'\"]+", log))
    outbound = {u for u in urls if not u.startswith(("http://127.0.0.1", "http://localhost"))}
    assert not outbound, outbound
