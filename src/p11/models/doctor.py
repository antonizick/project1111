"""Model health checks for ``p11 doctor`` (Task 8; wired into the CLI by Phase 07)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from p11.problems import Problem

from .download import human_size
from .registry import ModelManager

#: Below this much free space on the models disk, ``check`` warns.
LOW_DISK = 10 * 1000**3


def check(
    manager: ModelManager | None = None,
    *,
    free_space: Callable[[Path], int] | None = None,
) -> list[Problem]:
    """Missing default models, corrupt files (by size, and by hash where already cached), low disk.

    Cheap enough for every ``p11 doctor`` run: it never re-hashes a file whose size and mtime are
    unchanged since the last verification. ``p11 models verify`` does the full check.
    """
    manager = manager or ModelManager.from_settings()
    problems: list[Problem] = []
    for s in manager.statuses(include_unregistered=False):
        if s.state == "missing" and "default" in s.sets:
            problems.append(
                Problem(
                    "error",
                    "models.missing-default",
                    f"Default model {s.name} ({s.id}) is not installed.",
                    "Run `p11 models install default`.",
                )
            )
        elif s.state == "missing" and s.origin == "user":
            problems.append(
                Problem(
                    "warning",
                    "models.user-missing",
                    f"User model {s.id}: {s.detail}.",
                    f"Put the file back or run `p11 models remove {s.id}`.",
                )
            )
        elif s.state == "corrupt":
            problems.append(
                Problem(
                    "error",
                    "models.corrupt",
                    f"Model {s.id} is damaged ({s.detail}).",
                    f"Run `p11 models install {s.id}` to replace it."
                    if s.origin == "manifest"
                    else f"Re-add it or run `p11 models remove {s.id}`.",
                )
            )
        elif s.format in ("pickle", "torch-zip"):
            problems.append(
                Problem(
                    "warning",
                    "models.pickle",
                    f"User model {s.id} is a pickle-based file, which can run code when loaded.",
                    "Prefer a .safetensors version of it.",
                )
            )
    root = manager.root
    probe = root if root.exists() else next((p for p in root.parents if p.exists()), Path("/"))
    free = (free_space or (lambda p: shutil.disk_usage(p).free))(probe)
    if free < LOW_DISK:
        problems.append(
            Problem(
                "warning",
                "models.disk-low",
                f"Only {human_size(free)} free on the models disk ({probe}).",
                "Free some space or move models_root to a bigger disk (config.toml).",
            )
        )
    return problems
