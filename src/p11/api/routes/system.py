"""``/api/presets``, ``/api/models`` and ``/api/system``."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from p11 import __version__
from p11.api.studio import gpu_json
from p11.models.registry import ModelManager
from p11.recipe.presets import ASPECTS, STYLES, AspectPreset, StylePreset

from .deps import StudioDep

router = APIRouter(prefix="/api", tags=["system"])


def _aspect(a: AspectPreset) -> dict[str, Any]:
    return {
        "id": a.id,
        "label": a.label,
        "output": a.output,
        "bucket": a.bucket,
        "chain": a.chain,
        "quality_chain": a.quality_chain,
    }


def _style(s: StylePreset) -> dict[str, Any]:
    return {"id": s.id, "label": s.label, "aspect": s.aspect, "model": s.model, "tags": s.tags}


@router.get("/presets")
async def presets() -> dict[str, Any]:
    return {
        "aspects": [_aspect(a) for a in ASPECTS.values()],
        "styles": [_style(s) for s in STYLES.values()],
    }


def _statuses(root: Path) -> list[dict[str, object]]:
    return [s.as_json() for s in ModelManager(root).statuses()]


@router.get("/models")
async def models(studio: StudioDep) -> list[dict[str, object]]:
    """The same objects as ``p11 models list --json`` (Phase 06)."""
    return await asyncio.to_thread(_statuses, studio.settings.models_root)


def _disk(path: Path) -> dict[str, object]:
    probe = path if path.exists() else next((p for p in path.parents if p.exists()), Path("/"))
    usage = shutil.disk_usage(probe)
    return {"path": str(path), "free": usage.free, "total": usage.total}


@router.get("/system")
async def system(studio: StudioDep) -> dict[str, Any]:
    health = await studio.engine.health()
    sample = await studio.gpu_sample()
    disks = await asyncio.to_thread(
        lambda: {
            "outputs": _disk(studio.paths.outputs),
            "models": _disk(studio.settings.models_root),
            "data": _disk(studio.paths.data),
        }
    )
    return {
        "version": __version__,
        "fake": studio.fake,
        "started_at": studio.started_at,
        "port": studio.port,
        "engine": {**asdict(health), "ready": health.ready},
        "gpu": gpu_json(sample) if sample else None,
        "queue": {"current": studio.queue.current, "waiting": studio.queue.waiting},
        "disk": disks,
    }
