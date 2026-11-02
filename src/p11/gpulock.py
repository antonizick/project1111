"""Advisory GPU lock (spec R24, ADR-0014): ``flock`` on ``~/.cache/p11/gpu.lock``."""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from p11 import paths


class GpuLockTimeout(TimeoutError):
    """Raised when the lock is still held after ``timeout`` seconds."""

    def __init__(self, holder: dict[str, object] | None, timeout: float) -> None:
        self.holder = holder
        who = (
            f"pid {holder.get('pid')} ({holder.get('holder')}), since {holder.get('started')}"
            if holder
            else "unknown holder"
        )
        super().__init__(f"GPU is busy: held by {who}. Waited {timeout:g}s.")


def read_holder(path: Path | None = None) -> dict[str, object] | None:
    """Return the recorded holder info, or None if the file is empty or unreadable."""
    path = path or paths.gpu_lock_file()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@contextmanager
def gpu_lock(timeout: float = 0.0, holder: str = "p11", path: Path | None = None) -> Iterator[None]:
    """Hold the GPU lock; wait up to ``timeout`` seconds, else raise ``GpuLockTimeout``."""
    path = path or paths.gpu_lock_file()
    paths.ensure_private_dir(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise GpuLockTimeout(read_holder(path), timeout) from None
                time.sleep(0.05)
        info = {
            "pid": os.getpid(),
            "holder": holder,
            "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps(info).encode(), 0)
        try:
            yield
        finally:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
