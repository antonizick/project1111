import multiprocessing
import os
import time

import pytest

from p11 import gpulock


# spawn, not fork: earlier tests leave TestClient threads running, and fork() in a threaded
# process is deprecated (Phase 07 follow-up).
mp = multiprocessing.get_context("spawn")


def _hold(path, ready, release):
    with gpulock.gpu_lock(timeout=5, holder="child", path=path):
        ready.set()
        release.wait(10)


def test_contention_names_holder(tmp_path):
    path = tmp_path / "gpu.lock"
    ready, release = mp.Event(), mp.Event()
    proc = mp.Process(target=_hold, args=(path, ready, release))
    proc.start()
    try:
        assert ready.wait(10)
        with (
            pytest.raises(gpulock.GpuLockTimeout) as exc,
            gpulock.gpu_lock(timeout=0.2, holder="me", path=path),
        ):
            pass
        assert exc.value.holder is not None
        assert exc.value.holder["holder"] == "child"
        assert exc.value.holder["pid"] == proc.pid
        assert "child" in str(exc.value)
    finally:
        release.set()
        proc.join(10)


def test_second_waits_then_acquires(tmp_path):
    path = tmp_path / "gpu.lock"
    ready, release = mp.Event(), mp.Event()
    proc = mp.Process(target=_hold, args=(path, ready, release))
    proc.start()
    try:
        assert ready.wait(10)
        release.set()
        start = time.monotonic()
        with gpulock.gpu_lock(timeout=5, holder="me", path=path):
            assert gpulock.read_holder(path)["pid"] == os.getpid()  # type: ignore[index]
        assert time.monotonic() - start < 5
    finally:
        release.set()
        proc.join(10)
