"""The Studio's job queue: one GPU worker, persisted jobs, cancel, thermal pause, idle engine stop.

* One worker task runs jobs in submission order, so at most one job uses the GPU. The engine
  supervisor holds the GPU lock (R24) while the engine runs; the worker starts the engine lazily
  for the first job and stops it after ``idle_stop`` seconds without work, so other sessions'
  GPU work does not wait on an idle Studio.
* After an OOM retry the engine stays in low-VRAM mode (ADR-0020); once the queue has been idle
  for ``lowvram_reset`` seconds the worker restarts it in the faster dynamic mode (ADR-0022).
* Jobs are rows in ``jobs.db``; on startup any job left queued/running/paused is marked failed
  with ``job.interrupted``.
* Long jobs (several runs or steps) check the ``ThermalWatch`` between graphs and sit in
  ``paused`` while the GPU is above the pause threshold (R14, H9). Phase 13 uses the same hook.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from p11.engine.base import Engine, EngineInterrupted
from p11.gpu.telemetry import GpuSampler, ThermalGuard
from p11.recipe.migrate import migrate

from .errors import problem_for
from .events import EventBus
from .runner import JobControl, Runner, parse_bindings
from .store import FINISHED, Job, JobError, JobState, JobStore

log = logging.getLogger("p11.jobs")

MAX_COUNT = 16
QUEUE_LIMIT = 100


class QueueFull(RuntimeError):
    pass


class ThermalWatch:
    """Wait while the GPU is hot, with ``ThermalGuard``'s hysteresis (H9: 87 °C / 80 °C)."""

    def __init__(
        self, sampler: GpuSampler | None, guard: ThermalGuard, *, poll: float = 5.0
    ) -> None:
        self.sampler = sampler
        self.guard = guard
        self.poll = poll

    async def _temp(self) -> float | None:
        if self.sampler is None:
            return None
        try:
            return float((await asyncio.to_thread(self.sampler.sample)).temp_c)
        except Exception:  # telemetry trouble must never stop a job
            return None

    async def wait(
        self,
        control: JobControl,
        on_pause: Callable[[float], None],
        on_resume: Callable[[], None],
    ) -> None:
        temp = await self._temp()
        if temp is None or self.guard.update(temp) != "paused":
            return
        on_pause(temp)
        while not control.cancelled:
            await asyncio.sleep(self.poll)
            temp = await self._temp()
            if temp is None or self.guard.update(temp) == "ok":
                break
        on_resume()


