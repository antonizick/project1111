"""The running Studio: settings, engine, stores and the job queue, shared by every route.

SQLite connections are opened in the app's lifespan (the event-loop thread) and only used from
async routes on that thread. Blocking work (model hashing, thumbnails, video probing) runs in
worker threads and never touches the connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from p11 import paths
from p11.config import Settings
from p11.engine.base import Engine
from p11.gpu.telemetry import GpuSample, GpuSampler, ThermalGuard
from p11.jobs.events import EventBus
from p11.jobs.queue import JobQueue, ThermalWatch
from p11.jobs.runner import Runner
from p11.jobs.store import JobStore
from p11.media.control import Controls
from p11.media.faces import FaceKit
from p11.media.inputs import InputStore
from p11.media.segment import Segmenters, Segments
from p11.outputs.index import GalleryIndex
from p11.recipe.model import Generate, Recipe
from p11.recipe.registry import ModelRegistry
from p11.templates.starter import install_starters
from p11.templates.store import TemplateStore

from .security import Session

log = logging.getLogger("p11.studio")
GPU_INTERVAL = 1.0


@dataclass(frozen=True)
class StudioPaths:
    outputs: Path
    data: Path
    templates: Path

    @classmethod
    def real(cls, settings: Settings) -> StudioPaths:
        return cls(settings.outputs_root, paths.data_dir(), paths.config_dir() / "templates")

    @classmethod
    def sandbox(cls, root: Path) -> StudioPaths:
        """``--fake`` keeps its demo gallery away from the real one."""
        return cls(root / "pictures", root / "data", root / "templates")


def gpu_json(sample: GpuSample) -> dict[str, object]:
    return {
        "vram_used_mib": sample.vram_used_mib,
        "vram_total_mib": sample.vram_total_mib,
        "temp_c": sample.temp_c,
        "power_w": sample.power_w,
        "sm_clock_mhz": sample.sm_clock_mhz,
        "throttle_reasons": list(sample.throttle_reasons),
        "thermal_throttled": sample.thermal_throttled,
    }


@dataclass
class Studio:
    settings: Settings
    engine: Engine
    session: Session
    registry: Callable[[], ModelRegistry]
    paths: StudioPaths
    port: int
    fake: bool = False
    sampler: GpuSampler | None = None
    #: Seconds without jobs before the engine is stopped (frees the GPU lock).
    idle_stop: float = 300.0
    seed_demo: bool = False
    #: Install the bundled starter templates on first run (Phase 09).
    starters: bool = False
    #: Subject segmentation for background replacement (ADR-0026); ``--fake`` uses the stub.
    segmenters: Segments = field(default_factory=Segmenters)
    #: Face tools and the S5 guard (ADR-0028/0029); ``--fake`` uses the stubs.
    faces: FaceKit = field(default_factory=FaceKit)
    #: Pose/depth maps for ``pose`` steps (ADR-0030); ``--fake`` uses the stubs.
    controls: Controls = field(default_factory=Controls)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    bus: EventBus = field(default_factory=EventBus)
    inputs: InputStore = field(init=False)
    templates: TemplateStore = field(init=False)
    # Opened in ``open()``:
    gallery: GalleryIndex = field(init=False)
    jobs: JobStore = field(init=False)
    queue: JobQueue = field(init=False)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    last_gpu: GpuSample | None = None

    def __post_init__(self) -> None:
        self.inputs = InputStore(self.paths.data / "inputs")
        self.templates = TemplateStore(self.paths.templates)

    async def open(self) -> None:
        paths.ensure_private_dir(self.paths.data)
        paths.ensure_private_dir(self.paths.outputs)
        self.gallery = GalleryIndex(self.paths.data / "gallery.db")
        self.jobs = JobStore(self.paths.data / "jobs.db")
        runner = Runner(
            engine=self.engine,
            registry=self.registry,
            outputs_root=self.paths.outputs,
            gallery=self.gallery,
            inputs=self.inputs,
            segmenters=self.segmenters,
            faces=self.faces,
            controls=self.controls,
        )
        guard = ThermalGuard(self.settings.thermal_pause_c, self.settings.thermal_resume_c)
        self.queue = JobQueue(
            self.jobs,
            runner,
            self.bus,
            thermal=ThermalWatch(self.sampler, guard) if self.sampler else None,
            idle_stop=self.idle_stop,
        )
        if self.starters:
            await asyncio.to_thread(install_starters, self.templates)
        await self.queue.start()
        if self.sampler is not None:
            self._tasks.append(asyncio.create_task(self._gpu_loop(), name="p11-gpu"))
        if self.seed_demo and self.gallery.count() == 0:
            for recipe in demo_recipes():
                self.queue.submit(recipe.model_dump(mode="json"), {}, template="demo")
        log.info("studio open", extra={"port": self.port, "fake": self.fake})

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.queue.stop()
        self.gallery.close()
        self.jobs.close()
        if self.sampler is not None:
            with contextlib.suppress(Exception):
                self.sampler.close()
        log.info("studio closed")

    async def gpu_sample(self) -> GpuSample | None:
        if self.sampler is None:
            return None
        try:
            self.last_gpu = await asyncio.to_thread(self.sampler.sample)
        except Exception:
            return self.last_gpu
        return self.last_gpu

    async def _gpu_loop(self) -> None:
        """GPU samples at ≤ 1 Hz, only while a browser is listening (R14)."""
        while True:
            if self.bus.subscribers:
                sample = await self.gpu_sample()
                if sample is not None:
                    self.bus.publish("gpu", gpu_json(sample))
            await asyncio.sleep(GPU_INTERVAL)


DEMO_PROMPTS = (
    ("a lighthouse on a rocky coast at dusk", "photoreal", "16:9-1920x1080"),
    ("snow-capped mountains above a misty valley at sunrise", "photoreal", "16:9-2560x1440"),
    ("a quiet city street after rain, neon reflections", "photoreal", "16:9-1920x1080"),
    ("a smiling astronaut with a big head", "3d-animated-avatar", None),
    ("a paper plane", "logo-flat", None),
    ("a fox made of folded paper", "logo-3d", None),
)


def demo_recipes() -> list[Recipe]:
    """Synthetic prompts for the ``--fake`` demo gallery (no people, no brands; S6, H14)."""
    return [
        Recipe.new(f"Demo: {prompt}", [Generate(prompt=prompt, style=style, aspect=aspect)])
        for prompt, style, aspect in DEMO_PROMPTS
    ]
