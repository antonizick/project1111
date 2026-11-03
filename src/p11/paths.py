"""XDG path resolution for P11 (spec R8). ``P11_*`` environment variables override for tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP = "p11"


def _xdg(env: str, default: str) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else Path.home() / default


def config_dir() -> Path:
    override = os.environ.get("P11_CONFIG_DIR")
    return Path(override) if override else _xdg("XDG_CONFIG_HOME", ".config") / APP


def data_dir() -> Path:
    override = os.environ.get("P11_DATA_DIR")
    return Path(override) if override else _xdg("XDG_DATA_HOME", ".local/share") / APP


def cache_dir() -> Path:
    override = os.environ.get("P11_CACHE_DIR")
    return Path(override) if override else _xdg("XDG_CACHE_HOME", ".cache") / APP


def pictures_dir() -> Path:
    override = os.environ.get("P11_PICTURES_DIR")
    if override:
        return Path(override)
    return _xdg("XDG_PICTURES_DIR", "Pictures") / "P11"


def config_file() -> Path:
    return config_dir() / "config.toml"


def gpu_lock_file() -> Path:
    return cache_dir() / "gpu.lock"


def runtime_dir() -> Path:
    """Per-login runtime files (session token, studio state): ``$XDG_RUNTIME_DIR/p11``."""
    override = os.environ.get("P11_RUNTIME_DIR")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / APP if runtime else cache_dir() / "run"


def logs_dir() -> Path:
    return cache_dir() / "logs"


def inputs_dir() -> Path:
    """Validated uploads (S6, S8): generated names only, ``0700``."""
    return data_dir() / "inputs"


def gallery_db() -> Path:
    """The SQLite gallery index (a cache of the sidecars, spec R7)."""
    return data_dir() / "gallery.db"


def jobs_db() -> Path:
    """The SQLite job table, so a restart shows interrupted jobs."""
    return data_dir() / "jobs.db"


@dataclass(frozen=True)
class Paths:
    config: Path
    data: Path
    cache: Path
    pictures: Path
    engine: Path
    models: Path
    gpu_lock: Path


def resolve() -> Paths:
    data = data_dir()
    return Paths(
        config=config_dir(),
        data=data,
        cache=cache_dir(),
        pictures=pictures_dir(),
        engine=data / "engine",
        models=data / "models",
        gpu_lock=gpu_lock_file(),
    )


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (and parents) and make it ``0700``; returns the path."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path