class JobQueue:
    def __init__(
        self,
        store: JobStore,
        runner: Runner,
        bus: EventBus,
        *,
        thermal: ThermalWatch | None = None,
        idle_stop: float = 300.0,
        lowvram_reset: float = 60.0,
    ) -> None:
        self.store = store
        self.runner = runner
        self.bus = bus
        self.thermal = thermal
        self.idle_stop = idle_stop
        self.lowvram_reset = lowvram_reset
        self._pending: deque[str] = deque()
        self._wake = asyncio.Event()
        self._jobs: dict[str, Job] = {}
        self._controls: dict[str, JobControl] = {}
        self._task: asyncio.Task[None] | None = None
        self.current: str | None = None
        self.interrupted: list[str] = []

    @property
    def engine(self) -> Engine:
        return self.runner.engine

    # -- lifecycle ---------------------------------------------------------------------------

    async def start(self) -> None:
        self.interrupted = self.store.mark_interrupted()
        if self.interrupted:
            log.info("marked interrupted jobs", extra={"count": len(self.interrupted)})
        self._task = asyncio.create_task(self._worker(), name="p11-job-worker")

    async def stop(self) -> None:
        for control in self._controls.values():
            control.cancel()
        if self.current is not None:
            with contextlib.suppress(Exception):
                await self.engine.interrupt()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        with contextlib.suppress(Exception):
            await self.engine.stop()

    # -- API ---------------------------------------------------------------------------------

    def submit(
        self,
        recipe: dict[str, Any],
        bindings: dict[str, Any],
        *,
        count: int = 1,
        template: str | None = None,
        parent: str | None = None,
    ) -> Job:
        """Validate (compile + file check) and queue; raises the typed error for a 4xx."""
        if not 1 <= count <= MAX_COUNT:
            raise ValueError(f"count must be between 1 and {MAX_COUNT}")
        if len(self._pending) >= QUEUE_LIMIT:
            raise QueueFull(f"{QUEUE_LIMIT} jobs are already waiting.")
        parsed = migrate(recipe)
        self.runner.validate(parsed, parse_bindings(bindings))
        job = Job(
            id=uuid.uuid4().hex,
            state="queued",
            recipe=parsed.model_dump(mode="json"),
            bindings=dict(bindings),
            count=count,
            template=template,
            parent=parent,
        )
        job = self._save(job)
        self._pending.append(job.id)
        self._wake.set()
        log.info("job queued", extra={"job": job.id, "count": count})
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id) or self.store.get(job_id)

    def recent(self, limit: int = 50) -> list[Job]:
        stored = self.store.recent(limit)
        return [self._jobs.get(j.id, j) for j in stored]

    @property
    def waiting(self) -> int:
        return len(self._pending)

    async def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None or job.state in FINISHED:
            return job
        if job.state == "queued" and job_id in self._pending:
            self._pending.remove(job_id)
            return self._save(replace(job, state="cancelled", note=None))
        control = self._controls.get(job_id)
        if control is not None:
            control.cancel()
            await self.engine.interrupt()
        return self.get(job_id)

    # -- worker ------------------------------------------------------------------------------

    def _save(self, job: Job, *, persist: bool = True) -> Job:
        if persist:
            job = self.store.put(job)
        if job.state in FINISHED:
            self._jobs.pop(job.id, None)
        else:
            self._jobs[job.id] = job
        self.bus.publish("job", job.summary())
        return job

    async def _idle(self) -> None:
        """Wait for work; meanwhile reset low-VRAM mode and stop the idle engine."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        reset_due = self.engine.vram_mode == "lowvram"
        stopped = False
        while not self._pending:
            self._wake.clear()
            elapsed = loop.time() - started
            marks = [m for m in (self.idle_stop, self.lowvram_reset if reset_due else None)
                     if m is not None and m > elapsed]  # fmt: skip
            timeout = None if stopped or not marks else min(marks) - elapsed
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)
                continue
            except TimeoutError:
                pass
            elapsed = loop.time() - started
            health = await self.engine.health()
            if elapsed >= self.idle_stop:
                stopped = True
                if health.state != "stopped":
                    log.info("stopping idle engine", extra={"idle_s": round(elapsed)})
                    await self._quiet(self.engine.stop())
            elif reset_due and elapsed >= self.lowvram_reset:
                reset_due = False
                if health.ready and self.engine.vram_mode == "lowvram":
                    log.info("engine back to dynamic VRAM mode after an OOM retry")
                    await self._quiet(self.engine.restart("dynamic"))

    @staticmethod
    async def _quiet(aw: Any) -> None:
        try:
            await aw
        except Exception:
            log.exception("engine lifecycle call failed")

    async def _worker(self) -> None:
        while True:
            await self._idle()
            job_id = self._pending.popleft()
            job = self.get(job_id)
            if job is None or job.state != "queued":
                continue
            await self._run(job)

    async def _run(self, job: Job) -> None:
        control = JobControl(self._thermal_hook(job.id) if self.thermal else None)
        self._controls[job.id] = control
        self.current = job.id
        job = self._save(replace(job, state="running"))
        state: JobState = "done"
        error: JobError | None = None
        report = None
        try:
            health = await self.engine.health()
            if not health.ready:
                if health.state == "stopped" and self.engine.vram_mode == "lowvram":
                    await self.engine.restart("dynamic")
                else:
                    await self.engine.start()
            report = await self.runner.run(
                recipe=migrate(job.recipe),
                bindings=parse_bindings(job.bindings),
                count=job.count,
                template=job.template,
                parent=job.parent,
                control=control,
                publish=self.bus.publish,
                job_id=job.id,
                on_progress=lambda p, note: self._progress(job.id, p, note),
            )
        except EngineInterrupted:
            state = "cancelled" if control.cancelled else "failed"
            if state == "failed":
                error = problem_for(EngineInterrupted("interrupted"))[1]
        except asyncio.CancelledError:
            self._save(replace(self.get(job.id) or job, state="failed",
                               error=problem_for(EngineInterrupted())[1]))  # fmt: skip
            raise
        except Exception as exc:
            state = "failed"
            error = problem_for(exc)[1]
            if error.code in ("internal", "engine.execution"):
                log.exception("job failed", extra={"job": job.id, "code": error.code})
            else:
                log.info("job failed", extra={"job": job.id, "code": error.code})
        finally:
            self._controls.pop(job.id, None)
            self.current = None
        latest = self.get(job.id) or job
        images = tuple(report.image_ids) if report else latest.images
        note = latest.note if state == "done" and report and report.retried else None
        self._save(
            replace(latest, state=state, error=error, images=images, note=note,
                    progress=1.0 if state == "done" else latest.progress)
        )  # fmt: skip
        log.info("job finished", extra={"job": job.id, "state": state})

    def _progress(self, job_id: str, progress: float, note: str | None) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        if note is not None:
            self._save(replace(job, progress=progress, note=note))
        else:
            # Step progress goes out as ``progress`` events; keep the row write for state changes.
            self._jobs[job_id] = replace(job, progress=progress)

    def _thermal_hook(self, job_id: str) -> Callable[[JobControl], Any]:
        assert self.thermal is not None
        thermal = self.thermal

        async def hook(control: JobControl) -> None:
            def paused(temp: float) -> None:
                job = self.get(job_id)
                if job:
                    note = f"Paused: the GPU is at {temp:.0f} °C; continuing below "
                    note += f"{thermal.guard.resume_at} °C."
                    self._save(replace(job, state="paused", note=note))

            def resumed() -> None:
                job = self.get(job_id)
                if job and job.state == "paused":
                    self._save(replace(job, state="running", note=None))

            await thermal.wait(control, paused, resumed)

        return hook
