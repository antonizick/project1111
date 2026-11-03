"""Read ``engine/engine.lock.toml`` (spec S3): the pinned ComfyUI version and launch flags."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from p11 import paths

LOCK_NAME = "engine.lock.toml"


@dataclass(frozen=True)
class EngineLock:
    tag: str
    commit: str
    listen: str
    port: int
    flags: tuple[str, ...]
    path: Path

    @property
    def version(self) -> str:
        """The ``comfyui_version`` the pinned engine reports in ``/system_stats``."""
        return self.tag.removeprefix("v")


def find_lock_file() -> Path:
    """``$P11_ENGINE_LOCK``, else the repo's ``engine/``, else the data-dir copy."""
    override = os.environ.get("P11_ENGINE_LOCK")
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[3] / "engine" / LOCK_NAME
    if repo.exists():
        return repo
    return paths.data_dir() / "engine" / LOCK_NAME


def load_lock(path: Path | None = None) -> EngineLock:
    path = path or find_lock_file()
    data = tomllib.loads(path.read_text())
    launch = data["launch"]
    return EngineLock(
        tag=str(data["comfyui"]["tag"]),
        commit=str(data["comfyui"]["commit"]),
        listen=str(launch["listen"]),
        port=int(launch["port"]),
        flags=tuple(str(f) for f in launch["flags"]),
        path=path,
    )
